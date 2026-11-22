"""Evidence-based account follow-up state, separate from questionnaire progress."""
from datetime import datetime, timedelta, timezone
import os

from ..robot_records import RecordMessage, RecordSession, transaction
from ..care.models import InputRevision

LABELS = {'routine': '常规陪伴', 'followup': '待进一步了解', 'high_concern': '筛查高关注'}


def review_days():
    return int(os.getenv('ROBOT_CARE_REASSESSMENT_DAYS', '14'))


def recent_completion(plan):
    if not plan or plan.get('needs_collection') or not plan.get('completed_at'):
        return False
    days = review_days()
    if not 1 <= days <= 90:
        raise ValueError('reassessment_days_invalid')
    return datetime.fromisoformat(plan['completed_at'].replace('Z', '+00:00')) + timedelta(days=days) > datetime.now(timezone.utc)


def automatic_review_status(db, session):
    """Experimental audio features require independent, current user evidence."""
    from .after_call import AfterCallReview
    review=db.get(AfterCallReview,session.id)
    if not review or review.owner != session.user_id or review.state != 'succeeded':
        return 'pending_source_review'
    result=review.result or {}
    if result.get('decision') != 'follow_up' or 'PHQ-9' not in result.get('target_scales',[]):
        return 'not_supported_by_user_evidence'
    domains={}
    for ref in result.get('support_refs',[]):
        row=db.get(RecordMessage,ref['record_id'])
        if (row is None or row.recording_session_id != session.id or row.role != 'user'
                or row.text_status != 'completed'):
            continue
        version=db.get(InputRevision,row.id)
        if (version.revision if version else 0) != ref['input_revision']:
            return 'source_changed'
        domains[row.id]=ref['domain']
    if len(domains)<2 or not {'low_mood','interest'}.intersection(domains.values()):
        return 'not_supported_by_user_evidence'
    return 'supported_by_user_evidence'


def positive_source(db, uid, is_test, after=None):
    from .sega import SegaAnalysis
    from .sega_live import SegaVoiceJob
    sources = []
    for table in (SegaVoiceJob, SegaAnalysis):
        for row, session in db.query(table, RecordSession).join(RecordSession,
                RecordSession.id == table.session_id).filter(table.owner == uid, RecordSession.user_id == uid,
                    RecordSession.is_test == is_test, RecordSession.state != 'deleted').all():
            result = row.result if table is SegaVoiceJob else row.payload
            if (table is SegaVoiceJob and row.state != 'succeeded') or not result or result.get('model_class') != 1:
                continue
            if (result.get('source_kind') == 'automatic_voice_experimental'
                    and automatic_review_status(db,session) != 'supported_by_user_evidence'):
                continue
            # A late result from an already assessed conversation cannot reopen it.
            if after and datetime.fromisoformat((session.ended_at or session.started_at).replace('Z','+00:00')) <= datetime.fromisoformat(after.replace('Z','+00:00')):
                continue
            revisions = result.get('input_revisions')
            identifiers = result.get('record_ids', []) + result.get('question_record_ids', [])
            if not revisions or not identifiers or set(map(int, revisions)) != set(identifiers):
                continue
            rows = db.query(RecordMessage).filter(RecordMessage.recording_session_id == session.id,
                                                RecordMessage.id.in_(identifiers)).all()
            if len(rows) != len(set(identifiers)):
                continue
            if any((db.get(InputRevision, rid).revision if db.get(InputRevision, rid) else 0) != version
                   for identifier, version in revisions.items() for rid in [int(identifier)]):
                continue
            sources.append(session)
    return max(sources, key=lambda row: (row.ended_at or row.started_at, row.id), default=None)


def profile_in_db(db, uid, is_test, *, plan=None):
    from .collection_plan import read_plan_in_db
    from .collection_sources import answer_records,identifiers
    from .screening import ITEMS, OPTIONS_BY_SCALE, ScreeningResult
    from ..care.collection_history import collection_history
    from ..care.scale_catalog import summarize

    if plan is None:
        plan = read_plan_in_db(db, uid, is_test)
    threshold = int(os.getenv('ROBOT_CARE_PHQ_FOLLOWUP_THRESHOLD', '10'))
    if not 1 <= threshold <= 27:
        raise ValueError('phq_followup_threshold_invalid')
    assessment = None
    # Retain a previous valid complete result while a later task is unfinished.
    history = collection_history(db, uid, verify_current=True, limit=None,
        session_ids=db.query(ScreeningResult.session_id).filter_by(owner=uid))
    for row in history:
        session=db.get(RecordSession,row['recording_session_id'])
        if session is None or session.is_test is not is_test or row.get('demo_mode'):
            continue
        phq = next(s for s in summarize([row]) if s['scale_id'] == 'PHQ-9')
        if phq['status'] == 'complete':
            observed=next(s.get('observed_at') for s in row['scales'] if s['scale']=='PHQ-9')
            candidate = dict(score=phq['score'], completed_at=observed or row['started_at'],
                             safety_attention=phq['item9_attention'], source_session_ids=phq['recording_session_ids'])
            if assessment is None or candidate['completed_at'] > assessment['completed_at']:
                assessment = candidate
    if plan and not plan.get('demo_mode'):
        answers = [plan.get('answers', {}).get(f'PHQ-9:{i}') for i in range(1, 10)]
        if all(answers) and all(type(a.get('value')) is int and 0 <= a['value'] <= 3
                               and identifiers(a) and answer_records(db, uid, is_test, a)[1] for a in answers):
            candidate = dict(score=sum(a['value'] for a in answers),
                             completed_at=plan.get('completed_at') or plan['updated_at'],
                             safety_attention=answers[8]['value'] > 0,
                             source_session_ids=sorted({row.recording_session_id for a in answers
                                 for row in answer_records(db,uid,is_test,a)[0]}))
            if assessment is None or candidate['completed_at'] >= assessment['completed_at']:
                assessment = candidate
    source = None if recent_completion(plan) else positive_source(db, uid, is_test, assessment['completed_at'] if assessment else None)
    pending = bool(plan and plan.get('needs_collection'))
    high = bool(assessment and assessment['score'] >= threshold)
    care = 'high_concern' if high else 'followup' if pending or source else 'routine'
    scales = []
    if plan:
        for scale in plan.get('target_scales', []):
            answers = [plan.get('answers', {}).get(f'{scale}:{i}') for i in range(1, len(ITEMS[scale]) + 1)]
            points = [a['value'] for a in answers if a]
            maximum = len(OPTIONS_BY_SCALE[scale]) - 1
            scales.append(dict(scale=scale, answered=len(points), required=len(answers),
                coverage=round(len(points)/len(answers), 4), partial_score=sum(points),
                possible_total_min=sum(points), possible_total_max=sum(points)+(len(answers)-len(points))*maximum))
    return dict(care_status=care, care_label=LABELS[care], marked=care != 'routine',
        source_session_id=source.id if source else (assessment['source_session_ids'][-1] if high and assessment['source_session_ids'] else None), is_test=is_test,
        assessment=assessment, collection_status=plan['status'] if plan else 'no_task',
        needs_collection=pending or bool(source and not recent_completion(plan)), scales=scales,
        recheck_after=(datetime.fromisoformat(assessment['completed_at'].replace('Z','+00:00'))+
                      timedelta(days=review_days())).isoformat() if assessment else None,
        safety_attention=bool(assessment and assessment['safety_attention']) or bool(plan and plan.get('history_danger_unresolved')),
        threshold=threshold, clinical_diagnosis=False)


def profile(uid, is_test):
    with transaction() as db:
        return profile_in_db(db, uid, is_test)


def instructions(value):
    if value['care_status'] == 'high_concern':
        return ('已有完整的对话辅助筛查结果提示需要更多关注。开场先问候，适度主动关心近况，认真回应当前感受，'
                '避免连续追问、诊断或宣称康复，适宜时鼓励专业支持；本轮量表已完成时继续自然陪伴。')
    if value['needs_collection']:
        return '有尚未完成的信息整理任务。先自然问候和回应当下话题，合适时再继续未答方向，尊重暂停，不重复已答项。'
    return '先自然问候并围绕用户当前想聊的事情陪伴。已经完成的本轮信息整理不重复发起。'
