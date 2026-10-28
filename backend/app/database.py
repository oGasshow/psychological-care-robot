"""Shared Xinyi database; FKs and bounded busy waits on every connection."""
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import DATABASE_URL, SQLITE_BUSY_MS

url = make_url(DATABASE_URL)
if url.get_backend_name() != 'sqlite':
    raise RuntimeError('Module24 v1 supports SQLite only')
if url.database and url.database != ':memory:':
    Path(url.database).resolve().parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(DATABASE_URL, connect_args={
    'check_same_thread': False, 'timeout': SQLITE_BUSY_MS / 1000,
}, hide_parameters=True)

@event.listens_for(engine, 'connect')
def configure_sqlite(connection, _):
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
