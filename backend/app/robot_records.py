"""Immutable robot records. No imports of coordinator, model services or chat routes.

All writers acquire SQLite's database write reservation BEFORE inspecting state.
Unique constraints are the final guard; statistics are read from committed rows.
"""
import base64
import hashlib
import hmac
import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field, BeforeValidator
from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, UniqueConstraint, CheckConstraint, func, text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from .database import Base, SessionLocal, get_db
from .auth import get_current_user
from .config import SECRET_KEY

PREFIX = '/api/robot-records'
from robot_client.schemas import SessionCreate, MessageCreate, SessionClose

def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')

class RecordSession(Base):
    __tablename__ = 'robot_record_sessions'
    __table_args__ = (
        UniqueConstraint('user_id', 'source', 'external_session_id', name='uq_robot_owner_source_external'),
        CheckConstraint("state IN ('open','closed','deleted')"),
        {'sqlite_autoincrement': True},
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    source = Column(String(32), nullable=False)
    external_session_id = Column(String(128), nullable=False)
    device_id = Column(String(128))
    started_at = Column(String(32))
    is_test = Column(Boolean)
    state = Column(String(16), nullable=False, default='open')
    created_at = Column(String(32))
    ended_at = Column(String(32))
    last_sequence_no = Column(Integer)
    deleted_at = Column(String(32))

class RecordMessage(Base):
    __tablename__ = 'robot_record_messages'
    __table_args__ = (
        UniqueConstraint('recording_session_id', 'external_message_id', name='uq_robot_message_external'),
        UniqueConstraint('recording_session_id', 'sequence_no', name='uq_robot_message_sequence'),
        CheckConstraint('sequence_no BETWEEN 1 AND 2147483647'),
        {'sqlite_autoincrement': True},
    )
    id = Column(Integer, primary_key=True)
    recording_session_id = Column(Integer, ForeignKey('robot_record_sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    external_message_id = Column(String(128), nullable=False)
    turn_id = Column(String(128))
    sequence_no = Column(Integer, nullable=False)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    occurred_at = Column(String(32), nullable=False)
    text_status = Column(String(16), nullable=False)
    playback_status = Column(String(24), nullable=False)
    received_at = Column(String(32), nullable=False)

class RecordError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code

MESSAGES = {
    'authentication_required': 'Bearer authentication required', 'invalid_token': 'Invalid credentials',
    'account_disabled': 'Account disabled', 'not_found': 'Resource not found',
    'session_conflict': 'Immutable session fields differ', 'message_conflict': 'Immutable message fields differ',
    'sequence_conflict': 'Sequence already used', 'close_conflict': 'Close metadata conflicts',
    'session_closed': 'Sequence exceeds close boundary', 'session_deleted': 'Session deleted',
    'validation_error': 'Invalid request fields', 'invalid_cursor': 'Invalid or mismatched cursor',
    'storage_busy': 'Storage temporarily unavailable; retry later',
}

def error_response(status, code, details=None):
    error = {'code': code, 'message': MESSAGES[code], 'retryable': status == 503}
    if details is not None:
        error['details'] = details
    return JSONResponse(status_code=status, content={'error': error},
                        headers={'WWW-Authenticate': 'Bearer'} if status == 401 else None)

def install_handlers(app):
    @app.exception_handler(RecordError)
    async def record_error(request, exc):
        return error_response(exc.status, exc.code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path.startswith((PREFIX, '/api/robot-insights')):
            # Never echo rejected content, password, token or Pydantic input/context.
            return error_response(422, 'validation_error', [
                {'loc': [part if type(part) is int or part in {'body','query','path','sid','record_id','job_id','policy_id','delivery_id','limit','cursor','scope','session_ids','time_from','time_to','from','to','request_id','base_revision','content','source','device_id','external_session_id','started_at','is_test','external_message_id','turn_id','sequence_no','role','occurred_at','text_status','playback_status','ended_at','last_sequence_no'} else '*' for part in e['loc']], 'type': e['type']} for e in exc.errors()
            ])
        from fastapi.exception_handlers import request_validation_exception_handler
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(SQLAlchemyError)
    async def storage_error(request, exc):
        if request.url.path.startswith((PREFIX, '/api/robot-insights')):
            return error_response(503, 'storage_busy')
        return JSONResponse(status_code=500, content={'detail': 'Storage error'})

bearer = HTTPBearer(auto_error=False)
def owner(credentials=Depends(bearer), db=Depends(get_db)):
    if credentials is None:
        raise RecordError(401, 'authentication_required')
    try:
        return get_current_user(credentials, db).id
    except HTTPException as exc:
        raise RecordError(exc.status_code, 'account_disabled' if exc.status_code == 403 else 'invalid_token') from None

@contextmanager
def transaction(write=False):
    with SessionLocal() as db:
        # Explicit BEGIN also gives multi-query GETs a consistent SQLite snapshot.
        db.execute(text('BEGIN IMMEDIATE' if write else 'BEGIN'))
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise

def owned(db, sid, uid, deleted_ok=False):
    row = db.query(RecordSession).filter_by(id=sid, user_id=uid).first()
    if row is None:
        raise RecordError(404, 'not_found')
    if row.state == 'deleted' and not deleted_ok:
        raise RecordError(410, 'session_deleted')
    return row

def summary(db, row):
    count, maximum, received = db.query(func.count(RecordMessage.id), func.max(RecordMessage.sequence_no),
                                       func.max(RecordMessage.received_at)).filter_by(recording_session_id=row.id).one()
    return dict(recording_session_id=row.id, **{k: getattr(row, k) for k in SessionCreate.model_fields},
                state=row.state, created_at=row.created_at, last_received_at=received,
                ended_at=row.ended_at, last_sequence_no=row.last_sequence_no,
                received_record_count=count, max_received_sequence_no=maximum or 0,
                is_complete=row.state == 'closed' and count == row.last_sequence_no)

def message_data(row, is_test):
    return dict(record_id=row.id, recording_session_id=row.recording_session_id,
                **{k: getattr(row, k) for k in MessageCreate.model_fields}, received_at=row.received_at, is_test=is_test)

def identical(row, data):
    return all(getattr(row, k) == v for k, v in data.items())

def query_integer(value):
    if type(value) is int:
        return value
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value):
        raise ValueError('Integer required')
    return int(value)

PageLimit = Annotated[int, Field(ge=1, le=100), BeforeValidator(query_integer)]
ResourceID = Annotated[int, Field(ge=1, le=9223372036854775807), BeforeValidator(query_integer)]

def encode_cursor(uid, scope, snapshot, after):
    payload = json.dumps([1, uid, scope, snapshot, after], separators=(',', ':')).encode()
    sig = hmac.new(SECRET_KEY.encode(), b'robot-records-cursor:' + payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + sig).decode().rstrip('=')

def decode_cursor(cursor, uid, scope):
    try:
        if len(cursor) > 2048:
            raise ValueError()
        raw = base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True)
        payload, signature = raw[:-32], raw[-32:]
        expected = hmac.new(SECRET_KEY.encode(), b'robot-records-cursor:' + payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        version, user_id, route, snapshot, after = json.loads(payload)
        if version != 1 or user_id != uid or route != scope or type(snapshot) is not int or type(after) is not int or min(snapshot, after) < 0:
            raise ValueError()
        return snapshot, after
    except (ValueError, TypeError, UnicodeError):
        raise RecordError(422, 'invalid_cursor') from None

class ErrorInfo(BaseModel):
    code: str
    message: str
    retryable: bool
    details: list[dict] | None = None

class ErrorEnvelope(BaseModel):
    error: ErrorInfo

class SessionView(SessionCreate):
    recording_session_id: int
    state: Literal['open', 'closed']
    created_at: str
    last_received_at: str | None
    ended_at: str | None
    last_sequence_no: int | None
    received_record_count: int
    max_received_sequence_no: int
    is_complete: bool

class SessionWrite(SessionView):
    duplicate: bool

class MessageView(MessageCreate):
    record_id: int
    recording_session_id: int
    received_at: str
    is_test: bool

class MessageWrite(MessageView):
    duplicate: bool

class SessionPage(BaseModel):
    items: list[SessionView]
    next_cursor: str | None
    snapshot_max_id: int

class MessagePage(BaseModel):
    items: list[MessageView]
    next_cursor: str | None
    snapshot_max_id: int

router = APIRouter(prefix=PREFIX, tags=['Robot records 2.4'], responses={
    s: {'model': ErrorEnvelope} for s in (401, 403, 404, 409, 410, 422, 503)
})

@router.post('/sessions', status_code=201, response_model=SessionWrite, responses={200: {'model': SessionWrite}})
def create_session(body: SessionCreate, response: Response, uid=Depends(owner)):
    data = body.model_dump()
    with transaction(True) as db:
        # Attempt INSERT even for duplicates: uniqueness arbitration is in SQLite.
        try:
            with db.begin_nested():
                row = RecordSession(user_id=uid, **data, created_at=now(), state='open')
                db.add(row)
                db.flush()
            duplicate = False
        except IntegrityError:
            row = db.query(RecordSession).filter_by(user_id=uid, source=body.source,
                                                   external_session_id=body.external_session_id).first()
            if row is None:
                raise
            if row.state == 'deleted':
                raise RecordError(410, 'session_deleted')
            if not identical(row, data):
                raise RecordError(409, 'session_conflict')
            duplicate = True
        result = dict(**summary(db, row), duplicate=duplicate)
    response.status_code = 200 if duplicate else 201
    return result

@router.get('/sessions', response_model=SessionPage)
def list_sessions(limit: Annotated[PageLimit, Query()] = 50, cursor: str | None = None, uid=Depends(owner)):
    with transaction() as db:
        q = db.query(RecordSession).filter_by(user_id=uid).filter(RecordSession.state != 'deleted')
        if cursor is None:
            snapshot, after = q.with_entities(func.max(RecordSession.id)).scalar() or 0, None
        else:
            snapshot, after = decode_cursor(cursor, uid, 'sessions:id:desc')
        q = q.filter(RecordSession.id <= snapshot)
        if after is not None:
            q = q.filter(RecordSession.id < after)
        rows = q.order_by(RecordSession.id.desc()).limit(limit + 1).all()
        more = len(rows) > limit
        rows = rows[:limit]
        return dict(items=[summary(db, row) for row in rows], snapshot_max_id=snapshot,
                    next_cursor=encode_cursor(uid, 'sessions:id:desc', snapshot, rows[-1].id) if more else None)

@router.get('/sessions/{sid}', response_model=SessionView)
def get_session(sid: ResourceID, uid=Depends(owner)):
    with transaction() as db:
        return summary(db, owned(db, sid, uid))

@router.post('/sessions/{sid}/messages', status_code=201, response_model=MessageWrite, responses={200: {'model': MessageWrite}})
def create_message(sid: ResourceID, body: MessageCreate, response: Response, uid=Depends(owner)):
    data = body.model_dump()
    with transaction(True) as db:
        session = owned(db, sid, uid)
        old = db.query(RecordMessage).filter_by(recording_session_id=sid, external_message_id=body.external_message_id).first()
        if old is not None:
            if not identical(old, data):
                raise RecordError(409, 'message_conflict')
            row, duplicate = old, True
        else:
            if db.query(RecordMessage.id).filter_by(recording_session_id=sid, sequence_no=body.sequence_no).first():
                raise RecordError(409, 'sequence_conflict')
            if session.state == 'closed' and body.sequence_no > session.last_sequence_no:
                raise RecordError(409, 'session_closed')
            try:
                with db.begin_nested():
                    row = RecordMessage(recording_session_id=sid, **data, received_at=now())
                    db.add(row)
                    db.flush()
                duplicate = False
            except IntegrityError:
                row = db.query(RecordMessage).filter_by(recording_session_id=sid, external_message_id=body.external_message_id).first()
                if row is None:
                    raise RecordError(409, 'sequence_conflict')
                if not identical(row, data):
                    raise RecordError(409, 'message_conflict')
                duplicate = True
        result = dict(**message_data(row, session.is_test), duplicate=duplicate)
    response.status_code = 200 if duplicate else 201
    return result

@router.get('/sessions/{sid}/messages', response_model=MessagePage)
def list_messages(sid: ResourceID, limit: Annotated[PageLimit, Query()] = 50, cursor: str | None = None, uid=Depends(owner)):
    with transaction() as db:
        session = owned(db, sid, uid)
        scope = f'messages:{sid}:sequence:asc'
        q = db.query(RecordMessage).filter_by(recording_session_id=sid)
        if cursor is None:
            snapshot, after = q.with_entities(func.max(RecordMessage.id)).scalar() or 0, 0
        else:
            snapshot, after = decode_cursor(cursor, uid, scope)
        rows = q.filter(RecordMessage.id <= snapshot, RecordMessage.sequence_no > after).order_by(RecordMessage.sequence_no).limit(limit + 1).all()
        more = len(rows) > limit
        rows = rows[:limit]
        return dict(items=[message_data(row, session.is_test) for row in rows], snapshot_max_id=snapshot,
                    next_cursor=encode_cursor(uid, scope, snapshot, rows[-1].sequence_no) if more else None)

@router.post('/sessions/{sid}/close', response_model=SessionView)
def close_session(sid: ResourceID, body: SessionClose, uid=Depends(owner)):
    with transaction(True) as db:
        row = owned(db, sid, uid)
        if body.ended_at < row.started_at:
            raise RecordError(422, 'validation_error')
        if row.state == 'closed':
            if not identical(row, body.model_dump()):
                raise RecordError(409, 'close_conflict')
        else:
            maximum = db.query(func.max(RecordMessage.sequence_no)).filter_by(recording_session_id=sid).scalar() or 0
            if body.last_sequence_no < maximum:
                raise RecordError(409, 'close_conflict')
            row.state, row.ended_at, row.last_sequence_no = 'closed', body.ended_at, body.last_sequence_no
        return summary(db, row)

@router.delete('/sessions/{sid}', status_code=204)
def delete_session(sid: ResourceID, uid=Depends(owner)):
    with transaction(True) as db:
        row = owned(db, sid, uid, deleted_ok=True)
        if row.state != 'deleted':
            from .care.service import clear_session
            clear_session(db, sid)
            from .voice.screening import ScreeningResult
            db.query(ScreeningResult).filter_by(session_id=sid,owner=uid).delete()
            db.query(RecordMessage).filter_by(recording_session_id=sid).delete()
            for name in ('device_id', 'started_at', 'is_test', 'created_at', 'ended_at', 'last_sequence_no'):
                setattr(row, name, None)
            row.state, row.deleted_at = 'deleted', now()
    return Response(status_code=204)
