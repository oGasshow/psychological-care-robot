"""Persistent per-owner task. A new call or no-signal result never completes it."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import uuid
from sqlalchemy import Column,Integer,String,JSON,ForeignKey
from ..database import Base,SessionLocal
from ..robot_records import now,RecordSession,RecordMessage
from ..care.models import InputRevision
from .screening import CollectionTrace,ITEMS,SCALE_LABELS,OPTIONS_BY_SCALE,declines_collection
from .screening_policy import CORE_TARGETS
from .transcripts import explicit_end_request

class CollectionPlan(Base):
    __tablename__='robot_voice_collection_plans'
    key=Column(String(80),primary_key=True)
    owner=Column(Integer,ForeignKey('users.id'),nullable=False,index=True)
    payload=Column(JSON,nullable=False)
    updated_at=Column(String(32),nullable=False)

def key(uid,is_test):return f'{uid}:{int(is_test)}'

def has_saved_answers(uid,is_test):
    """Check before source validation, so queued sources can be recovered first."""
    with SessionLocal() as db:
        row=db.get(CollectionPlan,key(uid,is_test))
        return bool(row and row.payload.get('answers'))

def read_plan(uid,is_test):
    with SessionLocal() as db:
        return read_plan_in_db(db,uid,is_test)


def repair_legacy_stop(db,uid,is_test,data):
    """Only repair the old stop when its original transcript proves a call sign-off."""
    if data['status']!='declined' or data.get('demo_mode') or data.get('stop_reason'):
        return
    stopped=db.query(CollectionTrace,RecordSession).join(RecordSession).filter(
        CollectionTrace.owner==uid,RecordSession.user_id==uid,RecordSession.is_test==is_test,
        RecordSession.state=='closed',RecordSession.source=='doubao_realtime',
        CollectionTrace.payload['episode_id'].as_string()==data['episode_id'],
        CollectionTrace.payload['stage'].as_string()=='declined',
    ).order_by(RecordSession.id).all()
    if not stopped or stopped[0][0].payload.get('review_mode') is not None:
        return
    rows=db.query(RecordMessage).filter(RecordMessage.recording_session_id.in_([s.id for _,s in stopped]),
        RecordMessage.role=='user',RecordMessage.text_status=='completed').order_by(
        RecordMessage.recording_session_id,RecordMessage.sequence_no).all()
    first_call=[row for row in rows if row.recording_session_id==stopped[0][1].id]
    if (not first_call or not explicit_end_request(first_call[-1].content)
            or '不想聊' not in first_call[-1].content
            or any(declines_collection(row.content,question_pending=True) or db.get(InputRevision,row.id) for row in rows)):
        return
    data['status']='checking_in' if data.get('history_danger_unresolved') else 'waiting_context'
    data['stop_reason']='legacy_call_end'


def read_plan_in_db(db,uid,is_test):
    row=db.get(CollectionPlan,key(uid,is_test))
    if not row:return None
    data=deepcopy(row.payload)
    repair_legacy_stop(db,uid,is_test,data)
    # Answers only survive if all original owned sources still exist and are unchanged.
    for item,answer in list(data.get('answers',{}).items()):
        from .collection_sources import answer_records
        _,valid=answer_records(db,uid,is_test,answer)
        if not valid:
            data['answers'].pop(item)
            data['needs_collection']=True
            if data['status'] not in ('declined','paused'):data['status']='needs_revalidation'
    if (datetime.now(timezone(timedelta(hours=8))).date()-datetime.fromisoformat(data['window_end']).date()).days>=14 and data.get('needs_collection'):
        data.update(answers={},window_end=datetime.now(timezone(timedelta(hours=8))).date().isoformat())
        if data['status'] not in ('declined','paused'):data['status']='needs_revalidation'
    data['updated_at']=row.updated_at
    return data

def restore(controller,data):
    if not data:return
    completed_task=bool(controller.streamlined and not data.get('needs_collection') and data.get('status')=='complete'
        and not data.get('history_danger_unresolved')
        and (datetime.now(timezone(timedelta(hours=8))).date()-datetime.fromisoformat(data['window_end']).date()).days<14)
    if not data.get('needs_collection') and not completed_task:return
    controller.episode_id=data['episode_id'];controller.window_end=data['window_end']
    controller.target_scales=list(data.get('target_scales',[]))
    if controller.core_only and not completed_task:
        controller.target_scales=[scale for scale in controller.target_scales if scale in CORE_TARGETS]
    controller.signals=list(data.get('signal_evidence',[]))
    controller.detector=data.get('detector_version')
    controller.trigger_origin=data.get('trigger_origin','context_model')
    controller.stop_reason=data.get('stop_reason')
    controller.answers=deepcopy(data.get('answers',{}))
    controller.history_danger_unresolved|=data.get('history_danger_unresolved',False)
    if completed_task:controller.stage='complete'
    elif data['status']=='declined':controller.stage='declined'
    elif data['status'] in ('urgent','checking_in') or controller.history_danger_unresolved:controller.stage='checking_in'
    elif controller.core_only and data['status']=='paused':controller.stage='paused'
    elif controller.core_only and not controller.target_scales:controller.stage='companionship'
    else:controller.stage='waiting_context'

def store_plan(uid,is_test,controller):
    with SessionLocal() as db:
        store_plan_in_db(db,uid,is_test,controller)
        db.commit()

def store_plan_in_db(db,uid,is_test,controller):
    if not controller.enabled:return
    previous=db.get(CollectionPlan,key(uid,is_test))
    if not (controller.triggered or controller.stage in ('urgent','checking_in') or previous and previous.payload.get('needs_collection')):return
    if previous and previous.payload.get('needs_collection') and controller.episode_id is None:
        old=previous.payload
        controller.episode_id=old['episode_id'];controller.window_end=old['window_end']
        controller.answers={**old.get('answers',{}),**controller.answers}
        controller.target_scales=list(dict.fromkeys([*old.get('target_scales',[]),*controller.target_scales]))
        controller.signals=list(dict.fromkeys([*old.get('signal_evidence',[]),*controller.signals]))
        controller.history_danger_unresolved|=old.get('history_danger_unresolved',False)
        if controller.stage=='companionship':controller.stage='waiting_context'
    if controller.core_only:
        controller.target_scales=[scale for scale in controller.target_scales if scale in CORE_TARGETS]
    if not controller.episode_id:controller.episode_id=uuid.uuid4().hex
    if not controller.window_end:
        controller.window_end=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    complete=bool(controller.target_scales) and controller.stage not in ('urgent','checking_in') and all(f'{s}:{i+1}' in controller.answers for s in controller.target_scales for i in range(len(ITEMS[s])))
    status='complete' if complete else controller.stage
    payload=dict(needs_collection=not complete,status=status,episode_id=controller.episode_id,
        window_end=controller.window_end,target_scales=controller.target_scales,answers=controller.answers,
        signal_evidence=controller.signals,history_danger_unresolved=controller.history_danger_unresolved or controller.stage=='urgent',
        demo_mode=controller.demo_mode,trigger_origin=controller.trigger_origin,stop_reason=controller.stop_reason,
        detector_version=controller.detector,
        history_session_ids=controller.history_session_ids,observations=controller.observations,formal_assessment=False,
        completed_at=now() if complete else None)
    db.merge(CollectionPlan(key=key(uid,is_test),owner=uid,payload=deepcopy(payload),updated_at=now()))
    if controller.streamlined and getattr(controller,'collection_external_session_id',None):
        from .demo_reconciliation import register_in_db
        register_in_db(db,uid,controller.collection_external_session_id,controller)

def public_plan(uid,is_test,*,db=None):
    data=read_plan_in_db(db,uid,is_test) if db is not None else read_plan(uid,is_test)
    if not data:return dict(needs_collection=False,status='no_task',scales=[])
    return dict(needs_collection=data['needs_collection'],status=data['status'],episode_id=data['episode_id'],
        window_end=data['window_end'],formal_assessment=False,
        scales=[dict(scale=s,**(dict(total=sum(data['answers'][f'{s}:{i+1}']['value'] for i in range(len(ITEMS[s]))) if all(f'{s}:{i+1}' in data['answers'] for i in range(len(ITEMS[s]))) else None,max_score=len(ITEMS[s])*(len(OPTIONS_BY_SCALE[s])-1)) if data.get('demo_mode') else {}),**({'display_name':SCALE_LABELS[s]} if s not in ('PHQ-9','GAD-7') else {}),
            answered=sum(f'{s}:{i+1}' in data['answers'] for i in range(len(ITEMS[s]))),required=len(ITEMS[s]))
            for s in data['target_scales']])

def backfill_recent_plans():
    """Bootstrap existing owned voice history without inventing scale answers."""
    from .screening_policy import collection_policy
    from .screening import Screening
    from .continuity import recent_context
    try:policy=collection_policy()
    except ValueError:return
    if not policy.enabled:return
    with SessionLocal() as db:
        pairs=db.query(RecordSession.user_id,RecordSession.is_test).filter(RecordSession.state=='closed',
            RecordSession.external_session_id.startswith('voice_')).distinct().all()
    for uid,is_test in pairs:
        if read_plan(uid,is_test) is not None:continue
        context=recent_context(uid,is_test=is_test)
        if not context['danger_history']:continue
        controller=Screening(True,policy.notice_version);controller.inherit(context)
        store_plan(uid,is_test,controller)
