'use client';
import { useEffect,useState } from 'react';
import CareShell,{ErrorBox} from '@/components/care-shell';
import {Assessments} from '@/components/care-results';
import {Data,insights,label,list} from '@/lib/care-api';
export default function AssessmentPage(){
  const [data,setData]=useState<Data|null>(null),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false);
  async function load(){setBusy(true);setError(null);try{setData(await insights('assessments'));}catch(e){setError(e);}finally{setBusy(false);}}
  useEffect(()=>{void load();},[]);
  return <CareShell title="量表结果，只读展示" subtitle="沿用服务端配置的来源；不复制题库、不重新计分、不替历史记录补写版本或完成时间。"><div className="care-actions"><button className="care-btn secondary" disabled={busy} onClick={load}>刷新量表结果</button>{busy&&<span role="status">正在读取…</span>}</div><ErrorBox error={error}/>{data&&<><div className="care-notice">来源状态：{label(data.status || data.provider_status)} · {label(data.provider || data.source_kind)}{data.reason_code&&` · ${data.reason_code}`}</div><Assessments items={list(data.items)}/></>}</CareShell>;
}
