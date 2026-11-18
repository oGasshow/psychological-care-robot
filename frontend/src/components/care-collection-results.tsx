'use client';
import type {CollectionResult} from '@/lib/care-types';
import Link from 'next/link';
import {date,list} from '@/lib/care-api';

const stages:Record<string,string>={not_recorded:'本次采集进度待自动核对',companionship:'自然陪伴，未进入采集',checking_in:'历史关注任务待继续，先了解此刻感受',waiting_context:'等待适合继续了解的时机',collecting:'信息采集中',paused:'已暂停',declined:'用户已停止',reviewing:'正在梳理本次对话',urgent:'安全优先，停止量表信息采集',complete:'采集已完成，待核实'};
const reviews:Record<string,string>={
  pending:'等待完整文字保存后自动核对',
  reviewed:'已核对；缺少的内容会在后续对话继续了解',
  complete:'本次采集任务信息已齐',
  paused:'尊重暂停或停止，未继续采集',
  needs_revalidation:'原话已变化，需要重新核实',
};

export default function CollectionResults({items,demoMode=false}:{items:CollectionResult[];demoMode?:boolean}){
  return <section className="care-card" data-testid="conversation-collection-results">
    <h2>每次对话的量表结果</h2>
    <p>{demoMode?'按实际确认的回答展示三项自定义指标。':'查看语音对话中已确认的量表回答和小计。'}</p>
    {!items.length&&<p className="care-empty">暂无语音会话。</p>}
    {items.map(item=>{
      const scores=list(item.current_session_scores);
      const isDemo=demoMode||item.demo_mode;
      const demoScales=isDemo?list(item.scales):[];
      const canOpenReport=!isDemo&&item.is_closed&&item.stage!=='urgent';
      return <article className="care-message" key={item.recording_session_id} data-testid={`collection-${item.recording_session_id}`}>
        <p><Link href={`/robot-care/sessions/${item.recording_session_id}`}>{date(item.started_at)}</Link>
          {item.is_test&&<span className="care-badge test">测试环境会话</span>}</p>
        {scores.map(s=><p key={s.scale_id}><strong>{s.scale_id} · 本次对话采集</strong>　已确认 {s.answered}/{s.required} 项 · {s.answered===s.required?'合计':'小计'} <strong>{s.score}/{s.answered_max} 分</strong></p>)}
        <p>{item.demo_mode&&<span className="care-badge test">快速演示 · 3项自定义指标</span>}
          {item.trigger_origin==='manual_demo'&&<span className="care-badge">人工触发演示</span>}
          <strong>{stages[item.stage]||'采集状态待核实'}</strong>{item.detector_status==='unavailable'&&' · 上下文判断服务暂不可用'}</p>
        {!!list(item.history_session_ids).length&&<p className="care-meta">本次关联会话 {list(item.history_session_ids).join('、')}{item.history_danger_unresolved?' · 历史安全关注仍需核实':''}</p>}
        {list(item.observations).map((o,i)=><p className="care-meta" key={i}>{o.display_name||o.scale} 第{o.item}项 · {o.status==='awaiting_confirmation'?'等待核对回答':'仍需明确回顾范围或频率'}</p>)}
        {item.saved_answer_review&&<p className="care-meta">保存后自动核对 · {reviews[item.saved_answer_review.state]||'等待核对'}</p>}
        {item.snapshot_kind==='recovered_task_snapshot'&&<p className="care-meta">以下展示关联任务恢复后的累计结果。</p>}
        {item.snapshot_kind==='reconciled_session'&&<p className="care-meta">已从本次保存的语音问答核对条目。</p>}
        {item.source_status==='needs_revalidation'&&<p className="care-notice">对话原话需要重新核实，核实后显示分数。</p>}
        {demoScales.filter(s=>!scores.some(score=>score.scale_id===s.scale)).map(s=><p key={s.scale}><strong>{s.display_name||s.scale}</strong>　已确认 {s.answered}/{s.required} 项 · {
          s.total!=null?`辅助合计 ${s.total}/${s.max_score} 分`:
            s.partial_score!=null?`已答小计 ${s.partial_score}/${s.partial_max} 分`:'等待确认有效回答'
        }</p>)}
        {!scores.length&&!demoScales.length&&<p className="care-meta">本次暂无已确认的回答。{item.stage==='declined'?'账号的自动采集已停止。':''}</p>}
        {canOpenReport&&<Link className="care-btn secondary" href={`/robot-care/report?session=${item.recording_session_id}`}>查看本次报告</Link>}
      </article>;
    })}
  </section>;
}
