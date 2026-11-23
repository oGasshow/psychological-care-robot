import uuid
import pytest
from sqlalchemy import create_engine,text,inspect
from app.database import SessionLocal
from app.models import User,UserReportProfile
from app.user_profiles import save_registration_profile
from app.schemas import UserRegister
from app.care.template_report import read_template_report
from tools.migrate_user_profiles import migrate
from test_care_management import manager,saved  # noqa: F401

FIELDS=dict(full_name='虚构用户甲',gender='female',age=31,
    emergency_contact_name='虚构联系人乙',emergency_contact_phone='010-00000000',emergency_contact_authorized=True)


def register(a,**fields):
    username='profile_'+uuid.uuid4().hex[:12]
    response=a.client.post('/api/auth/register',json=dict(username=username,password='fictional-only',**fields))
    return username,response


def test_profile_registration_is_saved_and_visible_only_to_owner(actors):
    a,b=actors
    username,response=register(a,**FIELDS)
    assert response.status_code==201
    uid=response.json()['data']['user_id']
    assert 'emergency_contact_phone' not in response.text
    login=a.client.post('/api/auth/login',json={'username':username,'password':'fictional-only'})
    assert login.status_code==200
    headers={'Authorization':'Bearer '+login.json()['access_token']}
    profile=a.client.get('/api/auth/me',headers=headers).json()['report_profile']
    assert profile['full_name']==FIELDS['full_name'] and profile['age']==31 and profile['gender_label']=='女'
    assert profile['emergency_contact_phone']==FIELDS['emergency_contact_phone']
    assert b.request('GET','/api/auth/me').json()['report_profile']['full_name'] is None
    assert b.request('GET',f'/api/auth/me?user_id={uid}').json()['username']=='virtual_b'
    with SessionLocal() as db:
        row=db.get(UserReportProfile,uid)
        assert row.emergency_contact_authorized_at is not None
        assert db.get(User,uid).username==username


def test_legacy_accounts_and_optional_registration_remain_compatible(actors):
    a,_=actors
    assert a.request('GET','/api/auth/me').status_code==200
    assert all(v is None for v in a.request('GET','/api/auth/me').json()['report_profile'].values())
    username,response=register(a,emergency_contact_name='虚构联系人',emergency_contact_phone='010-00000000',emergency_contact_authorized=True)
    assert response.status_code==201
    with SessionLocal() as db:assert db.get(UserReportProfile,response.json()['data']['user_id']).full_name is None
    assert a.client.post('/api/auth/login',json={'username':username,'password':'fictional-only'}).status_code==200


@pytest.mark.parametrize('fields',[
    {'age':0},{'age':121},{'age':True},{'age':22.5},{'age':'22'},
    {'gender':'invalid'},{'full_name':'x'*51},{'full_name':'姓名\n换行'},
    {'emergency_contact_name':'未授权'},
    {'emergency_contact_name':'未授权','emergency_contact_phone':'010-00000000'},
    {'emergency_contact_name':'号码不合法','emergency_contact_phone':'123abc','emergency_contact_authorized':True},
    {'emergency_contact_name':'无效布尔值','emergency_contact_phone':'010-00000000','emergency_contact_authorized':'true'},
])
def test_invalid_profile_does_not_create_account_or_partial_metadata(actors,fields):
    a,_=actors;username,response=register(a,**fields)
    assert response.status_code==422
    with SessionLocal() as db:assert db.query(User).filter_by(username=username).count()==0


def test_name_only_profile_and_whitespace_normalization(actors):
    a,_=actors
    username,result=register(a,full_name='  虚构称呼  ',gender='undisclosed',age=None,emergency_contact_name='虚构联系人',emergency_contact_phone='010-00000000',emergency_contact_authorized=True)
    assert result.status_code==201
    with SessionLocal() as db:
        row=db.get(UserReportProfile,result.json()['data']['user_id'])
        assert row.full_name=='虚构称呼' and row.age is None and row.emergency_contact_name=='虚构联系人'


def test_account_and_profile_commit_atomically(actors,monkeypatch):
    a,_=actors
    monkeypatch.setenv('ROBOT_CARE_DEPLOYMENT_ROLE','edge')
    from sqlalchemy.exc import OperationalError
    def failed(*args):raise OperationalError('fictional SQL',{},RuntimeError('fictional profile store failure'))
    monkeypatch.setattr('app.user_profiles.save_registration_profile',failed)
    username,response=register(a,**FIELDS)
    assert response.status_code==503
    with SessionLocal() as db:assert db.query(User).filter_by(username=username).count()==0


def test_report_uses_owner_profile_and_metadata_changes_invalidate_hash(actors,manager):
    a,b=actors;sid,_=saved(a)
    with SessionLocal() as db:
        save_registration_profile(db,a.uid,UserRegister(username='fixture',password='fictional-only',**FIELDS));db.commit()
    first=a.request('GET',f'/api/robot-insights/reports/template/{sid}').json()
    assert first['personal_profile']['full_name']==FIELDS['full_name'] and first['personal_profile']['age']==31
    assert first['user_id']==a.uid
    staff=manager.request('GET',f'/api/care-management/template-reports/{sid}').json()['report']
    assert staff['personal_profile']==first['personal_profile']
    assert b.request('GET',f'/api/robot-insights/reports/template/{sid}').status_code==404
    listing=manager.request('GET','/api/care-management/users').text
    assert FIELDS['emergency_contact_phone'] not in listing and FIELDS['full_name'] not in listing
    with SessionLocal() as db:
        db.get(UserReportProfile,a.uid).full_name='虚构修改后的称呼';db.commit()
    updated=a.request('GET',f'/api/robot-insights/reports/template/{sid}').json()
    assert updated['source_snapshot_hash']!=first['source_snapshot_hash']
    assert updated['personal_profile']['full_name']=='虚构修改后的称呼'


def test_additive_migration_is_idempotent_and_preserves_old_user_rows(tmp_path):
    local=create_engine('sqlite:///'+str(tmp_path/'old.db'))
    with local.begin() as db:
        db.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, hashed_password TEXT)'))
        db.execute(text("INSERT INTO users VALUES(1,'old_fixture','unchanged_fixture_hash')"))
    assert migrate(local)['table_created'] is True
    assert migrate(local)['table_created'] is False
    assert inspect(local).has_table('user_report_profiles')
    with local.connect() as db:
        assert db.execute(text('SELECT * FROM users')).all()==[(1,'old_fixture','unchanged_fixture_hash')]
        assert db.execute(text('SELECT count(*) FROM user_report_profiles')).scalar()==0
    local.dispose()
