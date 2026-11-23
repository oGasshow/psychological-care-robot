'use client';
import {useCallback,useEffect,useState} from 'react';
import Link from 'next/link';
import {api,date} from '@/lib/care-api';
import {ErrorBox} from './care-shell';
interface Alert {user_id:number;username:string;session_id:number;occurred_at:string;is_complete:boolean;source_hash:string;contact_name:string|null;contact_phone:string|null;contact_available:boolean}
export default function SafetyAlerts({isTest=false}:{isTest?:boolean}){
  const [items,setItems]=useState<Alert[]>([]),[count,setCount]=useState(0),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false);
  const load=useCallback(async(signal?:AbortSignal)=>{try{const value=await api<{items:Alert[];pending_count:number}>(`care-management/safety-alerts?is_test=${isTest}&limit=30`,{signal});if(signal?.aborted)return;setItems(value.items);setCount(value.pending_count);setError(null);}catch(e){if(!signal?.aborted)setError(e);}},[isTest]);
  useEffect(()=>{const request=new AbortController();const initial=setTimeout(()=>void load(request.signal),0);const interval=setInterval(()=>{if(!document.hidden)void load(request.signal);},30000);return()=>{clearTimeout(initial);clearInterval(interval);request.abort();};},[load]);
  async function acknowledge(item:Alert){setBusy(true);try{await api(`care-management/safety-alerts/${item.session_id}/acknowledge`,{method:'POST',body:JSON.stringify({source_hash:item.source_hash})});await load();}catch(e){setError(e);}finally{setBusy(false);}}
  return <section className="care-card care-no-print" data-testid="safety-alerts"><div className="care-actions"><h2>待联系提醒（{count}）{isTest?' · 测试记录':''}</h2><button className="care-btn secondary" disabled={busy} onClick={()=>void load()}>刷新提醒</button></div><ErrorBox error={error}/>
    {!items.length&&!error&&<p>当前暂无待人工联系提醒。页面每 30 秒检查一次已保存记录。</p>}
    {items.map(item=><div className="care-notice care-warning" key={item.session_id}><strong>{item.username} · 需要优先人工核实</strong><p>{date(item.occurred_at)}{item.is_complete?'':' · 对话尚未结束'}</p>
      <p>紧急联系人：{item.contact_name||'尚未补全'} {item.contact_phone&&<a href={'tel:'+item.contact_phone}>{item.contact_phone}</a>}</p><p>请核实当前状况并人工联系；系统未自动发送短信或拨打电话。</p>
      <div className="care-actions"><Link className="care-btn secondary" href={`/care-admin/users/${item.user_id}${isTest?'?test=1':''}`}>查看用户报告</Link><button className="care-btn" disabled={busy} onClick={()=>void acknowledge(item)}>确认已人工跟进</button></div></div>)}
  </section>;
}
