import uuid
import pytest
from app.care.composite_score import calculate
from app.database import SessionLocal
from app.robot_records import now
from app.voice.screening import ScreeningResult
from test_scale_reports import setup_controller, save
from app.care.composite_score import for_sessions
from test_care_management import manager  # noqa: F401

KEYS=[('PHQ-9',i) for i in range(1,10)]+[('GAD-7',i) for i in range(1,8)]


@pytest.fixture(autouse=True)
def normal(monkeypatch):
    monkeypatch.setenv('ROBOT_CARE_GUIDED_SCREENING_ENABLED','true')
    monkeypatch.setenv('ROBOT_CARE_PURCHASE_NOTICE_VERSION','fictional-normal-v1')
    monkeypatch.setenv('ROBOT_CARE_COLLECTION_DEMO','false')


@pytest.mark.parametrize('total,band',[(0,'minimal'),(9,'minimal'),(10,'mild'),(19,'mild'),
    (20,'moderate'),(29,'moderate'),(30,'severe'),(48,'severe')])
def test_full_sum_and_boundaries(total,band):
    answers=dict.fromkeys(KEYS,0)
    for i in range(total):answers[KEYS[i//3]]+=1
    value=calculate(answers)
    assert value['score']==total and value['reference_band']==band
    assert value['confidence']==100 and value['score_kind']=='complete'
    assert value['confidence_basis']=='answer_completion_rate' and not value['clinical_diagnosis']


@pytest.mark.parametrize('count,confidence,level',[(1,6.25,'low'),(7,43.75,'low'),(8,50,'medium'),
    (12,75,'medium'),(13,81.25,'high'),(16,100,'high')])
def test_partial_prorates_all_sixteen_items_and_coverage(count,confidence,level):
    value=calculate(dict.fromkeys(KEYS[:count],1))
    assert value['score']==16 and value['confidence']==confidence and value['confidence_level']==level
    assert value['possible_total_min']==count and value['possible_total_max']==count+3*(16-count)


def test_empty_invalid_and_unanswered_item_nine_are_not_normal_findings():
    value=calculate({('PHQ-9',1):True,('GAD-7',8):3,('PHQ-9',2):4,('unknown',1):1})
    assert value['score'] is None and value['confidence']==0 and value['reference_band'] is None
    assert not value['item9_answered'] and not value['item9_attention']
    value=calculate({('PHQ-9',9):1})
    assert value['item9_answered'] and value['item9_attention']


def test_report_scope_does_not_inherit_other_call_answers(actors,manager):
    a,b=actors
    controller=setup_controller();controller.episode_id=uuid.uuid4().hex;controller.window_end=now()[:10]
    first=save(a,controller,'PHQ-9',[1]*8+[0])
    second=save(a,controller,'GAD-7',[1]*7)
    route=f'/api/robot-insights/reports/template/{second}'
    public=a.request('GET',route).json()
    combined=public['combined_score']
    assert combined['answered']==7 and combined['score']==16 and combined['confidence']==43.75
    with SessionLocal() as db:scoped={'combined_score':for_sessions(db,a.uid,[first,second])}
    assert scoped['combined_score']['answered']==16 and scoped['combined_score']['score']==15
    assert scoped['combined_score']['score_kind']=='complete'
    managed=manager.request('GET',f'/api/care-management/template-reports/{second}').json()['report']
    assert managed['combined_score']==combined
    assert b.request('GET',route).status_code==404


def test_different_task_or_recall_window_never_forms_complete_score(actors):
    a,_=actors
    old=setup_controller();old.episode_id=uuid.uuid4().hex;old.window_end=now()[:10]
    first=save(a,old,'PHQ-9',[1]*8+[0])
    newer=setup_controller();newer.episode_id=uuid.uuid4().hex;newer.window_end=old.window_end
    newer.target_scales=['GAD-7']
    second=save(a,newer,'GAD-7',[2]*7)
    def selected():
        with SessionLocal() as db:return for_sessions(db,a.uid,[first,second])
    assert selected()['answered']==7 and selected()['score']==32, (selected(),list(newer.answers),newer.stage)
    values=selected()['instruments']
    assert {v['scale_id'] for v in values}=={'PHQ-9','GAD-7'}
    assert {v['scale_id'] for v in values if v['included_in_combined']}=={'GAD-7'}
    with SessionLocal() as db:
        row=db.get(ScreeningResult,second);row.payload={**row.payload,'episode_id':old.episode_id,'window_end':'2000-01-01'};db.commit()
    assert selected()['answered']==7


def test_correction_and_deletion_remove_stale_answers_and_change_source_hash(actors):
    a,_=actors
    controller=setup_controller();controller.episode_id=uuid.uuid4().hex;controller.window_end=now()[:10]
    sid=save(a,controller,'PHQ-9',[1]*9)
    path=f'/api/robot-insights/reports/template/{sid}'
    before=a.request('GET',path).json()
    rows=a.request('GET',f'/api/robot-records/sessions/{sid}/messages?limit=50').json()['items']
    user=next(row for row in rows if row['role']=='user')
    result=a.request('POST',f'/api/robot-insights/messages/{user["record_id"]}/corrections',json={
        'request_id':'composite-correct','base_revision':0,'content':'虚构更正：这一题我还不能确认。'})
    assert result.status_code==201
    after=a.request('GET',path).json()
    assert after['combined_score']['answered']==8
    assert after['source_snapshot_hash']!=before['source_snapshot_hash']
    a.request('DELETE',f'/api/robot-records/sessions/{sid}')
    assert a.request('GET',path).status_code==410
