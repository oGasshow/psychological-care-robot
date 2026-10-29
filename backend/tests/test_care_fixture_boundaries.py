"""D03: malformed provider documents degrade safely across all consumers."""
import json
from pathlib import Path

import pytest
from app.models import AssessmentRecord
from app.database import SessionLocal

P='/api/robot-insights'
SCOPE={'scope':{'time_from':'2026-10-01T00:00:00Z','time_to':'2026-11-01T00:00:00Z'}}

def configure(monkeypatch,path):
    monkeypatch.setenv('APP_ENV','test')
    monkeypatch.setenv('ROBOT_CARE_ASSESSMENT_PROVIDER','fixture')
    monkeypatch.setenv('ROBOT_CARE_DEMO_DATABASE','true')
    monkeypatch.setenv('ROBOT_CARE_FIXTURE_FILE',str(path))

def assert_failed(a,path,reason):
    with SessionLocal() as db:
        before=db.query(AssessmentRecord).count()
    response=a.request('GET',P+'/assessments')
    assert response.status_code==200
    dto=response.json()
    assert dto['provider']=='fixture' and dto['status']=='query_failed'
    assert dto['reason_code']==reason and dto['items']==[]
    for method,route,body in [('GET','/trends',None),('POST','/reports/preview',SCOPE)]:
        response=a.request(method,P+route,**({'json':body} if body else {}))
        assert response.status_code==200
        data=response.json()
        assert data['assessment_status']=='query_failed' and data['assessment_reason_code']==reason
        assert data['assessments']==[] and data['assessment_groups']==[]
        assert str(path) not in response.text and 'PRIVATE_FIXTURE_SENTINEL' not in response.text
    with SessionLocal() as db:
        assert db.query(AssessmentRecord).count()==before

@pytest.mark.parametrize('document',[
    [],None,'PRIVATE_FIXTURE_SENTINEL',1,1.5,True,False,{},
    {'schema_version':'1.0','demo_only':True},
    {'schema_version':'1.0','records':[]},
    {'demo_only':True,'records':[]},
    {'schema_version':'1.0','demo_only':True,'records':{}},
    {'schema_version':'1.0','demo_only':True,'records':'PRIVATE_FIXTURE_SENTINEL'},
    {'schema_version':'1.0','demo_only':True,'records':[None]},
    {'schema_version':'1.0','demo_only':True,'records':[{}]},
    {'schema_version':'1.0','demo_only':True,'records':[{'owner_user_id':True,'source_record_id':'fixture:x'}]},
])
def test_D03_document_schema_rejected_before_fields(actors,tmp_path,monkeypatch,document):
    a,_=actors
    path=tmp_path/'private_fixture.json'
    path.write_text(json.dumps(document),encoding='utf-8')
    configure(monkeypatch,path)
    assert_failed(a,path,'fixture_schema_invalid')

@pytest.mark.parametrize('kind',['json','missing','unreadable','encoding'])
def test_D03_read_and_decode_errors_are_safe_without_fallback(actors,tmp_path,monkeypatch,kind):
    a,_=actors
    path=tmp_path/'private_fixture.json'
    reason='fixture_read_failed'
    if kind=='json':
        path.write_text('{"PRIVATE_FIXTURE_SENTINEL":',encoding='utf-8')
        reason='fixture_json_invalid'
    elif kind=='unreadable':
        path.write_text('{}',encoding='utf-8')
        original=Path.read_text
        def denied(self,*args,**kwargs):
            if self==path:
                raise PermissionError('PRIVATE_FIXTURE_SENTINEL '+str(path))
            return original(self,*args,**kwargs)
        monkeypatch.setattr(Path,'read_text',denied)
    elif kind=='encoding':
        path.write_bytes(b'\xff\xfePRIVATE_FIXTURE_SENTINEL')
    configure(monkeypatch,path)
    assert_failed(a,path,reason)

def test_D03_identifiable_invalid_or_incomplete_record_is_not_document_failure(actors,tmp_path,monkeypatch):
    a,_=actors
    base=dict(owner_user_id=a.uid,is_test=True,scale_name='virtual',display_name='虚构量表',scale_version='v1',
              scoring_version='v1',interpretation_version='draft-v1')
    items=[dict(base,source_record_id='fixture:incomplete',completed_at=None),
           dict(base,source_record_id='fixture:invalid',completed_at='2026-10-20T00:00:00Z',total_score=99,score_min=0,score_max=10)]
    path=tmp_path/'private_fixture.json'
    path.write_text(json.dumps(dict(schema_version='1.0',demo_only=True,records=items)),encoding='utf-8')
    configure(monkeypatch,path)
    data=a.request('GET',P+'/assessments').json()
    assert data['status']=='available' and [x['verification_status'] for x in data['items']]==['incomplete','invalid']
    assert all(x['total_score'] is None for x in data['items'])

def test_D03_live_query_failure_does_not_fall_back_to_fixture(monkeypatch):
    from app.care import providers
    monkeypatch.setenv('APP_ENV','test')
    monkeypatch.setenv('ROBOT_CARE_ASSESSMENT_PROVIDER','live')
    def forbidden_fixture(owner):
        raise AssertionError('No fixture fallback is authorized')
    monkeypatch.setattr(providers,'fixture',forbidden_fixture)
    class BrokenDatabase:
        def query(self,*args):
            raise RuntimeError('PRIVATE_FIXTURE_SENTINEL /internal/source/path')
    data=providers.assessments(BrokenDatabase(),1)
    assert data['provider']=='live' and data['status']=='query_failed'
    assert data['reason_code']=='assessment_query_failed' and data['items']==[]
    assert 'PRIVATE_FIXTURE_SENTINEL' not in json.dumps(data)
