from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import sqlite3
import threading

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError, OperationalError
from app.auth import create_access_token
from app.database import engine, SessionLocal, Base
from app.models import User, Message, Diary, AssessmentRecord, Conversation
from app.robot_records import RecordMessage, RecordSession
from conftest import session_body, message_body

ROOT = '/api/robot-records/sessions'

def close(api, sid, last, **kwargs):
    return api.request('POST', f'{ROOT}/{sid}/close', json={
        'ended_at': '2026-10-28T00:01:00+08:00', 'last_sequence_no': last, **kwargs})

def error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()['error']['code'] == code

def test_A01_roundtrip(actors, trace):
    a, _ = actors
    registered = a.client.post('/api/auth/register', json={'username': 'virtual_new', 'password': 'fictional-new'})
    assert registered.status_code == 201
    created = a.create()
    assert created.status_code == 201
    sid = created.json()['recording_session_id']
    assert a.send(sid).status_code == 201
    assert a.send(sid, 2, role='assistant', playback_status='unknown').status_code == 201
    rows = a.messages(sid).json()['items']
    assert [x['role'] for x in rows] == ['user', 'assistant']
    assert rows[0]['content'] == message_body()['content']
    detail = a.detail(sid).json()
    assert detail['source'] == 'doubao_realtime' and detail['received_record_count'] == 2
    with SessionLocal() as db:
        counts = {'sessions': db.query(RecordSession).count(), 'records': db.query(RecordMessage).count()}
    assert counts == {'sessions': 1, 'records': 2}
    trace.append({'row_counts': counts})

def test_A02_no_model_or_side_effects(actors, monkeypatch, trace):
    from app import model_router, perception_planning, coordinator
    calls = []
    def forbidden(*args, **kwargs):
        calls.append('model')
        raise AssertionError('No model allowed')
    for cls, method in [(model_router.LocalModelService, 'generate_with_prompt'),
                         (model_router.RemoteModelService, 'generate_with_prompt'),
                         (perception_planning.PerceptionPlanningModule, 'execute'),
                         (coordinator.MultiAgentCoordinator, 'process_message')]:
        monkeypatch.setattr(cls, method, forbidden)
    def counts():
        with engine.connect() as db:
            return {t: db.exec_driver_sql('SELECT count(*) FROM "' + t + '"').scalar() for t in Base.metadata.tables if not t.startswith('robot_')}
    before = counts()
    a, _ = actors
    sid = a.create().json()['recording_session_id']
    assert a.send(sid).status_code == 201
    assert a.send(sid, 2, role='assistant', playback_status='interrupted').status_code == 201
    assert a.messages(sid).status_code == 200
    assert counts() == before and calls == []
    trace.append({'model_call_count': len(calls), 'before': before, 'after': counts()})

def test_A03_auth_and_injection(actors):
    a, b = actors
    for token in (None, 'forged', create_access_token({'sub': 'virtual_a'}, timedelta(seconds=-1))):
        headers = {} if token is None else {'Authorization': 'Bearer ' + token}
        r = a.client.post(ROOT, headers=headers, json=session_body())
        assert r.status_code == 401
    with SessionLocal() as db:
        db.query(User).filter_by(id=b.uid).update({'is_active': False})
        db.commit()
    error(b.create(), 403, 'account_disabled')
    error(a.create(user_id=b.uid), 422, 'validation_error')
    with SessionLocal() as db:
        assert db.query(RecordSession).count() == 0

def test_A04_user_isolation(actors):
    a, b = actors
    sa = a.create().json()['recording_session_id']
    sb = b.create().json()['recording_session_id']
    assert sa != sb
    for method, suffix, body in [('GET', '', None), ('GET', '/messages', None),
                                  ('POST', '/messages', message_body()),
                                  ('POST', '/close', {'ended_at': '2026-10-28T01:00:00Z', 'last_sequence_no': 0}),
                                  ('DELETE', '', None)]:
        error(a.request(method, f'{ROOT}/{sb}{suffix}', **({'json': body} if body else {})), 404, 'not_found')

def test_A05_scoped_message_ids(actors):
    a, b = actors
    ids = [a.create('s1').json()['recording_session_id'], a.create('s2').json()['recording_session_id'], b.create('s1').json()['recording_session_id']]
    records = [api.send(sid, external_message_id='same_id').json()['record_id'] for api, sid in zip((a,a,b), ids)]
    assert len(set(records)) == 3

def test_A06_duplicates_equivalent_time(actors):
    a, _ = actors
    first = a.create()
    second = a.create(started_at='2026-10-27T16:00:00Z')
    assert first.status_code == 201 and second.status_code == 200 and second.json()['duplicate'] is True
    sid = first.json()['recording_session_id']
    error(a.create(device_id='other_device'), 409, 'session_conflict')
    m1 = a.send(sid)
    m2 = a.send(sid, occurred_at='2026-10-27T16:00:01Z')
    assert m1.status_code == 201 and m2.status_code == 200
    assert m1.json()['record_id'] == m2.json()['record_id'] and m1.json()['received_at'] == m2.json()['received_at']
    assert close(a, sid, 1).status_code == 200
    assert a.create().json()['state'] == 'closed'

@pytest.mark.parametrize('change', [
    {'content':'虚构修改'}, {'role':'assistant', 'playback_status':'unknown'}, {'sequence_no':2},
    {'occurred_at':'2026-10-28T00:00:02+08:00'}, {'turn_id':'another_turn'}, {'text_status':'canceled'},
    {'role':'assistant', 'playback_status':'interrupted'},
])
def test_A07_immutable_conflicts(actors, change):
    a, _ = actors
    sid = a.create().json()['recording_session_id']
    original = a.send(sid).json()
    error(a.send(sid, **change), 409, 'message_conflict')
    assert a.messages(sid).json()['items'][0]['content'] == original['content']

def test_A08_database_unique_and_fk(actors, trace):
    a, _ = actors
    sid = a.create().json()['recording_session_id']
    a.send(sid)
    error(a.send(sid, external_message_id='other'), 409, 'sequence_conflict')
    for data in [message_body(), message_body(external_message_id='other'), message_body(2)]:
        # Last case checks FK enforcement with an absent parent.
        parent = 99999 if data['sequence_no'] == 2 else sid
        with pytest.raises(IntegrityError), SessionLocal() as db:
            db.add(RecordMessage(recording_session_id=parent, **data, received_at='2026-10-28T00:00:00Z'))
            db.commit()
    with engine.connect() as db:
        assert db.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
        trace.append({'unique_indexes': [list(r) for r in db.exec_driver_sql('PRAGMA index_list(robot_record_messages)')]})

def test_A09_independent_connection_concurrency(actors, trace):
    a, _ = actors
    connections = set()
    def checkout(connection, *_):
        connections.add(id(connection))
    event.listen(engine, 'checkout', checkout)
    try:
        _concurrency_checks(a, trace)
        assert len(connections) >= 2
        trace.append({'distinct_sqlite_connection_count': len(connections)})
    finally:
        event.remove(engine, 'checkout', checkout)

def _concurrency_checks(a, trace):
    barrier = threading.Barrier(2)
    def create_concurrent(_):
        barrier.wait()
        return a.create().status_code
    with ThreadPoolExecutor(2) as pool:
        statuses = list(pool.map(create_concurrent, range(2)))
    assert sorted(statuses) == [200, 201]
    sid = a.create().json()['recording_session_id']
    barrier = threading.Barrier(2)
    def submit(content):
        barrier.wait()
        r = a.send(sid, content=content)
        return r.status_code, r.json()
    with ThreadPoolExecutor(2) as pool:
        same = list(pool.map(submit, ['虚构并发', '虚构并发']))
    assert sorted(x[0] for x in same) == [200,201]
    assert same[0][1]['record_id'] == same[1][1]['record_id']
    sid2 = a.create('conflicting_concurrent').json()['recording_session_id']
    barrier = threading.Barrier(2)
    def different(content):
        barrier.wait()
        return a.send(sid2, content=content).status_code
    with ThreadPoolExecutor(2) as pool:
        conflict = list(pool.map(different, ['虚构甲', '虚构乙']))
    assert sorted(conflict) == [201, 409]
    with SessionLocal() as db:
        assert db.query(RecordMessage).count() == 2
    trace.append({'same_results': same, 'different_statuses': conflict, 'engine_pool': str(type(engine.pool)), 'file_database': True})

def test_A10_validation_boundaries(actors):
    a, _ = actors
    sid = a.create().json()['recording_session_id']
    bad = [{'role':'system'}, {'occurred_at':'2026-10-28T00:00:00'}, {'occurred_at':123},
           {'occurred_at':'2026-10-28T00:00:00+00:60'}, {'content':'\ud800'},
           {'sequence_no':True}, {'sequence_no':1.0}, {'sequence_no':0}, {'sequence_no':2147483648},
           {'content':'a'*8001}, {'content':' \n\t'}, {'content':123}, {'user_id':1},
           {'playback_status':'unknown'}, {'external_message_id':'bad id'}, {'turn_id':''},
           {'role':'assistant','playback_status':'not_applicable'}]
    for fields in bad:
        error(a.send(sid, **fields), 422, 'validation_error')
    for field in message_body():
        if field == 'turn_id':
            continue
        body = message_body()
        del body[field]
        error(a.request('POST', f'{ROOT}/{sid}/messages', json=body), 422, 'validation_error')
    for body in [session_body(source='unknown'), session_body(is_test=1), session_body(device_id='a'*129)]:
        error(a.request('POST', ROOT, json=body), 422, 'validation_error')
    for path in [ROOT+'?limit=true', ROOT+'?limit=1.0', ROOT+'?limit=0', ROOT+'?limit=101', ROOT+'/1.0/messages']:
        error(a.request('GET', path), 422, 'validation_error')
    assert a.send(sid, content='a'*8000).status_code == 201
    assert a.send(sid,2, external_message_id='a'*128, content=' 中文\n🌳 ').status_code == 201
    assert a.messages(sid).json()['items'][1]['content'] == ' 中文\n🌳 '

def test_A11_transaction_fault_and_busy(actors, trace):
    a, _ = actors
    sid = a.create().json()['recording_session_id']
    def fail_commit(connection):
        raise OperationalError('commit', {}, sqlite3.OperationalError('injected failure'))
    event.listen(engine, 'commit', fail_commit)
    try:
        error(a.send(sid), 503, 'storage_unavailable')
    finally:
        event.remove(engine, 'commit', fail_commit)
    assert a.detail(sid).json()['received_record_count'] == 0
    raw = sqlite3.connect(engine.url.database)
    raw.execute('BEGIN IMMEDIATE')
    try:
        error(a.send(sid),503,'storage_busy')
    finally:
        raw.rollback()
        raw.close()
    assert a.send(sid).status_code == 201
    assert a.detail(sid).json()['received_record_count'] == 1
    trace.append({'commit_fault_rolled_back': True, 'lock_busy_returned_503': True})

def test_A13_out_of_order(actors):
    a, _ = actors
    sid = a.create().json()['recording_session_id']
    for seq in (3,1,2):
        assert a.send(sid, seq).status_code == 201
    assert [m['sequence_no'] for m in a.messages(sid).json()['items']] == [1,2,3]

def test_A14_message_snapshot(actors):
    a,b = actors
    sid = a.create().json()['recording_session_id']
    other = a.create('other').json()['recording_session_id']
    for seq in (2,4):
        a.send(sid,seq)
    first = a.messages(sid, params={'limit':1}).json()
    a.send(sid,1)
    second = a.messages(sid, params={'limit':1, 'cursor':first['next_cursor']}).json()
    assert second['snapshot_max_id'] == first['snapshot_max_id']
    assert [x['sequence_no'] for x in first['items']+second['items']] == [2,4]
    assert second['next_cursor'] is None
    assert [x['sequence_no'] for x in a.messages(sid).json()['items']] == [1,2,4]
    error(a.messages(other, params={'cursor':first['next_cursor']}),422,'invalid_cursor')
    error(b.messages(sid, params={'cursor':first['next_cursor']}),404,'not_found')
    error(a.messages(sid, params={'cursor':first['next_cursor']+'bad'}),422,'invalid_cursor')
    error(a.request('GET',ROOT, params={'cursor':first['next_cursor']}),422,'invalid_cursor')

def test_A15_session_snapshot(actors):
    a,b = actors
    assert b.request('GET',ROOT).json()['items'] == []
    ids = [a.create(f's{i}').json()['recording_session_id'] for i in range(4)]
    first = a.request('GET',ROOT,params={'limit':2}).json()
    new_id = a.create('new').json()['recording_session_id']
    a.send(ids[0])
    second = a.request('GET',ROOT,params={'limit':2,'cursor':first['next_cursor']}).json()
    assert [x['recording_session_id'] for x in first['items']+second['items']] == list(reversed(ids))
    assert first['snapshot_max_id'] == second['snapshot_max_id']
    assert a.request('GET',ROOT).json()['items'][0]['recording_session_id'] == new_id
    error(b.request('GET',ROOT,params={'cursor':first['next_cursor']}),422,'invalid_cursor')

def test_A16_utc_across_dates(actors):
    a,_ = actors
    sid = a.create().json()['recording_session_id']
    assert a.detail(sid).json()['started_at'] == '2026-10-27T16:00:00.000000Z'
    r = a.send(sid,occurred_at='2026-10-28T00:00:01.123456+08:00').json()
    assert r['occurred_at'] == '2026-10-27T16:00:01.123456Z' and r['received_at'] != r['occurred_at']
    assert a.send(sid,occurred_at='2026-10-27T16:00:01.123456Z').status_code == 200

def test_A17_text_and_playback_terminal(actors):
    a,_ = actors
    sid = a.create().json()['recording_session_id']
    error(a.send(sid,text_status='partial'),422,'validation_error')
    for seq,(content,status) in enumerate([('', 'not_started'),('虚构部分', 'interrupted'),('虚构完整', 'unknown'),('虚构播放', 'completed')],1):
        assert a.send(sid,seq,role='assistant',content=content,playback_status=status,text_status='canceled' if seq < 3 else 'completed').status_code == 201
    assert [m['playback_status'] for m in a.messages(sid).json()['items']] == ['not_started','interrupted','unknown','completed']
    assert a.request('PATCH',f'{ROOT}/{sid}/messages/1',json={'playback_status':'completed'}).status_code in (404,405)
    error(a.send(sid,3,role='assistant',content='虚构完整',playback_status='completed'),409,'message_conflict')

def test_A18_close_and_late_arrivals(actors,trace):
    a,_ = actors
    sid = a.create().json()['recording_session_id']
    a.send(sid,2)
    error(close(a,sid,2,ended_at='2026-10-27T00:00:00Z'),422,'validation_error')
    error(close(a,sid,1),409,'close_conflict')
    assert close(a,sid,2).json()['is_complete'] is False
    error(close(a,sid,3),409,'close_conflict')
    error(close(a,sid,2,ended_at='2026-10-28T02:00:00Z'),409,'close_conflict')
    assert a.send(sid,2).status_code == 200
    error(a.send(sid,2,content='虚构冲突'),409,'message_conflict')
    error(a.send(sid,2,external_message_id='another'),409,'sequence_conflict')
    assert a.send(sid,1).status_code == 201
    assert close(a,sid,2).json()['is_complete'] is True
    error(a.send(sid,3),409,'session_closed')
    empty = a.create('empty').json()['recording_session_id']
    assert close(a,empty,0).json()['is_complete'] is True
    concurrent = a.create('concurrent').json()['recording_session_id']
    barrier = threading.Barrier(2)
    def operation(name):
        barrier.wait()
        return (close(a,concurrent,0) if name == 'close' else a.send(concurrent)).status_code
    with ThreadPoolExecutor(2) as pool:
        statuses = list(pool.map(operation,['close','send']))
    assert statuses in ([200,409],[409,201])
    detail = a.detail(concurrent).json()
    assert detail['state'] != 'closed' or detail['max_received_sequence_no'] <= detail['last_sequence_no']
    trace.append({'concurrent_close_send': statuses})

def test_A19_delete_tombstone_and_race(actors,trace):
    a,b = actors
    sid = a.create().json()['recording_session_id']
    another = a.create('retained').json()['recording_session_id']
    a.send(sid)
    a.send(another)
    assert a.request('DELETE',f'{ROOT}/{sid}').status_code == 204
    assert a.request('DELETE',f'{ROOT}/{sid}').status_code == 204
    error(b.request('DELETE',f'{ROOT}/{sid}'),404,'not_found')
    error(a.detail(sid),410,'session_deleted')
    error(a.create(),410,'session_deleted')
    error(a.send(sid),410,'session_deleted')
    error(close(a,sid,1),410,'session_deleted')
    with SessionLocal() as db:
        tomb = db.get(RecordSession,sid)
        data = {c.name:getattr(tomb,c.name) for c in RecordSession.__table__.columns}
        assert {k for k,v in data.items() if v is not None} == {'id','user_id','source','external_session_id','state','deleted_at'}
        assert db.query(RecordMessage).filter_by(recording_session_id=sid).count() == 0
        trace.append({'tombstone':data})
    assert a.detail(another).json()['received_record_count'] == 1
    race = a.create('race').json()['recording_session_id']
    barrier = threading.Barrier(2)
    def operation(name):
        barrier.wait()
        return (a.request('DELETE',f'{ROOT}/{race}') if name=='delete' else a.send(race)).status_code
    with ThreadPoolExecutor(2) as pool:
        statuses = list(pool.map(operation,['delete','send']))
    assert statuses in ([204,201],[204,410])
    with SessionLocal() as db:
        assert db.query(RecordMessage).filter_by(recording_session_id=race).count() == 0
    trace.append({'concurrent_delete_send':statuses})
