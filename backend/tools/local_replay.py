"""Reproducible CLI replay in temporary files and a loopback-only server.

Only synthetic data and sanitized results are exported. Runtime DBs/tokens are
destroyed after the demo. This script does not visit any model endpoint.
"""
import argparse
from contextlib import closing
from importlib.metadata import version
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

import httpx

BACKEND=Path(__file__).resolve().parents[1]
NO_WINDOW=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    traces=[]
    with tempfile.TemporaryDirectory(prefix='module24-replay-') as scratch:
        scratch=Path(scratch)
        db=scratch/'backend.db'
        queue=scratch/'outbox.db'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        env=dict(os.environ,PYTHONUTF8='1',DATABASE_URL='sqlite:///'+db.as_posix(),SECRET_KEY=secrets.token_urlsafe(48),
                 MODELSCOPE_API_KEY='',ROBOT_BASE_URL=base,ROBOT_OUTBOX_PATH=str(queue))
        command=[sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port),'--log-level','warning']
        with open(args.output/'local_server.log','w',encoding='utf-8') as log:
            proc=subprocess.Popen(command,cwd=BACKEND,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=NO_WINDOW)
            traces.append({'start_command':command,'pid':proc.pid})
            try:
                with httpx.Client(base_url=base,trust_env=False,timeout=5) as client:
                    for _ in range(160):
                        if proc.poll() is not None:
                            raise RuntimeError('Local server exited')
                        try:
                            if client.get('/health').status_code==200:
                                break
                        except httpx.RequestError:
                            pass
                        time.sleep(.05)
                    else:
                        raise RuntimeError('Local server startup timed out')
                    password=secrets.token_urlsafe(24)
                    register=client.post('/api/auth/register',json={'username':'virtual_replay','password':password})
                    assert register.status_code==201
                    login=client.post('/api/auth/login',json={'username':'virtual_replay','password':password})
                    assert login.status_code==200
                    env['ROBOT_TOKEN']=login.json()['access_token']
                    headers={'Authorization':'Bearer '+env['ROBOT_TOKEN']}
                    owner=client.get('/api/auth/me',headers=headers).json()['id']
                    def cli(*arguments):
                        cmd=[sys.executable,'-m','robot_client',*arguments]
                        result=subprocess.run(cmd,cwd=BACKEND,env=env,capture_output=True,text=True,encoding='utf-8',creationflags=NO_WINDOW,timeout=15)
                        traces.append({'command':cmd,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
                        if result.returncode:
                            raise RuntimeError('Local replay CLI failed')
                        return json.loads(result.stdout)
                    cli('bind')
                    cli('--owner',str(owner),'replay',str(BACKEND/'examples'/'final_events.json'))
                    for _ in range(6):
                        cli('--owner',str(owner),'work','--once')
                    status=cli('--owner',str(owner),'status')
                    assert len(status)==5 and all(s['state']=='acked' for s in status)
                    sessions=client.get('/api/robot-records/sessions',headers=headers).json()
                    sid=sessions['items'][0]['recording_session_id']
                    messages=client.get(f'/api/robot-records/sessions/{sid}/messages',headers=headers).json()
                    assert len(messages['items'])==3 and sessions['items'][0]['is_complete'] is True
                    assert messages['items'][1]['playback_status']=='unknown' and messages['items'][2]['text_status']=='canceled'
                    with closing(sqlite3.connect(db)) as connection:
                        counts={t:connection.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('users','robot_record_sessions','robot_record_messages','messages','diaries','assessment_records')}
                    traces.append({'sessions':sessions,'messages':messages,'row_counts':counts})
                    (args.output/'openapi.json').write_text(json.dumps(client.get('/openapi.json').json(),ensure_ascii=False,indent=2),encoding='utf-8')
            finally:
                proc.terminate()
                proc.wait(timeout=15)
                traces.append({'server_exit_code':proc.returncode})
        (args.output/'replay_trace.json').write_text(json.dumps(traces,ensure_ascii=False,indent=2),encoding='utf-8')
        (args.output/'replay_environment.json').write_text(json.dumps({'python_executable':sys.executable,'python':sys.version,
            'sqlite':sqlite3.sqlite_version,'dependencies':{name:version(name) for name in ('fastapi','sqlalchemy','httpx','pydantic','uvicorn')},
            'model_endpoints_called':0,'synthetic_only':True,'runtime_databases_exported':False},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'replay':'passed','record_count':3,'output':str(args.output)},ensure_ascii=False))

if __name__=='__main__':
    main()
