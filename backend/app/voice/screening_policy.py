"""Deployment declaration of purchase-notice coverage; no in-chat consent gate."""
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class CollectionPolicy:
    enabled: bool
    notice_version: str
    detector: str


def collection_policy():
    enabled = os.getenv('ROBOT_CARE_GUIDED_SCREENING_ENABLED', 'false').lower()
    notice = os.getenv('ROBOT_CARE_PURCHASE_NOTICE_VERSION', '').strip()
    detector = os.getenv('ROBOT_CARE_CONCERN_DETECTOR', 'doubao_realtime')
    if enabled not in ('true', 'false') or len(notice) > 100 or detector != 'doubao_realtime':
        raise ValueError('screening_configuration_invalid')
    if enabled == 'true' and not notice:
        raise ValueError('purchase_notice_version_required')
    return CollectionPolicy(enabled == 'true', notice, detector)
