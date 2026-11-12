import json
import os
import socket
import sys
import tempfile
import subprocess
import sqlite3
from datetime import datetime, timezone, timedelta
from importlib.metadata import version
from pathlib import Path

import pytest

RUN_ROOT = Path(tempfile.mkdtemp(prefix='module24-tests-'))
os.environ['DATABASE_URL'] = 'sqlite:///' + (RUN_ROOT / 'server.db').as_posix()
os.environ['SECRET_KEY'] = 'fictional-test-only-secret-key-32-characters'
os.environ['SQLITE_BUSY_MS'] = '80'
os.environ['MODELSCOPE_API_KEY'] = ''
os.environ['DOUBAO_VOICE_API_KEY'] = ''
os.environ['ROBOT_CARE_VOICE_ENABLED'] = 'false'
os.environ['ROBOT_CARE_REPORT_PROVIDER'] = 'disabled'
os.environ['ROBOT_CARE_ANALYSIS_ENGINE'] = 'rules'
os.environ['ROBOT_CARE_GUIDED_SCREENING_ENABLED'] = 'false'
os.environ['ROBOT_CARE_PURCHASE_NOTICE_VERSION'] = ''
os.environ['PYTHONUTF8'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app.models import User
import bcrypt

RESULTS = Path(os.getenv('MODULE24_EVIDENCE', str(RUN_ROOT / 'evidence'))).resolve()
RESULTS.mkdir(parents=True, exist_ok=True)

def pytest_sessionstart(session):
    root=Path(__file__).resolve().parents[2]
    data={
        'started_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'python_executable':sys.executable,'python_version':sys.version,'sqlite_version':sqlite3.sqlite_version,
        'dependencies':{name:version(name) for name in ('fastapi','sqlalchemy','httpx','pydantic','pytest','uvicorn')},
        'code_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip() if (root/'.git').exists() else 'source_archive',
        'command':[sys.executable,*sys.argv], 'database':str(RUN_ROOT/'server.db'),
    }
    (RESULTS/'run_environment.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def pytest_sessionfinish(session,exitstatus):
    path=RESULTS/'run_environment.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    data.update(finished_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),exit_code=int(exitstatus),
                tests_collected=session.testscollected)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

class API:
    def __init__(self, client, token, uid, trace):
        self.client, self.token, self.uid, self.trace = client, token, uid, trace

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, headers={'Authorization': 'Bearer ' + self.token}, **kwargs)
        try:
            data = response.json()
        except ValueError:
            data = None
        self.trace.append(dict(method=method, path=path, request=kwargs.get('json'), status=response.status_code, response=data))
        return response

    def create(self, external='virtual_session', **kwargs):
        return self.request('POST', '/api/robot-records/sessions', json=session_body(external, **kwargs))

    def send(self, sid, seq=1, **kwargs):
        return self.request('POST', f'/api/robot-records/sessions/{sid}/messages', json=message_body(seq, **kwargs))

    def messages(self, sid, **kwargs):
        return self.request('GET', f'/api/robot-records/sessions/{sid}/messages', **kwargs)

    def detail(self, sid):
        return self.request('GET', f'/api/robot-records/sessions/{sid}')

def session_body(external='virtual_session', **kwargs):
    return dict(source='doubao_realtime', device_id='virtual_device', external_session_id=external,
                started_at='2026-10-28T00:00:00+08:00', is_test=True, **kwargs) if not kwargs else {
        **session_body(external), **kwargs}

def message_body(seq=1, **kwargs):
    return {**dict(external_message_id=f'virtual_msg_{seq}', turn_id=None, sequence_no=seq, role='user',
                   content='虚构测试文字\n保留 空格 🌳', occurred_at='2026-10-28T00:00:01+08:00',
                   text_status='completed', playback_status='not_applicable'), **kwargs}

@pytest.fixture
def trace(request):
    events = []
    yield events
    name = request.node.name.replace('/', '_').replace('\\', '_').replace(':', '_')
    (RESULTS / (name + '.json')).write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding='utf-8')

@pytest.fixture(autouse=True)
def isolated_db_and_network(monkeypatch):
    engine.dispose()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    real_connect = socket.socket.connect
    def guarded(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', 'localhost', '::1'):
            raise AssertionError('External network forbidden during tests')
        return real_connect(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', guarded)
    import ollama
    async def no_async_model(*args, **kwargs):
        raise AssertionError('Model invocation forbidden')
    def no_model(*args, **kwargs):
        raise AssertionError('Model invocation forbidden')
    monkeypatch.setattr(ollama.AsyncClient, 'chat', no_async_model)
    monkeypatch.setattr(ollama.Client, 'chat', no_model)

@pytest.fixture
def actors(trace):
    with SessionLocal() as db:
        for name in ('virtual_a', 'virtual_b'):
            db.add(User(username=name, hashed_password=bcrypt.hashpw(b'fictional-only', bcrypt.gensalt(rounds=4)).decode()))
        db.commit()
    with TestClient(app) as client:
        apis = []
        for name in ('virtual_a', 'virtual_b'):
            r = client.post('/api/auth/login', json={'username': name, 'password': 'fictional-only'})
            assert r.status_code == 200
            token = r.json()['access_token']
            uid = client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + token}).json()['id']
            trace.append({'login': name, 'status': 200, 'owner_id': uid, 'token': '[omitted]'})
            apis.append(API(client, token, uid, trace))
        yield apis
