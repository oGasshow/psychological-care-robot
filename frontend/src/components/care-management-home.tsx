'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import Link from 'next/link';
import {api,date} from '@/lib/care-api';
import type {Page} from '@/lib/care-types';
import type {ManagedUser} from '@/lib/care-management';
import ManagementShell from './care-management-shell';
import {ErrorBox} from './care-shell';

export default function ManagementHome(){
  const [search,setSearch]=useState('');
  const [term,setTerm]=useState('');
  const [isTest,setIsTest]=useState(false);
  const [items,setItems]=useState<ManagedUser[]>([]);
  const [cursor,setCursor]=useState<string|null>(null);
  const [busy,setBusy]=useState(true);
  const [error,setError]=useState<unknown>(null);
  const [updated,setUpdated]=useState<string|null>(null);
  const request=useRef<AbortController|null>(null);
  const load=useCallback(async(next?:string)=>{
    request.current?.abort();const current=new AbortController();request.current=current;
    setBusy(true);setError(null);
    try{
      const query=new URLSearchParams({q:term,is_test:String(isTest),limit:'20'});
      if(next)query.set('cursor',next);
      const value=await api<Page<ManagedUser>>(`care-management/users?${query}`,{signal:current.signal});
      if(current.signal.aborted)return;
      setItems(previous=>next?[...previous,...value.items]:value.items);setCursor(value.next_cursor);setUpdated(new Date().toISOString());
    }catch(cause){if(!current.signal.aborted)setError(cause);}finally{if(!current.signal.aborted)setBusy(false);}
  },[term,isTest]);
  useEffect(()=>{
    const initial=window.setTimeout(()=>void load(),0);
    const poll=window.setInterval(()=>{if(!document.hidden)void load();},60000);
    return()=>{clearTimeout(initial);clearInterval(poll);request.current?.abort();};
  },[load]);
  function clear(){request.current?.abort();setBusy(true);setItems([]);setCursor(null);setUpdated(null);}
  return <ManagementShell title="用户报告" subtitle="选择用户，查看其已生成的报告。">
    <form className="management-filters care-card care-no-print" onSubmit={event=>{event.preventDefault();clear();if(search.trim()===term)void load();else setTerm(search.trim());}}>
      <div><label htmlFor="management-search">查找用户</label><input id="management-search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="输入账号名称" maxLength={50}/></div>
      <div><label htmlFor="management-scope">记录范围</label><select id="management-scope" value={String(isTest)} onChange={e=>{clear();setIsTest(e.target.value==='true');}}><option value="false">业务记录</option><option value="true">测试记录</option></select></div>
      <button className="care-btn" type="submit" disabled={busy}>搜索</button><button className="care-btn secondary" type="button" disabled={busy} onClick={()=>void load()}>刷新报告</button>
    </form>
    <div className="management-list-heading"><h2>用户列表</h2><p className="care-meta" role="status">{busy?'正在读取…':updated?`更新于 ${date(updated)} · 每分钟自动刷新`:''}</p></div>
    {isTest&&<p className="care-notice">当前查看测试报告。</p>}
    <ErrorBox error={error}/>
    <div className="management-users" data-testid="management-users" aria-busy={busy}>
      {!busy&&!items.length&&!error&&<section className="care-card care-workspace-empty"><h2>暂无匹配用户</h2><p>可以调整搜索条件；新用户注册后会出现在这里。</p></section>}
      {items.map(user=><article className="care-card management-user-card" key={user.user_id}>
        <div className="management-user-title"><div><h2>{user.username}</h2><p className="care-meta">用户 #{user.user_id}{!user.is_active?' · 账号已停用':''}</p></div></div>
        <p className="management-report-count">可查看报告 <strong>{user.report_count}</strong> 份</p>
        <p className="care-meta">最近报告：{user.latest_at?date(user.latest_at):'暂无报告'}</p>
        <div className="care-actions"><Link className="care-btn" href={`/care-admin/users/${user.user_id}?test=${isTest?'1':'0'}`}>查看报告</Link>{isTest&&<span className="care-badge test">测试报告</span>}</div>
      </article>)}
    </div>
    {cursor&&<button className="care-btn secondary" disabled={busy} onClick={()=>void load(cursor)}>加载更多用户</button>}
  </ManagementShell>;
}
