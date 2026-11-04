'use client';

import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import CareShell, { ErrorBox } from '@/components/care-shell';
import { api, Data, date, insights, label, list, playbackLabel } from '@/lib/care-api';

function Correction({ message, onSaved }: { message: Data; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [effective, setEffective] = useState<Data | null>(null);
  const [content, setContent] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function read() {
    setBusy(true); setError(null);
    try { const data = await insights(`messages/${message.record_id}/effective`); setEffective(data); setContent(data.effective_content); setOpen(true); } catch(e) { setError(e); } finally { setBusy(false); }
  }
  async function save() {
    if (!effective || !content.trim()) return;
    setBusy(true); setError(null);
    try {
      await insights(`messages/${message.record_id}/corrections`, { method:'POST', body:JSON.stringify({ request_id:`web_${crypto.randomUUID()}`, base_revision:effective.input_revision, content }) });
      await read(); onSaved();
    } catch(e) { setError(e); } finally { setBusy(false); }
  }
  return <><button className="care-btn secondary" disabled={busy} onClick={read}>查看有效稿 / 更正转录</button><ErrorBox error={error}/>{open && effective && <div className="care-correction"><h3>原始转录 / 更正稿</h3><p className="care-meta">原记录 #{message.record_id} · 当前输入 revision {effective.input_revision} · 更正时间 {date(effective.corrected_at)}</p><p>原始转录（保持不变）</p><div className="care-text" data-testid={`original-${message.record_id}`}>{effective.original_content}</div><p>生效更正稿</p><div className="care-text" data-testid={`effective-${message.record_id}`}>{effective.effective_content}</div><label htmlFor={`correction-${message.record_id}`}>新的更正文字</label><textarea id={`correction-${message.record_id}`} value={content} maxLength={8000} onChange={e => setContent(e.target.value)}/><p className="care-meta">提交将递增输入版本，使旧分析及策略过期，并排入新的分析任务。</p><div className="care-actions"><button className="care-btn" disabled={busy || !content.trim()} onClick={save}>提交更正</button><button className="care-btn secondary" onClick={() => setOpen(false)}>收起</button></div></div>}</>;
}

export default function SessionPage() {
  const router = useRouter();
  const { id } = useParams<{id:string}>();
  const [items,setItems] = useState<Data[]>([]);
  const [summary,setSummary] = useState<Data | null>(null);
  const [analyses,setAnalyses] = useState<Data[]>([]);
  const [excluded,setExcluded] = useState<Data[]>([]);
  const [cursor,setCursor] = useState<string | null>(null);
  const [analysisCursor,setAnalysisCursor] = useState<string | null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState<unknown>(null);
  async function load(next?:string) {
    setBusy(true); setError(null);
    try {
      const [page,s,a] = await Promise.all([api(`robot-records/sessions/${id}/messages?limit=50${next ? `&cursor=${encodeURIComponent(next)}` : ''}`), insights(`sessions/${id}/summary`), insights(`sessions/${id}/analyses?limit=50`)]);
      setItems(old => next ? [...old,...list(page.items)] : list(page.items)); setCursor(page.next_cursor); setSummary(s); setAnalyses(list(a.items)); setExcluded(list(a.excluded_records)); setAnalysisCursor(a.next_cursor);
    } catch(e) { setError(e); } finally {setBusy(false);}
  }
  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, [id]);
  async function moreAnalyses() {
    if (!analysisCursor) return;
    setBusy(true); setError(null);
    try {const a=await insights(`sessions/${id}/analyses?limit=50&cursor=${encodeURIComponent(analysisCursor)}`); setAnalyses(old=>[...old,...list(a.items)]); setAnalysisCursor(a.next_cursor);} catch(e){setError(e);} finally{setBusy(false);}
  }
  async function analyze(recordId:number) {
    setBusy(true); setError(null);
    try {await insights('analysis-jobs',{method:'POST',body:JSON.stringify({record_id:recordId})}); await load();} catch(e) {setError(e);} finally {setBusy(false);}
  }
  return <CareShell title={`陪伴会话 #${id}`} subtitle="发生时间与分析时间分别呈现；播放中断或未知不代表完整听到。">
    <div className="care-actions"><Link className="care-btn secondary" href="/robot-care">返回历史</Link><button className="care-btn secondary" disabled={busy} onClick={()=>load()}>刷新记录与分析</button><button className="care-btn" onClick={()=>{sessionStorage.setItem('care-report-scope',JSON.stringify({session_ids:[Number(id)]})); router.push('/robot-care/report');}}>生成本会话报告</button>{busy && <span role="status">正在读取…</span>}</div><ErrorBox error={error}/>
    {summary && <section className="care-card" data-testid="session-summary"><h2>会话摘要</h2><span className="care-badge">{label(summary.state)}</span><span className="care-badge">{summary.is_complete ? '记录已收齐' : '尚未收齐，摘要不完整'}</span><div className="care-grid">{['positive','neutral','negative'].map(k=><div className="care-stat" key={k}>{label(k)}用户记录<strong>{summary.emotion_counts?.[k] ?? 0}</strong></div>)}</div><p>独立状态：{Object.entries(summary.analysis_counts || {}).map(([k,v])=><span className="care-badge" key={k}>{label(k)} {String(v)}</span>)}</p><p className="care-meta">数据截至 {date(summary.data_as_of)}。计数只取当前输入版本的有效分类，不将未知或失败补为中性。</p></section>}
    <section className="care-card"><h2>原始对话记录</h2>{items.map(m=><article className="care-message" key={m.record_id} data-testid={`message-${m.record_id}`}><header><strong>#{m.sequence_no} · {m.role === 'user' ? '用户' : '陪伴回复'}</strong><span className="care-badge">{label(m.text_status)}</span><span className="care-badge">{playbackLabel(m.playback_status)}</span>{m.is_test && <span className="care-badge test">模拟数据演示</span>}</header><p className="care-meta">原始发生：{date(m.occurred_at)} · 记录 ID {m.record_id} · 轮次 {m.turn_id || '未提供'}</p><div className="care-text">{m.content || '（空文本）'}</div>{m.role==='user' && m.text_status==='completed' && <><Correction message={m} onSaved={()=>load()}/><button style={{marginLeft:12}} className="care-btn secondary" disabled={busy} onClick={()=>analyze(m.record_id)}>触发 / 查询分析任务</button></>}</article>)}{!items.length&&!busy&&<p className="care-empty">暂无已保存记录。</p>}{cursor&&<div className="care-actions"><button className="care-btn secondary" disabled={busy} onClick={()=>load(cursor)}>加载下一页对话</button></div>}</section>
    <section className="care-card"><h2>分析结果与来源版本</h2><div className="care-table-wrap"><table><thead><tr><th>来源记录 / revision</th><th>状态 / 情绪</th><th>规则与配置</th><th>安全信号 / 策略</th></tr></thead><tbody>{analyses.map((entry,i)=>{const a=entry.result||entry; return <tr key={entry.task_id || entry.job_id || i}><td>#{entry.target_record_id || a.target_record_id}<br/>revision {entry.input_revision ?? a.input_revision}<br/><span className="care-meta">分析于 {date(a.analyzed_at)}</span></td><td><span className="care-badge">{label(entry.status || a.classification_status)}</span>{a.emotion_label && <span className={`care-badge ${a.emotion_label}`}>{label(a.emotion_label)}</span>}{a.classification_status==='unable_to_determine'&&<span>无法判断</span>}{(a.is_current===false || entry.is_current===false)&&<p>已过期，不计统计</p>}<p className="care-meta">{a.reason_code || entry.error_code || ''}</p></td><td>{a.engine_kind || entry.engine_kind} / {a.engine_version || entry.engine_version}<br/>{a.config_version || entry.config_version}<p className="care-meta">规则：{list(a.matched_rule_ids).length ? a.matched_rule_ids.join(', ') : '无 / 未分析'}</p></td><td>{label(a.safety_signal)}{a.support_policy_id && <Policy policyId={a.support_policy_id}/>}</td></tr>;})}</tbody></table></div>{!analyses.length&&<p className="care-empty">尚无分析任务；等待 worker 扫描或手动触发。</p>}{analysisCursor&&<button className="care-btn secondary" disabled={busy} onClick={moreAnalyses}>加载下一页分析</button>}{excluded.length>0&&<details><summary>排除记录与原因（{excluded.length}）</summary>{excluded.map((e,i)=><p key={i}>记录 #{e.record_id || e.target_record_id}：{e.reason_code || e.exclusion_reason}</p>)}</details>}</section>
  </CareShell>;
}

function Policy({policyId}:{policyId:number}) {
  const [policy,setPolicy]=useState<Data|null>(null); const [error,setError]=useState<unknown>(null); const [receipt,setReceipt]=useState<Data|null>(null);
  async function read(){try{setPolicy(await insights(`policies/${policyId}`));}catch(e){setError(e);}}
  async function simulate(){try{setReceipt(await insights('strategy-deliveries/simulate',{method:'POST',body:JSON.stringify({policy_id:policyId,request_id:`web_${crypto.randomUUID()}`})}));}catch(e){setError(e);}}
  return <><p><button className="care-btn secondary" onClick={read}>查看策略 #{policyId}</button></p><ErrorBox error={error}/>{policy&&<><p className="care-text">{policy.content || policy.text || policy.support_text || policy.response_text}</p><p className="care-meta">模板 {policy.template_version} · {policy.policy_kind} · 审核 {policy.review_state} · 真实接收未连接</p>{policy.simulator_enabled && <button className="care-btn secondary" onClick={simulate}>交本地模拟器核对</button>}</>}{receipt&&<p>{label(receipt.delivery_status)} · consumer_kind={receipt.consumer_kind} · 真实生效未连接</p>}</>;
}
