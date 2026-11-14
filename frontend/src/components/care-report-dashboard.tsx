'use client';
import type {TimeScope,ReportScope,ReportData,ReportFacts,ReportGroup} from '@/lib/care-types';

import Link from 'next/link';
import {useCallback,useEffect,useRef,useState} from 'react';
import CareShell,{ErrorBox} from '@/components/care-shell';
import ScaleSummaries from '@/components/care-scale-summaries';
import DangerNotice from '@/components/care-danger-notice';
import {DataNatureBadge,reportDataNature,dataNatureText} from '@/components/care-results';
import {ApiError,date,insights,label,list} from '@/lib/care-api';
import {Card,CardContent,CardDescription,CardFooter,CardHeader,CardTitle} from '@/components/report-ui/card';

const localInput=(v:string)=>new Date(new Date(v).valueOf()+8*3600000).toISOString().slice(0,19);
const shortDate=(v:string)=>new Date(v).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric'});
function period(days=7,complete=false):TimeScope {const end=new Date(Date.now()+8*3600000);end.setUTCHours(0,0,0,0);if(!complete)end.setUTCDate(end.getUTCDate()+1);const start=new Date(end);start.setUTCDate(start.getUTCDate()-days);return {time_from:new Date(start.valueOf()-8*3600000).toISOString(),time_to:new Date(end.valueOf()-8*3600000).toISOString()};}
const rangeText=(s:ReportScope)=>s.session_ids?`所选 ${s.session_ids.length} 个会话`:`${shortDate(s.time_from)} — ${shortDate(new Date(Date.parse(s.time_to)-1).toISOString())}`;
const reasonText=(r:string)=>({selected_sessions:'当前选择会话，未自动关联上一周期。',long_window:'范围较长，请缩短至 93 天以内查看按日分布。',partial_days:'范围包含不完整自然日，暂不进行周期比较。',includes_today:'本范围包含尚未结束的日期，暂不进行周期比较。',insufficient_comparable_records:'同口径记录不足：每周期至少需 5 条分类，并分布在至少 3 天。'}[r]||'暂时没有足够的同口径记录进行周期比较。');

export default function ReportPage({printMode=false}:{printMode?:boolean}) {
  const initial=period();
  const [mode,setMode]=useState('time'),[ids,setIds]=useState('');
  const [from,setFrom]=useState(()=>localInput(initial.time_from)),[to,setTo]=useState(()=>localInput(initial.time_to));
  const [scope,setScope]=useState<ReportScope|null>(null),[dto,setDto]=useState<ReportData|null>(null);
  const [error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
  const requestId=useRef(0);
  const request=useCallback(async function readReport(selected:ReportScope,print:boolean,retryChanged=true){
    const id=++requestId.current;setBusy(true);setError(null);setMessage('正在整理最新记录…');
    try{
      const latest=await insights<ReportData>('reports/preview',{method:'POST',body:JSON.stringify({scope:selected})});if(id!==requestId.current)return;
      setDto(latest);setScope(selected);sessionStorage.setItem('care-report-scope',JSON.stringify(selected));setMessage('记录已更新，正在准备文字回顾…');
      let complete=latest;
      try{const value=await insights<Pick<ReportData,'source_snapshot_hash'|'narrative'>>('reports/narrative',{method:'POST',body:JSON.stringify({scope:selected,source_snapshot_hash:latest.source_snapshot_hash})});if(value.source_snapshot_hash!==latest.source_snapshot_hash)throw new ApiError(409,'report_sources_changed');complete={...latest,narrative:value.narrative};}
      catch(e){if(e instanceof ApiError&&[401,403,404,409,410].includes(e.status))throw e;complete={...latest,narrative:{...latest.narrative,reason_code:'summary_request_failed'}};}
      if(id!==requestId.current)return;setDto(complete);setMessage(complete.narrative.mode==='model'?'已根据本次记录生成模型文字回顾。':'已根据最新记录生成自动回顾；当前采用规则摘要。');
      if(print){await document.fonts.ready;await new Promise(resolve=>window.requestAnimationFrame(()=>window.requestAnimationFrame(resolve)));if(id===requestId.current)window.print();}
    }catch(e){if(id!==requestId.current)return;setDto(null);
      if(retryChanged&&e instanceof ApiError&&e.status===409&&e.code==='report_sources_changed'){
        // Fresh uploads may finish background analysis during model generation.
        // Discard that output and regenerate once from an entirely new snapshot.
        await readReport(selected,print,false);return;
      }
      setError(e);setMessage(e instanceof ApiError&&e.status===409?'记录在生成期间发生变化，旧回顾已清除，请刷新本次回顾。':'暂时无法读取报告，请重试。');}
    finally{if(id===requestId.current)setBusy(false);}
  },[]);
  useEffect(()=>{const cancel=()=>{requestId.current++;};const timer=window.setTimeout(()=>{let saved:ReportScope|null=null;try{saved=JSON.parse(sessionStorage.getItem('care-report-scope')||'null');}catch{/* New range. */}const chosen=saved||period();if(chosen.session_ids){setMode('sessions');setIds(chosen.session_ids.join(','));}else{setFrom(localInput(chosen.time_from));setTo(localInput(chosen.time_to));}void request(chosen,false);},0);return()=>{window.clearTimeout(timer);cancel();};},[request]);
  function quick(days:number,complete=false){const selected=period(days,complete);setMode('time');setFrom(localInput(selected.time_from));setTo(localInput(selected.time_to));void request(selected,false);}
  function generate(){
    if(mode==='sessions'){const values=ids.split(/[,，\s]+/).filter(Boolean).map(Number);if(!values.length||values.length>50||new Set(values).size!==values.length||values.some(n=>!Number.isSafeInteger(n)||n<1)){setError(new Error('请输入 1—50 个不重复的有效会话编号。'));return;}void request({session_ids:values},false);return;}
    const start=new Date(`${from.length===16?`${from}:00`:from}+08:00`),end=new Date(`${to.length===16?`${to}:00`:to}+08:00`);if(Number.isNaN(start.valueOf())||Number.isNaN(end.valueOf())||start>=end){setError(new Error('请选择有效的开始和结束时间。'));return;}void request({time_from:start.toISOString(),time_to:end.toISOString()},false);
  }
  return <CareShell title="近期陪伴回顾" subtitle="回顾最近的对话，看看哪些感受和日常值得继续聊聊。">
    <div className="report-toolbar care-no-print"><div className="report-toolbar-main"><div className="report-periods" aria-label="报告时间范围"><button className="care-btn secondary" disabled={busy} onClick={()=>quick(7)}>近 7 天 · 含今天</button><button className="care-btn secondary" disabled={busy} onClick={()=>quick(7,true)}>近 7 个完整日</button><button className="care-btn secondary" disabled={busy} onClick={()=>quick(30)}>近 30 天</button></div>{scope&&<button className="care-btn secondary" disabled={busy} onClick={()=>request(scope,false)}>刷新本次回顾</button>}</div>{dto&&scope&&<button className="care-btn report-export" disabled={busy} onClick={()=>request(scope,true)}>更新并打印 / 保存 PDF</button>}</div>
    {!printMode&&<details className="report-scope care-no-print"><summary>自定义日期或会话</summary><div className="report-scope-fields"><div><label htmlFor="report-mode">范围类型</label><select id="report-mode" value={mode} onChange={e=>setMode(e.target.value)}><option value="time">日期范围</option><option value="sessions">指定会话</option></select></div>{mode==='sessions'?<div><label htmlFor="report-ids">会话编号，以逗号分隔</label><input id="report-ids" value={ids} onChange={e=>setIds(e.target.value)}/></div>:<><div><label htmlFor="report-from">开始（北京时间，包含）</label><input id="report-from" type="datetime-local" step="1" value={from} onChange={e=>setFrom(e.target.value)}/></div><div><label htmlFor="report-to">结束（北京时间，不包含）</label><input id="report-to" type="datetime-local" step="1" value={to} onChange={e=>setTo(e.target.value)}/></div></>}<button className="care-btn" disabled={busy} onClick={generate}>读取来源并生成预览</button></div></details>}
    <p className="care-meta care-no-print" role="status" data-testid="report-status">{message}</p><ErrorBox error={error}/>{Boolean(error)&&<button className="care-btn secondary care-no-print report-retry" disabled={busy} onClick={()=>request(scope||period(),false)}>{busy?'正在重试…':'重新读取回顾'}</button>}{dto&&<ReportBody dto={dto} busy={busy}/>}{printMode&&<Link className="care-btn secondary care-no-print" href="/robot-care/report">返回报告</Link>}
  </CareShell>;
}

function Evidence({ids,facts}:{ids:unknown;facts:ReportFacts}){
  const values=list<string>(ids);if(!values.length)return null;
  return <details className="report-evidence"><summary>查看依据</summary><div>{values.map((id:string)=>{const e=list(facts.evidence).find(v=>v.id===id),f=list(facts.facts).find(v=>v.id===id);return e?<div key={id}><p className="care-meta">{date(e.occurred_at)} · 记录 #{e.record_id} · 修订 {e.input_revision} <DataNatureBadge isTest={e.is_test}/></p><blockquote>{e.text}{e.truncated?'…（节选）':''}</blockquote></div>:f?.kind==='scale_result'?<div key={id}><strong>{f.name}</strong><p>已确认 {f.answered}/{f.item_count} 项 · {f.score==null?'尚无有效总分':`辅助合计 ${f.score}/${f.max_score}`}</p><p>{f.meaning}</p>{f.reference&&<a href={f.reference.url} target="_blank" rel="noreferrer">原始研究：{f.reference.title}</a>}</div>:<p className="care-meta" key={id}>{f?.kind==='coverage'?`${f.is_test?'模拟':'非测试标志'}记录：${f.active_days} 个记录日，${f.classified_count}/${f.user_text_count} 条有效分类。`:f?.kind==='classification_comparison'?'依据下方同口径周期统计。':'依据本次范围、记录覆盖及来源完整性。'}</p>;})}</div></details>;
}

function ReportBody({dto,busy}:{dto:ReportData;busy:boolean}){
  const facts=dto.report_facts||{},nature=reportDataNature(facts),n=dto.narrative||{},c=n.content||{},evidence=list(facts.evidence);
  return <article className="care-report report-template" data-testid="report-dto" data-is-test={nature==='test_only'?'true':'false'} data-data-nature={nature} data-generated-at={dto.generated_at}>
    <div className="care-print-stamp" data-testid="report-print-nature">{dataNatureText(nature)} · 辅助陪伴回顾 · 非诊断用途</div>
    <header className="report-heading"><div><div className="care-eyebrow">陪伴记录 / 一段时间的回顾</div><h1>近期陪伴回顾</h1><p className="report-range">{rangeText(dto.scope)}</p></div><div className="report-identity"><span className="care-badge" data-testid="report-nature-notice">{dataNatureText(nature)}</span><p>{dto.anonymous_id}</p><p className="care-meta">数据截至 {date(dto.data_as_of)}</p></div></header>
    <DangerNotice data={dto.danger_notice}/>
    <ScaleSummaries items={list(dto.scale_summaries)} readings={list(c.scale_readings)} model={n.mode==='model'}/>
    <section className="report-overview" data-testid="report-overview"><div className="report-section-heading"><h2>这段时间，记录告诉我们</h2><span className="report-provenance">{busy?'正在准备文字回顾…':n.mode==='model'?'模型生成 · 可查看依据':'自动摘要 · 规则生成'}</span></div><p className="report-overview-text">{c.overview?.text||'当前记录还不足以形成回顾。'}</p><Evidence ids={c.overview?.evidence_ids} facts={facts}/>{n.mode!=='model'&&!busy&&<p className="care-meta" data-testid="report-model-status">{['model_not_configured','not_requested'].includes(n.reason_code || '')?'模型总结尚未启用，当前根据已保存记录自动整理。':n.reason_code==='no_user_records'?'有了新的对话后，可以再次生成回顾。':n.reason_code==='mixed_sources_use_separate_rules'?'混合来源采用分流统计与规则摘要。':'本次模型总结未完成，已保留当前记录生成的规则摘要。'}</p>}</section>
    {list(facts.coverage).map(v=><div className="report-coverage" key={String(v.is_test)}>{nature==='mixed'&&<h2>{v.is_test?'模拟记录':'非测试标志记录'}</h2>}<div className="report-summary-cards"><Metric title="留下对话的日期" value={v.active_days} suffix={` / ${v.window_days} 天`} foot="空缺日期表示没有记录"/><Metric title="有效文本分类" value={v.classified_count} suffix={` / ${v.user_text_count} 条`} foot={v.unclassified_count?`${v.unclassified_count} 条尚未形成有效分类`:'当前用户文本均已形成分类'}/><Metric title="最近一次记录" value={shortDate(v.latest_record_at)} foot={`${new Date(v.latest_record_at).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false})} · 北京时间`}/></div></div>)}
    <section><div className="report-section-heading"><h2>每天的表达，有什么变化</h2><span className="care-meta">按用户文本条数展示</span></div><p className="report-explanation">积极、中性、消极是已记录文字的分类。无记录日留空，未分类文字不补成中性。</p>{!list(facts.groups).length&&<p className="care-empty">暂无有效分类，仍可在下方查看已保存原话。</p>}{list(facts.groups).map((g,i)=><ChartGroup group={g} facts={facts} key={i}/>)}</section>
    <section><h2>最近提到的事</h2><p className="report-explanation">这些话题来自原话中的提及，用于继续交流；不表示生活状况已被客观测量。</p>{list(facts.topics).length?<div className="report-topic-grid">{list(facts.topics).slice(0,4).map((t,i)=><Card key={i}><CardHeader><CardDescription>{t.is_test?'模拟记录':'非测试标志记录'}</CardDescription><CardTitle>{t.title}</CardTitle></CardHeader><CardContent><blockquote>{evidence.find(e=>e.id===t.evidence_ids[0])?.text}</blockquote><Evidence ids={t.evidence_ids} facts={facts}/></CardContent></Card>)}</div>:<p className="care-empty">暂未提取到可展示的话题，可以展开下方原话查看。</p>}</section>
    {([['changes','文字回顾中的变化'],['topics','原话中的线索']] as const).map(([key,title])=>!!list(c[key]).length&&<section key={key}><h2>{title}</h2>{list(c[key]).map((s,i)=><div key={i}><p>{s.text}</p><Evidence ids={s.evidence_ids} facts={facts}/></div>)}</section>)}
    <section className="report-next"><h2>下次可以从这里聊起</h2>{list(c.conversation_suggestions).length?list(c.conversation_suggestions).map((s,i)=><div className="report-suggestion" key={i}><span>{String(i+1).padStart(2,'0')}</span><div><p>{s.text}</p><Evidence ids={s.evidence_ids} facts={facts}/></div></div>):<p>如果愿意，可以先记录最近发生的一件小事，以及当时的感受。</p>}</section>
    <section className="report-limits"><h2>理解这份回顾时</h2>{list(c.limitations).map((s,i)=><p key={i}>{s.text}</p>)}{list(dto.sessions).some(s=>!s.is_complete)&&<p>部分会话尚未收齐，回顾仅覆盖已收到的记录。</p>}<p>{facts.evidence_selection?.sampled?'原话经过时间分散抽样，不能据此穷尽所有话题。':'下方提供本次选取的原话依据。'}{facts.evidence_selection?.danger_excluded_count?'明确危险表达的来源在上方独立提示区展示。':''}</p><p>辅助陪伴记录用于了解表达、支持交流，不构成诊断，也不能替代专业评估。</p></section>
    <details className="report-source-details" data-testid="report-source-details"><summary>查看记录、版本与生成信息</summary><div><p className="care-meta">生成：{date(dto.generated_at)} · 结构 {dto.schema_version} · 摘要 {n.prompt_version}{n.model?` · 模型 ${n.model}`:''}<br/>来源快照：{dto.source_snapshot_hash}</p><p className="care-meta">分析口径：{list(facts.groups).map(g=>`${g.engine_kind} / ${g.engine_version} / ${g.config_version} / ${g.is_test?'模拟':'非测试标志'}`).join('；')}</p>{evidence.map(e=><div className="report-source-row" key={e.id}><p className="care-meta">{date(e.occurred_at)} · 会话 #{e.recording_session_id} · 记录 #{e.record_id} · 修订 {e.input_revision} <DataNatureBadge isTest={e.is_test}/></p><p className="care-text">{e.text}{e.truncated?'…（节选）':''}</p></div>)}<details><summary>全部来源引用与分析状态</summary><div className="care-table-wrap"><table><thead><tr><th>来源属性</th><th>记录与版本</th></tr></thead><tbody>{list(dto.source_references).map((s,i)=><tr key={i}><td><DataNatureBadge isTest={s.is_test}/></td><td className="care-meta">{JSON.stringify(s)}</td></tr>)}</tbody></table></div></details></div></details>
  </article>;
}

function Metric({title,value,suffix='',foot}:{title:string;value:string|number;suffix?:string;foot:string}){return <Card><CardHeader><CardDescription>{title}</CardDescription><CardTitle>{value}<small>{suffix}</small></CardTitle></CardHeader><CardFooter>{foot}</CardFooter></Card>;}
function ChartGroup({group:g,facts}:{group:ReportGroup;facts:ReportFacts}){
  const rows=list(g.daily),max=Math.max(1,...rows.map(d=>d.classified_count)),comp=g.comparison;
  return <div className="report-chart-group"><div className="report-chart-heading"><DataNatureBadge isTest={g.is_test}/><div className="report-legend">{['positive','neutral','negative'].map(k=><span key={k}><i className={k}/>{label(k)} {g.counts[k]}</span>)}</div></div>{rows.length?<div className={`report-daily-chart ${rows.length>14?'report-dense-chart':''}`} style={{'--days':rows.length} as React.CSSProperties} role="img" aria-label="每日文本类别数量；可展开数据表查看数值。">{rows.map((d,i)=><div className="report-day" key={d.day} title={`${d.day}：积极 ${d.positive}，中性 ${d.neutral}，消极 ${d.negative}`}><span className="report-day-count">{d.classified_count||'—'}</span><div className="report-bar-space"><div className="report-bar">{(['negative','neutral','positive'] as const).map(k=><span className={k} key={k} style={{height:`${130*d[k]/max}px`}}/>)}{!d.classified_count&&<span className="report-no-data">{rows.length<=14?(d.has_user_records?'未分类':'无记录'):'·'}</span>}</div></div><time>{rows.length<=14||i%5===0||i===rows.length-1?`${Number(d.day.slice(5,7))}/${Number(d.day.slice(8))}`:''}</time></div>)}</div>:<p className="care-empty">范围较长，未绘制逐日分布；可缩短范围查看。</p>}
    {comp.eligible?<div className="report-comparison" data-testid="report-comparison"><strong>与前一周期相比</strong><p>消极类别文本占比：{comp.previous_counts.negative}/{comp.previous_count}（{(100*comp.previous_counts.negative/comp.previous_count).toFixed(1)}%）→ {g.counts.negative}/{g.classified_count}（{(100*g.counts.negative/g.classified_count).toFixed(1)}%），{comp.negative_share_delta_pp===0?'占比相同':`${comp.negative_share_delta_pp>0?'增加':'减少'} ${Math.abs(comp.negative_share_delta_pp)} 个百分点`}。</p><p className="care-meta">只描述已记录文本的变化，不能据此判断整体心理状态改善或恶化。</p></div>:<p className="report-comparison-empty" data-testid="report-insufficient">{reasonText(comp.reason_code)}</p>}
    <details className="report-evidence"><summary>查看每日数据与分类口径</summary><p className="care-meta">{g.engine_kind} / {g.engine_version} / {g.config_version}。仅比较相同引擎、配置、测试属性的完整周期；展示门槛不属于临床阈值。</p>{facts.comparison_scope&&<p className="care-meta">前一周期：{rangeText(facts.comparison_scope)}</p>}<div className="care-table-wrap"><table><thead><tr><th>日期</th><th>积极</th><th>中性</th><th>消极</th><th>记录情况</th></tr></thead><tbody>{rows.map(d=><tr key={d.day}><td>{d.day}</td><td>{d.positive}</td><td>{d.neutral}</td><td>{d.negative}</td><td>{d.classified_count?'已有有效分类':d.has_user_records?'有记录，暂无该口径分类':'无记录'}</td></tr>)}</tbody></table></div></details>
  </div>;
}
