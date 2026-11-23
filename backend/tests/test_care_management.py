import bcrypt
import pytest
from conftest import API
from app.auth import create_access_token
from app.database import SessionLocal
from app.models import User
from app.robot_records import now
from app.care_management import ReportManager, CareFollowup, ManagementAudit
from app.care.report_delivery import ReportWording

P = '/api/care-management'


@pytest.fixture
def manager(actors, trace):
    a, _ = actors
    with SessionLocal() as db:
        row = User(username='virtual_manager', hashed_password=bcrypt.hashpw(b'fictional-only', bcrypt.gensalt(rounds=4)).decode())
        db.add(row); db.flush()
        uid = row.id
        db.add(ReportManager(user_id=uid, granted_at=now())); db.commit()
    return API(a.client, create_access_token({'sub':'virtual_manager'}), uid, trace)


def saved(actor, external='virtual', is_test=False):
    sid = actor.create(external, is_test=is_test).json()['recording_session_id']
    rid = actor.send(sid, content='虚构近况：今天和朋友散步。').json()['record_id']
    actor.request('POST',f'/api/robot-records/sessions/{sid}/close',json={'ended_at':'2026-10-28T00:01:00Z','last_sequence_no':1})
    return sid, rid


def test_only_explicit_active_managers_can_access_all_users(actors, manager):
    a, b = actors
    sid, _ = saved(a)
    assert a.client.get(P+'/users').status_code == 401
    assert a.request('GET',P+'/users').status_code == 403
    assert b.request('GET',P+f'/reports/{sid}').status_code == 403
    assert a.request('GET','/api/auth/me').json()['can_manage_reports'] is False
    assert manager.request('GET','/api/auth/me').json()['can_manage_reports'] is True
    result = manager.request('GET',P+'/users')
    assert result.status_code == 200
    assert result.headers['cache-control'] == 'no-store'
    assert {r['user_id'] for r in result.json()['items']} == {a.uid,b.uid}
    assert 'hashed_password' not in result.text
    assert 'token' not in result.text
    with SessionLocal() as db:
        db.get(User,manager.uid).is_active = False; db.commit()
    assert manager.request('GET',P+'/users').status_code == 403


def test_public_registration_cannot_grant_management(actors):
    a, _ = actors
    r = a.client.post('/api/auth/register',json={'username':'new_public_user','password':'fictional-only','can_manage_reports':True,'role':'admin','emergency_contact_name':'虚构联系人','emergency_contact_phone':'010-00000000','emergency_contact_authorized':True})
    assert r.status_code == 201
    token = a.client.post('/api/auth/login',json={'username':'new_public_user','password':'fictional-only'}).json()['access_token']
    assert a.client.get(P+'/users',headers={'Authorization':'Bearer '+token}).status_code == 403


def test_manager_report_keeps_user_boundaries_and_deleted_reports_unavailable(actors, manager):
    a, b = actors
    sa, _ = saved(a,'a'); sb, _ = saved(b,'b')
    for actor,sid in [(a,sa),(b,sb)]:
        result = manager.request('GET',P+f'/reports/{sid}')
        assert result.status_code == 200
        assert result.json()['user_id'] == actor.uid
        assert result.json()['report']['username'] == ('virtual_a' if actor==a else 'virtual_b')
    assert b.request('GET',f'/api/robot-insights/reports/session/{sa}').status_code == 404
    assert a.request('GET',f'/api/robot-records/sessions/{sb}').status_code == 404
    assert manager.request('GET',f'/api/robot-records/sessions/{sa}').status_code == 404
    assert a.request('DELETE',f'/api/robot-records/sessions/{sa}').status_code == 204
    assert manager.request('GET',P+f'/reports/{sa}').status_code == 404


def test_list_reports_respects_user_test_scope_pagination_and_incomplete_sessions(actors, manager):
    a, b = actors
    sa, _ = saved(a,'a1'); newer, _ = saved(a,'a2'); test, _ = saved(a,'test',True); saved(b,'b1')
    first = manager.request('GET',P+f'/users/{a.uid}/sessions?limit=1').json()
    assert [r['recording_session_id'] for r in first['items']] == [newer]
    second = manager.request('GET',P+f'/users/{a.uid}/sessions?limit=1&cursor='+first['next_cursor']).json()
    assert [r['recording_session_id'] for r in second['items']] == [sa]
    assert manager.request('GET',P+f'/users/{b.uid}/sessions?cursor='+first['next_cursor']).status_code == 422
    assert manager.request('GET',P+f'/users/{a.uid}/sessions?is_test=true&cursor='+first['next_cursor']).status_code == 422
    tests = manager.request('GET',P+f'/users/{a.uid}/sessions?is_test=true').json()['items']
    assert [r['recording_session_id'] for r in tests] == [test]
    opened = a.create('open',is_test=False).json()['recording_session_id']
    assert manager.request('GET',P+f'/reports/{opened}').status_code == 409
    incomplete = a.create('incomplete',is_test=False).json()['recording_session_id']
    a.send(incomplete)
    a.request('POST',f'/api/robot-records/sessions/{incomplete}/close',json={'ended_at':'2026-10-28T00:01:00Z','last_sequence_no':2})
    reports=manager.request('GET',P+f'/users/{a.uid}/sessions').json()['items']
    assert {r['recording_session_id'] for r in reports} == {sa,newer}
    detail=manager.request('GET',P+f'/users/{a.uid}').json()
    assert detail['report_count']==2 and detail['latest_session_id']==newer


def test_user_search_and_cursor_scope_are_strict(actors, manager):
    a, b = actors
    result = manager.request('GET',P+'/users?limit=1').json()
    assert result['items'][0]['user_id'] == b.uid
    cursor = result['next_cursor']
    assert manager.request('GET',P+'/users?limit=1&cursor='+cursor).json()['items'][0]['user_id'] == a.uid
    assert manager.request('GET',P+'/users?q=virtual_a').json()['items'][0]['user_id'] == a.uid
    assert manager.request('GET',P+'/users?q=%25').json()['items'] == []
    for query in ['q=other&cursor='+cursor,'is_test=true&cursor='+cursor,'limit=101','owner=1','q=a&q=b','care_status=high_concern']:
        assert manager.request('GET',P+'/users?'+query).status_code == 422


def test_report_manager_is_read_only_and_legacy_notes_remain_private(actors, manager):
    a, _ = actors
    sid, _ = saved(a)
    with SessionLocal() as db:
        db.add(CareFollowup(user_id=a.uid, is_test=False, state='in_progress', note='legacy private note',
                            updated_by=manager.uid, updated_at=now()))
        db.commit()
    for method, path, body in [
        ('PUT', f'/users/{a.uid}/followup', {'state':'contacted','note':'changed'}),
        ('POST', f'/reports/{sid}/narrative', {'source_snapshot_hash':'a'*64}),
        ('DELETE', f'/reports/{sid}', None),
    ]:
        assert manager.request(method, P+path, **({'json':body} if body else {})).status_code in (404,405)
    detail = manager.request('GET', P+f'/users/{a.uid}').json()
    assert 'care' not in detail and 'followup' not in detail
    assert detail['report_count']==1
    with SessionLocal() as db:
        row=db.get(CareFollowup,(a.uid,False))
        assert row.state=='in_progress' and row.note=='legacy private note'
        assert db.query(ManagementAudit).filter_by(action='update_followup').count()==0


def test_revoked_permission_applies_to_existing_token(actors, manager):
    with SessionLocal() as db:
        db.delete(db.get(ReportManager,manager.uid)); db.commit()
    assert manager.request('GET',P+'/users').status_code == 403
    assert manager.request('GET','/api/auth/me').json()['can_manage_reports'] is False


def test_final_wording_is_shared_and_corrections_remove_old_wording(actors, manager, monkeypatch):
    from app.care import report_narrative
    from app.care.report_facts import rules_narrative
    a, _ = actors
    sid, rid = saved(a)
    calls = []
    def wording(facts):
        calls.append(1)
        result = rules_narrative(facts)
        result['mode']='model'
        return result
    monkeypatch.setattr(report_narrative,'generate',wording)
    initial = manager.request('GET',P+f'/reports/{sid}').json()['report']
    digest = initial['source_snapshot_hash']
    assert a.request('POST',f'/api/robot-insights/reports/session/{sid}/narrative',json={'source_snapshot_hash':digest}).status_code==200
    user = a.request('GET',f'/api/robot-insights/reports/session/{sid}').json()
    staff = manager.request('GET',P+f'/reports/{sid}').json()['report']
    assert user['summary']==staff['summary'] and user['suggestions']==staff['suggestions']
    assert len(calls)==1
    assert a.request('POST',f'/api/robot-insights/reports/session/{sid}/narrative',json={'source_snapshot_hash':digest}).status_code==200
    assert len(calls)==2
    assert a.request('POST',f'/api/robot-insights/messages/{rid}/corrections',json={'request_id':'edit-admin-report','base_revision':0,'content':'虚构更正：今天在家休息。'}).status_code==201
    with SessionLocal() as db:
        assert db.get(ReportWording,sid) is None
    assert a.request('POST',f'/api/robot-insights/reports/session/{sid}/narrative',json={'source_snapshot_hash':digest}).status_code==409


def test_deleted_session_removes_saved_report_wording(actors, manager):
    a, _ = actors
    sid, _ = saved(a)
    with SessionLocal() as db:
        db.add(ReportWording(session_id=sid,owner=a.uid,source_hash='a'*64,narrative={},updated_at=now()));db.commit()
    assert a.request('DELETE',f'/api/robot-records/sessions/{sid}').status_code==204
    with SessionLocal() as db:
        assert db.get(ReportWording,sid) is None
