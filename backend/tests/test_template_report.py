from datetime import timedelta
import uuid
import pytest
from app.care.template_report import read_template_report,emotion_chart
from app.care.report_facts import dt,stamp
from app.database import SessionLocal
from app.care.worker import Worker
from app.robot_records import now,RecordSession
from test_care_management import manager  # noqa: F401
from test_scale_reports import setup_controller,save

CUT='2026-11-23T15:59:59.999999Z'
P='/api/robot-insights/reports/template/'

@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv('ROBOT_CARE_GUIDED_SCREENING_ENABLED','true')
    monkeypatch.setenv('ROBOT_CARE_PURCHASE_NOTICE_VERSION','fictional-normal-v1')
    monkeypatch.setenv('ROBOT_CARE_COLLECTION_DEMO','false')
    monkeypatch.setenv('ROBOT_CARE_ANALYSIS_ENGINE','rules')
    monkeypatch.setattr('app.care.template_report.now',lambda:CUT)
    monkeypatch.setattr('test_scale_reports.now',lambda:'2026-11-23T01:00:00.000000Z')

def call(a,day='2026-11-23',texts=None,is_test=True,closed=True):
    start=f'{day}T00:01:00+08:00'
    sid=a.create(uuid.uuid4().hex,started_at=start,is_test=is_test).json()['recording_session_id']
    for i,text in enumerate(texts or ['今天和朋友散步很开心。'],1):
        a.send(sid,i,content=text,occurred_at=f'{day}T00:01:{i:02}+08:00')
    if closed:a.request('POST',f'/api/robot-records/sessions/{sid}/close',json={'ended_at':f'{day}T00:05:00+08:00','last_sequence_no':len(texts or [1])})
    return sid

def classify():
    w=Worker();w.scan()
    while w.step():pass

def test_scope_uses_three_or_seven_beijing_calendar_dates_with_isolation(actors,manager):
    a,b=actors
    sid=call(a);call(a,'2026-11-22');call(a,'2026-11-18');call(a,'2026-11-15')
    call(a,'2026-11-22',is_test=False);call(b);call(a,closed=False)
    for period,count,days in [('session',1,1),('three_days',2,2),('week',3,3)]:
        response=a.request('GET',P+f'{sid}?period={period}');assert response.status_code==200
        value=response.json();assert value['conversation_count']==count and value['user_turns']==count
        assert len(value['emotion_trend']['points'])==days
        assert value['qr_status']=='not_configured' and value['transcription_status']=='completed'
        assert value['combined_score']['score'] is None and value['combined_score']['confidence']==0
        assert value['instruments']==[]
        managed=manager.request('GET',f'/api/care-management/template-reports/{sid}?period={period}').json()['report']
        assert managed==value
    assert a.request('GET',P+f'{sid}?period=three_days').json()['time_from']=='2026-11-20T15:59:59.999999Z'
    assert b.request('GET',P+str(sid)).status_code==404
    assert a.request('GET',f'/api/care-management/template-reports/{sid}').status_code==403
    assert a.request('GET',P+f'{sid}?period=month').status_code==422
    assert a.request('GET',P+f'{sid}?period=week&period=session').status_code==422

def test_latest_task_scores_merge_but_window_excludes_old_answer_sources(actors):
    a,_=actors
    controller=setup_controller();controller.episode_id=uuid.uuid4().hex;controller.window_end='2026-11-23'
    first=save(a,controller,'PHQ-9',[1]*8+[0]);second=save(a,controller,'GAD-7',[1]*7)
    value=a.request('GET',P+f'{second}?period=three_days').json()
    assert value['combined_score']['answered']==16 and value['combined_score']['score']==15
    assert {s['scale_id'] for s in value['instruments']}=={'PHQ-9','GAD-7'}
    assert value['summary_sections']['sleep_interest']['status']=='confirmed_answers'
    with SessionLocal() as db:
        session=db.get(RecordSession,first);session.started_at='2026-11-18T00:00:00.000000Z';session.ended_at='2026-11-18T00:10:00.000000Z'
        from app.robot_records import RecordMessage
        for row in db.query(RecordMessage).filter_by(recording_session_id=first):row.occurred_at='2026-11-18T00:01:00.000000Z'
        db.commit()
    recent=a.request('GET',P+f'{second}?period=three_days').json()
    assert recent['combined_score']['answered']==7 and recent['combined_score']['confidence']==43.75
    assert [s['scale_id'] for s in recent['instruments']]==['GAD-7']
    week=a.request('GET',P+f'{second}?period=week').json()
    assert week['combined_score']['answered']==16

def test_summary_and_flags_preserve_denials_and_skip_others_hypotheses(actors):
    a,_=actors
    sid=call(a,texts=['我没有失眠，睡得很好。','我妈妈失眠很严重。','如果我失眠，你会怎么回答？','最近工作顺利。'])
    value=a.request('GET',P+str(sid)).json()
    assert not next(s for s in value['signals'] if s['key']=='sleep')['confirmed']
    sleep=value['summary_sections']['sleep_interest']['text']
    assert '没有失眠' in sleep and '妈妈' not in sleep and '如果' not in sleep
    assert '工作顺利' in value['summary_sections']['daily_function']['text']
    assert value['summary_sections']['emotion_life']['status']=='not_mentioned'
    normal=call(a,texts=['我不失眠。'])
    assert not next(s for s in a.request('GET',P+str(normal)).json()['signals'] if s['key']=='sleep')['confirmed']

def test_current_source_edits_remove_old_trend_and_summary(actors):
    a,_=actors
    sid=call(a,texts=['我最近总是失眠，很难过。','今天和朋友散步很开心。'])
    classify()
    before=a.request('GET',P+str(sid)).json()
    assert before['emotion_trend']['valid_count']==2
    rows=a.request('GET',f'/api/robot-records/sessions/{sid}/messages').json()['items']
    row=next(r for r in rows if '失眠' in r['content'])
    response=a.request('POST',f'/api/robot-insights/messages/{row["record_id"]}/corrections',json={'request_id':'template-edit','base_revision':0,'content':'我现在睡得很好，没有失眠。'})
    assert response.status_code==201
    after=a.request('GET',P+str(sid)).json()
    assert after['emotion_trend']['valid_count']==1
    assert after['emotion_trend']['points'][0]['score'] is None
    assert not next(s for s in after['signals'] if s['key']=='sleep')['confirmed']
    assert after['source_snapshot_hash']!=before['source_snapshot_hash']
    a.request('DELETE',f'/api/robot-records/sessions/{sid}')
    assert a.request('GET',P+str(sid)).status_code==410

def test_missing_days_are_null_and_emotion_is_separate_from_scale(actors):
    a,_=actors
    first=call(a,'2026-11-21',texts=['今天和朋友散步很开心。']);sid=call(a,'2026-11-23',texts=['我很难过，很孤独。'])
    classify()
    value=a.request('GET',P+f'{sid}?period=three_days').json()
    points=value['emotion_trend']['points']
    assert [p['session_id'] for p in points]==[first,sid]
    assert points[0]['score']==100 and points[1]['score']==0
    assert value['combined_score']['score'] is None

def test_safety_source_not_exported_as_general_summary(actors):
    a,_=actors
    sid=call(a,texts=['我有点不想活了都。'])
    value=a.request('GET',P+str(sid)).json()
    assert value['support_notice'] and next(s for s in value['signals'] if s['key']=='safety')['confirmed']
    assert '不想活' not in str(value['summary_sections'])

def test_only_latest_engine_version_contributes_to_chart():
    messages=[{'record_id':1,'occurred_at':'2026-11-23T00:00:00Z'},{'record_id':2,'occurred_at':'2026-11-23T00:01:00Z'}]
    def group(identifier,stamp,kind):return dict(engine_kind=kind,engine_version='v1',points=[dict(record_id=identifier,occurred_at=stamp,emotion_label='positive')])
    chart=emotion_chart({'emotion_groups':[group(1,messages[0]['occurred_at'],'old'),group(2,messages[1]['occurred_at'],'new')]},messages,'session',CUT,CUT)
    assert chart['points'][0]['score'] is None and chart['points'][1]['score']==100
    assert chart['excluded_engine_groups']==1

def test_asked_but_unanswered_instrument_is_listed_without_fabricating_score(actors):
    from app.voice.screening import save_result
    a,_=actors
    sid=a.create(uuid.uuid4().hex,started_at=now()).json()['recording_session_id']
    a.send(sid,1,role='assistant',content='最近两周，难以入睡、睡眠中断或睡得过多的情况怎么样？',occurred_at=now(),playback_status='completed')
    a.request('POST',f'/api/robot-records/sessions/{sid}/close',json={'ended_at':now(),'last_sequence_no':1})
    controller=setup_controller();controller.episode_id=uuid.uuid4().hex;controller.window_end='2026-11-23'
    save_result(a.uid,sid,controller)
    value=a.request('GET',P+str(sid)).json()
    assert value['combined_score']['score'] is None
    assert value['instruments'][0]['scale_id']=='PHQ-9' and value['instruments'][0]['answered']==0
