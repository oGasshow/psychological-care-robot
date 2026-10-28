from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON, UniqueConstraint
from ..database import Base

class AnonymousProfile(Base):
    __tablename__='robot_record_care_profiles'
    owner=Column(Integer,ForeignKey('users.id'),primary_key=True)
    anonymous_id=Column(String(40),unique=True,nullable=False)

class InputRevision(Base):
    __tablename__='robot_record_care_input_revisions'
    record_id=Column(Integer,ForeignKey('robot_record_messages.id',ondelete='CASCADE'),primary_key=True)
    owner=Column(Integer,ForeignKey('users.id'),nullable=False,index=True)
    session_id=Column(Integer,ForeignKey('robot_record_sessions.id'),nullable=False,index=True)
    revision=Column(Integer,nullable=False,default=0)

class Correction(Base):
    __tablename__='robot_record_care_corrections'
    __table_args__=(UniqueConstraint('owner','request_id'),UniqueConstraint('record_id','revision'),{'sqlite_autoincrement':True})
    id=Column(Integer,primary_key=True)
    owner=Column(Integer,ForeignKey('users.id'),nullable=False,index=True)
    session_id=Column(Integer,ForeignKey('robot_record_sessions.id'),nullable=False,index=True)
    record_id=Column(Integer,ForeignKey('robot_record_messages.id',ondelete='CASCADE'),nullable=False,index=True)
    request_id=Column(String(128),nullable=False)
    base_revision=Column(Integer,nullable=False)
    revision=Column(Integer,nullable=False)
    content=Column(Text,nullable=False)
    created_at=Column(String(32),nullable=False)

class AnalysisJob(Base):
    __tablename__='robot_record_care_analysis_jobs'
    __table_args__=(UniqueConstraint('owner','record_id','input_revision','engine_kind','engine_version','config_version',name='uq_care_job_version'),{'sqlite_autoincrement':True})
    id=Column(Integer,primary_key=True)
    owner=Column(Integer,ForeignKey('users.id'),nullable=False,index=True)
    session_id=Column(Integer,ForeignKey('robot_record_sessions.id'),nullable=False,index=True)
    record_id=Column(Integer,ForeignKey('robot_record_messages.id',ondelete='CASCADE'),nullable=False,index=True)
    input_revision=Column(Integer,nullable=False)
    input_snapshot_hash=Column(String(64),nullable=False)
    input_snapshot=Column(Text)
    engine_kind=Column(String(24),nullable=False)
    engine_version=Column(String(200),nullable=False)
    config_version=Column(String(128),nullable=False)
    config_summary=Column(JSON,nullable=False)
    state=Column(String(24),nullable=False,default='pending',index=True)
    attempt=Column(Integer,nullable=False,default=0)
    next_retry_at=Column(String(32))
    lease_until=Column(String(32))
    execution_token=Column(String(64))
    error_code=Column(String(80))
    created_at=Column(String(32),nullable=False)
    analyzed_at=Column(String(32))

class AnalysisResult(Base):
    __tablename__='robot_record_care_analysis_results'
    __table_args__=({'sqlite_autoincrement':True},)
    id=Column(Integer,primary_key=True)
    job_id=Column(Integer,ForeignKey('robot_record_care_analysis_jobs.id',ondelete='CASCADE'),nullable=False,unique=True)
    data=Column(JSON,nullable=False)

class SupportPolicy(Base):
    __tablename__='robot_record_care_support_policies'
    __table_args__=({'sqlite_autoincrement':True},)
    id=Column(Integer,primary_key=True)
    job_id=Column(Integer,ForeignKey('robot_record_care_analysis_jobs.id',ondelete='CASCADE'),nullable=False,unique=True)
    owner=Column(Integer,ForeignKey('users.id'),nullable=False,index=True)
    session_id=Column(Integer,ForeignKey('robot_record_sessions.id'),nullable=False,index=True)
    record_id=Column(Integer,ForeignKey('robot_record_messages.id',ondelete='CASCADE'),nullable=False)
    data=Column(JSON,nullable=False)
    expires_at=Column(String(32),nullable=False)
    is_current=Column(Integer,nullable=False,default=1)

class StrategyDelivery(Base):
    __tablename__='robot_record_care_strategy_deliveries'
    __table_args__=(UniqueConstraint('owner','request_id'),{'sqlite_autoincrement':True})
    id=Column(Integer,primary_key=True)
    owner=Column(Integer,ForeignKey('users.id'),nullable=False,index=True)
    session_id=Column(Integer,ForeignKey('robot_record_sessions.id'),nullable=False,index=True)
    policy_id=Column(Integer,ForeignKey('robot_record_care_support_policies.id',ondelete='CASCADE'),nullable=False)
    request_id=Column(String(128),nullable=False)
    delivery_status=Column(String(32),nullable=False)
    reason_code=Column(String(64))
    received_at=Column(String(32),nullable=False)

class DeletedReference(Base):
    """Opaque owner-bound markers only; no source IDs, text or event metadata."""
    __tablename__='robot_record_care_deleted_references'
    digest=Column(String(64),primary_key=True)
    session_id=Column(Integer,ForeignKey('robot_record_sessions.id'),nullable=False,index=True)
