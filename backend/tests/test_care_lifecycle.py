from uuid import uuid4

import pytest

from app.robot_records import now, transaction
from app.voice.care_status import profile, instructions
from app.voice.collection_plan import read_plan, restore, store_plan, prepare_sega_plan
from app.voice.collection_sources import attach_sources
from app.voice.screening import Screening, ITEMS, OPTIONS_BY_SCALE, save_result
from app.voice.sega_live import SegaVoiceJob
from test_scale_reports import entry


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    for key, value in dict(APP_ENV='test', ROBOT_CARE_COLLECTION_DEMO='false',
            ROBOT_CARE_GUIDED_SCREENING_ENABLED='true', ROBOT_CARE_PURCHASE_NOTICE_VERSION='test',
            ROBOT_CARE_PHQ_FOLLOWUP_THRESHOLD='10', ROBOT_CARE_REASSESSMENT_DAYS='14').items():
        monkeypatch.setenv(key, value)


def prediction(actor, label):
    sid=actor.create('voice_'+uuid4().hex,started_at=now()).json()['recording_session_id']
    question=actor.send(sid,1,role='assistant',playback_status='completed',content='虚构问题').json()['record_id']
    answer=actor.send(sid,2,content='虚构回答').json()['record_id']
    actor.request('POST',f'/api/robot-records/sessions/{sid}/close',json={'ended_at':now(),'last_sequence_no':2})
    with transaction(True) as db:
        db.add(SegaVoiceJob(session_id=sid,owner=actor.uid,is_test=True,state='succeeded',expires=0,
            inputs={},audio=None,result=dict(model_class=label,record_ids=[answer],question_record_ids=[question],
            input_revisions={str(answer):0,str(question):0})))
    prepare_sega_plan(actor.uid,True)
    return sid


def resume(actor):
    controller=Screening(True,'test')
    controller.core_only=True
    controller.direct_collection=True
    restore(controller,read_plan(actor.uid,True))
    controller.care_background=instructions(profile(actor.uid,True))
    return controller


def answer_items(actor, controller, indices, values):
    sid=actor.create('voice_'+uuid4().hex,started_at=now()).json()['recording_session_id']
    controller.stage='collecting'
    lines=[]
    for index in indices:
        for text,role in [(f'最近两周，{ITEMS["PHQ-9"][index-1]}的情况怎么样？','assistant'),
                          (OPTIONS_BY_SCALE['PHQ-9'][values[index-1]],'user')]:
            line=entry(text,role)
            controller.observe(line)
            lines.append(line)
    for seq,line in enumerate(lines,1):
        assert actor.send(sid,seq,**line.wire()).status_code==201
    actor.request('POST',f'/api/robot-records/sessions/{sid}/close',json={'ended_at':now(),'last_sequence_no':len(lines)})
    attach_sources(actor.uid,sid,controller,{})
    controller.history_session_ids.append(sid)
    store_plan(actor.uid,True,controller)
    save_result(actor.uid,sid,controller)
    return sid


@pytest.mark.parametrize('values,expected', [([0]*9,'routine'),([2]*8+[0],'high_concern')])
def test_five_conversations_complete_then_resume_companionship(actors, values, expected):
    actor,other=actors
    prediction(actor,0)
    assert profile(actor.uid,True)['care_status']=='routine'
    source=prediction(actor,1)
    episode=read_plan(actor.uid,True)['episode_id']
    assert profile(actor.uid,True)['care_status']=='followup'
    third=resume(actor)
    answer_items(actor,third,range(1,5),values)
    status=profile(actor.uid,True)
    assert status['needs_collection'] and status['scales'][0]['answered']==4
    fourth=resume(actor)
    assert fourth.current()[0]=='PHQ-9' and fourth.current()[1] in range(5,10)
    assert fourth.episode_id==episode
    last=answer_items(actor,fourth,range(5,10),values)
    assert not read_plan(actor.uid,True)['needs_collection']
    status=profile(actor.uid,True)
    assert status['care_status']==expected and not status['needs_collection']
    fifth=resume(actor)
    assert fifth.stage=='complete' and fifth.current() is None
    assert '继续温和倾听' in fifth.instructions()
    if expected=='high_concern':assert '更多关注' in fifth.instructions()
    completed=read_plan(actor.uid,True)['completed_at']
    assessment_time=profile(actor.uid,True)['assessment']['completed_at']
    store_plan(actor.uid,True,fifth)
    assert read_plan(actor.uid,True)['completed_at']==completed
    fifth_sid=actor.create('voice_'+uuid4().hex,started_at=now()).json()['recording_session_id']
    actor.send(fifth_sid,content='今天想聊一本书。',occurred_at=now())
    actor.request('POST',f'/api/robot-records/sessions/{fifth_sid}/close',json={'ended_at':now(),'last_sequence_no':1})
    save_result(actor.uid,fifth_sid,fifth)
    assert profile(actor.uid,True)['assessment']['completed_at']==assessment_time
    prediction(actor,0)
    prediction(actor,1)
    assert read_plan(actor.uid,True)['episode_id']==episode
    assert profile(actor.uid,True)['care_status']==expected
    assert profile(other.uid,True)['care_status']=='routine'
    assert profile(actor.uid,False)['care_status']=='routine'
    public=actor.request('GET','/api/robot-voice/care-status')
    assert public.status_code==200 and public.json()['clinical_diagnosis'] is False
    assert public.headers['cache-control']=='no-store'
    # Correcting a contributing answer invalidates the old score immediately.
    from app.database import SessionLocal
    from app.robot_records import RecordMessage
    with SessionLocal() as db:
        rid=db.query(RecordMessage).filter_by(recording_session_id=last,role='user').first().id
    actor.request('POST',f'/api/robot-insights/messages/{rid}/corrections',json=dict(
        request_id='correct-completed',base_revision=0,content='这条回答需要重新确认。'))
    assert profile(actor.uid,True)['care_status']=='followup'
    assert profile(actor.uid,True)['assessment'] is None
    assert profile(actor.uid,True)['needs_collection']
    fifth.observe(entry('我不想活了。','user'))
    assert fifth.stage=='urgent' and fifth.history_danger_unresolved


def test_completed_task_keeps_unresolved_safety_check(actors):
    actor,_=actors
    prediction(actor,1)
    controller=resume(actor)
    answer_items(actor,controller,range(1,10),[0]*9)
    controller.history_danger_unresolved=True
    store_plan(actor.uid,True,controller)
    following=resume(actor)
    assert following.stage=='checking_in' and following.needs_current_safety_check
