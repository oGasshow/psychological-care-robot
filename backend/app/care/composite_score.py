"""16-item depression/anxiety score; coverage is not statistical confidence.

Full score: PHQ-9 + GAD-7 (PHQ-ADS reference, DOI
10.1097/PSY.0000000000000322). Partial prorating and coverage bands are explicit
project rules, not validated PHQ-ADS scoring or diagnostic probabilities.
"""
from fractions import Fraction
from decimal import Decimal, ROUND_HALF_UP
from ..robot_records import owned, summary, RecordMessage
from ..voice.screening import ScreeningResult, CollectionTrace
from .collection_history import collection_history

VERSION = 'combined-16-v1'
SIZES = {'PHQ-9': 9, 'GAD-7': 7}
REQUIRED = 16
MAXIMUM = 48
BANDS = [(0,10,'minimal','正常参考（无明显或极轻微症状）'),
         (10,20,'mild','轻度症状参考段'),
         (20,30,'moderate','中度症状参考段'),
         (30,49,'severe','重度症状参考段')]


def calculate(answers):
    """Input maps distinct (instrument, item number) to confirmed 0–3 answers."""
    points = [value for (scale, item), value in answers.items()
        if scale in SIZES and type(item) is int and 1 <= item <= SIZES[scale]
        and type(value) is int and 0 <= value <= 3]
    count, subtotal = len(points), sum(points)
    score = Fraction(subtotal*REQUIRED, count) if count else None
    display = float((Decimal(score.numerator)/Decimal(score.denominator)).quantize(
        Decimal('0.1'), rounding=ROUND_HALF_UP)) if score is not None else None
    band = next((b for b in BANDS if score is not None and b[0] <= score < b[1]), None)
    coverage = count/REQUIRED*100
    level = 'high' if coverage >= 80 else 'medium' if coverage >= 50 else 'low'
    return dict(version=VERSION, score=display, full_max=MAXIMUM, answered=count, required=REQUIRED,
        observed_score=subtotal, confidence=coverage, confidence_basis='answer_completion_rate',
        confidence_level=level, confidence_label={'high':'高','medium':'中','low':'低'}[level],
        score_kind='complete' if count == REQUIRED else 'estimated' if count else 'unavailable',
        reference_band=band[2] if band else None, reference_label=band[3] if band else None,
        possible_total_min=subtotal, possible_total_max=subtotal+3*(REQUIRED-count),
        clinical_diagnosis=False, estimate_validated=False,
        item9_attention=type(answers.get(('PHQ-9',9))) is int and 0 < answers[('PHQ-9',9)] <= 3,
        item9_answered=type(answers.get(('PHQ-9',9))) is int and 0 <= answers[('PHQ-9',9)] <= 3)


def for_sessions(db, uid, session_ids, *, allowed_record_ids=None):
    """Latest coherent task in the selected scope; never sum independent tasks."""
    sessions = [owned(db, sid, uid) for sid in dict.fromkeys(session_ids)]
    sessions = [s for s in sessions if summary(db, s)['is_complete']]
    if len({bool(s.is_test) for s in sessions}) > 1:
        return dict(calculate({}), scope_status='mixed_data_excluded')
    identifiers = [s.id for s in sessions]
    allowed = {r for (r,) in db.query(RecordMessage.id).filter(RecordMessage.recording_session_id.in_(identifiers))}
    if allowed_record_ids is not None:
        allowed &= allowed_record_ids
    rows = collection_history(db, uid, session_ids=identifiers, allowed_record_ids=allowed,
        limit=None, session_only=True, verify_current=True)
    identities = {}
    task_payloads = {}
    for row in rows:
        saved = db.get(ScreeningResult, row['recording_session_id'])
        trace = db.get(CollectionTrace, row['recording_session_id'])
        payload = saved.payload if saved and saved.owner == uid else trace.payload if trace and trace.owner == uid else {}
        episode, window = payload.get('episode_id'), payload.get('window_end')
        task_payloads[row['recording_session_id']] = payload
        identities[row['recording_session_id']] = (row['is_test'], episode, window) if episode and window else ('single',row['recording_session_id'])
    groups = {}
    for row in sorted(rows, key=lambda r:(r['started_at'],r['recording_session_id'])):
        own_items = row.get('current_session_items', [])
        pending_task = task_payloads[row['recording_session_id']].get('triggered') and row.get('stage') in ('checking_in','waiting_context','collecting','complete')
        if not row['scales'] and not own_items and not pending_task:
            continue
        group = groups.setdefault(identities[row['recording_session_id']], dict(answers={}, latest=None,used=set()))
        group['latest'] = (row['started_at'],row['recording_session_id'])
        if pending_task:
            from ..voice.screening import question_item
            questions=db.query(RecordMessage).filter(RecordMessage.recording_session_id==row['recording_session_id'],
                RecordMessage.role=='assistant',RecordMessage.text_status=='completed',RecordMessage.id.in_(allowed)).all()
            for question in questions:
                text=question.content
                if task_payloads[row['recording_session_id']].get('window_end') and not any(cue in text for cue in ('两周','十四天','14天')):
                    text='最近两周，'+text
                matches=[scale for scale in SIZES if question_item(text,scale) is not None]
                if len(matches)==1:group['used'].add(matches[0])
        for scale in row['scales']:
            for i, answer in enumerate(scale.get('items', []), 1):
                if not answer or not answer.get('source_refs'):
                    continue
                if any(identities.get(ref['recording_session_id']) != identities[row['recording_session_id']]
                        for ref in answer['source_refs']):
                    continue
                group['answers'][(scale['scale'],i)] = answer.get('value')
                group['used'].add(scale['scale'])
        for item in own_items:
            group['answers'][(item['scale_id'],item['item'])] = item['value']
            group['used'].add(item['scale_id'])
    latest = max(groups.values(), key=lambda g:g['latest'], default=None)
    answers = latest['answers'] if latest else {}
    from .scale_catalog import definition
    from ..voice.screening import ITEMS,OPTIONS_BY_SCALE
    instruments=[]
    used=set().union(*(group['used'] for group in groups.values())) if groups else set()
    for scale in dict.fromkeys([*SIZES,*sorted(used)]):
        if scale not in ITEMS:continue
        candidates=[group for group in groups.values() if scale in group['used']]
        reading=max(candidates,key=lambda group:group['latest'],default=None)
        scale_answers=reading['answers'] if reading else {}
        required=len(ITEMS[scale]);maximum=len(OPTIONS_BY_SCALE[scale])-1
        points=[v for (s,i),v in scale_answers.items() if s==scale and 1<=i<=required and type(v) is int and 0<=v<=maximum]
        if not points and not reading:
            continue
        d=definition(scale)
        instruments.append(dict(scale_id=scale,name=d['name'],kind=d['kind'],answered=len(points),required=required,
            coverage=round(len(points)/required*100,2),observed_score=sum(points),answered_max=maximum*len(points),
            status='complete' if len(points)==required else 'collecting',
            task_session_id=reading['latest'][1],included_in_combined=reading is latest))
    confirmed=[dict(scale_id=s,item=i,value=v) for (s,i),v in sorted(answers.items())
        if s in SIZES and type(i) is int and 1<=i<=SIZES[s] and type(v) is int and 0<=v<=3]
    return dict(calculate(answers), scope_status='selected_complete_sessions',instruments=instruments,confirmed_items=confirmed)
