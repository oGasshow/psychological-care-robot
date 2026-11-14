"""Read conversational collection separately from formal/fixture assessments."""
from copy import deepcopy
from ..robot_records import RecordMessage,RecordSession
from ..voice.screening import CollectionTrace,ScreeningResult,has_collected_items
from .models import InputRevision


def collection_history(db,owner,*,session_ids=None,allowed_record_ids=None,limit=100):
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
        row=dict(recording_session_id=session.id,started_at=session.started_at,is_test=bool(session.is_test),
            demo_mode=bool((payload or progress).get('demo_mode')),trigger_origin=(payload or progress).get('trigger_origin'),
            source='conversation_assisted',formal_assessment=False,stage=progress.get('stage','not_recorded'),
            detector_status=progress.get('detector_status','not_recorded'),scales=[],
            observations=progress.get('observations',[]),history_session_ids=progress.get('history_session_ids',[]),
            history_danger_unresolved=progress.get('history_danger_unresolved',False),
            source_status='no_saved_collection',verification_status='unverified')
        if row['demo_mode']:
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
                for index,answer in enumerate(scale.get('items',[])):
                    if not answer:continue
                    messages,source_valid=answer_records(db,owner,session.is_test,answer)
                    valid&=source_valid
                    by_id={m.id:m for m in messages}
                    by_external=({ref['message_id']:by_id.get(ref['record_id']) for ref in answer['source_refs']}
                        if answer.get('source_refs') else {m.external_message_id:m for m in messages})
                    user_refs=[by_external.get(identifier) for identifier in answer.get('evidence_ids',[])]
                    context=by_external.get(answer.get('confirmation_context_id'))
                    direct=answer.get('confirmation_method')=='explicit_frequency_answer'
                    if (len(user_refs)<(1 if direct else 2) or any(m is None or m.role!='user' or m.text_status!='completed' for m in user_refs)
                            or context is None or context.role!='assistant' or context.text_status!='completed'):
                        valid=False
                    if direct and user_refs and user_refs[0] and context:
                        from ..voice.screening import frequency_answer,OPTIONS_BY_SCALE,TOPIC_CUES
                        import re
                        valid&=bool(row['demo_mode'] and scale['scale']=='mood_interest'
                            and frequency_answer(user_refs[0].content,OPTIONS_BY_SCALE[scale['scale']],context.content)==answer['value']
                            and re.search(r'两周|十四天',context.content)
                            and any(cue in context.content for cue in TOPIC_CUES[scale['scale']][index]))
                    linked=[m.id for m in [*user_refs,context] if m is not None]
                    if allowed_record_ids is not None and not set(linked)<=allowed_record_ids:valid=False
                    references.extend(linked)
            row.update(scales=payload['scales'],source_status='current_original_text' if valid else 'needs_revalidation',
                source_record_ids=sorted(set(references)))
            if not valid:
                for scale in row['scales']:
                    scale.update(total=None,status='needs_revalidation')
        items.append(row)
    return items
