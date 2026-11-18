"""A public report limited to one complete, owned session."""
from hashlib import sha256
import json
import re
from types import SimpleNamespace

from ..models import User
from ..robot_records import RecordSession, now, owned, summary
from .collection_history import collection_history
from .report_facts import build_facts, rules_narrative, selected_messages
from .reports import trends_data
from .safety_notice import dialogue_danger_notice
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
    scores = [score for collection in collections for score in
              (*collection['checkin_scores'], *collection['current_session_scores'])]
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
ACTION_PHRASE = re.compile(
    r'(?:^|[，、：])\s*(?:建议|不妨|试着|下一步|如果愿意|下次可以)'
    r'|(?:可以|尝试|建议)\s*(?:先|把|去|从|找|跟|和|记录|联系|安排|留意|写|做|给|尝试|试着|考虑|选择|你|您)')
ACTION_START = re.compile(
    r'^(?:如果愿意[，,]\s*)?(?:下次|接下来|今天)?'
    r'(?:建议你|建议您|建议|可以|不妨)?(?:先|试着|尝试|去)*'
    r'(?:在[^，。；？！]{1,14}?(?:时|期间|间隙|前|后)[，,]?\s*)?'
    r'(?:把|记下|记录|写下|拆分|选择|安排|留意|回顾|问问|找|联系|约|聊聊|说说|'
    r'列出|整理|留出|散步|休息|给自己|(?:和|与|跟).{1,24}(?:说说|聊聊|散步))')


def public_narrative(facts, value=None):
    value = value or rules_narrative(facts)
    content = value['content']
    overview = content['overview']['text']
    if value.get('mode') == 'model':
        observations = [sentence for sentence in re.split(r'(?<=[。！？；])', overview)
                        if not ACTION_PHRASE.search(sentence) and not ACTION_START.match(sentence.strip())
                        and not INTERNAL_REFERENCE.search(sentence)]
        overview = ''.join(observations).strip()
    if value.get('mode') != 'model' or not overview:
        topics = list(dict.fromkeys(topic['title'] for topic in facts['topics']))[:3]
        overview = ('这次对话涉及' + '、'.join(topics) + '。'
                    if topics else '本次记录反映了交谈当时的表达，提供了一段近况的初步线索。')
    suggestions = []
    for item in content['conversation_suggestions']:
        for sentence in re.split(r'(?<=[。！？；])', item['text']):
            sentence = sentence.strip()
            if (ACTION_START.match(sentence) and not INTERNAL_REFERENCE.search(sentence)
                    and sentence.strip('。！？；') not in overview and sentence not in suggestions):
                suggestions.append(sentence)
    return dict(summary=overview, suggestions=suggestions[:3] or
                ['可以记下一件目前最在意的事，以及当时的感受和你希望得到的支持。'])
