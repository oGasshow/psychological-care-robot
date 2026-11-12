"""Current dialogue warnings shared by session summaries and reports.

Run independently of model/job availability. Callers must supply owned, scoped rows.
"""
from care_core import safety
from ..robot_records import RecordSession


def dialogue_danger_notice(db, rows):
    from .service import effective, exclusion
    sources=[]
    unclear=0
    sessions={}
    for row in rows:
        if exclusion(row):
            continue
        session=sessions.setdefault(row.recording_session_id, db.get(RecordSession,row.recording_session_id))
        if session is None or session.state=='deleted':
            continue
        draft=effective(db,row)
        signal=safety(draft['effective_content'])
        unclear+=signal['safety_signal']=='undetermined'
        if signal['safety_signal']=='explicit_danger_expression':
            sources.append(dict(record_id=row.id,recording_session_id=row.recording_session_id,
                occurred_at=row.occurred_at,input_revision=draft['input_revision'],is_test=bool(session.is_test),
                expressions=signal.get('matched_expressions',[]),rule_ids=signal['matched_rule_ids']))
    return dict(status='explicit_danger_expression' if sources else 'not_detected',
        count=len(sources),sources=sources,unclear_count=unclear,
        basis='当前范围内用户已完成对话的有效稿；明确危险表达规则，排除否认、引用、他人转述及明确假设。',
        action='请优先安排人工关注与核实，不能仅凭本提示作诊断或自动采取处置。',
        limitation='未检出规则内明确危险表达不代表无风险；普通消极情绪和量表分数不触发本提示。')
