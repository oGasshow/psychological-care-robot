'use client';
import {DataNatureBadge} from '@/components/care-results';
import {Data,date,list} from '@/lib/care-api';

export default function DangerNotice({data}:{data:Data}){const sources=list(data?.sources);if(!sources.length)return null;return <section className="care-danger" data-testid="report-danger-alert" aria-label="明确危险表达提示"><div className="care-danger-heading"><strong>重要风险提示：对话中出现明确危险表达</strong><p>请优先安排人工关注与核实</p></div><p>本次范围内有 <strong>{sources.length}</strong> 条当前有效用户对话触发明确危险表达规则。</p><p>{data.action}</p><ol>{sources.map((s,i)=><li className="care-danger-source" key={i}><p><strong>对话依据 #{s.record_id}</strong> · 会话 #{s.recording_session_id} · 修订 {s.input_revision} · {date(s.occurred_at)} <DataNatureBadge isTest={s.is_test}/></p>{list(s.expressions).map((v,j)=><blockquote key={j}>{String(v)}</blockquote>)}</li>)}</ol><p className="care-meta">仅依据当前有效稿中的明确表达，需要人工核实，不作临床风险等级判断。</p></section>;}
