"""Separate persistent worker. Network/model inference occurs outside SQLite writes."""
import argparse
import os
import threading
import uuid
from sqlalchemy import or_,and_
from ..robot_records import RecordMessage,RecordSession,transaction,now
from .models import AnalysisJob,AnalysisResult,SupportPolicy
from .service import enqueue,current,later
from .settings import engine_configuration

class Worker:
    def __init__(self,*,clock=now,analyzer=None):
        self.refresh_configuration()
        self.clock=clock
        self.analyzer=analyzer

    def refresh_configuration(self):
        self.active,self.core,self.config=engine_configuration()

    def scan(self,limit=100):
        self.refresh_configuration()
        with transaction(True) as db:
            rows=db.query(RecordMessage,RecordSession.user_id).join(RecordSession,RecordSession.id==RecordMessage.recording_session_id).filter(
                RecordSession.state!='deleted',RecordMessage.role=='user',RecordMessage.text_status=='completed').order_by(RecordMessage.id).all()
            created=0
            for row,owner in rows:
                if not row.content.strip():
                    continue
                _,duplicate=enqueue(db,row,owner,(self.active,self.core,self.config))
                created+=not duplicate
                if created>=limit:
                    break
            return created

    def claim(self):
        self.refresh_configuration()
        stamp=self.clock()
        with transaction(True) as db:
            jobs=db.query(AnalysisJob).filter_by(engine_kind=self.config['engine_kind'],engine_version=self.config['engine_version'],config_version=self.config['config_version']).filter(or_(
                AnalysisJob.state=='pending',and_(AnalysisJob.state=='retry_wait',AnalysisJob.next_retry_at<=stamp),
                and_(AnalysisJob.state=='running',AnalysisJob.lease_until<=stamp))).order_by(AnalysisJob.id).all()
            for job in jobs:
                if not current(db,job):
                    job.state='invalidated'
                    job.input_snapshot=None
                    job.execution_token=None
                    job.lease_until=None
                    job.next_retry_at=None
                    db.query(SupportPolicy).filter_by(job_id=job.id).update({'is_current':0})
                    continue
                if job.attempt>=self.active.max_attempts:
                    job.state='failed'
                    job.error_code='attempt_limit_reached'
                    job.input_snapshot=None
                    job.next_retry_at=None
                    job.execution_token=None
                    job.lease_until=None
                    continue
                job.state='running'
                job.attempt+=1
                job.execution_token=uuid.uuid4().hex
                job.lease_until=later(self.active.lease_seconds,stamp)
                job.error_code=None
                return dict(job_id=job.id,token=job.execution_token,text=job.input_snapshot)
        return None

    def finish(self,claim,result=None,error=None):
        from care_core import safety
        stamp=self.clock()
        with transaction(True) as db:
            job=db.get(AnalysisJob,claim['job_id'])
            if job is None or job.state!='running' or job.execution_token!=claim['token'] or job.lease_until<=stamp or not current(db,job):
                return False
            policy_data=None
            if error is None:
                job.state='succeeded'
                job.next_retry_at=None
                data={key:result.get(key) for key in ('classification_status','emotion_label','emotion_tags','safety_signal','matched_rule_ids','reason_code')}
                policy_data=result.get('support')
                previous=db.query(AnalysisResult).filter_by(job_id=job.id).first()
                if previous:
                    previous.data=data
                else:
                    db.add(AnalysisResult(job_id=job.id,data=data))
                job.analyzed_at=stamp
            else:
                job.error_code=error.code
                job.state='retry_wait' if error.retryable and job.attempt<self.active.max_attempts else 'failed'
                job.next_retry_at=later(self.active.retry_seconds*2**(job.attempt-1),stamp) if job.state=='retry_wait' else None
                safe=error.safety_result or safety(claim['text'])
                policy_data=safe.get('support')
                data=dict(classification_status='failed',emotion_label=None,emotion_tags=[],
                          safety_signal=safe['safety_signal'],matched_rule_ids=safe['matched_rule_ids'],reason_code=error.code)
                previous=db.query(AnalysisResult).filter_by(job_id=job.id).first()
                if previous:
                    previous.data=data
                else:
                    db.add(AnalysisResult(job_id=job.id,data=data))
            if policy_data:
                old=db.query(SupportPolicy).filter_by(job_id=job.id).first()
                if old:
                    old.data=policy_data
                    old.expires_at=later(self.active.policy_lifetime,stamp)
                    old.is_current=1
                else:
                    db.add(SupportPolicy(job_id=job.id,owner=job.owner,session_id=job.session_id,record_id=job.record_id,
                        data=policy_data,expires_at=later(self.active.policy_lifetime,stamp),is_current=1))
            job.execution_token=None
            job.lease_until=None
            if job.state in ('succeeded','failed'):
                job.input_snapshot=None
        return True

    def step(self):
        from care_core import analyze,CoreAnalysisError,safety
        claim=self.claim()
        if claim is None:
            return False
        try:
            result=(self.analyzer or analyze)(claim['text'],self.active.engine,settings=self.core)
            self.finish(claim,result=result)
        except CoreAnalysisError as error:
            self.finish(claim,error=error)
        except Exception:
            self.finish(claim,error=CoreAnalysisError('analysis_execution_error',retryable=False,safety_result=safety(claim['text'])))
        return True

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--instance-id',default=None)
    args=parser.parse_args()
    # Import app ensures all tables and startup guards exist, without inference.
    from ..main import app
    worker=Worker()
    stop=threading.Event()
    try:
        while not stop.is_set():
            worker.scan()
            if args.once:
                processed=0
                while worker.step():
                    processed+=1
                print('{"analysis_worker":"completed","processed":'+str(processed)+'}')
                return
            if not worker.step():
                stop.wait(worker.active.poll_seconds)
    except KeyboardInterrupt:
        stop.set()

if __name__=='__main__':
    main()
