"""Sensitive intermediate features use volatile RAM storage on edge devices."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
from .deployment import edge


def volatile_available():
    mounts=Path('/proc/mounts')
    return mounts.exists() and any(line.split()[1:3]==['/dev/shm','tmpfs'] for line in mounts.read_text().splitlines())


@contextmanager
def sensitive_directory(prefix):
    parent=None
    if edge():
        parent=Path('/dev/shm')
        if not volatile_available():
            raise RuntimeError('edge_sensitive_processing_requires_tmpfs')
    with tempfile.TemporaryDirectory(prefix=prefix,dir=parent) as value:
        os.chmod(value,0o700)
        yield value
