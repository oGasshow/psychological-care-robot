'use client';
import type {SegaStatus,SegaProbe} from '@/lib/care-types';
import {useEffect,useState} from 'react';
import {api} from '@/lib/care-api';
import {ErrorBox} from '@/components/care-shell';

export default function SegaPanel(){
  const [status,setStatus]=useState<SegaStatus|null>(null),[result,setResult]=useState<SegaProbe|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null);
  useEffect(()=>{let active=true;api<SegaStatus>('robot-voice/sega/status').then(v=>{if(active)setStatus(v);}).catch(e=>{if(active)setError(e);});return()=>{active=false;};},[]);
  async function probe(){setBusy(true);setError(null);try{setResult(await api<SegaProbe>('robot-voice/sega/probe',{method:'POST'}));}catch(e){setError(e);}finally{setBusy(false);}}
  return <details className="care-card" data-testid="sega-panel"><summary>SEGA 图模型 · 实验分析</summary><p>{status?.message||'正在读取模型状态…'}</p><p>作者模型需要匹配的问答文本、对齐音频及辅助特征；原有纯文字会话不能补回音频。缺少输入时不生成模型判断，也不把它当作“没有问题”。</p><p>有完整特征的实验分析可建立待进一步了解任务，仍需结合当前交流；模型类别不等于量表分数或诊断。</p>{status?.probe_allowed&&status?.installed&&<button className="care-btn secondary" disabled={busy} onClick={probe}>{busy?'正在运行作者模型…':'运行作者特征样例（非本人数据）'}</button>}<ErrorBox error={error}/>{result&&<p data-testid="sega-probe-result">{result.status==='succeeded'?'作者权重已完成真实推理，运行设备：'+result.device+'。此结果仅用于核验接入，没有写成本账号的量表结果。':'本次模型核验未完成，请检查隔离运行环境。'}</p>}</details>;
}
