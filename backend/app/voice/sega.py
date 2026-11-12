"""Actual isolated SEGA inference, explicit feature gaps, no fabricated modalities."""
import asyncio,hashlib,json,os,subprocess,tempfile
from pathlib import Path
from sqlalchemy import Column,Integer,JSON,ForeignKey
from ..database import Base,SessionLocal
from ..robot_records import RecordMessage,RecordSession,owned,now
from ..care.models import InputRevision
from fastapi import HTTPException,Request

ROOT=Path(__file__).resolve().parents[3]
BACKEND=ROOT/'backend'
REQUIRED=['question_text_768','answer_text_768','aligned_answer_audio_88','emotion_probabilities_7','gender_feature']

class SegaAnalysis(Base):
    __tablename__='robot_voice_sega_analyses'
    session_id=Column(Integer,ForeignKey('robot_record_sessions.id',ondelete='CASCADE'),primary_key=True)
    owner=Column(Integer,nullable=False,index=True)
    payload=Column(JSON,nullable=False)

def config():
    python=Path(os.getenv('ROBOT_CARE_SEGA_PYTHON',str(ROOT/'runtime/sega_env/Scripts/python.exe')))
    reference=Path(os.getenv('ROBOT_CARE_SEGA_REFERENCE',str(ROOT/'runtime/sega_reference')))
    return python,reference

def status():
    python,ref=config();checkpoint=ref/'EATD/3-model/checkpoints/sega_best.pt'
    installed=python.is_file() and checkpoint.is_file() and checkpoint.stat().st_size>1000000
    return dict(engine='SEGA-EATD-author-checkpoint',installed=installed,
        status='experimental_ready' if installed else 'not_configured',required_features=REQUIRED,
        live_text_only_supported=False,automatic_questionnaire_trigger=False,
        message='已安装作者实模型；当前文字记录不能替代所需的对齐音频与辅助特征。' if installed else 'SEGA 运行环境或作者权重未配置。')

def execute(*,fixture=False,features=None):
    python,ref=config()
    if not status()['installed']:return dict(status='not_configured')
    args=[str(python),'-X','utf8',str(BACKEND/'tools/sega_infer.py'),'--reference',str(ref)]
    args+=['--fixture'] if fixture else ['--features',str(features)]
    # Model worker never needs application/cloud credentials.
    env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('KEY','TOKEN','PASSWORD','SECRET','DATABASE_URL'))}
    try:
        result=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',
            errors='replace',timeout=150,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        value=json.loads(result.stdout.strip().splitlines()[-1])
        if value.get('status') not in ('succeeded','failed'):raise ValueError()
        return value
    except (OSError,ValueError,IndexError,subprocess.TimeoutExpired):return dict(status='failed',error_type='sega_execution_unavailable')

def session_status(uid,sid):
    with SessionLocal() as db:
        owned(db,sid,uid);row=db.get(SegaAnalysis,sid)
        result=dict(row.payload) if row and row.owner==uid else None
        if result and any((db.get(InputRevision,int(identifier)).revision if db.get(InputRevision,int(identifier)) else 0)!=revision
                for identifier,revision in result.get('input_revisions',{}).items()):
            result={k:v for k,v in result.items() if k not in ('model_class','logits')}
            result.update(status='needs_revalidation',reason='source_text_changed')
        return dict(**status(),result=result,
            input_status='available_experimental_features' if row else 'missing_aligned_audio_and_auxiliary_features')

async def analyze_features(uid,sid,request:Request):
    with SessionLocal() as db:owned(db,sid,uid)
    # Incremental bound avoids loading a hostile request body before checking size.
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>16*1024*1024:raise HTTPException(413,'feature_bundle_too_large')
    if not data.startswith(b'PK'):raise HTTPException(422,'npz_required')
    import io,zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            if sum(i.file_size for i in bundle.infolist())>64*1024*1024 or len(bundle.infolist())>10:
                raise ValueError()
    except (ValueError,zipfile.BadZipFile):raise HTTPException(422,'npz_size_or_structure_invalid') from None
    with tempfile.TemporaryDirectory(prefix='care-sega-') as temporary:
        file=Path(temporary)/'features.npz';file.write_bytes(data)
        result=await asyncio.to_thread(execute,features=file)
    if result['status']!='succeeded':raise HTTPException(422,'sega_features_or_runtime_invalid')
    result.update(analyzed_at=now(),feature_sha256=hashlib.sha256(data).hexdigest())
    with SessionLocal() as db:
        owned(db,sid,uid)
        identifiers=[*result.get('record_ids',[]),*result.get('question_record_ids',[])]
        records=db.query(RecordMessage).filter(RecordMessage.recording_session_id==sid,RecordMessage.id.in_(identifiers),
            RecordMessage.text_status=='completed').all()
        by_id={r.id:r for r in records}
        if (len(result.get('record_ids',[]))!=3 or len(result.get('question_record_ids',[]))!=3
                or any(by_id.get(i) is None or by_id[i].role!='user' for i in result['record_ids'])
                or any(by_id.get(i) is None or by_id[i].role!='assistant' for i in result['question_record_ids'])):
            raise HTTPException(422,'owned_question_answer_sources_required')
        result['input_revisions']={str(i):(db.get(InputRevision,i).revision if db.get(InputRevision,i) else 0) for i in set(identifiers)}
        db.merge(SegaAnalysis(session_id=sid,owner=uid,payload=result));db.commit()
        is_test=bool(db.get(RecordSession,sid).is_test)
        evidence=[by_id[i].external_message_id for i in result['record_ids']]
    if result['model_class']==1:
        from .screening_policy import collection_policy
        from .screening import Screening
        from .collection_plan import read_plan,restore,store_plan
        try:policy=collection_policy()
        except ValueError:policy=None
        if policy and policy.enabled:
            controller=Screening(True,policy.notice_version)
            restore(controller,read_plan(uid,is_test))
            if controller.stage=='companionship':controller.concern(evidence,result['engine'],['PHQ-9'])
            controller.history_session_ids=list(dict.fromkeys([*controller.history_session_ids,sid]))
            store_plan(uid,is_test,controller)
            result['followup_task_created']=True
            result['followup_task_note']='实验信号仅建立待进一步了解任务，后续先核对当前对话时机，不直接施测或作诊断。'
    return result
