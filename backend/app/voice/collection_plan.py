"""Persistent per-owner task. A new call or no-signal result never completes it."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import uuid
from sqlalchemy import Column,Integer,String,JSON,ForeignKey
from ..database import Base,SessionLocal
from ..robot_records import now,RecordSession,RecordMessage
from ..care.models import InputRevision
from .screening import ITEMS

class CollectionPlan(Base):
    __tablename__='robot_voice_collection_plans'
    key=Column(String(80),primary_key=True)
    owner=Column(Integer,ForeignKey('users.id'),nullable=False,index=True)
    payload=Column(JSON,nullable=False)
    updated_at=Column(String(32),nullable=False)

def key(uid,is_test):return f'{uid}:{int(is_test)}'

def read_plan(uid,is_test):
    with SessionLocal() as db:
        row=db.get(CollectionPlan,key(uid,is_test))
        if not row:return None
        data=deepcopy(row.payload)
        # Answers only survive if all original owned sources still exist and are unchanged.
        for item,answer in list(data.get('answers',{}).items()):
            from .collection_sources import answer_records
            _,valid=answer_records(db,uid,is_test,answer)
            if not valid:
                data['answers'].pop(item)
                data.update(needs_collection=True,status='needs_revalidation')
        if (datetime.now(timezone(timedelta(hours=8))).date()-datetime.fromisoformat(data['window_end']).date()).days>=14 and data.get('needs_collection'):
            data.update(answers={},status='needs_revalidation',window_end=datetime.now(timezone(timedelta(hours=8))).date().isoformat())
        data['updated_at']=row.updated_at
        return data

def restore(controller,data):
    if not data or not data.get('needs_collection'):return
    controller.episode_id=data['episode_id'];controller.window_end=data['window_end']
    controller.target_scales=list(data.get('target_scales',[]))
    controller.signals=list(data.get('signal_evidence',[]))
    controller.detector=data.get('detector_version')
    controller.answers=deepcopy(data.get('answers',{}))
    controller.history_danger_unresolved|=data.get('history_danger_unresolved',False)
    if data['status']=='declined':controller.stage='declined'
    elif data['status'] in ('urgent','checking_in') or controller.history_danger_unresolved:controller.stage='checking_in'
    else:controller.stage='waiting_context'

def store_plan(uid,is_test,controller):
    if not controller.enabled:return
    with SessionLocal() as db:
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
        if not controller.episode_id:controller.episode_id=uuid.uuid4().hex
        if not controller.window_end:
            controller.window_end=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        complete=bool(controller.target_scales) and all(f'{s}:{i+1}' in controller.answers for s in controller.target_scales for i in range(len(ITEMS[s])))
        status='complete' if complete else controller.stage
        payload=dict(needs_collection=not complete,status=status,episode_id=controller.episode_id,
            window_end=controller.window_end,target_scales=controller.target_scales,answers=controller.answers,
            signal_evidence=controller.signals,history_danger_unresolved=controller.history_danger_unresolved or controller.stage=='urgent',
            detector_version=controller.detector,
            history_session_ids=controller.history_session_ids,observations=controller.observations,formal_assessment=False,
            completed_at=now() if complete else None)
        db.merge(CollectionPlan(key=key(uid,is_test),owner=uid,payload=deepcopy(payload),updated_at=now()))
        db.commit()

def public_plan(uid,is_test):
    data=read_plan(uid,is_test)
    if not data:return dict(needs_collection=False,status='no_task',scales=[])
    return dict(needs_collection=data['needs_collection'],status=data['status'],episode_id=data['episode_id'],
        window_end=data['window_end'],formal_assessment=False,
        scales=[dict(scale=s,answered=sum(f'{s}:{i+1}' in data['answers'] for i in range(len(ITEMS[s]))),required=len(ITEMS[s])) for s in data['target_scales']])

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
