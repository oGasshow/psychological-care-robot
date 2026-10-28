"""Additive upgrade, SQLite online backup, restore to a NEW destination, OpenAPI."""
import argparse
import json
import os
import sqlite3
from pathlib import Path

def backup(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError('Source database missing')
    if destination.exists():
        raise ValueError('Destination exists; choose a new path')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # URI read-only mode prevents an incorrect source path from creating a database.
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or dst.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Backup integrity check failed')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['upgrade', 'backup', 'restore', 'openapi', 'check'])
    p.add_argument('--db', type=Path, required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--source', type=Path)
    args = p.parse_args()
    if args.action in ('backup', 'restore'):
        if args.action == 'backup':
            if not args.output:
                p.error('--output required')
            backup(args.db, args.output)
        else:
            if not args.source:
                p.error('--source required')
            backup(args.source, args.db)
        print(json.dumps({'operation': args.action, 'integrity_check': 'ok'}))
        return
    if args.action == 'check':
        with sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True) as db:
            result = db.execute('PRAGMA integrity_check').fetchone()[0]
            fks = db.execute('PRAGMA foreign_key_check').fetchall()
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'")]
            counts = {t: db.execute('SELECT count(*) FROM "' + t.replace('"', '""') + '"').fetchone()[0] for t in tables}
            print(json.dumps({'integrity_check': result, 'foreign_key_violations': len(fks), 'row_counts': counts}))
            if result != 'ok' or fks:
                raise SystemExit(1)
        return
    os.environ['DATABASE_URL'] = 'sqlite:///' + args.db.resolve().as_posix()
    from app.main import app
    if args.action == 'openapi':
        if not args.output:
            p.error('--output required')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'operation': args.action, 'success': True}))

if __name__ == '__main__':
    main()
