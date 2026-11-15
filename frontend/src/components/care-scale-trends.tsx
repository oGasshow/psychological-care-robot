'use client';
import Link from 'next/link';
import type {ScaleTrend,ScaleTrendPoint} from '@/lib/care-types';
import {date,list} from '@/lib/care-api';
import {DataNatureBadge} from './care-results';

function Plot({group,points}:{group:ScaleTrend;points:ScaleTrendPoint[]}){
 const times=points.map(p=>Date.parse(p.observed_at!)),first=Math.min(...times),span=Math.max(1,Math.max(...times)-first);
 const coords=points.map((p,i)=>({x:45+590*(times[i]-first)/span,y:160-130*p.score!/group.max_score,p}));
 return <svg className="scale-trend-chart" viewBox="0 0 680 215" role="img" aria-label={`${group.name}，${points.length}次完整结果，按北京时间排列`}>
  {[0,group.max_score/2,group.max_score].map(value=><g key={value}><line x1="45" x2="635" y1={160-130*value/group.max_score} y2={160-130*value/group.max_score} className="trend-grid"/><text x="34" y={164-130*value/group.max_score} textAnchor="end">{value}</text></g>)}
  <polyline points={coords.map(c=>`${c.x},${c.y}`).join(' ')} fill="none" className="trend-line"/>
  {coords.map(({x,y,p},i)=><g key={p.id}><title>{date(p.observed_at)}：{p.score}/{group.max_score}</title><circle cx={x} cy={y} r="5"/><text x={x} y={y-12} textAnchor="middle" className="trend-value">{p.score}</text>{(i===0||i===coords.length-1||i%Math.ceil(coords.length/5)===0)&&<text x={x} y="185" textAnchor="middle">{new Date(p.observed_at!).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit'})}</text>}</g>)}
  <text x="340" y="207" textAnchor="middle">采集时间（北京时间）</text>
 </svg>;
}

export default function ScaleTrends({items}:{items:ScaleTrend[]}){
 return <section className="scale-trends" data-testid="scale-trends"><div className="report-section-heading"><h2>多次量表与指标的变化</h2></div><p className="report-explanation">同一采集任务跨会话续采或重复保存只算一次。完整结果按原话采集时间排列；未完成或来源待核实的记录不补分。不同量表、演示模式和来源属性分别展示。</p>
 {!items.length&&<p className="care-empty">所选范围暂无量表或指标采集记录。可选择近30天或更多会话查看历史。</p>}
 {items.map(g=>{const complete=list(g.points).filter(p=>p.score!=null&&p.observed_at);return <article className="scale-trend-group" key={g.id} data-testid={`scale-trend-${g.scale_id}`} data-completed-count={g.completed_count}>
  <header><h3>{g.name}</h3><DataNatureBadge isTest={g.is_test}/></header><p className="care-meta">{g.kind==='standard_reference'?'标准量表 · 对话辅助':'项目自定义指标'} · 满分 {g.max_score} 分 · {g.direction}</p>
  {complete.length>=2?<><Plot group={g} points={complete}/><p className="scale-trend-change" data-testid="scale-trend-change">{complete.length} 次完整结果：{complete[0].score} → {complete.at(-1)!.score} 分；{g.numeric_change===0?'首末分数相同':`较首次${g.numeric_change!>0?'增加':'减少'} ${Math.abs(g.numeric_change!)} 分`}。</p><p className="care-meta">这是记录分数的变化，不直接表示整体心理状态改善或恶化。</p></>:<p className="care-empty">当前范围只有 {complete.length} 次完整结果，暂不足以形成趋势；可扩大日期范围查看。</p>}
  <div className="care-table-wrap"><table><thead><tr><th>采集时间（北京时间）</th><th>分数 / 满分</th><th>完成度</th><th>原话来源</th></tr></thead><tbody>{list(g.points).map(p=><tr key={p.id} data-episode-id={p.episode_id}><td>{date(p.observed_at)}</td><td>{p.score==null?(p.status==='needs_revalidation'?'来源待核实':'信息未齐，未计分'):`${p.score} / ${g.max_score}`}</td><td>{p.answered}/{p.required}</td><td>{p.recording_session_ids.map(sid=><Link key={sid} href={`/robot-care/sessions/${sid}`}>会话 #{sid} </Link>)}</td></tr>)}</tbody></table></div>
 </article>;})}</section>;
}
