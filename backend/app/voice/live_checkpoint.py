"""Coalesced live uploads and atomic, source-checked collection snapshots."""
import asyncio
from copy import deepcopy
import logging
from ..robot_records import RecordSession,transaction,now
from .collection_sources import attach_sources_in_db,answer_records
from .collection_plan import CollectionPlan,key
from .screening import CollectionTrace,ScreeningResult,has_collected_items
logger=logging.getLogger(__name__)


def save_checkpoint(uid,sid,controller,references):
    s=deepcopy(controller)
    with transaction(True) as db:
        session=db.get(RecordSession,sid)
        if not session or session.user_id!=uid or session.state=='deleted':raise ValueError('checkpoint_session_not_owned')
        if getattr(s,'collection_external_session_id',session.external_session_id)!=session.external_session_id:raise ValueError('checkpoint_session_mismatch')
        attach_sources_in_db(db,uid,sid,s,references)
        missing=[]
        for item,answer in list(s.answers.items()):
            rows,valid=answer_records(db,uid,session.is_test,answer)
            if not valid or not all(r.text_status=='completed' for r in rows):missing.append(item);s.answers.pop(item)
        plan=db.get(CollectionPlan,key(uid,session.is_test))
        if plan and plan.payload.get('episode_id')==s.episode_id:
            payload=deepcopy(plan.payload);changed=False
            for item,answer in s.answers.items():
                current=payload.get('answers',{}).get(item)
                if current and current.get('value')==answer['value'] and current.get('evidence_ids')==answer['evidence_ids'] and current.get('source_refs')!=answer.get('source_refs'):
                    current['source_refs']=answer['source_refs'];changed=True
            if changed:plan.payload=payload;plan.updated_at=now()
        if s.stage=='complete' and missing:s.stage='collecting'
        view=s.view();view.update(source_save_status='pending_sources' if missing else 'saved',snapshot_kind='live_checkpoint')
        trace=db.get(CollectionTrace,sid)
        if s.enabled and (not trace or trace.payload.get('version',-1)<=s.version):
            db.merge(CollectionTrace(session_id=sid,owner=uid,payload=view))
            if has_collected_items(view):db.merge(ScreeningResult(session_id=sid,owner=uid,payload=view))
        return dict(type='screening.saved',recording_session_id=sid,version=s.version,saved_at=now(),
            answered=sum(scale['answered'] for scale in view['scales']),required=sum(scale['required'] for scale in view['scales']),pending_answers=len(missing))


class LiveCheckpoint:
    def __init__(self,recorder,uid,controller,references,emit):
        self.recorder,self.uid,self.controller,self.references,self.emit=recorder,uid,controller,references,emit
        self.queue=asyncio.Queue(maxsize=1);self.closed=False;self.task=asyncio.create_task(self.run())
    def request(self):
        if self.closed:return
        if self.queue.full():self.queue.get_nowait()
        self.queue.put_nowait(deepcopy(self.controller))
    async def run(self):
        while True:
            s=await self.queue.get()
            if s is None:return
            try:
                result=await asyncio.to_thread(self.recorder.sync_partial,1.5)
                if result.get('recording_session_id'):
                    receipt=await asyncio.to_thread(save_checkpoint,self.uid,result['recording_session_id'],s,self.references)
                    await self.emit(receipt)
            except asyncio.CancelledError:raise
            except Exception:
                logger.warning('collection_live_checkpoint_deferred')
                from ..deployment import edge
                message=('服务器保存尚未确认，请保持网络连接；未确认的数据不会显示为已保存。' if edge() else
                         '采集原话已写入本地队列，正在等待后台同步；结束后会自动继续核对。')
                await self.emit(dict(type='screening.save_pending',message=message))
    async def close(self):
        self.closed=True
        await self.queue.put(None)
        await self.task
