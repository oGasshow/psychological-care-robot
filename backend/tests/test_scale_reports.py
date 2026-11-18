"""Standard scoring, source-scoped reports and normal-mode collection migration."""
import json,uuid
import pytest
from app.robot_records import now
from app.voice.screening import Screening,ITEMS,OPTIONS_BY_SCALE,save_result
from app.voice.transcripts import Utterance
from app.voice.collection_sources import attach_sources
from app.voice.collection_plan import store_plan,read_plan
from app.care import report_narrative

@pytest.fixture(autouse=True)
def normal(monkeypatch):
    for k,v in dict(APP_ENV='test',ROBOT_CARE_COLLECTION_DEMO='false',ROBOT_CARE_GUIDED_SCREENING_ENABLED='true',ROBOT_CARE_PURCHASE_NOTICE_VERSION='fictional-normal-v1',ROBOT_CARE_REPORT_PROVIDER='disabled').items():monkeypatch.setenv(k,v)

def entry(text,role):return Utterance(uuid.uuid4().hex,role,'fictional',text=text,final=True,occurred_at=now())

def setup_controller():
    s=Screening(True,'fictional-normal-v1');s.direct_collection=True;s.concern(['fictional-signal'],'fictional',['PHQ-9','GAD-7']);s.stage='collecting';return s

def save(a,s,scale,values):
    sid=a.create('voice_scales_'+uuid.uuid4().hex[:8],started_at=now()).json()['recording_session_id'];entries=[]
    for i,value in enumerate(values,1):
        for text,role in [(f'最近两周，{ITEMS[scale][i-1]}的情况怎么样？','assistant'),(OPTIONS_BY_SCALE[scale][value],'user')]:
            e=entry(text,role);s.observe(e);entries.append(e)
    for i,e in enumerate(entries,1):assert a.send(sid,i,**e.wire()).status_code==201
    assert a.request('POST',f'/api/robot-records/sessions/{sid}/close',json=dict(ended_at=now(),last_sequence_no=len(entries))).status_code==200
    attach_sources(a.uid,sid,s,{});store_plan(a.uid,True,s);save_result(a.uid,sid,s)
    return sid

def seed(a):
    s=setup_controller();first=save(a,s,'PHQ-9',[2,1,2,1,1,2,1,2,0]);second=save(a,s,'GAD-7',[1,2,1,1,1,2,1]);return first,second,s


def test_public_report_uses_only_selected_session_even_with_inherited_items(actors,monkeypatch):
    a,b=actors
    s=setup_controller()
    first=save(a,s,'PHQ-9',[2,1,2,1,1,2,1,2,0])
    second=save(a,s,'GAD-7',[1,2,1,1,1])
    path=f'/api/robot-insights/reports/session/{second}'
    response=a.request('GET',path)
    assert response.status_code==200
    report=response.json()
    assert report['username']=='virtual_a' and report['user_turns']==5
    assert [(v['scale_id'],v['answered'],v['required'],v['score'],v['answered_max'])
            for v in report['scores']]==[('GAD-7',5,7,6,15)]
    assert not {'session_id','messages','source_references','report_facts','anonymous_id'} & report.keys()
    assert b.request('GET',path).status_code==404
    waiting=a.create('still_open').json()['recording_session_id']
    assert a.request('GET',f'/api/robot-insights/reports/session/{waiting}').status_code==409

    def generate(facts):
        assert facts['scope']=={'session_ids':[second]}
        assert all(row['recording_session_id']==second for row in facts['evidence'])
        assert first!=second and not facts['comparison_scope']
        return {'mode':'model','content':{'overview':{'text':'本轮虚构总结'},'conversation_suggestions':[]}}

    monkeypatch.setattr(report_narrative,'generate',generate)
    narrative=a.request('POST',path+'/narrative',json={'source_snapshot_hash':report['source_snapshot_hash']})
    assert narrative.status_code==200 and narrative.json()['summary']=='本轮虚构总结'

    def numbered_summary(_):
        return {'mode':'model','content':{'overview':{'text':'会话 #123 的记录'},
            'conversation_suggestions':[{'text':'查看会话编号 567'}]}}

    monkeypatch.setattr(report_narrative,'generate',numbered_summary)
    narrative=a.request('POST',path+'/narrative',json={'source_snapshot_hash':report['source_snapshot_hash']})
    assert narrative.status_code==200 and '123' not in narrative.text and '567' not in narrative.text

    def overlapping_summary(_):
        return {'mode':'model','content':{'overview':{'text':'你提到课业让你紧绷。把待办写在纸上。'},
            'conversation_suggestions':[{'text':'这几天作业集中堆在一起，你感到有些紧张。可以先在作业间隙联系一位朋友。'},
                                        {'text':'把待办写在纸上。'}]}}

    monkeypatch.setattr(report_narrative,'generate',overlapping_summary)
    narrative=a.request('POST',path+'/narrative',json={'source_snapshot_hash':report['source_snapshot_hash']}).json()
    assert narrative=={'summary':'你提到课业让你紧绷。','suggestions':['可以先在作业间隙联系一位朋友。','把待办写在纸上。']}


def legacy_call(actor,controller,lines,*,old=False):
    from app.robot_records import transaction
    from app.voice.screening import CollectionTrace
    sid=actor.create('voice_legacy_'+uuid.uuid4().hex[:8],started_at=now()).json()['recording_session_id']
    for index,(role,text) in enumerate(lines,1):
        assert actor.send(sid,index,**entry(text,role).wire()).status_code==201
    assert actor.request('POST',f'/api/robot-records/sessions/{sid}/close',
        json=dict(ended_at=now(),last_sequence_no=len(lines))).status_code==200
    save_result(actor.uid,sid,controller)
    if old:
        with transaction(True) as db:
            trace=db.get(CollectionTrace,sid)
            trace.payload={key:value for key,value in trace.payload.items() if key!='review_mode'}
    return sid


@pytest.mark.parametrize('refused',[False,True])
def test_legacy_goodbye_repair_recovers_only_grounded_spoken_answers(actors,refused):
    from app.voice.demo_reconciliation import scan
    a,_=actors
    s=setup_controller()
    s.stage='declined';s.history_danger_unresolved=True
    store_plan(a.uid,True,s)
    old=[('user','我不想做量表了。')] if refused else []
    legacy_call(a,s,[*old,('user','可以的，我现在有点不想聊天了，我们下次再聊吧。')],old=True)
    current=legacy_call(a,s,[
        ('assistant','这两周里，心情低落有几天？'),
        ('user','大概五天。'),
        ('assistant','这两周里，你会不会容易觉得累，没力气？'),
        ('user','有时会有这种感觉。'),
        ('assistant','这两周有没有反复想到死亡或者伤害自己的想法？'),
        ('user','这倒没有。'),
    ])
    plan=read_plan(a.uid,True)
    assert plan['status']==('declined' if refused else 'checking_in')
    assert plan['history_danger_unresolved'] and not plan['answers']
    scan()
    route=f'/api/robot-insights/reports/session/{current}'
    scores=a.request('GET',route).json()['scores']
    assert [(r['scale_id'],r['answered'],r['score']) for r in scores]==([] if refused else [('PHQ-9',2,1)])
    assert a.request('PUT',route+'/check-in',json={'phq_mood':2}).status_code==404
    assert scan()==0
    assert a.request('GET',route).json()['scores']==scores


def test_core_short_conversation_persists_early_items_in_selected_report(actors):
    a,_=actors
    s=Screening(True,'fictional-normal-v1')
    s.core_only=s.direct_collection=True
    s.review_mode='post_session'
    lines=[
        ('user','你好，我想和你聊近况。'),
        ('assistant','好啊，有什么想说的吗？'),
        ('user','我最近觉得心情很低落。'),
        ('assistant','听起来这段时间不容易。最近两周，大概有几天觉得心情低落？'),
        ('user','有时候会低落。'),
        ('assistant','我明白。那大概有几天呢？'),
        ('user','有五天左右。'),
        ('assistant','最近两周，大概有几天对平常喜欢的事提不起兴趣？'),
        ('user','大概八九天。'),
        ('assistant','最近两周有没有睡不好，比如半夜醒，或者睡很久还是觉得累？'),
        ('user','差不多，天天。'),
        ('assistant','谢谢你慢慢说。'),
    ]
    sid=a.create('voice_core_short_'+uuid.uuid4().hex[:8],started_at=now()).json()['recording_session_id']
    for i,(role,text) in enumerate(lines,1):
        row=entry(text,role);s.observe(row)
        assert a.send(sid,i,**row.wire()).status_code==201
    assert a.request('POST',f'/api/robot-records/sessions/{sid}/close',json=dict(ended_at=now(),last_sequence_no=len(lines))).status_code==200
    attach_sources(a.uid,sid,s,{})
    store_plan(a.uid,True,s);assert save_result(a.uid,sid,s)
    report=a.request('GET',f'/api/robot-insights/reports/session/{sid}').json()
    assert [(r['scale_id'],r['answered'],r['score']) for r in report['scores']]==[('PHQ-9',3,6)]
    rows=a.request('GET','/api/robot-insights/assessments').json()['conversation_collections']
    assert rows[0]['current_session_scores']==report['scores']


def test_standalone_frequency_appears_in_session_report(actors):
    a,_=actors
    s=Screening(True,'fictional-normal-v1')
    s.core_only=s.direct_collection=True
    s.review_mode='post_session'
    utterance=entry('过去两周，大概有五天我觉得心情低落。','user')
    s.observe(utterance)
    sid=a.create('voice_core_self_report_'+uuid.uuid4().hex[:8],started_at=now()).json()['recording_session_id']
    assert a.send(sid,1,**utterance.wire()).status_code==201
    assert a.request('POST',f'/api/robot-records/sessions/{sid}/close',json=dict(ended_at=now(),last_sequence_no=1)).status_code==200
    attach_sources(a.uid,sid,s,{})
    store_plan(a.uid,True,s);assert save_result(a.uid,sid,s)
    report=a.request('GET',f'/api/robot-insights/reports/session/{sid}').json()
    assert [(r['scale_id'],r['answered'],r['score']) for r in report['scores']]==[('PHQ-9',1,1)]


@pytest.mark.parametrize('line,expected',[
    ('如果我最近觉得心情很低落，你会怎么问？','companionship'),
    ('今天考试，我有点紧张。','companionship'),
    ('我最近心情很低落，但我不想回答量表问题。','declined'),
    ('我最近心情很低落，我有点不想活了。','urgent'),
])
def test_early_collection_does_not_override_context_and_safety(line,expected):
    s=Screening(True,'fictional-normal-v1')
    s.core_only=True
    s.observe(entry(line,'user'))
    assert s.stage==expected and not s.answers


@pytest.mark.parametrize('line', ['有十五天', '有15天', '有25天', '大概七八天'])
def test_core_frequency_rejects_out_of_range_or_ambiguous_days(line):
    from app.voice.screening import OPTIONS,frequency_answer
    assert frequency_answer(line,OPTIONS,'最近两周，大概有几天觉得心情低落？') is None


def test_window_report_returns_only_aggregate_data(actors):
    a,b=actors
    seed(a)
    seed(b)
    a.create('not_finished',started_at=now())
    path='/api/robot-insights/reports/window?time_from=2020-01-01T00:00:00Z&time_to=2099-01-01T00:00:00Z'
    response=a.request('GET',path)
    assert response.status_code==200
    value=response.json()
    assert set(value)=={'username','time_from','time_to','generated_at','groups'}
    assert value['username']=='virtual_a'
    assert value['groups']==[dict(is_test=True,conversation_count=2,user_turns=16,
                                 emotion_counts=dict(positive=0,neutral=0,negative=0))]


def test_public_report_has_soft_support_flag_without_exporting_raw_expression(actors):
    a,_=actors
    sid=a.create('session_support').json()['recording_session_id']
    assert a.send(sid,1,content='我有点不想活了都。').status_code==201
    assert a.request('POST',f'/api/robot-records/sessions/{sid}/close',
        json={'ended_at':now(),'last_sequence_no':1}).status_code==200
    response=a.request('GET',f'/api/robot-insights/reports/session/{sid}')
    assert response.status_code==200 and response.json()['support_notice']
    assert response.json()['scores']==[] and '不想活' not in response.text

def test_normal_standard_results_are_complete_and_explained(actors):
    a,_=actors;first,second,s=seed(a)
    assert s.stage=='complete' and len(s.answers)==16
    data=a.request('GET','/api/robot-insights/assessments').json()
    rows={r['scale_id']:r for r in data['scale_summaries']}
    assert rows['PHQ-9']['score']==12 and rows['PHQ-9']['max_score']==27
    assert rows['PHQ-9']['reference_band']=='中度症状参考段' and rows['PHQ-9']['reference']['doi']
    assert rows['GAD-7']['score']==9 and rows['GAD-7']['max_score']==21
    assert rows['GAD-7']['reference_band']=='轻度症状参考段'
    assert len(rows['PHQ-9']['items'])==9 and rows['PHQ-9']['recording_session_ids']==[first]

def test_report_passes_verified_scales_to_model_and_hashes_score_changes(actors):
    a,_=actors;first,second,_=seed(a);scope={'session_ids':[first,second]}
    dto=a.request('POST','/api/robot-insights/reports/preview',json={'scope':scope}).json()
    from pathlib import Path
    (Path(__file__).resolve().parents[2]/'runtime/standard-scale-report-fixture.json').write_text(json.dumps(dto,ensure_ascii=False),encoding='utf-8')
    facts=dto['report_facts'];scales=[f for f in facts['facts'] if f['kind']=='scale_result']
    assert {s['scale_id']:s['score'] for s in scales}=={'PHQ-9':12,'GAD-7':9}
    assert all(s['source_record_ids'] for s in scales)
    restricted=a.request('POST','/api/robot-insights/reports/preview',json={'scope':{'session_ids':[second]}}).json()
    assert next(s for s in restricted['scale_summaries'] if s['scale_id']=='PHQ-9')['score'] is None
    with __import__('app.database',fromlist=['SessionLocal']).SessionLocal() as db:
        from app.voice.screening import ScreeningResult
        row=db.get(ScreeningResult,second);v=dict(row.payload);v['stage']='paused';row.payload=v;db.commit()
    fresh=a.request('POST','/api/robot-insights/reports/preview',json={'scope':scope}).json()
    assert fresh['source_snapshot_hash']!=dto['source_snapshot_hash']

def test_custom_indicator_is_not_given_standard_severity():
    from app.care.scale_catalog import definition,summarize
    d=definition('mood_interest');assert d['max_score']==12 and not d['bands'] and d['reference'] is None
    assert all(s['score'] is None for s in summarize([]))

def test_model_cannot_invent_scale_score_or_wrong_reference_band(actors):
    a,_=actors;first,second,_=seed(a)
    facts=a.request('POST','/api/robot-insights/reports/preview',json={'scope':{'session_ids':[first,second]}}).json()['report_facts']
    base=dict(overview=dict(text='本次记录已整理出抑郁和焦虑相关症状的频率。',evidence_ids=['scale:PHQ-9']),changes=[],topics=[],conversation_suggestions=[],limitations=[])
    valid={**base,'scale_readings':[dict(text='PHQ-9辅助合计12分，处于中度症状参考段，仍需结合原话核实。',evidence_ids=['scale:PHQ-9'])]}
    assert report_narrative.validate_content(json.dumps(valid,ensure_ascii=False),facts)['scale_readings']
    for text in ['PHQ-9辅助合计18分。','PHQ-9辅助合计12分，属于重度症状参考段。']:
        bad={**base,'scale_readings':[dict(text=text,evidence_ids=['scale:PHQ-9'])]}
        with pytest.raises(ValueError):report_narrative.validate_content(json.dumps(bad,ensure_ascii=False),facts)

def test_normal_durable_recovery_uses_four_option_standard_scoring(actors):
    from app.voice.demo_reconciliation import register,scan
    from app.database import SessionLocal
    from app.robot_records import RecordSession
    a,_=actors;s=setup_controller();store_plan(a.uid,True,s)
    sid=a.create('voice_normal_durable',started_at=now()).json()['recording_session_id']
    with SessionLocal() as db:external=db.get(RecordSession,sid).external_session_id
    register(a.uid,external,s)
    entries=[entry('最近两周做事缺少兴趣或乐趣的情况怎么样？','assistant'),entry('有几天','user')]
    for i,e in enumerate(entries,1):assert a.send(sid,i,**e.wire()).status_code==201
    assert a.request('POST',f'/api/robot-records/sessions/{sid}/close',json=dict(ended_at=now(),last_sequence_no=2)).status_code==200
    assert scan()==1 and read_plan(a.uid,True)['answers']['PHQ-9:1']['value']==1
    assert 'mood_interest:1' not in read_plan(a.uid,True)['answers']



def test_doubao_composes_small_cited_sections_from_verified_scales(actors,monkeypatch):
    from app.voice import upstream
    a,_=actors;first,second,_=seed(a)
    facts=a.request('POST','/api/robot-insights/reports/preview',json={'scope':{'session_ids':[first,second]}}).json()['report_facts']
    monkeypatch.setenv('ROBOT_CARE_REPORT_PROVIDER','doubao_realtime');monkeypatch.setenv('DOUBAO_VOICE_API_KEY','fictional-key')
    calls=[]
    async def structured(prompt,schema,payload,timeout):
        calls.append(payload)
        if len(payload['facts'])==1:
            f=payload['facts'][0]
            return json.dumps(dict(text=f"{f['name']}辅助合计{f['score']}分，属于{f['reference_band']}，仍需结合原话核实。",evidence_ids=[f['id']]),ensure_ascii=False)
        return json.dumps(dict(text='近期记录整理了低落与担忧相关的表达，可以结合具体生活经历继续了解。',evidence_ids=['scale:PHQ-9']),ensure_ascii=False)
    monkeypatch.setattr(upstream,'structured_report',structured)
    value=report_narrative.generate(facts)
    assert value['mode']=='model' and len(value['content']['scale_readings'])==2 and len(calls)==4
    assert all('items' not in f for call in calls for f in call['facts'] if f['kind']=='scale_result')



def test_normal_direct_item9_positive_remains_safety_task(actors):
    a,_=actors;s=setup_controller();s.target_scales=['PHQ-9']
    save(a,s,'PHQ-9',[0,0,0,0,0,0,0,0,1])
    assert s.stage=='urgent' and read_plan(a.uid,True)['needs_collection']
    dto=a.request('GET','/api/robot-insights/assessments').json()
    phq=next(v for v in dto['scale_summaries'] if v['scale_id']=='PHQ-9')
    assert phq['score']==1 and phq['item9_attention']



def test_standard_frequency_never_uses_custom_five_level_mapping():
    from app.voice.screening import frequency_answer,OPTIONS
    q='最近两周做事缺少兴趣的情况怎么样？'
    assert frequency_answer('从来没有',OPTIONS,q)==0
    assert frequency_answer('经常',OPTIONS,q) is None
    assert frequency_answer('偶尔',OPTIONS,q) is None
