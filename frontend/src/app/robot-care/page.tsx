'use client';
import type { Page, SessionRecord } from '@/lib/care-types';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import CareShell, { ErrorBox } from '@/components/care-shell';
import DeleteSessionButton from '@/components/care-delete-session';
import { api, date, label, list } from '@/lib/care-api';

export default function HistoryPage() {
  const [items, setItems] = useState<SessionRecord[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState('');
  async function load(next?: string) {
    setBusy(true); setError(null);
    try {
      const page = await api<Page<SessionRecord>>(`robot-records/sessions?limit=50${next ? `&cursor=${encodeURIComponent(next)}` : ''}`);
      setItems(old => next ? [...old, ...list(page.items)] : list(page.items));
      setCursor(page.next_cursor);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, []);
  function removed(id: number) {
    setItems(current => current.filter(session => session.recording_session_id !== id));
    setNotice('已删除所选对话。');
  }
  return <CareShell title="我的对话" subtitle="每次对话独立保存，随时回来查看。">
    <div className="care-workspace-toolbar">
      <Link className="care-btn" href="/robot-care/voice">＋ 开始新对话</Link>
      <button className="care-btn secondary" disabled={busy} onClick={() => load()}>刷新记录</button>
      {busy && <span role="status">正在读取对话…</span>}
    </div>
    <ErrorBox error={error}/>
    {notice && <p role="status" className="care-notice">{notice}</p>}
    <div className="care-session-grid" data-testid="history-list" aria-label="我的对话列表" aria-busy={busy}>
      {!busy && !items.length && !error && <section className="care-card care-workspace-empty">
        <h2>从第一次对话开始</h2>
        <p>和语音助手聊聊近况，对话结束后会保存在这里。</p>
        <Link className="care-btn" href="/robot-care/voice">开始第一次对话</Link>
      </section>}
      {items.map(s => <article className="care-card care-session-card" key={s.recording_session_id}>
        <div className="care-session-heading"><span className="care-session-icon" aria-hidden="true"><svg width="23" height="23" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M20 11.5a8 8 0 0 1-8 8 9 9 0 0 1-4-.9L4 20l1.4-4a8 8 0 1 1 14.6-4.5Z"/><path d="M8 10h8M8 14h5"/></svg></span><span className="care-badge">{s.state === 'closed' ? '已结束' : label(s.state)}</span></div>
        <h2>对话 · {date(s.started_at).replace('（UTC+8）', '')}</h2>
        <p className="care-meta">会话编号 #{s.recording_session_id}</p>
        <div>{s.is_test && <span className="care-badge test">模拟数据演示</span>}<span className="care-badge">{s.is_complete ? '记录已收齐' : '记录尚未收齐'}</span></div>
        <dl className="care-session-facts"><div><dt>对话记录</dt><dd>{s.received_record_count} 条</dd></div><div><dt>结束时间</dt><dd>{s.ended_at ? date(s.ended_at).replace('（UTC+8）', '') : '尚未结束'}</dd></div></dl>
        <div className="care-actions"><Link className="care-btn secondary" href={`/robot-care/sessions/${s.recording_session_id}`}>查看对话与摘要</Link>{s.state === 'closed' && <DeleteSessionButton id={s.recording_session_id} startedAt={s.started_at} onDeleted={() => removed(s.recording_session_id)}/>}</div>
      </article>)}
    </div>
    {cursor && <button className="care-btn secondary" disabled={busy} onClick={() => load(cursor)}>加载下一页</button>}
  </CareShell>;
}
