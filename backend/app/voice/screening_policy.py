"""Deployment declaration of purchase-notice coverage; no in-chat consent gate."""
from dataclasses import dataclass
import os


def collection_targets():
    return ['PHQ-9', 'GAD-7', 'mood_interest', 'worry_anxiety', 'stress_load',
            'sleep_wellbeing', 'coping_resources', 'social_comfort']


@dataclass(frozen=True)
class CollectionPolicy:
    enabled: bool
    notice_version: str
    detector: str
    review_mode: str = 'post_session'


def collection_policy():
    enabled = os.getenv('ROBOT_CARE_GUIDED_SCREENING_ENABLED', 'false').lower()
    notice = os.getenv('ROBOT_CARE_PURCHASE_NOTICE_VERSION', '').strip()
    detector = os.getenv('ROBOT_CARE_CONCERN_DETECTOR', 'doubao_realtime')
    mode = os.getenv('ROBOT_CARE_CONCERN_REVIEW_MODE', 'post_session')
    if enabled not in ('true', 'false') or len(notice) > 100 or detector != 'doubao_realtime' or mode not in ('live','post_session'):
        raise ValueError('screening_configuration_invalid')
    if enabled == 'true' and not notice:
        raise ValueError('purchase_notice_version_required')
    return CollectionPolicy(enabled == 'true', notice, detector, mode)
