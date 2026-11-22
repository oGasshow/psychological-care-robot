from app.database import SessionLocal
from app.robot_records import now
from app.voice import sega_live
from app.voice.after_call import AfterCallReview
from test_sega_api import source


def test_experimental_positive_requires_current_user_evidence(actors,monkeypatch):
    owner,other=actors
    monkeypatch.setenv('APP_ENV','test')
    sid,users,questions=source(owner)
    owner.request('POST',f'/api/robot-records/sessions/{sid}/close',json={'ended_at':now(),'last_sequence_no':6})
    with SessionLocal() as db:
        result=dict(model_class=1,source_kind='automatic_voice_experimental',record_ids=users,
                    question_record_ids=questions,input_revisions={str(i):0 for i in users+questions})
        db.add(sega_live.SegaVoiceJob(session_id=sid,owner=owner.uid,is_test=True,state='succeeded',
                                    expires=0,inputs={},result=result))
        db.commit()
    path=f'/api/robot-voice/sega/sessions/{sid}'
    assert not sega_live.followup(owner.uid,True)['marked']
    assert owner.request('GET',path).json()['automatic_result']['model_class']==1
    assert owner.request('GET',path).json()['automatic_result']['followup_verification']=='pending_source_review'
    with SessionLocal() as db:
        db.add(AfterCallReview(session_id=sid,owner=owner.uid,state='succeeded',input_hash='test',source_refs={},
            result={'decision':'no_signal','target_scales':[]},updated_at=now()))
        db.commit()
    assert not sega_live.followup(owner.uid,True)['marked']
    assert owner.request('GET',path).json()['automatic_result']['followup_verification']=='not_supported_by_user_evidence'
    with SessionLocal() as db:
        row=db.get(AfterCallReview,sid)
        row.result={'decision':'follow_up','target_scales':['PHQ-9'], 'support_refs':[
            {'record_id':rid,'input_revision':0,'domain':domain} for rid,domain in zip(users[:2],('low_mood','energy'))]}
        db.commit()
    assert sega_live.followup(owner.uid,True)['marked']
    assert not sega_live.followup(other.uid,True)['marked']
    assert not sega_live.followup(owner.uid,False)['marked']
    owner.request('POST',f'/api/robot-insights/messages/{users[0]}/corrections',json={
        'request_id':'review-source-edit','base_revision':0,'content':'这句话需要更正。'})
    assert not sega_live.followup(owner.uid,True)['marked']
    assert owner.request('GET',path).json()['automatic_result']=={'followup_verification':'source_changed'}


def test_assistant_words_cannot_corroborate_experimental_positive(actors):
    owner,_=actors
    sid,users,questions=source(owner)
    with SessionLocal() as db:
        db.add(sega_live.SegaVoiceJob(session_id=sid,owner=owner.uid,is_test=True,state='succeeded',
            expires=0,inputs={},result=dict(model_class=1,source_kind='automatic_voice_experimental',
                record_ids=users,question_record_ids=questions,input_revisions={str(i):0 for i in users+questions})))
        db.add(AfterCallReview(session_id=sid,owner=owner.uid,state='succeeded',input_hash='test',source_refs={},
            result={'decision':'follow_up','target_scales':['PHQ-9'],'support_refs':[
                {'record_id':rid,'input_revision':0,'domain':'low_mood'} for rid in questions]},updated_at=now()))
        db.commit()
    assert not sega_live.followup(owner.uid,True)['marked']
