'use client';
import type {Page,SessionRecord} from '@/lib/care-types';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import CareShell, { ErrorBox } from '@/components/care-shell';
import { api, date, label, list } from '@/lib/care-api';

const scenarioNames:Record<string,string>={presentation_1:'日常积极对话',presentation_2:'孤独与担忧对话',presentation_3:'明确危险表达示例'};

export default function HistoryPage() {
  const [items, setItems] = useState<SessionRecord[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [demoEntry,setDemoEntry]=useState(false);
  async function load(next?: string) {
    setBusy(true); setError(null);
    try {
      const [page,profile] = await Promise.all([api<Page<SessionRecord>>(`robot-records/sessions?limit=50${next ? `&cursor=${encodeURIComponent(next)}` : ''}`),api('robot-insights/profile')]);
      setDemoEntry(profile.demo_entry_enabled===true);
      setItems(old => next ? [...old, ...list(page.items)] : list(page.items)); setCursor(page.next_cursor);
    } catch(e) { setError(e); } finally { setBusy(false); }
  }
  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, []);
  return <CareShell title="每一段对话，都有据可循" subtitle="按后台实际保存的记录查看。关闭状态、记录完整性与播放状态分别保留。">
    <div className="care-actions">{demoEntry&&<Link className="care-btn" href="/robot-care/new">新增演示对话</Link>}<button className="care-btn secondary" disabled={busy} onClick={() => load()}>刷新记录</button>{busy && <span role="status">正在读取后台记录…</span>}</div><ErrorBox error={error}/>
    <div className="care-card" data-testid="history-list">{!busy && !items.length && !error && <p className="care-empty">暂无会话记录。可从“新增演示对话”录入现场文字。</p>}{items.map(s => <article className="care-session" key={s.recording_session_id}><div><h2>{scenarioNames[s.external_session_id]||(s.device_id==='manual_text_demo'?'现场新增对话':'陪伴会话')} #{s.recording_session_id}</h2>{s.is_test && <span className="care-badge test">模拟数据演示</span>}<span className="care-badge">{label(s.state)}</span><span className="care-badge">{s.is_complete ? '记录已收齐' : '记录尚未收齐'}</span><p className="care-meta">原始开始：{date(s.started_at)}<br/>结束：{date(s.ended_at)} · 已保存 {s.received_record_count} 条 / 关闭上界 {s.last_sequence_no ?? '尚未固定'}</p></div><Link className="care-btn" href={`/robot-care/sessions/${s.recording_session_id}`}>查看对话与摘要</Link></article>)}</div>
    {cursor && <button className="care-btn secondary" disabled={busy} onClick={() => load(cursor)}>加载下一页</button>}
  </CareShell>;
}
