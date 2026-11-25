'use client';
import {date} from '@/lib/care-api';
export type ReportPeriod='session'|'three_days'|'week';
interface ChartPoint {key:string;label:string;score:number|null;count:number;occurred_at?:string}
interface SummaryField {title:string;text:string;status:string;source_record_ids:number[]}
export interface TemplateReport {
  template_version:string;username:string;generated_at:string;report_range:ReportPeriod;range_label:string;
  time_from:string;time_to:string;is_test:boolean;conversation_count:number;user_turns:number;elapsed_seconds:number;
  user_id?:number;personal_profile?:{full_name:string|null;gender_label:string|null;age:number|null;emergency_contact_name:string|null;emergency_contact_phone:string|null};
  transcription_status:'completed'|'failed'|'needs_review';
  combined_score:{score:number|null;confidence:number;full_max:number;score_kind:string;answered:number;required:number;observed_score:number};
  instruments:{scale_id:string;name:string;kind:string;answered:number;required:number;coverage:number;observed_score:number;answered_max:number;status:string}[];
  emotion_trend:{mode:string;x_label:string;points:ChartPoint[];valid_count:number;excluded_engine_groups:number;status:string};
  signals:{key:string;label:string;confirmed:boolean}[];
  summary_sections:Record<'emotion_life'|'sleep_interest'|'daily_function',SummaryField>;
  summary:string;suggestions:string[];support_notice:boolean;qr_status:string;source_snapshot_hash:string;report_id:string;
  emergency_contact_action?:{status:string;contact_name?:string|null;contact_phone?:string|null;notification_sent:boolean};
}
function EmotionChart({value}:{value:TemplateReport['emotion_trend']}){
  const points=value.points,x=(i:number)=>points.length>1?48+i*812/(points.length-1):454,y=(v:number)=>14+(100-v)*.64;
  const valid=(v:number|null):v is number=>v!==null&&Number.isFinite(v)&&v>=0&&v<=100;
  const segments:number[][]=[];let current:number[]=[];
  points.forEach((p,i)=>{if(valid(p.score))current.push(i);else if(current.length){segments.push(current);current=[];}});
  if(current.length)segments.push(current);
  const ticks=points.length<=7?points.map((_,i)=>i):[0,Math.round((points.length-1)/3),Math.round(2*(points.length-1)/3),points.length-1];
  return <svg className="pdf-emotion-chart" viewBox="0 0 900 112" role="img" aria-label="情绪变化趋势折线图" data-testid="report-emotion-chart">
    <title>情绪参考分，越高表示表达更积极；缺失记录不连线</title>
    {[0,50,100].map(v=><g key={v}><line x1="48" x2="860" y1={y(v)} y2={y(v)} stroke="#d6e5ef"/><text x="38" y={y(v)+3} textAnchor="end">{v}</text></g>)}
    <path d="M48 14V78H860" fill="none" stroke="#7498b3"/>
    {segments.filter(s=>s.length>1).map((s,i)=><polyline key={i} data-testid="emotion-line-segment" fill="none" stroke="#0874bc" strokeWidth="2" points={s.map(j=>`${x(j)},${y(points[j].score!)}`).join(' ')}/>)}
    {points.map((p,i)=>valid(p.score)?<circle data-testid="emotion-point" key={p.key} cx={x(i)} cy={y(p.score)} r="3" fill="#0874bc"><title>{p.label}：{p.score} 分，{p.count} 条有效表达{p.occurred_at?' · '+date(p.occurred_at):''}</title></circle>:null)}
    {ticks.map(i=><text key={points[i].key} x={x(i)} y="93" textAnchor="middle">{points[i].label}</text>)}
    {!points.some(p=>valid(p.score))&&<text x="454" y="49" textAnchor="middle" fill="#74899c">暂无有效情绪分类记录</text>}
    <text x="454" y="108" textAnchor="middle">{value.x_label}</text>
  </svg>;
}
export function Report({value,audience='self'}:{value:TemplateReport;audience?:'self'|'care_team'}){
  const score=value.combined_score,elapsed=value.elapsed_seconds<60?`${value.elapsed_seconds} 秒`:`${Math.round(value.elapsed_seconds/60)} 分钟`;
  const trans=[['completed','转写完成'],['failed','失败'],['needs_review','待核对']] as const;
  const profile=value.personal_profile;
  return <article className="care-report template-report" data-testid="report-dto" data-data-nature={value.is_test?'test_only':'non_test_only'}>
    <header className="pdf-report-heading"><h1>心理疏导机器人评估报告</h1><p>基于语音对话与辅助筛查的回顾结果 · {value.range_label}{value.is_test?' · 演示记录':''}</p></header>
    <section className="pdf-panel"><h2>01 评估流程概览</h2><div className="pdf-flow">语音对话采集 → 模型辅助初筛 → 按需引导问答 → 整理评分与情绪趋势 → 回顾与关怀</div></section>
    <div className="pdf-pair"><section className="pdf-panel"><h2>02 基础信息</h2><dl className="pdf-details">
      <dt>姓名／编号</dt><dd>{profile?.full_name||value.username}{value.user_id?` / ${value.user_id}`:''}</dd><dt>性别／年龄</dt><dd>{profile?.gender_label||'未提供'}／{profile?.age!=null?profile.age+' 岁':'未提供'}</dd><dt>报告范围</dt><dd>{value.range_label}</dd>
      <dt>起止时间</dt><dd>{date(value.time_from)}<br/>至 {date(value.time_to)}</dd><dt>纳入对话</dt><dd>{value.conversation_count} 段 · 用户发言 {value.user_turns} 条</dd>
      <dt>经过时长</dt><dd>{elapsed}（含停顿）</dd><dt>语音识别</dt><dd>{trans.map(([key,label])=><span className="pdf-transcription" key={key}>{value.transcription_status===key?'☑':'□'}{label} </span>)}</dd><dt>紧急联系人</dt><dd>{profile?.emergency_contact_name&&profile.emergency_contact_phone?<>{profile.emergency_contact_name}<br/>{profile.emergency_contact_phone}</>:'未提供（可选）'}</dd></dl></section>
      <section className="pdf-panel pdf-score"><h2>03 量表评分</h2><div className="pdf-number"><span>量表分数{score.score==null&&score.answered>0&&<small>（已答小计）</small>}</span><strong data-testid="combined-score-number">{score.score??(score.answered>0?score.observed_score:'—')}<small>{score.score!=null?` / ${score.full_max} 分`:score.answered>0?' 分 · 未完成':' 暂未计分'}</small></strong></div>
        <div className="pdf-number"><span>置信度</span><strong data-testid="combined-confidence">{score.confidence.toLocaleString('zh-CN',{maximumFractionDigits:2})}%</strong></div>
        <div className="pdf-small"><p>已答 {score.answered}/{score.required} 题{score.answered>0?`，已答题小计 ${score.observed_score} 分`:'，暂未计分'}。</p><p>置信度按已答题比例展示（项目规则），仅表示信息覆盖程度，不是统计置信度或医学准确率。</p><p>未答完整不推算总分、不判断轻重程度；已答题小计不代表整份量表结果。</p></div></section></div>
    <section className="pdf-panel"><h2>04 量表问答概况</h2>{value.instruments.length?<table className="pdf-scale-table"><thead><tr><th>量表名称</th><th>已完成／总题数</th><th>采集覆盖率</th><th>已答条目小计</th><th>完成状态</th></tr></thead><tbody>{value.instruments.map(s=><tr key={s.scale_id}><td>{s.name}</td><td>{s.answered} / {s.required} 项</td><td>{s.coverage}%</td><td>{s.observed_score} / {s.answered_max} 分</td><td>{s.status==='complete'?'已完成':'进行中'}</td></tr>)}</tbody></table>:<p className="pdf-empty">本次未使用量表或尚无可确认作答。</p>}
      <p className="pdf-strip">仅列范围内实际使用的量表，每种显示最近任务进度；第 3 部分仅对最新同一任务计分，独立任务不拼接。{value.instruments.some(s=>s.kind==='project_indicator')?'自定义指标不计入综合分。':''}</p></section>
    <section className="pdf-panel"><h2>05 情绪变化趋势</h2><p className="pdf-chart-label">情绪参考分</p><EmotionChart value={value.emotion_trend}/><p className="pdf-strip">多日报告每段会话一个点，本次按发言顺序。积极／中性／消极映射为 100／50／0，会话内取平均；缺失断线，单点不连线，仅作表达参考。{value.emotion_trend.excluded_engine_groups>0?'不同分析口径未混合绘制。':''}</p></section>
    <div className="pdf-pair"><section className="pdf-panel"><h2>06 对话风险信号</h2><ul className="pdf-signals">{value.signals.map(s=><li key={s.key} className={s.confirmed?'confirmed':''}>{s.confirmed?'☑':'□'} {s.label}</li>)}</ul><p className="pdf-small pdf-inset">未勾选表示未确认相关线索，不等于排除风险。</p></section>
      <section className="pdf-panel"><h2>07 关键对话摘要</h2><div className="pdf-summary">{(['emotion_life','sleep_interest','daily_function'] as const).map(k=><p key={k}><strong>{value.summary_sections[k].title}：</strong>{value.summary_sections[k].text}</p>)}<p className="pdf-overview">系统综述：{value.summary}</p></div></section></div>
    <div className="pdf-pair"><section className="pdf-panel"><h2>08 分级建议与处置</h2><ul className="pdf-advice">{value.suggestions.map((s,i)=><li key={i}>{s}</li>)}</ul>{value.support_notice&&<p className="pdf-support" data-testid="report-support-notice">{audience==='care_team'?'存在需优先人工核实的安全关注线索，请人工联系紧急联系人。':'如果担心自己此刻可能受伤，请联系当地紧急服务或请身边的人陪同前往急诊，不要等待量表补全。'}{value.emergency_contact_action&&<> {value.emergency_contact_action.status==='followed_up'?'管理员已记录人工跟进。':'管理员端有待联系提醒，尚需人工处理。'}系统未自动发送短信或拨打电话。</>}</p>}</section>
      <section className="pdf-panel"><h2>09 继续完成量表</h2><div className="pdf-qr-placeholder" aria-label="扫码续答入口待配置">扫码区<br/><strong>续答入口待配置</strong></div><p className="pdf-inset">{score.score_kind==='complete'?'本轮问答已完成，可继续日常对话。':'当前可在原设备登录同一账号继续对话及未完成问答。'}</p></section></div>
    <footer className="pdf-report-footer"><p>报告用于辅助筛查与关怀参考，不构成医学诊断。模型提示和对话辅助评分存在不确定性，发现安全关注线索时优先人工核实。</p><p>报告编号：{value.report_id}　生成：{date(value.generated_at)}　审核人：未审核</p><p>保密提示：仅供本人及获授权关怀人员查阅。</p></footer>
  </article>;
}
