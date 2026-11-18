'use client';

import Link from 'next/link';
import {useState} from 'react';
import CareShell, {ErrorBox} from '@/components/care-shell';
import {date, insights} from '@/lib/care-api';

interface Group {
  is_test:boolean;
  conversation_count:number;
  user_turns:number;
  emotion_counts:Record<'positive'|'neutral'|'negative',number>;
}
interface WindowReport {
  username:string;
  time_from:string;
  time_to:string;
  generated_at:string;
  groups:Group[];
}

export default function ReportWindow(){
  const [from,setFrom]=useState('');
  const [to,setTo]=useState('');
  const [report,setReport]=useState<WindowReport|null>(null);
  const [error,setError]=useState<unknown>(null);
  const [busy,setBusy]=useState(false);

  async function generate(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();
    setError(null);setReport(null);
    if(!from || !to || from>to){setError(new Error('请选择有效的日期范围。'));return;}
    // End date is inclusive in Beijing time.
    const start=new Date(from+'T00:00:00+08:00');
    const end=new Date(new Date(to+'T00:00:00+08:00').getTime()+86400000);
    const query=new URLSearchParams({time_from:start.toISOString(),time_to:end.toISOString()});
    setBusy(true);
    try{setReport(await insights<WindowReport>('reports/window?'+query));}
    catch(err){setError(err);}
    finally{setBusy(false);}
  }

  return <CareShell title="时间窗口报告" subtitle="查看所选日期内已结束对话的汇总。">
    <form className="care-actions care-no-print" onSubmit={generate}>
      <label>开始日期 <input type="date" value={from} required disabled={busy} onChange={e=>{setFrom(e.target.value);setReport(null);}}/></label>
      <label>结束日期 <input type="date" value={to} required disabled={busy} onChange={e=>{setTo(e.target.value);setReport(null);}}/></label>
      <button className="care-btn" type="submit" disabled={busy}>{busy?'正在生成…':'生成汇总'}</button>
      {report&&<button className="care-btn secondary" type="button" onClick={()=>window.print()}>打印 / 保存 PDF</button>}
      <Link className="care-btn secondary" href="/robot-care/report">返回单次对话报告</Link>
    </form>
    <ErrorBox error={error}/>
    {report&&<article className="care-report report-template" data-testid="report-dto">
      <header className="report-heading">
        <div><h1>{report.username}的时间窗口报告</h1><p>统计日期 {from} 至 {to}（北京时间）</p></div>
        <p>生成时间 {date(report.generated_at)}</p>
      </header>
      {report.groups.length===0&&<p>所选日期内暂无已完整归档的对话。</p>}
      {report.groups.map(group=><section key={String(group.is_test)}>
        <h2>{group.is_test?'演示对话':'对话概况'}</h2>
        <p>{group.conversation_count} 场对话 · {group.user_turns} 条用户发言</p>
        <p>积极 {group.emotion_counts.positive} 条 · 中性 {group.emotion_counts.neutral} 条 · 消极 {group.emotion_counts.negative} 条</p>
      </section>)}
      <p>汇总按对话开始日期归入所选时段。个人评分、总结和建议请查看单次对话报告。</p>
    </article>}
  </CareShell>;
}
