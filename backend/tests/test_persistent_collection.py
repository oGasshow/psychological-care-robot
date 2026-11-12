import json
import pytest
from datetime import datetime,timezone,timedelta
from app.voice.screening import Screening,ITEMS,OPTIONS,save_result
from app.voice.collection_plan import store_plan,read_plan,restore,public_plan
from app.voice.continuity import recent_context
from app.voice.transcripts import Transcripts
from test_guided_screening import collect,say,decision

def stamp():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')

def test_owner_history_uses_effective_text_and_excludes_fixtures_and_deleted(actors):
    a,b=actors
    sid=a.create('voice_history',started_at=stamp()).json()['recording_session_id']
    rid=a.send(sid,content='我不想活了。',occurred_at=stamp()).json()['record_id']
    assert a.request('POST',f'/api/robot-records/sessions/{sid}/close',json={'ended_at':stamp(),'last_sequence_no':1}).status_code==200
    context=recent_context(a.uid,is_test=True)
    assert context['danger_history'] and context['session_ids']==[sid]
    assert recent_context(b.uid,is_test=True)['turns']==[]
    assert recent_context(a.uid,is_test=False)['turns']==[]
    a.request('POST',f'/api/robot-insights/messages/{rid}/corrections',json=dict(request_id='correct-history',base_revision=0,content='今天去公园散步。'))
    assert not recent_context(a.uid,is_test=True)['danger_history']
    a.request('DELETE',f'/api/robot-records/sessions/{sid}')
    assert recent_context(a.uid,is_test=True)['turns']==[]


def test_flag_survives_calls_no_signal_and_only_complete_clears_it(actors):
    a,b=actors;first=collect()
    store_plan(a.uid,True,first)
    assert public_plan(a.uid,True)['needs_collection']
    assert not public_plan(b.uid,True)['needs_collection']
    assert not public_plan(a.uid,False)['needs_collection']
    second=Screening(True,'notice-v1');restore(second,read_plan(a.uid,True))
    assert second.triggered and second.stage=='waiting_context'
    second.apply_decision(decision(outcome='no_signal',ready=False))
    store_plan(a.uid,True,second)
    assert public_plan(a.uid,True)['needs_collection']
    for scale,topics in ITEMS.items():
        for i,_ in enumerate(topics):second.answers[f'{scale}:{i+1}']=dict(value=0,evidence_ids=['fictional','confirmation'],confirmation_context_id='q')
    # Use actual owned transcript sources so completion cannot survive missing inputs.
    sid=a.create('voice_complete',started_at=stamp()).json()['recording_session_id']
    a.send(sid,external_message_id='fictional',content='完全没有')
    a.send(sid,2,external_message_id='q',role='assistant',playback_status='unknown',content='最近两周完全没有，对吗？')
    a.send(sid,3,external_message_id='confirmation',content='对')
    second.stage='complete';store_plan(a.uid,True,second)
    assert public_plan(a.uid,True)['needs_collection'] is False
    third=Screening(True);restore(third,read_plan(a.uid,True))
    assert third.stage=='companionship' and not third.triggered


def test_urgent_flag_is_retained_and_new_call_checks_in_first(actors):
    a,_=actors;first=Screening(True,'notice-v1');say(first,'我想死了。')
    store_plan(a.uid,True,first)
    second=Screening(True,'notice-v1');restore(second,read_plan(a.uid,True))
    assert second.stage=='checking_in' and second.triggered
    say(second,'我现在好一点了')
    assert second.stage=='checking_in'
    assert public_plan(a.uid,True)['needs_collection']


def test_natural_candidate_waits_for_topic_confirmation(actors):
    from app.voice.answer_extractor import validate
    from app.voice.concern_detector import snapshot
    s=collect(['PHQ-9'])
    question=say(s,'最近两周，原来喜欢做的事情也很难提起兴趣吗？','assistant')
    answer=say(s,'这两周里大概有三四天，其他时候还好。')
    data=snapshot([question,answer])
    raw=dict(relevant=True,question_id=question.message_id,question_quote=question.text,
        answer_id=answer.message_id,answer_quote=answer.text,window_id=question.message_id,
        window_quote='最近两周',frequency_quote='大概有三四天',value=1)
    candidate=validate(json.dumps(raw),data)
    assert s.accept_candidate(candidate,s.current()) and not s.answers
    assert s.observations[0]['status']=='awaiting_confirmation'
    say(s,'最近两周做事缺少兴趣或乐趣有几天，对吗？','assistant');say(s,'对')
    assert s.answers['PHQ-9:1']['value']==1
    assert s.answers['PHQ-9:1']['question_context_id']==question.message_id


def test_missing_cancel_ack_does_not_block_new_unidentified_text():
    t=Transcripts();t.apply(dict(type='conversation.item.input_audio_transcription.completed',item_id='q1',text='旧问题'))
    old,_=t.apply(dict(type='response.output_text.delta',response_id='old',delta='旧回复'));t.interrupt()
    t.apply(dict(type='conversation.item.input_audio_transcription.completed',item_id='q2',text='新问题'))
    new,out=t.apply(dict(type='response.output_text.delta',delta='新回复'))
    assert out['text']=='新回复' and new is not old
    late,out=t.apply(dict(type='response.output_audio.delta',response_id='old',delta=''))
    assert late is old and out is None


def test_partial_answers_survive_reused_provider_ids_in_next_call(actors):
    from app.voice.collection_sources import attach_sources
    a,_=actors;sid=a.create('voice_partial',started_at=stamp()).json()['recording_session_id']
    s=collect(['PHQ-9']);entries=[say(s,'最近两周做事缺少兴趣或乐趣的情况怎么样？','assistant'),say(s,'有几天'),
        say(s,'最近两周做事缺少兴趣或乐趣有几天，对吗？','assistant'),say(s,'对')]
    first_user=None
    for i,e in enumerate(entries,1):
        body=e.wire();body.pop('occurred_at')
        r=a.send(sid,i,**body)
        assert r.status_code==201
        if e.role=='user' and first_user is None:first_user=r.json()['record_id']
    attach_sources(a.uid,sid,s,{});store_plan(a.uid,True,s)
    later=a.create('voice_later',started_at=stamp()).json()['recording_session_id']
    for i,e in enumerate(entries,1):
        body=e.wire();body.pop('occurred_at');body['content']='另一通话的不同原话'
        assert a.send(later,i,**body).status_code==201
    restored=Screening(True);restore(restored,read_plan(a.uid,True))
    assert restored.answers['PHQ-9:1']['value']==1 and restored.current()[1]==2
    a.request('POST',f'/api/robot-insights/messages/{first_user}/corrections',json=dict(request_id='edited-source',base_revision=0,content='频率需要重新确认。'))
    data=read_plan(a.uid,True)
    assert data['needs_collection'] and data['answers']=={}


def test_generic_small_talk_and_missing_window_cannot_score():
    from app.voice.answer_extractor import validate
    from app.voice.concern_detector import snapshot
    s=collect(['PHQ-9']);q=say(s,'最近有什么让你觉得轻松的小事？','assistant');u=say(s,'没有。')
    data=snapshot([q,u]);data['target']=dict(scale='PHQ-9',item=1)
    raw=dict(relevant=True,question_id=q.message_id,question_quote=q.text,answer_id=u.message_id,answer_quote=u.text,
        window_id='',window_quote='',frequency_quote='没有',value=0)
    with pytest.raises(ValueError):validate(json.dumps(raw),data)
    q.text='做事提不起兴趣的时候多吗？';data=snapshot([q,u]);raw.update(question_quote=q.text)
    with pytest.raises(ValueError):validate(json.dumps(raw),data)


def test_short_model_ids_are_grounded_then_mapped_back_with_bounded_retry(monkeypatch):
    import asyncio
    from app.voice import upstream
    from app.voice.answer_extractor import extract
    from app.voice.concern_detector import snapshot
    s=collect(['PHQ-9']);q=say(s,'最近两周做事提不起兴趣的情况怎么样？','assistant');a=say(s,'这两周有三四天。')
    calls=[]
    async def model(*args,**kwargs):
        data=args[2];calls.append(data)
        if len(calls)==1:return '{"type":"object","properties":{}}'
        return json.dumps(dict(relevant=True,question_id='T1',question_quote=q.text,answer_id='T2',answer_quote=a.text,
            window_id='T1',window_quote='最近两周',frequency_quote='有三四天',value=1))
    monkeypatch.setattr(upstream,'structured_tool',model)
    result=asyncio.run(extract(snapshot([q,a]),('PHQ-9',1,'做事缺少兴趣或乐趣')))
    assert len(calls)==2 and calls[0]['turns'][0]['message_id']=='T1'
    assert result['answer_id']==a.message_id and result['question_id']==q.message_id and result['value']==1
