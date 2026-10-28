from typing import Annotated
from fastapi import APIRouter,Depends,Request,Response,Query
from fastapi.responses import JSONResponse
from pydantic import Field,StrictInt,model_validator,field_validator
from sqlalchemy import func
from ..robot_records import owner,owned,transaction,RecordMessage,RecordSession,ResourceID,PageLimit,encode_cursor,decode_cursor,now
from robot_client.schemas import StrictBody,ID,UTCText
from .models import AnalysisJob,SupportPolicy,StrategyDelivery
from .service import CareError,profile,record,enqueue,job_view,correct,effective,simulate,delivery_view,policy_view,session_status,exclusion,missing
from .reports import report,trends_data
from .providers import assessments
from .settings import settings

PositiveID=Annotated[StrictInt,Field(ge=1,le=9223372036854775807)]
class JobBody(StrictBody):
    record_id:PositiveID
class CorrectionBody(StrictBody):
    request_id:ID
    base_revision:Annotated[StrictInt,Field(ge=0,le=2147483647)]
    content:Annotated[str,Field(strict=True,min_length=1,max_length=8000)]
    @field_validator('content')
    @classmethod
    def valid_content(cls,value):
        if not value.strip():
            raise ValueError('nonempty_content_required')
        try:
            value.encode('utf-8')
        except UnicodeError:
            raise ValueError('valid_unicode_required') from None
        return value
class SimulationBody(StrictBody):
    policy_id:PositiveID
    request_id:ID
class ReportScope(StrictBody):
    session_ids:Annotated[list[PositiveID],Field(min_length=1,max_length=50)]|None=None
    time_from:UTCText|None=None
    time_to:UTCText|None=None
    @model_validator(mode='after')
    def scope_valid(self):
        if self.session_ids is not None:
            if self.time_from is not None or self.time_to is not None or len(set(self.session_ids))!=len(self.session_ids):
                raise ValueError('exclusive_scope_required')
        elif not self.time_from or not self.time_to or self.time_from>=self.time_to:
            raise ValueError('valid_paired_time_range_required')
        return self
class ReportBody(StrictBody):
    scope:ReportScope

def check_query(request:Request):
    allowed={'limit','cursor'} if request.url.path.endswith('/analyses') else {'from','to'} if request.url.path.endswith('/trends') else set()
    if any(key not in allowed for key in request.query_params):
        raise CareError(422,'validation_error')
    if any(len(request.query_params.getlist(key))>1 for key in allowed):
        raise CareError(422,'validation_error')

router=APIRouter(prefix='/api/robot-insights',tags=['Robot care 2.3/2.6'],dependencies=[Depends(check_query)],responses={
    code:{'description':description} for code,description in {401:'authentication_required / invalid_token',403:'account_disabled',
        404:'not_found',409:'revision_conflict / correction_conflict / input_version_conflict / delivery_conflict',
        410:'session_deleted',422:'validation_error / excluded_input / invalid_cursor',503:'storage_busy'}.items()})

@router.get('/profile')
def get_profile(uid=Depends(owner)):
    with transaction(True) as db:
        return profile(db,uid)

@router.post('/analysis-jobs',status_code=202,responses={200:{'description':'Same version task'}})
def post_job(body:JobBody,response:Response,uid=Depends(owner)):
    with transaction(True) as db:
        row,_=record(db,body.record_id,uid)
        job,duplicate=enqueue(db,row,uid)
        result=job_view(db,job)
    response.status_code=200 if duplicate else 202
    return result

@router.get('/analysis-jobs/{job_id}')
def get_job(job_id:ResourceID,uid=Depends(owner)):
    with transaction() as db:
        job=db.query(AnalysisJob).filter_by(id=job_id,owner=uid).first()
        if job is None:
            missing(db,'job',job_id,uid)
        owned(db,job.session_id,uid)
        return job_view(db,job)

@router.get('/sessions/{sid}/analyses')
def get_analyses(sid:ResourceID,limit:Annotated[PageLimit,Query()]=50,cursor:str|None=None,uid=Depends(owner)):
    with transaction() as db:
        owned(db,sid,uid)
        scope=f'insights:{sid}:jobs:asc'
        q=db.query(AnalysisJob).filter_by(owner=uid,session_id=sid)
        snapshot,after=decode_cursor(cursor,uid,scope) if cursor is not None else (q.with_entities(func.max(AnalysisJob.id)).scalar() or 0,0)
        jobs=q.filter(AnalysisJob.id<=snapshot,AnalysisJob.id>after).order_by(AnalysisJob.id).limit(limit+1).all()
        more=len(jobs)>limit
        jobs=jobs[:limit]
        excluded=[dict(record_id=row.id,sequence_no=row.sequence_no,reason_code=exclusion(row),classification_status='excluded')
                  for row in db.query(RecordMessage).filter_by(recording_session_id=sid) if exclusion(row)]
        return dict(items=[job_view(db,j) for j in jobs],snapshot_max_id=snapshot,
                    next_cursor=encode_cursor(uid,scope,snapshot,jobs[-1].id) if more else None,excluded_records=excluded)

@router.get('/sessions/{sid}/summary')
def get_summary(sid:ResourceID,uid=Depends(owner)):
    with transaction() as db:
        return session_status(db,owned(db,sid,uid))

@router.get('/messages/{record_id}/effective')
def get_effective(record_id:ResourceID,uid=Depends(owner)):
    with transaction() as db:
        row,_=record(db,record_id,uid)
        return effective(db,row)

@router.post('/messages/{record_id}/corrections',status_code=201,responses={200:{'description':'Idempotent correction'}})
def post_correction(record_id:ResourceID,body:CorrectionBody,response:Response,uid=Depends(owner)):
    with transaction(True) as db:
        row,_=record(db,record_id,uid)
        result,duplicate=correct(db,row,uid,body)
    response.status_code=200 if duplicate else 201
    return result

@router.get('/policies/{policy_id}')
def get_policy(policy_id:ResourceID,uid=Depends(owner)):
    with transaction() as db:
        row=db.query(SupportPolicy).filter_by(id=policy_id,owner=uid).first()
        if row is None:
            missing(db,'policy',policy_id,uid)
        owned(db,row.session_id,uid)
        return policy_view(db,row)

@router.post('/strategy-deliveries/simulate',status_code=201,responses={200:{'description':'Idempotent simulator receipt'}})
def post_simulate(body:SimulationBody,response:Response,uid=Depends(owner)):
    with transaction(True) as db:
        result,duplicate=simulate(db,uid,body)
    response.status_code=200 if duplicate else 201
    return result

@router.get('/strategy-deliveries/{delivery_id}')
def get_delivery(delivery_id:ResourceID,uid=Depends(owner)):
    if not settings().simulator:
        raise CareError(404,'not_found')
    with transaction() as db:
        row=db.query(StrategyDelivery).filter_by(id=delivery_id,owner=uid).first()
        if row is None:
            missing(db,'delivery',delivery_id,uid)
        owned(db,row.session_id,uid)
        return delivery_view(row)

@router.get('/assessments')
def get_assessments(uid=Depends(owner)):
    with transaction() as db:
        return assessments(db,uid)

@router.get('/trends')
def get_trends(time_from:Annotated[UTCText|None,Query(alias='from')]=None,time_to:Annotated[UTCText|None,Query(alias='to')]=None,uid=Depends(owner)):
    if time_from and time_to and time_from>=time_to:
        raise CareError(422,'validation_error')
    with transaction() as db:
        result=trends_data(db,uid,time_from=time_from,time_to=time_to)
        result.pop('records')
        return result

@router.post('/reports/preview')
def preview_report(body:ReportBody,uid=Depends(owner)):
    with transaction(True) as db:
        return report(db,uid,body.scope)

def install(app):
    @app.exception_handler(CareError)
    async def care_error(request,exc):
        return JSONResponse(status_code=exc.status,content={'error':{'code':exc.code,'message':exc.code,'retryable':exc.status==503}},headers={'Cache-Control':'no-store'})
    @app.middleware('http')
    async def no_cache(request,call_next):
        response=await call_next(request)
        if request.url.path.startswith('/api/robot-insights'):
            response.headers['Cache-Control']='no-store'
        return response
    app.include_router(router)
