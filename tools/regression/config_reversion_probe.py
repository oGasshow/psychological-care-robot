import sys, os, json, copy
from pathlib import Path
backend=Path(sys.argv[1]).resolve()
out=Path(__file__).with_name('config_reversion_results.json')
os.environ['APP_ENV']='test'
os.environ['ROBOT_CARE_ANALYSIS_ENGINE']='rules'
os.environ['ROBOT_CARE_ASSESSMENT_PROVIDER']='disabled'
os.environ['ROBOT_CARE_SIMULATOR_ENABLED']='true'
sys.path[:0]=[str(backend/'tests'),str(backend)]
import conftest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base,engine,SessionLocal
from app.models import User
from app.care.worker import Worker
import care_core.core as core
import bcrypt
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)
with SessionLocal() as db:
    db.add(User(username='config_probe_virtual',hashed_password=bcrypt.hashpw(b'virtual_password',bcrypt.gensalt(rounds=4)).decode()))
    db.commit()
P='/api/robot-insights'
with TestClient(app) as client:
    token=client.post('/api/auth/login',json={'username':'config_probe_virtual','password':'virtual_password'}).json()['access_token']
    headers={'Authorization':'Bearer '+token}
    def call(method,path,**kwargs):
        r=client.request(method,path,headers=headers,**kwargs)
        assert r.status_code < 400,(path,r.status_code)
        return r.json()
    sid=call('POST','/api/robot-records/sessions',json=conftest.session_body('config_reversion_probe'))['recording_session_id']
    rid=call('POST',f'/api/robot-records/sessions/{sid}/messages',json=conftest.message_body(content='我今天很开心。'))['record_id']
    worker_a=Worker()
    assert worker_a.scan()==1 and worker_a.step()
    before=call('GET',f'{P}/sessions/{sid}/analyses')['items']
    original=core._RULES
    core._RULES=copy.deepcopy(original)
    core._RULES['rules_version']='rules-v1-config-probe-B'
    worker_b=Worker()
    assert worker_b.scan()==1 and worker_b.step()
    middle=call('GET',f'{P}/sessions/{sid}/analyses')['items']
    core._RULES=original
    worker_return_a=Worker()
    created=worker_return_a.scan()
    processed=worker_return_a.step()
    manual=call('POST',P+'/analysis-jobs',json={'record_id':rid})
    after=call('GET',f'{P}/sessions/{sid}/analyses')['items']
    keys=('job_id','state','is_current','config_version','input_revision','emotion_label')
    pick=lambda rows:[{k:r[k] for k in keys} for r in rows]
    result={'code_commit':'1acb3f222168c19179561550818fbf31867459cf','interpreter':sys.executable,'isolated_database':str(conftest.RUN_ROOT/'server.db'),'config_a':worker_a.config['config_version'],'config_b':worker_b.config['config_version'],'config_return_a':worker_return_a.config['config_version'],'after_a':pick(before),'after_b':pick(middle),'return_a_scan_created':created,'return_a_step':processed,'return_a_manual_job':{k:manual[k] for k in keys},'after_return_a':pick(after)}
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    print('EVIDENCE_PATH='+str(out))
