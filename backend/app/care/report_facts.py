"""Deterministic, revision-bound facts for the user-facing companionship report."""
from datetime import datetime, timedelta, timezone
import hashlib
import json

BJ = timezone(timedelta(hours=8))
LABELS = ('positive', 'neutral', 'negative')
TOPICS = (
    ('companionship', '独处与陪伴', ('孤独', '独处', '一个人', '陪伴'), '独处时最希望得到怎样的陪伴'),
    ('family', '家人与联系', ('家人', '孩子', '女儿', '儿子', '父母'), '最近与家人联系时的感受'),
    ('rest', '休息与睡眠', ('睡', '失眠', '休息'), '最近的休息感受和希望调整的日常安排'),
    ('daily', '日常与交流', ('散步', '公园', '朋友', '邻居', '聊天'), '最近一次让自己感到舒适的日常活动'),
)


def dt(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def group_key(group):
    return tuple(group.get(k) for k in ('engine_kind', 'engine_version', 'config_version', 'is_test'))


def selected_messages(dto):
    return [m for m in dto['messages'] if m['role'] == 'user' and m['text_status'] == 'completed'
            and m['effective_content'].strip()]


def previous_data(db, uid, scope, as_of):
    if scope.session_ids is not None:
        return None, None, 'selected_sessions'
    start, end = dt(scope.time_from), dt(scope.time_to)
    days = (end - start).total_seconds() / 86400
    local_start, local_end = start.astimezone(BJ), end.astimezone(BJ)
    if days > 93:
        return None, None, 'long_window'
    if any((v.hour, v.minute, v.second, v.microsecond) != (0, 0, 0, 0) for v in (local_start, local_end)):
        return None, None, 'partial_days'
    today = dt(as_of).astimezone(BJ).replace(hour=0, minute=0, second=0, microsecond=0)
    if local_end > today:
        return None, None, 'includes_today'
    from .reports import trends_data
    previous_scope = dict(time_from=stamp(start - (end - start)), time_to=stamp(start))
    prior = trends_data(db, uid, time_from=previous_scope['time_from'], time_to=previous_scope['time_to'],
                        include_assessments=False)
    # Include effective text and revision in the snapshot, also for unclassified records.
    from .service import effective
    prior['message_snapshot'] = [dict(role=row.role, text_status=row.text_status,
                                     occurred_at=row.occurred_at, **effective(db, row))
                                 for row in prior.pop('records')]
    return prior, previous_scope, None


def build_facts(db, uid, scope, dto):
    messages = selected_messages(dto)
    by_id = {m['record_id']: m for m in messages}
    previous, comparison_scope, comparison_reason = previous_data(db, uid, scope, dto['data_as_of'])
    previous_groups = {group_key(g): g for g in (previous or {}).get('emotion_groups', [])}
    if scope.session_ids is None:
        first = dt(scope.time_from).astimezone(BJ).date()
        last = (dt(scope.time_to) - timedelta(microseconds=1)).astimezone(BJ).date()
    elif messages:
        dates = [dt(m['occurred_at']).astimezone(BJ).date() for m in messages]
        first, last = min(dates), max(dates)
    else:
        first = last = dt(dto['data_as_of']).astimezone(BJ).date()
    day_count = (last - first).days + 1
    days = [(first + timedelta(days=i)).isoformat() for i in range(day_count)] if day_count <= 93 else []
    day_of = lambda value: dt(value).astimezone(BJ).date().isoformat()
    nature_messages = {kind: [m for m in messages if m['is_test'] is kind] for kind in (True, False)}
    all_points = {p['record_id']: p for g in dto['emotion_groups'] for p in g['points']}
    coverage = []
    for nature, rows in nature_messages.items():
        if not rows:
            continue
        valid = [m for m in rows if m['record_id'] in all_points]
        active = {day_of(m['occurred_at']) for m in rows}
        coverage.append(dict(is_test=nature, user_text_count=len(rows), classified_count=len(valid),
                             unclassified_count=len(rows) - len(valid), active_days=len(active),
                             window_days=day_count, missing_days=[d for d in days if d not in active],
                             latest_record_at=max(m['occurred_at'] for m in rows)))
    groups = []
    for group in dto['emotion_groups']:
        points = {p['record_id']: p for p in group['points']}
        counts = {label: sum(p['emotion_label'] == label for p in points.values()) for label in LABELS}
        nature_rows = nature_messages[group['is_test']]
        observed_days = {day_of(m['occurred_at']) for m in nature_rows}
        daily = []
        for day in days:
            day_points = [p for p in points.values() if day_of(p['occurred_at']) == day]
            daily.append(dict(day=day, **{k: sum(p['emotion_label'] == k for p in day_points) for k in LABELS},
                              classified_count=len(day_points), has_user_records=day in observed_days))
        prior = {p['record_id']: p for p in previous_groups.get(group_key(group), {}).get('points', [])}
        prior_counts = {k: sum(p['emotion_label'] == k for p in prior.values()) for k in LABELS}
        enough = (len(points) >= 5 and len(prior) >= 5
                  and len({day_of(p['occurred_at']) for p in points.values()}) >= 3
                  and len({day_of(p['occurred_at']) for p in prior.values()}) >= 3)
        eligible = comparison_reason is None and enough
        groups.append(dict(**{k: group[k] for k in ('engine_kind', 'engine_version', 'config_version', 'is_test')},
                           counts=counts, classified_count=len(points), daily=daily,
                           comparison=dict(eligible=eligible, reason_code=comparison_reason or (None if enough else 'insufficient_comparable_records'),
                                           previous_counts=prior_counts, previous_count=len(prior),
                                           negative_share_delta_pp=round(100 * (counts['negative'] / len(points) - prior_counts['negative'] / len(prior)), 1) if eligible else None)))
    # Excerpts are current user text only; danger remains in its independently computed area.
    danger_ids = {s['record_id'] for s in dto['danger_notice']['sources']}
    candidates = sorted((m for m in messages if m['record_id'] not in danger_ids), key=lambda m: (m['occurred_at'], m['record_id']))
    # Evenly spaced chronological sampling, rather than picking only one emotion.
    indices = sorted({round(i * (len(candidates) - 1) / 19) for i in range(20)}) if len(candidates) > 20 else range(len(candidates))
    excerpts = [dict(id=f"record:{m['record_id']}@{m['input_revision']}", record_id=m['record_id'],
                     recording_session_id=m['recording_session_id'], input_revision=m['input_revision'],
                     occurred_at=m['occurred_at'], is_test=m['is_test'], text=m['effective_content'][:400],
                     truncated=len(m['effective_content']) > 400) for i in indices for m in [candidates[i]]]
    topics = []
    for key, title, words, suggestion in TOPICS:
        # Keyword matches are descriptive topics, never diagnoses or extra emotion classes.
        sources = [e for e in excerpts if not e['truncated'] and any(w in e['text'] for w in words)]
        for nature in (True, False):
            subset = [e for e in sources if e['is_test'] is nature]
            if subset:
                topics.append(dict(key=key, title=title, is_test=nature, evidence_ids=[e['id'] for e in subset[:3]],
                                   suggestion=f'如果愿意，下次可以聊聊{suggestion}。'))
    facts = [dict(id=f'coverage:{"test" if c["is_test"] else "non_test"}', kind='coverage', **c) for c in coverage]
    facts.extend(dict(id=f'comparison:{i}', kind='classification_comparison', **g) for i, g in enumerate(groups))
    facts.append(dict(id='limitations', kind='limitations', comparison_reason=comparison_reason,
                      incomplete_sessions=any(not s['is_complete'] for s in dto['sessions']),
                      sampled=len(excerpts) < len(candidates), evidence_count=len(excerpts),
                      eligible_candidate_count=len(candidates), danger_excluded_count=len(danger_ids)))
    snapshot = dict(owner=uid, scope=dto['scope'], sessions=[{k:v for k,v in s.items() if k!='data_as_of'} for s in dto['sessions']],
                    messages=dto['messages'], sources=dto['source_references'],
                    emotion_groups=dto['emotion_groups'], danger_notice=dto['danger_notice'],
                    previous_sources=(previous or {}).get('source_references', []),
                    previous_messages=(previous or {}).get('message_snapshot', []),
                    previous_groups=(previous or {}).get('emotion_groups', []), comparison_reason=comparison_reason)
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    test_flags={m['is_test'] for m in messages}
    nature='mixed' if len(test_flags)>1 else 'test_only' if True in test_flags else 'non_test_only' if False in test_flags else 'empty'
    return dict(report_facts_version='report-facts-v1', source_snapshot_hash=digest, scope=dto['scope'],
                comparison_scope=comparison_scope, data_as_of=dto['data_as_of'], data_nature=nature,
                coverage=coverage, groups=groups, topics=topics, evidence=excerpts, facts=facts,
                evidence_selection=facts[-1], daily_status='available' if days else 'long_window',
                comparison_reason=comparison_reason, window_days=day_count,
                latest_record_at=max((m['occurred_at'] for m in messages), default=None),
                eligible_user_text_count=len(by_id))


def rules_narrative(facts, reason='model_not_configured'):
    count = facts['eligible_user_text_count']
    refs = [f['id'] for f in facts['facts'] if f['kind'] == 'coverage'] or ['limitations']
    if not count:
        overview = '这个范围还没有可纳入的用户对话，暂时无法形成近期概况。可以调整时间范围，或在有新的记录后再来回顾。'
    elif len(facts['coverage']) > 1:
        overview = '本次范围同时包含模拟和非测试标志记录，下方分别展示。可查看各自的记录覆盖、每日表达和原话，不将两类数据拼成个人变化。'
    else:
        c = facts['coverage'][0]
        overview = f"这段时间共有 {c['active_days']} 天留下对话，保存了 {c['user_text_count']} 条用户文本，其中 {c['classified_count']} 条形成有效分类。"
        titles = [t['title'] for t in facts['topics']][:3]
        overview += '原话中提到了' + '、'.join(titles) + '，下方可以查看对应记录。' if titles else '可以从下方原话继续了解当时的感受。'
        if c['unclassified_count']:
            overview += '部分文字尚未形成有效分类。'
        comparable=[g for g in facts['groups'] if g['comparison']['eligible']]
        if len(facts['groups'])==1 and comparable:
            delta=comparable[0]['comparison']['negative_share_delta_pp']
            overview += '同口径记录中，消极类别文本占比较前一周期'+('降低。' if delta<0 else '升高。' if delta>0 else '相同。')
        overview += '这些内容反映已记录的表达，不代表整体心理状态。'
    cite = lambda text, ids: dict(text=text, evidence_ids=ids)
    limitations = [cite('记录覆盖和对话长度会影响分类分布；没有记录的日期不能解释为状态正常。', refs)]
    if not any(g['comparison']['eligible'] for g in facts['groups']):
        limitations.append(cite('本次暂不作前后周期比较；需要完整时间窗及同口径、分布在不同日期的足够记录。', ['limitations']))
    return dict(mode='rules', status='ready', reason_code=reason, prompt_version='report-summary-v1',
                model=None, source_snapshot_hash=facts['source_snapshot_hash'],
                content=dict(overview=cite(overview, refs), changes=[], topics=[],
                             conversation_suggestions=[cite(t['suggestion'], t['evidence_ids']) for t in facts['topics'][:3]],
                             limitations=limitations))
