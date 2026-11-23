"""Read-only, source-bound data for the nine-part user PDF report."""
from datetime import timedelta,timezone
from hashlib import sha256
import json,re
from ..models import User
from ..robot_records import RecordMessage,RecordSession,owned,summary,now
from ..voice.screening import OPTIONS
from .service import CareError,effective,exclusion
from .reports import trends_data
from .report_facts import dt,stamp
from .composite_score import for_sessions
from .safety_notice import dialogue_danger_notice

VERSION='user-report-template-20261123-v2'
BJ=timezone(timedelta(hours=8))
PERIODS={'session':'本次对话','three_days':'近72小时','week':'近168小时'}
VALUES={'negative':0,'neutral':50,'positive':100}
THIRD=re.compile(r'^(?:我(?:的)?(?:妈妈|爸爸|母亲|父亲|朋友|同事|孩子|儿子|女儿|家人)|他|她|朋友|同事|家人)')
HYPOTHETICAL=re.compile(r'如果|假如|假设|举个例子|你觉得|你会|是什么意思|你能')
DOMAINS={
    'emotion_life':('情绪与生活状态',r'心情|情绪|压力|烦|难过|开心|高兴|低落|生活|孤独|盼头|家人|朋友|散步'),
    'sleep_interest':('睡眠／兴趣变化',r'睡|失眠|早醒|兴趣|乐趣|喜欢|爱好|提不起'),
    'daily_function':('日常功能影响',r'工作|学习|上课|作业|上班|请假|迟到|照顾|自理|做饭|洗漱|家务|无法出门|不能出门'),
}
SIGNALS=[('sleep','睡眠困扰',3,r'睡不着|失眠|总是早醒'),
    ('interest','兴趣下降',1,r'提不起兴趣|没有兴趣|什么都不想做'),
    ('fatigue','疲倦无力',4,r'总是很累|浑身没劲|一点力气也没有'),
    ('fluctuation','情绪波动',None,r'情绪起伏很大|情绪反复波动|情绪忽好忽坏'),
    ('self_criticism','自我否定',6,r'觉得自己没用|觉得自己一无是处'),
    ('withdrawal','社交退缩',None,r'不想和人来往|不愿和人交流|刻意回避社交')]


def self_sentences(messages,danger_ids):
    from .report_context import own_clauses
    yield from own_clauses(messages,danger_ids)


def dialogue_sections(messages,confirmed,danger_ids):
    sentences=list(self_sentences(messages,danger_ids))
    sections={}
    for key,(title,pattern) in DOMAINS.items():
        candidates=[(m,t) for m,t in sentences if re.search(pattern,t)]
        # Latest relevant originals, never a generated claim of worsening/improvement.
        selected=candidates[-2:]
        sections[key]=dict(title=title,status='recorded' if selected else 'not_mentioned',
            text='；'.join('用户自述：“'+t[:110]+('…' if len(t)>110 else '')+'”' for _,t in selected)
                if selected else '本报告范围内未提供足够相关信息。',
            source_record_ids=list(dict.fromkeys(m['record_id'] for m,_ in selected)))
    by_item={x['item']:x['value'] for x in confirmed if x['scale_id']=='PHQ-9'}
    for key,items in [('emotion_life',[(2,'低落或缺少盼头'),(1,'兴趣或乐趣降低')]),
                      ('sleep_interest',[(3,'睡眠相关困扰'),(1,'兴趣或乐趣降低')])]:
        if sections[key]['status']=='not_mentioned':
            readings=[f'{label}：近两周自述“{OPTIONS[by_item[i]]}”' for i,label in items if i in by_item]
            if readings:sections[key].update(status='confirmed_answers',text='；'.join(readings)+'。依据为本范围内已确认问答。')
    return sections,sentences


def risk_signals(confirmed,sentences,danger):
    phq={a['item']:a['value'] for a in confirmed if a['scale_id']=='PHQ-9'}
    result=[]
    for key,label,item,pattern in SIGNALS:
        refs=[]
        for m,text in sentences:
            if re.search(r'以前|曾经|去年|之前',text) and not re.search(r'现在仍|最近仍|现在还',text):
                continue
            for match in re.finditer(pattern,text):
                if not re.search(r'没有|并不|并非|从未|不再|不是|否认|(?:不|没|无)\s*$',text[max(0,match.start()-8):match.start()]):
                    refs.append(m['record_id'])
        result.append(dict(key=key,label=label,confirmed=bool(refs) or bool(item and phq.get(item,0)>0),source_record_ids=sorted(set(refs))))
    result.append(dict(key='safety',label='自伤相关表达（需单独核实）',
        confirmed=bool(danger['count']) or phq.get(9,0)>0,source_record_ids=[s['record_id'] for s in danger['sources']]))
    return result


def emotion_chart(data,messages,period,start,end,sessions=None):
    groups=[g for g in data['emotion_groups'] if g['points']]
    latest=max(groups,key=lambda g:max(p['occurred_at'] for p in g['points']),default=None)
    valid={p['record_id']:p for p in latest['points']} if latest else {}
    if period=='session':
        points=[dict(key=str(i),label=str(i),occurred_at=m['occurred_at'],
            score=VALUES[valid[m['record_id']]['emotion_label']] if m['record_id'] in valid else None,
            count=int(m['record_id'] in valid)) for i,m in enumerate(messages,1)]
        axis='用户发言顺序'
    else:
        points=[]
        ordered=sorted(sessions or [],key=lambda s:(s.started_at,s.id))
        record_sessions={m['record_id']:m['recording_session_id'] for m in messages}
        for i,session in enumerate(ordered,1):
            values=[VALUES[p['emotion_label']] for rid,p in valid.items() if record_sessions.get(rid)==session.id]
            points.append(dict(key=str(session.id),label=str(i),session_id=session.id,occurred_at=session.started_at,
                ended_at=session.ended_at,score=round(sum(values)/len(values),1) if values else None,count=len(values)))
        axis='会话段（按开始时间排列）'
    return dict(mode='conversation' if period=='session' else 'sessions',x_label=axis,points=points,
        valid_count=sum(p['count'] for p in points),excluded_engine_groups=max(0,len(groups)-1),
        engine_kind=latest['engine_kind'] if latest else None,engine_version=latest['engine_version'] if latest else None,
        status='available' if any(p['score'] is not None for p in points) else 'no_valid_classification')


def read_template_report(db,uid,sid,period='session',*,as_of=None):
    if period not in PERIODS:raise CareError(422,'validation_error')
    anchor=owned(db,sid,uid)
    if not summary(db,anchor)['is_complete']:raise CareError(409,'report_session_incomplete')
    generated=as_of or now()
    if period=='session':
        sessions=[anchor];start,end=anchor.started_at,anchor.ended_at
        data=trends_data(db,uid,selected=[sid],include_assessments=False)
    else:
        start=stamp(dt(generated)-timedelta(hours=72 if period=='three_days' else 168));end=generated
        candidates=db.query(RecordSession).filter(
            RecordSession.user_id==uid,RecordSession.is_test==anchor.is_test,RecordSession.state=='closed',
            RecordSession.started_at>=start,RecordSession.started_at<end,RecordSession.ended_at<=end).order_by(RecordSession.started_at,RecordSession.id).all()
        sessions=[s for s in candidates if summary(db,s)['is_complete']]
        data=trends_data(db,uid,selected=[s.id for s in sessions],time_from=start,time_to=end,include_assessments=False)
    rows=data.pop('records')
    messages=[dict(role=r.role,text_status=r.text_status,occurred_at=r.occurred_at,**effective(db,r)) for r in rows if not exclusion(r)]
    combined=for_sessions(db,uid,[s.id for s in sessions],allowed_record_ids={r.id for r in rows})
    confirmed=combined.pop('confirmed_items',[]);instruments=combined.pop('instruments',[])
    danger=dialogue_danger_notice(db,rows)
    sections,sentences=dialogue_sections(messages,confirmed,{s['record_id'] for s in danger['sources']})
    signals=risk_signals(confirmed,sentences,danger)
    support=any(s['key']=='safety' and s['confirmed'] for s in signals)
    transcript_rows=[r for r in rows if r.role=='user']
    transcription=('completed' if transcript_rows and all(r.text_status=='completed' and r.content.strip() for r in transcript_rows)
        else 'failed' if transcript_rows and all(r.text_status=='failed' for r in transcript_rows) else 'needs_review')
    elapsed=0
    for s in sessions:
        a,b=dt(s.started_at),dt(s.ended_at)
        if period!='session':a=max(a,dt(start));b=min(b,dt(end))
        elapsed+=max(0,(b-a).total_seconds())
    overview=(f'本报告纳入 {len(sessions)} 段已结束的完整对话、{len(messages)} 条有效用户发言。' if sessions
        else '本报告范围暂无符合条件的已结束完整对话。')
    from ..user_profiles import report_profile
    chart=emotion_chart(data,messages,period,start,end,sessions)
    from .report_advice import advice
    suggestions=advice(combined,signals,chart,sections,support)
    personal=report_profile(db,uid)
    from .safety_alerts import contact_alert
    contact=contact_alert(db,uid,[s.id for s in sessions],danger= danger,combined=combined,personal=personal)
    dto=dict(template_version=VERSION,username=db.get(User,uid).username,generated_at=generated,
        user_id=uid,personal_profile=personal,
        report_range=period,range_label=PERIODS[period],time_from=start,time_to=end,is_test=bool(anchor.is_test),
        conversation_count=len(sessions),user_turns=len(messages),elapsed_seconds=round(elapsed),
        transcription_status=transcription,combined_score=combined,instruments=instruments,
        emotion_trend=chart,signals=signals,summary_sections=sections,
        summary=overview,suggestions=suggestions[:3],support_notice=support,emergency_contact_action=contact,qr_status='not_configured')
    material=dict(dto,generated_at=None,messages=messages,source_references=data['source_references'],confirmed_items=confirmed,
        selected_sessions=[dict(id=s.id,started_at=s.started_at,ended_at=s.ended_at,last_sequence_no=s.last_sequence_no) for s in sessions])
    digest=sha256(json.dumps(material,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    dto.update(source_snapshot_hash=digest,report_id='R-'+digest[:16].upper())
    return dto
