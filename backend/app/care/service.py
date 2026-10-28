import hashlib
import hmac
import uuid
from datetime import datetime,timezone,timedelta
from sqlalchemy import func
from ..robot_records import RecordMessage,RecordSession,transaction,owned,now,summary as session_summary
from .models import AnonymousProfile,InputRevision,Correction,AnalysisJob,AnalysisResult,SupportPolicy,StrategyDelivery,DeletedReference
from ..config import SECRET_KEY
from .settings import engine_configuration,settings

class CareError(Exception):
    def __init__(self,status,code):
        self.status,self.code=status,code

def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def later(seconds,at=None):
    dt=datetime.fromisoformat((at or now()).replace('Z','+00:00'))+timedelta(seconds=seconds)
    return dt.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')

def profile(db,uid):
    row=db.get(AnonymousProfile,uid)
    if row is None:
        row=AnonymousProfile(owner=uid,anonymous_id='KY-'+uuid.uuid4().hex[:16].upper())
        db.add(row)
        db.flush()
    return {'anonymous_id':row.anonymous_id}

def record(db,rid,uid):
    message=db.get(RecordMessage,rid)
    if message is None:
        missing(db,'record',rid,uid)
    session=owned(db,message.recording_session_id,uid)
    return message,session

def reference_hash(kind,identifier,uid):
    return hmac.new(SECRET_KEY.encode(),f'care-deleted:{kind}:{uid}:{identifier}'.encode(),hashlib.sha256).hexdigest()

def missing(db,kind,identifier,uid):
    if db.get(DeletedReference,reference_hash(kind,identifier,uid)) is not None:
        raise CareError(410,'session_deleted')
    raise CareError(404,'not_found')

def exclusion(row):
    if row.role!='user':
        return 'assistant_not_analysis_input'
    if row.text_status!='completed':
        return 'canceled_not_analysis_input'
    if not row.content.strip():
        return 'empty_input'
    return None

def effective(db,row):
    state=db.get(InputRevision,row.id)
    revision=state.revision if state else 0
    correction=db.query(Correction).filter_by(record_id=row.id,revision=revision).first() if revision else None
    return dict(record_id=row.id,recording_session_id=row.recording_session_id,original_content=row.content,
                effective_content=correction.content if correction else row.content,input_revision=revision,
                corrected_at=correction.created_at if correction else None)

def invalidate(db,rid):
    db.query(AnalysisJob).filter_by(record_id=rid).update({'state':'invalidated','execution_token':None,'lease_until':None,'input_snapshot':None})
    db.query(SupportPolicy).filter_by(record_id=rid).update({'is_current':0})

def enqueue(db,row,uid,configuration=None):
    if exclusion(row):
        raise CareError(422,'excluded_input')
    active,core,config=configuration or engine_configuration()
    input_data=effective(db,row)
    key=dict(owner=uid,record_id=row.id,input_revision=input_data['input_revision'],engine_kind=config['engine_kind'],
             engine_version=config['engine_version'],config_version=config['config_version'])
    existing=db.query(AnalysisJob).filter_by(**key).first()
    if existing:
        if existing.input_snapshot_hash!=digest(input_data['effective_content']):
            raise CareError(409,'input_version_conflict')
        return existing,True
    invalidate(db,row.id)
    job=AnalysisJob(**key,session_id=row.recording_session_id,input_snapshot_hash=digest(input_data['effective_content']),
        input_snapshot=input_data['effective_content'],config_summary=config['config_summary'],state='pending',attempt=0,created_at=now())
    db.add(job)
    db.flush()
    return job,False

def current(db,job):
    row=db.get(RecordMessage,job.record_id)
    session=db.get(RecordSession,job.session_id)
    if row is None or session is None or session.state=='deleted' or exclusion(row):
        return False
    return effective(db,row)['input_revision']==job.input_revision and job.state!='invalidated'

def job_view(db,job):
    row=db.get(RecordMessage,job.record_id)
    result=db.query(AnalysisResult).filter_by(job_id=job.id).first()
    policy=db.query(SupportPolicy).filter_by(job_id=job.id).first()
    data=dict(schema_version='1.0',task_id=job.id,job_id=job.id,recording_session_id=job.session_id,target_record_id=job.record_id,
        sequence_no=row.sequence_no if row else None,input_revision=job.input_revision,input_snapshot_hash=job.input_snapshot_hash,
        engine_kind=job.engine_kind,engine_version=job.engine_version,config_version=job.config_version,config_summary=job.config_summary,
        state=job.state,status=job.state,attempt=job.attempt,next_retry_at=job.next_retry_at,lease_until=job.lease_until,
        error_code=job.error_code,analyzed_at=job.analyzed_at,created_at=job.created_at,is_test=bool(db.get(RecordSession,job.session_id).is_test),
        is_current=current(db,job),support_policy_id=policy.id if policy else None,result_id=result.id if result else None,
        classification_status='not_analyzed' if job.state in ('pending','running','retry_wait') else 'failed' if job.state=='failed' else 'invalidated',
        emotion_label=None,emotion_tags=[],safety_signal='undetermined',matched_rule_ids=[])
    if result:
        data.update(result.data)
        data['result_id']=result.id
    if job.state=='invalidated':
        data['classification_status']='invalidated'
    data['result']={k:v for k,v in data.items() if k!='result'} if result else None
    return data

def correct(db,row,uid,body):
    if exclusion(row):
        raise CareError(422,'excluded_input')
    old=db.query(Correction).filter_by(owner=uid,request_id=body.request_id).first()
    if old:
        if old.record_id!=row.id or old.base_revision!=body.base_revision or old.content!=body.content:
            raise CareError(409,'correction_conflict')
        return {'record_id':row.id,'input_revision':old.revision,'corrected_at':old.created_at,'duplicate':True},True
    value=effective(db,row)
    if value['input_revision']!=body.base_revision:
        raise CareError(409,'revision_conflict')
    revision=value['input_revision']+1
    state=db.get(InputRevision,row.id)
    if state is None:
        state=InputRevision(record_id=row.id,owner=uid,session_id=row.recording_session_id,revision=revision)
        db.add(state)
    else:
        state.revision=revision
    entry=Correction(owner=uid,session_id=row.recording_session_id,record_id=row.id,request_id=body.request_id,
        base_revision=body.base_revision,revision=revision,content=body.content,created_at=now())
    db.add(entry)
    db.flush()
    invalidate(db,row.id)
    job,_=enqueue(db,row,uid)
    return dict(record_id=row.id,input_revision=revision,corrected_at=entry.created_at,task_id=job.id,duplicate=False),False

def clear_session(db,sid):
    """Must be called inside the original DELETE's write transaction."""
    session=db.get(RecordSession,sid)
    for kind,query in [('record',db.query(RecordMessage.id).filter_by(recording_session_id=sid)),
                       ('job',db.query(AnalysisJob.id).filter_by(session_id=sid)),
                       ('policy',db.query(SupportPolicy.id).filter_by(session_id=sid)),
                       ('delivery',db.query(StrategyDelivery.id).filter_by(session_id=sid))]:
        for (identifier,) in query:
            db.add(DeletedReference(digest=reference_hash(kind,identifier,session.user_id),session_id=sid))
    jobs=[r[0] for r in db.query(AnalysisJob.id).filter_by(session_id=sid)]
    db.query(StrategyDelivery).filter_by(session_id=sid).delete()
    db.query(SupportPolicy).filter_by(session_id=sid).delete()
    if jobs:
        db.query(AnalysisResult).filter(AnalysisResult.job_id.in_(jobs)).delete(synchronize_session=False)
    db.query(AnalysisJob).filter_by(session_id=sid).delete()
    db.query(Correction).filter_by(session_id=sid).delete()
    db.query(InputRevision).filter_by(session_id=sid).delete()

def policy_view(db,row):
    job=db.get(AnalysisJob,row.job_id)
    return dict(policy_id=row.id,task_id=row.job_id,result_id=(db.query(AnalysisResult.id).filter_by(job_id=row.job_id).scalar()),
        recording_session_id=row.session_id,target_record_id=row.record_id,input_revision=job.input_revision,
        **row.data,expires_at=row.expires_at,is_current=bool(row.is_current) and current(db,job),
        source_kind='saved_analysis',real_delivery_status='not_connected',simulator_enabled=settings().simulator)

def simulate(db,uid,body):
    if not settings().simulator:
        raise CareError(404,'not_found')
    policy=db.query(SupportPolicy).filter_by(id=body.policy_id,owner=uid).first()
    if policy is None:
        missing(db,'policy',body.policy_id,uid)
    owned(db,policy.session_id,uid)
    prior=db.query(StrategyDelivery).filter_by(owner=uid,request_id=body.request_id).first()
    if prior:
        if prior.policy_id!=policy.id:
            raise CareError(409,'delivery_conflict')
        return delivery_view(prior),True
    valid=policy.is_current and current(db,db.get(AnalysisJob,policy.job_id)) and policy.expires_at>now()
    row=StrategyDelivery(owner=uid,session_id=policy.session_id,policy_id=policy.id,request_id=body.request_id,
        delivery_status='simulated_received' if valid else 'simulated_rejected',reason_code=None if valid else 'policy_expired_or_invalidated',received_at=now())
    db.add(row)
    db.flush()
    return delivery_view(row),False

def delivery_view(row):
    return dict(delivery_id=row.id,policy_id=row.policy_id,request_id=row.request_id,recording_session_id=row.session_id,
        consumer_kind='local_simulator',delivery_status=row.delivery_status,reason_code=row.reason_code,received_at=row.received_at,
        real_delivery_status='not_connected')

def session_status(db,session):
    source=db.query(RecordMessage).filter_by(recording_session_id=session.id).order_by(RecordMessage.sequence_no).all()
    counts={label:0 for label in ('positive','neutral','negative')}
    statuses={state:0 for state in ('pending','running','retry_wait','failed','unable_to_determine','excluded','invalidated','succeeded')}
    excluded=[]
    refs=[]
    for row in source:
        reason=exclusion(row)
        if reason:
            statuses['excluded']+=1
            excluded.append({'record_id':row.id,'sequence_no':row.sequence_no,'reason_code':reason})
            continue
        jobs=db.query(AnalysisJob).filter_by(record_id=row.id).order_by(AnalysisJob.id.desc()).all()
        active=next((job for job in jobs if current(db,job)),None)
        statuses['invalidated']+=sum(job.state=='invalidated' for job in jobs)
        if active is None:
            statuses['pending']+=1
            continue
        statuses[active.state]+=1
        value=job_view(db,active)
        if active.state=='succeeded':
            if value['classification_status']=='classified':
                counts[value['emotion_label']]+=1
            else:
                statuses['unable_to_determine']+=1
        refs.append({'record_id':row.id,'task_id':active.id,'input_revision':active.input_revision,'classification_status':value['classification_status']})
    return dict(**session_summary(db,session),emotion_counts=counts,analysis_counts=statuses,
                excluded_records=excluded,source_references=refs,data_as_of=now())
