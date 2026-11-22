"""Explicit process roles; central hosts storage and report reads, edge hosts computation."""
import os


def role():
    value = os.getenv('ROBOT_CARE_DEPLOYMENT_ROLE', 'standalone')
    if value not in ('standalone', 'edge', 'central'):
        raise RuntimeError('invalid_deployment_role')
    return value


def edge():
    return role() == 'edge'


def require_compute():
    if role() == 'central':
        raise RuntimeError('analysis_worker_not_allowed_on_storage_server')
