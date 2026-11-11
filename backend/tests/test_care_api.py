from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker
from app import database,robot_records as rr
from app.main import app
from app.models import User,AssessmentTemplate,AssessmentRecord
from app.database import Base,SessionLocal
from app.care.models import AnalysisJob,AnalysisResult,SupportPolicy
from app.care.worker import Worker
from conftest import message_body,session_body
from test_processes import BACKEND,NO_WINDOW

P='/api/robot-insights'

@pytest.fixture(autouse=True)
def care_environment(monkeypatch):
    monkeypatch.setenv('APP_ENV','test')
    monkeypatch.setenv('ROBOT_CARE_ANALYSIS_ENGINE','rules')
    monkeypatch.setenv('ROBOT_CARE_ASSESSMENT_PROVIDER','disabled')
    monkeypatch.setenv('ROBOT_CARE_SIMULATOR_ENABLED','true')

def sample(api,external='care_sample',texts=None):
    sid=api.create(external).json()['recording_session_id']
    for i,text in enumerate(texts or ['今天很开心。','今天去公园散步。','我觉得孤独。','我说不清。'],1):
        assert api.send(sid,i,content=text,occurred_at=f'2026-10-{i+20:02}T00:00:01+08:00').status_code==201
    return sid

def drain():
    worker=Worker()
    worker.scan()
    while worker.step():
        pass

def fixture_file(tmp_path,uid,records):
    path=tmp_path/'virtual_assessments.json'
    items=[]
    for i,changes in enumerate(records):
        item=dict(owner_user_id=uid,source_record_id=f'fixture:{i}',is_test=True,scale_name='demo_scale',display_name='虚构展示量表',
            scale_version='v1',scoring_version='s1',interpretation_version='i1',completed_at=f'2026-10-{i+20:02}T10:00:00+08:00',
            total_score=i+2,score_min=0,score_max=10,reference_interpretation='虚构参考，不表示心理疾病。')
        item.update(changes)
        items.append(item)
    path.write_text(json.dumps({'schema_version':'1.0','demo_only':True,'records':items},ensure_ascii=False),encoding='utf-8')
    return path

def use_fixture(monkeypatch,path):
    monkeypatch.setenv('ROBOT_CARE_ASSESSMENT_PROVIDER','fixture')
    monkeypatch.setenv('ROBOT_CARE_DEMO_DATABASE','true')
    monkeypatch.setenv('ROBOT_CARE_FIXTURE_FILE',str(path))

def test_care_N04_N05_profile_auth_and_cross_user(actors):
    a,b=actors
    one=a.request('GET',P+'/profile').json()['anonymous_id']
    assert one==a.request('GET',P+'/profile').json()['anonymous_id']
    assert one!=b.request('GET',P+'/profile').json()['anonymous_id']
    assert a.token not in json.dumps(a.request('GET',P+'/profile').json())
    assert a.client.get(P+'/profile').status_code==401
    sid=sample(a)
    drain()
    rid=a.messages(sid).json()['items'][0]['record_id']
    task=a.request('POST',P+'/analysis-jobs',json={'record_id':rid}).json()
    for path in [f'/messages/{rid}/effective',f'/sessions/{sid}/analyses',f'/sessions/{sid}/summary',
                 f'/analysis-jobs/{task["task_id"]}',f'/policies/{task["support_policy_id"]}']:
        assert b.request('GET',P+path).status_code==404
    assert b.request('POST',P+'/reports/preview',json={'scope':{'session_ids':[sid]}}).status_code==404
    assert b.request('POST',f'{P}/messages/{rid}/corrections',json={'request_id':'wrong','base_revision':0,'content':'虚构'}).status_code==404
    assert b.request('POST',P+'/strategy-deliveries/simulate',json={'request_id':'wrong','policy_id':task['support_policy_id']}).status_code==404
    assert b.request('GET',P+'/assessments').json()['items']==[]

def test_care_N06_N43_strict_boundaries_and_safe_errors(actors):
    a,_=actors
    secret='FAKE_BODY_SHORT_MARKER'
    for value in [True,1.0,0,9223372036854775808,'1']:
        result=a.request('POST',P+'/analysis-jobs',json={'record_id':value,'content':secret})
        assert result.status_code==422 and secret not in result.text
    for route in ['/profile?user_id=2','/assessments?provider=fixture','/trends?user_id=2']:
        assert a.request('GET',P+route).status_code==422
    for resource in ['9223372036854775808','9'*5000]:
        assert a.request('GET',P+'/analysis-jobs/'+resource).status_code==422
    for scope in [{'session_ids':[True]},{'session_ids':[1.0]},{'session_ids':[1],'time_from':'2026-10-01T00:00:00Z'},
                  {'time_from':'2026-10-01T00:00:00'},{'time_from':'2026-11-01T00:00:00Z','time_to':'2026-10-01T00:00:00Z'}]:
        assert a.request('POST',P+'/reports/preview',json={'scope':scope}).status_code==422
    for route in ['/profile','/assessments','/trends']:
        assert a.request('GET',P+route).headers['cache-control']=='no-store'

def test_care_N30_N31_N35_N36_summary_and_emotion_trend(actors):
    a,_=actors
    assert a.request('GET',P+'/trends').json()['emotion_groups']==[]
    sid=sample(a,texts=['今天很开心。'])
    assert a.request('GET',f'{P}/sessions/{sid}/summary').json()['analysis_counts']['pending']==1
    drain()
    groups=a.request('GET',P+'/trends').json()['emotion_groups']
    assert groups[0]['status']=='insufficient_records' and len(groups[0]['points'])==1
    a.send(sid,2,content='我觉得孤独。',occurred_at='2026-10-22T00:00:00+08:00')
    a.send(sid,3,content='我说不清。')
    a.send(sid,4,role='assistant',playback_status='unknown')
    a.send(sid,5,text_status='canceled',content='')
    drain()
    value=a.request('GET',P+'/trends').json()
    assert value['emotion_groups'][0]['status']=='available' and len(value['emotion_groups'][0]['points'])==2
    assert set(value['emotion_counts'])=={'positive','neutral','negative'}
    summary=a.request('GET',f'{P}/sessions/{sid}/summary').json()
    assert summary['analysis_counts']['unable_to_determine']==1 and summary['analysis_counts']['excluded']==2
    assert summary['source_references'][0]['input_revision']==0
    assert value['emotion_groups'][0]['points'][0]['occurred_at']=='2026-10-20T16:00:01.000000Z'

def test_care_N32_N34_N35_N37_fixture_missing_versions_duplicates(actors,tmp_path,monkeypatch):
    a,b=actors
    path=fixture_file(tmp_path,a.uid,[])
    use_fixture(monkeypatch,path)
    assert a.request('GET',P+'/assessments').json()['status']=='no_records'
    path=fixture_file(tmp_path,a.uid,[{}])
    use_fixture(monkeypatch,path)
    assert a.request('GET',P+'/trends').json()['assessment_groups'][0]['status']=='insufficient_records'
    path=fixture_file(tmp_path,a.uid,[{}, {}, {'scale_version':'v2'}, {'source_record_id':'fixture:duplicate'},
        {'source_record_id':'fixture:duplicate'},{'completed_at':None},{'total_score':99}])
    use_fixture(monkeypatch,path)
    before=SessionLocal().query(AssessmentRecord).count()
    items=a.request('GET',P+'/assessments').json()['items']
    assert all(item['is_test'] and item['applicability_status']=='demo_only' for item in items)
    assert {i['verification_status'] for i in items}>={'verified_fixture','invalid','incomplete'}
    groups=a.request('GET',P+'/trends').json()['assessment_groups']
    v1=next(g for g in groups if g['scale_version']=='v1')
    assert len(v1['points'])==2 and v1['status']=='available'
    assert next(g for g in groups if g['scale_version']=='v2')['status']=='insufficient_records'
    assert b.request('GET',P+'/assessments').json()['items']==[]
    with SessionLocal() as db:
        assert db.query(AssessmentRecord).count()==before
    path.write_text('not json',encoding='utf-8')
    assert a.request('GET',P+'/assessments').json()['status']=='query_failed'

def test_care_N33_live_adapter_never_manufactures_verification(actors,monkeypatch):
    a,_=actors
    with SessionLocal() as db:
        template=AssessmentTemplate(scale_name='virtual_old',display_name='虚构旧量表',category='test',description='test',question_count=1,estimated_time=1,
                                    version='CURRENT_TEMPLATE_NOT_RECORD_VERSION',questions=[],scoring_rules={},interpretation={})
        db.add(template); db.flush()
        db.add(AssessmentRecord(user_id=a.uid,template_id=template.id,answers=[1],total_score=8,risk_level='unknown',interpretation='PRIVATE_OLD_DIAGNOSTIC_TEXT'))
        db.commit()
    monkeypatch.setenv('ROBOT_CARE_ASSESSMENT_PROVIDER','live')
    response=a.request('GET',P+'/assessments')
    data=response.json()
    assert data['items'][0]['verification_status']=='incomplete'
    assert data['items'][0]['total_score']==8 and data['items'][0]['scale_version'] is None
    assert data['items'][0]['completed_at'] is None and data['items'][0]['reference_interpretation'] is None
    assert 'PRIVATE_OLD' not in response.text and 'CURRENT_TEMPLATE' not in response.text and 'answers' not in response.text
    assert a.request('GET',P+'/trends').json()['assessment_groups']==[]

def test_care_N38_N39_report_scope_and_no_fake_assessment_links(actors,tmp_path,monkeypatch,trace):
    a,b=actors
    sid=sample(a)
    drain()
    path=fixture_file(tmp_path,a.uid,[{},{}])
    use_fixture(monkeypatch,path)
    full=a.request('POST',P+'/reports/preview',json={'scope':{'time_from':'2026-10-01T00:00:00Z','time_to':'2026-11-01T00:00:00Z'}})
    assert full.status_code==200
    dto=full.json()
    assert dto['anonymous_id'].startswith('KY-') and dto['is_test'] is True and dto['simulation_notice']=='模拟数据演示'
    assert len(dto['assessments'])==2 and '非专业心理咨询师' in dto['nature_notice']
    assert dto['generated_at'].endswith('Z') and dto['data_as_of'].endswith('Z') and dto['suggestions']
    session=a.request('POST',P+'/reports/preview',json={'scope':{'session_ids':[sid]}}).json()
    assert session['assessments']==[] and session['assessment_status']=='unassociated'
    assert '未关联量表' in ''.join(session['warnings'])
    # Left-closed/right-open source occurred_at selection, not analysis time.
    narrow=a.request('POST',P+'/reports/preview',json={'scope':{'time_from':'2026-10-20T16:00:01Z','time_to':'2026-10-20T16:00:02Z'}}).json()
    assert len(narrow['messages'])==1 and narrow['messages'][0]['sequence_no']==1 and narrow['assessments']==[]
    empty=a.request('POST',P+'/reports/preview',json={'scope':{'time_from':'2026-01-01T00:00:00Z','time_to':'2026-02-01T00:00:00Z'}}).json()
    assert empty['messages']==[] and empty['assessments']==[] and empty['emotion_counts']=={'positive':0,'neutral':0,'negative':0}
    assert a.request('DELETE',f'/api/robot-records/sessions/{sid}').status_code==204
    assert a.request('POST',P+'/reports/preview',json={'scope':{'session_ids':[sid]}}).status_code==410
    assert b.request('POST',P+'/reports/preview',json={'scope':{'session_ids':[sid]}}).status_code==404
    trace.append({'report_never_persisted':True,'time_report_has_confirmed_fixture':True,'session_report_does_not_guess_links':True})

def test_care_N02_N03_legacy_upgrade_and_wal_recovery(actors,tmp_path,monkeypatch,trace):
    a,_=actors
    sid=sample(a,texts=['今天很开心。'])
    source=tmp_path/'old24.db'
    # Build the historical old24 schema, excluding later care AND voice tables.
    target_engine=create_engine('sqlite:///'+source.as_posix())
    old_tables=[t for n,t in Base.metadata.tables.items() if not n.startswith(('robot_record_care_','robot_voice_'))]
    Base.metadata.create_all(target_engine,tables=old_tables)
    with database.engine.connect() as original, target_engine.begin() as target:
        for table in old_tables:
            rows=[dict(r) for r in original.execute(table.select()).mappings()]
            if rows: target.execute(table.insert(),rows)
    target_engine.dispose()
    def old_rows(path):
        with closing(sqlite3.connect(path)) as db:
            return {t.name:db.execute('SELECT * FROM '+t.name+' ORDER BY id').fetchall() for t in old_tables}
    before=old_rows(source)
    def run(*args):
        command=[sys.executable,'manage_records.py',*map(str,args)]
        p=subprocess.run(command,cwd=BACKEND,capture_output=True,text=True,encoding='utf-8',creationflags=NO_WINDOW,timeout=15)
        trace.append({'command':command,'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
        assert p.returncode==0,p.stderr
    run('upgrade','--db',source); run('upgrade','--db',source)
    with closing(sqlite3.connect(source)) as upgraded_db:
        assert upgraded_db.execute('SELECT count(*) FROM robot_voice_screening_results').fetchone()[0]==0
    assert old_rows(source)==before
    upgraded=create_engine('sqlite:///'+source.as_posix(),connect_args={'check_same_thread':False})
    @event.listens_for(upgraded,'connect')
    def fk(conn,_): conn.execute('PRAGMA foreign_keys=ON')
    factory=sessionmaker(bind=upgraded,autoflush=False)
    monkeypatch.setattr(rr,'SessionLocal',factory)
    Worker().scan(); assert Worker().step()
    with factory() as db:
        assert db.query(AnalysisJob).count()==db.query(AnalysisResult).count()==db.query(SupportPolicy).count()==1
    with closing(sqlite3.connect(source)) as wal:
        wal.execute('PRAGMA journal_mode=WAL')
        wal.execute("UPDATE robot_record_care_analysis_jobs SET error_code='wal_test_marker' WHERE id=1")
        wal.commit()
        assert Path(str(source)+'-wal').exists()
        backup=tmp_path/'backup.db'; restored=tmp_path/'restored.db'
        run('backup','--db',source,'--output',backup); run('restore','--source',backup,'--db',restored); run('check','--db',restored)
        assert old_rows(restored)==before
        with closing(sqlite3.connect(restored)) as db:
            assert db.execute('SELECT error_code FROM robot_record_care_analysis_jobs').fetchone()[0]=='wal_test_marker'
            assert db.execute('SELECT count(*) FROM robot_record_care_analysis_results').fetchone()[0]==1
    upgraded.dispose()
    trace.append({'old24_rows_unchanged':True,'upgrade_twice':True,'restored_care_job_result_policy_counts':[1,1,1],'wal_marker_restored':True})
