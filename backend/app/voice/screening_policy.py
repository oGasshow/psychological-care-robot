"""Deployment declaration of purchase-notice coverage; no in-chat consent gate."""
from dataclasses import dataclass
import os


def collection_demo_enabled():
    requested=os.getenv('ROBOT_CARE_COLLECTION_DEMO','false').lower()
    if requested not in ('true','false'):
        raise ValueError('collection_demo_configuration_invalid')
    if requested=='false':return False
    if (os.getenv('APP_ENV','production') not in ('development','test')
            or os.getenv('ROBOT_CARE_RUNTIME_ROLE')!='collection_demo'
            or os.getenv('ROBOT_CARE_DEMO_DATABASE')!='true'):
        raise ValueError('collection_demo_requires_isolated_runtime')
    return True


def collection_targets():
    return ['PHQ-9', 'GAD-7', 'mood_interest', 'worry_anxiety', 'stress_load',
            'sleep_wellbeing', 'coping_resources', 'social_comfort']


@dataclass(frozen=True)
class CollectionPolicy:
    enabled: bool
    notice_version: str
    detector: str
    review_mode: str = 'post_session'
    demo_mode: bool = False


def collection_policy():
    enabled = os.getenv('ROBOT_CARE_GUIDED_SCREENING_ENABLED', 'false').lower()
    notice = os.getenv('ROBOT_CARE_PURCHASE_NOTICE_VERSION', '').strip()
    detector = os.getenv('ROBOT_CARE_CONCERN_DETECTOR', 'doubao_realtime')
    mode = os.getenv('ROBOT_CARE_CONCERN_REVIEW_MODE', 'post_session')
    demo=collection_demo_enabled()
    if demo:mode='live'
    if enabled not in ('true', 'false') or len(notice) > 100 or detector != 'doubao_realtime' or mode not in ('live','post_session'):
        raise ValueError('screening_configuration_invalid')
    if enabled == 'true' and not notice:
        raise ValueError('purchase_notice_version_required')
    return CollectionPolicy(enabled == 'true', notice, detector, mode, demo)
