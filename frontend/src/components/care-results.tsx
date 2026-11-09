'use client';

import { Data, date, label, list } from '@/lib/care-api';
import { assistantDisplayText } from '@/lib/display-text';

export type DataNature = 'test_only' | 'non_test_only' | 'mixed' | 'empty' | 'unconfirmed';
export function reportDataNature(data: Data): DataNature {
  return ['test_only', 'non_test_only', 'mixed', 'empty'].includes(data.data_nature)
    ? data.data_nature as DataNature : 'unconfirmed';
}
export function dataNatureText(nature: DataNature): string {
  return {
    test_only: '模拟数据演示',
    non_test_only: '非测试标志数据',
    mixed: '混合来源：测试与非测试分流',
    empty: '当前范围无纳入来源',
    unconfirmed: '数据性质待确认',
  }[nature];
}
export function dataNatureDescription(nature: DataNature): string {
  return {
    test_only: '本报告纳入的来源均带测试标志（is_test=true），按模拟数据展示；不作为真实评估。',
    non_test_only: '纳入来源均带非测试标志（is_test=false）。该标志不等于真实来源、量表有效性或内容审核已经通过。',
    mixed: '本范围同时纳入测试标志与非测试标志来源。下方按属性分流展示；测试数据不充当非测试历史，非测试标志也不等于真实来源已验证。',
    empty: '当前范围没有纳入对话或量表来源，不将空范围称为全模拟报告。',
    unconfirmed: '来源未提供完整的数据性质元信息，请重新读取并核对；不据单个布尔字段推断全部来源属性。',
  }[nature];
}
export function DataNatureBadge({ isTest }: { isTest: unknown }) {
  return <span className={`care-badge ${isTest === true ? 'test' : isTest === false ? 'non-test' : ''}`} data-source-is-test={isTest === true ? 'true' : isTest === false ? 'false' : 'unknown'}>{isTest === true ? '模拟数据演示' : isTest === false ? '非测试标志（非真实性验证）' : '测试属性未确认'}</span>;
}

export function Assessments({ items, empty = '暂无量表记录；未补为 0 分。' }: { items: Data[]; empty?: string }) {
  return <>{!items.length && <p className="care-empty">{empty}</p>}{items.map((a, i) => <article className="care-card" key={a.source_record_id || i}>
    <h3>{a.display_name || a.scale_name}</h3><DataNatureBadge isTest={a.is_test}/><span className="care-badge">{label(a.verification_status)}</span><span className="care-badge">{label(a.applicability_status)}</span>
    <p><strong>{a.total_score === null || a.total_score === undefined ? '分数未确认' : `${a.total_score} 分`}</strong> · 范围 {a.score_min ?? '未确认'}—{a.score_max ?? '未确认'}</p>
    <p className="care-meta">完成时间：{date(a.completed_at)} · 时间来源 {a.time_source || a.completed_at_source || '未确认'}<br/>来源 {a.source_record_id} · {label(a.source_kind)} · 量表版本 {a.scale_version || '未确认'}<br/>计分版本 {a.scoring_version || '未确认'} · 解释版本 {a.interpretation_version || '未确认'}<br/>内容审核 {a.content_review_status || '未确认'} · 审核依据 {typeof a.review_reference === 'object' ? JSON.stringify(a.review_reference) : a.review_reference || '未提供'}</p>
    {a.verification_status?.startsWith('verified_') && a.reference_interpretation && <p className="care-text">参考解释：{assistantDisplayText(String(a.reference_interpretation))}</p>}
    {a.verification_status?.startsWith('verified_') && (a.reference_advice || a.suggestions) && <p className="care-text">参考建议：{assistantDisplayText(String(a.reference_advice || a.suggestions))}</p>}
    {(a.reason_code || a.verification_reason || a.verification_reasons) && <p className="care-notice care-warning">{[a.reason_code, a.verification_reason, ...(Array.isArray(a.verification_reasons) ? a.verification_reasons : [])].filter(Boolean).join('；')}</p>}
  </article>)}</>;
}

// The API separates data nature. Repeat the split in the view so even a malformed
// group cannot use one test point plus one non-test point to meet the threshold.
function separateNature(groups: Data[]): Data[] {
  return groups.flatMap(group => {
    const partitions = new Map<unknown, Data[]>();
    for (const point of list(group.points)) {
      const nature = typeof point.is_test === 'boolean' ? point.is_test : undefined;
      const points = partitions.get(nature) || [];
      points.push({ ...point, is_test: nature });
      partitions.set(nature, points);
    }
    if (!partitions.size) partitions.set(typeof group.is_test === 'boolean' ? group.is_test : undefined, []);
    return [...partitions].map(([is_test, points]) => ({ ...group, is_test, points }));
  });
}

function independentPoints(group: Data, assessment = false): Data[] {
  const points = new Map<string | number, Data>();
  for (const point of list(group.points)) {
    const id = assessment ? point.source_record_id : point.record_id || point.target_record_id;
    if ((typeof id === 'string' && id) || typeof id === 'number') points.set(id, point);
  }
  return [...points.values()];
}

export function Trends({ data }: { data: Data }) {
  const emotions = separateNature(list(data.emotion_groups)), assessments = separateNature(list(data.assessment_groups));
  return <>
    <section className="care-card"><h2>情绪类别时间线</h2><p className="care-meta">只取当前输入版本、成功分类的独立用户记录。按引擎、配置及测试属性分流；每个分流至少 2 条独立记录，不将测试与非测试各 1 条拼成趋势。不换算临床总分，不自动判断改善或恶化。</p>
      {!emotions.length && <p className="care-empty">独立有效记录不足，暂无类别时间线。</p>}
      {emotions.map((g, i) => { const points = independentPoints(g); return <div className="care-trend-group" key={i} data-testid="emotion-trend-group" data-is-test={g.is_test === true ? 'true' : g.is_test === false ? 'false' : 'unknown'} data-independent-count={points.length}>
        <h3>{g.engine_kind} / {g.engine_version} / {g.config_version}</h3><DataNatureBadge isTest={g.is_test}/>
        {typeof g.is_test !== 'boolean' ? <p className="care-notice care-warning">来源测试属性未确认，暂不绘制时间变化。</p> : points.length < 2 ? <p className="care-notice care-warning">本分流独立有效记录不足 2 条，暂不绘制时间变化。{g.reason_code || ''}</p> : <ol className="care-timeline">{points.map((p, j) => <li key={j}><time>{date(p.occurred_at)}</time><span className={`care-badge ${p.emotion_label}`}>{label(p.emotion_label)}</span><span className="care-meta">来源记录 #{p.record_id || p.target_record_id} · revision {p.input_revision}</span><DataNatureBadge isTest={p.is_test}/></li>)}</ol>}
      </div>; })}
    </section>
    <section className="care-card"><h2>量表分数时间变化</h2><p className="care-meta">同一来源、量表、记录级版本及测试属性分别展示；每个分流至少 2 条独立有效结果。不同量表不合并为“心理总分”，测试结果不补入非测试历史。</p>
      {!assessments.length && <p className="care-empty">暂无满足条件的量表趋势。</p>}
      {assessments.map((g, i) => { const points = independentPoints(g, true); return <div className="care-trend-group" key={i} data-testid="assessment-trend-group" data-is-test={g.is_test === true ? 'true' : g.is_test === false ? 'false' : 'unknown'} data-independent-count={points.length}>
        <h3>{g.display_name || g.scale_name} · {g.scale_version || '版本未确认'} · {label(g.source_kind)}</h3><DataNatureBadge isTest={g.is_test}/>
        {typeof g.is_test !== 'boolean' ? <p className="care-notice care-warning">来源测试属性未确认，暂不展示时间变化。</p> : points.length < 2 ? <p className="care-notice care-warning">本分流独立有效记录不足 2 条，暂不展示时间变化。{g.reason_code || ''}</p> : <div className="care-table-wrap"><table><thead><tr><th>确认完成时间</th><th>分数 / 范围</th><th>独立来源 / 属性</th></tr></thead><tbody>{points.map((p, j) => <tr key={j}><td>{date(p.completed_at)}</td><td>{p.total_score} / {p.score_min}—{p.score_max}</td><td>{p.source_record_id}<br/><DataNatureBadge isTest={p.is_test}/></td></tr>)}</tbody></table></div>}
      </div>; })}
    </section>
  </>;
}
