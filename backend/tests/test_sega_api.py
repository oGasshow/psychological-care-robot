import io,zipfile
import pytest
from app.voice import sega
from app.voice.collection_plan import public_plan

P='/api/robot-voice/sega'

def bundle():
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:z.writestr('dummy.npy',b'fictional')
    return out.getvalue()

def source(actor):
    sid=actor.create('sega-upload').json()['recording_session_id'];users=[];questions=[]
    for i in range(3):
        questions.append(actor.send(sid,2*i+1,role='assistant',playback_status='unknown',content='虚构访谈问题').json()['record_id'])
        users.append(actor.send(sid,2*i+2,content='虚构访谈回答').json()['record_id'])
    return sid,users,questions

def test_sega_missing_features_is_explicit_and_owned(actors):
    a,b=actors;sid=a.create().json()['recording_session_id']
    result=a.request('GET',P+f'/sessions/{sid}')
    assert result.status_code==200 and result.json()['result'] is None
    assert result.json()['input_status']=='missing_aligned_audio_and_auxiliary_features'
    assert result.json()['live_text_only_supported'] is False
    assert b.request('GET',P+f'/sessions/{sid}').status_code==404

def test_actual_adapter_result_can_create_pending_task_but_not_score_or_clear_it(actors,monkeypatch):
    a,b=actors;sid,users,questions=source(a)
    monkeypatch.setenv('ROBOT_CARE_GUIDED_SCREENING_ENABLED','true')
    monkeypatch.setenv('ROBOT_CARE_PURCHASE_NOTICE_VERSION','test-notice')
    def inference(**kwargs):return dict(status='succeeded',engine='SEGA-EATD-author-checkpoint',model_class=1,
        record_ids=users,question_record_ids=questions,experimental=True,formal_assessment=False,
        source_kind='manual_aligned_features_unverified')
    monkeypatch.setattr(sega,'execute',inference)
    r=a.request('POST',P+f'/sessions/{sid}',content=bundle())
    assert r.status_code==200 and r.json()['followup_task_created']
    plan=public_plan(a.uid,True)
    assert plan['needs_collection'] and plan['scales']==[dict(scale='PHQ-9',answered=0,required=9)]
    assert not public_plan(b.uid,True)['needs_collection']
    assert a.request('GET','/api/robot-insights/assessments').json()['items']==[]
    monkeypatch.setattr(sega,'execute',lambda **kwargs:{**inference(), 'model_class':0})
    assert a.request('POST',P+f'/sessions/{sid}',content=bundle()).status_code==200
    assert public_plan(a.uid,True)['needs_collection']  # negative output does not finish collection
    a.request('POST',f'/api/robot-insights/messages/{users[0]}/corrections',json=dict(request_id='sega-edit',base_revision=0,content='来源已更正。'))
    stale=a.request('GET',P+f'/sessions/{sid}').json()['result']
    assert stale['status']=='needs_revalidation' and 'model_class' not in stale

def test_cross_user_feature_sources_and_non_npz_are_rejected(actors,monkeypatch):
    a,b=actors;sid,_,_=source(a);_,users,questions=source(b)
    monkeypatch.setattr(sega,'execute',lambda **kwargs:dict(status='succeeded',model_class=1,record_ids=users,question_record_ids=questions))
    assert a.request('POST',P+f'/sessions/{sid}',content=bundle()).status_code==422
    assert a.request('POST',P+f'/sessions/{sid}',content=b'invalid').status_code==422
    assert b.request('POST',P+f'/sessions/{sid}',content=bundle()).status_code==404

def test_author_fixture_probe_does_not_write_personal_result_or_task(actors,monkeypatch):
    a,_=actors
    monkeypatch.setenv('APP_ENV','test')
    monkeypatch.setattr(sega,'execute',lambda **kwargs:dict(status='succeeded',source_kind='author_heldout_feature_fixture'))
    assert a.request('POST',P+'/probe').status_code==200
    assert not public_plan(a.uid,True)['needs_collection']
