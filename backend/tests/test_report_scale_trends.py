"""Independent episodes, original source times, and Beijing midnight boundaries."""
import json
import pytest
from app.database import SessionLocal
from app.robot_records import RecordMessage
from app.voice.screening import ScreeningResult
from app.care.worker import Worker
from test_scale_reports import seed,setup_controller,save

@pytest.fixture(autouse=True)
def settings(monkeypatch):
 for k,v in dict(APP_ENV='test',ROBOT_CARE_COLLECTION_DEMO='false',ROBOT_CARE_GUIDED_SCREENING_ENABLED='true',ROBOT_CARE_PURCHASE_NOTICE_VERSION='fictional-normal-v1',ROBOT_CARE_REPORT_PROVIDER='disabled',ROBOT_CARE_ASSESSMENT_PROVIDER='disabled',ROBOT_CARE_ANALYSIS_ENGINE='rules').items():monkeypatch.setenv(k,v)

def preview(a,ids):
 r=a.request('POST','/api/robot-insights/reports/preview',json={'scope':{'session_ids':ids}});assert r.status_code==200;return r.json()

def test_multiple_episodes_deduplicate_snapshots_and_use_scale_answer_time(actors):
 a,_=actors;first,second,_=seed(a);s=setup_controller()
 third=save(a,s,'PHQ-9',[1,1,1,1,1,1,0,0,0]);fourth=save(a,s,'GAD-7',[1,0,1,0,1,0,1])
 dto=preview(a,[first,second,third,fourth]);groups={g['scale_id']:g for g in dto['scale_trends']}
 phq=groups['PHQ-9'];assert phq['completed_count']==2 and len(phq['points'])==2
 assert [p['score'] for p in phq['points']]==[12,6] and phq['numeric_change']==-6
 assert [p['score'] for p in groups['GAD-7']['points']]==[9,4]
 with SessionLocal() as db:
  expected=max(m.occurred_at for m in db.query(RecordMessage).filter_by(recording_session_id=first,role='user'))
 assert phq['points'][0]['observed_at']==expected
 fact=next(f for f in dto['report_facts']['facts'] if f.get('scale_id')=='PHQ-9')
 assert [p['score'] for p in fact['history']]==[12,6] and fact['trend_numeric_change']==-6
 restricted=preview(a,[third,fourth]);assert all(g['completed_count']==1 for g in restricted['scale_trends'])
 assert restricted['source_snapshot_hash']!=dto['source_snapshot_hash']
 from pathlib import Path
 (Path(__file__).resolve().parents[2]/'runtime/report-scale-trends-fixture.json').write_text(json.dumps(dto,ensure_ascii=False),encoding='utf8')

def test_old_episode_score_is_revision_bound_in_report_hash(actors):
 a,_=actors;first,second,_=seed(a);s=setup_controller();third=save(a,s,'PHQ-9',[0]*9)
 before=preview(a,[first,second,third])
 with SessionLocal() as db:
  row=db.get(ScreeningResult,first);payload=json.loads(json.dumps(row.payload));payload['scales'][0]['items'][0]['value']=3;row.payload=payload
  row2=db.get(ScreeningResult,second);payload=json.loads(json.dumps(row2.payload));payload['scales'][0]['items'][0]['value']=3;row2.payload=payload;db.commit()
 after=preview(a,[first,second,third]);assert before['source_snapshot_hash']!=after['source_snapshot_hash']
 phq=next(g for g in after['scale_trends'] if g['scale_id']=='PHQ-9');assert phq['completed_count']==1
 assert any(p['status']=='needs_revalidation' and p['score'] is None for p in phq['points'])

def test_daily_counts_follow_beijing_midnight_and_identify_sessions(actors):
 a,_=actors;sid=a.create('midnight_boundary').json()['recording_session_id']
 stamps=['2026-11-14T15:59:59Z','2026-11-14T16:00:00Z','2026-11-14T17:54:52.445992Z','2026-11-15T15:59:59Z','2026-11-15T16:00:00Z']
 for n,stamp in enumerate(stamps,1):assert a.send(sid,n,content='今天和朋友散步很开心。',occurred_at=stamp).status_code==201
 w=Worker();w.scan()
 while w.step():pass
 r=a.request('POST','/api/robot-insights/reports/preview',json={'scope':{'time_from':'2026-11-13T16:00:00Z','time_to':'2026-11-16T16:00:00Z'}});assert r.status_code==200
 dto=r.json();days={d['day']:d for d in dto['report_facts']['groups'][0]['daily']}
 assert [days[f'2026-11-{d}']['classified_count'] for d in (14,15,16)]==[1,3,1]
 assert days['2026-11-15']['recording_session_ids']==[sid]
 with SessionLocal() as db:expected={m.id for m in db.query(RecordMessage).filter_by(recording_session_id=sid) if m.sequence_no in (2,3,4)}
 assert set(days['2026-11-15']['record_ids'])==expected
 assert dto['report_timezone']=='Asia/Shanghai'

def test_model_can_cite_verified_historical_scores_but_not_invent_them(actors):
 from app.care.report_narrative import validate_content
 a,_=actors;first,second,_=seed(a);s=setup_controller();third=save(a,s,'PHQ-9',[1,1,1,1,1,1,0,0,0])
 facts=preview(a,[first,second,third])['report_facts']
 content=dict(overview=dict(text='可以结合多次记录继续了解近况。',evidence_ids=['scale:PHQ-9']),changes=[],topics=[],conversation_suggestions=[],limitations=[],
  scale_readings=[dict(text='PHQ-9辅助合计从12分变为6分，比首次减少6分。',evidence_ids=['scale:PHQ-9'])])
 assert validate_content(json.dumps(content,ensure_ascii=False),facts)['scale_readings']
 content['scale_readings'][0]['text']='PHQ-9辅助合计从18分变为6分。'
 with pytest.raises(ValueError,match='scale_number_not_verified'):validate_content(json.dumps(content,ensure_ascii=False),facts)
