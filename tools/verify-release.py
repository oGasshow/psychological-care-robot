"""Run release checks in the current extracted project and its own venv.

All runtime users/data are fictional; deliberate non-test flags only test metadata.
Never prints credentials. Evidence must be separate from source and private runtime.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
NO_WINDOW=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['backend','start','browser','lifecycle'])
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--runtime',type=Path)
    parser.add_argument('--node',default='node')
    parser.add_argument('--browser',default=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    args=parser.parse_args()
    evidence=args.evidence.resolve();evidence.mkdir(parents=True,exist_ok=True)
    runtime=(args.runtime or ROOT/'runtime/release_demo').resolve()
    if Path(sys.prefix).resolve()!= (ROOT/'.venv').resolve():
        raise RuntimeError('Run this script with this extracted project .venv interpreter')
    base_env=dict(os.environ,PYTHONUTF8='1',NEXT_TELEMETRY_DISABLED='1')
    commands=[]
    def save(name,data):
        path=evidence/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    def run(name,command,cwd=ROOT,extra=None):
        env=dict(base_env,**(extra or {}));start=datetime.now(timezone.utc).isoformat()
        with (evidence/(name+'.stdout')).open('wb') as stdout,(evidence/(name+'.stderr')).open('wb') as stderr:
            process=subprocess.run(list(map(str,command)),cwd=cwd,env=env,stdout=stdout,stderr=stderr,creationflags=NO_WINDOW)
        entry=dict(name=name,command=list(map(str,command)),cwd=str(cwd),started_at=start,finished_at=datetime.now(timezone.utc).isoformat(),exit_code=process.returncode,
                   frontend_lock_sha256=sha(ROOT/'frontend/package-lock.json'),backend_lock_sha256=sha(ROOT/'backend/uv.lock'))
        commands.append(entry);save(args.phase+'_execution.json',commands)
        if process.returncode:raise RuntimeError(name+'_failed_see_evidence')
        return (evidence/(name+'.stdout')).read_text(encoding='utf-8')
    backend=ROOT/'backend'
    if args.phase=='backend':
        run('pytest',[sys.executable,'-m','pytest','tests','-q','--junitxml='+str(evidence/'junit.xml')],backend,
            {'MODULE24_EVIDENCE':str(evidence/'test_evidence')})
        probe_dir=evidence/'original_probes';probe_dir.mkdir(exist_ok=True)
        for source in (ROOT/'tools/regression').glob('*.py'):shutil.copyfile(source,probe_dir/source.name)
        run('probe_config',[sys.executable,probe_dir/'config_reversion_probe.py',backend])
        run('probe_report',[sys.executable,probe_dir/'report_boundary_probes.py','--backend',backend,'--output',probe_dir/'report'])
        run('probe_linux',[sys.executable,probe_dir/'probe_lifecycle_linux.py','--source',backend/'tools/demo_care.py','--output',probe_dir/'linux_stop.json'])
        # Run after other process tests have exited; retain any cleanup failure.
        run('twenty',[sys.executable,backend/'tools/replay_twenty.py','--output-dir',evidence/'twenty_rounds'],backend)
    elif args.phase=='start':
        run('demo_prepare',[sys.executable,backend/'tools/demo_care.py','prepare','--runtime',runtime])
        run('demo_start',[sys.executable,backend/'tools/demo_care.py','start','--runtime',runtime])
    elif args.phase=='browser':
        cfg=json.loads((runtime/'access.json').read_text(encoding='utf-8'))
        origin=f'http://127.0.0.1:{cfg["frontend_port"]}'
        frontend=ROOT/'frontend'
        env=dict(CARE_BASE_URL=origin,DEMO_USER=cfg['users'][0]['username'],DEMO_PASSWORD=cfg['users'][0]['password'],BROWSER_EXE=args.browser)
        for _ in range(60):
            try:
                import httpx
                if httpx.get(origin+'/login',trust_env=False,timeout=1).status_code==200:break
            except (OSError,httpx.RequestError):pass
            time.sleep(.25)
        else:raise RuntimeError('frontend_not_ready')
        for label,script in [('browser','browser-evidence.mjs'),('browser_d02','browser-data-nature.mjs')]:
            run(label,[args.node,frontend/'tools'/script],frontend,dict(env,EVIDENCE_DIR=str(evidence/label)))
        fixture=Path(cfg['fixture']);original=fixture.read_bytes()
        before=sha(fixture)
        try:
            fixture.write_text('[]',encoding='utf-8')
            run('browser_d03',[args.node,frontend/'tools/browser-provider-errors.mjs'],frontend,dict(env,EVIDENCE_DIR=str(evidence/'browser_d03')))
        finally:
            fixture.write_bytes(original)
            save('fixture_restoration.json',dict(before_sha256=before,after_sha256=sha(fixture),restored=sha(fixture)==before))
        assert sha(fixture)==before
    else:
        cfg=json.loads((runtime/'access.json').read_text(encoding='utf-8'))
        def counts():
            with sqlite3.connect(cfg['database'],timeout=5) as db:
                tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'") if r[0].startswith(('robot_','care_'))]
                return {name:db.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in tables}
        def identities():
            records=json.loads((runtime/'pids.json').read_text(encoding='utf-8'))
            return sorted({item['pid'] for record in records for item in [record['identity'],*record.get('children',[])]})
        stopped=[]
        def check_closed(pids):
            filters=' OR '.join('ProcessId='+str(pid) for pid in pids)
            command="$found=@(Get-CimInstance Win32_Process -Filter '"+filters+"'); @($found | ForEach-Object {[int]$_.ProcessId}) | ConvertTo-Json -Compress"
            check=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,text=True,creationflags=NO_WINDOW)
            assert check.returncode==0
            present=json.loads(check.stdout) if check.stdout.strip() else []
            if isinstance(present,int):present=[present]
            ports={}
            for port in (cfg['backend_port'],cfg['frontend_port']):
                with socket.socket() as sock:
                    sock.settimeout(1);ports[str(port)]=sock.connect_ex(('127.0.0.1',port))==0
            state=dict(recorded_pids=pids,remaining_pids=present,ports_listening=ports)
            stopped.append(state);save('lifecycle_stopped_checks.json',stopped)
            assert not present and not any(ports.values())
        first=identities();before=counts()
        run('demo_stop_first',[sys.executable,backend/'tools/demo_care.py','stop','--runtime',runtime]);check_closed(first)
        repeated=run('demo_stop_repeated',[sys.executable,backend/'tools/demo_care.py','stop','--runtime',runtime])
        assert json.loads(repeated)['already_stopped'] is True
        run('demo_restart',[sys.executable,backend/'tools/demo_care.py','start','--runtime',runtime])
        second=identities();after=counts()
        assert set(first).isdisjoint(second) and before==after
        save('lifecycle_data_preservation.json',dict(before=before,after=after,data_counts_equal=True,first_pids=first,restarted_pids=second))
        run('demo_stop_final',[sys.executable,backend/'tools/demo_care.py','stop','--runtime',runtime]);check_closed(second)
        repeated=run('demo_stop_final_repeated',[sys.executable,backend/'tools/demo_care.py','stop','--runtime',runtime])
        assert json.loads(repeated)['already_stopped'] is True
    print(json.dumps({'phase':args.phase,'status':'passed','commands':len(commands)}))

if __name__=='__main__':main()
