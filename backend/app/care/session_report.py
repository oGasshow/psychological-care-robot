"""A public report limited to one complete, owned session."""
from hashlib import sha256
import json
import re
from types import SimpleNamespace

from ..models import User
from ..robot_records import RecordSession, now, owned, summary
from ..voice.screening import OPTIONS_BY_SCALE
from .collection_history import collection_history
from .report_facts import build_facts, rules_narrative, selected_messages
from .reports import trends_data
from .safety_notice import dialogue_danger_notice
from .scale_catalog import definition
from .service import CareError, effective, exclusion


def session_report(db, uid, sid):
    session = owned(db, sid, uid)
    if not summary(db, session)['is_complete']:
        raise CareError(409, 'report_session_incomplete')
    scope = SimpleNamespace(session_ids=[sid])
    data = trends_data(db, uid, selected=[sid], include_assessments=False)
    rows = data.pop('records')
    danger = dialogue_danger_notice(db, rows)
    stamp = now()
    report_data = dict(data, scope={'session_ids': [sid]},
        sessions=[{'is_complete': True}], danger_notice=danger,
        messages=[dict(role=row.role, text_status=row.text_status, occurred_at=row.occurred_at,
                       is_test=bool(session.is_test), **effective(db, row)) for row in rows])
    facts = build_facts(db, uid, scope, report_data)
    facts['single_session'] = True
    collections = collection_history(db, uid, session_ids=[sid],
        allowed_record_ids={row.id for row in rows}, session_only=True)
    scores = []
    for collection in collections:
        for scale in collection['scales']:
            scale_id = scale['scale']
            if scale_id not in OPTIONS_BY_SCALE:
                continue
            instrument = definition(scale_id)
            maximum = len(OPTIONS_BY_SCALE[scale_id]) - 1
            values = [a.get('value') for a in scale.get('items', []) if a]
            values = [v for v in values if type(v) is int and 0 <= v <= maximum]
            if not values or len(values) > instrument['item_count']:
                continue
            scores.append(dict(name=instrument['name'], scale_id=scale_id,
                score=sum(values), answered_max=len(values)*maximum, answered=len(values),
                required=instrument['item_count'], full_max=instrument['max_score']))
    frequencies = {}
    for label in ('从不','完全没有','较少','偶尔','有时','经常','几乎总是','有几天','超过一半的天数','几乎每天'):
        count = sum(len(re.findall(label, m['effective_content'])) for m in selected_messages(report_data))
        if count:
            frequencies[label] = count
    public = dict(username=db.get(User, uid).username, started_at=session.started_at,
        ended_at=session.ended_at, generated_at=stamp, is_test=bool(session.is_test),
        emotion_counts=data['emotion_counts'], scores=scores,
        user_turns=facts['eligible_user_text_count'], frequencies=frequencies,
        support_notice=bool(danger['count']))
    # Scores come from the application; no prior context or account metadata goes to the model.
    material = dict(scores=scores, support_notice=public['support_notice'], facts=facts['source_snapshot_hash'])
    digest = sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    facts['source_snapshot_hash'] = digest
    return dict(public, source_snapshot_hash=digest), facts


def window_report(db, uid, start, end):
    sessions = db.query(RecordSession).filter(
        RecordSession.user_id == uid, RecordSession.state == 'closed',
        RecordSession.started_at >= start, RecordSession.started_at < end).all()
    complete = [row for row in sessions if summary(db, row)['is_complete']]
    groups = []
    for is_test in (False, True):
        selected = [row.id for row in complete if bool(row.is_test) == is_test]
        if not selected:
            continue
        totals = trends_data(db, uid, selected=selected, include_assessments=False)
        groups.append(dict(is_test=is_test, conversation_count=len(selected),
            emotion_counts=totals['emotion_counts'],
            user_turns=sum(not exclusion(row) for row in totals['records'])))
    return dict(username=db.get(User, uid).username, time_from=start, time_to=end,
        generated_at=now(), groups=groups)


INTERNAL_REFERENCE = re.compile(
    r'[#＃]\s*\d+|(?:会话|记录|来源|用户|账号)(?:\s*(?:ID|编号|标识)\s*[:：]?\s*|\s*[#＃]\s*)\w+'
    r'|\b(?:session_id|record_id|source_snapshot_hash)\b', re.IGNORECASE)


def public_narrative(facts, value=None):
    value = value or rules_narrative(facts)
    content = value['content']
    overview = content['overview']['text']
    if value.get('mode') != 'model' or INTERNAL_REFERENCE.search(overview):
        topics = list(dict.fromkeys(topic['title'] for topic in facts['topics']))[:3]
        overview = ('这次对话涉及' + '、'.join(topics) + '。可以从当时最在意的一件事说起，看看它带来了怎样的感受。'
                    if topics else '这次记录反映了你在交谈时的表达。回顾时，可以留意哪些事情让你感到轻松，哪些仍需要多一点支持。')
    return dict(summary=overview,
        suggestions=[item['text'] for item in content['conversation_suggestions']
                     if not INTERNAL_REFERENCE.search(item['text'])] or
        ['可以记下一件目前最在意的事，以及当时的感受和你希望得到的支持。'])
