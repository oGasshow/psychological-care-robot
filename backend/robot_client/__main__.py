"""CLI: credentials are read from the environment, never command arguments/files."""
import argparse
import json
import os
import sys
import threading
from pathlib import Path
import httpx
from pydantic import ValidationError
from .outbox import Outbox, Transport, Worker, verified_owner
from .errors import InputValidationError, OutboxError
from .schemas import validation_details

def run():
    p = argparse.ArgumentParser(description='Robot text outbox; final events only')
    p.add_argument('--outbox', default=os.getenv('ROBOT_OUTBOX_PATH'))
    p.add_argument('--base-url', default=os.getenv('ROBOT_BASE_URL'))
    p.add_argument('--owner', type=int, default=None)
    p.add_argument('--capacity', type=int, default=10000)
    p.add_argument('--upload-policy', choices=('streaming', 'after_close'),
                   default=os.getenv('ROBOT_UPLOAD_POLICY', 'streaming'))
    sub = p.add_subparsers(dest='action', required=True)
    sub.add_parser('bind')
    sub.add_parser('upgrade')
    replay = sub.add_parser('replay')
    replay.add_argument('file', type=Path)
    sub.add_parser('work').add_argument('--once', action='store_true')
    sub.add_parser('status')
    sub.add_parser('resume').add_argument('--include-dead', action='store_true')
    sub.add_parser('purge').add_argument('external_session_id')
    args = p.parse_args()
    if args.action == 'upgrade':
        if not args.outbox:
            p.error('Set ROBOT_OUTBOX_PATH or supply --outbox')
        print(json.dumps({'schema_version': Outbox.upgrade(args.outbox), 'upgraded': True}))
        return
    if not args.outbox or not args.base_url:
        p.error('Set ROBOT_OUTBOX_PATH and ROBOT_BASE_URL or supply options')
    transport = None
    try:
        if args.action in ('bind', 'work'):
            token = os.getenv('ROBOT_TOKEN')
            if not token:
                p.error('ROBOT_TOKEN is required')
            transport = Transport(args.base_url, token, timeout=float(os.getenv('ROBOT_HTTP_TIMEOUT', '5')))
        owner = args.owner
        if args.action == 'bind':
            owner = verified_owner(transport)
        if owner is None:
            p.error('--owner is required; use bind first to verify identity')
        box = Outbox(args.outbox, args.base_url, owner, transport=transport, capacity=args.capacity,
                     upload_policy=args.upload_policy)
        if args.action == 'bind':
            print(json.dumps({'owner_user_id': owner, 'bound': True}))
        elif args.action == 'replay':
            records = json.loads(args.file.read_text(encoding='utf-8'))
            count = 0
            for record in records:
                action = record['type']
                if action == 'session':
                    if record['body'].get('is_test') is not True:
                        raise ValueError('CLI demonstration replay requires is_test=true')
                    box.create_session(record['body'])
                elif action == 'message':
                    box.enqueue(record['external_session_id'], record['body'])
                elif action == 'close':
                    box.close_session(record['external_session_id'], record['ended_at'])
                else:
                    raise ValueError('Unknown event type')
                count += 1
            print(json.dumps({'events_durably_accepted': count}))
        elif args.action == 'status':
            print(json.dumps(box.status(), ensure_ascii=False, indent=2))
        elif args.action == 'resume':
            box.resume(include_dead=args.include_dead)
            print('{"resumed":true}')
        elif args.action == 'purge':
            box.purge(args.external_session_id)
            print('{"purged":true}')
        elif args.action == 'work':
            worker = Worker(box, transport, retry_base=float(os.getenv('ROBOT_RETRY_BASE', '1')),
                            retry_cap=float(os.getenv('ROBOT_RETRY_CAP', '60')),
                            max_transient=int(os.getenv('ROBOT_MAX_TRANSIENT', '8')))
            if args.once:
                print(json.dumps({'processed': worker.step()}))
            else:
                stop = threading.Event()
                try:
                    worker.run(stop)
                except KeyboardInterrupt:
                    stop.set()
    finally:
        if transport:
            transport.close()

def main():
    try:
        run()
        return 0
    except InputValidationError as exc:
        error = {'code': exc.code, 'details': exc.details}
    except ValidationError as exc:
        error = {'code': 'validation_error', 'details': validation_details(exc)}
    except OutboxError as exc:
        error = {'code': exc.code}
    except json.JSONDecodeError:
        error = {'code': 'invalid_json'}
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        error = {'code': 'invalid_input'}
    except (OSError, httpx.HTTPError):
        error = {'code': 'io_error'}
    print(json.dumps({'error': error}, ensure_ascii=False), file=sys.stderr)
    return 1

if __name__ == '__main__':
    raise SystemExit(main())
