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
from datetime import datetime,timezone

BACKEND=Path(__file__).resolve().parents[1]
PROJECT=BACKEND.parent
sys.path.insert(0,str(BACKEND))
NO_WINDOW=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0

class ProcessIdentityError(Exception):
    """Identity could not be proved; never use this as permission to signal."""

def write_json(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)

def windows_argv(command_line):
    import ctypes
    from ctypes import wintypes
    function=ctypes.windll.shell32.CommandLineToArgvW
    function.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_int)]
    function.restype=ctypes.POINTER(wintypes.LPWSTR)
    count=ctypes.c_int()
    pointer=function(command_line,ctypes.byref(count))
    if not pointer:
        raise ProcessIdentityError('argv_unreadable')
    try:
        return [pointer[index] for index in range(count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes=[ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(pointer)

def windows_console_host(argv):
    import ctypes
    import ntpath
    buffer=ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetSystemDirectoryW(buffer,len(buffer)):
        return False
    executable=argv[0].removeprefix('\\??\\')
    expected=ntpath.join(buffer.value,'conhost.exe')
    return (ntpath.normcase(executable)==ntpath.normcase(expected) and len(argv)==2 and
            argv[1].startswith('0x') and all(value in '0123456789abcdefABCDEF' for value in argv[1][2:]))

def windows_handle(pid,access):
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
    kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    handle=kernel.OpenProcess(access,False,pid)
    if not handle:
        if ctypes.get_last_error()==87:
            return None,None,None
        raise ProcessIdentityError('process_handle_unreadable')
    creation,exit_time,kernel_time,user_time=(wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(handle,ctypes.byref(creation),ctypes.byref(exit_time),
                                  ctypes.byref(kernel_time),ctypes.byref(user_time)):
        kernel.CloseHandle(handle)
        raise ProcessIdentityError('creation_identity_unreadable')
    return kernel,handle,(creation.dwHighDateTime<<32)|creation.dwLowDateTime

def windows_query(pid):
    script=f'''$p=Get-CimInstance Win32_Process -Filter "ProcessId={pid}" -ErrorAction Stop; if($p){{[ordered]@{{pid=[int]$p.ProcessId; parent_pid=[int]$p.ParentProcessId; command_line=$p.CommandLine; creation_ticks=[string]$p.CreationDate.ToUniversalTime().ToFileTimeUtc()}}|ConvertTo-Json -Compress}}'''
    result=subprocess.run(['powershell','-NoProfile','-Command',
        '[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); '+script],
        capture_output=True,text=True,encoding='utf-8',errors='strict',creationflags=NO_WINDOW,timeout=10)
    if result.returncode:
        raise ProcessIdentityError('process_query_failed')
    if not result.stdout.strip():
        return None
    try:
        value=json.loads(result.stdout)
        if value['pid']!=pid or not value['command_line']:
            raise ValueError()
        return value
    except (ValueError,KeyError,TypeError):
        raise ProcessIdentityError('process_query_invalid') from None

def process_identity(pid):
    """Read a complete identity, or fail closed. No source text or secrets escape."""
    if type(pid) is not int or pid<1:
        raise ProcessIdentityError('invalid_process_id')
    try:
        if os.name=='nt':
            kernel,handle,created=windows_handle(pid,0x1000)
            if handle is None:
                return None
            try:
                data=windows_query(pid)
                if data is None:
                    return None
                # CIM has microsecond precision; the handle retains exact 100ns ticks.
                if int(data['creation_ticks'])//10!=created//10:
                    raise ProcessIdentityError('creation_identity_changed')
                return {'platform':'windows','pid':pid,'parent_pid':data['parent_pid'],
                        'argv':windows_argv(data['command_line']),'creation_ticks':str(created)}
            finally:
                kernel.CloseHandle(handle)
        proc=Path(f'/proc/{pid}')
        raw=(proc/'cmdline').read_bytes()
        argv=[part.decode('utf-8') for part in raw.rstrip(b'\0').split(b'\0')]
        stat=(proc/'stat').read_text(encoding='utf-8').rsplit(')',1)[1].split()
        environment={}
        for entry in (proc/'environ').read_bytes().split(b'\0'):
            key,separator,value=entry.partition(b'=')
            if separator and key in (b'ROBOT_CARE_RUNTIME_ID',b'ROBOT_CARE_RUNTIME_ROOT',b'ROBOT_CARE_PROCESS_ID'):
                environment[key.decode()]=value.decode('utf-8')
        if not argv or not argv[0] or len(stat)<20:
            raise ProcessIdentityError('process_identity_invalid')
        return {'platform':'linux','pid':pid,'parent_pid':int(stat[1]),'argv':argv,
                'start_ticks':stat[19],'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'uid':proc.stat().st_uid,'cwd':str((proc/'cwd').resolve(strict=True)),
                'runtime_id':environment.get('ROBOT_CARE_RUNTIME_ID'),
                'runtime_root':environment.get('ROBOT_CARE_RUNTIME_ROOT'),
                'process_id':environment.get('ROBOT_CARE_PROCESS_ID'),'state':stat[0]}
    except (FileNotFoundError,ProcessLookupError):
        return None
    except ProcessIdentityError:
        raise
    except (OSError,UnicodeError,ValueError,KeyError,IndexError,subprocess.SubprocessError):
        raise ProcessIdentityError('process_identity_unreadable') from None

def identity_key(value):
    keys=('platform','pid','argv','creation_ticks') if value.get('platform')=='windows' else (
        'platform','pid','argv','start_ticks','boot_id','uid','cwd','runtime_id','runtime_root','process_id')
    return {key:value.get(key) for key in keys}

def child_pids(pid):
    try:
        if os.name=='nt':
            script=f'@(Get-CimInstance Win32_Process -Filter "ParentProcessId={pid}" -ErrorAction Stop | ForEach-Object {{[int]$_.ProcessId}})|ConvertTo-Json -Compress'
            result=subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True,
                text=True,encoding='utf-8',errors='strict',creationflags=NO_WINDOW,timeout=10)
            if result.returncode:
                raise ProcessIdentityError('children_unreadable')
            value=json.loads(result.stdout) if result.stdout.strip() else []
            return value if isinstance(value,list) else [value]
        return [int(value) for value in Path(f'/proc/{pid}/task/{pid}/children').read_text().split()]
    except FileNotFoundError:
        return []
    except (OSError,ValueError,subprocess.SubprocessError):
        raise ProcessIdentityError('children_unreadable') from None

def capture_process(record,root,cfg):
    identity=process_identity(record['pid'])
    if identity is None or identity['argv']!=record['command']:
        raise ProcessIdentityError('launch_identity_not_verified')
    if identity['platform']=='linux' and (identity['runtime_id']!=cfg['runtime_id'] or
            identity['runtime_root']!=str(root) or identity['process_id']!=record['process_id'] or
            identity['cwd']!=record['cwd']):
        raise ProcessIdentityError('launch_runtime_not_verified')
    record['identity']=identity
    record['identity_schema']=1

def capture_children(record,root,cfg):
    """Persist only individually verified descendants; never save a blind tree."""
    if identity_key(process_identity(record['pid']) or {})!=identity_key(record['identity']):
        raise ProcessIdentityError('launch_identity_changed')
    children=[]
    pending=[record['identity']]
    seen={record['pid']}
    while pending:
        parent=pending.pop()
        for pid in child_pids(parent['pid']):
            if pid in seen or len(seen)>=64:
                raise ProcessIdentityError('child_identity_invalid')
            seen.add(pid)
            child=process_identity(pid)
            if child is None:
                continue
            valid=child['parent_pid']==parent['pid']
            if child['platform']=='linux':
                valid=valid and int(child['start_ticks'])>=int(parent['start_ticks']) and (
                    child['runtime_id']==cfg['runtime_id'] and child['runtime_root']==str(root) and
                    child['process_id']==record['process_id'])
            else:
                # Windows venv redirectors create a real interpreter with the same args.
                allowed={str(Path(value).resolve()).lower() for value in (
                    record['command'][0],sys.executable,getattr(sys,'_base_executable',sys.executable))}
                interpreter=(str(Path(child['argv'][0]).resolve()).lower() in allowed and
                             child['argv'][1:]==record['command'][1:])
                valid=valid and int(child['creation_ticks'])>=int(parent['creation_ticks']) and (
                    interpreter or windows_console_host(child['argv']))
            if not valid:
                raise ProcessIdentityError('child_ownership_unverified')
            children.append(child)
            pending.append(child)
    record['children']=children

def signal_verified(expected):
    """Bind the exact process instance before the final check and the signal."""
    pid=expected['pid']
    if os.name=='nt':
        kernel,handle,created=windows_handle(pid,0x1000|0x00100000|0x0001)
        if handle is None:
            return 'already_gone'
        try:
            current=process_identity(pid)
            if str(created)!=expected['creation_ticks'] or current is None or identity_key(current)!=identity_key(expected):
                return 'identity_changed'
            if not kernel.TerminateProcess(handle,0):
                raise ProcessIdentityError('termination_failed')
            return 'stopped' if kernel.WaitForSingleObject(handle,5000)==0 else 'stop_not_confirmed'
        finally:
            kernel.CloseHandle(handle)
    if not hasattr(os,'pidfd_open') or not hasattr(signal,'pidfd_send_signal'):
        raise ProcessIdentityError('instance_bound_signal_unavailable')
    try:
        descriptor=os.pidfd_open(pid,0)
    except ProcessLookupError:
        return 'already_gone'
    except OSError:
        raise ProcessIdentityError('instance_bound_signal_unavailable') from None
    try:
        current=process_identity(pid)
        if current is None or identity_key(current)!=identity_key(expected):
            return 'identity_changed'
        signal.pidfd_send_signal(descriptor,signal.SIGTERM,None,0)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            current=process_identity(pid)
            if current is None or current.get('state')=='Z' or identity_key(current)!=identity_key(expected):
                return 'stopped'
            time.sleep(.05)
        return 'stop_not_confirmed'
    finally:
        os.close(descriptor)

def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]

def prepare(root,empty=False,presentation=False):
    root=root.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError('Choose a new empty dedicated demo directory')
    root.mkdir(parents=True,exist_ok=True)
    cfg={'marker':'module236-synthetic-demo-v1','seed_sample_data':not empty,'sample_profile':'presentation' if presentation else 'legacy','runtime_id':secrets.token_hex(24),'backend_port':port(),'frontend_port':port(),
         'database':str(root/'demo.db'),'fixture':str(root/'assessments.json'),'secret':secrets.token_urlsafe(48),
         'users':[{'username':'virtual_care_a','password':secrets.token_urlsafe(18)},
                  {'username':'virtual_care_b','password':secrets.token_urlsafe(18)}]}
    (root/'access.json').write_text(json.dumps(cfg,indent=2),encoding='utf-8')
    print(json.dumps({'prepared':True,'runtime':str(root),'credentials_file':'access.json (runtime only)'}))

def environment(root,cfg):
    return dict(os.environ,PYTHONUTF8='1',APP_ENV='development',DATABASE_URL='sqlite:///'+Path(cfg['database']).as_posix(),
        SECRET_KEY=cfg['secret'],SQLITE_BUSY_MS='1000',MODELSCOPE_API_KEY='',ROBOT_CARE_ANALYSIS_ENGINE='rules',ROBOT_UPLOAD_POLICY='after_close',
        ROBOT_CARE_ASSESSMENT_PROVIDER='fixture' if cfg.get('seed_sample_data',True) else 'disabled',ROBOT_CARE_DEMO_DATABASE='true',ROBOT_CARE_FIXTURE_FILE=cfg['fixture'],
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
    root=root.resolve()
    if not cfg.get('runtime_id'):
        cfg['runtime_id']=secrets.token_hex(24)
        write_json(root/'access.json',cfg)
    fresh=not Path(cfg['database']).exists()
    fixture={'schema_version':'1.0','demo_only':True,'records':[]}
    if fresh:
        Path(cfg['fixture']).write_text(json.dumps(fixture),encoding='utf-8')
    elif not Path(cfg['fixture']).exists():
        raise RuntimeError('existing_demo_fixture_missing')
    env=environment(root,cfg)
    procs=[]
    def launch(label,cmd,cwd,custom_env=None):
        process_id=secrets.token_hex(24)
        process_env=dict(custom_env or env,ROBOT_CARE_RUNTIME_ID=cfg['runtime_id'],
                         ROBOT_CARE_RUNTIME_ROOT=str(root),ROBOT_CARE_PROCESS_ID=process_id)
        handle=open(root/(label+'.log'),'ab')
        try:
            proc=subprocess.Popen(cmd,cwd=cwd,env=process_env,stdout=handle,stderr=subprocess.STDOUT,creationflags=NO_WINDOW)
        finally:
            handle.close()
        record={'label':label,'pid':proc.pid,'command':cmd,'cwd':str(cwd.resolve()),
                'runtime_root':str(root),'runtime_id':cfg['runtime_id'],'process_id':process_id,'children':[]}
        procs.append(record)
        write_json(root/'pids.json',procs)
        capture_process(record,root,cfg)
        write_json(root/'pids.json',procs)
        return proc
    base=f'http://127.0.0.1:{cfg["backend_port"]}'
    try:
        backend=launch('backend',[sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(cfg['backend_port']),'--log-level','warning'],BACKEND)
        wait_backend(base,backend)
        capture_children(procs[0],root,cfg)
        write_json(root/'pids.json',procs)
        if fresh:
            if cfg.get('sample_profile')=='presentation':
                seed_presentation(base,cfg,fixture)
            elif cfg.get('seed_sample_data',True):
                seed(base,cfg,fixture)
            else:
                cfg['session_ids']=[]
                with httpx.Client(base_url=base,trust_env=False,timeout=5) as client:
                    for user in cfg['users']:
                        response=client.post('/api/auth/register',json={k:user[k] for k in ('username','password')})
                        response.raise_for_status()
                        response=client.post('/api/auth/login',json={k:user[k] for k in ('username','password')})
                        response.raise_for_status()
                        user['token']=response.json()['access_token']
            Path(cfg['fixture']).write_text(json.dumps(fixture,ensure_ascii=False,indent=2),encoding='utf-8')
        else:
            with httpx.Client(base_url=base,trust_env=False,timeout=5) as client:
                for user in cfg['users']:
                    response=client.post('/api/auth/login',json={k:user[k] for k in ('username','password')})
                    if response.status_code!=200:
                        raise RuntimeError('existing_demo_login_failed')
                    user['token']=response.json()['access_token']
        # Preserve completed preparation even if a later frontend build fails.
        (root/'access.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
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
            for _ in range(200 if cfg.get('session_ids') else 0):
                s=client.get(f'/api/robot-insights/sessions/{cfg["session_ids"][0]}/summary',headers=h).json()
                if not any(s['analysis_counts'][k] for k in ('pending','running','retry_wait')):
                    break
                time.sleep(.05)
        (root/'access.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
        for record in procs:
            capture_children(record,root,cfg)
        write_json(root/'pids.json',procs)
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

def seed_presentation(base,cfg,fixture):
    """Fixed fictional baseline, never reimported when resuming this runtime."""
    scripts=[
        ['今天和朋友散步，我很开心。','愿意讲讲今天最开心的片段吗？','我很期待下一次见面。','可以把这段愉快的感受记录下来。'],
        ['最近孩子工作很忙，我感到孤独。','我愿意听你慢慢讲。','我也很担心家人，最近压力很大。','如果愿意，可以先说一件最希望被理解的事。'],
        ['最近我觉得很难过。','我们可以慢慢说说发生了什么。','我不想活了。','这句话需要优先人工关注与核实，请联系身边可信赖的人协助获得支持。'],
    ]
    cfg['session_ids']=[]
    with httpx.Client(base_url=base,trust_env=False,timeout=5) as client:
        for index,user in enumerate(cfg['users']):
            r=client.post('/api/auth/register',json={k:user[k] for k in ('username','password')});r.raise_for_status()
            r=client.post('/api/auth/login',json={k:user[k] for k in ('username','password')});r.raise_for_status();user['token']=r.json()['access_token']
            if index:continue
            headers={'Authorization':'Bearer '+user['token']}
            r=client.get('/api/auth/me',headers=headers);r.raise_for_status()
            user['owner_user_id']=r.json()['id']
            seed_assessments(fixture,user['owner_user_id'])
            for number,lines in enumerate(scripts,1):
                stamp=datetime.now(timezone.utc).isoformat()
                r=client.post('/api/robot-records/sessions',headers=headers,json=dict(source='doubao_realtime',device_id='presentation_demo',external_session_id=f'presentation_{number}',started_at=stamp,is_test=True));r.raise_for_status();sid=r.json()['recording_session_id'];cfg['session_ids'].append(sid)
                for sequence,content in enumerate(lines,1):
                    user_role=sequence%2==1
                    r=client.post(f'/api/robot-records/sessions/{sid}/messages',headers=headers,json=dict(external_message_id=f'message_{sequence}',turn_id=f'turn_{(sequence+1)//2}',sequence_no=sequence,role='user' if user_role else 'assistant',content=content,occurred_at=stamp,text_status='completed',playback_status='not_applicable' if user_role else 'not_started'));r.raise_for_status()
                r=client.post(f'/api/robot-records/sessions/{sid}/close',headers=headers,json=dict(ended_at=stamp,last_sequence_no=len(lines)));r.raise_for_status()

def seed_assessments(fixture,uid):
    """Original fictional results; preserve historical versions, scores and dates."""
    for index,(date,score,version) in enumerate([('2026-10-20T10:00:00+08:00',5,'demo-v1'),('2026-10-27T10:00:00+08:00',7,'demo-v1'),('2026-10-28T10:00:00+08:00',4,'demo-v2')],1):
        fixture['records'].append(dict(owner_user_id=uid,source_record_id=f'fixture:user{uid}_{index}',is_test=True,
            scale_name='demo_wellbeing',display_name='虚构展示量表（非实际评估）',scale_version=version,scoring_version=version,
            interpretation_version='demo-draft-v1',completed_at=date,total_score=score,score_min=0,score_max=10,
            reference_interpretation='虚构分数用于演示数值展示，不表示心理状态或疾病。',suggestions='可以选择与信任的人分享日常感受。'))


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
            seed_assessments(fixture,uid)


def stop(root,cfg):
    path=root/'pids.json'
    if not path.exists():
        result={'stopped_recorded_demo_processes':True,'already_stopped':True,'results':[]}
        print(json.dumps(result))
        return result
    records=json.loads(path.read_text(encoding='utf-8'))
    remaining=[]
    results=[]
    for record in reversed(records):
        outcomes=[]
        valid=(record.get('identity_schema')==1 and cfg.get('runtime_id') and
               record.get('runtime_id')==cfg['runtime_id'] and record.get('runtime_root')==str(root.resolve()) and
               isinstance(record.get('identity'),dict) and record['identity'].get('argv')==record.get('command'))
        if not valid:
            outcomes.append({'pid':record.get('pid'),'status':'not_stopped','reason':'ownership_record_unverified'})
        else:
            expected_processes=[*reversed(record.get('children',[])),record['identity']]
            known={value['pid'] for value in expected_processes}
            for expected in expected_processes:
                outcome={'pid':expected['pid']}
                try:
                    current=process_identity(expected['pid'])
                    if current is None:
                        outcome['status']='already_gone'
                    elif identity_key(current)!=identity_key(expected):
                        outcome.update(status='not_stopped',reason='identity_mismatch')
                    elif current.get('platform')=='linux' and (current.get('runtime_id')!=cfg['runtime_id'] or
                            current.get('runtime_root')!=str(root.resolve()) or current.get('process_id')!=record.get('process_id')):
                        outcome.update(status='not_stopped',reason='runtime_mismatch')
                    elif any(pid not in known for pid in child_pids(expected['pid'])):
                        outcome.update(status='not_stopped',reason='unrecorded_child')
                    else:
                        status=signal_verified(expected)
                        outcome.update(status=status if status in ('stopped','already_gone') else 'not_stopped')
                        if status not in ('stopped','already_gone'):
                            outcome['reason']=status
                except ProcessIdentityError as error:
                    outcome.update(status='not_stopped',reason=str(error))
                except (OSError,ValueError,KeyError,TypeError):
                    outcome.update(status='not_stopped',reason='identity_operation_failed')
                outcomes.append(outcome)
        stopped=all(value['status'] in ('stopped','already_gone') for value in outcomes)
        results.append({'label':record.get('label'),'complete':stopped,'processes':outcomes})
        if not stopped:
            record['last_stop_result']=outcomes
            remaining.append(record)
    result={'stopped_recorded_demo_processes':not remaining,'already_stopped':False,'results':results}
    stamp=str(time.time_ns())
    write_json(root/('stop_attempt_'+stamp+'.json'),result)
    if remaining:
        write_json(path,list(reversed(remaining)))
    else:
        path.rename(root/('pids_stopped_'+stamp+'.json'))
    print(json.dumps(result))
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','start','stop'])
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--no-frontend',action='store_true')
    parser.add_argument('--empty',action='store_true',help='Prepare accounts only, without sample records or assessments')
    parser.add_argument('--presentation',action='store_true',help='Prepare a fixed set of fictional presentation dialogues')
    args=parser.parse_args()
    root=args.runtime.resolve()
    if args.action=='prepare':
        if args.empty and args.presentation:parser.error('Choose empty or presentation')
        prepare(root,empty=args.empty,presentation=args.presentation)
        return
    cfg=json.loads((root/'access.json').read_text(encoding='utf-8'))
    if cfg.get('marker')!='module236-synthetic-demo-v1' or Path(cfg['database']).parent!=root:
        raise ValueError('invalid_demo_directory')
    if args.action=='start':
        start(root,cfg,not args.no_frontend)
    elif not stop(root,cfg)['stopped_recorded_demo_processes']:
        raise SystemExit(2)

if __name__=='__main__':
    main()
