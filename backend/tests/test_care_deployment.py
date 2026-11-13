"""Real startup rejection and dedicated-demo lifecycle; no model or company calls."""
import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

BACKEND=Path(__file__).resolve().parents[1]
NO_WINDOW=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0

def run(args,env,timeout=45):
    return subprocess.run([sys.executable,*args],cwd=BACKEND,env=env,capture_output=True,text=True,
                          encoding='utf-8',errors='replace',timeout=timeout,creationflags=NO_WINDOW)

@pytest.mark.parametrize('changes,expected',[
    ({'ROBOT_CARE_ASSESSMENT_PROVIDER':'fixture','ROBOT_CARE_DEMO_DATABASE':'true','ROBOT_CARE_FIXTURE_FILE':'virtual.json'},'demo_feature_forbidden_in_production'),
    ({'ROBOT_CARE_SIMULATOR_ENABLED':'true'},'demo_feature_forbidden_in_production'),
    ({'ROBOT_CARE_ANALYSIS_ENGINE':'ollama'},'model_configuration_required'),
    ({'ROBOT_CARE_ANALYSIS_ENGINE':'ollama','ROBOT_CARE_MODEL_BASE_URL':'file:///not-an-endpoint','ROBOT_CARE_MODEL_NAME':'test'},'model_configuration_invalid'),
    ({'ROBOT_CARE_SIMULATOR_ENABLED':'perhaps'},'invalid_care_configuration'),
    ({'SECRET_KEY':''},'Set SECRET_KEY'),
])
def test_N45_real_worker_rejects_invalid_production_before_calls(tmp_path,changes,expected):
    env={k:v for k,v in os.environ.items() if not k.startswith('ROBOT_CARE_')}
    env.update(APP_ENV='production',SECRET_KEY='virtual-startup-secret-01234567890123456789',
               DATABASE_URL='sqlite:///'+(tmp_path/'isolated.db').as_posix(),PYTHONUTF8='1',MODELSCOPE_API_KEY='')
    env.update(changes)
    proc=run(['-m','app.care.worker','--once'],env)
    assert proc.returncode!=0
    assert expected in proc.stderr
    assert not (tmp_path/'isolated.db').exists()

def test_N44_real_prepare_start_stop_and_restart_preserves_data(tmp_path,trace):
    runtime=tmp_path/'dedicated_virtual_demo'
    env=dict(os.environ,PYTHONUTF8='1')
    args=['tools/demo_care.py']
    prepared=run([*args,'prepare','--runtime',str(runtime)],env)
    assert prepared.returncode==0,prepared.stderr
    private=(runtime/'access.json').read_bytes()
    refused=run([*args,'prepare','--runtime',str(runtime)],env)
    assert refused.returncode!=0 and (runtime/'access.json').read_bytes()==private
    def start():
        result=run([*args,'start','--runtime',str(runtime),'--no-frontend'],env)
        assert result.returncode==0,result.stderr
        cfg=json.loads((runtime/'access.json').read_text(encoding='utf-8'))
        with httpx.Client(base_url=f'http://127.0.0.1:{cfg["backend_port"]}',trust_env=False,timeout=5) as client:
            ids=[]
            for user in cfg['users']:
                headers={'Authorization':'Bearer '+user['token']}
                profile=client.get('/api/robot-insights/profile',headers=headers)
                assert profile.status_code==200
                ids.append(profile.json()['anonymous_id'])
            assert ids[0]!=ids[1]
            headers={'Authorization':'Bearer '+cfg['users'][0]['token']}
            count=client.get('/api/robot-records/sessions',headers=headers).json()['items']
            sid=cfg['session_ids'][0]
            summary=client.get(f'/api/robot-insights/sessions/{sid}/summary',headers=headers).json()
            assert sum(summary['emotion_counts'].values())==4
            assert summary['analysis_counts']['succeeded']==6
            assert summary['analysis_counts']['unable_to_determine']==2
        assert cfg['users'][0]['password'] not in result.stdout
        return ids,len(count),json.loads((runtime/'pids.json').read_text(encoding='utf-8'))
    def stop():
        result=run([*args,'stop','--runtime',str(runtime)],env)
        assert result.returncode==0,result.stderr
        assert not (runtime/'pids.json').exists()
        cfg=json.loads((runtime/'access.json').read_text(encoding='utf-8'))
        with pytest.raises((httpx.ConnectError,httpx.ConnectTimeout)):
            httpx.get(f'http://127.0.0.1:{cfg["backend_port"]}/health',trust_env=False,timeout=1)
    try:
        ids,count,first=start()
        stop()
        again,new_count,second=start()
        assert again==ids and new_count==count
        assert {p['pid'] for p in first}.isdisjoint({p['pid'] for p in second})
        trace.append({'runtime':str(runtime),'first_processes':first,'restarted_processes':second,
                      'same_anonymous_ids':True,'sessions_preserved':count,'prepare_existing_refused':True})
    finally:
        stop()
