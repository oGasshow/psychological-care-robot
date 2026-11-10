import pytest

P='/api/robot-insights/demo-conversations'

@pytest.fixture(autouse=True)
def demo(monkeypatch):
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.setenv('ROBOT_CARE_DEMO_DATABASE','true')
    monkeypatch.setenv('ROBOT_CARE_ASSESSMENT_PROVIDER','disabled')

def test_manual_demo_atomic_idempotent_and_owned(actors):
    a,b=actors
    body={'request_id':'demo-one','messages':[{'role':'user','content':'我今天很开心。'},{'role':'assistant','content':'虚构手动回复。'}]}
    first=a.request('POST',P,json=body);assert first.status_code==201
    sid=first.json()['recording_session_id']
    retry=a.request('POST',P,json=body);assert retry.status_code==200 and retry.json()['recording_session_id']==sid
    summary=a.request('GET',f'/api/robot-records/sessions/{sid}').json()
    assert summary['is_test'] is True and summary['is_complete'] is True and summary['received_record_count']==2
    messages=a.messages(sid).json()['items'];assert messages[1]['playback_status']=='not_started'
    assert b.request('GET',f'/api/robot-records/sessions/{sid}').status_code==404
    body['messages'][0]['content']='改过的请求'
    assert a.request('POST',P,json=body).status_code==409

def test_manual_demo_guard_and_validation(actors,monkeypatch):
    a,_=actors;body={'request_id':'x','messages':[{'role':'user','content':'虚构文字'}]}
    assert a.request('POST',P,json={**body,'owner':999}).status_code==422
    assert a.request('POST',P,json={**body,'messages':[{'role':'user','content':' '}]}).status_code==422
    monkeypatch.setenv('APP_ENV','production');monkeypatch.setenv('ROBOT_CARE_SIMULATOR_ENABLED','false')
    assert a.request('POST',P,json=body).status_code==404
