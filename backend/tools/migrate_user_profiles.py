"""Add optional profile storage without changing users, credentials or history."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def migrate(engine):
    from app.models import UserReportProfile
    from sqlalchemy import inspect
    existed=inspect(engine).has_table(UserReportProfile.__tablename__)
    UserReportProfile.__table__.create(engine,checkfirst=True)
    return {'profile_storage_ready':True,'table_created':not existed,'existing_users_changed':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    from app.database import engine
    from sqlalchemy import inspect
    if args.check:
        ready=inspect(engine).has_table('user_report_profiles')
        print(json.dumps({'profile_storage_ready':ready}));raise SystemExit(0 if ready else 1)
    print(json.dumps(migrate(engine)))


if __name__=='__main__':main()
