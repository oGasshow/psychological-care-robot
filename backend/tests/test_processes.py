from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time

import httpx
import pytest

from robot_client import Outbox, Transport, Worker, OutboxError
from conftest import session_body, message_body

BACKEND=Path(__file__).resolve().parents[1]
NO_WINDOW=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0

class Server:
    def __init__(self,path,trace):
        self.path,self.trace=path,trace
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            self.port=sock.getsockname()[1]
        self.base=f'http://127.0.0.1:{self.port}'
        self.proc=None
        self.log=None

    def start(self):
        env=dict(os.environ,DATABASE_URL='sqlite:///'+self.path.as_posix(),MODELSCOPE_API_KEY='')
        command=[sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(self.port),'--log-level','warning']
        self.log=open(self.path.with_suffix('.server.log'),'ab')
        self.proc=subprocess.Popen(command,cwd=BACKEND,env=env,stdout=self.log,stderr=subprocess.STDOUT,creationflags=NO_WINDOW)
        self.trace.append({'server_start':command,'pid':self.proc.pid})
        for _ in range(160):
            if self.proc.poll() is not None:
                raise AssertionError('Server exited: '+self.path.with_suffix('.server.log').read_text(encoding='utf-8',errors='replace'))
            try:
                if httpx.get(self.base+'/health',timeout=.3,trust_env=False).status_code==200:
                    return
            except httpx.RequestError:
                pass
            time.sleep(.05)
        raise AssertionError('Server startup timed out')

    def stop(self):
        if self.proc and self.proc.poll() is None:
            pid=self.proc.pid
            self.proc.kill()
            self.proc.wait(timeout=10)
            self.trace.append({'server_killed':pid,'exit_code':self.proc.returncode})
        if self.log:
            self.log.close()

@pytest.fixture
def server(tmp_path,trace):
    s=Server(tmp_path/'backend.db',trace)
    s.start()
    try:
        yield s
    finally:
        s.stop()

def login(server):
    with httpx.Client(base_url=server.base,trust_env=False,timeout=5) as client:
        r=client.post('/api/auth/register',json={'username':'virtual_process_user','password':'fictional-only'})
        assert r.status_code==201
        token=client.post('/api/auth/login',json={'username':'virtual_process_user','password':'fictional-only'}).json()['access_token']
        uid=client.get('/api/auth/me',headers={'Authorization':'Bearer '+token}).json()['id']
        return uid,token

def child(server,path,uid,token,mode,trace):
    ready=path.parent/(mode+'.ready.json')
    env=dict(os.environ,ROBOT_BASE_URL=server.base,ROBOT_TOKEN=token,ROBOT_OWNER=str(uid),
             ROBOT_OUTBOX_PATH=str(path),CLIENT_FAULT=mode,CLIENT_READY=str(ready),PYTHONPATH=str(BACKEND))
    command=[sys.executable,str(BACKEND/'tests'/'process_client.py')]
    proc=subprocess.Popen(command,cwd=BACKEND,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=NO_WINDOW)
    for _ in range(180):
        if ready.exists():
            trace.append({'client_mode':mode,'pid':proc.pid,'command':command,'barrier':json.loads(ready.read_text(encoding='utf-8'))})
            return proc
        if proc.poll() is not None:
            _,err=proc.communicate()
            raise AssertionError('Client failed: '+err.decode('utf-8',errors='replace'))
        time.sleep(.05)
    proc.kill()
    proc.wait(timeout=10)
    raise AssertionError('Client barrier timeout')

def kill_child(proc,trace):
    pid=proc.pid
    if proc.poll() is None:
        proc.kill()
    proc.communicate(timeout=10)
    trace.append({'client_killed':pid,'exit_code':proc.returncode})

def drain(worker):
    for _ in range(12):
        if not worker.step():
            return
    raise AssertionError('Outbox not drained')

def test_A12_backend_real_process_restart(server,trace):
    uid,token=login(server)
    transport=Transport(server.base,token)
    try:
        first=transport.request('POST','/api/robot-records/sessions',json=session_body())
        assert first.status_code==201
        sid=first.json()['recording_session_id']
        m1=transport.request('POST',f'/api/robot-records/sessions/{sid}/messages',json=message_body()).json()
        server.stop()
        server.start()
        found=transport.request('GET',f'/api/robot-records/sessions/{sid}/messages').json()['items'][0]
        assert found['record_id']==m1['record_id'] and found['received_at']==m1['received_at']
        dup=transport.request('POST',f'/api/robot-records/sessions/{sid}/messages',json=message_body())
        assert dup.status_code==200 and dup.json()['duplicate'] is True
        assert transport.request('POST','/api/robot-records/sessions',json=session_body()).status_code==200
        trace.append({'before_restart':m1,'after_restart':found,'duplicate_after_restart':dup.json()})
    finally:
        transport.close()

def test_A20_outbox_real_process_restart(server,tmp_path,trace):
    uid,token=login(server)
    path=tmp_path/'outbox.db'
    proc=child(server,path,uid,token,'before_session',trace)
    try:
        with sqlite3.connect(path) as db:
            states=[r[0] for r in db.execute('SELECT state FROM tasks ORDER BY id')]
        assert states==['sending','pending']
        trace.append({'states_before_client_kill':states})
    finally:
        kill_child(proc,trace)
    transport=Transport(server.base,token)
    try:
        box=Outbox(path,server.base,uid)
        drain(Worker(box,transport))
        assert all(s['state']=='acked' for s in box.status())
        mapping=box.status()[0]['server_id']
        with box.db() as db:
            assert db.execute('SELECT count(*) FROM tasks WHERE payload IS NOT NULL').fetchone()[0]==0
        p2=child(server,path,uid,token,'enqueue_second',trace)
        p2.communicate(timeout=10)
        assert p2.returncode==0
        box=Outbox(path,server.base,uid)
        assert box.status()[-1]['sequence']==2 and box.status()[0]['server_id']==mapping
        assert box.close_session('virtual_process','2026-10-28T00:01:00Z')==2
        with pytest.raises(OutboxError,match='session_sealed'):
            box.enqueue('virtual_process',{'external_message_id':'new','role':'user','content':'虚构新增',
                                         'occurred_at':'2026-10-28T00:00:03Z','text_status':'completed','playback_status':'not_applicable'})
        drain(Worker(box,transport))
        detail=transport.request('GET',f'/api/robot-records/sessions/{mapping}').json()
        assert detail['is_complete'] is True and detail['received_record_count']==2
        trace.append({'final_outbox':box.status(),'server_session':detail})
    finally:
        transport.close()

def test_A22_commit_then_client_kill_before_ack(server,tmp_path,trace):
    uid,token=login(server)
    path=tmp_path/'outbox.db'
    for mode in ('after_session','after_message','after_close'):
        proc=child(server,path,uid,token,mode,trace)
        try:
            with sqlite3.connect(path) as db:
                states=[r[0] for r in db.execute('SELECT state FROM tasks ORDER BY id')]
                assert 'sending' in states
                trace.append({'mode':mode,'states_before_kill':states})
        finally:
            kill_child(proc,trace)
    transport=Transport(server.base,token)
    try:
        box=Outbox(path,server.base,uid)
        drain(Worker(box,transport))
        assert all(s['state']=='acked' for s in box.status())
        with sqlite3.connect(server.path) as db:
            counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('robot_record_sessions','robot_record_messages')}
        assert counts=={'robot_record_sessions':1,'robot_record_messages':1}
        trace.append({'after_response_loss_recovery':box.status(),'row_counts':counts})
    finally:
        transport.close()
