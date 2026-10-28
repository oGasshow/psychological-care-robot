import json
import os
import subprocess
import sys

import pytest

from robot_client import Outbox, OutboxError, Worker
from conftest import session_body
from test_outbox import make_box, event, drain, response
from test_processes import server, login, BACKEND, NO_WINDOW


def test_N07_open_is_durable_and_has_zero_worker_http(actors, tmp_path, trace):
    a, _ = actors
    box, transport = make_box(tmp_path, a, upload_policy='after_close')
    box.create_session(session_body())
    assert box.enqueue('virtual_session', event()) == 1
    calls = len(transport.calls)
    assert Worker(box, transport).step() is False
    assert transport.calls[calls:] == []
    reopened = Outbox(box.path, box.base, box.owner, upload_policy='after_close')
    assert all(s['waiting_for_close'] and s['display_status'] == '等待会话结束' and
               s['state'] == 'pending' and s['attempts'] == 0 for s in reopened.status())
    assert reopened.enqueue('virtual_session', event(2)) == 2
    assert reopened.close_session('virtual_session', '2026-10-28T00:02:00+08:00') == 2
    drain(Worker(reopened, transport))
    assert all(s['state'] == 'acked' and not s['waiting_for_close'] for s in reopened.status())
    trace.append({'persisted_policy_status': reopened.status(), 'http_while_open': 0})


def test_N08_other_open_session_does_not_block_sealed_and_close_waits_for_messages(actors, tmp_path, trace):
    a, _ = actors
    box, transport = make_box(tmp_path, a, upload_policy='after_close')
    box.create_session(session_body('keep_open'))
    box.enqueue('keep_open', event())
    box.create_session(session_body('upload_sealed'))
    box.enqueue('upload_sealed', event())
    box.close_session('upload_sealed', '2026-10-28T00:02:00+08:00')
    transport.calls.clear()
    clock = [1000.0]
    worker = Worker(box, transport, clock=lambda: clock[0], retry_base=10, rng=lambda: 1)
    assert worker.step()  # Create only the sealed session.
    transport.fault = lambda method, path, kwargs: response(503) if path.endswith('/messages') else None
    assert worker.step()
    assert worker.step() is False  # Close is held until the failed message succeeds.
    assert not any(path.endswith('/close') for _, path in transport.calls)
    transport.fault = None
    clock[0] += 11
    drain(worker)
    held = [s for s in box.status() if s['external'] == 'keep_open']
    sent = [s for s in box.status() if s['external'] == 'upload_sealed']
    assert all(s['state'] == 'pending' and s['attempts'] == 0 and s['server_id'] is None for s in held)
    assert all(s['state'] == 'acked' for s in sent)
    assert a.detail(sent[0]['server_id']).json()['is_complete'] is True
    trace.append({'open_held': held, 'sealed_uploaded': sent})


def test_N11_after_close_pause_barrier_and_highwater_survive_reopen(actors, tmp_path, trace):
    a, b = actors
    box, transport = make_box(tmp_path, a, upload_policy='after_close')
    box.create_session(session_body())
    assert box.enqueue('virtual_session', event()) == 1
    box.close_session('virtual_session', '2026-10-28T00:02:00+08:00')
    transport.fault = lambda method, path, kwargs: response(401) if path == '/api/auth/me' else None
    assert Worker(box, transport).step()
    reopened = Outbox(box.path, box.base, box.owner, upload_policy='after_close')
    transport.calls.clear()
    assert Worker(reopened, transport).step() is False
    assert transport.calls == [] and reopened.partition_status()['auth_blocked']
    assert all(s['next_sequence'] == 2 and s['display_status'] == '身份暂停' for s in reopened.status())
    reopened.resume()
    transport.fault = None
    drain(Worker(reopened, transport))
    assert all(s['state'] == 'acked' and s['next_sequence'] == 2 for s in reopened.status())
    trace.append({'recovered': reopened.status()})


def test_upload_policy_validated_and_default_is_streaming(actors, tmp_path):
    a, _ = actors
    with pytest.raises(OutboxError, match='invalid_upload_policy'):
        make_box(tmp_path, a, upload_policy='unknown')
    box, transport = make_box(tmp_path, a)
    box.create_session(session_body())
    assert box.upload_policy == 'streaming'
    assert Worker(box, transport).step() is True
    assert box.status()[0]['state'] == 'acked'


def test_cli_reads_after_close_policy_from_environment(actors, tmp_path, trace):
    a, _ = actors
    box, transport = make_box(tmp_path, a, upload_policy='after_close')
    box.create_session(session_body())
    command = [sys.executable, '-m', 'robot_client', '--owner', str(box.owner), 'status']
    result = subprocess.run(command, cwd=BACKEND, env=dict(os.environ,
                            ROBOT_UPLOAD_POLICY='after_close', ROBOT_OUTBOX_PATH=str(box.path),
                            ROBOT_BASE_URL=box.base, PYTHONUTF8='1'),
                            capture_output=True, text=True, encoding='utf-8', creationflags=NO_WINDOW, timeout=10)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data[0]['upload_policy'] == 'after_close' and data[0]['waiting_for_close'] is True
    trace.append({'command': command, 'exit_code': result.returncode, 'status': data})


def test_N09_N10_N11_twenty_real_http_and_killed_process_recovery(server, tmp_path, trace):
    owner, token = login(server)
    evidence = tmp_path / 'twenty_evidence'
    command = [sys.executable, str(BACKEND / 'tools/replay_twenty.py'),
               '--base-url', server.base, '--output-dir', str(evidence)]
    result = subprocess.run(command, cwd=BACKEND, env=dict(os.environ, ROBOT_TOKEN=token, PYTHONUTF8='1'),
                            capture_output=True, text=True, encoding='utf-8', creationflags=NO_WINDOW, timeout=100)
    assert result.returncode == 0, result.stderr
    summary = json.loads((evidence / 'twenty_summary.json').read_text(encoding='utf-8'))
    assert summary['normal']['record_success'] == {'numerator': 40, 'denominator': 40, 'rate': 1.0}
    assert summary['normal']['complete_turns'] == {'numerator': 20, 'denominator': 20, 'rate': 1.0}
    assert summary['fault_before']['record_success']['denominator'] == summary['fault_after']['record_success']['denominator'] == 40
    assert summary['fault_before']['complete_turns']['denominator'] == summary['fault_after']['complete_turns']['denominator'] == 20
    assert summary['fault_after']['record_success']['numerator'] == 40
    assert summary['fault_after']['complete_turns']['numerator'] == 20
    assert summary['fault_before']['record_success']['numerator'] < 40
    lifecycle = json.loads((evidence / 'process_lifecycle.json').read_text(encoding='utf-8'))
    killed = [row for row in lifecycle if row['action'] == 'worker_killed']
    assert {row['mode'] for row in killed} == {'open', 'pause', 'check_pause', 'response_loss'}
    assert any(row['action'] == 'proxy_injected_http_503' for row in lifecycle)
    assert len({row['pid'] for row in lifecycle if row['action'] == 'worker_start'}) == 5
    attempt_rows = [json.loads(row) for row in (evidence / 'attempts_recover.jsonl').read_text(encoding='utf-8').splitlines()]
    assert any(row.get('sequence_no') == 7 and row.get('status') == 200 for row in attempt_rows)
    trace.append({'command': command, 'exit_code': result.returncode, 'evidence_directory': str(evidence),
                  'summary': summary, 'process_lifecycle': lifecycle})
