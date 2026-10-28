"""Regression coverage for independently reported E01/E02/E03 defects."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from pydantic import ValidationError
import pytest

from app.main import app
from robot_client import Outbox, OutboxError, Worker
from robot_client.outbox import upgrade_schema
from robot_client.errors import InputValidationError
from robot_client.schemas import MessageCreate
from conftest import session_body, message_body
from test_outbox import LocalTransport, make_box, event, response, drain
from test_processes import BACKEND, NO_WINDOW

ROOT='/api/robot-records/sessions'

def routes(api,sid):
    return [api.request('GET',f'{ROOT}/{sid}'),
            api.request('GET',f'{ROOT}/{sid}/messages'),
            api.request('POST',f'{ROOT}/{sid}/messages',json=message_body()),
            api.request('POST',f'{ROOT}/{sid}/close',json={'ended_at':'2026-10-28T01:00:00Z','last_sequence_no':0}),
            api.request('DELETE',f'{ROOT}/{sid}')]

@pytest.mark.parametrize('sid,status',[
    ('9223372036854775807',404),('9223372036854775808',422),('9'*1000,422),('9'*5000,422),('999999',404),
],ids=['int64_max','int64_overflow','long_digits','python_digit_limit','valid_missing'])
def test_E01_shared_internal_id_bounds(actors,sid,status):
    a,_=actors
    for r in routes(a,sid):
        assert r.status_code==status,r.text
        assert r.json()['error']['code']==('validation_error' if status==422 else 'not_found')
    schema=app.openapi()
    for path,methods in schema['paths'].items():
        if path.startswith(ROOT+'/{sid}'):
            for operation in methods.values():
                parameter=next(p for p in operation['parameters'] if p['name']=='sid')
                assert parameter['schema']['maximum']==9223372036854775807

def test_E01_other_owner_stays_404(actors):
    a,b=actors
    sid=b.create().json()['recording_session_id']
    assert all(r.status_code==404 and r.json()['error']['code']=='not_found' for r in routes(a,sid))

@pytest.mark.parametrize('failure',['post401','post403','me401','me403','owner_mismatch'])
def test_E02_pause_covers_future_tasks_and_partitions(actors,tmp_path,failure,trace):
    a,b=actors
    box,t=make_box(tmp_path,a)
    box.create_session(session_body())
    worker=Worker(box,t)
    assert worker.step()
    sid=box.status()[0]['server_id']
    box.enqueue('virtual_session',event())
    def fault(method,path,kwargs):
        if failure=='owner_mismatch' and path=='/api/auth/me':
            return response(200,{'id':b.uid})
        if failure.startswith('post') and method=='POST':
            return response(int(failure[-3:]))
        if failure.startswith('me') and path=='/api/auth/me':
            return response(int(failure[-3:]))
    t.fault=fault
    assert worker.step()
    assert box.partition_status()['auth_blocked'] is True
    t.fault=None
    box.enqueue('virtual_session',event(2))
    box.create_session(session_body('new_while_paused'))
    box.enqueue('new_while_paused',event())
    box.close_session('new_while_paused','2026-10-28T00:01:00+08:00')
    assert all(s['state']=='blocked_auth' for s in box.status() if s['kind']!='session' or s['external']=='new_while_paused')
    t.calls.clear()
    assert worker.step() is False and t.calls==[]
    box=Outbox(box.path,box.base,box.owner)
    assert Worker(box,t).step() is False and t.calls==[]
    trace.append({'failure':failure,'before_resume':box.status(),'partition':box.partition_status(),'posted_before_resume':0})

    # Another owner can run, then keep its own independent auth pause.
    tb=LocalTransport(b)
    other=Outbox(box.path,tb.base_url,b.uid,transport=tb)
    other.create_session(session_body())
    assert Worker(other,tb).step()
    other.enqueue('virtual_session',event())
    tb.fault=lambda method,path,kwargs: response(401) if method=='POST' else None
    assert Worker(other,tb).step()
    tc=LocalTransport(a,'https://second.test')
    elsewhere=Outbox(box.path,tc.base_url,a.uid,transport=tc)
    elsewhere.create_session(session_body('elsewhere'))
    drain(Worker(elsewhere,tc))
    assert all(s['state']=='acked' for s in elsewhere.status())
    box.resume()
    assert box.partition_status()['auth_blocked'] is False
    assert other.partition_status()['auth_blocked'] is True and Worker(other,tb).step() is False
    drain(Worker(box,t))
    assert all(s['state']=='acked' for s in box.status())
    assert [x['sequence_no'] for x in a.messages(sid).json()['items']]==[1,2]
    trace.append({'after_resume':box.status(),'other_owner_still_paused':other.partition_status(),
                  'other_target_unblocked':elsewhere.partition_status()})

def snapshot_legacy(db):
    return {table:[dict(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY '+('base,owner' if table=='targets' else 'id'))]
            for table in ('targets','sessions','tasks')}

def create_legacy_outbox(path,blocked):
    """Frozen v0 DDL from 58195b8; no reference to the new migration schema."""
    with closing(sqlite3.connect(path)) as db:
        db.executescript((BACKEND/'tests/fixtures/outbox_v0.sql').read_text(encoding='utf-8'))
        db.execute('INSERT INTO targets VALUES (?,?)',('http://local.test',1))
        db.execute('INSERT INTO targets VALUES (?,?)',('http://other.test',1))
        db.execute("""INSERT INTO sessions VALUES (1,'http://local.test',1,'legacy_sealed','doubao_realtime',
          'create_hash',3,41,'sealed',2,'close_hash')""")
        payloads=[None,json.dumps(message_body()),json.dumps(message_body(2)),
                  json.dumps({'ended_at':'2026-10-28T00:01:00Z','last_sequence_no':2})]
        for i,(kind,state,sequence) in enumerate([('session','acked',None),('message','blocked_auth' if blocked else 'pending',1),
                                                ('message','pending',2),('close','pending',None)],1):
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (i,1,kind,f'legacy_{i}',sequence,payloads[i-1],f'digest_{i}',state,3 if i==2 else 0,0,0,
                        'http_401' if i==2 and blocked else None,'{"recording_session_id":41}' if i==1 else None))
        db.commit()

@pytest.mark.parametrize('blocked',[False,True],ids=['pending_only','legacy_blocked_auth'])
def test_E02_legacy_upgrade_idempotent_and_lossless(tmp_path,blocked,trace):
    path=tmp_path/'legacy.db'
    create_legacy_outbox(path,blocked)
    with closing(sqlite3.connect(path)) as db:
        db.row_factory=sqlite3.Row
        before=snapshot_legacy(db)
        assert db.execute('PRAGMA user_version').fetchone()[0]==0
    command=[sys.executable,'-m','robot_client','--outbox',str(path),'upgrade']
    for _ in range(2):
        result=subprocess.run(command,cwd=BACKEND,env=dict(os.environ,PYTHONPATH=str(BACKEND)),capture_output=True,
                              text=True,encoding='utf-8',creationflags=NO_WINDOW,timeout=10)
        assert result.returncode==0,result.stderr
        trace.append({'upgrade_command':command,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
    box=Outbox(path,'http://local.test',1)
    with box.db() as db:
        after=snapshot_legacy(db)
        assert db.execute('PRAGMA user_version').fetchone()[0]==1
    assert before['sessions']==after['sessions'] and before['tasks']==after['tasks']
    assert [{k:r[k] for k in ('base','owner')} for r in after['targets']]==before['targets']
    assert box.partition_status()['auth_blocked'] is blocked
    assert next(r for r in after['targets'] if r['base']=='http://other.test')['auth_blocked']==0
    with pytest.raises(OutboxError,match='session_sealed'):
        box.enqueue('legacy_sealed',event(3))
    trace.append({'before_task_count':len(before['tasks']),'after_task_count':len(after['tasks']),
                  'tasks_and_sessions_byte_values_preserved':True,'mapping':41,'next_sequence':3,'sealed_upper_bound':2,
                  'partition':box.partition_status()})

def test_E02_upgrade_failure_rolls_back(tmp_path,trace):
    path=tmp_path/'legacy.db'
    create_legacy_outbox(path,True)
    with closing(sqlite3.connect(path)) as db:
        db.row_factory=sqlite3.Row
        before=snapshot_legacy(db)
        def deny_version_write(action,arg1,arg2,*_):
            return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_PRAGMA and arg1=='user_version' and arg2 else sqlite3.SQLITE_OK
        db.set_authorizer(deny_version_write)
        with pytest.raises(sqlite3.DatabaseError), db:
            db.execute('BEGIN IMMEDIATE')
            upgrade_schema(db)
        db.set_authorizer(None)
        assert snapshot_legacy(db)==before
        assert db.execute('PRAGMA user_version').fetchone()[0]==0
        assert 'auth_blocked' not in {row[1] for row in db.execute('PRAGMA table_info(targets)')}
    Outbox.upgrade(path)
    trace.append({'injected_migration_failure_rolled_back_columns_and_rows':True,'subsequent_upgrade_passed':True})

INVALIDS=[
    ('short','FAKE7',{'playback_status':'unknown'}),
    ('long_fragment','VIRTUAL_LONG_PREFIX_'+'甲'*200+'VIRTUAL_LONG_SUFFIX',{'playback_status':'unknown'}),
    ('chinese_newline','虚构敏感标记甲\n虚构敏感标记乙',{'playback_status':'unknown'}),
    ('invalid_role','VIRTUAL_BAD_ROLE',{'role':'system'}),
    ('too_long','VIRTUAL_OVERLONG_'+'z'*8000,{}),
    ('extra_key','VIRTUAL_EXTRA_KEY',{'VIRTUAL_EXTRA_KEY':'VIRTUAL_EXTRA_VALUE'}),
]

def assert_redacted(text,content):
    # Check fragments as well as the complete value; repr truncation is insufficient.
    for part in [content,content[:12],content[-12:],*content.splitlines()]:
        if part:
            assert part not in text
    assert 'input_value' not in text and 'input_type' not in text and 'Traceback' not in text

@pytest.mark.parametrize('label,content,change',INVALIDS,ids=[v[0] for v in INVALIDS])
def test_E03_library_and_cli_validation_are_redacted(actors,tmp_path,label,content,change,trace):
    a,_=actors
    box,t=make_box(tmp_path,a)
    box.create_session(session_body())
    bad=event(content=content,**change)
    with pytest.raises(InputValidationError) as caught:
        box.enqueue('virtual_session',bad)
    assert_redacted(str(caught.value),content)
    assert_redacted(repr(caught.value),content)
    assert_redacted(json.dumps(caught.value.details,ensure_ascii=False),content)
    with pytest.raises(ValidationError) as model_error:
        MessageCreate.model_validate(dict(bad,sequence_no=1))
    # Pydantic hides input values. For unknown extra keys use the library's safe wrapper.
    if label!='extra_key':
        assert_redacted(str(model_error.value),content)
    path=tmp_path/'invalid_events.json'
    path.write_text(json.dumps([{'type':'message','external_session_id':'virtual_session','body':bad}],ensure_ascii=False),encoding='utf-8')
    env=dict(os.environ,ROBOT_BASE_URL=box.base,ROBOT_OUTBOX_PATH=str(box.path),PYTHONPATH=str(BACKEND))
    command=[sys.executable,'-m','robot_client','--owner',str(a.uid),'replay',str(path)]
    result=subprocess.run(command,cwd=BACKEND,env=env,capture_output=True,text=True,encoding='utf-8',creationflags=NO_WINDOW,timeout=10)
    assert result.returncode==1 and result.stdout==''
    assert_redacted(result.stderr,content)
    parsed=json.loads(result.stderr)
    assert parsed['error']['code']=='validation_error'
    assert all(set(detail)=={'loc','type'} for detail in parsed['error']['details'])
    with box.db() as db:
        assert db.execute("SELECT count(*) FROM tasks WHERE kind='message'").fetchone()[0]==0
        assert db.execute('SELECT next_sequence FROM sessions').fetchone()[0]==1
    trace.append({'case':label,'command':command,'exit_code':result.returncode,'stderr':parsed,
                  'full_text_and_fragments_absent':True,'library_error':str(caught.value),'invalid_event_not_enqueued':True})
