"""Local-only protocol, interruption and ownership regressions; no cloud/audio devices."""
import asyncio
import base64
from contextlib import contextmanager
import json
import threading
from types import SimpleNamespace
from conftest import RUN_ROOT

import pytest
from websockets.sync.server import serve
from starlette.websockets import WebSocketDisconnect
from app.voice import api, upstream
from app.voice.settings import settings
from app.voice.transcripts import Transcripts, Utterance
from app.care import report_narrative


def test_interrupt_old_ack_and_late_audio_never_discard_new_turn():
    state=Transcripts()
    state.apply(dict(type='conversation.item.input_audio_transcription.completed',item_id='q1',text='虚构旧问题'))
    old,_=state.apply(dict(type='response.output_text.delta',question_id='q1',response_id='r1',delta='旧回复'))
    assert state.interrupt()==[old]
    state.apply(dict(type='conversation.item.input_audio_transcription.completed',item_id='q2',text='虚构新问题'))
    new,public=state.apply(dict(type='response.output_text.delta',question_id='q2',response_id='r2',delta='新回复'))
    assert public['text']=='新回复' and new.turn_id=='turn_2'
    state.apply(dict(type='response.canceled'))
    late,public=state.apply(dict(type='response.output_audio.delta',response_id='r1',delta=''))
    assert late is old and public is None and old.interrupted
    entry,public=state.apply(dict(type='response.output_text.done',response_id='r2',text='新回复完成'))
    assert entry is new and public['type']=='transcript.final' and not new.interrupted
    assert new.wire()['playback_status']=='unknown'
    assert state.apply(dict(type='response.output_text.done',response_id='r2',text='重复完成'))[1] is None


def test_greeting_aliases_and_transcription_final_dedup():
    state=Transcripts()
    state.responses['greeting']=Utterance('greeting','assistant','turn_0',text='你好',final=True)
    state.active_response='greeting'
    entry,_=state.apply(dict(type='response.output_audio.done',question_id='hello',response_id='r0'))
    assert entry.key=='greeting' and entry.done and not state.interrupt()
    one,public=state.apply(dict(type='conversation.item.input_audio_transcription.completed',item_id='q',text='今天很开心'))
    assert public['text']=='今天很开心' and one.wire()['text_status']=='completed'
    assert state.apply(dict(type='conversation.item.input_audio_transcription.completed',item_id='q',text='今天很开心'))[1] is None
    assert len(state.users)==1


def test_empty_provider_started_id_adopts_real_asr_id_without_extra_turn():
    state=Transcripts()
    pending,_=state.apply(dict(type='conversation.item.input_audio_transcription.started',item_id=''))
    named,_=state.apply(dict(type='conversation.item.input_audio_transcription.delta',item_id='actual_id',delta='虚构'))
    assert named is pending and state.turn==1 and len(state.users)==1
    state.apply(dict(type='conversation.item.input_audio_transcription.completed',item_id='actual_id',text='虚构'))
    next_entry,_=state.apply(dict(type='conversation.item.input_audio_transcription.started',item_id=''))
    assert next_entry is not named and next_entry.turn_id=='turn_2'


@contextmanager
def cloud(user_texts=None, *, audio_only=False):
    received=[]
    def handler(ws):
        input_count=0
        try:
            for raw in ws:
                event=json.loads(raw);received.append(event);kind=event['type']
                if kind=='session.create':ws.send(json.dumps(dict(type='session.created')))
                elif kind=='session.update':ws.send(json.dumps(dict(type='session.updated')))
                elif kind=='speech_text_buffer.commit':
                    ws.send(json.dumps(dict(type='response.output_audio.done',response_id='hello')))
                elif kind=='input_audio_buffer.append':
                    input_count+=1
                    assert len(base64.b64decode(event['audio']))==640
                    q=f'u{input_count}';r=f'r{input_count}'
                    spoken=user_texts[min(input_count-1,len(user_texts)-1)] if user_texts else '虚构：今天开心'
                    events=[dict(type='conversation.item.input_audio_transcription.started',item_id=q),
                            dict(type='conversation.item.input_audio_transcription.completed',item_id=q,text=spoken),
                            dict(type='response.output_text.done',question_id=q,response_id=r,text='我在听，可以慢慢说。'),
                            dict(type='response.output_audio.delta',question_id=q,response_id=r,delta=base64.b64encode(b'\0'*640).decode()),
                            dict(type='response.output_audio.done',question_id=q,response_id=r)]
                    if audio_only:
                        events=[item for item in events if item['type']!='response.output_text.done']
                    for event in events:ws.send(json.dumps(event))
                elif kind=='session.close':ws.send(json.dumps(dict(type='session.closed')));break
        except Exception:
            # Deliberately malformed client tests may close before the mock does.
            pass
    local=serve(handler,'127.0.0.1',0)
    thread=threading.Thread(target=local.serve_forever,daemon=True);thread.start()
    try:yield f'ws://127.0.0.1:{local.socket.getsockname()[1]}',received
    finally:local.shutdown();thread.join(timeout=3)


class FakeRecorder:
    instances=[]
    def __init__(self,uid,token,base,*,is_test,device_id):
        self.uid,self.is_test,self.device_id=uid,is_test,device_id
        self.external='virtual_voice';self.entries=[];self.instances.append(self)
        self.box=SimpleNamespace(path=RUN_ROOT/f'fictional_voice_{uid}.sqlite')
    def enqueue(self,entry):
        self.entries.append(entry.wire());entry.recorded=True
    def finish(self):return dict(type='records.saved',recording_session_id=123,pending=0)
    def sync_partial(self,seconds=3.5):return dict(type='records.saved',recording_session_id=123,pending=0)


def setup_bridge(monkeypatch,url):
    monkeypatch.setenv('APP_ENV','test')
    monkeypatch.setenv('DOUBAO_VOICE_API_KEY','fictional-key-for-local-mock')
    monkeypatch.setenv('ROBOT_CARE_VOICE_ENABLED','true')
    monkeypatch.setenv('DOUBAO_VOICE_WS_URL',url)
    monkeypatch.setattr(api,'Recorder',FakeRecorder)
    monkeypatch.setattr(api,'internal_base',lambda scope:'http://127.0.0.1:1234')
    monkeypatch.setattr(api,'retry',lambda *args:dict(items=[],pending=0))
    FakeRecorder.instances.clear();api.ACTIVE.clear()


def authenticate(ws,actor):
    ws.send_json(dict(type='authenticate',token=actor.token,device_id='pi_adapter_test'))
    while ws.receive_json()['type']!='session.ready':pass


def test_goodbye_waits_for_client_playback_finish_even_without_output_text(actors,monkeypatch):
    from app.voice.screening import Screening
    def completed(*args):
        s=Screening(True,'fictional-notice');s.stage='complete';s.closing_question_asked=True
        return s
    a,_=actors
    with cloud(['没有了。'],audio_only=True) as (url,received):
        setup_bridge(monkeypatch,url)
        monkeypatch.setattr(api,'Screening',completed)
        monkeypatch.setattr(api,'store_plan',lambda *args:None)
        with a.client.websocket_connect('/api/robot-voice/live') as ws:
            authenticate(ws,a);ws.send_bytes(b'\0'*640)
            while ws.receive_json()['type']!='dialogue.finished':pass
            assert not any(e['type']=='session.close' for e in received)
            assert a.request('GET','/api/robot-voice/diagnostics').json()['active']
            ws.send_json(dict(type='finish'))
            while ws.receive_json()['type']!='records.saved':pass
    assert any(e['type']=='session.close' for e in received)


@pytest.mark.parametrize('pending',[0,1])
def test_saved_answers_recover_before_task_validation_and_survive_retry_failure(actors,monkeypatch,pending):
    a,_=actors;calls=[]
    def recover(*args):
        calls.append('retry');return dict(items=[],pending=pending)
    def load(*args):
        calls.append('read_plan');assert calls[0]=='retry';return None
    with cloud() as (url,_):
        setup_bridge(monkeypatch,url)
        monkeypatch.setenv('ROBOT_CARE_GUIDED_SCREENING_ENABLED','true')
        monkeypatch.setenv('ROBOT_CARE_PURCHASE_NOTICE_VERSION','fictional-notice')
        monkeypatch.setattr(api,'has_saved_answers',lambda *args:True)
        monkeypatch.setattr(api,'retry',recover)
        monkeypatch.setattr(api,'read_plan',load)
        with a.client.websocket_connect('/api/robot-voice/live') as ws:
            ws.send_json(dict(type='authenticate',token=a.token))
            if pending:
                while True:
                    event=ws.receive_json()
                    if event['type']=='error':break
                assert event['code']=='record_recovery_pending'
                assert calls==['retry'] and not FakeRecorder.instances
            else:
                while ws.receive_json()['type']!='session.ready':pass
                assert calls[:2]==['retry','read_plan']
                ws.send_json(dict(type='finish'))
                while ws.receive_json()['type']!='records.saved':pass


def test_local_cloud_round_trip_and_saved_final_texts(actors,monkeypatch):
    a,_=actors
    with cloud() as (url,received):
        setup_bridge(monkeypatch,url)
        assert a.request('GET','/api/robot-voice/config').json()['enabled'] is True
        with a.client.websocket_connect('/api/robot-voice/live') as ws:
            authenticate(ws,a);ws.send_json(dict(type='unmute'));ws.send_bytes(b'\0'*640)
            events=[]
            while True:
                event=ws.receive_json();events.append(event)
                if event['type']=='audio.done' and any(e['type']=='audio.delta' for e in events):break
            ws.send_json(dict(type='finish'))
            while True:
                event=ws.receive_json()
                if event['type']=='records.saved':break
        assert any(e['type']=='audio.delta' for e in events)
        assert any(e['type']=='transcript.final' and e['role']=='user' for e in events)
    recorder=FakeRecorder.instances[0]
    assert recorder.uid==a.uid and recorder.is_test and recorder.device_id=='pi_adapter_test'
    assert len(recorder.entries)==3 and len({e['external_message_id'] for e in recorder.entries})==3
    assert recorder.entries[-1]['playback_status']=='unknown'
    assert not api.ACTIVE
    assert received[0]['session']['model']=='1.2.6.1'
    assert '量表' in received[0]['session']['instructions']


@pytest.mark.parametrize('bad',[b'\0'*100,dict(type='unknown'),[],dict(type='session.create')],ids=['short-audio','unknown-command','array-command','provider-command'])
def test_invalid_browser_frames_fail_safely(actors,monkeypatch,bad):
    a,_=actors
    with cloud() as (url,_):
        setup_bridge(monkeypatch,url)
        with a.client.websocket_connect('/api/robot-voice/live') as ws:
            authenticate(ws,a)
            ws.send_bytes(bad) if isinstance(bad,bytes) else ws.send_json(bad)
            while True:
                event=ws.receive_json()
                if event['type']=='error':break
            assert event['code']=='voice_protocol_invalid' and 'fictional-key' not in json.dumps(event)


def test_authentication_origin_and_concurrent_owner_guard(actors,monkeypatch):
    a,_=actors
    with cloud() as (url,_):
        setup_bridge(monkeypatch,url)
        assert a.client.get('/api/robot-voice/config').status_code==401
        with pytest.raises(WebSocketDisconnect):
            with a.client.websocket_connect('/api/robot-voice/live',headers={'origin':'https://untrusted.invalid'}):pass
        with a.client.websocket_connect('/api/robot-voice/live') as ws:
            ws.send_json(dict(type='authenticate',token='invalid-token-long-enough'))
            assert ws.receive_json()['code']=='authentication_required'
        with a.client.websocket_connect('/api/robot-voice/live') as first:
            authenticate(first,a)
            with a.client.websocket_connect('/api/robot-voice/live') as second:
                second.send_json(dict(type='authenticate',token=a.token))
                assert second.receive_json()['code']=='voice_session_active'
            assert a.uid in api.ACTIVE  # Closing rejected duplicate cannot release first.
            assert a.request('POST','/api/robot-voice/retry-records').status_code==409
            first.send_json(dict(type='finish'))
            while first.receive_json()['type']!='records.saved':pass
    assert not api.ACTIVE


def test_disabled_configuration_and_private_key_repr(actors,monkeypatch):
    a,_=actors
    monkeypatch.setenv('DOUBAO_VOICE_API_KEY','fictional-secret')
    assert 'fictional-secret' not in repr(settings())
    response=a.request('GET','/api/robot-voice/config')
    assert not response.json()['enabled'] and 'fictional-secret' not in response.text
    monkeypatch.setenv('DOUBAO_VOICE_WS_URL','wss://untrusted.invalid')
    assert not a.request('GET','/api/robot-voice/config').json()['enabled']


def test_speech_report_provider_validates_real_shape_and_falls_back(actors,monkeypatch):
    from test_report_summary import seed,preview,generate,output
    a,_=actors;seed(a);dto=preview(a)
    monkeypatch.setenv('ROBOT_CARE_REPORT_PROVIDER','doubao_realtime')
    monkeypatch.setenv('DOUBAO_VOICE_API_KEY','fictional-key')
    async def good(*args):return json.dumps(output())
    monkeypatch.setattr(upstream,'structured_report',good)
    result=generate(a,dto).json()['narrative']
    assert result['mode']=='model' and result['provider']=='doubao_realtime'
    async def bad(*args):return json.dumps(dict(overview='malformed'))
    monkeypatch.setattr(upstream,'structured_report',bad)
    assert generate(a,dto).json()['narrative']['reason_code']=='model_output_rejected'


def test_report_function_call_uses_inline_schema_and_allowed_evidence(monkeypatch):
    received=[]
    def handler(ws):
        received.append(json.loads(ws.recv()))
        ws.send(json.dumps(dict(type='session.created')))
        ws.send(json.dumps(dict(type='response.function_call_arguments.done',items=[dict(name='write_companionship_report',arguments='{}')])))
        with __import__('contextlib').suppress(Exception):
            for _ in ws:pass
    local=serve(handler,'127.0.0.1',0)
    thread=threading.Thread(target=local.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv('APP_ENV','test')
    monkeypatch.setenv('DOUBAO_VOICE_API_KEY','fictional-key')
    monkeypatch.setenv('DOUBAO_VOICE_WS_URL',f'ws://127.0.0.1:{local.socket.getsockname()[1]}')
    try:
        raw=asyncio.run(upstream.structured_report('虚构测试',report_narrative.Narrative.model_json_schema(),
                                                  dict(facts=[dict(id='coverage:test')],evidence=[dict(id='record:1@0')]),3))
        assert raw=='{}'
        parameters=received[0]['session']['tools'][0]['parameters']
        assert '$ref' not in json.dumps(parameters) and '$defs' not in parameters
        overview=parameters['properties']['overview']
        assert overview['type']=='object'
        assert overview['properties']['evidence_ids']['items']['enum']==['coverage:test','record:1@0']
    finally:local.shutdown();thread.join(timeout=3)


def test_recording_durable_retry_dedup_and_owner_partition(actors,monkeypatch,tmp_path):
    from app.voice import recording
    a,b=actors
    monkeypatch.setenv('ROBOT_CARE_VOICE_OUTBOX_DIR',str(tmp_path))
    class LocalTransport:
        fail=True
        def __init__(self,base,token,timeout=3):self.base_url,self.token=base,token
        def request(self,method,path,**kwargs):
            if self.fail and path!='/api/auth/me':
                import httpx
                return httpx.Response(503,request=httpx.Request(method,self.base_url+path))
            return a.client.request(method,path,headers={'Authorization':'Bearer '+self.token},**kwargs)
        def close(self):pass
    monkeypatch.setattr(recording,'Transport',LocalTransport)
    recorder=recording.Recorder(a.uid,a.token,'http://127.0.0.1:1234',is_test=True,device_id='pi_test')
    from app.voice.transcripts import utc_now
    entry=Utterance('synthetic','user','turn_1',text='虚构：和朋友聊天',final=True,occurred_at=utc_now())
    recorder.enqueue(entry);recorder.enqueue(entry)
    recorder.box.close_session(recorder.external,utc_now());recorder.closed=True
    pending=recording.flush(recorder.box,recorder.transport,seconds=.05)
    assert pending['type']=='records.pending'
    assert recording.retry(b.uid,b.token,'http://127.0.0.1:1234')['items']==[]
    LocalTransport.fail=False
    result=recording.retry(a.uid,a.token,'http://127.0.0.1:1234')
    assert result['pending']==0 and result['items'][0]['type']=='records.saved'
    sid=result['items'][0]['recording_session_id']
    assert len(a.messages(sid).json()['items'])==1
    assert b.messages(sid).status_code==404
    assert recording.retry(a.uid,a.token,'http://127.0.0.1:1234')['pending']==0
    assert len(a.messages(sid).json()['items'])==1
