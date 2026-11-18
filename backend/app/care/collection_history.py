"""Read conversational collection separately from formal/fixture assessments."""
from copy import deepcopy
from ..robot_records import RecordMessage,RecordSession
from ..voice.screening import CollectionTrace,ScreeningResult,ITEMS,OPTIONS_BY_SCALE,core_self_report,has_collected_items
from .models import InputRevision
from .scale_catalog import session_score


def collection_history(db,owner,*,session_ids=None,allowed_record_ids=None,limit=100,session_only=False):
    query=db.query(RecordSession).filter(RecordSession.user_id==owner,RecordSession.state!='deleted',
        RecordSession.source=='doubao_realtime')
    if session_ids is not None:
        query=query.filter(RecordSession.id.in_(session_ids))
    sessions=query.order_by(RecordSession.id.desc()).limit(limit).all()
    items=[]
    for session in sessions:
        trace=db.get(CollectionTrace,session.id)
        saved=db.get(ScreeningResult,session.id)
        payload=deepcopy(saved.payload) if saved and saved.owner==owner else None
        progress=trace.payload if trace and trace.owner==owner else {}
        row=dict(snapshot_kind=(payload or progress).get('snapshot_kind'),recording_session_id=session.id,started_at=session.started_at,is_test=bool(session.is_test),
            episode_id=(payload or progress).get('episode_id'),demo_mode=bool((payload or progress).get('demo_mode')),trigger_origin=(payload or progress).get('trigger_origin'),
            source='conversation_assisted',formal_assessment=False,stage=progress.get('stage','not_recorded'),
            detector_status=progress.get('detector_status','not_recorded'),scales=[],
            observations=progress.get('observations',[]),history_session_ids=progress.get('history_session_ids',[]),
            history_danger_unresolved=progress.get('history_danger_unresolved',False),
            source_status='no_saved_collection',verification_status='unverified',
            is_closed=session.state=='closed',current_session_scores=[])
        from ..voice.demo_reconciliation import DemoAnswerReview
        job=db.get(DemoAnswerReview,session.external_session_id)
        if job and job.owner==owner:
            row['saved_answer_review']=dict(state=job.state,updated_at=job.updated_at)
        if payload:
            row.update(stage=payload.get('stage','not_recorded'),detector_status=payload.get('detector_status','not_recorded'))
        if payload and has_collected_items(payload):
            from ..voice.collection_sources import answer_records
            valid=True
            references=[]
            for scale in payload.get('scales',[]):
                current_points=[]
                options=OPTIONS_BY_SCALE.get(scale['scale'],[])
                answer_times=[];answer_sessions=set()
                for index,answer in enumerate(scale.get('items',[])):
                    if not answer:continue
                    messages,source_valid=answer_records(db,owner,session.is_test,answer)
                    answer_sessions.update(m.recording_session_id for m in messages)
                    item_valid=source_valid
                    by_id={m.id:m for m in messages}
                    by_external=({ref['message_id']:by_id.get(ref['record_id']) for ref in answer['source_refs']}
                        if answer.get('source_refs') else {m.external_message_id:m for m in messages})
                    user_refs=[by_external.get(identifier) for identifier in answer.get('evidence_ids',[])]
                    answer_times.extend(m.occurred_at for m in user_refs if m is not None)
                    context=by_external.get(answer.get('confirmation_context_id'))
                    anchor=by_external.get(answer.get('question_context_id')) or context
                    window=by_external.get(answer.get('window_context_id')) or anchor
                    direct=answer.get('confirmation_method')=='explicit_frequency_answer'
                    standalone=answer.get('confirmation_method')=='explicit_self_report'
                    if (len(user_refs)<(1 if direct or standalone else 2)
                            or any(m is None or m.role!='user' or m.text_status!='completed' for m in user_refs)):
                        item_valid=False
                    if standalone:
                        item_valid &= bool(len(user_refs)==1 and window is user_refs[0] and window is not None
                            and core_self_report(window.content)==(scale['scale'],index+1,answer['value']))
                    elif context is None or context.role!='assistant' or context.text_status!='completed':
                        item_valid=False
                    elif direct and user_refs and user_refs[0]:
                        from ..voice.screening import frequency_answer,TOPIC_CUES,question_item
                        import re
                        item_valid&=bool(anchor is not None and window is not None and anchor.role=='assistant' and window.text_status=='completed'
                            and question_item(anchor.content if re.search(r'两周|十四天|14天',anchor.content) else '最近两周，'+anchor.content,scale['scale'])==index+1
                            and frequency_answer(user_refs[0].content,OPTIONS_BY_SCALE[scale['scale']],context.content,anchor.content)==answer['value']
                            and re.search(r'两周|十四天|14天',window.content)
                            and any(cue in anchor.content for cue in TOPIC_CUES[scale['scale']][index]))
                    linked=[m.id for m in messages]
                    if allowed_record_ids is not None and not set(linked)<=allowed_record_ids:item_valid=False
                    value=answer.get('value')
                    if (item_valid and messages and all(m.recording_session_id==session.id for m in messages)
                            and type(value) is int and 0 <= value < len(options)):
                        current_points.append(value)
                    if session_only and not item_valid:
                        scale['items'][index]=None
                        continue
                    valid&=item_valid
                    references.extend(linked)
                scale['observed_at']=max(answer_times,default=None)
                scale['source_recording_session_ids']=sorted(answer_sessions)
                if session_only:
                    scale['answered']=sum(a is not None for a in scale.get('items',[]))
                if current_points and len(current_points)<=len(ITEMS[scale['scale']]):
                    row['current_session_scores'].append(session_score(scale['scale'],current_points))
            row.update(scales=payload['scales'],source_status='current_original_text' if valid else 'needs_revalidation',
                source_record_ids=sorted(set(references)))
            if not valid:
                for scale in row['scales']:
                    scale.update(total=None,status='needs_revalidation')
            else:
                for scale in row['scales']:
                    options = OPTIONS_BY_SCALE.get(scale['scale'])
                    if not options:
                        continue
                    maximum = len(options)-1
                    points = [item['value'] for item in scale.get('items',[]) if item
                              and type(item.get('value')) is int and 0 <= item['value'] <= maximum]
                    scale['partial_score'] = sum(points) if points else None
                    scale['partial_max'] = len(points)*maximum
        items.append(row)
    return items
