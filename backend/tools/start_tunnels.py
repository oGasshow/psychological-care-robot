"""Start only restricted, host-key-pinned SSH forwards; never use root credentials."""
import argparse
import json
from pathlib import Path
import os
import shutil
import socket
import subprocess
import time
import sys


def port_ready(port):
    with socket.socket() as probe:
        probe.settimeout(.5)
        return probe.connect_ex(('127.0.0.1',port))==0


def watch(path, selected, port, command):
    # One supervisor per profile; the lock contains no business data.
    with (path.parent/(selected+'-tunnel.lock')).open('a+b') as lock:
        try:
            if os.name=='nt':
                import msvcrt
                lock.seek(0)
                if not lock.read(1):lock.write(b'0');lock.flush()
                lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            return
        (path.parent/(selected+'-supervisor.pid')).write_text(str(os.getpid()))
        while True:
            while port_ready(port):time.sleep(1)
            with (path.parent/(selected+'-tunnel.log')).open('ab') as stream:
                proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                (path.parent/(selected+'-tunnel.pid')).write_text(str(proc.pid))
                proc.wait()
            time.sleep(3)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--reports',action='store_true')
    parser.add_argument('--watch',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    path=args.config.resolve();config=json.loads(path.read_text(encoding='utf-8-sig'))
    selected='reports' if args.reports else 'database'
    profile=config[selected]
    def resolve(value):return str((path.parent/value).resolve())
    port=int(profile['local_port'])
    if not 1024<=port<=65535:raise ValueError('invalid_forward_port')
    ssh=shutil.which('ssh')
    if not ssh:raise RuntimeError('OpenSSH client required')
    log=path.parent/(selected+'-tunnel.log')
    command=[ssh,'-N','-T','-i',resolve(profile['private_key']),'-o','BatchMode=yes',
        '-o','ExitOnForwardFailure=yes','-o','StrictHostKeyChecking=yes',
        '-o','UserKnownHostsFile='+resolve(config['known_hosts']),'-o','ServerAliveInterval=10',
        '-o','ServerAliveCountMax=2','-o','ConnectTimeout=10',
        '-L',f'127.0.0.1:{port}:127.0.0.1:{int(profile["remote_port"])}',
        profile['user']+'@'+config['host']]
    if args.watch:
        watch(path,selected,port,command)
        return
    supervisor=[sys.executable,str(Path(__file__).resolve()),'--config',str(path),'--watch']
    if args.reports:supervisor.append('--reports')
    with log.open('ab') as stream:
        proc=subprocess.Popen(supervisor,stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
    for _ in range(200):
        if port_ready(port):
            print(json.dumps({'forward_ready':True,'local_port':port,'automatic_reconnect':True}));return
        time.sleep(.1)
    raise RuntimeError('SSH forward startup timed out')


if __name__=='__main__':main()
