import pytest

from app.voice import api
from app.voice.settings import VOICE_OPTIONS, settings
from test_voice_bridge import cloud, setup_bridge


@pytest.mark.parametrize('selected', [v['id'] for v in VOICE_OPTIONS] + [None])
def test_selected_voice_reaches_cloud_without_changing_default(actors, monkeypatch, selected):
    actor,_=actors
    with cloud() as (url, events):
        setup_bridge(monkeypatch,url)
        original=settings().voice
        with actor.client.websocket_connect('/api/robot-voice/live') as ws:
            auth=dict(type='authenticate',token=actor.token,device_id='voice_choice_test')
            if selected is not None:auth['voice']=selected
            ws.send_json(auth)
            while ws.receive_json()['type']!='session.ready':pass
            ws.send_json({'type':'finish'})
            while ws.receive_json()['type']!='records.saved':pass
        sent=next(e for e in events if e['type']=='session.create')
        assert sent['session']['audio']['output']['voice']==(selected or original)
        assert settings().voice==original


def test_unknown_voice_rejected_and_choices_advertised(actors,monkeypatch):
    actor,_=actors
    with cloud() as (url,events):
        setup_bridge(monkeypatch,url)
        config=actor.request('GET','/api/robot-voice/config').json()
        assert config['voices']==list(VOICE_OPTIONS)
        assert config['default_voice']==VOICE_OPTIONS[0]['id']
        with actor.client.websocket_connect('/api/robot-voice/live') as ws:
            ws.send_json(dict(type='authenticate',token=actor.token,voice='unknown-voice'))
            assert ws.receive_json()['code']=='voice_protocol_invalid'
        assert not events


@pytest.mark.parametrize('speed',[-50,0,100,None])
def test_speed_is_applied_to_create_and_update_for_this_session(actors,monkeypatch,speed):
    actor,_=actors
    with cloud() as (url,events):
        setup_bridge(monkeypatch,url)
        monkeypatch.setenv('ROBOT_CARE_GUIDED_SCREENING_ENABLED','true')
        monkeypatch.setenv('ROBOT_CARE_PURCHASE_NOTICE_VERSION','fictional-speed-test')
        original=settings().speed
        with actor.client.websocket_connect('/api/robot-voice/live') as ws:
            auth=dict(type='authenticate',token=actor.token)
            if speed is not None:auth['speed']=speed
            ws.send_json(auth)
            while ws.receive_json()['type']!='session.ready':pass
            ws.send_json({'type':'finish'})
            while ws.receive_json()['type']!='records.saved':pass
        payloads=[e for e in events if e['type'] in ('session.create','session.update')]
        assert {e['type'] for e in payloads}=={'session.create','session.update'}
        assert all(e['session']['audio']['output']['speed']==(original if speed is None else speed) for e in payloads)
        assert settings().speed==original


@pytest.mark.parametrize('invalid',[-51,101,0.5,'20',True])
def test_invalid_speed_never_reaches_provider(actors,monkeypatch,invalid):
    actor,_=actors
    with cloud() as (url,events):
        setup_bridge(monkeypatch,url)
        with actor.client.websocket_connect('/api/robot-voice/live') as ws:
            ws.send_json(dict(type='authenticate',token=actor.token,speed=invalid))
            assert ws.receive_json()['code']=='voice_protocol_invalid'
        assert not events
