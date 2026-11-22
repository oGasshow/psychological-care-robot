"""Reuse the existing durable Outbox; HTTP is kept off audio/event callbacks."""
import os
from pathlib import Path
import time
import threading
import uuid
from sqlalchemy.engine import make_url
from robot_client import Outbox, Transport, Worker
from .transcripts import utc_now
from ..deployment import edge
REMOTE_PENDING = {}
REMOTE_PENDING_LOCK = threading.RLock()

def directory(uid):
    if edge():
        raise RuntimeError('local_business_spool_disabled_in_edge_mode')
    from ..config import DATABASE_URL
    database=make_url(DATABASE_URL).database
    parent=Path(database).resolve().parent if database and database!=':memory:' else Path(__file__).resolve().parents[3]/'runtime'
    root=Path(os.getenv('ROBOT_CARE_VOICE_OUTBOX_DIR',str(parent/'voice_outbox'))).resolve()/f'user_{uid}'
    root.mkdir(parents=True,exist_ok=True)
    return root

def internal_base(scope):
    explicit=os.getenv('ROBOT_CARE_VOICE_RECORD_BASE_URL')
    if explicit:return explicit
    server=scope.get('server')
    if not server:raise ValueError('voice_internal_api_unavailable')
    host,port=server
    if host in ('0.0.0.0','::'):host='127.0.0.1'
    if ':' in host:host='['+host+']'
    return f'http://{host}:{port}'

class DurableRecorder:
    def __init__(self,uid,token,base,*,is_test,device_id='voice_bridge'):
        self.external='voice_'+uuid.uuid4().hex
        self.transport=Transport(base,token,timeout=3)
        self.box=Outbox(directory(uid)/(self.external+'.sqlite'),base,uid,transport=self.transport,upload_policy='after_close')
        self.box.create_session(dict(source='doubao_realtime',device_id=device_id,external_session_id=self.external,
                                     started_at=utc_now(),is_test=is_test))
        self.closed=False
        self.io_lock=threading.RLock()

    def enqueue(self,entry):
        if not entry.recorded and entry.text.strip():
            self.box.enqueue(self.external,entry.wire())
            entry.recorded=True

    def sync_partial(self,seconds=3.5):
        """Upload one coalesced checkpoint; serialize with final close/retries."""
        with self.io_lock:
            if self.closed:return dict(type='records.pending',recording_session_id=None,pending=1)
            previous=self.box.upload_policy;self.box.upload_policy='streaming'
            try:
                result=flush(self.box,self.transport,self.external,seconds=seconds)
                result['upload_policy']='same_session_checkpoint';return result
            finally:self.box.upload_policy=previous

    def finish(self):
        with self.io_lock:
            if not self.closed:self.box.close_session(self.external,utc_now());self.closed=True
            try:return flush(self.box,self.transport,self.external)
            finally:self.transport.close()


def flush(box,transport,external=None,seconds=8):
    worker=Worker(box,transport,retry_base=.3,retry_cap=2)
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        rows=[r for r in box.status() if external is None or r['external']==external]
        if rows and all(r['state']=='acked' for r in rows):break
        if any(r['state'] in ('dead_letter','blocked_auth','paused_retry') for r in rows):break
        if not worker.step():time.sleep(.12)
    rows=[r for r in box.status() if external is None or r['external']==external]
    saved=bool(rows) and all(r['state']=='acked' for r in rows)
    sid=next((r['server_id'] for r in rows if r['server_id']),None)
    return dict(type='records.saved' if saved else 'records.pending',recording_session_id=sid,
                pending=sum(r['state']!='acked' for r in rows),upload_policy='after_close')

def retry(uid,token,base,paths=None):
    if edge():
        with REMOTE_PENDING_LOCK:
            pending=list(REMOTE_PENDING.get(uid,[]))
        results=[]
        for recorder in pending:
            recorder.transport=Transport(base,token,timeout=6)
            results.append(recorder.finish())
        return dict(items=results,pending=sum(r['pending'] for r in results),storage='server')
    results=[]
    with_transport=Transport(base,token,timeout=3)
    try:
        for path in paths if paths is not None else directory(uid).glob('voice_*.sqlite'):
            box=Outbox(path,base,uid,transport=with_transport,upload_policy='after_close')
            # A process restart may have left an open local session. Seal its
            # already durable final texts before retrying; no old audio is resumed.
            with box.db() as db:
                opened=[r['external'] for r in db.execute("SELECT external FROM sessions WHERE base=? AND owner=? AND state='open'",(box.base,uid))]
            for external in opened:box.close_session(external,utc_now())
            if any(r['state']=='blocked_auth' for r in box.status()):box.resume()
            result=flush(box,with_transport)
            results.append(result)
    finally:with_transport.close()
    return dict(items=results,pending=sum(r['pending'] for r in results))


class ServerRecorder:
    """No local disk spool. ACKs mean a committed write to the shared server DB."""
    persistent_local = False

    def __init__(self, uid, token, base, *, is_test, device_id='voice_bridge'):
        self.external='voice_'+uuid.uuid4().hex
        self.transport=Transport(base,token,timeout=6)
        self.io_lock=threading.RLock();self.closed=False;self.pending=[];self.sequence=0
        self.uid=uid;self.ended_at=None
        try:
            response=self.transport.request('POST','/api/robot-records/sessions',json=dict(
                source='doubao_realtime',device_id=device_id,external_session_id=self.external,
                started_at=utc_now(),is_test=is_test))
            response.raise_for_status();self.sid=response.json()['recording_session_id']
        except BaseException:
            self.transport.close();raise

    def enqueue(self, entry):
        with self.io_lock:
            if entry.recorded or not entry.text.strip():return
            self.sequence+=1
            self.pending.append(dict(sequence_no=self.sequence,**entry.wire()))
            entry.recorded=True
            self._flush()

    def _flush(self):
        while self.pending:
            try:
                response=self.transport.request('POST',f'/api/robot-records/sessions/{self.sid}/messages',json=self.pending[0])
                response.raise_for_status()
            except Exception:
                return False
            self.pending.pop(0)
        return True

    def sync_partial(self, seconds=3.5):
        with self.io_lock:
            saved=self._flush()
            return dict(type='records.saved' if saved else 'records.pending',
                recording_session_id=self.sid if saved else None,pending=len(self.pending),
                upload_policy='server_only',storage='server')

    def finish(self):
        with self.io_lock:
            if self.closed:return dict(type='records.saved',recording_session_id=self.sid,pending=0,storage='server')
            if self.ended_at is None:self.ended_at=utc_now()
            result=None
            try:
                if not self._flush():
                    result=dict(type='records.pending',recording_session_id=self.sid,pending=len(self.pending),storage='server')
                    return result
                response=self.transport.request('POST',f'/api/robot-records/sessions/{self.sid}/close',json=dict(
                    ended_at=self.ended_at,last_sequence_no=self.sequence))
                response.raise_for_status();self.closed=True
                result=dict(type='records.saved',recording_session_id=self.sid,pending=0,storage='server')
                return result
            except Exception:
                result=dict(type='records.pending',recording_session_id=self.sid,pending=max(1,len(self.pending)),storage='server')
                return result
            finally:
                self.transport.close()
                with REMOTE_PENDING_LOCK:
                    rows=REMOTE_PENDING.setdefault(self.uid,[])
                    if result and result['type']=='records.pending' and self not in rows:rows.append(self)
                    if self.closed and self in rows:rows.remove(self)


def Recorder(*args, **kwargs):
    return (ServerRecorder if edge() else DurableRecorder)(*args, **kwargs)
