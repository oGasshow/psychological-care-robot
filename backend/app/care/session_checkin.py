"""Owner-submitted optional follow-up for one saved voice call."""
from typing import Annotated

from pydantic import Field, StrictInt, model_validator
from sqlalchemy import Column, ForeignKey, Integer, JSON, String

from robot_client.schemas import StrictBody

from ..database import Base
from ..robot_records import RecordMessage, now, owned, summary
from ..voice.screening import CollectionTrace, ITEMS, OPTIONS
from ..voice.screening_policy import collection_policy
from .safety_notice import dialogue_danger_notice
from .scale_catalog import session_score
from .service import CareError, exclusion


QUESTIONS = {'phq_mood': ('PHQ-9', 2), 'gad_tension': ('GAD-7', 1)}
Points = Annotated[StrictInt, Field(ge=0, le=3)]


class CheckinBody(StrictBody):
    phq_mood: Points | None = None
    gad_tension: Points | None = None

    @model_validator(mode='after')
    def require_selection(self):
        if self.phq_mood is None and self.gad_tension is None:
            raise ValueError('checkin_requires_answer')
        return self


class SessionCheckin(Base):
    __tablename__ = 'robot_care_session_checkins'
    session_id = Column(Integer, ForeignKey('robot_record_sessions.id', ondelete='CASCADE'), primary_key=True)
    owner = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    answers = Column(JSON, nullable=False)
    submitted_at = Column(String(32), nullable=False)


def checkin_scores(row):
    if row is None:
        return []
    scores = []
    for key, (scale, _) in QUESTIONS.items():
        points = row.answers.get(key)
        if type(points) is not int or not 0 <= points < len(OPTIONS):
            continue
        scores.append(session_score(scale, [points], 'session_checkin'))
    return scores


def checkin_state(db, uid, sid, *, answers=None):
    session = owned(db, sid, uid)
    rows = db.query(RecordMessage).filter_by(recording_session_id=sid).all()
    trace = db.get(CollectionTrace, sid)
    try:
        policy = collection_policy()
    except ValueError:
        policy = None
    available = bool(policy and policy.enabled and not policy.demo_mode and session.source == 'doubao_realtime'
                     and not (trace and trace.payload.get('demo_mode'))
                     and summary(db, session)['is_complete'] and any(not exclusion(row) for row in rows)
                     and not dialogue_danger_notice(db, rows)['count'])
    saved = db.get(SessionCheckin, sid)
    if saved is not None and saved.owner != uid:
        raise CareError(404, 'not_found')
    if answers is not None:
        if not available:
            raise CareError(409, 'session_checkin_unavailable')
        if saved is None or saved.answers != answers:
            saved = db.merge(SessionCheckin(session_id=sid, owner=uid, answers=answers, submitted_at=now()))
    from .collection_history import collection_history
    collection = collection_history(db, uid, session_ids=[sid], session_only=True,
                                    allowed_record_ids={row.id for row in rows})
    has_voice_score = any(item['current_session_scores'] for item in collection)
    return dict(available=available, recall_date=session.ended_at, has_voice_score=has_voice_score,
                questions=[dict(key=key, scale_id=scale, text=ITEMS[scale][number-1])
                           for key, (scale, number) in QUESTIONS.items()] if available else [],
                options=OPTIONS if available else [],
                answers=saved.answers if saved else {}, scores=checkin_scores(saved))
