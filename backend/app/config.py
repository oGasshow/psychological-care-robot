"""Load configuration before database, JWT and model objects are constructed."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./data/xinyi.db')
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError('Set SECRET_KEY to at least 32 characters before startup')
SQLITE_BUSY_MS = int(os.getenv('SQLITE_BUSY_MS', '1000'))
