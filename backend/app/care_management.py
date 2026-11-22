"""Care-team access is granted locally; a public registration never grants it."""
from typing import Annotated
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Column, Integer, String, Boolean, Text, ForeignKey, func, select
from .database import Base
from .models import User
from .robot_records import owner, transaction, now, RecordSession, RecordMessage, ResourceID, PageLimit, encode_cursor, decode_cursor, summary
from .care.service import CareError
from .care.report_delivery import read_report


class ReportManager(Base):
    __tablename__ = 'robot_care_report_managers'
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    granted_at = Column(String(32), nullable=False)


class CareFollowup(Base):
    """Legacy rows retained; report viewers have no follow-up editing interface."""
    __tablename__ = 'robot_care_management_followups'
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    is_test = Column(Boolean, primary_key=True)
    state = Column(String(20), nullable=False)
    note = Column(Text, nullable=False)
    updated_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    updated_at = Column(String(32), nullable=False)


class ManagementAudit(Base):
    __tablename__ = 'robot_care_management_audit'
    id = Column(Integer, primary_key=True)
    manager_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    subject_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    session_id = Column(Integer, ForeignKey('robot_record_sessions.id'), nullable=True)
    action = Column(String(32), nullable=False)
    occurred_at = Column(String(32), nullable=False)


def can_manage_reports(db, uid):
    return db.get(ReportManager, uid) is not None


def manager(uid=Depends(owner)):
    with transaction() as db:
        if not can_manage_reports(db, uid):
            raise CareError(403, 'management_access_required')
    return uid


def audit(db, manager_id, action, subject_id=None, session_id=None):
    db.add(ManagementAudit(manager_id=manager_id, action=action, subject_id=subject_id,
                           session_id=session_id, occurred_at=now()))


def record_access(manager_id, action, subject_id=None, session_id=None):
    with transaction(True) as db:
        audit(db, manager_id, action, subject_id, session_id)


def subject(db, uid):
    user = db.get(User, uid)
    if user is None or can_manage_reports(db, uid):
        raise CareError(404, 'not_found')
    return user


def complete_sessions(db, uid, is_test):
    count = select(func.count(RecordMessage.id)).where(
        RecordMessage.recording_session_id == RecordSession.id).correlate(RecordSession).scalar_subquery()
    return db.query(RecordSession).filter_by(user_id=uid, is_test=is_test, state='closed').filter(
        RecordSession.last_sequence_no == count)


def user_view(db, user, is_test):
    reports = complete_sessions(db, user.id, is_test)
    latest = reports.order_by(RecordSession.id.desc()).first()
    return dict(user_id=user.id, username=user.username, is_active=user.is_active,
        report_count=reports.count(), latest_session_id=latest.id if latest else None,
        latest_at=latest.ended_at if latest else None, is_test=is_test)


def queries(request: Request):
    allowed = {'q', 'is_test', 'limit', 'cursor'} if request.url.path.endswith('/users') else {'is_test', 'limit', 'cursor'} if request.url.path.endswith('/sessions') else {'is_test'} if request.method == 'GET' and '/users/' in request.url.path else set()
    if any(k not in allowed or len(request.query_params.getlist(k)) != 1 for k in request.query_params):
        raise CareError(422, 'validation_error')


router = APIRouter(prefix='/api/care-management', tags=['Care report management'], dependencies=[Depends(queries)])


@router.get('/users')
def users(q: Annotated[str, Query(max_length=50)] = '',
          is_test: bool = False, limit: Annotated[PageLimit, Query()] = 20, cursor: str | None = None,
          mid=Depends(manager)):
    with transaction() as db:
        query = db.query(User).filter(~User.id.in_(select(ReportManager.user_id)))
        if q.strip():
            query = query.filter(User.username.contains(q.strip(), autoescape=True))
        scope = f'management:users:reports-only:{is_test}:{q}'
        snapshot, after = decode_cursor(cursor, mid, scope) if cursor else (query.with_entities(func.max(User.id)).scalar() or 0, None)
        query = query.filter(User.id <= snapshot)
        if after is not None:
            query = query.filter(User.id < after)
        rows = query.order_by(User.id.desc()).limit(limit + 1).all()
        items = [user_view(db, user, is_test) for user in rows]
        more = len(items) > limit
        items = items[:limit]
        value = dict(items=items, next_cursor=encode_cursor(mid, scope, snapshot, items[-1]['user_id']) if more else None)
    record_access(mid, 'list_users')
    return value


@router.get('/users/{uid}')
def user_detail(uid: ResourceID, is_test: bool = False, mid=Depends(manager)):
    with transaction() as db:
        value = user_view(db, subject(db, uid), is_test)
    record_access(mid, 'read_user', uid)
    return value


@router.get('/users/{uid}/sessions')
def user_sessions(uid: ResourceID, is_test: bool = False, limit: Annotated[PageLimit, Query()] = 20,
                  cursor: str | None = None, mid=Depends(manager)):
    with transaction() as db:
        subject(db, uid)
        query = complete_sessions(db, uid, is_test)
        scope = f'management:reports-only:sessions:{uid}:{is_test}'
        snapshot, after = decode_cursor(cursor, mid, scope) if cursor else (query.with_entities(func.max(RecordSession.id)).scalar() or 0, None)
        query = query.filter(RecordSession.id <= snapshot)
        if after is not None:
            query = query.filter(RecordSession.id < after)
        rows = query.order_by(RecordSession.id.desc()).limit(limit + 1).all()
        more = len(rows) > limit
        rows = rows[:limit]
        value = dict(items=[summary(db, row) for row in rows],
                    next_cursor=encode_cursor(mid, scope, snapshot, rows[-1].id) if more else None)
    record_access(mid, 'list_reports', uid)
    return value


def report_owner(db, sid):
    row = db.get(RecordSession, sid)
    if row is None or row.state == 'deleted':
        raise CareError(404, 'not_found')
    subject(db, row.user_id)
    return row.user_id


@router.get('/reports/{sid}')
def report_detail(sid: ResourceID, mid=Depends(manager)):
    with transaction() as db:
        uid = report_owner(db, sid)
        value, _ = read_report(db, uid, sid)
    record_access(mid, 'read_report', uid, sid)
    return dict(report=value, user_id=uid)


def install(app):
    app.include_router(router)

    @app.middleware('http')
    async def private_reports(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith('/api/care-management') or request.url.path == '/api/auth/me':
            response.headers['Cache-Control'] = 'no-store'
        return response
