'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import CareShell, { ErrorBox } from '@/components/care-shell';
import { api, Data, date, label, list } from '@/lib/care-api';

export default function HistoryPage() {
  const [items, setItems] = useState<Data[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<unknown>(null);
  async function load(next?: string) {
    setBusy(true); setError(null);
    try {
      const page = await api(`robot-records/sessions?limit=50${next ? `&cursor=${encodeURIComponent(next)}` : ''}`);
      setItems(old => next ? [...old, ...list(page.items)] : list(page.items)); setCursor(page.next_cursor);
    } catch(e) { setError(e); } finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, []);
  return <CareShell title="每一段对话，都有据可循" subtitle="按后台实际保存的记录查看。关闭状态、记录完整性与播放状态分别保留。">
    <div className="care-actions"><button className="care-btn secondary" disabled={busy} onClick={() => load()}>刷新记录</button>{busy && <span role="status">正在读取后台记录…</span>}</div><ErrorBox error={error}/>
    <div className="care-card" data-testid="history-list">{!busy && !items.length && !error && <p className="care-empty">暂无会话记录。请先完成专用演示回放。</p>}{items.map(s => <article className="care-session" key={s.recording_session_id}><div><h2>陪伴会话 #{s.recording_session_id}</h2>{s.is_test && <span className="care-badge test">模拟数据演示</span>}<span className="care-badge">{label(s.state)}</span><span className="care-badge">{s.is_complete ? '记录已收齐' : '记录尚未收齐'}</span><p className="care-meta">原始开始：{date(s.started_at)}<br/>结束：{date(s.ended_at)} · 已保存 {s.received_record_count} 条 / 关闭上界 {s.last_sequence_no ?? '尚未固定'}</p></div><Link className="care-btn" href={`/robot-care/sessions/${s.recording_session_id}`}>查看对话与摘要</Link></article>)}</div>
    {cursor && <button className="care-btn secondary" disabled={busy} onClick={() => load(cursor)}>加载下一页</button>}
  </CareShell>;
}
