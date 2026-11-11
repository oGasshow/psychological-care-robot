import asyncio
import uuid
import pytest
from app.voice.screening import Screening,ITEMS,OPTIONS
from app.voice.transcripts import Utterance
from app.voice import api

def say(s,text):
    entry=Utterance(uuid.uuid4().hex,'user','test',text=text,final=True)
    s.observe(entry);return entry

def collect():
    s=Screening(True)
    say(s,'这几天心情低落');say(s,'晚上有点孤独')
    assert s.stage=='waiting_ready'
    say(s,'我喝了点水');say(s,'今天还去了公园')
    assert s.stage=='offering'
    s.observe(Utterance('invite','assistant','t',text='愿意聊聊最近两周的感受吗？',final=True))
    say(s,'可以')
    assert s.stage=='collecting'
    return s

def test_natural_transition_needs_distinct_turns_and_consent():
    s=Screening(True);say(s,'有点孤独');entry=say(s,'睡不好又担心')
    s.observe(entry);assert s.stage=='waiting_ready'
    say(s,'我还是很难受');say(s,'喝了杯水');assert s.stage=='waiting_ready'
    say(s,'刚刚去看了花');assert s.stage=='offering'
    say(s,'最近睡得不好');assert s.stage=='offering' and not s.answers
    s.observe(Utterance('invite','assistant','t',text='愿意聊聊最近两周的感受吗？',final=True))
    say(s,'好');assert s.stage=='collecting'

def test_complete_both_scales_requires_confirmation_and_preserves_missing():
    s=collect()
    say(s,'最近不知道怎么样');assert s.pending is None
    for scale,items in ITEMS.items():
        for i,_ in enumerate(items):
            value=0 if scale=='PHQ-9' and i==8 else 1
            before=len(s.answers)
            say(s,'回顾这两周，是'+OPTIONS[value]+'。')
            assert len(s.answers)==before
            s.observe(Utterance(uuid.uuid4().hex,'assistant','t',text='我理解是'+OPTIONS[value]+'，对吗？',final=True))
            say(s,'对')
    view=s.view();assert s.stage=='complete'
    assert [r['total'] for r in view['scales']]==[8,7]
    assert view['verification_status']=='unverified' and view['formal_assessment'] is False
    assert all(len(v['evidence_ids'])==2 for v in s.answers.values())

@pytest.mark.parametrize('text',['不是几乎每天','可能有几天','不知道是不是有几天','她说几乎每天','有几天或者几乎每天'])
def test_ambiguous_answers_never_scored(text):
    s=collect();say(s,text);say(s,'确认')
    assert not s.answers
    assert all(r['total'] is None for r in s.view()['scales'])

def test_decline_pause_and_danger_override_collection():
    s=collect();say(s,'不想继续了');say(s,'可以');assert s.stage=='declined'
    s=collect();say(s,'我想先休息一下');assert s.stage=='paused'
    s=collect();say(s,'我不想活了');assert s.stage=='urgent'
    s.action('ready');s.action('consent');assert s.stage=='urgent'
    s=Screening(False);say(s,'我不想活了');assert s.stage=='companionship'

def test_detector_signal_is_owner_and_evidence_scoped(actors):
    a,b=actors;s=Screening(True);entry=Utterance('known','user','t',text='虚构原话',final=True)
    api.RUNTIMES[a.uid]=dict(session_id='voice_test',queue=asyncio.Queue(maxsize=16),controller=s,
                            transcripts=type('T',(),{'users':{'known':entry}})())
    payload=dict(session_id='voice_test',evidence_ids=[entry.message_id],detector_version='sega-placeholder-not-trained')
    try:
        assert b.request('POST','/api/robot-voice/screening-signal',json=payload).status_code==404
        assert a.request('POST','/api/robot-voice/screening-signal',json={**payload,'evidence_ids':['invented']}).status_code==422
        r=a.request('POST','/api/robot-voice/screening-signal',json=payload)
        assert r.status_code==200 and r.json()==dict(status='queued',applied=False)
    finally:api.RUNTIMES.clear()

def test_live_guidance_reaches_upstream_and_ack_is_not_just_enqueue(actors,monkeypatch):
    from test_voice_bridge import cloud,setup_bridge
    a,_=actors
    with cloud() as (url,received):
        setup_bridge(monkeypatch,url)
        monkeypatch.setattr(api,'save_result',lambda *args:None)
        with a.client.websocket_connect('/api/robot-voice/live') as ws:
            ws.send_json(dict(type='authenticate',token=a.token,guided_screening=True))
            while ws.receive_json()['type']!='screening.policy_applied':pass
            ws.send_bytes(b'\0'*640)
            while True:
                e=ws.receive_json()
                if e['type']=='transcript.final' and e['role']=='user':break
            r=a.request('POST','/api/robot-voice/screening-signal',json=dict(session_id='virtual_voice',evidence_ids=[e['message_id']],detector_version='test-detector-v1'))
            assert r.status_code==200
            while True:
                e=ws.receive_json()
                if e['type']=='screening.policy_applied':break
            assert any(e['type']=='session.update' and '不要求用户说' in e['session']['instructions'] for e in received)
            ws.send_json(dict(type='finish'))
            while ws.receive_json()['type']!='records.saved':pass

def test_persisted_results_owner_visibility_and_deletion(actors):
    from app.voice.screening import save_result,ScreeningResult
    from app.database import SessionLocal
    a,b=actors;sid=a.create('screening-persistence').json()['recording_session_id']
    save_result(a.uid,sid,collect())
    assert a.request('GET',f'/api/robot-voice/screening-results/{sid}').json()['result']['formal_assessment'] is False
    assert b.request('GET',f'/api/robot-voice/screening-results/{sid}').status_code==404
    assert a.request('DELETE',f'/api/robot-records/sessions/{sid}').status_code==204
    with SessionLocal() as db:assert db.get(ScreeningResult,sid) is None
