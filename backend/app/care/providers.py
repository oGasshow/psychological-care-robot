"""Read-only assessments. No question bank, scoring or authority manufactured here."""
import json
import math
import os
from pathlib import Path
from ..models import AssessmentRecord, AssessmentTemplate
from ..robot_records import now
from robot_client.schemas import utc
from .settings import settings

def blank(source,kind,status,reason):
    return dict(source_record_id=source,source_kind=kind,is_test=kind=='fixture',
        scale_name=None,display_name=None,scale_version=None,scoring_version=None,interpretation_version=None,
        version_source=None,completed_at=None,time_source=None,total_score=None,score_min=None,score_max=None,
        reference_interpretation=None,suggestions=None,verification_status=status,reason_code=reason,
        applicability_status='demo_only' if kind=='fixture' else 'unconfirmed',content_review_status='not_reviewed',
        review_reference=None,source_version=None)

def fixture_failure(reason):
    return {'items':[],'status':'query_failed','reason_code':reason}

def valid_fixture_document(raw):
    """Validate the document envelope before reading any record fields.

    Record values such as completion, scores and versions are checked separately
    so an invalid/incomplete owned record remains distinguishable from a broken
    provider document. Unidentifiable records cannot safely be scoped to an owner.
    """
    if (not isinstance(raw,dict) or raw.get('demo_only') is not True
            or raw.get('schema_version')!='1.0' or not isinstance(raw.get('records'),list)):
        return False
    for record in raw['records']:
        if not isinstance(record,dict):
            return False
        owner=record.get('owner_user_id')
        identifier=record.get('source_record_id')
        if (type(owner) is not int or not 1<=owner<=9223372036854775807
                or not isinstance(identifier,str) or not identifier.startswith('fixture:')
                or len(identifier)<=len('fixture:') or len(identifier)>140):
            return False
    return True

def fixture(owner):
    try:
        text=Path(os.environ['ROBOT_CARE_FIXTURE_FILE']).read_text(encoding='utf-8')
    except (OSError,UnicodeError,KeyError):
        return fixture_failure('fixture_read_failed')
    try:
        raw=json.loads(text)
    except (ValueError,RecursionError):
        return fixture_failure('fixture_json_invalid')
    if not valid_fixture_document(raw):
        return fixture_failure('fixture_schema_invalid')
    items=[]
    seen=set()
    for source in raw['records']:
        if not isinstance(source,dict) or type(source.get('owner_user_id')) is not int or source['owner_user_id']!=owner:
            continue
        identifier=source.get('source_record_id')
        if not isinstance(identifier,str) or not identifier.startswith('fixture:') or len(identifier)>140:
            continue
        if identifier in seen:
            for item in items:
                if item['source_record_id']==identifier:
                    item.update(verification_status='invalid',reason_code='duplicate_source_id')
            continue
        seen.add(identifier)
        dto=blank(identifier,'fixture','invalid','invalid_fixture_record')
        try:
            if source.get('is_test') is not True:
                raise ValueError()
            for field in ('scale_name','display_name','scale_version','scoring_version','interpretation_version'):
                if not isinstance(source.get(field),str) or not 0<len(source[field])<=200:
                    raise ValueError()
                dto[field]=source[field]
            if not source.get('completed_at'):
                dto.update(verification_status='incomplete',reason_code='not_completed')
                items.append(dto)
                continue
            dto['completed_at']=utc(source['completed_at'])
            score,minimum,maximum=(source[field] for field in ('total_score','score_min','score_max'))
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in (score,minimum,maximum)) or not minimum<=score<=maximum or minimum>=maximum:
                raise ValueError()
            dto.update(total_score=score,score_min=minimum,score_max=maximum,version_source='fixture_record',
                time_source='fixture_completed_at',verification_status='verified_fixture',reason_code=None,
                content_review_status='demo_draft',review_reference='demo:not_formal_review',source_version=source['scale_version'],
                reference_interpretation=str(source.get('reference_interpretation','虚构演示分数，仅用于测试展示。')),
                suggestions=str(source.get('suggestions','可按自己的节奏记录生活感受。')))
        except (ValueError,TypeError,KeyError,OverflowError):
            dto.update(verification_status='invalid',reason_code='invalid_fixture_record',total_score=None,
                       reference_interpretation=None,suggestions=None)
        items.append(dto)
    return dict(items=items,status='available' if items else 'no_records',reason_code=None if items else 'no_records')

def live(db,owner):
    try:
        records=db.query(AssessmentRecord,AssessmentTemplate).join(AssessmentTemplate,AssessmentTemplate.id==AssessmentRecord.template_id).filter(AssessmentRecord.user_id==owner).all()
        items=[]
        for row,template in records:
            dto=blank(f'live:{row.id}','live','unverified','record_version_and_review_missing')
            dto.update(scale_name=template.scale_name,display_name=template.display_name,
                       total_score=row.total_score if type(row.total_score) is int else None)
            if row.completed_at is None:
                dto.update(verification_status='incomplete',reason_code='not_completed')
            elif row.total_score is None or type(row.total_score) is not int:
                dto.update(verification_status='invalid',reason_code='invalid_source_score')
            # Legacy schema has no historical record versions, score range,
            # confirmed timezone, applicability review or external review_reference.
            # Never substitute current template.version/created_at/interpretation.
            items.append(dto)
        return dict(items=items,status='available' if items else 'no_records',reason_code=None if items else 'no_records')
    except Exception:
        return dict(items=[],status='query_failed',reason_code='assessment_query_failed')

def assessments(db,owner):
    provider=settings().provider
    result=fixture(owner) if provider=='fixture' else live(db,owner) if provider=='live' else dict(items=[],status='disabled',reason_code='provider_disabled')
    return dict(**result,provider=provider,data_as_of=now())
