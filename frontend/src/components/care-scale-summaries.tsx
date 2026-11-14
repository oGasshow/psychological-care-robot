'use client';
import type {ScaleSummary,NarrativeSection} from '@/lib/care-types';
import Link from 'next/link';
const statusText:Record<string,string>={complete:'已完成',collecting:'采集中',not_collected:'尚未采集',needs_revalidation:'来源待核实'};
export default function ScaleSummaries({items,readings=[],model=false}:{items:ScaleSummary[];readings?:NarrativeSection[];model?:boolean}){
 const used=items.filter(s=>s.status!=='not_collected'),unused=items.filter(s=>s.status==='not_collected');
 function cards(values:ScaleSummary[]){return <div className="scale-summary-grid">{values.map(s=><article className="scale-summary-card" key={s.id} data-testid={`scale-summary-${s.scale_id}`}>
  <header><span className={`scale-kind ${s.kind==='standard_reference'?'standard':'custom'}`}>{s.kind==='standard_reference'?'标准量表 · 对话辅助':'项目自定义指标'}</span><span>{statusText[s.status]||s.status}</span></header>
  <h3>{s.name}</h3><p className="scale-purpose">{s.purpose}</p>
  <div className="scale-number">{s.score==null?<strong className="scale-no-score">{s.status==='not_collected'?'尚无分数':'暂不计总分'}</strong>:<><strong>{s.score}</strong><span>/ {s.max_score} 分</span></>}</div>
  <p className="scale-completion">已确认 {s.answered}/{s.item_count} 项 · 回顾范围：{s.recall_window}</p>
  {s.score!=null&&<><div className={`scale-meter ${s.kind}`} role="meter" aria-label={s.name+'辅助合计'} aria-valuenow={s.score} aria-valuemin={0} aria-valuemax={s.max_score}><span style={{width:`${s.score/s.max_score*100}%`}}/></div><p className="scale-band">{s.reference_band?`原量表分段参考：${s.reference_band}`:'频率合计 · 无临床分界'}</p></>}
  <p className="scale-meaning">{s.meaning}</p>
  {s.item9_attention&&<p className="care-notice">PHQ-9 第9项出现非零回答，需要单独关怀与核实，不能仅凭合计判断安全。</p>}
  {model&&readings.filter(r=>r.evidence_ids?.includes(s.id)).map((r,i)=><div className="scale-api-reading" key={i}><strong>结合本次记录的解读</strong><p>{r.text}</p><small>API生成 · 引用本卡片的核验事实</small></div>)}
  <details><summary>了解计分方法与依据</summary><p>{s.limitation}</p>{s.bands.length>0&&<div className="scale-band-list">{s.bands.map(b=><span key={b.min}>{b.min}—{b.max}：{b.label}</span>)}</div>}{s.reference&&<p><a href={s.reference.url} target="_blank" rel="noreferrer">原始研究：{s.reference.title}</a><br/><small>DOI：{s.reference.doi}</small></p>}{s.items.length>0&&<ol className="scale-items">{s.items.map(i=><li key={i.item}><span>{i.topic}</span><strong>{i.answer==null?'未确认':`${i.answer} · ${i.points}分`}</strong></li>)}</ol>}{s.recording_session_ids.length>0&&<p>原话来源：{s.recording_session_ids.map(id=><Link key={id} href={`/robot-care/sessions/${id}`}> 会话 #{id} </Link>)}</p>}</details>
 </article>)}</div>;}
 return <section className="scale-summaries" data-testid="scale-summaries"><div className="report-section-heading"><h2>量表与对话指标</h2></div><p>以下为所选记录中各指标最新一轮的结果。标准量表与项目自定义指标分别展示；未采齐不补分，不同指标不合成“心理健康总分”。</p>{used.length>0?cards(used):<p className="care-empty">尚无已确认的完整量表结果。</p>}{unused.length>0&&<details className="scale-unused" open={used.length===0}><summary>尚未采集：{unused.map(s=>s.scale_id).join("、")}（不代表得分为零）</summary>{cards(unused)}</details>}</section>;
}
