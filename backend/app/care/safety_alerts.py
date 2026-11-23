"""Current source-bound reminders for manual emergency contact follow-up.

No messages/calls are sent. Acknowledgement is an audited human action and
never clears source safety evidence or converts it into a normal finding.
"""
from hashlib import sha256
import json
from ..robot_records import RecordSession,RecordMessage
from ..models import User
from .safety_notice import dialogue_danger_notice
from .service import effective,CareError


def contact_alert(db,uid,sids,*,danger=None,combined=None,personal=None):
    from ..user_profiles import report_profile
    from ..care_management import ManagementAudit
    if len(sids)>1:
        items=[dict(session_id=sid,**contact_alert(db,uid,[sid],personal=personal)) for sid in sids]
        active=[a for a in items if a['status']!='not_triggered']
        if not active:return dict(status='not_triggered',manual_contact_required=False,notification_sent=False)
        pending=any(a['status']=='pending_manual_contact' for a in active)
        return dict(status='pending_manual_contact' if pending else 'followed_up',manual_contact_required=pending,
            notification_sent=False,contact_available=active[0]['contact_available'],contact_name=active[0]['contact_name'],
            contact_phone=active[0]['contact_phone'],source_hash=sha256(''.join(a['source_hash'] for a in active).encode()).hexdigest(),
            explanation='按各会话的当前来源核对人工跟进记录；不代表短信、电话已发送。')
    rows=db.query(RecordMessage).filter(RecordMessage.recording_session_id.in_(sids)).all()
    danger=danger if danger is not None else dialogue_danger_notice(db,rows)
    if combined is None:
        from .composite_score import for_sessions
        combined=for_sessions(db,uid,sids)
    personal=personal or report_profile(db,uid)
    active=bool(danger['count']) or combined.get('item9_attention',False)
    if not active:return dict(status='not_triggered',manual_contact_required=False,notification_sent=False)
    signature=dict(danger=[{k:s[k] for k in ('record_id','recording_session_id','input_revision')} for s in danger['sources']],
        phq9=combined.get('item9_attention',False))
    if signature['phq9']:
        # A changed questionnaire source must not inherit an old acknowledgement.
        signature['source_versions']=[(r.id,effective(db,r)['input_revision']) for r in rows if r.role=='user']
    digest=sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()
    action='contact_done_'+digest[:19]
    reviewed=db.query(ManagementAudit).filter(ManagementAudit.subject_id==uid,
        ManagementAudit.session_id.in_(sids),ManagementAudit.action==action).order_by(ManagementAudit.id.desc()).first()
    return dict(status='followed_up' if reviewed else 'pending_manual_contact',manual_contact_required=not bool(reviewed),
        notification_sent=False,source_hash=digest,audit_action=action,
        contact_available=bool(personal['emergency_contact_name'] and personal['emergency_contact_phone']),
        contact_name=personal['emergency_contact_name'],contact_phone=personal['emergency_contact_phone'],
        reviewed_at=reviewed.occurred_at if reviewed else None,
        explanation='需人工核实并联系；本状态不代表短信、电话已发送。')


def pending_alerts(db,is_test=False,limit=30):
    from ..care_management import ReportManager
    from ..robot_records import summary
    from sqlalchemy import select
    sessions=db.query(RecordSession).filter(RecordSession.state!='deleted',RecordSession.is_test==is_test,
        ~RecordSession.user_id.in_(select(ReportManager.user_id))).order_by(RecordSession.id.desc()).all()
    values=[]
    for session in sessions:
        value=contact_alert(db,session.user_id,[session.id])
        if value['status']!='pending_manual_contact':continue
        person=db.get(User,session.user_id)
        if not person or not person.is_active:continue
        values.append(dict(user_id=session.user_id,username=person.username,session_id=session.id,
            occurred_at=session.ended_at or session.started_at,is_complete=summary(db,session)['is_complete'],**value))
    return dict(items=values[:limit],pending_count=len(values),is_test=is_test)


def acknowledge(db,uid,sid,mid,source_hash):
    from ..care_management import audit
    value=contact_alert(db,uid,[sid])
    if value['status']=='not_triggered' or value['source_hash']!=source_hash:raise CareError(409,'safety_sources_changed')
    if value['status']!='followed_up':audit(db,mid,value['audit_action'],uid,sid)
    db.flush()
    return dict(status='followed_up',notification_sent=False)
