'use client';

import Link from 'next/link';
import {useEffect,useState} from 'react';
import CareShell,{ErrorBox} from '@/components/care-shell';
import {Assessments,Trends} from '@/components/care-results';
import {Data,date,insights,label,list,natureNotice} from '@/lib/care-api';

function describe(v:unknown):string { return typeof v==='string' ? v : typeof v==='object' && v!==null ? JSON.stringify(v) : String(v??'未提供'); }
function signature(data:Data):string { const copy={...data}; delete copy.generated_at; delete copy.data_as_of; return JSON.stringify(copy); }

export default function ReportPage({printMode=false}:{printMode?:boolean}) {
  const [mode,setMode]=useState('time');
  const [ids,setIds]=useState('');
  const [from,setFrom]=useState('2026-10-01T00:00');
  const [to,setTo]=useState('2026-11-01T00:00');
  const [scope,setScope]=useState<Data|null>(null);
  const [dto,setDto]=useState<Data|null>(null);
  const [error,setError]=useState<unknown>(null);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  useEffect(()=>{
    try { const saved=JSON.parse(sessionStorage.getItem('care-report-scope')||'null'); if(saved){setScope(saved);if(saved.session_ids){setMode('sessions');setIds(saved.session_ids.join(','));}void request(saved,false);} }
    catch{setMessage('请重新选择报告范围。');}
  },[]);
  async function request(selected:Data,print:boolean) {
    setBusy(true);setError(null);setMessage('正在重新读取并核验来源…');
    try{
      const latest=await insights('reports/preview',{method:'POST',body:JSON.stringify({scope:selected})});
      const changed=dto && signature(dto)!==signature(latest);
      setDto(latest);setScope(selected);sessionStorage.setItem('care-report-scope',JSON.stringify(selected));
      setMessage(changed ? '已重新核验来源；来源数据已有变化，预览和打印已更新为同一份最新报告。' : '已重新核验来源；预览和打印使用本次返回的同一份报告。');
      if(print){await new Promise(resolve=>setTimeout(resolve,100));await document.fonts.ready;window.print();}
    }catch(e){setDto(null);setError(e);setMessage('来源核验失败，已清除旧预览。请解决后重新生成。');}finally{setBusy(false);}
  }
  function generate(){
    let selected:Data;
    if(mode==='sessions'){
      const values=ids.split(/[,，\s]+/).filter(Boolean).map(Number);
      if(!values.length||values.length>50||values.some(n=>!Number.isSafeInteger(n)||n<1)){setError(new Error('请输入 1—50 个有效会话 ID，以逗号分隔。'));return;}
      selected={session_ids:values};
    }else{
      const start=new Date(`${from}:00+08:00`),end=new Date(`${to}:00+08:00`);
      if(Number.isNaN(start.valueOf())||Number.isNaN(end.valueOf())||start>=end){setError(new Error('请提供成对且结束晚于开始的时间范围。'));return;}
      selected={time_from:start.toISOString(),time_to:end.toISOString()};
    }
    void request(selected,false);
  }
  return <CareShell title={printMode?'报告打印与来源核验':'陪伴与量表报告摘要'} subtitle="报告按当前请求临时组装，服务端不长期保存报告正文。选择范围后，核对来源与数据缺口。">
    {!printMode&&<section className="care-card care-no-print"><h2>选择统计范围</h2><label htmlFor="report-mode">范围类型</label><select id="report-mode" value={mode} onChange={e=>setMode(e.target.value)}><option value="time">时间窗口（对话发生时间 / 已确认量表完成时间）</option><option value="sessions">指定会话（不自动关联量表）</option></select>{mode==='sessions'?<><label htmlFor="report-ids">本人会话 ID，逗号分隔</label><input id="report-ids" value={ids} onChange={e=>setIds(e.target.value)}/></>:<><label htmlFor="report-from">开始（北京时间 UTC+8，包含）</label><input id="report-from" type="datetime-local" value={from} onChange={e=>setFrom(e.target.value)}/><label htmlFor="report-to">结束（北京时间 UTC+8，不包含）</label><input id="report-to" type="datetime-local" value={to} onChange={e=>setTo(e.target.value)}/></>}<div className="care-actions"><button className="care-btn" disabled={busy} onClick={generate}>读取来源并生成预览</button></div></section>}
    <div className="care-actions care-no-print">{dto&&scope&&<><button className="care-btn" disabled={busy} onClick={()=>request(scope,true)}>重新核验来源并打印 / 保存 PDF</button>{!printMode&&<Link className="care-btn secondary" href="/robot-care/report/print">打开专用打印页</Link>}</>}{printMode&&<Link className="care-btn secondary" href="/robot-care/report">返回范围与预览</Link>}</div><p className="care-meta care-no-print" role="status" data-testid="report-status">{message}</p><ErrorBox error={error}/>
    {printMode&&!scope&&!busy&&<p className="care-notice care-no-print">请先返回报告预览选择统计范围。URL 中不传递正文、答案或 token。</p>}
    {dto&&<ReportBody dto={dto}/>}
  </CareShell>;
}

function ReportBody({dto}:{dto:Data}) {
  const isTest=Boolean(dto.is_test);
  return <article className="care-report" data-testid="report-dto" data-generated-at={dto.generated_at}>
    <div className="care-print-stamp">{isTest?'模拟数据演示 · ':''}辅助陪伴记录摘要 · 非诊断用途</div>
    <div className="care-eyebrow">XINYI / 辅助陪伴记录摘要</div><h1 className="care-title">陪伴与量表报告</h1>{isTest&&<p className="care-notice care-warning"><strong>模拟数据演示</strong> · 所有内容来自专用虚构测试数据，不是真实评估。</p>}
    <p><strong>匿名展示编号：{dto.anonymous_id || dto.anonymous_code}</strong></p><p className="care-meta">报告生成：{date(dto.generated_at)}<br/>数据截至：{date(dto.data_as_of)}<br/>报告结构版本：{dto.schema_version || '1.0'}</p>
    <section><h2>统计范围与记录完整性</h2>{dto.scope?.session_ids?<p>指定会话：{dto.scope.session_ids.map((id:number)=>`#${id}`).join('、')}。未关联量表，未纳入本报告。</p>:<p>时间窗口（左闭右开）：{date(dto.scope?.time_from)} 至 {date(dto.scope?.time_to)}。对话按原始发生时间、量表按已确认完成时间筛选。</p>}{list(dto.sessions).map((s,i)=><p key={i}>会话 #{s.recording_session_id} · {label(s.state)} · {s.is_complete?'记录已收齐':'记录尚未收齐，结果不完整'} · 已保存 {s.received_record_count??'未提供'} 条</p>)}</section>
    <section><h2>主要情绪与来源</h2><div className="care-grid">{['positive','neutral','negative'].map(k=><div className="care-stat" key={k}>{label(k)}记录<strong>{dto.emotion_counts?.[k] ?? 0}</strong></div>)}</div><p className="care-meta">这些是单条文本的规则/模型分类，不代表临床结论。未知、失败、过期与排除记录不加入有效类别计数。</p>{dto.analysis_counts&&<p>{Object.entries(dto.analysis_counts).map(([k,v])=><span className="care-badge" key={k}>{label(k)} {describe(v)}</span>)}</p>}</section>
    <Trends data={dto}/>
    <section><h2>有效量表分数与参考解释</h2><Assessments items={list(dto.assessments)} empty={dto.scope?.session_ids?'未关联量表，未纳入本报告。':'当前范围没有确认可纳入的量表结果，未补 0 分或“正常”。'}/></section>
    <section><h2>非医疗建议</h2>{list(dto.suggestions).length?dto.suggestions.map((s:unknown,i:number)=><p className="care-text" key={i}>{describe(s)}</p>):<p>如愿意，可以记录自己的感受，与信任的人交流；需要时寻求合格专业人员的帮助。</p>}</section>
    <section><h2>数据缺失与说明</h2>{list(dto.warnings).length?dto.warnings.map((w:unknown,i:number)=><p className="care-text" key={i}>{describe(w)}</p>):<p>以本次来源核验结果为准。真实模型、真实语音与量表有效性须分别验证。</p>}<p>{dto.nature_notice || natureNotice}</p>{isTest&&<p>fixture 的“已验证”仅指虚构演示数据的契约有效；适用范围为 demo_only，不能代替正式内容审核与适老确认。</p>}</section>
    <section><h2>来源 ID 与版本</h2>{list(dto.source_references).length?<div className="care-table-wrap"><table><thead><tr><th>来源引用（保留记录与输入版本）</th></tr></thead><tbody>{dto.source_references.map((s:unknown,i:number)=><tr key={i}><td className="care-text care-meta">{describe(s)}</td></tr>)}</tbody></table></div>:<p>本范围暂无有效来源引用。</p>}</section>
  </article>;
}
