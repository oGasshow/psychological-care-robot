'use client';

import {useCallback,useEffect,useRef,useState} from 'react';
import Link from 'next/link';
import {api,ApiError,date,insights} from '@/lib/care-api';
import type {Page,SessionRecord,SessionScore} from '@/lib/care-types';
import CareShell,{ErrorBox} from './care-shell';

interface Wording {summary:string;suggestions:string[]}
export interface SessionReport extends Wording {
  username:string;started_at:string;ended_at:string;generated_at:string;is_test:boolean;
  user_turns:number;emotion_counts:Record<string,number>;scores:SessionScore[];frequencies:Record<string,number>;
  support_notice:boolean;source_snapshot_hash:string;
}

const emotions = [['positive','积极'],['neutral','中性'],['negative','消极']] as const;
const selfAssessments = [
  ['心情与兴趣','PHQ-9 心情自评（英文）','https://screening.mhanational.org/screening-tools/depression/'],
  ['紧张与担忧','GAD-7 焦虑自评（英文）','https://screening.mhanational.org/screening-tools/anxiety/'],
  ['睡眠困扰','ISI 失眠严重程度自评（英文）','https://www.mirecc.va.gov/visn19/treatmentworksforvets/insomnia/check-for-symptoms.asp'],
  ['主观幸福感','WHO-5 幸福感量表（可选中文版）','https://www.who.int/zh/publications/m/item/WHO-UCN-MSD-MHE-2024.01'],
  ['重大事件后的困扰','创伤后应激自评（英文）','https://screening.mhanational.org/screening-tools/ptsd/'],
] as const;

export default function SessionReportPage({printMode=false}:{printMode?:boolean}) {
  const [sessions,setSessions]=useState<SessionRecord[]>([]);
  const [cursor,setCursor]=useState<string|null>(null);
  const [value,setValue]=useState<SessionReport|null>(null);
  const [selected,setSelected]=useState('');
  const [busy,setBusy]=useState(false);
  const [listing,setListing]=useState(true);
  const [error,setError]=useState<unknown>(null);
  const active=useRef<AbortController|null>(null);

  const loadReport=useCallback(async (sid:number,print=false)=>{
    active.current?.abort();
    const request=new AbortController();
    active.current=request;
    setBusy(true);setValue(null);setError(null);
    const publish=async (report:SessionReport)=>{
      if(request.signal.aborted)return;
      setValue(report);
      if(print){
        await document.fonts.ready;
        await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));
        if(!request.signal.aborted)window.print();
      }
    };
    try {
      for(let attempt=0;attempt<2;attempt++){
        const report=await insights<SessionReport>(`reports/session/${sid}`,{signal:request.signal});
        try {
          const wording=await insights<Wording>(`reports/session/${sid}/narrative`,{
            method:'POST',body:JSON.stringify({source_snapshot_hash:report.source_snapshot_hash}),signal:request.signal
          });
          await publish({...report,...wording});
          return;
        } catch(err){
          if(request.signal.aborted)return;
          if(err instanceof ApiError && err.status===409 && attempt===0)continue;
          if(err instanceof ApiError && [401,403,404,409,410].includes(err.status))throw err;
          await publish(report);
          return;
        }
      }
    } catch(err){if(!request.signal.aborted)setError(err instanceof ApiError && err.code==='report_session_incomplete'
      ? new Error('请等本次对话结束并保存完整后，再生成报告。') : err);}
    finally{if(!request.signal.aborted)setBusy(false);}
  },[]);

  const loadList=useCallback(async (next?:string)=>{
    setListing(true);
    try {
      const page=await api<Page<SessionRecord>>('robot-records/sessions?limit=50'+(next?'&cursor='+encodeURIComponent(next):''));
      setSessions(previous=>[...(next?previous:[]),...page.items.filter(row=>row.is_complete)]);
      setCursor(page.next_cursor);
    } catch(err){setError(err);}
    finally{setListing(false);}
  },[]);

  useEffect(()=>{
    const timer=window.setTimeout(()=>{
      const sid=new URLSearchParams(window.location.search).get('session');
      if(sid && /^[1-9]\d*$/.test(sid) && Number.isSafeInteger(Number(sid))){
        setSelected(sid);void loadReport(Number(sid));
      }
      void loadList();
    },0);
    return ()=>{window.clearTimeout(timer);active.current?.abort();};
  },[loadList,loadReport]);

  function choose(sid:string){
    setSelected(sid);
    const url=new URL(window.location.href);
    if(sid){url.searchParams.set('session',sid);void loadReport(Number(sid));}
    else {url.searchParams.delete('session');active.current?.abort();setValue(null);setBusy(false);}
    window.history.replaceState(null,'',url);
  }

  return <CareShell title="对话报告" subtitle="选择一次已结束的对话，查看本次结果。">
    <div className="care-actions care-no-print">
      <label htmlFor="report-session">选择对话</label>
      <select id="report-session" value={selected} onChange={event=>choose(event.target.value)}>
        <option value="">请选择已结束的对话</option>
        {selected&&!sessions.some(s=>String(s.recording_session_id)===selected)&&<option value={selected}>{value?date(value.started_at):'已选择的会话'}</option>}
        {sessions.map(s=><option value={s.recording_session_id} key={s.recording_session_id}>{date(s.started_at)}（{s.received_record_count}条记录）</option>)}
      </select>
      {cursor&&<button className="care-btn secondary" disabled={listing} onClick={()=>void loadList(cursor)}>查看更多对话</button>}
      {selected&&!printMode&&<button className="care-btn secondary" disabled={busy} onClick={()=>void loadReport(Number(selected))}>重新生成</button>}
      {value&&<button className="care-btn" disabled={busy} onClick={()=>void loadReport(Number(selected),true)}>更新并打印 / 保存 PDF</button>}
      {!printMode&&<Link className="care-btn secondary" href="/robot-care/report/window">查看时间窗口汇总</Link>}
    </div>
    <div className="care-no-print" role="status">{busy?'正在生成本次对话报告…':listing?'正在读取会话…':''}</div>
    <ErrorBox error={error}/>
    {value&&<Report value={value}/>}
  </CareShell>;
}

export function Report({value,audience='self'}:{value:SessionReport;audience?:'self'|'care_team'}){
  const classified=emotions.reduce((sum,[key])=>sum+(value.emotion_counts[key]||0),0);
  const leaders=emotions.filter(([key])=>value.emotion_counts[key]>0 && emotions.every(([other])=>value.emotion_counts[key]>=value.emotion_counts[other]));
  return <article className="care-report report-template session-report" data-testid="report-dto" data-data-nature={value.is_test?'test_only':'non_test_only'}>
    <header className="report-heading"><div><h1>{value.username}的对话报告</h1>
      <p>对话时间 {date(value.started_at)} 至 {date(value.ended_at)}</p></div>
      <div className="report-identity"><p>生成时间 {date(value.generated_at)}</p>{value.is_test&&<p>演示记录</p>}</div>
    </header>
    {value.support_notice&&<section className="care-notice" data-testid="report-support-notice">
      <h2>{audience==='care_team'?'需要优先人工核实与关怀':'给自己多一点支持'}</h2><p>{audience==='care_team'?'本次对话出现需要优先关注的表达，请由关怀人员核实用户当前状况，并按机构既定流程安排支持。':'这次对话里有些感受听起来很难承受。可以先联系一位信任的人，请对方陪你一起寻求专业支持。如果你此刻担心自己可能受伤，请联系当地紧急服务，或请身边的人陪你去急诊。'}</p>
    </section>}
    <section><h2>本次评分与采集覆盖率</h2>
      {value.scores.length?value.scores.map(s=>{
        const coverage=Math.round(100*s.answered/s.required);
        return <div className="scale-summary-card session-score" key={`${s.scale_id}-${s.source}`}>
          <h3>{s.name}</h3><p><strong>{s.score} / {s.answered_max} 分</strong> · {s.answered===s.required?'本次对话辅助合计':'本次已答条目小计'}</p>
          <p>采集覆盖率 <strong>{coverage}%</strong>（{s.answered}/{s.required} 项，完整满分 {s.full_max} 分）</p>
          <progress aria-label={s.name+'采集覆盖率'} max={s.required} value={s.answered}/>
        </div>;
      }):<p>采集覆盖率 <strong>0%</strong>。本次没有可计分条目，可先查看下方的对话总结。</p>}
      <p className="care-meta">覆盖率＝本次已确认条目数 ÷ 对应量表总条目数。它表示本次采集了多少信息，分数仅汇总已确认的回答。</p>
    </section>
    <section><h2>本次对话的情绪表达</h2>
      <p>{classified ? leaders.length===1?`已分类的表达中，${leaders[0][1]}表达最多。`:'已分类的表达中，有多种类别并列。':'这次先以整体对话总结为参考。'}</p>
      {classified>0&&<p>{emotions.map(([key,label])=>`${label} ${value.emotion_counts[key]||0} 条`).join(' · ')}（共 {classified} 条已分类表达）</p>}
      {!!Object.keys(value.frequencies).length&&<p>频率用词 {Object.entries(value.frequencies).map(([word,count])=>`${word} ${count} 次`).join(' · ')}</p>}
    </section>
    <section className="report-overview"><h2>对话总结与分析</h2><p>{value.summary}</p></section>
    <section className="report-next"><h2>{audience==='care_team'?'关怀参考建议':'接下来可以尝试'}</h2><ul>{value.suggestions.map((text,index)=><li key={index}>{text}</li>)}</ul></section>
    <section className="report-limits"><h2>关于这份报告</h2>
      <p>本报告回顾{audience==='care_team'?'该用户本次':'你这次'}对话中的表达，共 {value.user_turns} 条用户发言。短对话能提供初步线索，更充分的交流能为回顾提供更多信息。报告供{audience==='care_team'?'关怀团队':'个人'}参考，不构成医学判断。</p>
      {audience==='self'&&<><h3>可选外部自评</h3>
      <p>可以按自己想了解的方向选填。外部自评结果由相应网站提供。</p>
      <ul className="report-self-assessment">
        {selfAssessments.map(([topic,title,url])=><li key={url}>{topic} <a href={url} target="_blank" rel="noreferrer">{title}</a>
          <span className="report-resource-url">{url}</span></li>)}
      </ul></>}
    </section>
  </article>;
}
