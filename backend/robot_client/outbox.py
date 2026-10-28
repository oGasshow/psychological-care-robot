"""Durable, partitioned SQLite outbox with a single cross-process worker lease.

Credentials live only in Transport. Task payloads are immutable and cleared after
verified ACKs. Session mapping/high-water marks survive payload cleanup.
"""
import asyncio
import hashlib
import json
import random
import sqlite3
import time
from contextlib import contextmanager, closing
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

# Schemas have no backend side effects when config/database is not imported.
from .schemas import SessionCreate, MessageCreate, SessionClose, utc, validate_body
from .errors import OutboxError

SCHEMA_VERSION = 1

def upgrade_schema(db):
    """Run under BEGIN IMMEDIATE: transactional, additive v0 -> v1 upgrade."""
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > SCHEMA_VERSION:
        raise OutboxError('unsupported_outbox_schema')
    for statement in (
        '''CREATE TABLE IF NOT EXISTS targets (
          base TEXT NOT NULL, owner INTEGER NOT NULL, PRIMARY KEY(base,owner))''',
        '''CREATE TABLE IF NOT EXISTS sessions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, base TEXT NOT NULL, owner INTEGER NOT NULL,
          external TEXT NOT NULL, source TEXT NOT NULL, create_hash TEXT,
          next_sequence INTEGER NOT NULL DEFAULT 1, server_id INTEGER,
          state TEXT NOT NULL DEFAULT 'open', last_sequence INTEGER, close_hash TEXT,
          UNIQUE(base,owner,source,external), FOREIGN KEY(base,owner) REFERENCES targets(base,owner))''',
        '''CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY AUTOINCREMENT, session INTEGER NOT NULL REFERENCES sessions(id),
          kind TEXT NOT NULL, stable_id TEXT NOT NULL, sequence INTEGER,
          payload TEXT, digest TEXT, state TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0, transient_count INTEGER NOT NULL DEFAULT 0,
          next_at REAL NOT NULL DEFAULT 0, last_error TEXT, receipt TEXT,
          UNIQUE(session,kind,stable_id))''',
    ):
        db.execute(statement)
    columns = {row[1] for row in db.execute('PRAGMA table_info(targets)')}
    if 'auth_blocked' not in columns:
        db.execute('ALTER TABLE targets ADD COLUMN auth_blocked INTEGER NOT NULL DEFAULT 0')
    if 'auth_error' not in columns:
        db.execute('ALTER TABLE targets ADD COLUMN auth_error TEXT')
    if version < SCHEMA_VERSION:
        # Preserve legacy tasks verbatim; infer the partition barrier from old failures.
        db.execute("""UPDATE targets SET auth_blocked=1,auth_error='legacy_blocked_auth'
          WHERE EXISTS (SELECT 1 FROM sessions s JOIN tasks t ON s.id=t.session
            WHERE s.base=targets.base AND s.owner=targets.owner AND t.state='blocked_auth')""")
        db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def fingerprint(data):
    return hashlib.sha256(canonical(data).encode()).hexdigest()

def normalize_base(value):
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise OutboxError('invalid_base_url')
    host = parsed.hostname.lower().encode('idna').decode()
    if ':' in host:
        host = '[' + host + ']'
    port = parsed.port
    if port and (parsed.scheme.lower(), port) not in (('http', 80), ('https', 443)):
        host += ':' + str(port)
    return urlunsplit((parsed.scheme.lower(), host, parsed.path.rstrip('/'), '', ''))

class Transport:
    def __init__(self, base_url, token, timeout=5):
        self.base_url = normalize_base(base_url)
        self.token = token
        self.http = httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False)

    def request(self, method, path, **kwargs):
        return self.http.request(method, self.base_url + path,
                                 headers={'Authorization': 'Bearer ' + self.token}, **kwargs)

    def close(self):
        self.http.close()

def verified_owner(transport):
    try:
        response = transport.request('GET', '/api/auth/me')
        if response.status_code in (401, 403):
            raise OutboxError('blocked_auth')
        response.raise_for_status()
        uid = response.json()['id']
        if type(uid) is not int or uid < 1:
            raise ValueError()
        return uid
    except (ValueError, KeyError, TypeError):
        raise OutboxError('identity_protocol_error') from None

class Outbox:
    def __init__(self, path, base_url, owner_user_id, *, transport=None, capacity=10000,
                 upload_policy='streaming'):
        if type(owner_user_id) is not int or owner_user_id < 1 or capacity < 1:
            raise OutboxError('invalid_configuration')
        if upload_policy not in ('streaming', 'after_close'):
            raise OutboxError('invalid_upload_policy')
        self.path = Path(path).resolve()
        self.base = normalize_base(base_url)
        self.owner = owner_user_id
        self.capacity = capacity
        self.upload_policy = upload_policy
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.write() as db:
                upgrade_schema(db)
            with self.db() as db:
                exists = db.execute('SELECT 1 FROM targets WHERE base=? AND owner=?', (self.base, self.owner)).fetchone()
                if not exists:
                    if transport is None or normalize_base(transport.base_url) != self.base or verified_owner(transport) != self.owner:
                        raise OutboxError('identity_unverified')
                    db.execute('INSERT OR IGNORE INTO targets(base,owner) VALUES (?,?)', (self.base, self.owner))
        except sqlite3.Error:
            raise OutboxError('local_storage_error') from None

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA secure_delete=ON')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def write(self):
        try:
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                yield db
        except sqlite3.Error:
            raise OutboxError('local_storage_error') from None

    @staticmethod
    def upgrade(path):
        """Explicit offline upgrade; refuse to silently create an absent old file."""
        path = Path(path).resolve()
        if not path.is_file():
            raise OutboxError('outbox_not_found')
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=2)) as db:
                with db:
                    db.execute('PRAGMA foreign_keys=ON')
                    db.execute('BEGIN IMMEDIATE')
                    upgrade_schema(db)
        except sqlite3.Error:
            raise OutboxError('local_storage_error') from None
        return SCHEMA_VERSION

    def _partition(self, db):
        return db.execute('SELECT auth_blocked,auth_error FROM targets WHERE base=? AND owner=?',
                          (self.base, self.owner)).fetchone()

    def partition_status(self):
        with self.db() as db:
            row = self._partition(db)
            return dict(auth_blocked=bool(row['auth_blocked']), auth_error=row['auth_error'],
                        schema_version=db.execute('PRAGMA user_version').fetchone()[0])

    def _new_task_state(self, db):
        row = self._partition(db)
        return ('blocked_auth', row['auth_error']) if row['auth_blocked'] else ('pending', None)

    def session(self, db, external):
        row = db.execute('SELECT * FROM sessions WHERE base=? AND owner=? AND source=? AND external=?',
                         (self.base, self.owner, 'doubao_realtime', external)).fetchone()
        if row is None:
            raise OutboxError('unknown_session')
        if row['state'] == 'deleted':
            raise OutboxError('session_deleted')
        return row

    def room(self, db):
        if db.execute("SELECT count(*) FROM tasks WHERE state!='acked'").fetchone()[0] >= self.capacity:
            raise OutboxError('queue_full')

    def create_session(self, body):
        data = validate_body(SessionCreate, body).model_dump()
        digest = fingerprint(data)
        with self.write() as db:
            row = db.execute('SELECT * FROM sessions WHERE base=? AND owner=? AND source=? AND external=?',
                             (self.base, self.owner, data['source'], data['external_session_id'])).fetchone()
            if row:
                if row['state'] == 'deleted':
                    raise OutboxError('session_deleted')
                if row['create_hash'] != digest:
                    raise OutboxError('session_conflict')
                return row['id']
            self.room(db)
            sid = db.execute('INSERT INTO sessions(base,owner,external,source,create_hash) VALUES (?,?,?,?,?)',
                             (self.base, self.owner, data['external_session_id'], data['source'], digest)).lastrowid
            db.execute("INSERT INTO tasks(session,kind,stable_id,payload,digest,state,last_error) VALUES (?,'session',?,?,?,?,?)",
                       (sid, data['external_session_id'], canonical(data), digest, *self._new_task_state(db)))
        return sid

    def enqueue(self, external, event):
        # Serial number allocation, validation and durable insert share one transaction.
        if 'sequence_no' in event:
            raise OutboxError('sequence_allocated_by_outbox')
        with self.write() as db:
            row = self.session(db, external)
            old = db.execute("SELECT * FROM tasks WHERE session=? AND kind='message' AND stable_id=?",
                             (row['id'], event.get('external_message_id'))).fetchone()
            sequence = old['sequence'] if old else row['next_sequence']
            data = validate_body(MessageCreate, dict(event, sequence_no=sequence)).model_dump()
            digest = fingerprint(data)
            if old:
                if old['digest'] != digest:
                    raise OutboxError('message_conflict')
                return sequence
            if row['state'] != 'open':
                raise OutboxError('session_sealed')
            self.room(db)
            db.execute("INSERT INTO tasks(session,kind,stable_id,sequence,payload,digest,state,last_error) VALUES (?,'message',?,?,?,?,?,?)",
                       (row['id'], data['external_message_id'], sequence, canonical(data), digest, *self._new_task_state(db)))
            db.execute('UPDATE sessions SET next_sequence=? WHERE id=?', (sequence + 1, row['id']))
        return sequence

    async def enqueue_async(self, external, event):
        # Only call this from a scheduled TEXT task; an audio callback schedules it.
        return await asyncio.to_thread(self.enqueue, external, event)

    def close_session(self, external, ended_at):
        with self.write() as db:
            row = self.session(db, external)
            data = validate_body(SessionClose, dict(ended_at=ended_at, last_sequence_no=row['next_sequence'] - 1)).model_dump()
            digest = fingerprint(data)
            if row['state'] == 'sealed':
                if row['close_hash'] != digest:
                    raise OutboxError('close_conflict')
                return data['last_sequence_no']
            self.room(db)
            db.execute("UPDATE sessions SET state='sealed',last_sequence=?,close_hash=? WHERE id=?",
                       (data['last_sequence_no'], digest, row['id']))
            db.execute("INSERT INTO tasks(session,kind,stable_id,payload,digest,state,last_error) VALUES (?,'close',?,?,?,?,?)",
                       (row['id'], external, canonical(data), digest, *self._new_task_state(db)))
        return data['last_sequence_no']

    def _purge(self, db, sid):
        db.execute("UPDATE tasks SET payload=NULL,digest=NULL,receipt=NULL,state='acked',last_error='session_deleted',next_at=0 WHERE session=?", (sid,))
        db.execute("UPDATE sessions SET state='deleted',create_hash=NULL,close_hash=NULL WHERE id=?", (sid,))

    def purge(self, external):
        with self.write() as db:
            row = db.execute('SELECT id FROM sessions WHERE base=? AND owner=? AND external=?',
                             (self.base, self.owner, external)).fetchone()
            if row:
                self._purge(db, row['id'])

    def status(self):
        # Do not expose stored message bodies or credentials through default status.
        with self.db() as db:
            rows = [dict(r) for r in db.execute('''SELECT t.id,s.external,t.kind,t.sequence,t.state,
              t.attempts,t.transient_count,t.next_at,t.last_error,t.receipt,s.server_id,s.next_sequence,s.state AS local_state,
              p.auth_blocked AS partition_auth_blocked,p.auth_error AS partition_auth_error
              FROM tasks t JOIN sessions s ON s.id=t.session JOIN targets p ON p.base=s.base AND p.owner=s.owner
              WHERE s.base=? AND s.owner=? ORDER BY t.id''', (self.base, self.owner))]
        for row in rows:
            waiting = self.upload_policy == 'after_close' and row['local_state'] == 'open' and row['state'] != 'acked'
            row.update(upload_policy=self.upload_policy, waiting_for_close=waiting,
                       display_status=('身份暂停' if row['partition_auth_blocked'] else
                                       '等待会话结束' if waiting else row['state']))
        return rows

    def resume(self, *, include_dead=False):
        # Explicit operator action, never silently rewrites immutable payloads/IDs.
        states = ['blocked_auth', 'paused_retry'] + (['dead_letter'] if include_dead else [])
        with self.write() as db:
            db.execute('UPDATE targets SET auth_blocked=0,auth_error=NULL WHERE base=? AND owner=?',
                       (self.base, self.owner))
            db.execute(f'''UPDATE tasks SET state='pending',transient_count=0,next_at=0
              WHERE state IN ({','.join('?' for _ in states)}) AND payload IS NOT NULL
              AND session IN (SELECT id FROM sessions WHERE base=? AND owner=? AND state!='deleted')''',
                       (*states, self.base, self.owner))

    @contextmanager
    def lease(self):
        # An OS lock is released on crash; no timeout guesses can steal a live worker.
        handle = open(str(self.path) + '.worker.lock', 'a+b')
        try:
            handle.seek(0)
            if handle.read(1) == b'':
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            try:
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                unlock = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except ImportError:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                unlock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                raise OutboxError('worker_already_running') from None
            try:
                yield
            finally:
                handle.seek(0)
                unlock()
        finally:
            handle.close()

def retry_after(value, current):
    if value is None:
        return 0
    try:
        if value.strip().isdigit():
            return current + int(value.strip())
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(current, parsed.timestamp())
    except (ValueError, TypeError, OverflowError):
        return 0

class Worker:
    def __init__(self, outbox, transport, *, clock=time.time, rng=random.random,
                 retry_base=1, retry_cap=60, max_transient=8):
        if max_transient < 1 or retry_base < 0 or retry_cap < 0:
            raise OutboxError('invalid_configuration')
        self.outbox, self.transport = outbox, transport
        self.clock, self.rng = clock, rng
        self.retry_base, self.retry_cap, self.max_transient = retry_base, retry_cap, max_transient

    def _set_failure(self, task, state, code, next_at=0, transient=0):
        with self.outbox.write() as db:
            if state == 'blocked_auth':
                db.execute('UPDATE targets SET auth_blocked=1,auth_error=? WHERE base=? AND owner=?',
                           (code, self.outbox.base, self.outbox.owner))
                db.execute("""UPDATE tasks SET state='blocked_auth',last_error=? WHERE state IN ('pending','sending','retry_wait','paused_retry')
                  AND session IN (SELECT id FROM sessions WHERE base=? AND owner=? AND state!='deleted')""",
                           (code, self.outbox.base, self.outbox.owner))
            else:
                db.execute('''UPDATE tasks SET state=?,last_error=?,next_at=?,transient_count=?
                  WHERE id=? AND state='sending' ''', (state, code, next_at, transient, task['id']))

    def _retry(self, task, code, header=None):
        n = task['transient_count'] + 1
        delay = min(self.retry_cap, self.retry_base * 2 ** min(n - 1, 30)) * (0.8 + 0.2 * self.rng())
        at = max(self.clock() + delay, retry_after(header, self.clock()))
        self._set_failure(task, 'paused_retry' if n >= self.max_transient else 'retry_wait', code, at, n)

    def step(self):
        box = self.outbox
        with box.lease():
            with box.write() as db:
                if box._partition(db)['auth_blocked']:
                    return False
                db.execute("""UPDATE tasks SET state='pending' WHERE state='sending'
                  AND session IN (SELECT id FROM sessions WHERE base=? AND owner=?)""", (box.base, box.owner))
                task = db.execute("""SELECT t.*,s.server_id,s.external FROM tasks t JOIN sessions s ON s.id=t.session
                  WHERE s.base=? AND s.owner=? AND s.state!='deleted' AND t.state IN ('pending','retry_wait')
                  AND t.next_at<=? AND (t.kind='session' OR s.server_id IS NOT NULL)
                  AND (?='streaming' OR (s.state='sealed' AND (t.kind!='close' OR NOT EXISTS (
                    SELECT 1 FROM tasks m WHERE m.session=s.id AND m.kind='message' AND m.state!='acked'))))
                  ORDER BY t.id LIMIT 1""",
                                  (box.base, box.owner, self.clock(), box.upload_policy)).fetchone()
                if task is None:
                    return False
                task = dict(task)
                db.execute("UPDATE tasks SET state='sending',attempts=attempts+1 WHERE id=?", (task['id'],))
            try:
                if normalize_base(self.transport.base_url) != box.base:
                    self._set_failure(task, 'blocked_auth', 'target_mismatch')
                    return True
                if verified_owner(self.transport) != box.owner:
                    self._set_failure(task, 'blocked_auth', 'owner_mismatch')
                    return True
                payload = json.loads(task['payload'])
                root = '/api/robot-records/sessions'
                path = root if task['kind'] == 'session' else f"{root}/{task['server_id']}/" + ('messages' if task['kind'] == 'message' else 'close')
                response = self.transport.request('POST', path, json=payload)
                code = response.status_code
                if code in (401, 403):
                    self._set_failure(task, 'blocked_auth', f'http_{code}')
                elif code == 410:
                    try:
                        deleted = response.json()['error']['code'] == 'session_deleted'
                    except (ValueError, KeyError, TypeError):
                        deleted = False
                    if deleted:
                        with box.write() as db:
                            box._purge(db, task['session'])
                    else:
                        self._set_failure(task, 'dead_letter', 'protocol_error')
                elif code == 429 or code >= 500:
                    self._retry(task, f'http_{code}', response.headers.get('Retry-After'))
                elif code in (200, 201):
                    self._ack(task, payload, response)
                else:
                    self._set_failure(task, 'dead_letter', f'http_{code}')
            except OutboxError as exc:
                if exc.code == 'blocked_auth':
                    self._set_failure(task, 'blocked_auth', 'authentication_failed')
                elif exc.code == 'identity_protocol_error':
                    self._set_failure(task, 'dead_letter', exc.code)
                else:
                    raise
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429 or status >= 500:
                    self._retry(task, f'identity_http_{status}', exc.response.headers.get('Retry-After'))
                else:
                    self._set_failure(task, 'dead_letter', f'identity_http_{status}')
            except httpx.RequestError:
                self._retry(task, 'network_error')
            return True

    def _ack(self, task, payload, response):
        try:
            data = response.json()
            sid = data['recording_session_id']
            if type(sid) is not int or sid < 1 or (task['server_id'] is not None and sid != task['server_id']):
                raise ValueError()
            receipt = {'recording_session_id': sid}
            if task['kind'] == 'session':
                if data.get('state') not in ('open', 'closed') or any(data.get(k) != v for k, v in payload.items()):
                    raise ValueError()
            elif task['kind'] == 'message':
                if data['external_message_id'] != payload['external_message_id'] or type(data['sequence_no']) is not int or data['sequence_no'] != payload['sequence_no']:
                    raise ValueError()
                if type(data['record_id']) is not int or data['record_id'] < 1:
                    raise ValueError()
                receipt.update(record_id=data['record_id'], received_at=utc(data['received_at']))
                for key, value in payload.items():
                    if key in data and data[key] != value:
                        raise ValueError()
            else:
                if response.status_code != 200 or data['state'] != 'closed' or utc(data['ended_at']) != payload['ended_at'] or type(data['last_sequence_no']) is not int or data['last_sequence_no'] != payload['last_sequence_no'] or type(data['is_complete']) is not bool:
                    raise ValueError()
                receipt.update(ended_at=payload['ended_at'], last_sequence_no=payload['last_sequence_no'])
            if task['kind'] != 'close' and (type(data.get('duplicate')) is not bool or data['duplicate'] != (response.status_code == 200)):
                raise ValueError()
        except (ValueError, KeyError, TypeError, AttributeError):
            self._set_failure(task, 'dead_letter', 'protocol_error')
            return
        with self.outbox.write() as db:
            # purge may run concurrently while HTTP is in flight; it wins.
            current = db.execute('SELECT state FROM sessions WHERE id=?', (task['session'],)).fetchone()
            if current['state'] == 'deleted':
                return
            if task['kind'] == 'session':
                db.execute('UPDATE sessions SET server_id=? WHERE id=?', (sid, task['session']))
            db.execute("UPDATE tasks SET state='acked',payload=NULL,receipt=?,last_error=NULL,next_at=0,transient_count=0 WHERE id=?",
                       (canonical(receipt), task['id']))

    def run(self, stop_event):
        while not stop_event.is_set():
            if not self.step():
                stop_event.wait(0.2)
