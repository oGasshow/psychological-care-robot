"""Own isolated short demo, preserving the normal runtime and source progress."""
import argparse
import json
from pathlib import Path
import socket
import httpx
import demo_care

PROJECT=Path(__file__).resolve().parents[2]


def preferred_port(value):
    with socket.socket() as sock:
        try:sock.bind(('127.0.0.1',value));return value
        except OSError:return demo_care.port()


def directory():
    return PROJECT/'runtime/collection_demo'


def load():
    root=directory().resolve()
    assert root.is_relative_to((PROJECT/'runtime').resolve())
    if not (root/'access.json').exists():
        demo_care.prepare(root,empty=True)
        cfg=json.loads((root/'access.json').read_text(encoding='utf-8'))
        cfg.update(collection_demo=True,sample_profile='collection_demo',
            backend_port=preferred_port(8091),frontend_port=preferred_port(3091),
            frontend_dist_dir='.next-collection-demo')
        demo_care.write_json(root/'access.json',cfg)
    cfg=json.loads((root/'access.json').read_text(encoding='utf-8'))
    if (not cfg.get('collection_demo') or cfg.get('marker')!='module236-synthetic-demo-v1'
            or Path(cfg['database']).resolve()!=root/'demo.db'
            or cfg.get('frontend_dist_dir')!='.next-collection-demo'):
        raise ValueError('refuse_non_collection_demo_runtime')
    return root,cfg


def healthy(cfg):
    try:
        with httpx.Client(trust_env=False,timeout=3) as client:
            base=f'http://127.0.0.1:{cfg["backend_port"]}'
            mode=client.get(base+'/api/robot-voice/mode')
            web=client.get(f'http://127.0.0.1:{cfg["frontend_port"]}/login')
            web_mode=client.get(f'http://127.0.0.1:{cfg["frontend_port"]}/api/robot-voice/mode')
            if not (mode.status_code==200 and isinstance(mode.json(),dict) and mode.json().get('demo_mode') is True
                    and web.status_code==200 and web_mode.status_code==200
                    and isinstance(web_mode.json(),dict) and web_mode.json().get('demo_mode') is True):return False
            login=client.post(base+'/api/auth/login',json={k:cfg['users'][0][k] for k in ('username','password')})
            return login.status_code==200
    except (httpx.RequestError,ValueError):return False


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['start','stop','status'])
    args=parser.parse_args()
    root,cfg=load()
    if args.action=='stop':
        if not demo_care.stop(root,cfg)['stopped_recorded_demo_processes']:raise SystemExit(2)
        return
    if args.action=='start' and not healthy(cfg):
        if (root/'pids.json').exists() and not demo_care.stop(root,cfg)['stopped_recorded_demo_processes']:
            raise RuntimeError('demo_process_ownership_unverified')
        demo_care.start(root,cfg)
    print(json.dumps(dict(mode='collection_demo',frontend_url=f'http://127.0.0.1:{cfg["frontend_port"]}/login',
        normal_data_unchanged=True,credentials_file=str(root/'access.json')),ensure_ascii=False))


if __name__=='__main__':main()
