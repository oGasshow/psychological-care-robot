"""One current report wording shared by the user and the authorized care team."""
from sqlalchemy import Column, Integer, String, ForeignKey, JSON
from ..database import Base
from ..robot_records import now
from .session_report import session_report, public_narrative
from .service import CareError


class ReportWording(Base):
    __tablename__ = 'robot_record_care_report_wordings'
    session_id = Column(Integer, ForeignKey('robot_record_sessions.id'), primary_key=True)
    owner = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    source_hash = Column(String(64), nullable=False)
    narrative = Column(JSON, nullable=False)
    updated_at = Column(String(32), nullable=False)


def read_report(db, uid, sid):
    value, facts = session_report(db, uid, sid)
    cached = db.get(ReportWording, sid)
    narrative = cached.narrative if cached and cached.owner == uid and cached.source_hash == value['source_snapshot_hash'] else None
    return dict(value, **public_narrative(facts, narrative)), facts


def generate_report(uid, sid, source_hash):
    from ..robot_records import transaction
    from .report_narrative import generate
    with transaction() as db:
        value, facts = read_report(db, uid, sid)
        if value['source_snapshot_hash'] != source_hash:
            raise CareError(409, 'report_sources_changed')
    narrative = generate(facts)
    if narrative.get('mode') != 'model':
        # A temporary provider failure must not become a permanent cached report.
        with transaction() as db:
            latest, _ = read_report(db, uid, sid)
        if latest['source_snapshot_hash'] != source_hash:
            raise CareError(409, 'report_sources_changed')
        return public_narrative(facts, narrative)
    with transaction(True) as db:
        latest, _ = read_report(db, uid, sid)
        if latest['source_snapshot_hash'] != source_hash:
            raise CareError(409, 'report_sources_changed')
        cached = db.get(ReportWording, sid)
        if not cached:
            cached = ReportWording(session_id=sid, owner=uid)
            db.add(cached)
        cached.source_hash, cached.narrative, cached.updated_at = source_hash, narrative, now()
    return public_narrative(facts, narrative)
