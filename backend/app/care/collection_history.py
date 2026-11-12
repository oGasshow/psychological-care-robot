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
            source='conversation_assisted',formal_assessment=False,stage=progress.get('stage','not_recorded'),
            detector_status=progress.get('detector_status','not_recorded'),scales=[],
            source_status='no_saved_collection',verification_status='unverified')
        if payload:
            row.update(stage=payload.get('stage','not_recorded'),detector_status=payload.get('detector_status','not_recorded'))
        if payload and has_collected_items(payload):
            messages=db.query(RecordMessage).filter_by(recording_session_id=session.id).all()
            by_external={m.external_message_id:m for m in messages}
            edited=bool(db.query(InputRevision).join(RecordMessage,RecordMessage.id==InputRevision.record_id).filter(
                RecordMessage.recording_session_id==session.id,InputRevision.revision>0).first())
            valid=not edited
            references=[]
            for scale in payload.get('scales',[]):
                for answer in scale.get('items',[]):
                    if not answer:continue
                    user_refs=[by_external.get(identifier) for identifier in answer.get('evidence_ids',[])]
                    context=by_external.get(answer.get('confirmation_context_id'))
                    if (len(user_refs)<2 or any(m is None or m.role!='user' or m.text_status!='completed' for m in user_refs)
                            or context is None or context.role!='assistant' or context.text_status!='completed'):
                        valid=False
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
