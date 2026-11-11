import asyncio
import json
import pytest
from app.voice import concern_detector as detector
from app.voice.screening import Screening
from app.voice.screening_monitor import ScreeningMonitor
from app.voice.transcripts import Utterance
from app.voice.screening_policy import collection_policy


def entry(key,text,role='user'):
    return Utterance(key,role,'t',text=text,final=True)


def fixture():
    turns=[entry('u1','这两周持续低落，做饭都没兴趣。'),entry('a1','可以慢慢说。','assistant'),
           entry('u2','持续半个月睡不好，影响工作。'),entry('u3','说出来之后好多了，想聊聊日常。')]
    return detector.snapshot(turns)


def output(data,positive=True):
    users=[t for t in data['turns'] if t['role']=='user']
    return dict(decision='follow_up' if positive else 'no_signal',target_scales=['PHQ-9'] if positive else [],
                evidence=[dict(message_id=t['message_id'],quote=t['text'],domain='low_mood' if i==0 else 'sleep')
                          for i,t in enumerate(users[:2])] if positive else [],
                transition_ready=True,latest_user_quote=users[-1]['text'],reason='虚构测试线索')


@pytest.mark.parametrize('mutation',['assistant','invented_quote','one_message','old_readiness','wrong_scale','non_trigger_scales'])
def test_detector_rejects_ungrounded_or_incompatible_output(mutation):
    data=fixture();value=output(data)
    if mutation=='assistant':value['evidence'][0]['message_id']=data['turns'][1]['message_id']
    elif mutation=='invented_quote':value['evidence'][0]['quote']='没有提供的原话'
    elif mutation=='one_message':value['evidence']=value['evidence'][:1]
    elif mutation=='old_readiness':value['latest_user_quote']=data['turns'][0]['text']
    elif mutation=='wrong_scale':value['target_scales']=['GAD-7']
    elif mutation=='non_trigger_scales':value['decision']='no_signal'
    with pytest.raises(ValueError):detector.validate(json.dumps(value),data)


def test_no_signal_ready_never_creates_assessment():
    data=fixture();result=detector.validate(json.dumps(output(data,False)),data)
    s=Screening(True);s.apply_decision(result)
    assert not s.triggered and not s.view()['scales'] and s.stage=='companionship'


def test_policy_requires_server_notice_declaration(monkeypatch):
    monkeypatch.setenv('ROBOT_CARE_GUIDED_SCREENING_ENABLED','true')
    monkeypatch.delenv('ROBOT_CARE_PURCHASE_NOTICE_VERSION',raising=False)
    with pytest.raises(ValueError):collection_policy()
    monkeypatch.setenv('ROBOT_CARE_PURCHASE_NOTICE_VERSION','purchase-v1')
    assert collection_policy().enabled


def test_background_inference_failure_does_not_trigger_or_block(monkeypatch):
    async def scenario():
        called=asyncio.Event()
        async def failing(data):called.set();raise TimeoutError()
        monkeypatch.setattr(detector,'assess',failing)
        async def changed():raise AssertionError('Failed inference cannot trigger')
        s=Screening(True);m=ScreeningMonitor(s,changed)
        for i in range(3):m.observe(entry(f'u{i}','虚构普通对话'))
        task=asyncio.create_task(m.run());await asyncio.wait_for(called.wait(),1)
        await asyncio.sleep(0)
        assert s.stage=='companionship' and s.detector_status=='unavailable'
        task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(scenario())


def test_bad_collection_config_keeps_ordinary_voice_available(actors,monkeypatch):
    from test_voice_bridge import cloud,setup_bridge,authenticate
    a,_=actors
    with cloud() as (url,received):
        setup_bridge(monkeypatch,url)
        monkeypatch.setenv('ROBOT_CARE_GUIDED_SCREENING_ENABLED','true')
        monkeypatch.setenv('ROBOT_CARE_PURCHASE_NOTICE_VERSION','')
        config=a.request('GET','/api/robot-voice/config').json()
        assert config['enabled'] and config['conditional_collection_enabled'] is False
        with a.client.websocket_connect('/api/robot-voice/live') as ws:
            authenticate(ws,a)
            ws.send_json(dict(type='finish'))
            while ws.receive_json()['type']!='records.saved':pass
        assert not any(e['type']=='session.update' for e in received)


def test_stale_inference_only_flags_concern_then_rechecks_latest(monkeypatch):
    async def scenario():
        entered=asyncio.Event();release=asyncio.Event();evaluations=[]
        async def delayed(data):
            evaluations.append(data)
            if len(evaluations)==1:entered.set();await release.wait()
            result=detector.validate(json.dumps(output(data)),data)
            if len(evaluations)>1:result['transition_ready']=False
            return result
        monkeypatch.setattr(detector,'assess',delayed)
        async def changed():pass
        s=Screening(True);m=ScreeningMonitor(s,changed)
        for t in [entry('u1','持续两周心情低落。'),entry('u2','半个月影响工作。'),entry('u3','说出来好多了。')]:m.observe(t)
        task=asyncio.create_task(m.run());await asyncio.wait_for(entered.wait(),1)
        newer=entry('u4','我现在很难受，不适合继续。');m.observe(newer);s.observe(newer)
        release.set()
        for _ in range(30):
            if len(evaluations)==2:break
            await asyncio.sleep(.01)
        assert len(evaluations)==2 and evaluations[-1]['latest_user_id']==newer.message_id
        assert s.stage=='waiting_context'
        task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize('positive',[False,True],ids=['ordinary-no-questionnaire','concern-auto-transition'])
def test_real_bridge_auto_detection_without_optin_or_spoken_consent(actors,monkeypatch,positive):
    from test_voice_bridge import cloud,setup_bridge
    from app.voice import api
    a,_=actors;texts=['这两周持续心情低落。','半个月都没兴趣，影响工作。','说出来好多了，想继续聊聊日常。']
    async def infer(data):return detector.validate(json.dumps(output(data,positive)),data)
    monkeypatch.setattr(detector,'assess',infer)
    saved=[]
    with cloud(user_texts=texts) as (url,received):
        setup_bridge(monkeypatch,url)
        monkeypatch.setenv('ROBOT_CARE_GUIDED_SCREENING_ENABLED','true')
        monkeypatch.setenv('ROBOT_CARE_PURCHASE_NOTICE_VERSION','purchase-v1')
        monkeypatch.setattr(api,'save_result',lambda uid,sid,s:saved.append(s.view()))
        with a.client.websocket_connect('/api/robot-voice/live') as ws:
            # False from a legacy client is intentionally not a product consent gate.
            ws.send_json(dict(type='authenticate',token=a.token,guided_screening=False))
            events=[]
            while ws.receive_json()['type']!='session.ready':pass
            for _ in texts:
                ws.send_bytes(b'\0'*640)
                while True:
                    e=ws.receive_json();events.append(e)
                    if e['type']=='audio.done':break
            while not any(e['type']=='screening.detector_checked' for e in events):events.append(ws.receive_json())
            runtime=api.RUNTIMES[a.uid]
            assert runtime['controller'].stage==('collecting' if positive else 'companionship')
            assert runtime['controller'].target_scales==(['PHQ-9'] if positive else [])
            updates=[e for e in received if e['type']=='session.update']
            assert any('无需再次征求量表同意' in e['session']['instructions'] for e in updates)
            if positive:assert any('后台已根据对话线索' in e['session']['instructions'] for e in updates)
            else:assert not any('后台已根据对话线索' in e['session']['instructions'] for e in updates)
            ws.send_json(dict(type='finish'))
            while ws.receive_json()['type']!='records.saved':pass
    assert saved and saved[0]['triggered'] is positive
    assert saved[0]['purchase_notice_version']=='purchase-v1'
