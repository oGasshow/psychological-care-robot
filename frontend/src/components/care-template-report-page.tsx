'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import {api,ApiError,date,insights} from '@/lib/care-api';
import type {Page,SessionRecord} from '@/lib/care-types';
import CareShell,{ErrorBox} from './care-shell';
import {Report,type TemplateReport,type ReportPeriod} from './care-report-template';
export default function SessionReportPage({printMode=false}:{printMode?:boolean}){
  const [sessions,setSessions]=useState<SessionRecord[]>([]),[cursor,setCursor]=useState<string|null>(null);
  const [value,setValue]=useState<TemplateReport|null>(null),[selected,setSelected]=useState('');
  const [period,setPeriod]=useState<ReportPeriod>('session'),[busy,setBusy]=useState(false),[listing,setListing]=useState(true);
  const [error,setError]=useState<unknown>(null);const active=useRef<AbortController|null>(null);
  const loadReport=useCallback(async(sid:number,range:ReportPeriod='session',print=false)=>{
    active.current?.abort();const request=new AbortController();active.current=request;setBusy(true);setError(null);setValue(null);
    try{const report=await insights<TemplateReport>(`reports/template/${sid}?period=${range}`,{signal:request.signal});
      if(request.signal.aborted)return;setValue(report);
      if(print){await document.fonts.ready;await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));if(!request.signal.aborted)window.print();}
    }catch(cause){if(!request.signal.aborted)setError(cause instanceof ApiError&&cause.code==='report_session_incomplete'?new Error('请等对话结束并保存完整后再生成报告。'):cause);}finally{if(!request.signal.aborted)setBusy(false);}
  },[]);
  const loadList=useCallback(async(next?:string)=>{setListing(true);
    try{const page=await api<Page<SessionRecord>>('robot-records/sessions?limit=50'+(next?'&cursor='+encodeURIComponent(next):''));setSessions(old=>[...(next?old:[]),...page.items.filter(s=>s.is_complete)]);setCursor(page.next_cursor);}
    catch(cause){setError(cause);}finally{setListing(false);}
  },[]);
  useEffect(()=>{const timer=setTimeout(()=>{const query=new URLSearchParams(window.location.search),sid=query.get('session'),scope=query.get('period');const range:ReportPeriod=scope==='week'||scope==='three_days'?scope:'session';setPeriod(range);
    if(sid&&/^[1-9]\d*$/.test(sid)&&Number.isSafeInteger(Number(sid))){setSelected(sid);void loadReport(Number(sid),range);}void loadList();},0);return()=>{clearTimeout(timer);active.current?.abort();};},[loadList,loadReport]);
  function choose(sid:string,range:ReportPeriod){setSelected(sid);setPeriod(range);const url=new URL(window.location.href);url.searchParams.set('period',range);
    if(sid){url.searchParams.set('session',sid);void loadReport(Number(sid),range);}else{url.searchParams.delete('session');active.current?.abort();setValue(null);setBusy(false);}window.history.replaceState(null,'',url);}
  return <CareShell title="用户评估报告" subtitle="选择报告范围，查看并打印或保存 PDF。"><div className="care-actions care-no-print">
    <label htmlFor="report-session">选择对话</label><select id="report-session" value={selected} onChange={e=>choose(e.target.value,period)}><option value="">请选择已结束的对话</option>{selected&&!sessions.some(s=>String(s.recording_session_id)===selected)&&<option value={selected}>已选择的会话</option>}{sessions.map(s=><option key={s.recording_session_id} value={s.recording_session_id}>{date(s.started_at)}{s.is_test?'（演示记录）':''}</option>)}</select>
    <label htmlFor="report-period">报告范围</label><select id="report-period" value={period} onChange={e=>choose(selected,e.target.value as ReportPeriod)}><option value="session">本次对话</option><option value="three_days">近三天</option><option value="week">近七天</option></select>
    {cursor&&<button className="care-btn secondary" disabled={listing} onClick={()=>void loadList(cursor)}>更多对话</button>}{selected&&!printMode&&<button className="care-btn secondary" disabled={busy} onClick={()=>void loadReport(Number(selected),period)}>刷新报告</button>}{value&&<button className="care-btn" disabled={busy} onClick={()=>void loadReport(Number(selected),period,true)}>更新并打印 / 保存 PDF</button>}</div>
    <p className="care-meta care-no-print">近三天／近七天分别回看 72／168 小时，按会话开始时间纳入完整记录，每段会话一个情绪点。演示与非测试记录分开。</p>{(busy||listing)&&<p className="care-no-print" role="status">{busy?'正在生成报告…':'正在读取会话…'}</p>}<ErrorBox error={error}/>{value&&<Report value={value}/>}{!listing&&!sessions.length&&<p>暂无已结束且记录完整的对话。</p>}
  </CareShell>;
}
