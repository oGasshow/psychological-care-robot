import sqlite3
import subprocess
import sys
from pathlib import Path


def test_public_demo_is_synthetic_and_refuses_overwrite(tmp_path):
    tool=Path(__file__).resolve().parents[1]/'tools/create_development_database.py'
    target=tmp_path/'public-example.db'
    result=subprocess.run([sys.executable,str(tool),'--output',str(target)],capture_output=True,text=True)
    assert result.returncode==0, result.stderr
    with sqlite3.connect(target) as db:
        assert {row[0] for row in db.execute('select username from users')}=={'development_admin','development_user'}
        assert db.execute('select count(*) from robot_record_sessions where is_test=0').fetchone()[0]==0
        assert db.execute('select count(*) from robot_record_messages').fetchone()[0]==18
        assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
        assert not db.execute('pragma foreign_key_check').fetchall()
    before=target.read_bytes()
    assert subprocess.run([sys.executable,str(tool),'--output',str(target)],capture_output=True).returncode!=0
    assert target.read_bytes()==before
