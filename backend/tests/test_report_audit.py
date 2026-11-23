from types import SimpleNamespace
import uuid
import pytest
from app.database import SessionLocal
from app.models import UserReportProfile
from app.schemas import ProfileUpdate
from app.user_profiles import replace_profile
from app.care.template_report import emotion_chart
from app.care.report_advice import advice
from app.care.composite_score import calculate
from test_template_report import call,classify,CUT,P
from test_care_management import manager  # noqa: F401

CONTACT={'emergency_contact_name':'虚构紧急联系人','emergency_contact_phone':'010-00000000','emergency_contact_authorized':True}

@pytest.fixture(autouse=True)
def freeze_report_clock(monkeypatch):monkeypatch.setattr('app.care.template_report.now',lambda:CUT)


def test_contact_required_for_new_registration_and_legacy_owner_can_complete_profile(actors):
    a,b=actors
    assert a.client.post('/api/auth/register',json={'username':'missing_contact','password':'fictional-only'}).status_code==422
    assert not a.request('GET','/api/auth/me').json()['emergency_contact_complete']
    result=a.request('PUT','/api/auth/profile',json=dict(full_name='虚构补填用户',age=28,gender='male',user_id=b.uid,**CONTACT))
    assert result.status_code==200
    value=a.request('GET','/api/auth/me').json()
    assert value['emergency_contact_complete'] and value['report_profile']['full_name']=='虚构补填用户'
    assert b.request('GET','/api/auth/me').json()['report_profile']['full_name'] is None
    assert a.request('PUT','/api/auth/profile',json={}).status_code==422
    assert a.request('GET','/api/auth/me').json()['emergency_contact_complete']


def test_rolling72_includes_multiple_calls_same_day_and_keeps_empty_session_gap(actors):
    a,_=actors
    first=call(a,'2026-11-21',texts=['我很开心。'])
    gap=call(a,'2026-11-21',texts=['没有可分析的词语甲乙丙。'])
    last=call(a,'2026-11-23',texts=['我很难过。'])
    classify()
    value=a.request('GET',P+f'{last}?period=three_days').json()
    points=value['emotion_trend']['points']
    assert [p['session_id'] for p in points]==[first,gap,last]
    assert [p['score'] for p in points]==[100,None,0]
    assert value['time_from']=='2026-11-20T15:59:59.999999Z'
    assert value['emotion_trend']['mode']=='sessions'


@pytest.mark.parametrize('text',[
    '我睡得很好，但朋友最近失眠。','昨天我朋友说他失眠。','妈妈说她失眠。',
    '如果我失眠怎么办？','电影里的人说“我失眠”。','我没有失眠。','我以前失眠，但现在睡得很好。'])
def test_context_filter_does_not_flag_others_negation_hypotheses_or_past_sleep(actors,text):
    a,_=actors;sid=call(a,texts=[text]);value=a.request('GET',P+str(sid)).json()
    assert not next(s for s in value['signals'] if s['key']=='sleep')['confirmed']
    if '朋友' in text:assert '朋友' not in value['summary_sections']['sleep_interest']['text']


def test_explicit_safety_expression_creates_manual_contact_alert_during_open_session(actors,manager):
    a,b=actors
    assert a.request('PUT','/api/auth/profile',json=CONTACT).status_code==200
    sid=call(a,texts=['我不想活了。'],closed=False)
    path='/api/care-management/safety-alerts?is_test=true'
    response=manager.request('GET',path);assert response.status_code==200
    item=response.json()['items'][0]
    assert item['session_id']==sid and item['contact_name']==CONTACT['emergency_contact_name']
    assert not item['notification_sent'] and not item['is_complete']
    assert a.request('GET',path).status_code==403
    assert b.request('POST',f'/api/care-management/safety-alerts/{sid}/acknowledge',json={'source_hash':item['source_hash']}).status_code==403
    result=manager.request('POST',f'/api/care-management/safety-alerts/{sid}/acknowledge',json={'source_hash':item['source_hash']})
    assert result.status_code==200 and result.json()['status']=='followed_up' and not result.json()['notification_sent']
    assert manager.request('GET',path).json()['pending_count']==0
    # Same source is idempotent; a new explicit message needs new follow-up.
    assert manager.request('POST',f'/api/care-management/safety-alerts/{sid}/acknowledge',json={'source_hash':item['source_hash']}).status_code==200
    a.send(sid,2,content='我现在想伤害自己。',occurred_at='2026-11-23T00:02:00Z')
    assert manager.request('GET',path).json()['pending_count']==1
    assert manager.request('POST',f'/api/care-management/safety-alerts/{sid}/acknowledge',json={'source_hash':item['source_hash']}).status_code==409


def test_quoted_or_denied_danger_does_not_create_explicit_contact_alert(actors,manager):
    a,_=actors
    for t in ['我没有想过自杀。','我朋友说他不想活了。','如果我说我不想活了你会怎么办？']:
        call(a,texts=[t])
    assert manager.request('GET','/api/care-management/safety-alerts?is_test=true').json()['pending_count']==0


def test_source_correction_and_deletion_remove_stale_alerts(actors,manager):
    a,_=actors;sid=call(a,texts=['我不想活了。'])
    item=manager.request('GET','/api/care-management/safety-alerts?is_test=true').json()['items'][0]
    record=a.messages(sid).json()['items'][0]['record_id']
    a.request('POST',f'/api/robot-insights/messages/{record}/corrections',json={'request_id':'fix-risk','base_revision':0,'content':'我没有想过自杀。'})
    assert manager.request('GET','/api/care-management/safety-alerts?is_test=true').json()['pending_count']==0
    assert manager.request('POST',f'/api/care-management/safety-alerts/{sid}/acknowledge',json={'source_hash':item['source_hash']}).status_code==409
    other=call(a,texts=['我不想活了。']);a.request('DELETE',f'/api/robot-records/sessions/{other}')
    assert manager.request('GET','/api/care-management/safety-alerts?is_test=true').json()['pending_count']==0


def test_central_only_permits_new_audited_contact_action_not_other_management_writes(actors,manager,monkeypatch):
    a,_=actors;sid=call(a,texts=['我不想活了。'])
    item=manager.request('GET','/api/care-management/safety-alerts?is_test=true').json()['items'][0]
    monkeypatch.setenv('ROBOT_CARE_DEPLOYMENT_ROLE','central')
    assert manager.request('POST',f'/api/care-management/safety-alerts/{sid}/acknowledge',json={'source_hash':item['source_hash']}).status_code==200
    assert manager.request('POST',f'/api/care-management/users/{a.uid}/followup',json={}).status_code==403
    assert manager.request('PUT','/api/auth/profile',json=CONTACT).status_code==403


def test_safety_advice_overrides_low_combined_and_positive_chart():
    output=advice(calculate({('PHQ-9',1):0}),[],{'points':[{'score':100}]},
        {'daily_function':{'status':'not_mentioned'}},True)
    assert '人工联系' in output[0] and '不等待' in output[1]
    output=advice(calculate({}),[],{'points':[{'score':100},{'score':0}]},
        {'daily_function':{'status':'not_mentioned'}},False)
    assert any('表达' in s for s in output)


def test_missing_contact_blocks_voice_before_cloud_connection(actors,monkeypatch):
    a,_=actors;monkeypatch.setenv('ROBOT_CARE_REQUIRE_EMERGENCY_CONTACT','true')
    with a.client.websocket_connect('/api/robot-voice/live') as ws:
        ws.send_json({'type':'authenticate','token':a.token})
        value=ws.receive_json()
        assert value['code']=='emergency_contact_required'
