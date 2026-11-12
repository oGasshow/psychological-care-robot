"""Namespace cross-call evidence by durable record ID, never provider ID alone."""
from ..database import SessionLocal
from ..robot_records import RecordMessage,RecordSession
from ..care.models import InputRevision

def identifiers(answer):
    return set(i for i in [*answer.get('evidence_ids',[]),answer.get('confirmation_context_id'),
        answer.get('question_context_id'),answer.get('window_context_id')] if i)

def answer_records(db,owner,is_test,answer):
    refs=answer.get('source_refs')
    query=db.query(RecordMessage).join(RecordSession,RecordSession.id==RecordMessage.recording_session_id).filter(
        RecordSession.user_id==owner,RecordSession.is_test==is_test,RecordSession.state!='deleted')
    if refs:
        records=query.filter(RecordMessage.id.in_([r['record_id'] for r in refs])).all()
        by_id={m.id:m for m in records}
        valid=identifiers(answer)=={r['message_id'] for r in refs}
        valid&=all(r['record_id'] in by_id and
            (db.get(InputRevision,r['record_id']).revision if db.get(InputRevision,r['record_id']) else 0)==r['input_revision'] for r in refs)
    else:
        # Legacy records with ambiguous IDs across calls must be revalidated.
        records=query.filter(RecordMessage.external_message_id.in_(identifiers(answer))).all()
        valid=len(records)==len(identifiers(answer))
        valid&=not any(db.get(InputRevision,m.id) and db.get(InputRevision,m.id).revision>0 for m in records)
    return records,bool(valid)

def attach_sources(uid,sid,controller,history_references):
    with SessionLocal() as db:
        session=db.get(RecordSession,sid)
        if session is None or session.user_id!=uid:return
        current={m.external_message_id:m for m in db.query(RecordMessage).filter_by(recording_session_id=sid).all()}
        for answer in controller.answers.values():
            if answer.get('source_refs'):continue
            refs=[]
            for identifier in identifiers(answer):
                row=current.get(identifier)
                if row is None and identifier in history_references:
                    row=db.get(RecordMessage,history_references[identifier]['record_id'])
                if row is None:continue
                refs.append(dict(message_id=identifier,record_id=row.id,recording_session_id=row.recording_session_id,
                    input_revision=db.get(InputRevision,row.id).revision if db.get(InputRevision,row.id) else 0))
            answer['source_refs']=refs
