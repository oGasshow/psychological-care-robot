from copy import deepcopy
import uuid
import pytest
from app.database import SessionLocal
from app.robot_records import now,RecordSession
from app.voice.screening import Screening,CollectionTrace,frequency_answer,CUSTOM_OPTIONS,OPTIONS
from app.voice.transcripts import Utterance
from app.voice.collection_sources import attach_sources
from app.voice.collection_plan import store_plan,read_plan
from app.voice.live_checkpoint import save_checkpoint
from app.voice.demo_reconciliation import register,scan

@pytest.fixture(autouse=True)
def demo(monkeypatch):
 for k,v in dict(APP_ENV='test',ROBOT_CARE_COLLECTION_DEMO='true',ROBOT_CARE_RUNTIME_ROLE='collection_demo',ROBOT_CARE_DEMO_DATABASE='true',ROBOT_CARE_GUIDED_SCREENING_ENABLED='true',ROBOT_CARE_PURCHASE_NOTICE_VERSION='fictional-v3').items():monkeypatch.setenv(k,v)

def utter(text,role='user'):return Utterance(uuid.uuid4().hex,role,'test',text=text,final=True,occurred_at=now())
def controller():
 s=Screening(True,'fictional-v3');s.demo_mode=True;s.direct_collection=True;s.start_demo('test-trigger');return s

def turns():return [utter(t,r) for t,r in [
 ('最近两周，你觉得对什么都没乐趣或者情绪低落的情况属于哪种频率？','assistant'),('较少。','user'),
 ('最近两周里，有没有经常觉得疲惫，或者没做什么事也觉得累？','assistant'),('会的呀。','user'),
 ('这种没缘由的疲惫，最近两周是从不、较少、有时、经常还是几乎总是出现呢？','assistant'),('这种感觉经常出现呢。','user'),
 ('最近两周，你会不会经常觉得自己没什么用，或者对未来没什么盼头？','assistant'),('有一点点吧，不严重。','user'),
 ('那这种感受最近两周是属于有时出现吗？','assistant'),('偶尔会有。','user')]]

def upload(a,entries,closed=False):
 sid=a.create('voice_live_'+uuid.uuid4().hex[:12],started_at=now()).json()['recording_session_id']
 for n,e in enumerate(entries,1):assert a.send(sid,n,**e.wire()).status_code==201
 if closed:assert a.request('POST',f'/api/robot-records/sessions/{sid}/close',json=dict(ended_at=now(),last_sequence_no=len(entries))).status_code==200
 return sid

@pytest.mark.parametrize('text,value',[('这种感觉经常出现呢。',3),('偶尔会有。',1),('我感觉偶尔会出现这种情况吧，最近两周。',1),('这倒是没有。',0),('有时会这样。',2)])
def test_natural_frequency_in_full_reply(text,value):assert frequency_answer(text,CUSTOM_OPTIONS,'最近两周你会低落吗？')==value

@pytest.mark.parametrize('text',['可能经常吧','以前经常，现在偶尔','不经常','我朋友说他经常这样','有一点点，不严重','我经常看比赛'])
def test_ambiguous_or_unrelated_reply_never_guesses_frequency(text):assert frequency_answer(text,CUSTOM_OPTIONS,'最近两周你会低落吗？') is None

def test_same_call_collects_three_natural_answers_including_pronoun_followup(actors):
 a,_=actors;s=controller();entries=turns()
 for e in entries:s.observe(e)
 assert s.stage=='complete' and [s.answers[f'mood_interest:{i}']['value'] for i in (1,2,3)]==[1,3,1]
 assert s.answers['mood_interest:3']['question_context_id']==entries[6].message_id
 assert s.answers['mood_interest:3']['confirmation_context_id']==entries[8].message_id
 sid=upload(a,entries,closed=True);attach_sources(a.uid,sid,s,{});store_plan(a.uid,True,s)
 save_checkpoint(a.uid,sid,s,{})
 result=a.request('GET','/api/robot-insights/assessments').json()['conversation_collections'][0]
 assert result['source_status']=='current_original_text' and result['scales'][0]['total']==5

def test_open_call_has_saved_progress_before_end_and_old_checkpoint_cannot_regress_it(actors):
 a,_=actors;s=controller();entries=turns();sid=upload(a,entries)
 for e in entries[:2]:s.observe(e)
 old=deepcopy(s);store_plan(a.uid,True,s);r=save_checkpoint(a.uid,sid,s,{})
 assert r['answered']==1
 first=a.request('GET','/api/robot-insights/assessments').json()['conversation_collections'][0]
 assert first['stage']=='collecting' and first['scales'][0]['answered']==1
 for e in entries[2:]:s.observe(e)
 store_plan(a.uid,True,s);r=save_checkpoint(a.uid,sid,s,{})
 assert r['answered']==3
 save_checkpoint(a.uid,sid,old,{})
 current=a.request('GET','/api/robot-insights/assessments').json()
 assert current['collection_plan']['scales'][0]['answered']==3 and current['conversation_collections'][0]['scales'][0]['total']==5

def test_registered_saved_call_recovers_missing_trace_even_when_answers_already_in_plan(actors):
 a,_=actors;s=controller();entries=turns()
 for e in entries:s.observe(e)
 sid=upload(a,entries,closed=True);attach_sources(a.uid,sid,s,{});store_plan(a.uid,True,s)
 with SessionLocal() as db:external=db.get(RecordSession,sid).external_session_id
 register(a.uid,external,s)
 scan()
 result=a.request('GET','/api/robot-insights/assessments').json()['conversation_collections'][0]
 assert result['snapshot_kind']=='recovered_task_snapshot' and result['scales'][0]['total']==5
 assert result['source_status']=='current_original_text'

def test_invitation_advances_existing_safe_task_and_does_not_trigger_new_task():
 s=controller();s.stage='waiting_context';s.observe(utter('那你还有什么想问我的吗？'))
 assert s.stage=='collecting' and s.user_invited_questions and '本轮依次了解多个' in s.instructions()
 ordinary=Screening(True);ordinary.direct_collection=True;ordinary.observe(utter('你可以多问我一些问题。'))
 assert ordinary.stage=='companionship' and not ordinary.triggered

def test_affirmation_only_uses_a_uniquely_stated_frequency():
 assert frequency_answer('会的呀。',CUSTOM_OPTIONS,'最近两周会不会经常觉得疲惫？')==3
 assert frequency_answer('会的呀。',CUSTOM_OPTIONS,'最近两周会觉得疲惫吗？') is None

def test_standard_answer_never_uses_five_level_frequency():
 assert frequency_answer('这种感觉经常出现呢。',OPTIONS,'最近两周缺少兴趣的情况怎么样？') is None

def test_checkpoint_denies_another_owner(actors):
 a,b=actors;s=controller();sid=upload(a,[])
 with pytest.raises(ValueError,match='not_owned'):save_checkpoint(b.uid,sid,s,{})
