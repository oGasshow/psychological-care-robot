"""Report warnings use explicit current user dialogue, not emotion scores."""
import pytest

P='/api/robot-insights'

@pytest.fixture(autouse=True)
def provider(monkeypatch):
    monkeypatch.setenv('ROBOT_CARE_ASSESSMENT_PROVIDER','disabled')

def preview(actor,sid):
    response=actor.request('POST',P+'/reports/preview',json={'scope':{'session_ids':[sid]}})
    assert response.status_code==200
    return response.json()['danger_notice']

@pytest.mark.parametrize('text,role,status,expected',[
    ('我不想活了。','user','completed',True),
    ('我有点不想活了都。','user','completed',True),
    ('我最近真的有点不想活了。','user','completed',True),
    ('我感觉自己有一点想死。','user','completed',True),
    ('我现在想伤害自己。','user','completed',True),
    ('我很难过，压力很大。','user','completed',False),
    ('我不想伤害自己。','user','completed',False),
    ('我最近真的没有想过伤害自己。','user','completed',False),
    ('如果我有点不想活了怎么办？','user','completed',False),
    ('假设我不想活了，你会怎么回答？','user','completed',False),
    ('朋友说我有点不想活了都。','user','completed',False),
    ('“我有点不想活了都。”','user','completed',False),
    ('朋友说他不想活了。','user','completed',False),
    ('“我不想活了。”','user','completed',False),
    ('我不想活了。','assistant','completed',False),
    ('我不想活了。','user','canceled',False),
])
def test_report_explicit_current_dialogue(actors,text,role,status,expected):
    a,b=actors
    sid=a.create().json()['recording_session_id']
    assert a.send(sid,content=text,role=role,text_status=status,playback_status='completed' if role=='assistant' else 'not_applicable').status_code==201
    notice=preview(a,sid)
    assert bool(notice['count']) is expected
    assert (notice['status']=='explicit_danger_expression') is expected
    summary=a.request('GET',P+f'/sessions/{sid}/summary')
    assert summary.status_code==200
    assert summary.json()['danger_notice']==notice  # no worker or model needed
    assert b.request('GET',P+f'/sessions/{sid}/summary').status_code==404
    if expected:
        assert notice['sources'][0]['expressions']
        assert notice['sources'][0]['input_revision']==0
    assert b.request('POST',P+'/reports/preview',json={'scope':{'session_ids':[sid]}}).status_code==404

def test_report_danger_tracks_corrections_without_worker(actors):
    a,_=actors
    sid=a.create().json()['recording_session_id']
    rid=a.send(sid,content='我不想活了。').json()['record_id']
    assert preview(a,sid)['count']==1  # no model/worker needed to expose safety signal
    r=a.request('POST',P+f'/messages/{rid}/corrections',json={'request_id':'correction-neutral','base_revision':0,'content':'我今天去公园散步。'})
    assert r.status_code==201
    assert preview(a,sid)['count']==0
    assert a.request('GET',P+f'/sessions/{sid}/summary').json()['danger_notice']['count']==0
    r=a.request('POST',P+f'/messages/{rid}/corrections',json={'request_id':'correction-danger','base_revision':1,'content':'我现在想伤害自己。'})
    assert r.status_code==201
    notice=preview(a,sid)
    assert notice['count']==1 and notice['sources'][0]['input_revision']==2
    assert a.request('GET',P+f'/sessions/{sid}/summary').json()['danger_notice']==notice
    assert a.request('DELETE',f'/api/robot-records/sessions/{sid}').status_code==204
    assert a.request('POST',P+'/reports/preview',json={'scope':{'session_ids':[sid]}}).status_code==410

def test_report_danger_respects_owner_and_time_window(actors):
    a,b=actors
    sid=a.create().json()['recording_session_id']
    a.send(sid,content='我不想活了。',occurred_at='2026-10-28T01:00:00Z')
    other=b.create().json()['recording_session_id']
    b.send(other,content='我不想活了。',occurred_at='2026-11-10T01:00:00Z')
    response=a.request('POST',P+'/reports/preview',json={'scope':{'time_from':'2026-11-01T00:00:00Z','time_to':'2026-12-01T00:00:00Z'}})
    assert response.status_code==200 and response.json()['danger_notice']['count']==0
