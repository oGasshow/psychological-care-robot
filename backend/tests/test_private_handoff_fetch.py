from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.parametrize('host,user,port',[('invalid host','operator','22'),('localhost','bad@user','22'),('localhost','operator','0')])
def test_private_fetch_rejects_invalid_connection_before_transfer(tmp_path,host,user,port):
    tool=Path(__file__).resolve().parents[2]/'tools/fetch_private_handoff.py'
    folder=tmp_path/'private'
    result=subprocess.run([sys.executable,str(tool),'--host',host,'--user',user,'--port',port,'--output-dir',str(folder)],capture_output=True,text=True)
    assert result.returncode!=0
    assert not folder.exists()
