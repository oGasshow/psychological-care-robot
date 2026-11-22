"""Start only restricted, host-key-pinned SSH forwards; never use root credentials."""
import argparse
import json
from pathlib import Path
import os
import shutil
import socket
import subprocess
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--reports',action='store_true')
    args=parser.parse_args()
    path=args.config.resolve();config=json.loads(path.read_text(encoding='utf-8-sig'))
    selected='reports' if args.reports else 'database'
    profile=config[selected]
    def resolve(value):return str((path.parent/value).resolve())
    port=int(profile['local_port'])
    if not 1024<=port<=65535:raise ValueError('invalid_forward_port')
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',port))==0:
            print(json.dumps({'forward_ready':True,'local_port':port}));return
    ssh=shutil.which('ssh')
    if not ssh:raise RuntimeError('OpenSSH client required')
    log=path.parent/(selected+'-tunnel.log')
    command=[ssh,'-N','-T','-i',resolve(profile['private_key']),'-o','BatchMode=yes',
        '-o','ExitOnForwardFailure=yes','-o','StrictHostKeyChecking=yes',
        '-o','UserKnownHostsFile='+resolve(config['known_hosts']),'-o','ServerAliveInterval=15',
        '-o','ServerAliveCountMax=3','-L',f'127.0.0.1:{port}:127.0.0.1:{int(profile["remote_port"])}',
        profile['user']+'@'+config['host']]
    with log.open('ab') as stream:
        proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
    for _ in range(100):
        if proc.poll() is not None:raise RuntimeError('SSH forward failed; inspect private tunnel log')
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',port))==0:
                (path.parent/(selected+'-tunnel.pid')).write_text(str(proc.pid))
                print(json.dumps({'forward_ready':True,'local_port':port}));return
        time.sleep(.1)
    raise RuntimeError('SSH forward startup timed out')


if __name__=='__main__':main()
