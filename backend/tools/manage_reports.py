"""Local deployment-owner CLI. Passwords are read interactively, never from argv."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description='Grant or revoke report-team access in one deployment.')
    parser.add_argument('action', choices=['create', 'grant', 'revoke'])
    parser.add_argument('--username', required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    args = parser.parse_args()
    access = json.loads((args.runtime.resolve() / 'access.json').read_text(encoding='utf-8'))
    os.environ['DATABASE_URL'] = 'sqlite:///' + Path(access['database']).as_posix()
    os.environ['SECRET_KEY'] = access['secret']
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.main import app  # Register all existing tables before create_all.
    from app.database import SessionLocal
    from app.models import User
    from app.auth import get_password_hash
    from app.schemas import UserAccountCredentials as UserRegister
    from app.care_management import ReportManager
    from app.robot_records import now
    with SessionLocal() as db:
        user = db.query(User).filter_by(username=args.username).first()
        if args.action == 'create':
            if user is not None:
                raise SystemExit('Account exists; use grant instead.')
            password = getpass.getpass('New management-account password: ')
            if password != getpass.getpass('Repeat password: '):
                raise SystemExit('Passwords differ.')
            data = UserRegister(username=args.username, password=password)
            if len(password.encode('utf-8')) > 72:
                raise SystemExit('Password must be at most 72 UTF-8 bytes.')
            user = User(username=data.username, hashed_password=get_password_hash(data.password))
            db.add(user)
            db.flush()
        if user is None:
            raise SystemExit('Account does not exist.')
        access_row = db.get(ReportManager, user.id)
        if args.action == 'revoke':
            if access_row:
                db.delete(access_row)
        elif access_row is None:
            db.add(ReportManager(user_id=user.id, granted_at=now()))
        db.commit()
    print('Report access revoked.' if args.action == 'revoke' else 'Report management account ready.')


if __name__ == '__main__':
    main()
