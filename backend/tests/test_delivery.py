import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import bcrypt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app import database, robot_records
from app.database import Base
from app.models import User, Conversation, Message, AssessmentTemplate, AssessmentRecord
from conftest import session_body, message_body
from test_processes import BACKEND, NO_WINDOW

def run_manage(args,trace):
    command=[sys.executable,'manage_records.py',*map(str,args)]
    result=subprocess.run(command,cwd=BACKEND,capture_output=True,text=True,encoding='utf-8',creationflags=NO_WINDOW,timeout=20)
    trace.append({'command':command,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
    assert result.returncode==0,result.stderr

def rows(path,tables):
    with sqlite3.connect(path) as db:
        return {table:[list(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY id')] for table in tables}

def test_A27_additive_upgrade_native_regression_and_wal_backup(tmp_path,monkeypatch,trace):
    legacy_path=tmp_path/'legacy.db'
    upgraded_path=tmp_path/'upgraded.db'
    legacy_engine=create_engine('sqlite:///'+legacy_path.as_posix())
    old_tables=[t for name,t in Base.metadata.tables.items() if not name.startswith('robot_record_')]
    Base.metadata.create_all(legacy_engine,tables=old_tables)
    Legacy=sessionmaker(bind=legacy_engine)
    with Legacy() as db:
        user=User(username='virtual_legacy',hashed_password=bcrypt.hashpw(b'fictional-only',bcrypt.gensalt(rounds=4)).decode())
        db.add(user)
        db.flush()
        conv=Conversation(user_id=user.id)
        db.add(conv)
        db.flush()
        db.add(Message(conversation_id=conv.id,role='user',content='虚构旧库消息'))
        template=AssessmentTemplate(scale_name='virtual_scale',display_name='虚构模板',category='test',description='虚构测试',question_count=0,estimated_time=1,questions=[],scoring_rules={},interpretation={})
        db.add(template)
        db.flush()
        db.add(AssessmentRecord(user_id=user.id,template_id=template.id,answers=[],total_score=0,risk_level='test',interpretation='虚构结果'))
        db.commit()
    legacy_engine.dispose()
    table_names=[t.name for t in old_tables]
    before=rows(legacy_path,table_names)
    run_manage(['backup','--db',legacy_path,'--output',upgraded_path],trace)
    for _ in range(2):
        run_manage(['upgrade','--db',upgraded_path],trace)
    assert rows(upgraded_path,table_names)==before
    trace.append({'legacy_data_unchanged_after_two_upgrades':True,'old_table_counts':{k:len(v) for k,v in before.items()}})
    upgraded_engine=create_engine('sqlite:///'+upgraded_path.as_posix(),connect_args={'check_same_thread':False})
    from sqlalchemy import event
    @event.listens_for(upgraded_engine,'connect')
    def foreign_keys(connection,_):
        connection.execute('PRAGMA foreign_keys=ON')
    Upgraded=sessionmaker(bind=upgraded_engine)
    monkeypatch.setattr(database,'SessionLocal',Upgraded)
    monkeypatch.setattr(robot_records,'SessionLocal',Upgraded)
    from app.routers.chat import coordinator
    async def perception(*args,**kwargs):
        return {'is_crisis':False,'is_privacy_issue':False,'is_complex_issue':False}
    async def fake_generate(*args,**kwargs):
        yield '虚构模型替身回复'
    monkeypatch.setattr(coordinator.perception_module,'execute',perception)
    monkeypatch.setattr(coordinator.model_router.local_service,'generate_with_prompt',fake_generate)
    with TestClient(app) as client:
        login=client.post('/api/auth/login',json={'username':'virtual_legacy','password':'fictional-only'})
        assert login.status_code==200
        headers={'Authorization':'Bearer '+login.json()['access_token']}
        sid=client.post('/api/robot-records/sessions',headers=headers,json=session_body()).json()['recording_session_id']
        assert client.post(f'/api/robot-records/sessions/{sid}/messages',headers=headers,json=message_body()).status_code==201
        sse=client.post('/api/chat/send',headers=headers,json={'message':'虚构原生回归'})
        assert sse.status_code==200 and 'text/event-stream' in sse.headers['content-type']
        events=[json.loads(line[6:]) for line in sse.text.splitlines() if line.startswith('data: ')]
        assert [e['type'] for e in events]==['metadata','chunk','end']
        assert events[1]['content']=='虚构模型替身回复'
        with Upgraded() as db:
            assert db.query(Message).count()==3
        assert client.delete('/api/chat/clear',headers=headers).status_code==200
        assert client.get(f'/api/robot-records/sessions/{sid}',headers=headers).json()['received_record_count']==1
        with Upgraded() as db:
            assert db.query(Message).count()==0 and db.query(Conversation).count()==0
        trace.append({'native_sse_events':events,'native_clear_kept_robot_records':True})
        # Keep a connection open in WAL mode with committed content in the WAL.
        with sqlite3.connect(upgraded_path) as live:
            assert live.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal'
            live.execute("INSERT INTO users(username,hashed_password,is_active) VALUES ('virtual_wal_only','fixture-not-a-password',1)")
            live.commit()
            assert Path(str(upgraded_path)+'-wal').exists()
            expected=rows(upgraded_path,table_names+['robot_record_sessions','robot_record_messages'])
            backup_path=tmp_path/'online_backup.db'
            restored_path=tmp_path/'restored.db'
            run_manage(['backup','--db',upgraded_path,'--output',backup_path],trace)
            run_manage(['restore','--source',backup_path,'--db',restored_path],trace)
            run_manage(['check','--db',restored_path],trace)
            assert rows(restored_path,list(expected))==expected
            trace.append({'wal_present_during_backup':True,'restored_all_rows_equal':True})
        assert client.delete(f'/api/robot-records/sessions/{sid}',headers=headers).status_code==204
        assert client.get(f'/api/robot-records/sessions/{sid}',headers=headers).status_code==410
        assert rows(upgraded_path,['assessment_records','assessment_templates']) == {k:before[k] for k in ('assessment_records','assessment_templates')}
    upgraded_engine.dispose()

def test_A28_openapi_configuration_and_delivery_contract(tmp_path,trace):
    schema=app.openapi()
    expected={
        '/api/robot-records/sessions':{'post','get'},
        '/api/robot-records/sessions/{sid}':{'get','delete'},
        '/api/robot-records/sessions/{sid}/messages':{'get','post'},
        '/api/robot-records/sessions/{sid}/close':{'post'},
    }
    for route,methods in expected.items():
        assert set(schema['paths'][route])==methods
        for method in methods:
            assert schema['paths'][route][method]['security']
    for name in ('SessionCreate','MessageCreate','SessionClose'):
        assert schema['components']['schemas'][name]['additionalProperties'] is False
        assert 'user_id' not in schema['components']['schemas'][name]['properties']
    assert schema['components']['schemas']['MessageCreate']['properties']['sequence_no']['type']=='integer'
    path=tmp_path/'openapi.json'
    db=tmp_path/'configuration.db'
    run_manage(['openapi','--db',db,'--output',path],trace)
    assert path.exists() and db.exists()
    command=[sys.executable,'-c','from app.config import SECRET_KEY; from app.database import engine; print(SECRET_KEY == "other-fictional-secret-32-characters"); print(engine.url.database)']
    env=dict(os.environ,SECRET_KEY='other-fictional-secret-32-characters',DATABASE_URL='sqlite:///'+db.as_posix())
    result=subprocess.run(command,cwd=BACKEND,env=env,capture_output=True,text=True,encoding='utf-8',creationflags=NO_WINDOW)
    assert result.returncode==0 and result.stdout.startswith('True') and db.as_posix() in result.stdout.replace('\\','/')
    trace.append({'configuration_read_before_initialization':True,'explicit_database':str(db),'schema_route_count':len(expected)})
