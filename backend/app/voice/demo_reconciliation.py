"""Durable normal/demo answer reconciliation; source rows and task updates commit together."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from sqlalchemy import Column,Integer,String,ForeignKey
from ..database import Base
from ..robot_records import RecordSession,RecordMessage,transaction,now,summary
from ..care.service import effective
from .screening_policy import collection_policy


RECONCILIATION_VERSION='saved-answers-v4-legacy-call-end'


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
    if not (controller.streamlined and controller.episode_id and collection_policy().enabled):return
    row=db.get(DemoAnswerReview,external)
    if row is None:db.add(DemoAnswerReview(external=external,owner=uid,episode_id=controller.episode_id,
        window_end=controller.window_end,state='pending',updated_at=now()))
    elif row.owner!=uid or row.episode_id!=controller.episode_id:raise ValueError('review_owner_or_episode_mismatch')


def register(uid,external,controller):
    if not controller.streamlined:return
    with transaction(True) as db:register_in_db(db,uid,external,controller)


def mirror_missing(db,target,plan):
    """Restore a missing receipt without inferring answers or changing task state."""
    from .collection_plan import restore
    from .screening import Screening,CollectionTrace,ScreeningResult,has_collected_items
    if db.get(CollectionTrace,target.id) is not None:return
    s=Screening(True,collection_policy().notice_version);s.demo_mode=bool(plan.get('demo_mode'));s.direct_collection=True
    restore(s,plan)
    s.stage='complete' if not plan['needs_collection'] else plan['status']
    view=s.view();view.update(automatic_saved_answer_review=True,snapshot_kind='recovered_task_snapshot')
    db.merge(CollectionTrace(session_id=target.id,owner=target.user_id,payload=view))
    if has_collected_items(view):db.merge(ScreeningResult(session_id=target.id,owner=target.user_id,payload=view))


def recover_scoped_call(db,target,plan,rows):
    """Verify already-spoken answers during follow-up, within a single call."""
    from care_core import safety
    from .collection_sources import attach_sources_in_db
    from .screening import CollectionTrace, Screening, ScreeningResult, declines_collection
    from .screening_policy import CORE_TARGETS

    trace=db.get(CollectionTrace,target.id)
    if not trace or db.get(ScreeningResult,target.id):
        return False
    stage=trace.payload.get('stage')
    if stage not in ('checking_in','waiting_context','collecting') and not (
            stage=='declined' and plan.get('stop_reason')=='legacy_call_end'):
        return False
    if any(row.role=='user' and (declines_collection(row.content,question_pending=True)
            or safety(row.content)['safety_signal']=='explicit_danger_expression') for row in rows):
        return False
    controller=Screening(True,collection_policy().notice_version)
    controller.core_only=controller.direct_collection=True
    controller.target_scales=list(CORE_TARGETS)
    controller.stage='collecting'
    entries=[SimpleNamespace(message_id=row.external_message_id,role=row.role,text=row.content,final=True) for row in rows]
    controller.reconcile_demo_turns(entries)
    if not controller.answers or controller.stage in ('urgent','declined'):
        return False
    attach_sources_in_db(db,target.user_id,target.id,controller,{})
    controller.stage=plan['status']
    controller.history_danger_unresolved=plan.get('history_danger_unresolved',False)
    controller.window_end=datetime.fromisoformat(target.started_at).astimezone(
        timezone(timedelta(hours=8))).date().isoformat()
    controller.target_scales=[scale for scale in CORE_TARGETS
        if any(key.startswith(scale+':') for key in controller.answers)]
    controller.signals=list(dict.fromkeys(identifier for answer in controller.answers.values()
        for identifier in answer['evidence_ids']))
    controller.trigger_origin='saved_voice_answers'
    controller.detector=RECONCILIATION_VERSION
    view=controller.view()
    view.update(snapshot_kind='reconciled_session',automatic_saved_answer_review=True)
    db.add(ScreeningResult(session_id=target.id,owner=target.user_id,payload=view))
    return True


def scan(limit=100):
    if not collection_policy().enabled:return 0
    from .collection_plan import CollectionPlan,key as plan_key,read_plan_in_db,restore,store_plan_in_db
    from .screening import Screening,CollectionTrace,ScreeningResult,has_collected_items
    from .after_call import has_open_call
    changed=0
    with transaction(True) as db:
        # Bootstrap receipts for older saved calls, only when their episode matches.
        for trace,session in db.query(CollectionTrace,RecordSession).join(RecordSession,RecordSession.id==CollectionTrace.session_id).filter(RecordSession.state=='closed').order_by(RecordSession.id.desc()).limit(limit):
            if trace.owner!=session.user_id:continue
            if not trace.payload.get('episode_id'):continue
            if db.get(DemoAnswerReview,session.external_session_id) is None:
                db.add(DemoAnswerReview(external=session.external_session_id,owner=session.user_id,episode_id=trace.payload['episode_id'],window_end=trace.payload.get('window_end',''),state='pending',updated_at=now()))
        db.flush()
        jobs=db.query(DemoAnswerReview).join(RecordSession,(RecordSession.external_session_id==DemoAnswerReview.external)&(RecordSession.user_id==DemoAnswerReview.owner)).order_by(RecordSession.id.desc()).limit(limit).all()
        for job in jobs:
            target=db.query(RecordSession).filter_by(external_session_id=job.external,user_id=job.owner,source='doubao_realtime').first()
            if not target or target.state!='closed' or not summary(db,target)['is_complete'] or has_open_call(db,target):continue
            plan=read_plan_in_db(db,job.owner,bool(target.is_test))
            if not plan or plan['episode_id']!=job.episode_id or bool(plan.get('demo_mode'))!=collection_policy().demo_mode or plan['window_end']!=job.window_end:continue
            if plan.get('stop_reason')=='legacy_call_end':
                saved=db.get(CollectionPlan,plan_key(job.owner,bool(target.is_test)))
                if saved.payload['status']=='declined' and not saved.payload.get('stop_reason'):
                    saved.payload={**saved.payload,'status':plan['status'],'stop_reason':plan['stop_reason']}
                    saved.updated_at=now()
            rows=db.query(RecordMessage).filter_by(recording_session_id=target.id,text_status='completed').order_by(RecordMessage.sequence_no).all()
            drafts={row.id:effective(db,row) for row in rows}
            signature=hashlib.sha256(json.dumps(dict(version=RECONCILIATION_VERSION,episode=job.episode_id,window=job.window_end,status=plan['status'],answers=sorted(plan['answers']),
                rows=[(r.id,drafts[r.id]['input_revision'],drafts[r.id]['effective_content']) for r in rows]),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            if job.input_hash==signature:continue
            job.input_hash=signature;job.updated_at=now()
            if any(d['input_revision'] for d in drafts.values()):
                job.state='needs_revalidation';continue
            if (not plan.get('demo_mode') and (plan.get('history_danger_unresolved') or plan.get('stop_reason')=='legacy_call_end')
                    and plan['status'] not in ('declined','paused','urgent') and recover_scoped_call(db,target,plan,rows)):
                job.state='reviewed';changed+=1;continue
            if not plan['needs_collection']:
                mirror_missing(db,target,plan);job.state='complete';continue
            if plan['status'] in ('declined','paused','urgent','checking_in') or plan.get('history_danger_unresolved'):
                mirror_missing(db,target,plan);job.state='paused';continue
            s=Screening(True,collection_policy().notice_version);s.demo_mode=bool(plan.get('demo_mode'));s.direct_collection=True;restore(s,plan);s.stage='collecting'
            entries=[SimpleNamespace(message_id=r.external_message_id,role=r.role,text=drafts[r.id]['effective_content'],final=True) for r in rows]
            before=set(s.answers)
            s.reconcile_demo_turns(entries)
            missing_trace=db.get(CollectionTrace,target.id) is None
            missing_result=bool(s.answers) and db.get(ScreeningResult,target.id) is None
            if set(s.answers)!=before or s.stage in ('urgent','declined','paused') or missing_trace or missing_result:
                by_external={r.external_message_id:r for r in rows}
                from .collection_sources import identifiers
                for key in set(s.answers)-before:
                    answer=s.answers[key];refs=[]
                    for identifier in identifiers(answer):
                        row=by_external[identifier]
                        refs.append(dict(message_id=identifier,record_id=row.id,recording_session_id=target.id,input_revision=drafts[row.id]['input_revision']))
                    answer['source_refs']=refs
                if target.id not in s.history_session_ids:s.history_session_ids.append(target.id)
                store_plan_in_db(db,job.owner,bool(target.is_test),s)
                view=s.view();trace=db.get(CollectionTrace,target.id)
                if trace:
                    view={**trace.payload,**view,'transport_diagnostics':trace.payload.get('transport_diagnostics',{})}
                view['automatic_saved_answer_review']=True
                if missing_trace or missing_result:view['snapshot_kind']='recovered_task_snapshot'
                db.merge(CollectionTrace(session_id=target.id,owner=job.owner,payload=view))
                if has_collected_items(view):db.merge(ScreeningResult(session_id=target.id,owner=job.owner,payload=view))
                changed+=1
            job.state='reviewed'
    return changed
