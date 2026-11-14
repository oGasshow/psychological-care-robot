import asyncio
import json
import uuid
import pytest
from app.database import SessionLocal
from app.robot_records import now,RecordMessage
from app.voice import api
from app.voice.screening import Screening,ITEMS,CUSTOM_OPTIONS,save_result
from app.voice.screening_policy import collection_demo_enabled,collection_policy
from app.voice.concern_detector import snapshot,validate
from app.voice.screening_monitor import ScreeningMonitor
from app.voice.transcripts import Utterance
from app.voice.collection_plan import store_plan,read_plan
from app.voice.collection_sources import attach_sources


@pytest.fixture(autouse=True)
def isolated_demo(monkeypatch):
    for name,value in dict(APP_ENV='test',ROBOT_CARE_COLLECTION_DEMO='true',
        ROBOT_CARE_RUNTIME_ROLE='collection_demo',ROBOT_CARE_DEMO_DATABASE='true',
        ROBOT_CARE_GUIDED_SCREENING_ENABLED='true',ROBOT_CARE_PURCHASE_NOTICE_VERSION='fictional-demo').items():
        monkeypatch.setenv(name,value)


def utter(text,role='user'):
    return Utterance(uuid.uuid4().hex,role,'demo',text=text,final=True,occurred_at=now())


def decision(data):
    user=next(t for t in data['turns'] if t['role']=='user')
    return dict(decision='follow_up',target_scales=['mood_interest'],
        evidence=[dict(message_id=user['message_id'],quote=user['text'],domain='low_mood')],
        transition_ready=True,latest_user_quote=user['text'],reason='虚构演示线索')


def controller():
    s=Screening(True,'fictional-demo');s.demo_mode=True
    return s


def collect_three(s,values=(2,3,1)):
    entries=[]
    for topic,value in zip(ITEMS['mood_interest'],values):
        for text,role in [(f'最近两周，{topic}的情况怎么样？','assistant'),(CUSTOM_OPTIONS[value],'user'),
            (f'最近两周，{topic}大约是{CUSTOM_OPTIONS[value]}，我这样理解对吗？','assistant'),('对','user')]:
            entry=utter(text,role);s.observe(entry);entries.append(entry)
    return entries


@pytest.mark.parametrize('name,value',[('APP_ENV','production'),('ROBOT_CARE_RUNTIME_ROLE','normal'),('ROBOT_CARE_DEMO_DATABASE','false')])
def test_short_demo_requires_all_deployment_guards(monkeypatch,name,value):
    monkeypatch.setenv(name,value)
    with pytest.raises(ValueError):collection_demo_enabled()
    with pytest.raises(ValueError):collection_policy()


def test_short_demo_uses_live_mode_and_normal_mode_stays_post_session(monkeypatch):
    monkeypatch.setenv('ROBOT_CARE_CONCERN_REVIEW_MODE','post_session')
    assert collection_policy().demo_mode and collection_policy().review_mode=='live'
    monkeypatch.setenv('ROBOT_CARE_COLLECTION_DEMO','false')
    assert not collection_policy().demo_mode and collection_policy().review_mode=='post_session'


def test_one_grounded_turn_is_only_accepted_in_isolated_demo(monkeypatch):
    data=snapshot([utter('今天心情有点低落。')]);data['demo_mode']=True
    result=validate(json.dumps(decision(data)),data)
    assert result['target_scales']==['mood_interest']
    monkeypatch.setenv('ROBOT_CARE_COLLECTION_DEMO','false')
    with pytest.raises(ValueError,match='insufficient_concern_evidence'):validate(json.dumps(decision(data)),data)


def test_short_demo_still_rejects_fake_evidence_and_standard_scale_targets():
    data=snapshot([utter('今天心情有点低落。')]);data['demo_mode']=True
    raw=decision(data);raw['evidence'][0]['quote']='没有出现过的原话'
    with pytest.raises(ValueError,match='ungrounded'):validate(json.dumps(raw),data)
    raw=decision(data);raw['target_scales']=['PHQ-9']
    with pytest.raises(ValueError,match='demo_target'):validate(json.dumps(raw),data)


def test_demo_monitor_schedules_after_one_turn_and_keeps_normal_minimum(monkeypatch):
    async def updated():pass
    s=controller();m=ScreeningMonitor(s,updated);m.observe(utter('今天有点低落。'))
    assert not m.queue.empty() and m.queue.get_nowait()[1]['demo_mode'] is True
    regular=Screening(True);n=ScreeningMonitor(regular,updated);n.observe(utter('今天有点低落。'))
    assert n.queue.empty()


def test_three_confirmed_items_produce_actual_custom_total_and_no_phq_gad_score():
    s=controller();s.start_demo('fictional-trigger');collect_three(s)
    view=s.view();scale=view['scales'][0]
    assert s.stage=='complete' and len(view['scales'])==1
    assert scale['scale']=='mood_interest' and scale['total']==6 and scale['max_score']==12
    assert view['demo_mode'] and not view['formal_assessment']
    assert s.public_status()['demo_progress']['total']==6
    assert view['trigger_origin']=='manual_demo'


def test_demo_scores_explicit_answers_but_never_fills_missing_items():
    s=controller();s.start_demo('fictional-trigger')
    s.observe(utter('最近两周低落或提不起兴趣的情况怎么样？','assistant'))
    s.observe(utter('有时'))
    assert len(s.answers)==1 and s.view()['scales'][0]['total'] is None
    s.observe(utter('最近两周低落或提不起兴趣有时，对吗？','assistant'));s.observe(utter('对'))
    assert len(s.answers)==1 and s.view()['scales'][0]['total'] is None


def test_demo_refusal_and_danger_still_override_and_cannot_be_manually_bypassed():
    for text,stage in [('我不想回答这些问题。','declined'),('我不想活了。','urgent')]:
        s=controller();s.start_demo('fictional-trigger');s.observe(utter(text))
        assert s.stage==stage and not s.start_demo('another-trigger') and not s.answers


def test_manual_demo_endpoint_is_owner_scoped_and_normal_runtime_cannot_use_it(actors,monkeypatch):
    a,b=actors;s=controller();u=utter('今天想聊聊。')
    queue=asyncio.Queue(maxsize=1)
    api.RUNTIMES[a.uid]=dict(session_id='voice_demo_test',controller=s,queue=queue,
        transcripts=type('T',(),{'users':{u.key:u}})())
    try:
        assert b.request('POST','/api/robot-voice/demo/start').status_code==409
        assert queue.empty()
        r=a.request('POST','/api/robot-voice/demo/start');assert r.status_code==200
        signal=queue.get_nowait();assert signal.evidence_id==u.message_id
        assert r.json()['trigger_origin']=='manual_demo'
        monkeypatch.setenv('ROBOT_CARE_COLLECTION_DEMO','false')
        assert a.request('POST','/api/robot-voice/demo/start').status_code==404
        assert a.request('POST','/api/robot-voice/demo/reset').status_code==404
    finally:api.RUNTIMES.pop(a.uid,None)


def test_saved_demo_score_has_sources_and_reset_preserves_history(actors):
    a,b=actors;s=controller();first=utter('今天心情有点低落。');s.observe(first);s.start_demo(first.message_id)
    entries=[first,*collect_three(s)]
    sid=a.create('voice_short_demo',started_at=now()).json()['recording_session_id']
    record_ids=[]
    for i,e in enumerate(entries,1):
        response=a.send(sid,i,**e.wire());assert response.status_code==201
        record_ids.append(response.json()['record_id'])
    assert a.request('POST',f'/api/robot-records/sessions/{sid}/close',json=dict(ended_at=now(),last_sequence_no=len(entries))).status_code==200
    attach_sources(a.uid,sid,s,{});store_plan(a.uid,True,s);assert save_result(a.uid,sid,s)
    result=a.request('GET',f'/api/robot-voice/screening-results/{sid}').json()['result']
    assert result['demo_mode'] and result['scales'][0]['total']==6
    assert result['source_status']=='current_original_text'
    assert b.request('GET',f'/api/robot-voice/screening-results/{sid}').status_code==404
    with SessionLocal() as db:before=db.query(RecordMessage).count()
    assert a.request('POST','/api/robot-voice/demo/reset').json()['history_preserved']
    with SessionLocal() as db:assert db.query(RecordMessage).count()==before
    assert read_plan(a.uid,True) is None
    assert a.request('GET',f'/api/robot-voice/screening-results/{sid}').json()['result']['scales'][0]['total']==6
    # The first frequency answer is entries[2]. Editing it invalidates the score.
    assert a.request('POST',f'/api/robot-insights/messages/{record_ids[2]}/corrections',json=dict(
        request_id='edit-demo-answer',base_revision=0,content='频率需要重新确认。')).status_code==201
    assert a.request('GET',f'/api/robot-voice/screening-results/{sid}').json()['result']['scales'][0]['total'] is None


def test_demo_reset_cannot_cancel_an_active_call_or_unresolved_safety_task(actors):
    a,_=actors;api.ACTIVE.add(a.uid)
    try:assert a.request('POST','/api/robot-voice/demo/reset').status_code==409
    finally:api.ACTIVE.discard(a.uid)
    s=controller();s.observe(utter('我不想活了。'));store_plan(a.uid,True,s)
    assert a.request('POST','/api/robot-voice/demo/reset').status_code==409


def test_public_mode_is_explicit_and_contains_no_credentials(actors,monkeypatch):
    a,_=actors;r=a.client.get('/api/robot-voice/mode')
    assert r.status_code==200 and r.json()['mode']=='demo' and r.headers['cache-control']=='no-store'
    assert 'password' not in r.text and 'token' not in r.text and 'api_key' not in r.text
    monkeypatch.setenv('ROBOT_CARE_COLLECTION_DEMO','false')
    assert a.client.get('/api/robot-voice/mode').json()['mode']=='normal'


def test_profile_and_results_can_load_concurrently_without_nested_read_locks(actors):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    a,_=actors
    with ThreadPoolExecutor(max_workers=2) as pool:
        for _ in range(12):
            barrier=Barrier(2)
            def read(route):
                barrier.wait()
                return a.request('GET','/api/robot-insights/'+route)
            responses=list(pool.map(read,('profile','assessments')))
            assert [r.status_code for r in responses]==[200,200]
            assert responses[1].json()['demo_mode'] is True


@pytest.mark.parametrize('answer,value',[('经常。',3),('经常这样。',3),('有时会这样。',2),('较少',1)])
def test_demo_spoken_frequency_is_recorded_without_second_yes(answer,value):
    s=controller();s.start_demo('trigger')
    question=utter('最近两周，心情低落或没兴趣的情况怎么样？','assistant');s.observe(question)
    source=utter(answer);s.observe(source)
    assert s.answers['mood_interest:1']['value']==value
    assert s.answers['mood_interest:1']['evidence_ids']==[source.message_id]
    assert s.answers['mood_interest:1']['question_context_id']==question.message_id
    assert s.current()[1]==2


@pytest.mark.parametrize('question,answer',[
    ('今天心情低落吗？','经常'),('最近两周睡眠怎么样？','有时'),
    ('最近两周心情低落的频率怎样？','可能经常吧'),('最近两周心情低落的频率怎样？','会的')])
def test_demo_never_guesses_missing_window_topic_or_frequency(question,answer):
    s=controller();s.start_demo('trigger');s.observe(utter(question,'assistant'));s.observe(utter(answer))
    assert not s.answers


def test_typography_matching_keeps_actual_source_span_and_rejects_paraphrase():
    from app.voice.grounding import source_span
    assert source_span('最近心情低落做事没兴趣','最近心情低落，做事没兴趣。')=='最近心情低落，做事没兴趣'
    assert source_span('每天都心情低落','最近心情低落。') is None


def test_direct_answer_does_not_get_extracted_for_next_item():
    async def updated():pass
    s=controller();s.start_demo('trigger');m=ScreeningMonitor(s,updated)
    q=utter('最近两周心情低落的情况怎么样？','assistant');s.observe(q);m.observe(q)
    source=utter('经常这样。');s.observe(source);m.last_error_code='answer_candidate_invalid';m.observe(source)
    assert m.queue.empty() and m.last_error_code is None and s.current()[1]==2


def test_explicit_answer_before_delayed_trigger_is_recovered():
    s=controller()
    q=utter('最近两周心情低落的情况怎么样？','assistant');a=utter('经常这样。')
    s.observe(q);s.observe(a)
    assert not s.answers
    s.start_demo('trigger')
    assert s.reconcile_demo_turns([q,a])
    assert s.answers['mood_interest:1']['value']==3
    assert not s.reconcile_demo_turns([q,a])


def test_completed_question_is_not_reasked_or_mapped_to_next_item():
    s=controller();s.start_demo('trigger')
    for entry in [utter('最近两周心情低落的情况怎么样？','assistant'),utter('经常')]:s.observe(entry)
    for entry in [utter('最近两周这种没兴趣的状态经常出现吗？','assistant'),utter('经常')]:s.observe(entry)
    assert len(s.answers)==1 and s.pending is None and s.current()[1]==2


def test_out_of_order_self_worth_answer_counts_for_third_item():
    s=controller();s.start_demo('trigger')
    for entry in [utter('最近两周低落出现多少？','assistant'),utter('经常'),
        utter('最近两周会不会经常觉得自己没价值或者总责怪自己？','assistant'),utter('经常出现。')]:s.observe(entry)
    assert set(s.answers)=={'mood_interest:1','mood_interest:3'}
    assert s.answers['mood_interest:3']['value']==3 and s.current()[1]==2
    assert s.view()['scales'][0]['answered']==2
    from app.voice.screening import demo_question_item
    assert demo_question_item('自责确实让人难受。最近两周精力不足的情况怎么样？')==2


def test_cross_call_progress_prompt_and_order_independent_persistence(actors):
    from app.voice.collection_plan import restore
    a,_=actors
    s=controller();s.start_demo('trigger')
    for n,pairs in enumerate([
        [('最近两周心情低落的情况怎么样？','assistant'),('经常','user')],
        [('最近两周会不会觉得自己没价值或者总责怪自己？','assistant'),('经常出现。','user')],
        [('最近两周精力不足或做事提不起劲的情况怎么样？','assistant'),('较少','user')]],1):
        if n>1:
            s=controller();restore(s,read_plan(a.uid,True))
            prompt=s.instructions()
            assert '这些方向已完成，不重复询问' in prompt and '下一项只了解“精力与行动受到影响”' in prompt
            s.stage='collecting'
        sid=a.create('voice_resume_'+str(n),started_at=now()).json()['recording_session_id']
        entries=[]
        for text,role in pairs:
            e=utter(text,role);s.observe(e);entries.append(e)
        for i,e in enumerate(entries,1):assert a.send(sid,i,**e.wire()).status_code==201
        assert a.request('POST',f'/api/robot-records/sessions/{sid}/close',json=dict(ended_at=now(),last_sequence_no=len(entries))).status_code==200
        attach_sources(a.uid,sid,s,{});store_plan(a.uid,True,s);assert save_result(a.uid,sid,s)
        result=a.request('GET','/api/robot-insights/assessments').json()
        assert result['collection_plan']['scales'][0]['answered']==n
        assert result['conversation_collections'][0]['source_status']=='current_original_text'
    assert s.view()['scales'][0]['total']==7 and not read_plan(a.uid,True)['needs_collection']


@pytest.mark.parametrize('answer,value',[('偶尔',1),('时不时',2),('常常',3),('从来没有',0)])
def test_natural_frequency_synonyms_have_auditable_mapping(answer,value):
    s=controller();s.start_demo('trigger');s.observe(utter('最近两周心情低落的情况怎么样？','assistant'));s.observe(utter(answer))
    assert s.answers['mood_interest:1']['value']==value


def test_yes_requires_one_explicit_frequency_option_in_question():
    from app.voice.screening import frequency_answer
    assert frequency_answer('是的。',CUSTOM_OPTIONS,'最近两周低落经常出现吗？')==3
    assert frequency_answer('是的。',CUSTOM_OPTIONS,'最近两周低落不是经常出现吧？') is None
    assert frequency_answer('是的。',CUSTOM_OPTIONS,'最近两周低落经常还是有时出现？') is None
    assert frequency_answer('会的',CUSTOM_OPTIONS,'最近两周会低落吗？') is None


def test_durable_review_recovers_without_manual_script_and_is_idempotent(actors):
    from app.voice.demo_reconciliation import scan,register,DemoAnswerReview
    a,_=actors;s=controller();s.start_demo('trigger');store_plan(a.uid,True,s)
    sid=a.create('voice_durable_demo',started_at=now()).json()['recording_session_id']
    from app.robot_records import RecordSession
    with SessionLocal() as db:external=db.get(RecordSession,sid).external_session_id
    register(a.uid,external,s)
    pairs=[('最近两周心情低落经常出现吗？','assistant'),('是的。','user'),
        ('刚才聊到低落。最近两周会不会觉得自己没价值？','assistant'),('常常','user'),
        ('最近两周做事没精力的情况怎么样？','assistant'),('偶尔','user')]
    entries=[utter(text,role) for text,role in pairs]
    for i,e in enumerate(entries,1):assert a.send(sid,i,**e.wire()).status_code==201
    # An uploaded but still-open call is never reconciled.
    assert scan()==0 and not read_plan(a.uid,True)['answers']
    assert a.request('POST',f'/api/robot-records/sessions/{sid}/close',json=dict(ended_at=now(),last_sequence_no=len(entries))).status_code==200
    assert scan()==1
    result=a.request('GET','/api/robot-insights/assessments').json()
    assert result['collection_plan']['status']=='complete'
    saved=result['conversation_collections'][0]
    assert saved['scales'][0]['total']==7 and saved['source_status']=='current_original_text'
    assert scan()==0
    with SessionLocal() as db:assert db.get(DemoAnswerReview,external).state=='complete'


def test_plan_and_receipt_are_committed_together(actors):
    from app.voice.demo_reconciliation import DemoAnswerReview
    a,_=actors;s=controller();s.start_demo('trigger');s.collection_external_session_id='voice_atomic_demo'
    store_plan(a.uid,True,s)
    with SessionLocal() as db:
        receipt=db.get(DemoAnswerReview,'voice_atomic_demo')
        assert receipt.owner==a.uid and receipt.episode_id==read_plan(a.uid,True)['episode_id']


def test_durable_review_never_resumes_declined_task(actors):
    from app.voice.demo_reconciliation import scan
    a,_=actors;s=controller();s.start_demo('trigger');s.action('decline');store_plan(a.uid,True,s)
    assert scan()==0 and read_plan(a.uid,True)['status']=='declined'


@pytest.mark.parametrize('question',['最近两周心情很好的情况经常吗？','最近两周精力充沛的情况经常吗？','最近两周评价自己的情况经常吗？'])
def test_positive_or_unspecified_direction_is_never_scored_as_distress(question):
    from app.voice.screening import demo_question_item
    assert demo_question_item(question) is None


def test_receipt_waits_for_live_call_and_obeys_recall_window(actors):
    from app.voice.demo_reconciliation import scan,register,DemoAnswerReview
    from app.voice.after_call import touch_live_call,end_live_call
    from app.robot_records import RecordSession
    a,_=actors;s=controller();s.start_demo('trigger');store_plan(a.uid,True,s)
    sid=a.create('voice_receipt_lease',started_at=now()).json()['recording_session_id']
    with SessionLocal() as db:external=db.get(RecordSession,sid).external_session_id
    register(a.uid,external,s)
    entries=[utter('最近两周心情低落的情况怎么样？','assistant'),utter('经常')]
    for i,e in enumerate(entries,1):assert a.send(sid,i,**e.wire()).status_code==201
    assert a.request('POST',f'/api/robot-records/sessions/{sid}/close',json=dict(ended_at=now(),last_sequence_no=2)).status_code==200
    touch_live_call(a.uid,True,'voice_other_call')
    assert scan()==0
    end_live_call(a.uid,True,'voice_other_call')
    with SessionLocal() as db:
        row=db.get(DemoAnswerReview,external);row.window_end='2000-01-01';db.commit()
    assert scan()==0
    with SessionLocal() as db:
        row=db.get(DemoAnswerReview,external);row.window_end=s.window_end;db.commit()
    assert scan()==1 and len(read_plan(a.uid,True)['answers'])==1


def test_reconciliation_stops_on_refusal_without_guessing_following_answers():
    s=controller();s.start_demo('trigger')
    turns=[utter('我不想回答这些问题。'),utter('最近两周心情低落的情况怎么样？','assistant'),utter('经常')]
    assert not s.reconcile_demo_turns(turns) and s.stage=='declined' and not s.answers



def test_unclear_answer_requests_clarification_instead_of_silently_stalling():
    s=controller();s.start_demo('trigger');s.observe(utter('最近两周心情低落的情况怎么样？','assistant'))
    version=s.version;s.observe(utter('不太确定。'))
    assert s.version>version and not s.answers and '请温和补问一次' in s.instructions()


def test_ending_call_keeps_task_and_does_not_restart_questions():
    s=controller();s.start_demo('trigger');s.observe(utter('好的，那我们结束对话吧。'))
    assert s.end_after_response and '不再提问' in s.instructions() and s.triggered



def test_background_refusal_does_not_create_empty_score(actors):
    from app.voice.demo_reconciliation import scan,register
    from app.voice.screening import ScreeningResult
    from app.robot_records import RecordSession
    a,_=actors;s=controller();s.start_demo('trigger');store_plan(a.uid,True,s)
    sid=a.create('voice_background_refusal',started_at=now()).json()['recording_session_id']
    with SessionLocal() as db:external=db.get(RecordSession,sid).external_session_id
    register(a.uid,external,s)
    e=utter('我不想回答这些问题。');assert a.send(sid,1,**e.wire()).status_code==201
    assert a.request('POST',f'/api/robot-records/sessions/{sid}/close',json=dict(ended_at=now(),last_sequence_no=1)).status_code==200
    assert scan()==1 and read_plan(a.uid,True)['status']=='declined'
    with SessionLocal() as db:assert db.get(ScreeningResult,sid) is None
