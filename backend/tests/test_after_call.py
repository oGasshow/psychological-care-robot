import asyncio
import json
import pytest
from app.database import SessionLocal
from app.robot_records import now
from app.care.service import later
from app.voice.after_call import ReviewWorker, AfterCallReview
from app.voice.collection_plan import read_plan, restore, store_plan, CollectionPlan, key
from app.voice.screening import Screening
from app.voice.screening_monitor import ScreeningMonitor
from app.voice.screening_policy import collection_policy
from app.voice.concern_detector import validate
from app.voice.transcripts import Utterance


@pytest.fixture(autouse=True)
def post_session(monkeypatch):
    monkeypatch.setenv('APP_ENV','test')
    monkeypatch.setenv('ROBOT_CARE_GUIDED_SCREENING_ENABLED','true')
    monkeypatch.setenv('ROBOT_CARE_PURCHASE_NOTICE_VERSION','fictional-notice')
    monkeypatch.setenv('ROBOT_CARE_CONCERN_REVIEW_MODE','post_session')


def call(actor,name,texts,close=True):
    sid=actor.create('voice_'+name,started_at=now()).json()['recording_session_id']
    records=[]
    for i,text in enumerate(texts,1):
        records.append(actor.send(sid,i,content=text,occurred_at=now()).json()['record_id'])
    if close:
        assert actor.request('POST',f'/api/robot-records/sessions/{sid}/close',
            json=dict(ended_at=now(),last_sequence_no=len(texts))).status_code==200
    return sid,records


def output(data,decision='follow_up'):
    users=[t for t in data['turns'] if t['role']=='user']
    return validate(json.dumps(dict(decision=decision,target_scales=['PHQ-9'] if decision=='follow_up' else [],
        evidence=[dict(message_id=t['message_id'],quote=t['text'],domain='low_mood') for t in users[:2]]
            if decision=='follow_up' else [],transition_ready=True,latest_user_quote=users[-1]['text'],reason='虚构测试')),
        data)


async def assess(data):return output(data)


def job(sid):
    with SessionLocal() as db:
        row=db.get(AfterCallReview,sid)
        return dict(state=row.state,attempt=row.attempt,error=row.error_code,result=row.result)


def test_deployment_default_is_post_session(monkeypatch):
    monkeypatch.delenv('ROBOT_CARE_CONCERN_REVIEW_MODE')
    assert collection_policy().review_mode=='post_session'


def test_new_concerns_do_not_schedule_live_analysis():
    s=Screening(True);s.review_mode='post_session'
    async def updated():raise AssertionError('No new live analysis')
    m=ScreeningMonitor(s,updated)
    for i in range(5):m.observe(Utterance(str(i),'user','test',text='持续两周心情低落。',final=True))
    assert m.queue.empty() and s.stage=='companionship'
    assert '通话文字保存后' in s.instructions()


def test_two_short_calls_create_one_persistent_task_without_scoring(actors):
    a,b=actors;worker=ReviewWorker(assessor=assess)
    first,_=call(a,'first',['这两周持续心情低落。'])
    assert worker.scan()==1 and not worker.step()
    assert job(first)['state']=='insufficient_data' and read_plan(a.uid,True) is None
    second,_=call(a,'second',['最近半个月低落影响了工作。'])
    assert worker.scan()==1 and worker.step()
    plan=read_plan(a.uid,True)
    assert plan['needs_collection'] and plan['answers']=={}
    assert plan['target_scales']==['PHQ-9','mood_interest']
    assert set(plan['history_session_ids'])=={first,second}
    assert read_plan(b.uid,True) is None and read_plan(a.uid,False) is None
    assert worker.scan()==0 and not worker.step()
    reviews=a.request('GET','/api/robot-voice/after-call-reviews').json()['items']
    assert reviews[0]['state']=='succeeded'
    assert b.request('GET','/api/robot-voice/after-call-reviews').json()['items']==[]


def test_pending_task_can_resume_after_current_readiness_without_a_new_trigger(actors):
    a,_=actors;call(a,'resume',['持续两周低落。','最近半个月影响工作。'])
    worker=ReviewWorker(assessor=assess);worker.scan();assert worker.step()
    s=Screening(True);s.review_mode='post_session';restore(s,read_plan(a.uid,True))
    s.apply_decision(dict(decision='no_signal',target_scales=[],evidence=[],detector_version='fixture',transition_ready=False))
    assert s.stage=='waiting_context'
    s.apply_decision(dict(decision='no_signal',target_scales=[],evidence=[],detector_version='fixture',transition_ready=True))
    assert s.stage=='collecting' and s.current()[1]==1


def test_confirmed_item_is_retained_for_the_next_call(actors):
    from test_guided_screening import say
    from app.voice.collection_sources import attach_sources
    a,_=actors;call(a,'initial',['持续两周低落。','最近半个月影响工作。'])
    worker=ReviewWorker(assessor=assess);worker.scan();worker.step()
    s=Screening(True);s.review_mode='post_session';restore(s,read_plan(a.uid,True))
    s.apply_decision(dict(decision='no_signal',target_scales=[],evidence=[],detector_version='fixture',transition_ready=True))
    entries=[say(s,'最近两周做事缺少兴趣或乐趣的情况怎么样？','assistant'),say(s,'有几天'),
        say(s,'最近两周做事缺少兴趣或乐趣有几天，对吗？','assistant'),say(s,'对')]
    sid=a.create('voice_confirmation',started_at=now()).json()['recording_session_id']
    for i,e in enumerate(entries,1):
        body=e.wire();body.pop('occurred_at')
        assert a.send(sid,i,**body).status_code==201
    attach_sources(a.uid,sid,s,{})
    store_plan(a.uid,True,s)
    restored=Screening(True);restore(restored,read_plan(a.uid,True))
    assert restored.answers['PHQ-9:1']['value']==1 and restored.current()[1]==2
    assert read_plan(a.uid,True)['needs_collection']


def test_timeouts_retry_persistently_and_owner_can_retry_failed_job(actors):
    a,b=actors;sid,_=call(a,'fail',['持续两周低落。','最近半个月影响工作。'])
    async def timeout(data):raise TimeoutError()
    stamp=[now()];worker=ReviewWorker(clock=lambda:stamp[0],assessor=timeout);worker.scan()
    for i in range(3):
        assert worker.step()
        assert job(sid)['attempt']==i+1
        stamp[0]=later(200,stamp[0])
    assert job(sid)['state']=='failed' and read_plan(a.uid,True) is None
    assert b.request('POST',f'/api/robot-voice/after-call-reviews/{sid}/retry').status_code==404
    assert a.request('POST',f'/api/robot-voice/after-call-reviews/{sid}/retry').status_code==200
    worker.assessor=assess;assert worker.step()
    assert job(sid)['state']=='succeeded' and read_plan(a.uid,True)['needs_collection']


def test_correction_during_inference_rejects_old_result(actors):
    a,_=actors;sid,records=call(a,'edit',['持续两周低落。','最近半个月影响工作。'])
    worker=ReviewWorker(assessor=assess);worker.scan();claim=worker.claim()
    assert a.request('POST',f'/api/robot-insights/messages/{records[0]}/corrections',
        json=dict(request_id='after-call-edit',base_revision=0,content='更正原话：今天很开心。')).status_code==201
    assert not worker.finish(claim,result=output(claim['data']))
    assert job(sid)['state']=='invalidated' and read_plan(a.uid,True) is None
    assert worker.scan()==1 and job(sid)['state']=='pending'


def test_deleted_sources_cannot_apply_a_late_result(actors):
    a,_=actors;sid,_=call(a,'deleted',['持续两周低落。','最近半个月影响工作。'])
    worker=ReviewWorker(assessor=assess);worker.scan();claim=worker.claim()
    assert a.request('DELETE',f'/api/robot-records/sessions/{sid}').status_code==204
    assert not worker.finish(claim,result=output(claim['data']))
    assert a.request('GET','/api/robot-voice/after-call-reviews').json()['items']==[]
    assert read_plan(a.uid,True) is None


def test_active_call_defers_review_and_a_restart_can_reclaim_expired_lease(actors):
    a,_=actors;sid,_=call(a,'lease',['持续两周低落。','最近半个月影响工作。'])
    worker=ReviewWorker(assessor=assess);worker.scan();old=worker.claim()
    restarted=ReviewWorker(clock=lambda:later(200),assessor=assess)
    fresh=restarted.claim();assert fresh['token']!=old['token']
    assert not worker.finish(old,result=output(old['data']))
    assert restarted.finish(fresh,result=output(fresh['data']))
    other,_=call(a,'open',['持续两周低落。'],close=False)
    # A new completed call is discoverable, but not analyzed during another call.
    call(a,'deferred',['持续两周低落。','最近半个月影响工作。'])
    worker.scan();assert worker.claim() is None


def test_no_signal_review_does_not_clear_an_existing_task(actors):
    a,_=actors;call(a,'pending',['持续两周低落。','最近半个月影响工作。'])
    worker=ReviewWorker(assessor=assess);worker.scan();worker.step()
    old=read_plan(a.uid,True)
    call(a,'quiet',['今天散步了。','现在还想随便聊聊。'])
    async def quiet(data):return output(data,'no_signal')
    worker.assessor=quiet;worker.scan();assert worker.step()
    plan=read_plan(a.uid,True)
    assert plan['episode_id']==old['episode_id'] and plan['needs_collection']


def test_completed_task_is_not_reopened_by_review_of_the_same_call(actors):
    a,_=actors;sid,_=call(a,'complete',['持续两周低落。','最近半个月影响工作。'])
    with SessionLocal() as db:
        db.add(CollectionPlan(key=key(a.uid,True),owner=a.uid,updated_at=now(),payload=dict(
            needs_collection=False,status='complete',episode_id='fictional-completed',window_end=now()[:10],
            target_scales=[],answers={},completed_at=now())))
        db.commit()
    worker=ReviewWorker(assessor=assess);worker.scan();assert worker.step()
    assert not read_plan(a.uid,True)['needs_collection']
    assert job(sid)['result']['applied_to_task'] is False


def test_buffered_live_call_also_defers_background_review(actors):
    from app.voice.after_call import touch_live_call,end_live_call
    a,_=actors;call(a,'buffered',['持续两周低落。','最近半个月影响工作。'])
    worker=ReviewWorker(assessor=assess);worker.scan()
    touch_live_call(a.uid,True,'voice_still_in_local_outbox')
    assert worker.claim() is None
    # A stale close cannot remove a newer call's lease.
    end_live_call(a.uid,True,'some_other_call')
    assert worker.claim() is None
    end_live_call(a.uid,True,'voice_still_in_local_outbox')
    assert worker.step()
