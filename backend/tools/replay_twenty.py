"""Fixed synthetic 20-turn audit over real HTTP, including killed-process recovery.

Run with no --base-url for a private loopback backend; otherwise ROBOT_TOKEN is
required. Exported evidence contains only the declared synthetic manifest and
sanitized attempts. Credentials and runtime SQLite files stay in a temp folder.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from robot_client import Outbox, Transport, Worker
from robot_client.schemas import SessionCreate, MessageCreate, utc

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
MANIFEST = BACKEND / 'examples' / 'twenty_turns.json'


def stop_owned_process(proc):
    """Stop only this Popen tree, including the Windows venv redirector child."""
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        result = subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                                capture_output=True, creationflags=NO_WINDOW, timeout=15)
        if result.returncode and proc.poll() is None:
            raise RuntimeError('owned_process_tree_stop_failed')
    else:
        proc.kill()
    proc.wait(timeout=10)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def journal(path, value):
    with open(path, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + '\n')
        handle.flush()
        os.fsync(handle.fileno())


class AuditedTransport(Transport):
    def __init__(self, base, token, log, *, barrier=None):
        super().__init__(base, token, timeout=5)
        self.log, self.barrier = log, barrier

    def request(self, method, path, **kwargs):
        body = kwargs.get('json', {})
        attempt = dict(at=now(), method=method, path=path,
                       sequence_no=body.get('sequence_no'),
                       external_message_id=body.get('external_message_id'))
        journal(self.log, dict(attempt, phase='started'))
        started = time.monotonic()
        try:
            response = super().request(method, path, **kwargs)
        except httpx.HTTPError:
            journal(self.log, dict(attempt, phase='finished', outcome='network_error',
                                   elapsed_seconds=time.monotonic() - started))
            raise
        journal(self.log, dict(attempt, phase='finished', status=response.status_code,
                               elapsed_seconds=time.monotonic() - started))
        if self.barrier and method == 'POST' and body.get('sequence_no') == 7 and response.status_code in (200, 201):
            save(self.barrier, dict(pid=os.getpid(), at=now(), phase='server_committed_before_local_ack',
                                    sequence_no=7, http_status=response.status_code))
            # The parent kills this actual process while Worker still owns sending.
            while True:
                time.sleep(.05)
        return response


def child(args):
    box = Outbox(os.environ['ROBOT_OUTBOX_PATH'], os.environ['ROBOT_BASE_URL'],
                 int(os.environ['ROBOT_OWNER']), upload_policy='after_close')
    token = 'invalid-synthetic-audit-token' if args.child_mode == 'pause' else os.environ['ROBOT_TOKEN']
    transport = AuditedTransport(box.base, token, args.attempts,
                                 barrier=args.ready if args.child_mode == 'response_loss' else None)
    worker = Worker(box, transport, retry_base=.05, retry_cap=.1)
    try:
        if args.child_mode in ('open', 'pause', 'check_pause'):
            processed = worker.step()
            save(args.ready, dict(pid=os.getpid(), at=now(), phase=args.child_mode,
                                  processed=processed, partition=box.partition_status(), status=box.status()))
            while True:
                time.sleep(.05)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            processed = worker.step()
            sealed = [r for r in box.status() if r['local_state'] == 'sealed']
            if sealed and all(r['state'] == 'acked' for r in sealed):
                save(args.ready, dict(pid=os.getpid(), at=now(), phase='drained', status=box.status()))
                return
            if not processed:
                time.sleep(.02)
        raise RuntimeError('worker_timeout')
    finally:
        transport.close()


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@contextmanager
def local_backend(scratch, output, lifecycle):
    port = free_port()
    base = f'http://127.0.0.1:{port}'
    env = dict(os.environ, PYTHONUTF8='1', APP_ENV='test',
               DATABASE_URL='sqlite:///' + (scratch / 'backend.db').as_posix(),
               SECRET_KEY=secrets.token_urlsafe(48), MODELSCOPE_API_KEY='',
               ROBOT_CARE_ASSESSMENT_PROVIDER='disabled', ROBOT_CARE_SIMULATOR_ENABLED='false',
               ROBOT_CARE_ENGINE='rules')
    command = [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
               '--port', str(port), '--log-level', 'warning']
    with open(output / 'twenty_server.log', 'w', encoding='utf-8') as log:
        proc = subprocess.Popen(command, cwd=BACKEND, env=env, stdout=log,
                                stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        lifecycle.append(dict(action='backend_start', pid=proc.pid, at=now(), command=command))
        try:
            with httpx.Client(base_url=base, trust_env=False, timeout=5) as client:
                for _ in range(200):
                    if proc.poll() is not None:
                        raise RuntimeError('local_backend_exited')
                    try:
                        if client.get('/health').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.05)
                else:
                    raise RuntimeError('local_backend_timeout')
                password = secrets.token_urlsafe(24)
                registered = client.post('/api/auth/register', json={
                    'username': 'virtual_twenty_audit', 'password': password})
                registered.raise_for_status()
                signed = client.post('/api/auth/login', json={
                    'username': 'virtual_twenty_audit', 'password': password})
                signed.raise_for_status()
                token = signed.json()['access_token']
            yield base, token
        finally:
            stop_owned_process(proc)
            lifecycle.append(dict(action='backend_stop', pid=proc.pid, at=now(), exit_code=proc.returncode,
                                  stop_method='owned_pid_tree' if os.name == 'nt' else 'owned_pid_kill'))


@contextmanager
def fault_proxy(target, lifecycle):
    """A real HTTP 503, before any upstream write, on the first session POST."""
    class Handler(BaseHTTPRequestHandler):
        fault_remaining = True

        def log_message(self, *args):
            pass

        def do_GET(self):
            self.forward()

        def do_POST(self):
            self.forward()

        def forward(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            if self.command == 'POST' and self.path == '/api/robot-records/sessions' and Handler.fault_remaining:
                Handler.fault_remaining = False
                payload = b'{"error":{"code":"synthetic_unavailable","retryable":true}}'
                self.send_response(503)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Retry-After', '0')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                lifecycle.append(dict(action='proxy_injected_http_503', at=now(),
                                      method=self.command, path=self.path, forwarded=False))
                return
            try:
                with httpx.Client(trust_env=False, timeout=10) as client:
                    response = client.request(self.command, target + self.path,
                                              headers={'Authorization': self.headers.get('Authorization', '')},
                                              content=body)
                self.send_response(response.status_code)
                self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
                self.send_header('Content-Length', str(len(response.content)))
                self.end_headers()
                self.wfile.write(response.content)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def load_manifest():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert manifest['schema_version'] == '1.0' and manifest['is_test'] is True
    for batch in manifest['batches'].values():
        SessionCreate.model_validate(batch['session'])
        records = batch['messages']
        assert len(records) == 40 and [r['sequence_no'] for r in records] == list(range(1, 41))
        assert len({r['external_message_id'] for r in records}) == 40
        turns = {}
        for record in records:
            MessageCreate.model_validate(record)
            assert record['text_status'] == 'completed'
            turns.setdefault(record['turn_id'], set()).add(record['role'])
        assert len(turns) == 20 and all(v == {'user', 'assistant'} for v in turns.values())
    return manifest


def enqueue_batch(box, batch):
    box.create_session(batch['session'])
    external = batch['session']['external_session_id']
    for record in batch['messages']:
        event = {k: v for k, v in record.items() if k != 'sequence_no'}
        assert box.enqueue(external, event) == record['sequence_no']


def statistics(transport, batch, *, phase, started):
    """An ACK is deliberately ignored; only authenticated GET bodies count."""
    owner = transport.request('GET', '/api/auth/me')
    owner.raise_for_status()
    cursor, sessions = None, []
    while True:
        page = transport.request('GET', '/api/robot-records/sessions', params={
            'limit': 100, **({'cursor': cursor} if cursor else {})})
        page.raise_for_status()
        data = page.json()
        sessions.extend(data['items'])
        cursor = data['next_cursor']
        if cursor is None:
            break
    matched = [s for s in sessions if s['external_session_id'] == batch['session']['external_session_id']]
    actual, detail, errors = [], None, []
    if len(matched) == 1:
        sid = matched[0]['recording_session_id']
        response = transport.request('GET', f'/api/robot-records/sessions/{sid}')
        response.raise_for_status()
        detail = response.json()
        cursor = None
        while True:
            response = transport.request('GET', f'/api/robot-records/sessions/{sid}/messages', params={
                'limit': 100, **({'cursor': cursor} if cursor else {})})
            response.raise_for_status()
            page = response.json()
            actual.extend(page['items'])
            cursor = page['next_cursor']
            if cursor is None:
                break
    elif len(matched) > 1:
        errors.append('multiple_matching_sessions')
    expected_ids = {r['external_message_id'] for r in batch['messages']}
    for row in actual:
        if row['external_message_id'] not in expected_ids:
            errors.append('unexpected_external_message_id')
    if len({row['record_id'] for row in actual}) != len(actual):
        errors.append('duplicate_record_id')
    checks, valid = [], set()
    for expected in batch['messages']:
        found = [r for r in actual if r['external_message_id'] == expected['external_message_id']]
        reasons = []
        if len(found) != 1:
            reasons.append('missing' if not found else 'duplicate_external_message_id')
        else:
            row = found[0]
            if sum(r['sequence_no'] == expected['sequence_no'] for r in actual) != 1:
                reasons.append('duplicate_sequence_no')
            normalized = MessageCreate.model_validate(expected).model_dump()
            reasons.extend('field_mismatch:' + k for k, value in normalized.items() if row.get(k) != value)
            if row.get('is_test') is not True:
                reasons.append('is_test_mismatch')
            if detail is None or row.get('recording_session_id') != detail['recording_session_id']:
                reasons.append('session_owner_binding_mismatch')
            if type(row.get('record_id')) is not int or row['record_id'] < 1:
                reasons.append('invalid_record_id')
        if not reasons:
            valid.add(expected['external_message_id'])
        checks.append(dict(external_message_id=expected['external_message_id'], turn_id=expected['turn_id'],
                           sequence_no=expected['sequence_no'], valid=not reasons, reasons=reasons))
    turns = {row['turn_id'] for row in batch['messages']}
    complete = sum(all(r['external_message_id'] in valid for r in batch['messages'] if r['turn_id'] == turn)
                   for turn in turns)
    session_valid = detail is not None and all(detail.get(k) == v for k, v in
                                              SessionCreate.model_validate(batch['session']).model_dump().items())
    if detail and not session_valid:
        errors.append('session_metadata_mismatch')
        valid.clear()
        complete = 0
    return dict(phase=phase, queried_at=now(), authenticated_owner_id=owner.json()['id'],
                external_session_id=batch['session']['external_session_id'],
                record_success=dict(numerator=len(valid), denominator=40, rate=len(valid) / 40),
                complete_turns=dict(numerator=complete, denominator=20, rate=complete / 20),
                actual_unique_record_count=len({r['record_id'] for r in actual}),
                queried_messages=actual,
                session_metadata_valid=session_valid, server_session=detail, checks=checks, errors=errors,
                elapsed_seconds=time.monotonic() - started,
                passed=len(valid) >= 38 and complete >= 19 and not errors)


def wait_barrier(proc, ready):
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        if ready.exists():
            return json.loads(ready.read_text(encoding='utf-8'))
        if proc.poll() is not None:
            raise RuntimeError('audit_worker_exited_before_barrier')
        time.sleep(.02)
    raise RuntimeError('audit_worker_barrier_timeout')


def launch(mode, box, token, output, lifecycle):
    ready = output / ('worker_' + mode + '.json')
    # Each audit output directory is new, so stale ready markers are refused.
    if ready.exists():
        raise RuntimeError('audit_output_already_used')
    attempts = output / ('attempts_' + mode + '.jsonl')
    env = dict(os.environ, PYTHONUTF8='1', PYTHONPATH=str(BACKEND), ROBOT_BASE_URL=box.base,
               ROBOT_OUTBOX_PATH=str(box.path), ROBOT_OWNER=str(box.owner), ROBOT_TOKEN=token,
               ROBOT_UPLOAD_POLICY='after_close')
    command = [sys.executable, str(Path(__file__).resolve()), '--child-mode', mode,
               '--ready', str(ready), '--attempts', str(attempts)]
    log = open(output / ('worker_' + mode + '.log'), 'w', encoding='utf-8')
    proc = subprocess.Popen(command, cwd=BACKEND, env=env, stdout=log,
                            stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    lifecycle.append(dict(action='worker_start', mode=mode, pid=proc.pid, at=now(), command=command))
    try:
        result = wait_barrier(proc, ready)
    except BaseException:
        stop_owned_process(proc)
        log.close()
        raise
    started = next(row for row in reversed(lifecycle)
                   if row['action'] == 'worker_start' and row['pid'] == proc.pid)
    started['runtime_pid'] = result['pid']
    return proc, log, result


def kill(proc, log, mode, lifecycle):
    stop_owned_process(proc)
    log.close()
    runtime_pid = next(row.get('runtime_pid') for row in reversed(lifecycle)
                       if row['action'] == 'worker_start' and row['pid'] == proc.pid)
    lifecycle.append(dict(action='worker_killed', mode=mode, pid=proc.pid, runtime_pid=runtime_pid,
                          at=now(), exit_code=proc.returncode,
                          stop_method='owned_pid_tree' if os.name == 'nt' else 'owned_pid_kill'))


def audit(base, token, scratch, output, lifecycle, manifest):
    started = time.monotonic()
    with httpx.Client(trust_env=False, timeout=5) as client:
        response = client.get(base + '/api/auth/me', headers={'Authorization': 'Bearer ' + token})
        response.raise_for_status()
        owner = response.json()['id']
    normal = manifest['batches']['normal']
    transport = AuditedTransport(base, token, output / 'attempts_normal.jsonl')
    try:
        box = Outbox(scratch / 'normal.db', base, owner, transport=transport, upload_policy='after_close')
        enqueue_batch(box, normal)
        transport.log = output / 'attempts_normal_open.jsonl'
        assert Worker(box, transport).step() is False
        assert not transport.log.exists(), 'Open after_close worker emitted HTTP'
        open_status = box.status()
        assert all(s['waiting_for_close'] and s['attempts'] == 0 for s in open_status)
        save(output / 'normal_open_status.json', open_status)
        assert box.close_session(normal['session']['external_session_id'], normal['ended_at']) == 40
        transport.log = output / 'attempts_normal.jsonl'
        worker = Worker(box, transport)
        for _ in range(45):
            if not worker.step():
                break
        assert all(s['state'] == 'acked' for s in box.status())
        result = statistics(transport, normal, phase='normal_final', started=started)
        assert result['record_success']['numerator'] == 40 and result['complete_turns']['numerator'] == 20
        assert result['server_session']['last_sequence_no'] == 40 and result['server_session']['is_complete']
        save(output / 'normal_final.json', result)
        save(output / 'normal_final_outbox.json', box.status())
    finally:
        transport.close()

    with fault_proxy(base, lifecycle) as proxy:
        fault = manifest['batches']['fault']
        read = Transport(proxy, token)
        try:
            box = Outbox(scratch / 'fault.db', proxy, owner, transport=read, upload_policy='after_close')
            enqueue_batch(box, fault)
            extra = dict(fault['session'], external_session_id='twenty_unclosed_v1')
            box.create_session(extra)
            extra_event = dict(fault['messages'][0], external_message_id='unclosed_msg_1')
            del extra_event['sequence_no']
            assert box.enqueue(extra['external_session_id'], extra_event) == 1
            proc, log, opened = launch('open', box, token, output, lifecycle)
            try:
                assert opened['processed'] is False and all(s['waiting_for_close'] for s in opened['status'])
                assert not (output / 'attempts_open.jsonl').exists()
            finally:
                kill(proc, log, 'open', lifecycle)
            # Reopen the same durable outbox, never reconstruct its manifest in memory.
            box = Outbox(box.path, proxy, owner, upload_policy='after_close')
            assert all(s['local_state'] == 'open' and s['attempts'] == 0 for s in box.status())
            assert box.close_session(fault['session']['external_session_id'], fault['ended_at']) == 40
            proc, log, paused = launch('pause', box, token, output, lifecycle)
            try:
                assert paused['partition']['auth_blocked'] is True
                assert all(s['partition_auth_blocked'] for s in paused['status'])
            finally:
                kill(proc, log, 'pause', lifecycle)
            proc, log, still_paused = launch('check_pause', box, token, output, lifecycle)
            try:
                assert still_paused['processed'] is False and still_paused['partition']['auth_blocked'] is True
                assert not (output / 'attempts_check_pause.jsonl').exists()
            finally:
                kill(proc, log, 'check_pause', lifecycle)
            extra_event['external_message_id'] = 'unclosed_msg_2'
            assert box.enqueue(extra['external_session_id'], extra_event) == 2
            assert box.status()[-1]['state'] == 'blocked_auth'
            box.resume()
            proc, log, committed = launch('response_loss', box, token, output, lifecycle)
            try:
                before = statistics(read, fault, phase='fault_before_recovery', started=started)
                assert 0 < before['record_success']['numerator'] < 40
                save(output / 'fault_before_recovery.json', before)
                save(output / 'fault_before_outbox.json', box.status())
                assert any(s['state'] == 'sending' and s['sequence'] == 7 for s in box.status())
            finally:
                kill(proc, log, 'response_loss', lifecycle)
            proc, log, recovered = launch('recover', box, token, output, lifecycle)
            try:
                proc.wait(timeout=10)
                assert proc.returncode == 0 and recovered['phase'] == 'drained'
                lifecycle.append(dict(action='worker_completed', mode='recover', pid=proc.pid,
                                      at=now(), exit_code=proc.returncode))
            finally:
                if proc.poll() is None:
                    stop_owned_process(proc)
                log.close()
            after = statistics(read, fault, phase='fault_after_recovery', started=started)
            assert after['record_success']['numerator'] == 40 and after['complete_turns']['numerator'] == 20
            assert after['server_session']['last_sequence_no'] == 40 and after['server_session']['is_complete']
            save(output / 'fault_after_recovery.json', after)
            final_status = box.status()
            save(output / 'fault_final_outbox.json', final_status)
            opened = [s for s in final_status if s['external'] == extra['external_session_id']]
            assert all(s['waiting_for_close'] and s['attempts'] == 0 and s['next_sequence'] == 3 for s in opened)
            messages = [s for s in final_status if s['external'] == fault['session']['external_session_id'] and s['kind'] == 'message']
            assert [s['sequence'] for s in messages] == list(range(1, 41))
            assert next(s for s in messages if s['sequence'] == 7)['attempts'] == 2
            first = next(s for s in final_status if s['kind'] == 'session' and s['external'] == fault['session']['external_session_id'])
            assert first['attempts'] == 3  # identity pause + actual 503 + successful creation
        finally:
            read.close()
    return dict(schema_version='1.0', synthetic_only=True, upload_policy='after_close',
                fixed_record_denominator=40, fixed_turn_denominator=20,
                normal=result, fault_before=before, fault_after=after,
                unclosed_session_retained=True, identity_pause_survived_restart=True,
                duplicate_post_did_not_duplicate_record=True,
                elapsed_seconds=time.monotonic() - started, runtime_databases_exported=False,
                model_endpoints_called=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', '--output', type=Path)
    parser.add_argument('--base-url', default=os.getenv('ROBOT_BASE_URL'))
    parser.add_argument('--child-mode', choices=('open', 'pause', 'check_pause', 'response_loss', 'recover'))
    parser.add_argument('--ready', type=Path)
    parser.add_argument('--attempts', type=Path)
    args = parser.parse_args()
    if args.child_mode:
        child(args)
        return
    if not args.output_dir:
        parser.error('--output-dir is required')
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'twenty_summary.json').exists():
        parser.error('Use a new output directory to preserve prior audit evidence')
    manifest = load_manifest()
    save(output / 'fixed_manifest.json', manifest)
    lifecycle = []
    try:
        with tempfile.TemporaryDirectory(prefix='module236-twenty-') as runtime:
            scratch = Path(runtime)
            if args.base_url:
                token = os.getenv('ROBOT_TOKEN')
                if not token:
                    parser.error('ROBOT_TOKEN is required with --base-url')
                summary = audit(args.base_url.rstrip('/'), token, scratch, output, lifecycle, manifest)
            else:
                with local_backend(scratch, output, lifecycle) as (base, token):
                    summary = audit(base, token, scratch, output, lifecycle, manifest)
        summary['environment'] = dict(python_executable=sys.executable, python=sys.version)
        save(output / 'twenty_summary.json', summary)
        print(json.dumps(dict(result='passed', records='40/40', complete_turns='20/20',
                              fault_recovered_records='40/40', output=str(output)), ensure_ascii=False))
    finally:
        save(output / 'process_lifecycle.json', lifecycle)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Exclude request bodies, tokens, transport objects and internal tracebacks.
        print(json.dumps({'error': {'code': 'twenty_audit_failed', 'type': type(error).__name__}}), file=sys.stderr)
        raise SystemExit(1)
