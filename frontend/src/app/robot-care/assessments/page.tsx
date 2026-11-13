'use client';
import { useEffect,useState } from 'react';
import CareShell,{ErrorBox} from '@/components/care-shell';
import {Assessments} from '@/components/care-results';
import CollectionResults from '@/components/care-collection-results';
import SegaPanel from '@/components/care-sega';
import {Data,insights,label,list} from '@/lib/care-api';
export default function AssessmentPage(){
  const [data,setData]=useState<Data|null>(null),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false);
  async function load(){setBusy(true);setError(null);try{setData(await insights('assessments'));}catch(e){setError(e);}finally{setBusy(false);}}
  useEffect(()=>{const timer=window.setTimeout(()=>{void load();},0);return()=>window.clearTimeout(timer);},[]);
  return <CareShell title="量表与对话采集结果" subtitle="查看 PHQ-9／GAD-7 对话辅助结果、六类自定义指标及采集进度；历史标准量表按原来源单独展示。"><div className="care-actions"><button className="care-btn secondary" disabled={busy} onClick={load}>刷新采集与指标结果</button>{busy&&<span role="status">正在读取…</span>}</div><ErrorBox error={error}/>{data&&<>{data.collection_plan?.needs_collection&&<section className="care-notice" data-testid="persistent-collection-plan"><h2>待完成的信息采集任务</h2><p>任务会随本人账号保留到后续通话，采齐后才自动切回自然陪伴。当前状态：{data.collection_plan.status==='checking_in'||data.collection_plan.status==='urgent'?'安全关注优先，先了解当前感受':data.collection_plan.status==='declined'?'尊重停止，不继续追问':'等待适宜时机继续采集'}</p>{list(data.collection_plan.scales).map(s=><p key={s.scale}>{s.display_name||s.scale}：已确认 {s.answered}/{s.required} 项</p>)}</section>}<CollectionResults items={list(data.conversation_collections)}/><SegaPanel/>{data.provider==='fixture'?<details className="care-card" data-testid="fixture-assessments"><summary>模拟量表数据（仅用于演示）</summary><p>以下不是本次对话采集的结果。</p><Assessments items={list(data.items)}/></details>:<section className="care-card"><h2>历史量表来源</h2><p>来源状态：{label(data.status || data.provider_status)} · {label(data.provider || data.source_kind)}</p><Assessments items={list(data.items)}/></section>}</>}</CareShell>;
}
