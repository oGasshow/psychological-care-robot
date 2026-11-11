'use client';

import Link from 'next/link';
import {useCallback,useEffect,useRef,useState} from 'react';
import CareShell,{ErrorBox} from '@/components/care-shell';
import {api,Data,date} from '@/lib/care-api';

type Line={message_id:string;role:string;text:string;final:boolean;interrupted?:boolean;occurred_at?:string};
const names:Record<string,string>={idle:'准备就绪',connecting:'正在连接',listening:'正在倾听',muted:'收音已暂停',playing:'助手正在回复',interrupted:'已打断，继续倾听',ending:'正在结束并保存',ended:'本次对话已结束',error:'连接需要处理'};

export default function CareVoice(){
  const [config,setConfig]=useState<Data|null>(null),[state,setState]=useState('idle'),[error,setError]=useState<unknown>(null);
  const [lines,setLines]=useState<Line[]>([]),[level,setLevel]=useState(0),[muted,setMuted]=useState(false);
  const [recording,setRecording]=useState<Data|null>(null),[notice,setNotice]=useState('点击开始后，浏览器会请求麦克风权限。');
  const [guided,setGuided]=useState(false),[screening,setScreening]=useState<Data|null>(null);
  const socket=useRef<WebSocket|null>(null),context=useRef<AudioContext|null>(null),media=useRef<MediaStream|null>(null);
  const capture=useRef<AudioWorkletNode|null>(null),ready=useRef(false),micMuted=useRef(false),stopping=useRef(false);
  const nodes=useRef(new Map<AudioBufferSourceNode,string>()),audioDone=useRef(new Set<string>()),blocked=useRef(new Set<string>());
  const nextAudio=useRef(0),lastMeter=useRef(0),currentAudio=useRef('');

  function send(value:Data){if(socket.current?.readyState===WebSocket.OPEN)socket.current.send(JSON.stringify(value));}
  const clearPlayback=useCallback(()=>{
    for(const [node,id] of nodes.current){blocked.current.add(id);node.onended=null;try{node.stop();}catch{/* Already ended. */}}
    nodes.current.clear();nextAudio.current=0;
    if(currentAudio.current)blocked.current.add(currentAudio.current);
  },[]);
  const releaseAudio=useCallback(()=>{
    ready.current=false;media.current?.getTracks().forEach(t=>t.stop());media.current=null;
    capture.current?.disconnect();capture.current=null;clearPlayback();
    if(context.current){void context.current.close().catch(()=>{});context.current=null;}
  },[clearPlayback]);
  useEffect(()=>{let active=true;api('robot-voice/config').then(v=>{if(active)setConfig(v);}).catch(e=>{if(active)setError(e);});return()=>{active=false;socket.current?.close();releaseAudio();};},[releaseAudio]);
  function interrupt(){clearPlayback();send({type:'interrupt'});setState('interrupted');setNotice('旧回复已停止，可以继续说。');}
  function finish(){
    stopping.current=true;ready.current=false;media.current?.getTracks().forEach(t=>t.stop());clearPlayback();setLevel(0);setState('ending');
    setNotice('正在结束语音并保存最终文字，请稍候。');send({type:'finish'});
  }
  function playAudio(event:Data){
    const ctx=context.current,id=String(event.message_id||'');if(!ctx||blocked.current.has(id)||stopping.current)return;
    const binary=atob(event.audio);if(binary.length%2)throw Error('返回音频格式不正确。');
    const pcm=new DataView(Uint8Array.from(binary,c=>c.charCodeAt(0)).buffer),buffer=ctx.createBuffer(1,binary.length/2,24000);
    const samples=buffer.getChannelData(0);for(let i=0;i<samples.length;i++)samples[i]=pcm.getInt16(i*2,true)/32768;
    const begin=Math.max(ctx.currentTime+.025,nextAudio.current);
    if(begin-ctx.currentTime>30){interrupt();setNotice('回复较长，已停止播放。可以继续提问。');return;}
    const node=ctx.createBufferSource();node.buffer=buffer;node.connect(ctx.destination);nodes.current.set(node,id);currentAudio.current=id;
    node.onended=()=>{nodes.current.delete(node);if(![...nodes.current.values()].includes(id)&&audioDone.current.has(id)){send({type:'playback',state:'completed',message_id:id});if(!stopping.current)setState(micMuted.current?'muted':'listening');}};
    node.start(begin);nextAudio.current=begin+buffer.duration;setState('playing');send({type:'playback',state:'playing',message_id:id});
  }
  function receive(event:Data){
    if(event.type==='screening.status'){setScreening(event);return;}
    if(event.type==='screening.result_failed'){setError(new Error(event.message));return;}
    if(event.type==='session.ready'){ready.current=true;send({type:'unmute'});setState('listening');setNotice('已连接，可以直接说话；说话时插话可打断助手。');}
    else if(event.type==='transcript.delta'||event.type==='transcript.final'){
      setLines(old=>{const line={...event,final:event.type==='transcript.final'} as Line;const index=old.findIndex(v=>v.message_id===line.message_id);return index<0?[...old,line]:old.map((v,i)=>i===index?line:v);});
    }else if(event.type==='audio.delta')playAudio(event);
    else if(event.type==='audio.done'){audioDone.current.add(event.message_id);if(![...nodes.current.values()].includes(event.message_id))send({type:'playback',state:'completed',message_id:event.message_id});}
    else if(event.type==='playback.clear'){clearPlayback();if(!stopping.current)setState(micMuted.current?'muted':'listening');}
    else if(event.type==='records.saved'){setRecording(event);setNotice('本次文字记录已保存，可查看历史和报告。');}
    else if(event.type==='records.pending'){setRecording(event);setNotice('文字记录待保存，可在结束后点击重试保存。');}
    else if(event.type==='records.error'){setRecording(event);setError(new Error(event.message));setNotice('保存状态需要处理，请保留当前页面的文字。');}
    else if(event.type==='status'){setNotice(event.message||'');}
    else if(event.type==='error'){setError(new Error(event.message||'语音连接异常，请稍后重试。'));setState('error');ready.current=false;media.current?.getTracks().forEach(t=>t.stop());}
  }
  async function start(){
    setScreening(null);
    socket.current?.close();socket.current=null;
    releaseAudio();setError(null);setLines([]);setRecording(null);setMuted(false);micMuted.current=false;stopping.current=false;
    blocked.current.clear();audioDone.current.clear();currentAudio.current='';setState('connecting');setNotice('正在准备麦克风和语音连接…');
    try{
      if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia)throw Error('当前页面无法使用麦克风，请使用本机 localhost 页面或 HTTPS。');
      const token=localStorage.getItem('access_token');if(!token)throw Error('请先登录再开始语音。');
      const ctx=new AudioContext({latencyHint:'interactive'});context.current=ctx;await ctx.resume();
      const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});media.current=stream;
      await ctx.audioWorklet.addModule('/audio/pcm-capture.js');
      const node=new AudioWorkletNode(ctx,'pcm-capture',{numberOfInputs:1,numberOfOutputs:1,channelCount:1});capture.current=node;
      const source=ctx.createMediaStreamSource(stream),silent=ctx.createGain();silent.gain.value=0;source.connect(node);node.connect(silent);silent.connect(ctx.destination);
      const ws=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/api/robot-voice/live`);socket.current=ws;
      ws.onopen=()=>ws.send(JSON.stringify({type:'authenticate',token,device_id:'windows_browser',guided_screening:guided}));
      ws.onmessage=e=>{if(socket.current!==ws)return;try{receive(JSON.parse(e.data));}catch{setError(new Error('收到的语音数据无法处理，请重新开始。'));finish();}};
      ws.onerror=()=>{if(socket.current!==ws)return;setError(new Error('语音连接未能建立，请检查服务状态后重试。'));setState('error');releaseAudio();};
      ws.onclose=()=>{if(socket.current!==ws)return;socket.current=null;releaseAudio();setLevel(0);setState(old=>old==='error'?'error':'ended');};
      node.port.onmessage=e=>{if(!ready.current||micMuted.current)return;if(Date.now()-lastMeter.current>100){lastMeter.current=Date.now();setLevel(Math.min(100,e.data.level*500));}if(ws.readyState===WebSocket.OPEN){if(ws.bufferedAmount>128000){setError(new Error('网络发送拥堵，本次收音已停止。'));finish();return;}ws.send(e.data.pcm);}};
    }catch(e){releaseAudio();setState('error');setError(e instanceof Error?e:new Error('无法打开麦克风。'));}
  }
  function toggleMute(){const next=!micMuted.current;micMuted.current=next;setMuted(next);media.current?.getAudioTracks().forEach(t=>{t.enabled=!next;});send({type:next?'mute':'unmute'});setState(next?'muted':'listening');if(next)setLevel(0);}
  async function retrySave(){try{const result=await api('robot-voice/retry-records',{method:'POST'});setNotice(result.pending?'仍有文字等待保存，请稍后重试。':'待保存记录已处理，可在历史中查看。');}catch(e){setError(e);}}
  const connected=['listening','muted','playing','interrupted'].includes(state),canStart=['idle','ended','error'].includes(state);
  return <CareShell title="和陪伴助手聊一聊" subtitle="直接说话即可交流，实时文字会显示在这里。">
    {canStart&&<p><label><input type="checkbox" checked={guided} onChange={e=>setGuided(e.target.checked)}/> 允许在我愿意时邀请我回顾最近两周的感受（PHQ-9 / GAD-7 辅助采集，可随时停止）</label></p>}
    {screening&&['paused','declined','urgent'].includes(screening.stage)&&<p role="status">{screening.stage==='urgent'?'先照顾当下感受，相关信息采集已暂停。':'已暂停相关信息整理，可以继续随意聊聊。'}</p>}
    {guided&&connected&&<button className="care-btn secondary" onClick={()=>send({type:'screening.action',action:'decline'})}>停止相关信息整理</button>}
    <div className="voice-layout"><section className="care-card voice-console"><div className={`voice-orb ${connected?'active':''}`} aria-hidden="true">声</div><h2>{names[state]||state}</h2><p className="voice-notice" role="status">{notice}</p><div className="voice-meter" aria-label="麦克风输入强度"><span style={{width:`${level}%`}}/></div><p className="care-meta">麦克风输入 · 建议使用耳机，减少回声</p><div className="voice-controls">{canStart?<button className="care-btn" disabled={!config?.enabled} onClick={start}>开始语音对话</button>:<><button className="care-btn secondary" disabled={!connected} onClick={toggleMute}>{muted?'继续收音':'暂停收音'}</button><button className="care-btn secondary" disabled={!connected} onClick={interrupt}>打断回复</button><button className="care-btn" disabled={!connected} onClick={finish}>结束并保存</button></>}</div>{config&&!config.enabled&&<p className="care-notice">{config.message}</p>}<ErrorBox error={error}/><p className="care-meta">{config?.is_test?'当前为联调测试，文字记录带测试标记。':'当前记录带非测试标记；不代表已完成真实性或专业核验。'}</p></section>
    <section className="care-card voice-transcripts"><div className="voice-transcript-heading"><h2>正在聊的内容</h2><span className="care-badge">实时字幕</span></div>{!lines.length&&<div className="voice-empty">开始后，您说的话和助手回复会依次显示。<br/>语音对话中可以随时暂停收音或打断回复。</div>}<div aria-live="polite" aria-relevant="additions text" className="voice-lines">{lines.map(line=><article className={`voice-line ${line.role}`} key={line.message_id} data-testid={`voice-line-${line.message_id}`}><header><strong>{line.role==='user'?'您':'陪伴助手'}</strong><span>{line.interrupted?'已打断':line.final?'最终文字':'识别 / 回复中'}</span></header><p>{line.text}</p>{line.occurred_at&&<time>{date(line.occurred_at)}</time>}</article>)}</div></section></div>
    <section className="care-card voice-record-status"><h2>本次记录</h2><p>{recording?.type==='records.saved'?'双方最终文字已保存到历史。':connected?'已确认的最终文字写入持久队列，结束会话后上传到历史。':'结束后可查看本次文字记录与报告。'}</p><div className="care-actions">{recording?.recording_session_id&&<><Link className="care-btn secondary" href={`/robot-care/sessions/${recording.recording_session_id}`}>查看本次记录</Link><Link className="care-btn" href="/robot-care/report" onClick={()=>sessionStorage.setItem('care-report-scope',JSON.stringify({session_ids:[recording.recording_session_id]}))}>生成本次回顾</Link></>}<button className="care-btn secondary" disabled={!canStart} onClick={retrySave}>重试待保存记录</button></div></section>
  </CareShell>;
}
