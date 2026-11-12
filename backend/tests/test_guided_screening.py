import asyncio
import uuid
import pytest
from app.voice.screening import Screening, ITEMS, OPTIONS, save_result, ScreeningResult
from app.voice.transcripts import Utterance
from app.voice import api


def say(s, text, role='user'):
    entry=Utterance(uuid.uuid4().hex,role,'test',text=text,final=True)
    s.observe(entry)
    return entry


def decision(*, ready=True, scales=None, outcome='follow_up'):
    return dict(decision=outcome,target_scales=scales or ['PHQ-9','GAD-7'],
                evidence=[dict(message_id='u1',quote='持续两周低落',domain='low_mood'),
                          dict(message_id='u2',quote='持续担忧影响工作',domain='worry')],
                transition_ready=ready,latest_user_quote='现在可以慢慢聊',reason='虚构测试',
                detector_version='synthetic-detector-v1',source_snapshot_hash='test',latest_user_id='u3')


def collect(scales=None):
    s=Screening(True,'test-purchase-notice-v1')
    s.apply_decision(decision(scales=scales))
    assert s.stage=='collecting'
    return s


def test_ordinary_conversation_has_no_scales_and_no_keyword_trigger():
    s=Screening(True,'purchase-v1')
    say(s,'今天有点孤独');say(s,'昨天有点低落');say(s,'我准备好了');say(s,'可以')
    assert s.stage=='companionship' and not s.triggered and s.view()['scales']==[]
    s.apply_decision(decision(outcome='no_signal'))
    assert s.stage=='companionship' and s.view()['scales']==[]


def test_contextual_decision_replaces_ready_and_consent_gate():
    s=Screening(True,'purchase-v1')
    s.apply_decision(decision(ready=False))
    assert s.stage=='waiting_context'
    say(s,'喝了一杯水');say(s,'今天去了公园')
    s.action('ready');s.action('consent')
    assert s.stage=='waiting_context'
    s.apply_decision(decision(ready=True,scales=['PHQ-9']))
    assert s.stage=='collecting'
    prompt=s.instructions()
    assert '无需再次征求量表同意' in prompt and '后台已根据对话线索' in prompt
    assert 'offering' not in s.stage
    assert s.view()['purchase_notice_version']=='purchase-v1'


def test_late_decision_cannot_set_newer_user_as_ready():
    s=Screening(True)
    s.apply_decision(decision(),fresh=False)
    assert s.stage=='waiting_context'


def test_relevant_scales_only_and_complete_totals_with_evidence():
    s=collect()
    for scale,items in ITEMS.items():
        for index,_ in enumerate(items):
            value=0 if scale=='PHQ-9' and index==8 else 1
            before=len(s.answers)
            say(s,'最近两周，关于'+ITEMS[scale][index]+'的情况怎么样？',role='assistant')
            say(s,'回顾这两周，是'+OPTIONS[value]+'。')
            assert len(s.answers)==before
            say(s,'最近两周关于'+ITEMS[scale][index]+'，我理解是'+OPTIONS[value]+'，对吗？',role='assistant')
            say(s,'对')
    assert s.stage=='complete'
    assert [r['total'] for r in s.view()['scales']]==[8,7]
    assert all(len(v['evidence_ids'])==2 for v in s.answers.values())
    one=collect(['GAD-7'])
    assert [r['scale'] for r in one.view()['scales']]==['GAD-7']
    assert one.view()['scales'][0]['total'] is None


@pytest.mark.parametrize('text',['不是几乎每天','可能有几天','她说几乎每天','有几天或者几乎每天','我有几天挺开心的'])
def test_ambiguous_answers_never_scored(text):
    s=collect();say(s,text);say(s,'确认')
    assert not s.answers and all(v['total'] is None for v in s.view()['scales'])


def test_refusal_pause_and_danger_override_model():
    for text,expected in [('不想继续了','declined'),('我想先休息一下','paused'),('我不想活了','urgent'),('我有点不想活了都。','urgent')]:
        s=collect();say(s,text);assert s.stage==expected
        s.apply_decision(decision())
        assert s.stage==expected
    s=Screening(False);say(s,'我不想活了');assert not s.triggered


def test_confirmation_requires_current_topic_window_and_symptom_polarity():
    s=collect(['PHQ-9'])
    for wrong in ['有几天，对吗？','最近两周睡不好有几天，对吗？',
                  '最近两周有兴趣做事有几天，对吗？']:
        say(s,'有几天');say(s,wrong,'assistant');say(s,'对')
        assert not s.answers
    say(s,'有几天')
    context=say(s,'最近两周，做事缺少兴趣或乐趣有几天，对吗？','assistant')
    say(s,'对')
    assert s.answers['PHQ-9:1']['value']==1
    assert s.answers['PHQ-9:1']['confirmation_context_id']==context.message_id


def test_detector_signal_is_owner_and_evidence_scoped(actors):
    a,b=actors;s=Screening(True);entry=Utterance('known','user','t',text='虚构原话',final=True)
    api.RUNTIMES[a.uid]=dict(session_id='voice_test',queue=asyncio.Queue(maxsize=16),controller=s,
                            transcripts=type('T',(),{'users':{'known':entry}})())
    payload=dict(session_id='voice_test',evidence_ids=[entry.message_id],detector_version='test-external-detector')
    try:
        assert b.request('POST','/api/robot-voice/screening-signal',json=payload).status_code==404
        assert a.request('POST','/api/robot-voice/screening-signal',json={**payload,'evidence_ids':['invented']}).status_code==422
        r=a.request('POST','/api/robot-voice/screening-signal',json=payload)
        assert r.status_code==200 and r.json()==dict(status='queued',applied=False)
    finally:api.RUNTIMES.clear()


def test_ordinary_no_empty_rows_results_or_report_scale_section(actors):
    from app.database import SessionLocal
    a,_=actors;sid=a.create('ordinary-screening').json()['recording_session_id']
    a.send(sid,content='今天和朋友散步，很开心。')
    assert save_result(a.uid,sid,Screening(True,'purchase-v1')) is False
    with SessionLocal() as db:assert db.get(ScreeningResult,sid) is None
    assert a.request('GET',f'/api/robot-voice/screening-results/{sid}').json()['result'] is None
    dto=a.request('POST','/api/robot-insights/reports/preview',json={'scope':{'session_ids':[sid]}}).json()
    assert dto['conversation_assessments']==[]
    assert dto['narrative']['content']['overview']['text']


def test_legacy_empty_rows_are_hidden_and_collected_results_are_owned(actors):
    from app.database import SessionLocal
    a,b=actors;sid=a.create('legacy-empty').json()['recording_session_id']
    with SessionLocal() as db:
        db.add(ScreeningResult(session_id=sid,owner=a.uid,payload={'scales':[{'scale':'PHQ-9','answered':0}]}));db.commit()
    assert a.request('GET',f'/api/robot-voice/screening-results/{sid}').json()['result'] is None
    s=collect(['GAD-7'])
    say(s,'最近两周，紧张焦虑的情况怎么样？','assistant')
    say(s,'有几天');say(s,'最近两周紧张焦虑有几天，对吗？','assistant');say(s,'对')
    assert save_result(a.uid,sid,s)
    assert b.request('GET',f'/api/robot-voice/screening-results/{sid}').status_code==404
    assert a.request('GET',f'/api/robot-voice/screening-results/{sid}').json()['result']['triggered']
    assert a.request('DELETE',f'/api/robot-records/sessions/{sid}').status_code==204
    with SessionLocal() as db:assert db.get(ScreeningResult,sid) is None
