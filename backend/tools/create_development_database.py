"""Create an isolated, PUBLIC synthetic demo database; never copy live data."""
import argparse
import os
from pathlib import Path
import sys
import uuid

DEMO_PASSWORD = 'DEMO-ONLY-CHANGE-ME'
DEMO_SIGNING_KEY = 'development-only-public-example-key-never-use-in-production'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    if output.exists():raise SystemExit('Refusing to overwrite an existing database.')
    output.parent.mkdir(parents=True,exist_ok=True)
    os.environ.update(DATABASE_URL='sqlite:///'+output.as_posix(),SECRET_KEY=DEMO_SIGNING_KEY,
        APP_ENV='development',ROBOT_CARE_DEPLOYMENT_ROLE='standalone',ROBOT_CARE_DEMO_DATABASE='true',
        ROBOT_CARE_VOICE_ENABLED='false',ROBOT_CARE_GUIDED_SCREENING_ENABLED='false',
        ROBOT_CARE_COLLECTION_DEMO='false',ROBOT_CARE_REPORT_PROVIDER='disabled',
        ROBOT_CARE_ANALYSIS_ENGINE='rules',ROBOT_CARE_ASSESSMENT_PROVIDER='disabled',
        DOUBAO_VOICE_API_KEY='',MODELSCOPE_API_KEY='',ROBOT_CARE_REPORT_API_KEY='')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import SessionLocal
    from app.models import User
    from app.care_management import ReportManager
    from app.robot_records import now
    from app.voice.screening import Screening,CORE_OPENERS,OPTIONS,save_result
    from app.voice.transcripts import Utterance
    from app.voice.collection_sources import attach_sources
    from app.voice.collection_plan import store_plan
    with TestClient(app) as client:
        for name in ('development_admin','development_user'):
            response=client.post('/api/auth/register',json={'username':name,'password':DEMO_PASSWORD,'emergency_contact_name':'虚构演示联系人（非真实）','emergency_contact_phone':'00000000','emergency_contact_authorized':True})
            response.raise_for_status()
        with SessionLocal() as db:
            admin=db.query(User).filter_by(username='development_admin').one()
            db.add(ReportManager(user_id=admin.id,granted_at=now()));db.commit()
        token=client.post('/api/auth/login',json={'username':'development_user','password':DEMO_PASSWORD}).json()['access_token']
        headers={'Authorization':'Bearer '+token}
        uid=client.get('/api/auth/me',headers=headers).json()['id']
        response=client.post('/api/robot-records/sessions',headers=headers,json=dict(source='doubao_realtime',
            device_id='synthetic_development_example',external_session_id='PUBLIC-SYNTHETIC-EXAMPLE',started_at=now(),is_test=True))
        response.raise_for_status();sid=response.json()['recording_session_id']
        screening=Screening(True,'public-synthetic-example')
        screening.core_only=screening.direct_collection=True
        screening.concern(['synthetic-development-only'],'public-synthetic-example',['PHQ-9']);screening.start_collection()
        sequence=0
        for index in range(1,10):
            screening.preferred_item=('PHQ-9',index)
            for role,content in [('assistant',CORE_OPENERS['PHQ-9',index]),('user',OPTIONS[0])]:
                sequence+=1
                entry=Utterance(uuid.uuid4().hex,role,'example_'+str(index),text=content,final=True,occurred_at=now())
                screening.observe(entry)
                client.post(f'/api/robot-records/sessions/{sid}/messages',headers=headers,
                    json=dict(sequence_no=sequence,**entry.wire())).raise_for_status()
        client.post(f'/api/robot-records/sessions/{sid}/close',headers=headers,json=dict(ended_at=now(),last_sequence_no=sequence)).raise_for_status()
        screening.history_session_ids=[sid]
        attach_sources(uid,sid,screening,{});store_plan(uid,True,screening);save_result(uid,sid,screening)
    print('Created PUBLIC synthetic development database; no live data or credentials were read into it.')


if __name__=='__main__':main()
