import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import format_datetime
import json
import sqlite3
import threading
import time

import httpx
import pytest

from robot_client import Outbox, OutboxError, Worker
from robot_client.outbox import normalize_base
from conftest import session_body, message_body

class LocalTransport:
    def __init__(self, api, base='http://local.test'):
        self.api, self.base_url = api, base
        self.calls = []
        self.fault = None

    def request(self, method, path, **kwargs):
        self.calls.append((method,path))
        if self.fault:
            result = self.fault(method,path,kwargs)
            if result is not None:
                return result
        return self.api.request(method,path,**kwargs)

def event(seq=1, **kwargs):
    data = message_body(seq,**kwargs)
    del data['sequence_no']
    return data

def make_box(tmp_path, api, **kwargs):
    transport = LocalTransport(api)
    box = Outbox(tmp_path / 'outbox.db', transport.base_url, api.uid, transport=transport, **kwargs)
    return box, transport

def drain(worker, maximum=40):
    for _ in range(maximum):
        if not worker.step():
            return
    raise AssertionError('Worker did not drain')

def response(status, data=None, headers=None):
    return httpx.Response(status, json=data or {}, headers=headers or {}, request=httpx.Request('POST','http://local.test/test'))

def test_A21_persistent_retry_schedule(actors,tmp_path,trace):
    a,_=actors
    box,t=make_box(tmp_path,a)
    box.create_session(session_body())
    clock=[1800000000.0]
    failures=[httpx.ConnectError('fictional unreachable'),httpx.ReadTimeout('fictional timeout'),
              response(429,headers={'Retry-After':'120'}),response(503),
              response(429,headers={'Retry-After':format_datetime(datetime.fromtimestamp(clock[0]+500,timezone.utc),usegmt=True)})]
    def fail(method,path,kwargs):
        if method=='POST' and failures:
            result=failures.pop(0)
            if isinstance(result,Exception):
                raise result
            return result
    t.fault=fail
    worker=Worker(box,t,clock=lambda:clock[0],rng=lambda:1)
    for n in range(5):
        before=clock[0]
        assert worker.step()
        state=box.status()[0]
        assert state['state']=='retry_wait' and state['attempts']==n+1
        if n==2:
            assert state['next_at'] >= before+120
        if n==4:
            assert state['next_at'] >= 1800000500
        assert worker.step() is False
        trace.append({'attempt':n+1,'schedule':state,'clock':clock[0]})
        clock[0]=state['next_at']+0.001
    reopened=Outbox(box.path,box.base,box.owner)
    assert reopened.status()[0]['attempts']==5
    drain(Worker(reopened,t,clock=lambda:clock[0]))
    assert reopened.status()[0]['state']=='acked'
    sid=reopened.status()[0]['server_id']
    assert a.detail(sid).status_code==200

def test_A23_identity_and_target_partition(actors,tmp_path,trace):
    a,b=actors
    box,t=make_box(tmp_path,a)
    box.create_session(session_body())
    box.enqueue('virtual_session',event())
    wrong=LocalTransport(b)
    worker=Worker(box,wrong)
    assert worker.step()
    assert all(s['state']=='blocked_auth' for s in box.status())
    assert not any(m=='POST' for m,_ in wrong.calls)
    box.resume()
    second=LocalTransport(a,'https://second.test')
    assert Worker(box,second).step()
    assert all(s['last_error']=='target_mismatch' for s in box.status())
    assert second.calls==[]
    box.resume()
    t.fault=lambda method,path,kwargs: response(401) if path=='/api/auth/me' else None
    assert Worker(box,t).step()
    assert all(s['state']=='blocked_auth' for s in box.status())
    box.resume()
    t.fault=lambda method,path,kwargs: response(403) if method=='POST' else None
    assert Worker(box,t).step()
    assert all(s['state']=='blocked_auth' for s in box.status())
    trace.append({'before_recovery':box.status()})
    t.fault=None
    box.resume()
    drain(Worker(box,t))
    assert all(s['state']=='acked' for s in box.status())
    otherbox=Outbox(box.path,second.base_url,a.uid,transport=second)
    assert otherbox.status()==[]
    otherbox.create_session(session_body('other_server'))
    assert Worker(otherbox,second).step()
    assert otherbox.status()[0]['state']=='acked'
    assert normalize_base('HTTP://LOCAL.TEST:80/') == 'http://local.test'

@pytest.mark.parametrize('status',[404,409,422])
def test_A24_dead_letters(actors,tmp_path,status,trace):
    a,_=actors
    box,t=make_box(tmp_path,a)
    box.create_session(session_body())
    t.fault=lambda method,path,kwargs: response(status) if method=='POST' else None
    worker=Worker(box,t)
    assert worker.step()
    assert box.status()[0]['state']=='dead_letter'
    assert box.status()[0]['last_error']==f'http_{status}'
    assert worker.step() is False
    with box.db() as db:
        assert db.execute('SELECT payload FROM tasks').fetchone()[0] is not None
    t.fault=None
    box.resume(include_dead=True)
    assert worker.step()
    assert box.status()[0]['state']=='acked'
    trace.append({'explicit_replay':box.status()})

def test_A24_protocol_and_retry_threshold(actors,tmp_path,trace):
    a,_=actors
    box,t=make_box(tmp_path,a)
    box.create_session(session_body())
    t.fault=lambda method,path,kwargs: response(201,{'recording_session_id':999,'duplicate':False}) if method=='POST' else None
    worker=Worker(box,t,max_transient=2,clock=lambda:1000,retry_base=0)
    assert worker.max_transient==2 and Worker(box,t).max_transient==8
    worker.step()
    assert box.status()[0]['state']=='dead_letter' and box.status()[0]['last_error']=='protocol_error'
    box.resume(include_dead=True)
    t.fault=lambda method,path,kwargs: response(503) if method=='POST' else None
    assert worker.step() and worker.step()
    assert box.status()[0]['state']=='paused_retry' and box.status()[0]['transient_count']==2
    assert worker.step() is False
    trace.append({'paused':box.status()})
    box.resume()
    t.fault=None
    drain(worker)
    box.enqueue('virtual_session',event())
    def mismatch(method,path,kwargs):
        if path.endswith('/messages'):
            return response(200, {'record_id':1,'recording_session_id':box.status()[0]['server_id'],
                                  'external_message_id':'wrong','sequence_no':1,'received_at':'2026-10-28T00:00:00Z','duplicate':True})
    t.fault=mismatch
    worker.step()
    assert box.status()[-1]['state']=='dead_letter'
    t.fault=None
    box.resume(include_dead=True)
    drain(worker)
    assert box.status()[-1]['state']=='acked'
    box.close_session('virtual_session','2026-10-28T00:01:00+08:00')
    t.fault=lambda method,path,kwargs: response(200,{'recording_session_id':-1}) if path.endswith('/close') else None
    worker.step()
    assert box.status()[-1]['last_error']=='protocol_error'

def test_A25_capacity_disk_and_async_text_entry(actors,tmp_path,monkeypatch,trace):
    a,_=actors
    box,t=make_box(tmp_path,a,capacity=2)
    box.create_session(session_body())
    assert box.enqueue('virtual_session',event())==1
    with pytest.raises(OutboxError,match='queue_full'):
        box.enqueue('virtual_session',event(2))
    with box.db() as db:
        assert db.execute('SELECT next_sequence FROM sessions').fetchone()[0]==2
    drain(Worker(box,t))
    original_db=box.db
    @contextmanager
    def readonly():
        db=sqlite3.connect(box.path.as_uri()+'?mode=ro',uri=True)
        db.row_factory=sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()
    monkeypatch.setattr(box,'db',readonly)
    with pytest.raises(OutboxError,match='local_storage_error'):
        box.enqueue('virtual_session',event(3))
    monkeypatch.setattr(box,'db',original_db)
    original_enqueue=box.enqueue
    tids=[]
    def slow_persistence(external,data):
        tids.append(threading.get_ident())
        time.sleep(.15)
        return original_enqueue(external,data)
    monkeypatch.setattr(box,'enqueue',slow_persistence)
    calls_before=len(t.calls)
    async def exercise():
        task=asyncio.create_task(box.enqueue_async('virtual_session',event(2)))
        ticks=0
        while not task.done():
            await asyncio.sleep(.01)
            ticks+=1
        assert await task==2
        return ticks
    main_thread=threading.get_ident()
    ticks=asyncio.run(exercise())
    assert ticks>=5 and tids[0]!=main_thread and len(t.calls)==calls_before
    assert box.status()[-1]['state']=='pending'
    trace.append({'heartbeat_ticks_during_slow_disk':ticks,'separate_thread':True,'http_calls_during_enqueue':0})

def test_A26_deleted_session_scoped_purge_and_no_credentials(actors,tmp_path,trace):
    a,b=actors
    box,t=make_box(tmp_path,a)
    box.create_session(session_body())
    box.enqueue('virtual_session',event())
    Worker(box,t).step()
    sid=box.status()[0]['server_id']
    box.create_session(session_body('keep_session'))
    box.enqueue('keep_session',event())
    tb=LocalTransport(b)
    other=Outbox(box.path,tb.base_url,b.uid,transport=tb)
    other.create_session(session_body())
    other.enqueue('virtual_session',event())
    tc=LocalTransport(a,'https://second.test')
    elsewhere=Outbox(box.path,tc.base_url,a.uid,transport=tc)
    elsewhere.create_session(session_body())
    elsewhere.enqueue('virtual_session',event())
    assert a.request('DELETE',f'/api/robot-records/sessions/{sid}').status_code==204
    assert Worker(box,t).step()
    with box.db() as db:
        erased=db.execute("SELECT t.payload,t.digest,t.receipt,s.state FROM tasks t JOIN sessions s ON s.id=t.session WHERE s.base=? AND s.owner=? AND s.external=?",(box.base,box.owner,'virtual_session')).fetchall()
        assert all(r['payload'] is None and r['digest'] is None and r['receipt'] is None and r['state']=='deleted' for r in erased)
        assert db.execute("SELECT count(*) FROM tasks WHERE payload IS NOT NULL").fetchone()[0]==6
    with pytest.raises(OutboxError,match='session_deleted'):
        box.create_session(session_body())
    assert all(s['state']=='pending' for s in other.status()+elsewhere.status())
    assert all(s['state']=='pending' for s in box.status() if s['external']=='keep_session')
    raw=box.path.read_bytes()
    assert a.token.encode() not in raw and b.token.encode() not in raw and b'fictional-only' not in raw
    box.purge('keep_session')
    assert all(s['local_state']=='deleted' for s in box.status())
    trace.append({'partitioned_states':box.status(),'other_owner':other.status(),'other_target':elsewhere.status(),'credentials_persisted':False})
