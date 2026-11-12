'use client';
import { useEffect,useState } from 'react';
import CareShell,{ErrorBox} from '@/components/care-shell';
import {Assessments} from '@/components/care-results';
import CollectionResults from '@/components/care-collection-results';
import {Data,insights,label,list} from '@/lib/care-api';
export default function AssessmentPage(){
  const [data,setData]=useState<Data|null>(null),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false);
  async function load(){setBusy(true);setError(null);try{setData(await insights('assessments'));}catch(e){setError(e);}finally{setBusy(false);}}
  useEffect(()=>{const timer=window.setTimeout(()=>{void load();},0);return()=>window.clearTimeout(timer);},[]);
  return <CareShell title="量表与对话采集结果" subtitle="查看语音会话中的已确认信息和采集进度；历史量表按原来源单独展示。"><div className="care-actions"><button className="care-btn secondary" disabled={busy} onClick={load}>刷新采集与量表结果</button>{busy&&<span role="status">正在读取…</span>}</div><ErrorBox error={error}/>{data&&<><CollectionResults items={list(data.conversation_collections)}/>{data.provider==='fixture'?<details className="care-card" data-testid="fixture-assessments"><summary>模拟量表数据（仅用于演示）</summary><p>以下不是本次对话采集的结果。</p><Assessments items={list(data.items)}/></details>:<section className="care-card"><h2>历史量表来源</h2><p>来源状态：{label(data.status || data.provider_status)} · {label(data.provider || data.source_kind)}</p><Assessments items={list(data.items)}/></section>}</>}</CareShell>;
}
