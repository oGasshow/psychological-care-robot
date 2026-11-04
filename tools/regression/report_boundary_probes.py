"""Isolated 2.6 acceptance probes; no external services, no source mutation.

Usage: dedicated_python report_boundary_probes.py --backend <frozen-source/backend> --output <evidence-dir>
Exit 1 means one or more boundary defects reproduced; exit 0 means neither defect reproduced.
The is_test=False case still contains only invented text and a virtual account.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--backend', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
backend = args.backend.resolve()
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
runtime = Path(tempfile.mkdtemp(prefix='module236-report-probes-'))
os.environ.update(
    DATABASE_URL='sqlite:///' + (runtime / 'isolated.db').as_posix(),
    SECRET_KEY='fictional-audit-only-secret-32-characters',
    APP_ENV='test', ROBOT_CARE_ANALYSIS_ENGINE='rules',
    ROBOT_CARE_ASSESSMENT_PROVIDER='disabled',
    ROBOT_CARE_SIMULATOR_ENABLED='false', MODELSCOPE_API_KEY='',
)
sys.dont_write_bytecode = True
sys.path.insert(0, str(backend))
real_connect = socket.socket.connect

def guarded_connect(sock, address):
    if isinstance(address, tuple) and address[0] not in ('127.0.0.1', 'localhost', '::1'):
        raise AssertionError('External network forbidden during acceptance probes')
    return real_connect(sock, address)

socket.socket.connect = guarded_connect
from app.main import app
from app.database import SessionLocal
from app.models import User
from app.care.worker import Worker
from fastapi.testclient import TestClient
import bcrypt

with SessionLocal() as db:
    db.add(User(username='virtual_audit26', hashed_password=bcrypt.hashpw(b'fictional-only', bcrypt.gensalt(rounds=4)).decode()))
    db.commit()

with TestClient(app, raise_server_exceptions=False) as client:
    login = client.post('/api/auth/login', json={'username': 'virtual_audit26', 'password': 'fictional-only'})
    assert login.status_code == 200
    headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
    provider_before = client.get('/api/robot-insights/assessments', headers=headers)
    assert provider_before.status_code == 200 and provider_before.json()['provider'] == 'disabled'
    assert provider_before.json()['items'] == []
    sessions = []
    # Deliberately distinct metadata, but BOTH texts are fictional and this is an isolated test DB.
    for number, is_test in enumerate((False, True), 1):
        created = client.post('/api/robot-records/sessions', headers=headers, json={
            'source': 'doubao_realtime', 'device_id': 'virtual_audit_device',
            'external_session_id': f'virtual26_{number}', 'started_at': '2026-10-20T00:00:00Z', 'is_test': is_test,
        })
        assert created.status_code == 201, created.text
        sid = created.json()['recording_session_id']
        sessions.append({'recording_session_id': sid, 'is_test': is_test})
        sent = client.post(f'/api/robot-records/sessions/{sid}/messages', headers=headers, json={
            'external_message_id': f'virtual26_m{number}', 'turn_id': None, 'sequence_no': 1,
            'role': 'user', 'content': '今天很开心。',
            'occurred_at': f'2026-10-{20 + number:02}T00:00:00Z',
            'text_status': 'completed', 'playback_status': 'not_applicable',
        })
        assert sent.status_code == 201, sent.text
    worker = Worker()
    worker.scan()
    while worker.step():
        pass
    trend_response = client.get('/api/robot-insights/trends', headers=headers)
    assert trend_response.status_code == 200
    groups = trend_response.json()['emotion_groups']
    mixed_groups = [group for group in groups if {point['recording_session_id'] for point in group['points']} >= {s['recording_session_id'] for s in sessions}]
    report_response = client.post('/api/robot-insights/reports/preview', headers=headers, json={
        'scope': {'time_from': '2026-10-01T00:00:00Z', 'time_to': '2026-11-01T00:00:00Z'},
    })
    assert report_response.status_code == 200
    report = report_response.json()
    result = {
        'backend': str(backend), 'runtime': str(runtime), 'python_executable': sys.executable,
        'all_text_synthetic': True, 'external_network_forbidden': True,
        'R26_01_mixed_test_metadata': {
            'provider_before': provider_before.json()['provider'], 'assessment_items_before': len(provider_before.json()['items']),
            'sessions': sessions, 'emotion_groups': groups,
            'mixed_group_count': len(mixed_groups), 'report_is_test': report['is_test'],
            'report_positive_count': report['emotion_counts']['positive'],
            'reproduced': bool(mixed_groups),
        },
    }
    fixture_path = runtime / 'invalid_structure.json'
    fixture_path.write_text('[]', encoding='utf-8')
    os.environ.update(ROBOT_CARE_ASSESSMENT_PROVIDER='fixture', ROBOT_CARE_DEMO_DATABASE='true', ROBOT_CARE_FIXTURE_FILE=str(fixture_path))
    response = client.get('/api/robot-insights/assessments', headers=headers)
    result['R26_02_fixture_top_level_array'] = {
        'fixture_content': '[]', 'response_status': response.status_code,
        'response_text': response.text, 'reproduced': response.status_code >= 500,
    }
    result['findings_reproduced'] = sum(result[key]['reproduced'] for key in ('R26_01_mixed_test_metadata', 'R26_02_fixture_top_level_array'))
    (output / 'frozen_source_results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result['findings_reproduced'] else 0)
