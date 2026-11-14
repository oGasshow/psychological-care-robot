"""Owner-authenticated browser/device bridge; cloud credentials stay server-side."""
import asyncio
import base64
from contextlib import suppress
import json
import logging
import os
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import Annotated, Literal
from ..database import SessionLocal
from ..robot_records import owner, RecordError
from . import upstream
from .settings import settings
from .recording import Recorder, directory as outbox_directory, internal_base, retry
from .transcripts import Transcripts, Utterance, utc_now
from .screening import Screening, ScreeningResult, save_result, has_collected_items
from .screening_policy import CollectionPolicy, collection_policy, collection_targets
from .screening_monitor import ScreeningMonitor
from .collection_plan import read_plan,restore,store_plan,public_plan,has_saved_answers
from .continuity import recent_context
from . import sega
from .after_call import public_reviews, AfterCallReview,touch_live_call,end_live_call

router=APIRouter(prefix='/api/robot-voice',tags=['Doubao voice'])
logger=logging.getLogger(__name__)
ACTIVE=set()
RUNTIMES={}
BACKGROUND_TASKS=set()


async def retry_outboxes_background(uid,token,base,current_path):
    try:
        paths=await asyncio.to_thread(lambda:tuple(
            path for path in outbox_directory(uid).glob('voice_*.sqlite')
            if path.resolve()!=current_path.resolve()))
        result=await asyncio.to_thread(retry,uid,token,base,paths)
        if result.get('pending'):
            logger.info('voice_outbox_retry_deferred pending=%s',result['pending'])
    except Exception:
        logger.warning('voice_outbox_background_retry_failed')


def schedule_outbox_retry(uid,token,base,current_path):
    task=asyncio.create_task(retry_outboxes_background(uid,token,base,current_path))
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(BACKGROUND_TASKS.discard)


@router.get('/diagnostics')
async def diagnostics(response:Response,uid=Depends(owner)):
    """Read-only owner diagnostics; never triggers a model or returns excerpts/keys."""
    response.headers['Cache-Control']='no-store'
    runtime=RUNTIMES.get(uid)
    try:enabled=collection_policy().enabled
    except (ValueError,TypeError):enabled=False
    if not runtime:
        return dict(active=False,conditional_collection_enabled=enabled,message='当前没有正在进行的语音会话。')
    controller=runtime['controller'];monitor=runtime.get('monitor')
    decision=controller.decisions[-1]['decision'] if controller.decisions else None
    count=monitor.user_count if monitor else 0
    applied=runtime.get('applied_policy_version')
    error_messages={
        'context_detector_timeout':'后台判断超时；没有据此启动采集。继续交流后会重试。',
        'context_detector_authentication_failed':'后台判断服务认证失败；没有据此启动采集。请检查服务配置。',
        'context_detector_transport_unavailable':'后台判断服务连接失败；没有据此启动采集。继续交流后会重试。',
        'context_detector_provider_error':'后台判断服务返回错误；没有据此启动采集。继续交流后会重试。',
        'context_detector_invalid_output':'后台判断结果格式或原话依据未通过核验；没有据此启动采集。继续交流后会重试。',
        'context_detector_unavailable':'后台判断暂不可用；没有据此启动采集。继续交流后会重试。',
        'answer_candidate_timeout':'本轮自然回答整理超时；不会记为已确认条目。',
        'answer_candidate_invalid':'本轮自然回答未通过原话或频率范围核验；不会记为已确认条目。',
        'answer_candidate_unavailable':'本轮自然回答整理暂不可用；不会记为已确认条目。',
        'answer_candidate_superseded':'回答期间收到了新内容，旧候选已丢弃，正在核对最新对话。',
    }
    last_error=monitor.last_error_code if monitor else None
    if last_error in error_messages:message=error_messages[last_error]
    elif not controller.enabled:message='本次会话未启用后台信息采集。'
    elif controller.review_mode=='post_session' and not controller.triggered:message='本次新出现的关注线索会在结束并保存后后台复核；不会让当前语音等待判定。'
    elif controller.stage=='collecting':message='豆包已确认采集指令，可继续自然交流。' if applied==controller.version else '采集任务已下发，正在等待豆包确认。'
    elif controller.stage=='waiting_context':message='已有进一步了解的线索，正在等待适合自然过渡的对话时机。'
    elif controller.stage=='checking_in':message='已带入历史关注任务，先了解当前感受，不因换通话清除任务。'
    elif controller.stage in ('paused','declined','urgent','complete'):message='本次采集已暂停或结束，不会强行继续。'
    elif monitor and monitor.in_flight:message='正在后台核查对话，语音交流可以继续。'
    elif controller.detector_status=='unavailable':message='后台检测暂未完成，请稍后再试；没有据此启动采集。'
    elif count<3:message=f'已收到 {count} 段用户最终转录；至少 3 段后才进行首次后台检测。'
    else:message='本次尚未触发进一步采集；关于系统功能的提问不等于症状自述。'
    raw_transport=controller.transport_diagnostics
    transport={key:raw_transport.get(key) for key in ('audio_frames','remote_events','last_remote_event',
        'last_client_command','capture_gap_count','session_ready_ms','last_final_role')}
    for source,target in (('last_remote_event_at','last_remote_event_age_seconds'),
                          ('last_final_at','last_final_age_seconds')):
        stamp=raw_transport.get(source)
        transport[target]=max(0,round(time.monotonic()-stamp,1)) if isinstance(stamp,(int,float)) else None
    return dict(active=True,conditional_collection_enabled=controller.enabled,session_id=runtime['session_id'],
                concern_review_mode=controller.review_mode,
                stage=controller.stage,user_turns=count,first_check_min_turns=3,
                checked_user_turns=monitor.checked_count if monitor else 0,
                detector_running=bool(monitor and monitor.in_flight),detector_status=controller.detector_status,
                last_decision=decision,target_scales=controller.target_scales,
                sent_policy_version=runtime.get('sent_policy_version'),applied_policy_version=applied,
                transport=transport,
                last_error_code=last_error,message=message)

@router.get('/collection-plan')
def collection_plan(response:Response,uid=Depends(owner)):
    response.headers['Cache-Control']='no-store'
    return public_plan(uid,test_data())

@router.get('/after-call-reviews')
def after_call_reviews(response:Response,uid=Depends(owner)):
    response.headers['Cache-Control']='no-store'
    return dict(items=public_reviews(uid,test_data()))

@router.post('/after-call-reviews/{sid}/retry')
def retry_after_call_review(sid:int,response:Response,uid=Depends(owner)):
    from ..robot_records import owned,transaction
    from fastapi import HTTPException
    response.headers['Cache-Control']='no-store'
    with transaction(True) as db:
        owned(db,sid,uid)
        row=db.get(AfterCallReview,sid)
        if row is None or row.owner!=uid:raise HTTPException(404,'review_not_found')
        if row.state not in ('failed','retry_wait','invalidated'):raise HTTPException(409,'review_not_retryable')
        row.state,row.attempt='pending',0
        row.error_code=row.next_retry_at=row.execution_token=row.lease_until=None
    return dict(status='queued')

@router.get('/sega/status')
def sega_status(response:Response,uid=Depends(owner)):
    response.headers['Cache-Control']='no-store'
    return dict(**sega.status(),probe_allowed=test_data())

@router.post('/sega/probe')
async def sega_probe(response:Response,uid=Depends(owner)):
    from fastapi import HTTPException
    if not test_data():raise HTTPException(404,'not_found')
    response.headers['Cache-Control']='no-store'
    return await asyncio.to_thread(sega.execute,fixture=True)

@router.get('/sega/sessions/{sid}')
def sega_session(sid:int,response:Response,uid=Depends(owner)):
    response.headers['Cache-Control']='no-store'
    return sega.session_status(uid,sid)

@router.post('/sega/sessions/{sid}')
async def sega_analyze(sid:int,request:Request,response:Response,uid=Depends(owner)):
    response.headers['Cache-Control']='no-store'
    return await sega.analyze_features(uid,sid,request)

class Authenticate(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    type:Literal['authenticate']
    token:Annotated[str,Field(min_length=10,max_length=8192)]
    device_id:Annotated[str,Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')]='browser_audio'
    guided_screening:bool|None=None  # Accepted for older clients; not an authorization gate.

class ConcernSignal(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    session_id:Annotated[str,Field(min_length=1,max_length=100)]
    evidence_ids:Annotated[list[str],Field(min_length=1,max_length=20)]
    detector_version:Annotated[str,Field(min_length=1,max_length=100)]
    target_scales:Annotated[list[Literal['PHQ-9','GAD-7','mood_interest','worry_anxiety',
        'stress_load','sleep_wellbeing','coping_resources','social_comfort']],Field(min_length=1,max_length=8)]=Field(default_factory=collection_targets)

@router.post('/screening-signal')
async def screening_signal(body:ConcernSignal,uid=Depends(owner)):
    from fastapi import HTTPException
    runtime=RUNTIMES.get(uid)
    if not runtime or runtime['session_id']!=body.session_id:raise HTTPException(404,'active_session_not_found')
    known={u.message_id for u in runtime['transcripts'].users.values() if u.final}
    if not set(body.evidence_ids)<=known:raise HTTPException(422,'unknown_user_evidence')
    if not runtime['controller'].enabled:raise HTTPException(409,'guided_collection_not_enabled')
    if runtime['queue'].full():raise HTTPException(429,'screening_signal_queue_full')
    await runtime['queue'].put(body)
    return dict(status='queued',applied=False)

@router.get('/screening-results/{sid}')
def screening_result(sid:int,response:Response,uid=Depends(owner)):
    from ..robot_records import owned
    response.headers['Cache-Control']='no-store'
    with SessionLocal() as db:
        owned(db,sid,uid)
        value=db.get(ScreeningResult,sid)
        if not value or value.owner!=uid or not has_collected_items(value.payload):
            return dict(result=None)
        from ..care.collection_history import collection_history
        public=collection_history(db,uid,session_ids=[sid],limit=1)[0]
        return dict(result={**value.payload,'scales':public['scales'],'source_status':public['source_status']})

def test_data():
    return os.getenv('APP_ENV','production')!='production' or os.getenv('ROBOT_CARE_DEMO_DATABASE')=='true'

@router.get('/config')
def config(response:Response,uid=Depends(owner)):
    response.headers['Cache-Control']='no-store'
    try:
        cfg=settings()
        enabled=cfg.enabled and bool(cfg.api_key)
        limit=cfg.session_seconds
    except (ValueError,TypeError):
        enabled,limit=False,900
    try:
        policy=collection_policy();conditional_enabled=policy.enabled;review_mode=policy.review_mode
    except (ValueError,TypeError):conditional_enabled,review_mode=False,'post_session'
    return dict(enabled=enabled,input_rate=16000,output_rate=24000,frame_bytes=640,
                session_seconds=limit,is_test=test_data(),protocol='voice-bridge-v1',
                conditional_collection_enabled=conditional_enabled,
                concern_review_mode=review_mode,
                message='可以开始语音对话。' if enabled else '语音服务尚未配置，请联系项目维护人员。')

@router.post('/retry-records')
def retry_records(request:Request,response:Response,uid=Depends(owner)):
    response.headers['Cache-Control']='no-store'
    if uid in ACTIVE:
        from ..care.service import CareError
        raise CareError(409,'voice_session_active')
    token=request.headers['authorization'].split(' ',1)[1]
    return retry(uid,token,internal_base(request.scope))

def authenticate_token(token):
    with SessionLocal() as db:
        return owner(HTTPAuthorizationCredentials(scheme='Bearer',credentials=token),db)

def origin_allowed(ws):
    origin=ws.headers.get('origin')
    if not origin:return True  # Native/Pi clients still require the same JWT.
    parsed=urlsplit(origin)
    allowed={x.strip() for x in os.getenv('ROBOT_CARE_VOICE_ALLOWED_ORIGINS','').split(',') if x.strip()}
    host=urlsplit('http://'+ws.headers.get('host','')).hostname
    return parsed.scheme in ('http','https') and (origin in allowed or parsed.hostname==host or
        parsed.hostname in ('localhost','127.0.0.1','::1') and host in ('localhost','127.0.0.1','::1'))

@router.websocket('/live')
async def live(ws:WebSocket):
    if not origin_allowed(ws):
        await ws.close(code=4403);return
    await ws.accept()
    uid=None;reserved=False;recorder=None;state=Transcripts();client_closed=False;controller=Screening()
    session_end_code='normal';review_lease=False
    async def emit(value):
        nonlocal client_closed
        if client_closed:return
        try:await ws.send_json(value)
        except (WebSocketDisconnect,RuntimeError):client_closed=True
    async def persist(entry):
        if recorder and entry and entry.text.strip() and not entry.recorded:
            await asyncio.to_thread(recorder.enqueue,entry)
    try:
        raw=await asyncio.wait_for(ws.receive_text(),8)
        if len(raw)>10000:raise ValueError('invalid_authentication_frame')
        auth=Authenticate.model_validate_json(raw)
        try:policy=collection_policy()
        except (ValueError,TypeError):policy=CollectionPolicy(False,'','doubao_realtime')
        controller=Screening(policy.enabled,policy.notice_version)
        controller.review_mode=policy.review_mode
        uid=await asyncio.to_thread(authenticate_token,auth.token)
        if uid in ACTIVE:
            await emit(dict(type='error',code='voice_session_active',message='已有语音会话正在进行，请先结束另一处会话。'));return
        ACTIVE.add(uid);reserved=True
        cfg=settings()
        if not cfg.enabled or not cfg.api_key:
            await emit(dict(type='error',code='voice_not_configured',message='语音服务尚未配置。'));return
        startup_started=time.monotonic()
        base=internal_base(ws.scope)
        await emit(dict(type='status',state='connecting',message='正在连接豆包语音…'))
        if controller.enabled:
            # Confirmed answers may still refer to a previous call's outbox.
            # Recover those sources before read_plan validates and store_plan
            # persists the resumed task. Calls with no answers keep fast startup.
            if await asyncio.to_thread(has_saved_answers,uid,test_data()):
                recovery=await asyncio.to_thread(retry,uid,auth.token,base)
                if recovery.get('pending'):
                    await emit(dict(type='error',code='record_recovery_pending',
                        message='上次对话的原话仍待保存，请先重试保存后再继续，已采集进度会保留。'))
                    return
            plan=await asyncio.to_thread(read_plan,uid,test_data())
            context=await asyncio.to_thread(recent_context,uid,is_test=test_data(),
                after=plan.get('completed_at') if plan and not plan['needs_collection'] else None)
            controller.inherit(context)
            restore(controller,plan)
        else:context={'turns':[],'references':{}}
        async with upstream.connection(cfg,instructions=controller.instructions()) as (remote,created):
            await remote.send(json.dumps({'type':'input_audio_mute.commit'}))
            recorder=await asyncio.to_thread(Recorder,uid,auth.token,base,is_test=test_data(),device_id=auth.device_id)
            if controller.enabled and controller.review_mode=='post_session':
                await asyncio.to_thread(touch_live_call,uid,test_data(),recorder.external)
                review_lease=True
            queue=asyncio.Queue(maxsize=16);pending_versions=[]
            transport=dict(audio_frames=0,remote_events=0,last_remote_event=None,last_client_command=None,
                           capture_gap_count=0,last_remote_event_at=None,last_final_role=None,last_final_at=None)
            controller.transport_diagnostics=transport
            last_frame=time.monotonic();mic_enabled=False
            RUNTIMES[uid]=dict(session_id=recorder.external,queue=queue,controller=controller,transcripts=state,
                               sent_policy_version=None,applied_policy_version=None)
            async def update_policy():
                await asyncio.to_thread(store_plan,uid,test_data(),controller)
                payload=upstream.session_payload(cfg,instructions=controller.instructions())
                payload['type']='session.update'
                pending_versions.append(controller.version)
                RUNTIMES[uid]['sent_policy_version']=controller.version
                await remote.send(json.dumps(payload,ensure_ascii=False))
                await emit(controller.public_status())
            async def receive_control():
                while True:
                    signal=await queue.get()
                    controller.concern(signal.evidence_ids,signal.detector_version,signal.target_scales)
                    await update_policy()
            monitor=ScreeningMonitor(controller,update_policy,provider=policy.detector,emit=emit,history=context['turns'])
            RUNTIMES[uid]['monitor']=monitor
            review_tasks=set()
            checkpoint_uploads=set()
            async def review_checkpoint(snapshot_hash,start_user_count):
                sync_task=asyncio.create_task(asyncio.to_thread(recorder.sync_partial,3.5))
                checkpoint_uploads.add(sync_task)
                sync_task.add_done_callback(checkpoint_uploads.discard)
                try:
                    await interrupt('review_checkpoint')
                    await remote.send(json.dumps({'type':'speech_text_buffer.commit',
                        'text':'我先把咱们刚才聊的内容梳理一下，稍等我一小会儿，马上回来跟你接着说。'},ensure_ascii=False))
                    completed=await monitor.wait_for_snapshot(snapshot_hash,3.8)
                    if (not completed or monitor.last_error_code) and controller.stage=='reviewing':
                        controller.review_status='pending'
                        controller.stage='companionship'
                        controller.version+=1
                        await update_policy()
                    # The same live call remains available throughout. If the
                    # person spoke during review, let the model answer them and
                    # do not inject a competing scripted greeting.
                    if monitor.user_count==start_user_count:
                        await interrupt('review_return')
                        await remote.send(json.dumps({'type':'speech_text_buffer.commit',
                            'text':'你好呀，我回来了，我们继续吧。'},ensure_ascii=False))
                except (WebSocketDisconnect,upstream.VoiceServiceError):
                    return
            if controller.enabled:await update_policy()
            transport['session_ready_ms']=round((time.monotonic()-startup_started)*1000)
            logger.info('voice_session_ready latency_ms=%s',transport['session_ready_ms'])
            await emit(dict(type='session.ready',session_id=recorder.external,input_rate=16000,output_rate=24000,
                            is_test=test_data(),protocol='voice-bridge-v1'))
            # Scan and retry older outboxes in the background. Exclude the live
            # session database so recovery can never close the current call.
            schedule_outbox_retry(uid,auth.token,base,recorder.box.path)
            greeting=Utterance('greeting','assistant','turn_0',text=upstream.GREETING,final=True,occurred_at=utc_now())
            state.responses['greeting']=greeting;state.active_response='greeting'
            await persist(greeting);await emit(greeting.public(True))
            await remote.send(json.dumps({'type':'speech_text_buffer.commit','text':upstream.GREETING},ensure_ascii=False))
            finishing=asyncio.Event()
            async def interrupt(reason):
                entries=state.interrupt()
                await emit(dict(type='playback.clear',reason=reason))
                for entry in entries:
                    if not entry.recorded and entry.text.strip():
                        await persist(entry);await emit(entry.public(True))
                if entries:
                    await remote.send(json.dumps({'type':'response.cancel'}))
            async def receive_remote():
                closing_response=None
                closing_announced=False
                async for raw_event in remote:
                    event=upstream.decode_event(raw_event);kind=event['type']
                    transport['remote_events']+=1;transport['last_remote_event']=kind
                    transport['last_remote_event_at']=time.monotonic()
                    if kind=='session.updated' and pending_versions:
                        applied=pending_versions.pop(0)
                        RUNTIMES[uid]['applied_policy_version']=applied
                        await emit(dict(type='screening.policy_applied',version=applied))
                    if kind=='conversation.item.input_audio_transcription.started':
                        closing_response=None
                        closing_announced=False
                        controller.end_after_response=False
                        await interrupt('user_started_speaking')
                    entry,public=state.apply(event)
                    if public:
                        if public['type']=='transcript.final':
                            transport['last_final_role']=entry.role
                            transport['last_final_at']=time.monotonic()
                            await persist(entry)
                            version=controller.version;controller.observe(entry)
                            monitor.observe(entry)
                            if version!=controller.version:await update_policy()
                            if entry.role=='user' and controller.stage=='reviewing' and not review_tasks:
                                snapshot_hash=monitor.snapshot()['source_snapshot_hash']
                                task=asyncio.create_task(review_checkpoint(snapshot_hash,monitor.user_count))
                                review_tasks.add(task);task.add_done_callback(review_tasks.discard)
                        await emit(public)
                    if kind.startswith('response.output_') and entry and not entry.interrupted and controller.end_after_response and not closing_announced:
                        closing_response=closing_response or entry.message_id
                    if kind=='response.output_audio.delta' and entry and not entry.interrupted:
                        encoded=event.get('delta','')
                        pcm=base64.b64decode(encoded,validate=True)
                        if len(pcm)%2 or len(pcm)>256000:raise ValueError('invalid_provider_audio')
                        await emit(dict(type='audio.delta',message_id=entry.message_id,audio=encoded,rate=24000))
                    elif kind=='response.output_audio.done' and entry and not entry.interrupted:
                        await emit(dict(type='audio.done',message_id=entry.message_id))
                        if controller.end_after_response and closing_response==entry.message_id:
                            closing_announced=True
                            await emit(dict(type='dialogue.finished'))
                            # Browser acknowledges finish after its queued audio
                            # drains. Closing the socket here truncates playback.
                            closing_response=None
                    elif kind=='response.canceled':
                        await emit(dict(type='status',state='interrupted',message='已打断旧回复，可以继续说。'))
                    elif kind=='session.closed':break
            async def receive_client():
                nonlocal client_closed,last_frame,mic_enabled
                while True:
                    packet=await ws.receive()
                    if packet['type']=='websocket.disconnect':
                        client_closed=True
                        finishing.set();return
                    if packet.get('bytes') is not None:
                        pcm=packet['bytes']
                        if len(pcm)!=640:raise ValueError('invalid_audio_frame')
                        if not mic_enabled:
                            await remote.send(json.dumps({'type':'input_audio_unmute.commit'}));mic_enabled=True
                        last_frame=time.monotonic();transport['audio_frames']+=1
                        await remote.send(json.dumps({'type':'input_audio_buffer.append','audio':base64.b64encode(pcm).decode('ascii')}))
                        continue
                    text=packet.get('text','')
                    if len(text)>2000:raise ValueError('invalid_control_frame')
                    command=json.loads(text)
                    if not isinstance(command,dict):raise ValueError('invalid_control_frame')
                    kind=command.get('type')
                    transport['last_client_command']=kind
                    if kind=='finish':finishing.set();return
                    if kind=='screening.action':
                        action=command.get('action')
                        if action not in ('decline','pause'):raise ValueError('invalid_screening_action')
                        line=Utterance('screening_action_'+__import__('uuid').uuid4().hex,'user','screening_control',
                            text={'decline':'我不想继续信息采集。','pause':'我想先暂停信息采集。'}[action],final=True,occurred_at=utc_now())
                        await persist(line);await emit(line.public(True))
                        controller.action(action)
                        await update_policy();continue
                    if kind=='interrupt':await interrupt('manual')
                    elif kind in ('mute','unmute'):
                        mic_enabled=kind=='unmute';last_frame=time.monotonic()
                        await remote.send(json.dumps({'type':'input_audio_mute.commit' if kind=='mute' else 'input_audio_unmute.commit'}))
                    elif kind=='commit':await remote.send(json.dumps({'type':'input_audio_buffer.commit'}))
                    elif kind=='playback':
                        # Client scheduling is visible live. Saved immutable text
                        # remains unknown unless interruption was already known.
                        if command.get('state') in ('playing','completed','interrupted'):
                            await emit(dict(type='playback.status',state=command['state'],message_id=str(command.get('message_id',''))[:100]))
                    elif kind not in ('interrupt','mute','unmute','commit'):
                        raise ValueError('unsupported_voice_command')
            async def capture_guard():
                nonlocal mic_enabled
                lease_touch=time.monotonic()
                while True:
                    await asyncio.sleep(2)
                    if review_lease and time.monotonic()-lease_touch>10:
                        await asyncio.to_thread(touch_live_call,uid,test_data(),recorder.external)
                        lease_touch=time.monotonic()
                    if mic_enabled and time.monotonic()-last_frame>6:
                        await remote.send(json.dumps({'type':'input_audio_mute.commit'}));mic_enabled=False
                        transport['capture_gap_count']=transport.get('capture_gap_count',0)+1
                        await emit(dict(type='status',state='capture_paused',message='收音数据暂时中断，已暂停上行；恢复收音后继续，或重新连接。'))
            receiver=asyncio.create_task(receive_remote())
            client=asyncio.create_task(receive_client())
            deadline=asyncio.create_task(asyncio.sleep(cfg.session_seconds))
            control=asyncio.create_task(receive_control())
            detector=asyncio.create_task(monitor.run())
            guard=asyncio.create_task(capture_guard())
            try:
                done,_=await asyncio.wait([receiver,client,deadline,control,detector,guard],return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task is not deadline and not task.cancelled() and task.exception():raise task.exception()
                if deadline in done:await emit(dict(type='status',state='time_limit',message='本次语音已到时限，正在保存记录。'))
                if not receiver.done():
                    if state.active_user and not state.users[state.active_user].final:
                        await remote.send(json.dumps({'type':'input_audio_buffer.commit'}))
                    await remote.send(json.dumps({'type':'input_audio_mute.commit'}))
                    # A small drain retains final ASR/text already in flight.
                    await asyncio.sleep(.6)
                    await remote.send(json.dumps({'type':'session.close'}))
                    with suppress(TimeoutError):await asyncio.wait_for(asyncio.shield(receiver),2)
            finally:
                for task in (receiver,client,deadline,control,detector,guard,*review_tasks):task.cancel()
                await asyncio.gather(receiver,client,deadline,control,detector,guard,*review_tasks,return_exceptions=True)
                if checkpoint_uploads:
                    await asyncio.gather(*checkpoint_uploads,return_exceptions=True)
    except RecordError:
        session_end_code='authentication_required'
        await emit(dict(type='error',code='authentication_required',message='登录已失效，请重新登录。'))
    except (ValidationError,ValueError,TypeError,KeyError):
        session_end_code='voice_protocol_invalid'
        await emit(dict(type='error',code='voice_protocol_invalid',message='语音数据格式不正确，请重新开始。'))
    except upstream.VoiceServiceError as exc:
        session_end_code=exc.code
        await emit(dict(type='error',code=exc.code,provider_code=exc.provider_code,message='语音服务暂时无法继续，已保存的文字将保留，可稍后重试。'))
    except (TimeoutError,WebSocketDisconnect):
        session_end_code='timeout_or_disconnect'
    except Exception:
        # No raw exception or provider payload can expose credentials/text.
        session_end_code='voice_session_failed'
        await emit(dict(type='error',code='voice_session_failed',message='本次语音连接已结束，正在尝试保存已有文字。'))
    finally:
        transport=controller.transport_diagnostics
        command=transport.get('last_client_command')
        if command not in ('finish','screening.action','interrupt','mute','unmute','commit','playback'):
            command=None
        logger.info('voice_session_closed outcome=%s stage=%s audio_frames=%s remote_events=%s '
                    'last_remote_event=%s capture_gap_count=%s last_client_command=%s detector_error=%s',
                    session_end_code,controller.stage,transport.get('audio_frames',0),
                    transport.get('remote_events',0),transport.get('last_remote_event'),
                    transport.get('capture_gap_count',0),command,
                    RUNTIMES.get(uid,{}).get('monitor').last_error_code
                    if uid and RUNTIMES.get(uid,{}).get('monitor') else None)
        if recorder:
            try:
                for entry in state.unfinished():
                    if entry.role=='assistant':entry.interrupted=not entry.done
                    await persist(entry)
                result=await asyncio.to_thread(recorder.finish)
                if controller.enabled and result['type']=='records.saved':
                    from .collection_sources import attach_sources
                    await asyncio.to_thread(attach_sources,uid,result['recording_session_id'],controller,context['references'])
                    if result['recording_session_id'] not in controller.history_session_ids:
                        controller.history_session_ids.append(result['recording_session_id'])
                    await asyncio.to_thread(store_plan,uid,test_data(),controller)
                    try:await asyncio.to_thread(save_result,uid,result['recording_session_id'],controller)
                    except Exception:await emit(dict(type='screening.result_failed',message='对话文字已保存，辅助采集结果未能确认保存，后续需从原话重新核实。'))
                await emit(result)
            except Exception:
                await emit(dict(type='records.error',pending=None,message='部分文字未能确认保存，请保留本页内容并联系项目维护人员。'))
        if review_lease and recorder:
            with suppress(Exception):await asyncio.to_thread(end_live_call,uid,test_data(),recorder.external)
        if reserved:ACTIVE.discard(uid);RUNTIMES.pop(uid,None)
        with suppress(RuntimeError,WebSocketDisconnect):await ws.close()

def install(app):
    app.include_router(router)
