'use client';

import { useState } from 'react';
import { ErrorBox } from '@/components/care-shell';
import { api, date } from '@/lib/care-api';

export default function DeleteSessionButton({ id, startedAt, onDeleted }: {
  id: number | string;
  startedAt?: string;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function remove() {
    const target = startedAt ? `${date(startedAt)}开始的对话` : '当前对话';
    if (!window.confirm(`确定删除${target}吗？转录及对应的分析和报告将无法查看。此操作无法撤回。`)) return;
    setBusy(true);
    setError(null);
    try {
      await api(`robot-records/sessions/${id}`, { method: 'DELETE' });
      onDeleted();
    } catch (failure) {
      setError(failure);
      setBusy(false);
    }
  }

  return <div>
    <button type="button" className="care-btn delete" disabled={busy} onClick={remove}>
      {busy ? '正在删除…' : '删除对话'}
    </button>
    <ErrorBox error={error}/>
  </div>;
}
