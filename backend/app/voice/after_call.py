"""Durable after-call review. Model calls never hold a database write lock."""
import asyncio
from datetime import datetime, timedelta, timezone
import uuid
from sqlalchemy import Column, Integer, String, JSON, ForeignKey
from ..database import Base
from ..robot_records import RecordSession, RecordMessage, transaction, now, summary as session_view
from ..care.service import effective, later
from . import concern_detector
from .screening_policy import collection_policy
from .transcripts import Utterance


class AfterCallReview(Base):
    __tablename__ = 'robot_voice_after_call_reviews'
    session_id = Column(Integer, ForeignKey('robot_record_sessions.id'), primary_key=True)
    owner = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    state = Column(String(32), nullable=False, default='pending', index=True)
    input_hash = Column(String(64), nullable=False)
    source_refs = Column(JSON, nullable=False)
    attempt = Column(Integer, nullable=False, default=0)
    execution_token = Column(String(64))
    lease_until = Column(String(32))
    next_retry_at = Column(String(32))
    error_code = Column(String(80))
    result = Column(JSON)
    updated_at = Column(String(32), nullable=False)


class LiveCallLease(Base):
    __tablename__ = 'robot_voice_live_call_leases'
    key = Column(String(80), primary_key=True)
    owner = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    external = Column(String(100), nullable=False)
    expires_at = Column(String(32), nullable=False)


def touch_live_call(uid, is_test, external):
    # Voice text is buffered locally until close, so RecordSession alone cannot
    # reveal an active call to the separate review worker process.
    with transaction(True) as db:
        db.merge(LiveCallLease(key=f'{uid}:{int(is_test)}', owner=uid, external=external,
                               expires_at=later(30)))


def end_live_call(uid, is_test, external):
    with transaction(True) as db:
        db.query(LiveCallLease).filter_by(key=f'{uid}:{int(is_test)}', external=external).delete()


def enabled():
    try:
        policy = collection_policy()
        return policy if policy.enabled and policy.review_mode == 'post_session' else None
    except ValueError:
        return None


def snapshot(db, target):
    """Only complete, owner-matched voice calls, within a fixed seven-day window."""
    if (target is None or target.state != 'closed' or target.source != 'doubao_realtime'
            or not target.external_session_id.startswith('voice_')
            or not session_view(db, target)['is_complete']):
        return None
    start = (datetime.fromisoformat(target.started_at.replace('Z', '+00:00'))
             - timedelta(days=7)).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    sessions = db.query(RecordSession).filter(
        RecordSession.user_id == target.user_id, RecordSession.is_test == target.is_test,
        RecordSession.state == 'closed', RecordSession.source == 'doubao_realtime',
        RecordSession.external_session_id.startswith('voice_'), RecordSession.id <= target.id,
        RecordSession.started_at >= start).order_by(RecordSession.id.desc()).limit(5).all()
    ids = [s.id for s in sessions if session_view(db, s)['is_complete']]
    rows = db.query(RecordMessage).filter(RecordMessage.recording_session_id.in_(ids),
        RecordMessage.text_status == 'completed').order_by(RecordMessage.id.desc()).limit(240).all()[::-1]
    entries, refs = [], {}
    for row in rows:
        draft = effective(db, row)
        entry = Utterance(f'after_call:{row.id}:{draft["input_revision"]}', row.role,
            row.turn_id or 'saved', text=draft['effective_content'], final=True, occurred_at=row.occurred_at)
        entries.append(entry)
        refs[entry.message_id] = dict(record_id=row.id, recording_session_id=row.recording_session_id,
                                      input_revision=draft['input_revision'])
    if not any(e.role == 'user' and e.text.strip() for e in entries
               if refs[e.message_id]['recording_session_id'] == target.id):
        return None
    data = concern_detector.snapshot(entries)
    from care_core import safety
    data['historical_danger'] = any(e.role == 'user' and
        safety(e.text)['safety_signal'] == 'explicit_danger_expression' for e in entries)
    return data, {t['message_id']: refs[t['message_id']] for t in data['turns']}


def has_open_call(db, target):
    lease=db.get(LiveCallLease,f'{target.user_id}:{int(target.is_test)}')
    if lease and lease.expires_at>now():
        return True
    return db.query(RecordSession.id).filter(RecordSession.user_id == target.user_id,
        RecordSession.is_test == target.is_test, RecordSession.source == 'doubao_realtime',
        RecordSession.external_session_id.startswith('voice_'), RecordSession.state == 'open').first() is not None


class ReviewWorker:
    def __init__(self, *, clock=now, assessor=None):
        self.clock, self.assessor = clock, assessor

    def scan(self, limit=100):
        if not enabled():
            return 0
        created = 0
        start=(datetime.fromisoformat(self.clock().replace('Z','+00:00'))-timedelta(days=7)).isoformat().replace('+00:00','Z')
        with transaction(True) as db:
            targets = db.query(RecordSession).filter(RecordSession.state == 'closed',
                RecordSession.started_at >= start,
                RecordSession.source == 'doubao_realtime',
                RecordSession.external_session_id.startswith('voice_')).order_by(RecordSession.id.desc()).limit(limit).all()
            for target in targets:
                value = snapshot(db, target)
                if value is None:
                    continue
                data, refs = value
                row = db.get(AfterCallReview, target.id)
                if row and row.input_hash == data['source_snapshot_hash']:
                    continue
                if row is None:
                    row = AfterCallReview(session_id=target.id, owner=target.user_id)
                    db.add(row)
                row.input_hash, row.source_refs = data['source_snapshot_hash'], refs
                row.state, row.attempt, row.updated_at = 'pending', 0, self.clock()
                row.execution_token = row.lease_until = row.next_retry_at = row.error_code = row.result = None
                created += 1
        return created

    def claim(self):
        if not enabled():
            return None
        stamp = self.clock()
        with transaction(True) as db:
            rows = db.query(AfterCallReview).filter(AfterCallReview.state.in_(
                ('pending', 'retry_wait', 'running'))).order_by(AfterCallReview.session_id).all()
            for row in rows:
                if row.state == 'running' and row.lease_until and row.lease_until > stamp:
                    continue
                if row.state == 'retry_wait' and row.next_retry_at and row.next_retry_at > stamp:
                    continue
                target = db.get(RecordSession, row.session_id)
                value = snapshot(db, target)
                if value is None:
                    row.state, row.result = 'invalidated', None
                    row.execution_token = row.lease_until = None
                    continue
                if has_open_call(db, target):
                    continue
                data, refs = value
                if row.input_hash != data['source_snapshot_hash']:
                    row.input_hash, row.source_refs, row.attempt = data['source_snapshot_hash'], refs, 0
                if sum(t['role'] == 'user' for t in data['turns']) < 2:
                    row.state, row.error_code, row.updated_at = 'insufficient_data', 'need_more_saved_turns', stamp
                    continue
                if row.attempt >= 3:
                    row.state, row.error_code, row.updated_at = 'failed', 'review_attempt_limit', stamp
                    row.execution_token = row.lease_until = None
                    continue
                row.state, row.execution_token = 'running', uuid.uuid4().hex
                row.attempt += 1
                row.lease_until, row.updated_at = later(180, stamp), stamp
                row.next_retry_at = row.error_code = None
                return dict(session_id=row.session_id, token=row.execution_token,
                            input_hash=row.input_hash, data=data)
        return None

    def finish(self, claim, result=None, error=None):
        stamp = self.clock()
        with transaction(True) as db:
            row = db.get(AfterCallReview, claim['session_id'])
            if (row is None or row.state != 'running' or row.execution_token != claim['token']
                    or row.lease_until <= stamp):
                return False
            target = db.get(RecordSession, row.session_id)
            value = snapshot(db, target)
            row.execution_token = row.lease_until = None
            row.updated_at = stamp
            if value is None or value[0]['source_snapshot_hash'] != claim['input_hash']:
                row.state, row.result, row.error_code = 'invalidated', None, 'review_sources_changed'
                return False
            if has_open_call(db, target):
                row.state, row.next_retry_at = 'retry_wait', later(15, stamp)
                row.error_code = 'waiting_for_call_end'
                return False
            if error:
                row.state = 'retry_wait' if row.attempt < 3 else 'failed'
                row.error_code = error
                row.next_retry_at = later(30 * 2 ** (row.attempt - 1), stamp) if row.state == 'retry_wait' else None
                return True
            policy = enabled()
            if policy is None:
                row.state, row.error_code = 'invalidated', 'review_disabled'
                return False
            from .collection_plan import read_plan_in_db, restore, store_plan_in_db
            from .screening import Screening
            plan = read_plan_in_db(db, row.owner, bool(target.is_test))
            already_completed = bool(plan and not plan['needs_collection'] and
                plan.get('completed_at') and plan['completed_at'] >= (target.ended_at or target.started_at))
            if result['decision'] == 'follow_up' and not already_completed:
                controller = Screening(True, policy.notice_version)
                controller.review_mode = 'post_session'
                restore(controller, plan)
                controller.apply_decision({**result, 'transition_ready': False}, fresh=False)
                controller.history_session_ids = sorted(set(controller.history_session_ids +
                    [ref['recording_session_id'] for ref in row.source_refs.values()]))
                store_plan_in_db(db, row.owner, bool(target.is_test), controller)
            row.state, row.error_code, row.next_retry_at = 'succeeded', None, None
            row.result = dict(decision=result['decision'], detector_version=result['detector_version'],
                target_scales=result['target_scales'], applied_to_task=result['decision'] == 'follow_up' and not already_completed)
        return True

    def step(self):
        claim = self.claim()
        if claim is None:
            return False
        try:
            result = asyncio.run((self.assessor or concern_detector.assess)(claim['data']))
            if result.get('source_snapshot_hash') != claim['input_hash']:
                raise ValueError('review_snapshot_mismatch')
            self.finish(claim, result=result)
        except TimeoutError:
            self.finish(claim, error='after_call_review_timeout')
        except ValueError:
            self.finish(claim, error='after_call_review_invalid_output')
        except Exception:
            self.finish(claim, error='after_call_review_unavailable')
        return True


def public_reviews(uid, is_test, limit=20):
    messages = {'pending': '通话已保存，等待后台复核。', 'running': '正在后台复核已保存的对话。',
        'retry_wait': '后台复核待重试，不影响已保存的文字和采集进度。',
        'failed': '后台复核暂未完成，可重试；未据此认定不需要进一步了解。',
        'insufficient_data': '已保存信息不足，后续会话将结合历史继续了解。',
        'invalidated': '原话或来源已变化，需要重新复核。',
        'succeeded': '后台复核已完成；未完成的采集任务会在后续会话继续。'}
    with transaction() as db:
        rows = db.query(AfterCallReview).join(RecordSession,
            RecordSession.id == AfterCallReview.session_id).filter(AfterCallReview.owner == uid,
            RecordSession.user_id == uid, RecordSession.is_test == is_test,
            RecordSession.state != 'deleted').order_by(AfterCallReview.session_id.desc()).limit(limit).all()
        return [dict(recording_session_id=row.session_id, state=row.state, attempt=row.attempt,
            updated_at=row.updated_at, error_code=row.error_code, decision=(row.result or {}).get('decision'),
            target_scales=(row.result or {}).get('target_scales', []), message=messages[row.state]) for row in rows]


def run(stop):
    worker = ReviewWorker()
    while not stop.is_set():
        try:
            worker.scan()
            processed = worker.step()
        except Exception:
            processed = False
        if not processed:
            stop.wait(3)
