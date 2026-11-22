"""Fetch private runtime materials using operator-provided server SSH credentials."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

ROOT=Path(__file__).resolve().parents[1]
REMOTE='/opt/robot-care-central/private/developer-handoff-20261122'


def main():
    parser=argparse.ArgumentParser(description='Server password is entered only in the OpenSSH prompt, never saved.')
    parser.add_argument('--host',required=True)
    parser.add_argument('--user',required=True)
    parser.add_argument('--port',type=int,default=22)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'runtime/private-import')
    parser.add_argument('--host-key',type=Path,default=ROOT/'deploy/server-host-key.pub')
    args=parser.parse_args()
    try:ipaddress.ip_address(args.host)
    except ValueError:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*',args.host):raise SystemExit('Invalid server host.')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*',args.user) or not 1<=args.port<=65535:
        raise SystemExit('Invalid SSH account or port.')
    scp=shutil.which('scp')
    if not scp:raise SystemExit('OpenSSH scp client is required.')
    folder=args.output_dir.resolve()
    if folder.is_relative_to(ROOT) and not folder.is_relative_to(ROOT/'runtime'):
        raise SystemExit('Private runtime files inside the project must stay under ignored runtime/.')
    folder.mkdir(parents=True,exist_ok=True)
    if os.name=='nt':
        account=subprocess.check_output(['whoami'],text=True).strip()
        subprocess.run(['icacls',str(folder),'/inheritance:r','/grant:r',account+':(OI)(CI)F','SYSTEM:(OI)(CI)F'],stdout=subprocess.DEVNULL,check=True)
    else:os.chmod(folder,0o700)
    fields=args.host_key.read_text(encoding='utf-8-sig').split()
    if len(fields)!=2 or fields[0] not in ('ssh-ed25519','ssh-rsa','ecdsa-sha2-nistp256'):
        raise SystemExit('Invalid pinned server public host key.')
    host_label=args.host if args.port==22 else f'[{args.host}]:{args.port}'
    known=folder/'server-known-hosts'
    known.write_text(host_label+' '+fields[0]+' '+fields[1]+'\n',encoding='utf-8')
    destination=folder/'runtime-private.tar.gz'
    if destination.exists():raise SystemExit('Destination exists. Choose a new --output-dir; no files overwritten.')
    host=f'[{args.host}]' if ':' in args.host else args.host
    options=[scp,'-P',str(args.port),'-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile="'+known.as_posix()+'"']
    manifest=folder/('manifest-'+uuid.uuid4().hex+'.json')
    subprocess.run([*options,args.user+'@'+host+':'+REMOTE+'/manifest.json',str(manifest)],check=True)
    expected=json.loads(manifest.read_text(encoding='utf-8'))
    temporary=folder/('runtime-private-'+uuid.uuid4().hex+'.part')
    try:
        subprocess.run([*options,args.user+'@'+host+':'+REMOTE+'/runtime-private.tar.gz',str(temporary)],check=True)
        digest=hashlib.sha256()
        with temporary.open('rb') as source:
            for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
        if temporary.stat().st_size!=expected['bytes'] or digest.hexdigest()!=expected['sha256']:
            raise SystemExit('Private archive verification failed; no final archive published.')
        os.link(temporary,destination)
        print('Verified private runtime archive: '+str(destination))
        print('No server password was stored. Inspect archive contents before restoring to a private directory.')
    finally:
        if temporary.exists():temporary.unlink()


if __name__=='__main__':main()
