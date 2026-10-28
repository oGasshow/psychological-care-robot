"""Prepare/start/stop only this isolated virtual demo; no real credentials in output.

Credentials stay in runtime/access.json (gitignored and excluded from delivery).
No reset/drop/delete command is provided. Always choose a new runtime directory.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
import httpx

BACKEND=Path(__file__).resolve().parents[1]
PROJECT=BACKEND.parent
sys.path.insert(0,str(BACKEND))
NO_WINDOW=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0

def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]

def prepare(root):
    root=root.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError('Choose a new empty dedicated demo directory')
    root.mkdir(parents=True,exist_ok=True)
    cfg={'marker':'module236-synthetic-demo-v1','backend_port':port(),'frontend_port':port(),
         'database':str(root/'demo.db'),'fixture':str(root/'assessments.json'),'secret':secrets.token_urlsafe(48),
         'users':[{'username':'virtual_care_a','password':secrets.token_urlsafe(18)},
                  {'username':'virtual_care_b','password':secrets.token_urlsafe(18)}]}
    (root/'access.json').write_text(json.dumps(cfg,indent=2),encoding='utf-8')
    print(json.dumps({'prepared':True,'runtime':str(root),'credentials_file':'access.json (runtime only)'}))

def environment(root,cfg):
    return dict(os.environ,PYTHONUTF8='1',APP_ENV='development',DATABASE_URL='sqlite:///'+Path(cfg['database']).as_posix(),
        SECRET_KEY=cfg['secret'],SQLITE_BUSY_MS='1000',MODELSCOPE_API_KEY='',ROBOT_CARE_ANALYSIS_ENGINE='rules',ROBOT_UPLOAD_POLICY='after_close',
        ROBOT_CARE_ASSESSMENT_PROVIDER='fixture',ROBOT_CARE_DEMO_DATABASE='true',ROBOT_CARE_FIXTURE_FILE=cfg['fixture'],
        ROBOT_CARE_SIMULATOR_ENABLED='true')

def wait_backend(base,proc):
    for _ in range(200):
        if proc.poll() is not None:
            raise RuntimeError('demo_backend_exited')
        try:
            if httpx.get(base+'/health',trust_env=False,timeout=.3).status_code==200:
                return
        except httpx.RequestError:
            pass
        time.sleep(.05)
    raise RuntimeError('demo_backend_start_timeout')

def start(root,cfg,frontend=True):
    if (root/'pids.json').exists():
        raise ValueError('Demo already has process records; stop it first')
    fresh=not Path(cfg['database']).exists()
    fixture={'schema_version':'1.0','demo_only':True,'records':[]}
    if fresh:
        Path(cfg['fixture']).write_text(json.dumps(fixture),encoding='utf-8')
    elif not Path(cfg['fixture']).exists():
        raise RuntimeError('existing_demo_fixture_missing')
    env=environment(root,cfg)
    procs=[]
    def launch(label,cmd,cwd,custom_env=None):
        handle=open(root/(label+'.log'),'ab')
        try:
            proc=subprocess.Popen(cmd,cwd=cwd,env=custom_env or env,stdout=handle,stderr=subprocess.STDOUT,creationflags=NO_WINDOW)
        finally:
            handle.close()
        procs.append({'label':label,'pid':proc.pid,'command':cmd})
        (root/'pids.json').write_text(json.dumps(procs,indent=2),encoding='utf-8')
        return proc
    base=f'http://127.0.0.1:{cfg["backend_port"]}'
    try:
        backend=launch('backend',[sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(cfg['backend_port']),'--log-level','warning'],BACKEND)
        wait_backend(base,backend)
        if fresh:
            seed(base,cfg,fixture)
            Path(cfg['fixture']).write_text(json.dumps(fixture,ensure_ascii=False,indent=2),encoding='utf-8')
        else:
            with httpx.Client(base_url=base,trust_env=False,timeout=5) as client:
                for user in cfg['users']:
                    response=client.post('/api/auth/login',json={k:user[k] for k in ('username','password')})
                    if response.status_code!=200:
                        raise RuntimeError('existing_demo_login_failed')
                    user['token']=response.json()['access_token']
        worker=launch('worker',[sys.executable,'-m','app.care.worker','--instance-id',root.name],BACKEND)
        if frontend:
            node=shutil_which('node')
            frontend_env=dict(env,BACKEND_URL=base,NEXT_TELEMETRY_DISABLED='1')
            manifest=PROJECT/'frontend/.next/routes-manifest.json'
            target=base+'/api/:path*'
            rebuild=True
            if manifest.exists():
                try:
                    routes=json.loads(manifest.read_text(encoding='utf-8')).get('rewrites',{})
                    entries=routes if isinstance(routes,list) else sum(routes.values(),[])
                    rebuild=not any(r.get('destination')==target for r in entries)
                except (ValueError,TypeError):
                    pass
            if rebuild:
                with open(root/'frontend_build.log','ab') as log:
                    completed=subprocess.run([node,str(PROJECT/'frontend/node_modules/next/dist/bin/next'),'build'],cwd=PROJECT/'frontend',env=frontend_env,stdout=log,stderr=subprocess.STDOUT,creationflags=NO_WINDOW)
                if completed.returncode:
                    raise RuntimeError('demo_frontend_build_failed')
            cmd=[node,str(PROJECT/'frontend/node_modules/next/dist/bin/next'),'start','--hostname','127.0.0.1','--port',str(cfg['frontend_port'])]
            launch('frontend',cmd,PROJECT/'frontend',frontend_env)
        # Give the persistent worker a bounded opportunity to finish seed analysis.
        with httpx.Client(base_url=base,trust_env=False,timeout=5) as client:
            h={'Authorization':'Bearer '+cfg['users'][0]['token']}
            for _ in range(200):
                s=client.get(f'/api/robot-insights/sessions/{cfg["session_ids"][0]}/summary',headers=h).json()
                if not any(s['analysis_counts'][k] for k in ('pending','running','retry_wait')):
                    break
                time.sleep(.05)
        (root/'access.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'started':True,'backend':base,'frontend':f'http://127.0.0.1:{cfg["frontend_port"]}/robot-care',
                          'runtime':str(root),'session_ids':cfg['session_ids'],'processes':[{'label':p['label'],'pid':p['pid']} for p in procs]}))
    except BaseException:
        stop(root,cfg)
        raise

def shutil_which(name):
    import shutil
    value=shutil.which(name)
    if not value:
        raise RuntimeError('required_runtime_missing')
    return value

def seed(base,cfg,fixture):
    from robot_client import Outbox,Transport,Worker
    texts=['今天和朋友散步，我很开心。','今天去公园散步。','最近孩子工作很忙，很少有人陪我聊天，感到孤独。',
           '最近总是担心一些事情，心里不踏实。','我不知道该怎么形容。','我很开心但也难过。']
    cfg['session_ids']=[]
    with httpx.Client(base_url=base,trust_env=False,timeout=5) as client:
        for user in cfg['users']:
            response=client.post('/api/auth/register',json={k:user[k] for k in ('username','password')})
            if response.status_code!=201:
                raise RuntimeError('demo_requires_fresh_database')
            user['token']=client.post('/api/auth/login',json={k:user[k] for k in ('username','password')}).json()['access_token']
            uid=client.get('/api/auth/me',headers={'Authorization':'Bearer '+user['token']}).json()['id']
            user['owner_user_id']=uid
            transport=Transport(base,user['token'])
            try:
                box=Outbox(Path(cfg['database']).parent/f'outbox_{uid}.db',base,uid,transport=transport,upload_policy='after_close')
                for day in (21,28):
                    external=f'demo_{uid}_{day}'
                    box.create_session(dict(source='doubao_realtime',device_id='virtual_pi',external_session_id=external,
                        started_at=f'2026-10-{day}T00:00:00+08:00',is_test=True))
                    for i,text in enumerate(texts,1):
                        common=dict(turn_id=f'turn_{i}',occurred_at=f'2026-10-{day}T00:00:{i:02}+08:00',text_status='completed')
                        box.enqueue(external,dict(**common,external_message_id=f'u{i}',role='user',content=text,playback_status='not_applicable'))
                        box.enqueue(external,dict(**common,external_message_id=f'a{i}',role='assistant',content='虚构演示：我在听，您可以慢慢说。',playback_status='unknown' if i%2 else 'interrupted'))
                    box.enqueue(external,dict(external_message_id='canceled',role='assistant',content='',occurred_at=f'2026-10-{day}T00:01:00+08:00',text_status='canceled',playback_status='not_started'))
                    box.close_session(external,f'2026-10-{day}T00:02:00+08:00')
                    worker=Worker(box,transport)
                    for _ in range(40):
                        if not worker.step():
                            break
                    if not all(t['state']=='acked' for t in box.status()):
                        raise RuntimeError('demo_upload_failed')
                    if user==cfg['users'][0]:
                        cfg['session_ids'].append(next(t['server_id'] for t in box.status() if t['external']==external))
                # One closed incomplete session to make missing-record behavior visible.
                headers={'Authorization':'Bearer '+user['token']}
                missing=client.post('/api/robot-records/sessions',headers=headers,json=dict(source='doubao_realtime',device_id='virtual_pi',external_session_id=f'missing_{uid}',started_at='2026-10-28T00:00:00Z',is_test=True)).json()['recording_session_id']
                client.post(f'/api/robot-records/sessions/{missing}/close',headers=headers,json={'ended_at':'2026-10-28T00:01:00Z','last_sequence_no':2})
            finally:
                transport.close()
            for index,(date,score,version) in enumerate([('2026-10-20T10:00:00+08:00',5,'demo-v1'),('2026-10-27T10:00:00+08:00',7,'demo-v1'),('2026-10-28T10:00:00+08:00',4,'demo-v2')],1):
                fixture['records'].append(dict(owner_user_id=uid,source_record_id=f'fixture:user{uid}_{index}',is_test=True,
                    scale_name='demo_wellbeing',display_name='虚构展示量表（非实际评估）',scale_version=version,scoring_version=version,
                    interpretation_version='demo-draft-v1',completed_at=date,total_score=score,score_min=0,score_max=10,
                    reference_interpretation='虚构分数用于演示数值展示，不表示心理状态或疾病。',suggestions='可以选择与信任的人分享日常感受。'))

def stop(root,cfg):
    path=root/'pids.json'
    if not path.exists():
        return
    records=json.loads(path.read_text(encoding='utf-8'))
    for record in reversed(records):
        pid=record['pid']
        if os.name=='nt':
            # Verify recorded process still carries this exact command before stopping.
            escaped=str(pid)
            result=subprocess.run(['powershell','-NoProfile','-Command',f'[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); (Get-CimInstance Win32_Process -Filter "ProcessId={escaped}").CommandLine'],capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=NO_WINDOW)
            actual=result.stdout
            if actual and all(part in actual for part in record['command'][1:]):
                script=f'''$all=Get-CimInstance Win32_Process; $pending=[System.Collections.Generic.List[int]]::new(); $pending.Add({escaped}); for($i=0;$i -lt $pending.Count;$i++){{ foreach($p in $all){{if($p.ParentProcessId -eq $pending[$i]){{$pending.Add([int]$p.ProcessId)}}}}}}; for($i=$pending.Count-1;$i -ge 0;$i--){{Stop-Process -Id $pending[$i] -ErrorAction SilentlyContinue}}'''
                subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True,creationflags=NO_WINDOW)
        else:
            try:
                command=Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode()
                if record['command'][1] in command:
                    os.kill(pid,signal.SIGTERM)
            except (FileNotFoundError,ProcessLookupError):
                pass
    path.rename(root/f'pids_stopped_{int(time.time())}.json')
    print(json.dumps({'stopped_recorded_demo_processes':True}))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','start','stop'])
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--no-frontend',action='store_true')
    args=parser.parse_args()
    root=args.runtime.resolve()
    if args.action=='prepare':
        prepare(root)
        return
    cfg=json.loads((root/'access.json').read_text(encoding='utf-8'))
    if cfg.get('marker')!='module236-synthetic-demo-v1' or Path(cfg['database']).parent!=root:
        raise ValueError('invalid_demo_directory')
    start(root,cfg,not args.no_frontend) if args.action=='start' else stop(root,cfg)

if __name__=='__main__':
    main()
