'use client';
import {useEffect,useState} from 'react';
import CareShell,{ErrorBox} from '@/components/care-shell';
import {Trends} from '@/components/care-results';
import {Data,insights} from '@/lib/care-api';
export default function TrendsPage(){
  const [data,setData]=useState<Data|null>(null),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false);
  async function load(){setBusy(true);setError(null);try{setData(await insights('trends'));}catch(e){setError(e);}finally{setBusy(false);}}
  useEffect(()=>{const timer=window.setTimeout(()=>{void load();},0);return()=>window.clearTimeout(timer);},[]);
  return <CareShell title="类别与分数，按来源分别观察" subtitle="至少 2 条独立有效记录才展示变化；失败、无法判断和过期结果不凑趋势。"><div className="care-actions"><button className="care-btn secondary" disabled={busy} onClick={load}>刷新趋势</button>{busy&&<span role="status">正在读取…</span>}</div><ErrorBox error={error}/>{data&&<Trends data={data}/>}</CareShell>;
}
