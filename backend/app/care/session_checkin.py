"""Legacy web answers retained for existing-data deletion."""
from sqlalchemy import Column, ForeignKey, Integer, JSON, String

from ..database import Base


class SessionCheckin(Base):
    __tablename__ = 'robot_care_session_checkins'
    session_id = Column(Integer, ForeignKey('robot_record_sessions.id', ondelete='CASCADE'), primary_key=True)
    owner = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    answers = Column(JSON, nullable=False)
    submitted_at = Column(String(32), nullable=False)
