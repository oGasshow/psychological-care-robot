from contextlib import closing
import json
import os
import sqlite3
import subprocess
import sys
import time

from robot_client import Outbox, Transport
from test_processes import server, login, BACKEND, NO_WINDOW, kill_child

def test_E02_real_process_pause_kill_and_resume(server,tmp_path,trace):
    uid,token=login(server)
    path=tmp_path/'outbox.db'
    ready=tmp_path/'paused.ready.json'
    env=dict(os.environ,ROBOT_BASE_URL=server.base,ROBOT_TOKEN=token,ROBOT_OWNER=str(uid),
             ROBOT_OUTBOX_PATH=str(path),PYTHONPATH=str(BACKEND))
    command=[sys.executable,str(BACKEND/'tests/auth_pause_client.py')]
    proc=subprocess.Popen(command+['pause','--ready',str(ready)],cwd=BACKEND,env=env,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=NO_WINDOW)
    try:
        for _ in range(180):
            if ready.exists():
                break
            if proc.poll() is not None:
                _,stderr=proc.communicate()
                raise AssertionError(stderr.decode('utf-8',errors='replace'))
            time.sleep(.05)
        else:
            raise AssertionError('Auth pause process barrier timed out')
        paused=json.loads(ready.read_text(encoding='utf-8'))
        assert paused['partition']['auth_blocked'] is True
        assert paused['status'][-1]['last_error']=='http_401'
        trace.append({'pause_command':command+['pause','--ready',str(ready)],'pid':proc.pid,'paused':paused})
    finally:
        kill_child(proc,trace)
    box=Outbox(path,server.base,uid)
    assert box.enqueue('pause_session',{'external_message_id':'m2','role':'user','content':'虚构重启新增测试',
                                       'occurred_at':'2026-10-28T00:00:02Z','text_status':'completed','playback_status':'not_applicable'})==2
    assert all(s['state']=='blocked_auth' for s in box.status() if s['kind']=='message')
    for mode in ('check_paused','resume'):
        p=subprocess.run(command+[mode],cwd=BACKEND,env=env,capture_output=True,text=True,encoding='utf-8',
                         creationflags=NO_WINDOW,timeout=15)
        assert p.returncode==0,p.stderr
        data=json.loads(p.stdout)
        trace.append({'command':command+[mode],'exit_code':p.returncode,'observed':data})
        if mode=='check_paused':
            assert data['calls']==[] and data['partition']['auth_blocked'] is True
            read_transport=Transport(server.base,token)
            try:
                sid=box.status()[0]['server_id']
                before=read_transport.request('GET',f'/api/robot-records/sessions/{sid}/messages').json()['items']
                assert before==[]
                trace.append({'server_sequences_before_resume':[]})
            finally:
                read_transport.close()
        else:
            posted=[c['sequence'] for c in data['calls'] if c['method']=='POST']
            assert posted==[1,2]
            assert sum(c['path']=='/api/auth/me' for c in data['calls'])==2
            assert data['partition']['auth_blocked'] is False
    transport=Transport(server.base,token)
    try:
        sid=box.status()[0]['server_id']
        rows=transport.request('GET',f'/api/robot-records/sessions/{sid}/messages').json()['items']
        assert [r['sequence_no'] for r in rows]==[1,2]
        with closing(sqlite3.connect(path)) as db:
            assert db.execute('SELECT count(*) FROM tasks WHERE payload IS NOT NULL').fetchone()[0]==0
        trace.append({'server_sequences_after_resume':[r['sequence_no'] for r in rows],
                      'next_sequence':box.status()[0]['next_sequence'],'mapping':sid})
    finally:
        transport.close()
