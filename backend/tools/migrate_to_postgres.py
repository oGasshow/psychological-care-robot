"""Copy a consistent SQLite snapshot into an EMPTY PostgreSQL database."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    if not os.environ.get('DATABASE_URL','').startswith('postgresql+psycopg://'):
        raise SystemExit('Set target DATABASE_URL securely in the process environment.')
    # No inference/backfill during migration.
    os.environ['ROBOT_CARE_DEPLOYMENT_ROLE']='central'
    from app.main import app
    from app.database import Base,engine
    from sqlalchemy import create_engine,select,func,text
    source=create_engine('sqlite:///'+args.source.resolve().as_posix())
    with source.connect() as src,engine.begin() as target:
        for table in Base.metadata.sorted_tables:
            if target.execute(select(func.count()).select_from(table)).scalar():
                raise RuntimeError('Target must be empty; existing database was not overwritten.')
        counts={}
        for table in Base.metadata.sorted_tables:
            rows=[dict(row) for row in src.execute(select(table)).mappings()]
            if rows:target.execute(table.insert(),rows)
            counts[table.name]=len(rows)
        for table in Base.metadata.sorted_tables:
            actual=target.execute(select(func.count()).select_from(table)).scalar()
            if actual!=counts[table.name]:raise RuntimeError('Migration count mismatch')
            for column in table.primary_key.columns:
                sequence=target.execute(text('SELECT pg_get_serial_sequence(:table_name,:column_name)'),
                    {'table_name':table.name,'column_name':column.name}).scalar()
                if sequence:
                    maximum=target.execute(select(func.max(column))).scalar()
                    target.execute(text('SELECT setval(CAST(:name AS regclass), :value, :used)'),
                        {'name':sequence,'value':max(maximum or 1,1),'used':maximum is not None})
    import json
    print(json.dumps({'migrated':True,'tables':len(counts),'counts':counts}))


if __name__=='__main__':main()
