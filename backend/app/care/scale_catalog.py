"""Source-linked instrument definitions and deterministic score explanations."""
from ..voice.screening import ITEMS,OPTIONS_BY_SCALE,SCALE_LABELS,SCALE_DIRECTIONS

VERSION='scale-catalog-v1'
REFERENCES={
 'PHQ-9':dict(title='Kroenke, Spitzer & Williams (2001): The PHQ-9',url='https://pmc.ncbi.nlm.nih.gov/articles/PMC1495268/',doi='10.1046/j.1525-1497.2001.016009606.x'),
 'GAD-7':dict(title='Spitzer et al. (2006): A brief measure for assessing generalized anxiety disorder',url='https://pubmed.ncbi.nlm.nih.gov/16717171/',doi='10.1001/archinte.166.10.1092')}
BANDS={'PHQ-9':[(0,4,'最低分段'),(5,9,'轻度症状参考段'),(10,14,'中度症状参考段'),(15,19,'中重度症状参考段'),(20,27,'重度症状参考段')],
       'GAD-7':[(0,4,'最低分段'),(5,9,'轻度症状参考段'),(10,14,'中度症状参考段'),(15,21,'重度症状参考段')]}


def definition(scale):
    standard=scale in REFERENCES
    purposes={'PHQ-9':'了解近两周抑郁相关症状的出现频率，包括兴趣、心情、睡眠、精力等九个方向。',
        'GAD-7':'了解近两周焦虑相关症状的出现频率，包括紧张、担忧、放松困难等七个方向。'}
    return dict(scale_id=scale,name={'PHQ-9':'患者健康问卷 PHQ-9','GAD-7':'广泛性焦虑量表 GAD-7'}.get(scale,SCALE_LABELS[scale]),
        kind='standard_reference' if standard else 'project_indicator',version=VERSION,item_count=len(ITEMS[scale]),
        max_score=len(ITEMS[scale])*(len(OPTIONS_BY_SCALE[scale])-1),recall_window='近两周',
        purpose=purposes.get(scale,'通过自然对话整理'+SCALE_LABELS[scale].replace('对话指标','')+'的相关频率。'),
        direction=SCALE_DIRECTIONS.get(scale,'分数较高表示对应症状自述的频率较高'),
        reference=REFERENCES.get(scale),bands=[dict(min=a,max=b,label=c) for a,b,c in BANDS.get(scale,[])],
        limitation=('本系统为对话辅助采集；原量表在标准施测条件下的验证结果不等于聊天采集已获同等验证，分段仅作待核实参考。'
            if standard else '项目自定义频率指标，没有经验证的临床分界，不能换算为 PHQ-9、GAD-7 或作出诊断。'))


def summarize(collections,expected=None):
    actual={s['scale'] for row in collections for s in row.get('scales',[]) if s['scale'] in ITEMS}
    scales=list(dict.fromkeys(['PHQ-9','GAD-7',*(expected or []),*sorted(actual)]))
    readings=[]
    for scale in scales:
        if scale not in ITEMS:continue
        d=definition(scale)
        candidates=[(row,s) for row in collections for s in row.get('scales',[]) if s['scale']==scale]
        if candidates:
            latest=max(candidates,key=lambda pair:(pair[0]['started_at'],pair[0]['recording_session_id']))[0]
            episode=latest.get('episode_id')
            if episode:candidates=[p for p in candidates if p[0].get('episode_id')==episode]
            row,s=max(candidates,key=lambda pair:(pair[1]['answered'],pair[0]['source_status']=='current_original_text',pair[0]['recording_session_id']))
            valid=row['source_status']=='current_original_text'
            answers=s.get('items',[])
            points=[a.get('value') for a in answers if a]
            answered=len(points)
            complete=bool(valid and len(answers)==d['item_count'] and answered==d['item_count']
                and all(type(v) is int and 0<=v<len(OPTIONS_BY_SCALE[scale]) for v in points))
            total=sum(points) if complete else None
            status='complete' if complete else 'collecting' if valid else 'needs_revalidation'
            items=[]
            for i,a in enumerate(s.get('items',[]),1):
                value=a.get('value') if a else None
                items.append(dict(item=i,topic=ITEMS[scale][i-1],points=value if valid else None,
                    answer=OPTIONS_BY_SCALE[scale][value] if valid and isinstance(value,int) and 0<=value<len(OPTIONS_BY_SCALE[scale]) else None,
                    record_ids=[r['record_id'] for r in (a or {}).get('source_refs',[])]))
            source_ids=row.get('source_record_ids',[])
            result=dict(answered=answered,score=total,status=status,episode_id=episode,
                source_status=row['source_status'],source_record_ids=source_ids,recording_session_ids=sorted(set(
                    ref['recording_session_id'] for a in s.get('items',[]) if a for ref in a.get('source_refs',[]))),items=items,is_test=row['is_test'])
        else:
            result=dict(answered=0,score=None,status='not_collected',episode_id=None,source_status='no_saved_collection',source_record_ids=[],recording_session_ids=[],items=[],is_test=None)
        result.update(d);result['id']='scale:'+scale
        score=result['score']
        result['reference_band']=next((b['label'] for b in d['bands'] if score is not None and b['min']<=score<=b['max']),None)
        result['meaning']=('尚未采集，不能判断该量表分数或症状程度。' if result['status']=='not_collected' else
            '信息未齐或原话待核实，当前不计算完整总分，也不套用分段。' if score is None else
            '完整条目已采齐。按原量表分段可作症状频率参考，仍需结合原话与专业核实；分数不代表诊断。' if scale in REFERENCES else
            d['direction']+'；这里只表示项目指标的频率合计，不划分临床程度。')
        result['item9_attention']=bool(scale=='PHQ-9' and len(result['items'])>=9 and result['items'][8]['points'] is not None and result['items'][8]['points']>0)
        readings.append(result)
    return readings
