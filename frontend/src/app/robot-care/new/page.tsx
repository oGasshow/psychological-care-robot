'use client';

import Link from 'next/link';
import {useEffect,useRef,useState} from 'react';
import {useRouter} from 'next/navigation';
import CareShell,{ErrorBox} from '@/components/care-shell';
import {insights} from '@/lib/care-api';

export default function NewDemoConversation(){
  const router=useRouter();
  const [turns,setTurns]=useState([{user:'',assistant:''}]);
  const [enabled,setEnabled]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<unknown>(null);
  const requestId=useRef<string|null>(null);
  useEffect(()=>{let active=true;insights('profile').then(data=>{if(active)setEnabled(data.demo_entry_enabled===true);}).catch(e=>{if(active)setError(e);});return()=>{active=false;};},[]);
  function change(index:number,field:'user'|'assistant',value:string){setTurns(old=>old.map((turn,i)=>i===index?{...turn,[field]:value}:turn));}
  async function save(){
    setError(null);
    if(turns.some(turn=>!turn.user.trim())){setError(new Error('每轮至少填写一条用户文字。'));return;}
    const messages=turns.flatMap(turn=>[{role:'user',content:turn.user},...(turn.assistant.trim()?[{role:'assistant',content:turn.assistant}]:[])]);
    setBusy(true);
    try{
      requestId.current??=crypto.randomUUID();
      const result=await insights('demo-conversations',{method:'POST',body:JSON.stringify({request_id:requestId.current,messages})});
      router.push(`/robot-care/sessions/${result.recording_session_id}`);
    }catch(e){setError(e);}finally{setBusy(false);}
  }
  return <CareShell title="新增演示对话" subtitle="输入现场演示用文字，保存后可查看记录、分析结果并生成报告。">
    <p className="care-notice">所有新增内容标记为模拟数据。助手文字由你手动填写，可留空；这里不会调用真实模型或播放语音。保存只创建新会话，不改动预置样例。</p>
    <ErrorBox error={error}/>
    {!enabled&&<p className="care-meta">此入口仅在专用本地演示环境开放。</p>}
    {turns.map((turn,index)=><section className="care-card" key={index}><h2>第 {index+1} 轮</h2>
      <label htmlFor={`demo-user-${index}`}>用户文字（必填）</label><textarea id={`demo-user-${index}`} value={turn.user} maxLength={8000} disabled={busy||!enabled} onChange={e=>change(index,'user',e.target.value)}/>
      <label htmlFor={`demo-assistant-${index}`}>助手文字（可选，手动演示）</label><textarea id={`demo-assistant-${index}`} value={turn.assistant} maxLength={8000} disabled={busy||!enabled} onChange={e=>change(index,'assistant',e.target.value)}/>
    </section>)}
    <div className="care-actions"><button className="care-btn secondary" disabled={!enabled||busy||turns.length>=20} onClick={()=>setTurns(old=>[...old,{user:'',assistant:''}])}>添加一轮</button><button className="care-btn" disabled={!enabled||busy} onClick={save}>{busy?'正在保存…':'保存对话并查看分析'}</button><Link className="care-btn secondary" href="/robot-care">返回对话记录</Link></div>
    <p className="care-meta">分析由后台异步完成。保存失败可重试同一请求；已保存的内容不会重复创建。重新汇报启动会恢复固定演示对话，继续上次现场数据请使用 Resume-Project.cmd。</p>
  </CareShell>;
}
