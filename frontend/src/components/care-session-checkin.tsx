'use client';

import {useEffect,useState} from 'react';
import type {FormEvent} from 'react';
import type {SessionScore} from '@/lib/care-types';
import {insights} from '@/lib/care-api';
import {ErrorBox} from './care-shell';

type Answers = Record<string,number>;
interface Checkin {
  available: boolean;
  recall_date: string;
  has_voice_score: boolean;
  questions: {key:string;scale_id:string;text:string}[];
  options: string[];
  answers: Answers;
  scores: SessionScore[];
}

export default function SessionCheckin({sessionId,onSaved}:{
  sessionId:number;
  onSaved?:(scores:SessionScore[])=>void;
}){
  const [checkin,setCheckin]=useState<Checkin|null>(null);
  const [answers,setAnswers]=useState<Answers>({});
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState<unknown>(null);
  const [saved,setSaved]=useState(false);
  const route=`reports/session/${sessionId}/check-in`;

  useEffect(()=>{
    const request=new AbortController();
    insights<Checkin>(route,{signal:request.signal}).then(value=>{
      if(!request.signal.aborted){setCheckin(value);setAnswers(value.answers);}
    }).catch(err=>{if(!request.signal.aborted)setError(err);});
    return ()=>request.abort();
  },[route]);

  async function save(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    setSaving(true);setSaved(false);setError(null);
    try{
      const value=await insights<Checkin>(route,{method:'PUT',body:JSON.stringify(answers)});
      setCheckin(value);setAnswers(value.answers);setSaved(true);onSaved?.(value.scores);
    }catch(err){setError(err);}
    finally{setSaving(false);}
  }

  if(!checkin?.available || (checkin.has_voice_score && !checkin.scores.length)){
    return <ErrorBox error={error}/>;
  }
  const recallDate=new Date(checkin.recall_date).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai'});
  const changed=checkin.questions.some(q=>answers[q.key]!==checkin.answers[q.key]);
  return <section className="care-card care-no-print" data-testid="session-checkin">
    <h2>给本次对话补答近况</h2>
    <p>自愿选答任意一项。以本次对话日期（{recallDate}）为准，回顾此前两周出现以下情况的频率。回答只保存到本次对话。</p>
    <form onSubmit={save}>
      <div className="session-checkin-questions">
        {checkin.questions.map(q=><label key={q.key}>
          <span>{q.text}（{q.scale_id}）</span>
          <select value={answers[q.key] ?? ''} disabled={saving} onChange={event=>{
            const value=event.target.value;
            setSaved(false);
            setAnswers(previous=>{
              const next={...previous};
              if(value==='')delete next[q.key];else next[q.key]=Number(value);
              return next;
            });
          }}>
            <option value="">跳过此项</option>
            {checkin.options.map((label,index)=><option value={index} key={label}>{label}</option>)}
          </select>
        </label>)}
      </div>
      <div className="care-actions"><button className="care-btn secondary" disabled={saving||!changed||!Object.keys(answers).length}>保存本次自评</button></div>
    </form>
    <ErrorBox error={error}/>
    <div role="status">{saved&&<p>本次自评已保存。</p>}
      {checkin.scores.map(s=><p key={s.scale_id}>{s.scale_id} 已答 1/{s.required} 项 · 自评小计 {s.score}/{s.answered_max} 分</p>)}
    </div>
  </section>;
}
