'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import Link from 'next/link';
import {api,ApiError,date} from '@/lib/care-api';
import type {Page,SessionRecord} from '@/lib/care-types';
import type {ManagedUser} from '@/lib/care-management';
import ManagementShell from './care-management-shell';
import {ErrorBox} from './care-shell';
import {Report,type SessionReport} from './care-session-report';

export default function ManagementUser({userId,isTest}:{userId:number;isTest:boolean}){
  const [user,setUser]=useState<ManagedUser|null>(null);
  const [sessions,setSessions]=useState<SessionRecord[]>([]);
  const [cursor,setCursor]=useState<string|null>(null);
  const [busy,setBusy]=useState(true);
  const [error,setError]=useState<unknown>(null);
  const [report,setReport]=useState<SessionReport|null>(null);
  const [selected,setSelected]=useState<number|null>(null);
  const [reportBusy,setReportBusy]=useState(false);
  const [reportError,setReportError]=useState<unknown>(null);
  const reportRequest=useRef<AbortController|null>(null);
  const loadReport=useCallback(async(sid:number,print=false)=>{
    reportRequest.current?.abort();const request=new AbortController();reportRequest.current=request;
    setReportBusy(true);setReport(null);setReportError(null);setSelected(sid);
    try{
      const value=await api<{report:SessionReport;user_id:number}>(`care-management/reports/${sid}`,{signal:request.signal});
      if(value.user_id!==userId)throw new Error('报告不属于当前选中的用户。');
      if(request.signal.aborted)return;
      setReport(value.report);
      if(print){await document.fonts.ready;await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));if(!request.signal.aborted)window.print();}
    }catch(cause){if(!request.signal.aborted)setReportError(cause instanceof ApiError&&cause.code==='report_session_incomplete'?new Error('这段对话的记录尚未收齐，请稍后刷新。'):cause);}
    finally{if(!request.signal.aborted)setReportBusy(false);}
  },[userId]);
  useEffect(()=>{
    const request=new AbortController();
    const timer=window.setTimeout(async()=>{
      try{
        const [person,page]=await Promise.all([api<ManagedUser>(`care-management/users/${userId}?is_test=${isTest}`,{signal:request.signal}),api<Page<SessionRecord>>(`care-management/users/${userId}/sessions?is_test=${isTest}&limit=20`,{signal:request.signal})]);
        if(request.signal.aborted)return;
        setUser(person);setSessions(page.items);setCursor(page.next_cursor);
        const latest=page.items.find(row=>row.is_complete);if(latest)void loadReport(latest.recording_session_id);
      }catch(cause){if(!request.signal.aborted)setError(cause);}finally{if(!request.signal.aborted)setBusy(false);}
    },0);
    return()=>{clearTimeout(timer);request.abort();reportRequest.current?.abort();};
  },[userId,isTest,loadReport]);
  async function more(){
    if(!cursor)return;setBusy(true);
    try{const page=await api<Page<SessionRecord>>(`care-management/users/${userId}/sessions?is_test=${isTest}&limit=20&cursor=${encodeURIComponent(cursor)}`);setSessions(old=>[...old,...page.items]);setCursor(page.next_cursor);}catch(cause){setError(cause);}finally{setBusy(false);}
  }
  return <ManagementShell title={user?`${user.username} · 用户报告`:'用户报告'} subtitle={isTest?'当前查看该用户的测试记录。':'查看该用户的历史报告。'}>
    <div className="care-actions care-no-print"><Link className="care-btn secondary" href="/care-admin">返回用户列表</Link>{selected&&<button className="care-btn secondary" disabled={reportBusy} onClick={()=>void loadReport(selected)}>刷新本次报告</button>}{report&&selected&&<button className="care-btn" disabled={reportBusy} onClick={()=>void loadReport(selected,true)}>更新并打印 / 保存 PDF</button>}</div>
    <ErrorBox error={error}/>
    {busy&&!user&&<p role="status">正在读取用户资料…</p>}
    {user&&<section className="care-card care-no-print"><h2>历史报告</h2>{!sessions.length&&<p>该用户在当前范围内暂无报告。</p>}<div className="management-session-list">{sessions.map(session=><button key={session.recording_session_id} className={`management-session-option ${selected===session.recording_session_id?'selected':''}`} disabled={!session.is_complete} onClick={()=>void loadReport(session.recording_session_id)}><strong>{date(session.started_at)}</strong><span>报告对应会话 #{session.recording_session_id} · {session.is_complete?'查看报告':'等待记录收齐'}</span></button>)}</div>{cursor&&<button className="care-btn secondary" disabled={busy} onClick={()=>void more()}>更多报告</button>}</section>}
    {reportBusy&&<p role="status" className="care-no-print">正在读取本次对话报告…</p>}<ErrorBox error={reportError}/>
    {report&&<Report value={report} audience="care_team"/>}
  </ManagementShell>;
}
