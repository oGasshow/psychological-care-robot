"""D02: all content is fictional; false flags exercise metadata, never real data."""
import json
import pytest
from app.care.worker import Worker

P='/api/robot-insights'
SCOPE={'time_from':'2026-10-01T00:00:00Z','time_to':'2026-11-01T00:00:00Z'}

@pytest.fixture(autouse=True)
def care_environment(monkeypatch):
    monkeypatch.setenv('APP_ENV','test')
    monkeypatch.setenv('ROBOT_CARE_ASSESSMENT_PROVIDER','disabled')
    monkeypatch.setenv('ROBOT_CARE_ANALYSIS_ENGINE','rules')

def create(api,flag,index=0):
    sid=api.create(f'nature_{flag}_{index}',is_test=flag).json()['recording_session_id']
    assert api.send(sid,content='虚构边界测试：今天很开心。',occurred_at=f'2026-10-{20+index:02}T00:00:00Z').status_code==201
    return sid

def drain():
    worker=Worker()
    worker.scan()
    while worker.step():pass

def preview(api,scope=None):
    response=api.request('POST',P+'/reports/preview',json={'scope':scope or SCOPE})
    assert response.status_code==200
    return response.json()

def assert_groups_separated(data):
    for group in data['emotion_groups']:
        assert all(point['is_test'] is group['is_test'] for point in group['points'])
        if len(group['points'])<2:
            assert group['status']=='insufficient_records'
    assert all('is_test' in ref for ref in data['source_references'])

@pytest.mark.parametrize('flags,nature',[
    ([], 'empty'),([True],'test_only'),([False],'non_test_only'),
    ([True,True],'test_only'),([False,False],'non_test_only'),([True,False],'mixed')])
def test_D02_report_and_trends_keep_source_nature(actors,flags,nature,trace):
    a,b=actors
    ids=[create(a,flag,i) for i,flag in enumerate(flags)]
    create(b,False,9)  # same date range, different owner never enters source counts
    drain()
    data=preview(a)
    trend=a.request('GET',P+'/trends').json()
    for dto in (data,trend):
        assert dto['data_nature']==nature
        assert dto['is_test'] is (nature=='test_only')
        assert dto['data_nature_summary']==dict(dialogue=dict(test=flags.count(True),non_test=flags.count(False)),assessments=dict(test=0,non_test=0))
        assert dto['emotion_counts']['positive']==len(flags)
        assert dto['emotion_counts_by_nature']['test']['positive']==flags.count(True)
        assert dto['emotion_counts_by_nature']['non_test']['positive']==flags.count(False)
        assert_groups_separated(dto)
    assert data['simulation_notice']==('模拟数据演示' if nature=='test_only' else None)
    assert [m['is_test'] for m in data['messages']]==flags
    if nature=='mixed':
        assert len(data['emotion_groups'])==2
        assert all(g['status']=='insufficient_records' for g in data['emotion_groups'])
        assert '分别统计' in data['data_nature_notice']
        for sid,flag in zip(ids,flags):
            session=preview(a,{'session_ids':[sid]})
            assert session['data_nature']==('test_only' if flag else 'non_test_only')
            assert not session['assessments']
    trace.append({'all_text_fictional':True,'source_flags':flags,'observed_nature':nature,
                  'emotion_counts_by_nature':data['emotion_counts_by_nature']})

def fixture(monkeypatch,tmp_path,owner):
    record=dict(owner_user_id=owner,source_record_id='fixture:nature',is_test=True,scale_name='virtual',display_name='虚构量表',
                scale_version='v1',scoring_version='v1',interpretation_version='demo-v1',completed_at='2026-10-22T00:00:00Z',
                total_score=5,score_min=0,score_max=10)
    path=tmp_path/'nature.json'
    path.write_text(json.dumps(dict(schema_version='1.0',demo_only=True,records=[record])),encoding='utf-8')
    monkeypatch.setenv('ROBOT_CARE_ASSESSMENT_PROVIDER','fixture')
    monkeypatch.setenv('ROBOT_CARE_DEMO_DATABASE','true')
    monkeypatch.setenv('ROBOT_CARE_FIXTURE_FILE',str(path))

def test_D02_non_test_dialogue_with_fixture_and_scope_boundaries(actors,tmp_path,monkeypatch,trace):
    a,_=actors
    sid=create(a,False,0)
    create(a,True,1)
    drain()
    fixture(monkeypatch,tmp_path,a.uid)
    full=preview(a)
    assert full['data_nature']=='mixed' and full['is_test'] is False
    assert full['data_nature_summary']==dict(dialogue=dict(test=1,non_test=1),assessments=dict(test=1,non_test=0))
    assert all(g['is_test'] and all(p['is_test'] for p in g['points']) for g in full['assessment_groups'])
    non_test=preview(a,{'time_from':'2026-10-20T00:00:00Z','time_to':'2026-10-21T00:00:00Z'})
    assert non_test['data_nature']=='non_test_only' and not non_test['assessments']
    mixed_fixture=preview(a,{'time_from':'2026-10-20T00:00:00Z','time_to':'2026-10-23T00:00:00Z'})
    assert mixed_fixture['data_nature']=='mixed'
    only_assessments=preview(a,{'time_from':'2026-10-22T00:00:00Z','time_to':'2026-10-23T00:00:00Z'})
    assert only_assessments['data_nature']=='test_only' and only_assessments['messages']==[]
    assert only_assessments['data_nature_summary']['dialogue']==dict(test=0,non_test=0)
    session=preview(a,{'session_ids':[sid]})
    assert session['data_nature']=='non_test_only' and session['assessment_status']=='unassociated'
    assert session['assessments']==[]
    empty=preview(a,{'time_from':'2026-11-01T00:00:00Z','time_to':'2026-12-01T00:00:00Z'})
    assert empty['data_nature']=='empty' and empty['is_test'] is False
    trace.append({'all_text_fictional':True,'fixture_kept_separate_from_non_test_dialogue':True,
                  'time_and_session_scopes_verified':True})
