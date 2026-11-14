from collections import defaultdict
from ..robot_records import RecordMessage,RecordSession,now,owned
from .models import AnalysisJob
from .service import current,job_view,effective,profile,exclusion,session_status
from .providers import assessments

NATURE='本系统为辅助陪伴设备，非专业心理咨询师或医疗服务设备；文本与量表展示不作确定性诊断。'

def valid_assessment(item):
    return item['verification_status'] in ('verified_fixture','verified_live') and item['completed_at'] is not None

def source_nature(record_flags,assessment_items):
    summary={name:{'test':0,'non_test':0} for name in ('dialogue','assessments')}
    for flag in record_flags:
        summary['dialogue']['test' if flag else 'non_test']+=1
    for item in assessment_items:
        summary['assessments']['test' if item['is_test'] else 'non_test']+=1
    tests=sum(part['test'] for part in summary.values())
    non_tests=sum(part['non_test'] for part in summary.values())
    nature='mixed' if tests and non_tests else 'test_only' if tests else 'non_test_only' if non_tests else 'empty'
    return dict(data_nature=nature,data_nature_summary=summary,is_test=nature=='test_only',
        data_nature_notice={
            'test_only':'纳入来源均带测试标志，仅用于模拟展示。',
            'non_test_only':'纳入来源均带非测试标志；该标志不代表真实来源或评估有效性已确认。',
            'mixed':'包含测试与非测试标志来源，分别统计并形成独立趋势，不将测试数据作为非测试历史。',
            'empty':'当前范围暂无纳入来源，未推定为模拟或真实记录。'}[nature])

def trends_data(db,uid,*,selected=None,time_from=None,time_to=None,include_assessments=True):
    query=db.query(RecordMessage).join(RecordSession,RecordSession.id==RecordMessage.recording_session_id).filter(RecordSession.user_id==uid,RecordSession.state!='deleted')
    if selected is not None:
        query=query.filter(RecordMessage.recording_session_id.in_(selected))
    if time_from:
        query=query.filter(RecordMessage.occurred_at>=time_from)
    if time_to:
        query=query.filter(RecordMessage.occurred_at<time_to)
    entries=query.with_entities(RecordMessage,RecordSession.is_test).order_by(RecordMessage.occurred_at,RecordMessage.id).all()
    records=[row for row,_ in entries]
    record_flags={row.id:bool(is_test) for row,is_test in entries}
    emotion=defaultdict(list)
    counts={key:0 for key in ('positive','neutral','negative')}
    nature_counts={kind:dict(counts) for kind in ('test','non_test')}
    statuses={key:0 for key in ('pending','running','retry_wait','failed','unable_to_determine','excluded','invalidated','succeeded')}
    sources=[]
    for row in records:
        is_test=record_flags[row.id]
        if exclusion(row):
            statuses['excluded']+=1
            sources.append({'record_id':row.id,'recording_session_id':row.recording_session_id,'sequence_no':row.sequence_no,
                            'occurred_at':row.occurred_at,'is_test':is_test,'status':'excluded','reason_code':exclusion(row)})
            continue
        jobs=db.query(AnalysisJob).filter_by(record_id=row.id).order_by(AnalysisJob.id.desc()).all()
        statuses['invalidated']+=sum(j.state=='invalidated' for j in jobs)
        job=next((j for j in jobs if current(db,j)),None)
        source=dict(record_id=row.id,recording_session_id=row.recording_session_id,sequence_no=row.sequence_no,
                    occurred_at=row.occurred_at,is_test=is_test,input_revision=effective(db,row)['input_revision'])
        if not job:
            statuses['pending']+=1
            sources.append(dict(source,status='not_analyzed'))
            continue
        value=job_view(db,job)
        statuses[job.state]+=1
        source.update(task_id=job.id,engine_kind=job.engine_kind,engine_version=job.engine_version,config_version=job.config_version,
                      analyzed_at=job.analyzed_at,status=job.state,classification_status=value['classification_status'])
        sources.append(source)
        if job.state!='succeeded':
            continue
        if value['classification_status']!='classified':
            statuses['unable_to_determine']+=1
            continue
        label=value['emotion_label']
        counts[label]+=1
        nature_counts['test' if is_test else 'non_test'][label]+=1
        key=(job.engine_kind,job.engine_version,job.config_version,is_test)
        emotion[key].append(dict(record_id=row.id,recording_session_id=row.recording_session_id,
            occurred_at=row.occurred_at,input_revision=job.input_revision,emotion_label=label,is_test=is_test))
    emotion_groups=[dict(engine_kind=key[0],engine_version=key[1],config_version=key[2],source_kind='saved_user_text',
        is_test=key[3],points=points,status='available' if len(points)>=2 else 'insufficient_records',
        reason_code=None if len(points)>=2 else 'at_least_two_distinct_records_required') for key,points in emotion.items()]
    scale_result=assessments(db,uid) if include_assessments else {'items':[],'status':'unassociated','reason_code':'session_assessment_link_missing'}
    values=scale_result['items']
    if time_from or time_to:
        values=[item for item in values if item['completed_at'] and (not time_from or item['completed_at']>=time_from) and (not time_to or item['completed_at']<time_to)]
    scale=defaultdict(dict)
    for item in values:
        if valid_assessment(item):
            key=(item['source_kind'],item['scale_name'],item['scale_version'],item['scoring_version'],item['interpretation_version'],bool(item['is_test']))
            scale[key][item['source_record_id']]=dict(source_record_id=item['source_record_id'],completed_at=item['completed_at'],
                total_score=item['total_score'],score_min=item['score_min'],score_max=item['score_max'],is_test=bool(item['is_test']))
    assessment_groups=[]
    for key,mapped in scale.items():
        points=sorted(mapped.values(),key=lambda p:(p['completed_at'],p['source_record_id']))
        assessment_groups.append(dict(source_kind=key[0],scale_name=key[1],scale_version=key[2],scoring_version=key[3],
            interpretation_version=key[4],is_test=key[5],points=points,status='available' if len(points)>=2 else 'insufficient_records',
            reason_code=None if len(points)>=2 else 'at_least_two_distinct_records_required',
            numeric_change=points[-1]['total_score']-points[0]['total_score'] if len(points)>=2 else None))
    return dict(emotion_groups=emotion_groups,assessment_groups=assessment_groups,emotion_counts=counts,
                emotion_counts_by_nature=nature_counts,analysis_counts=statuses,**source_nature(record_flags.values(),values),
                assessments=values,assessment_status=scale_result['status'],assessment_reason_code=scale_result['reason_code'],
                source_references=sources,data_as_of=now(),records=records)

def report(db,uid,scope):
    selected=scope.session_ids
    if selected is not None:
        sessions=[owned(db,sid,uid) for sid in selected]
    else:
        sessions=db.query(RecordSession).join(RecordMessage,RecordMessage.recording_session_id==RecordSession.id).filter(
            RecordSession.user_id==uid,RecordSession.state!='deleted',RecordMessage.occurred_at>=scope.time_from,
            RecordMessage.occurred_at<scope.time_to).distinct().order_by(RecordSession.id).all()
    result=trends_data(db,uid,selected=selected,time_from=scope.time_from,time_to=scope.time_to,include_assessments=selected is None)
    rows=result.pop('records')
    # Evaluate the current effective user text independently of job/model state.
    # A negative emotion or an assessment score never triggers this warning.
    from .safety_notice import dialogue_danger_notice
    danger_notice=dialogue_danger_notice(db,rows)
    session_values=[session_status(db,row) for row in sessions]
    warnings=[]
    if selected is not None:
        warnings.append('未关联量表，未纳入本报告。')
    if not rows:
        warnings.append('所选范围没有对话记录。')
    if any(not s['is_complete'] for s in session_values):
        warnings.append('包含未结束或关闭但未收齐的会话，统计仅限已收到记录。')
    if result['assessment_status'] in ('disabled','no_records','query_failed'):
        warnings.append('量表数据未启用、无记录或查询失败；未补造分数。')
    if any(not valid_assessment(item) for item in result['assessments']):
        warnings.append('未完成、无效或未确认量表不进入有效统计。')
    if any(result['analysis_counts'][key] for key in ('pending','running','retry_wait','failed','unable_to_determine')):
        warnings.append('包含待分析、失败或无法判断的文本，未将其补作中性。')
    if result['data_nature']=='mixed':
        warnings.append('测试与非测试标志来源混合，类别计数和趋势按来源性质分流；不能把测试结果作为非测试历史。')
    source_flags={source['record_id']:source['is_test'] for source in result['source_references']}
    suggestions=['可按自己的节奏记录感受，也可以选择与信任的人交流；本摘要不作医疗判断。']
    if result['emotion_counts']['negative']:
        suggestions.append('如果愿意，可以先谈一件最想被理解的事，或尝试舒适、自然的短暂放松。')
    dto=dict(schema_version='1.1',**profile(db,uid),generated_at=now(),scope=scope.model_dump(exclude_none=True),
        **result,sessions=session_values,simulation_notice='模拟数据演示' if result['is_test'] else None,
        nature_notice=NATURE,warnings=warnings,suggestions=suggestions,danger_notice=danger_notice,
        assessment_time_source='confirmed_completed_at',dialogue_time_source='source_occurred_at',
        messages=[dict(record_id=row.id,recording_session_id=row.recording_session_id,sequence_no=row.sequence_no,role=row.role,
            text_status=row.text_status,playback_status=row.playback_status,occurred_at=row.occurred_at,received_at=row.received_at,is_test=source_flags[row.id],
            **{k:v for k,v in effective(db,row).items() if k not in ('record_id','recording_session_id')}) for row in rows])
    from .collection_history import collection_history
    from .scale_catalog import summarize
    selected_ids=scope.session_ids or [s.id for s in sessions]
    dto['conversation_assessments']=[item for item in collection_history(db,uid,session_ids=selected_ids,
        allowed_record_ids={m['record_id'] for m in dto['messages']},limit=None) if item['scales']]
    dto['scale_summaries']=summarize(dto['conversation_assessments'])
    # Legacy external assessments are separate from conversation-assisted scales.
    if any(s['score'] is not None for s in dto['scale_summaries']):
        dto['warnings']=[w for w in dto['warnings'] if w not in ('未关联量表，未纳入本报告。','量表数据未启用、无记录或查询失败；未补造分数。')]
    from .report_facts import build_facts,rules_narrative
    dto['report_facts']=build_facts(db,uid,scope,dto)
    dto['source_snapshot_hash']=dto['report_facts']['source_snapshot_hash']
    dto['narrative']=rules_narrative(dto['report_facts'],'not_requested')
    return dto
