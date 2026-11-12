from app.database import SessionLocal
from app.voice.screening import CollectionTrace,ITEMS,OPTIONS,Screening,ScreeningResult,save_result
from test_guided_screening import collect,say

P='/api/robot-insights'

def history(actor):
    response=actor.request('GET',P+'/assessments')
    assert response.status_code==200
    return response.json()['conversation_collections']

def saved(actor,*,complete=False):
    sid=actor.create('collection-results').json()['recording_session_id']
    controller=collect()
    entries=[]
    for scale,topics in ITEMS.items():
        for index,topic in enumerate(topics):
            value=0 if scale=='PHQ-9' and index==8 else 1
            entries.extend([say(controller,'最近两周关于'+topic+'，情况怎么样？','assistant'),
                say(controller,OPTIONS[value]),
                say(controller,'最近两周关于'+topic+'，我理解是'+OPTIONS[value]+'，对吗？','assistant'),
                say(controller,'对')])
            if not complete:break
        if not complete:break
    for seq,entry in enumerate(entries,1):
        body=entry.wire();body.pop('occurred_at')
        assert actor.send(sid,seq,**body).status_code==201
    assert save_result(actor.uid,sid,controller)
    return sid


def test_actual_collection_is_separate_from_legacy_assessments_and_owned(actors,monkeypatch):
    monkeypatch.setenv('ROBOT_CARE_ASSESSMENT_PROVIDER','disabled')
    a,b=actors;sid=saved(a)
    response=a.request('GET',P+'/assessments').json()
    assert response['items']==[] and response['status']=='disabled'
    item=response['conversation_collections'][0]
    assert item['recording_session_id']==sid and item['scales'][0]['answered']==1
    assert item['source_status']=='current_original_text' and item['scales'][0]['total'] is None
    assert item['source_record_ids'] and not item['formal_assessment']
    assert history(b)==[]


def test_complete_both_totals_require_evidence_and_edits_hide_them(actors):
    a,_=actors;sid=saved(a,complete=True)
    item=history(a)[0]
    assert [s['total'] for s in item['scales']]==[8,7]
    dto=a.request('POST',P+'/reports/preview',json={'scope':{'session_ids':[sid]}}).json()
    assert [s['total'] for s in dto['conversation_assessments'][0]['scales']]==[8,7]
    assert dto['assessments']==[]  # no conversational estimates in formal trends
    rid=next(m['record_id'] for m in a.messages(sid).json()['items'] if m['role']=='user')
    assert a.request('POST',P+f'/messages/{rid}/corrections',json=dict(request_id='edited-evidence',base_revision=0,content='原来那句话需要核实。')).status_code==201
    item=history(a)[0]
    assert item['source_status']=='needs_revalidation' and all(s['total'] is None for s in item['scales'])
    voice=a.request('GET',f'/api/robot-voice/screening-results/{sid}').json()['result']
    assert voice['source_status']=='needs_revalidation' and all(s['total'] is None for s in voice['scales'])
    dto=a.request('POST',P+'/reports/preview',json={'scope':{'session_ids':[sid]}}).json()
    assert all(s['total'] is None for s in dto['conversation_assessments'][0]['scales'])


def test_progress_receipts_do_not_manufacture_empty_scale_records_and_delete_cascades(actors):
    a,_=actors;sid=a.create('collection-progress').json()['recording_session_id']
    controller=Screening(True,'notice-v1')
    say(controller,'我有点不想活了都。')
    assert save_result(a.uid,sid,controller) is False
    item=history(a)[0]
    assert item['stage']=='urgent' and item['scales']==[]
    with SessionLocal() as db:
        assert db.get(ScreeningResult,sid) is None
        assert db.get(CollectionTrace,sid) is not None
    assert a.request('DELETE',f'/api/robot-records/sessions/{sid}').status_code==204
    assert history(a)==[]
    with SessionLocal() as db:assert db.get(CollectionTrace,sid) is None


def test_old_session_does_not_invent_missing_collection_reason(actors):
    a,_=actors;a.create('old-collection')
    item=history(a)[0]
    assert item['stage']=='not_recorded' and item['scales']==[]


def test_missing_original_evidence_never_exposes_total(actors):
    a,_=actors;sid=a.create('missing-evidence').json()['recording_session_id']
    controller=collect()
    for scale,topics in ITEMS.items():
        for index,topic in enumerate(topics):
            value=0 if scale=='PHQ-9' and index==8 else 1
            say(controller,OPTIONS[value]);say(controller,'最近两周关于'+topic+'，我理解是'+OPTIONS[value]+'，对吗？','assistant');say(controller,'对')
    assert save_result(a.uid,sid,controller)
    item=history(a)[0]
    assert item['source_status']=='needs_revalidation'
    assert all(s['total'] is None for s in item['scales'])
