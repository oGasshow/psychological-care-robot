"""Shared Xinyi database; FKs and bounded busy waits on every connection."""
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import DATABASE_URL, SQLITE_BUSY_MS
from .deployment import role

url = make_url(DATABASE_URL)
kind = url.get_backend_name()
if kind not in ('sqlite', 'postgresql'):
    raise RuntimeError('unsupported_database_backend')
if role() in ('edge', 'central') and kind != 'postgresql':
    raise RuntimeError('distributed_deployment_requires_server_postgresql')
if kind == 'postgresql' and url.drivername != 'postgresql+psycopg':
    raise RuntimeError('postgresql_requires_psycopg_driver')
if kind == 'sqlite' and url.database and url.database != ':memory:':
    Path(url.database).resolve().parent.mkdir(parents=True, exist_ok=True)
sqlite_args = {
    'check_same_thread': False, 'timeout': SQLITE_BUSY_MS / 1000,
}
engine = create_engine(DATABASE_URL, connect_args=sqlite_args if kind == 'sqlite' else {'connect_timeout': 5},
    hide_parameters=True, pool_pre_ping=True, pool_recycle=300)

@event.listens_for(engine, 'connect')
def configure_sqlite(connection, _):
    if kind != 'sqlite':
        return
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute(f'PRAGMA busy_timeout={SQLITE_BUSY_MS}')
    connection.execute('PRAGMA secure_delete=ON')

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 数据库依赖注入
def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
