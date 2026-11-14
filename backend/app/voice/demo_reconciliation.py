"""Durable demo answer reconciliation; source rows and task updates commit together."""
import hashlib
import json
from types import SimpleNamespace
from sqlalchemy import Column,Integer,String,ForeignKey
from ..database import Base
from ..robot_records import RecordSession,RecordMessage,transaction,now,summary
from ..care.service import effective
from .screening_policy import collection_demo_enabled


class DemoAnswerReview(Base):
    __tablename__='robot_voice_demo_answer_reviews'
    external=Column(String(100),primary_key=True)
    owner=Column(Integer,ForeignKey('users.id'),nullable=False,index=True)
    episode_id=Column(String(80),nullable=False)
    window_end=Column(String(16),nullable=False)
    state=Column(String(40),nullable=False,default='pending')
    input_hash=Column(String(64))
    updated_at=Column(String(32),nullable=False)


def register_in_db(db,uid,external,controller):
    if not (controller.demo_mode and controller.episode_id and collection_demo_enabled()):return
    row=db.get(DemoAnswerReview,external)
    if row is None:db.add(DemoAnswerReview(external=external,owner=uid,episode_id=controller.episode_id,
        window_end=controller.window_end,state='pending',updated_at=now()))
    elif row.owner!=uid or row.episode_id!=controller.episode_id:raise ValueError('review_owner_or_episode_mismatch')


def register(uid,external,controller):
    if not controller.demo_mode:return
    with transaction(True) as db:register_in_db(db,uid,external,controller)


def scan(limit=100):
    if not collection_demo_enabled():return 0
    from .collection_plan import CollectionPlan,read_plan_in_db,restore,store_plan_in_db
    from .screening import Screening,CollectionTrace,ScreeningResult,has_collected_items
    from .after_call import has_open_call
    changed=0
    with transaction(True) as db:
        # Bootstrap receipts for older saved calls, only when their episode matches.
        for trace,session in db.query(CollectionTrace,RecordSession).join(RecordSession,RecordSession.id==CollectionTrace.session_id).filter(RecordSession.state=='closed',RecordSession.is_test.is_(True)).order_by(RecordSession.id.desc()).limit(limit):
            if not trace.payload.get('demo_mode') or trace.owner!=session.user_id:continue
            if not trace.payload.get('episode_id'):continue
            if db.get(DemoAnswerReview,session.external_session_id) is None:
                db.add(DemoAnswerReview(external=session.external_session_id,owner=session.user_id,episode_id=trace.payload['episode_id'],window_end=trace.payload.get('window_end',''),state='pending',updated_at=now()))
        db.flush()
        jobs=db.query(DemoAnswerReview).order_by(DemoAnswerReview.updated_at.desc()).limit(limit).all()
        for job in jobs:
            target=db.query(RecordSession).filter_by(external_session_id=job.external,user_id=job.owner,source='doubao_realtime',is_test=True).first()
            if not target or target.state!='closed' or not summary(db,target)['is_complete'] or has_open_call(db,target):continue
            plan=read_plan_in_db(db,job.owner,True)
            if not plan or plan['episode_id']!=job.episode_id or not plan.get('demo_mode') or plan['window_end']!=job.window_end:continue
            rows=db.query(RecordMessage).filter_by(recording_session_id=target.id,text_status='completed').order_by(RecordMessage.sequence_no).all()
            drafts={row.id:effective(db,row) for row in rows}
            signature=hashlib.sha256(json.dumps(dict(episode=job.episode_id,window=job.window_end,status=plan['status'],answers=sorted(plan['answers']),
                rows=[(r.id,drafts[r.id]['input_revision'],drafts[r.id]['effective_content']) for r in rows]),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            if job.input_hash==signature:continue
            job.input_hash=signature;job.updated_at=now()
            if any(d['input_revision'] for d in drafts.values()):
                job.state='needs_revalidation';continue
            if not plan['needs_collection']:
                job.state='complete';continue
            if plan['status'] in ('declined','paused','urgent','checking_in') or plan.get('history_danger_unresolved'):
                job.state='paused';continue
            s=Screening(True,'collection-demo-v1');s.demo_mode=True;restore(s,plan);s.stage='collecting'
            entries=[SimpleNamespace(message_id=r.external_message_id,role=r.role,text=drafts[r.id]['effective_content'],final=True) for r in rows]
            before=set(s.answers)
            s.reconcile_demo_turns(entries)
            if set(s.answers)!=before or s.stage in ('urgent','declined','paused'):
                by_external={r.external_message_id:r for r in rows}
                from .collection_sources import identifiers
                for key in set(s.answers)-before:
                    answer=s.answers[key];refs=[]
                    for identifier in identifiers(answer):
                        row=by_external[identifier]
                        refs.append(dict(message_id=identifier,record_id=row.id,recording_session_id=target.id,input_revision=drafts[row.id]['input_revision']))
                    answer['source_refs']=refs
                if target.id not in s.history_session_ids:s.history_session_ids.append(target.id)
                store_plan_in_db(db,job.owner,True,s)
                view=s.view();trace=db.get(CollectionTrace,target.id)
                if trace:
                    view={**trace.payload,**view,'transport_diagnostics':trace.payload.get('transport_diagnostics',{})}
                view['automatic_saved_answer_review']=True
                db.merge(CollectionTrace(session_id=target.id,owner=job.owner,payload=view))
                if has_collected_items(view):db.merge(ScreeningResult(session_id=target.id,owner=job.owner,payload=view))
                changed+=1
            job.state='reviewed'
    return changed
