"""Owner-authenticated browser/device bridge; cloud credentials stay server-side."""
import asyncio
import base64
from contextlib import suppress
import json
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
from .recording import Recorder, internal_base, retry
from .transcripts import Transcripts, Utterance, utc_now
from .screening import Screening, ScreeningResult, save_result, has_collected_items
from .screening_policy import CollectionPolicy, collection_policy
from .screening_monitor import ScreeningMonitor
from .collection_plan import read_plan,restore,store_plan,public_plan
from .continuity import recent_context
from . import sega

router=APIRouter(prefix='/api/robot-voice',tags=['Doubao voice'])
ACTIVE=set()
RUNTIMES={}


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
    if not controller.enabled:message='本次会话未启用后台信息采集。'
    elif controller.stage=='collecting':message='豆包已确认采集指令，可继续自然交流。' if applied==controller.version else '采集任务已下发，正在等待豆包确认。'
    elif controller.stage=='waiting_context':message='已有进一步了解的线索，正在等待适合自然过渡的对话时机。'
    elif controller.stage=='checking_in':message='已带入历史关注任务，先了解当前感受，不因换通话清除任务。'
    elif controller.stage in ('paused','declined','urgent','complete'):message='本次采集已暂停或结束，不会强行继续。'
    elif monitor and monitor.in_flight:message='正在后台核查对话，语音交流可以继续。'
    elif controller.detector_status=='unavailable':message='后台检测暂未完成，请稍后再试；没有据此启动采集。'
    elif count<3:message=f'已收到 {count} 段用户最终转录；至少 3 段后才进行首次后台检测。'
    else:message='本次尚未触发进一步采集；关于系统功能的提问不等于症状自述。'
    return dict(active=True,conditional_collection_enabled=controller.enabled,session_id=runtime['session_id'],
                stage=controller.stage,user_turns=count,first_check_min_turns=3,
                checked_user_turns=monitor.checked_count if monitor else 0,
                detector_running=bool(monitor and monitor.in_flight),detector_status=controller.detector_status,
                last_decision=decision,target_scales=controller.target_scales,
                sent_policy_version=runtime.get('sent_policy_version'),applied_policy_version=applied,
                transport=controller.transport_diagnostics,
                last_error_code=monitor.last_error_code if monitor else None,message=message)

@router.get('/collection-plan')
def collection_plan(response:Response,uid=Depends(owner)):
    response.headers['Cache-Control']='no-store'
    return public_plan(uid,test_data())

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
    target_scales:Annotated[list[Literal['PHQ-9','GAD-7']],Field(min_length=1,max_length=2)]=['PHQ-9','GAD-7']

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
    try:conditional_enabled=collection_policy().enabled
    except (ValueError,TypeError):conditional_enabled=False
    return dict(enabled=enabled,input_rate=16000,output_rate=24000,frame_bytes=640,
                session_seconds=limit,is_test=test_data(),protocol='voice-bridge-v1',
                conditional_collection_enabled=conditional_enabled,
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
        uid=await asyncio.to_thread(authenticate_token,auth.token)
        if uid in ACTIVE:
            await emit(dict(type='error',code='voice_session_active',message='已有语音会话正在进行，请先结束另一处会话。'));return
        ACTIVE.add(uid);reserved=True
        cfg=settings()
        if not cfg.enabled or not cfg.api_key:
            await emit(dict(type='error',code='voice_not_configured',message='语音服务尚未配置。'));return
        base=internal_base(ws.scope)
        await emit(dict(type='status',state='connecting',message='正在连接豆包语音…'))
        # Retry previously sealed local queues with this owner's current JWT.
        await asyncio.to_thread(retry,uid,auth.token,base)
        if controller.enabled:
            plan=await asyncio.to_thread(read_plan,uid,test_data())
            context=await asyncio.to_thread(recent_context,uid,is_test=test_data(),
                after=plan.get('completed_at') if plan and not plan['needs_collection'] else None)
            controller.inherit(context)
            restore(controller,plan)
        else:context={'turns':[],'references':{}}
        async with upstream.connection(cfg,instructions=controller.instructions()) as (remote,created):
            await remote.send(json.dumps({'type':'input_audio_mute.commit'}))
            recorder=await asyncio.to_thread(Recorder,uid,auth.token,base,is_test=test_data(),device_id=auth.device_id)
            queue=asyncio.Queue(maxsize=16);pending_versions=[]
            transport=dict(audio_frames=0,remote_events=0,last_remote_event=None,last_client_command=None)
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
                await emit(controller.view())
            async def receive_control():
                while True:
                    signal=await queue.get()
                    controller.concern(signal.evidence_ids,signal.detector_version,signal.target_scales)
                    await update_policy()
            monitor=ScreeningMonitor(controller,update_policy,provider=policy.detector,emit=emit,history=context['turns'])
            RUNTIMES[uid]['monitor']=monitor
            if controller.enabled:await update_policy()
            await emit(dict(type='session.ready',session_id=recorder.external,input_rate=16000,output_rate=24000,
                            is_test=test_data(),protocol='voice-bridge-v1'))
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
                async for raw_event in remote:
                    event=upstream.decode_event(raw_event);kind=event['type']
                    transport['remote_events']+=1;transport['last_remote_event']=kind
                    if kind=='session.updated' and pending_versions:
                        applied=pending_versions.pop(0)
                        RUNTIMES[uid]['applied_policy_version']=applied
                        await emit(dict(type='screening.policy_applied',version=applied))
                    if kind=='conversation.item.input_audio_transcription.started':
                        await interrupt('user_started_speaking')
                    entry,public=state.apply(event)
                    if public:
                        if public['type']=='transcript.final':
                            await persist(entry)
                            version=controller.version;controller.observe(entry)
                            monitor.observe(entry)
                            if version!=controller.version:await update_policy()
                        await emit(public)
                    if kind=='response.output_audio.delta' and entry and not entry.interrupted:
                        encoded=event.get('delta','')
                        pcm=base64.b64decode(encoded,validate=True)
                        if len(pcm)%2 or len(pcm)>256000:raise ValueError('invalid_provider_audio')
                        await emit(dict(type='audio.delta',message_id=entry.message_id,audio=encoded,rate=24000))
                    elif kind=='response.output_audio.done' and entry and not entry.interrupted:
                        await emit(dict(type='audio.done',message_id=entry.message_id))
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
                while True:
                    await asyncio.sleep(2)
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
                for task in (receiver,client,deadline,control,detector,guard):task.cancel()
                await asyncio.gather(receiver,client,deadline,control,detector,guard,return_exceptions=True)
    except RecordError:
        await emit(dict(type='error',code='authentication_required',message='登录已失效，请重新登录。'))
    except (ValidationError,ValueError,TypeError,KeyError):
        await emit(dict(type='error',code='voice_protocol_invalid',message='语音数据格式不正确，请重新开始。'))
    except upstream.VoiceServiceError as exc:
        await emit(dict(type='error',code=exc.code,provider_code=exc.provider_code,message='语音服务暂时无法继续，已保存的文字将保留，可稍后重试。'))
    except (TimeoutError,WebSocketDisconnect):pass
    except Exception:
        # No raw exception or provider payload can expose credentials/text.
        await emit(dict(type='error',code='voice_session_failed',message='本次语音连接已结束，正在尝试保存已有文字。'))
    finally:
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
        if reserved:ACTIVE.discard(uid);RUNTIMES.pop(uid,None)
        with suppress(RuntimeError,WebSocketDisconnect):await ws.close()

def install(app):
    app.include_router(router)
