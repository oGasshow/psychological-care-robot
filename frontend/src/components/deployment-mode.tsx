'use client';
import {useEffect,useState} from 'react';
import type {DeploymentMode} from '@/lib/care-types';

export default function DeploymentModeNotice(){
  const [mode,setMode]=useState<DeploymentMode|null>(null);
  useEffect(()=>{let active=true;void fetch('/api/robot-voice/mode',{cache:'no-store'}).then(async response=>{
    if(!response.ok)return;
    const value:DeploymentMode=await response.json();
    if(active&&['normal','demo','unavailable'].includes(value.mode))setMode(value);
  }).catch(()=>{});return()=>{active=false;};},[]);
  if(!mode)return null;
  return <aside data-testid="deployment-mode" data-mode={mode.mode} style={{padding:'12px 16px',marginBlock:16,borderRadius:10,border:`1px solid ${mode.demo_mode?'#c68e28':'#769f92'}`,background:mode.demo_mode?'#fff7e6':'#edf5f1',color:'#173f40'}}><strong>{mode.name}</strong><p style={{margin:'4px 0 0'}}>{mode.description}</p>{mode.demo_mode&&<p style={{margin:'4px 0 0'}}>演示结果单独保存，不是完整 PHQ-9／GAD-7 总分。</p>}</aside>;
}
