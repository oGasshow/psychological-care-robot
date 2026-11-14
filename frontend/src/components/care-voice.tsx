'use client';
import type {VoiceConfig,RecordingReceipt,VoiceDiagnostics,ScreeningStatus,VoiceEvent,AudioDelta} from '@/lib/care-types';

import Link from 'next/link';
import {useCallback,useEffect,useRef,useState} from 'react';
import CareShell,{ErrorBox} from '@/components/care-shell';
import {api,Data,date} from '@/lib/care-api';

type Line={message_id:string;role:string;text:string;final:boolean;interrupted?:boolean;occurred_at?:string};
const names:Record<string,string>={idle:'准备就绪',connecting:'正在连接',listening:'正在倾听',muted:'收音已暂停',playing:'助手正在回复',interrupted:'已打断，继续倾听',ending:'正在结束并保存',ended:'本次对话已结束',error:'连接需要处理'};
const screeningLabels:Record<string,string>={companionship:'先倾听与交流',waiting_context:'正在留意合适时机',checking_in:'先关心你此刻的感受',reviewing:'正在梳理刚才的对话',collecting:'结合对话继续梳理',complete:'这一部分已经聊完',paused:'已暂停',declined:'已停止',urgent:'安全关怀优先'};
const screeningErrors:Record<string,string>={context_detector_timeout:'后台判断超时，暂未开始梳理；可以继续聊，之后会再试。',context_detector_authentication_failed:'后台判断服务认证失败，暂未开始梳理。',context_detector_transport_unavailable:'后台判断服务暂时连不上，暂未开始梳理；可以继续聊，之后会再试。',context_detector_provider_error:'后台判断服务返回错误，暂未开始梳理；可以继续聊，之后会再试。',context_detector_invalid_output:'后台判断结果未通过核验，暂未开始梳理；可以继续聊，之后会再试。'};

export default function CareVoice(){
  const [config,setConfig]=useState<VoiceConfig|null>(null),[state,setState]=useState('idle'),[error,setError]=useState<unknown>(null);
  const [lines,setLines]=useState<Line[]>([]),[level,setLevel]=useState(0),[muted,setMuted]=useState(false);
  const [recording,setRecording]=useState<RecordingReceipt|null>(null),[notice,setNotice]=useState('点击开始后，浏览器会请求麦克风权限。');
  const [debug,setDebug]=useState<VoiceDiagnostics|null>(null);
  const [screening,setScreening]=useState<ScreeningStatus|null>(null);
  const [stalled,setStalled]=useState(false);
  const socket=useRef<WebSocket|null>(null),context=useRef<AudioContext|null>(null),media=useRef<MediaStream|null>(null);
  const capture=useRef<AudioWorkletNode|null>(null),ready=useRef(false),micMuted=useRef(false),stopping=useRef(false);
  const nodes=useRef(new Map<AudioBufferSourceNode,string>()),audioDone=useRef(new Set<string>()),blocked=useRef(new Set<string>());
  const nextAudio=useRef(0),lastMeter=useRef(0),currentAudio=useRef('');
  const replyWait=useRef(0),watchdog=useRef<ReturnType<typeof setInterval>|null>(null),reconnecting=useRef(false);
  const finishAfterPlayback=useRef(false);
  const speech=useRef({active:false,lastVoice:0,started:0});

  function send(value:Data){if(socket.current?.readyState===WebSocket.OPEN)socket.current.send(JSON.stringify(value));}
  const clearPlayback=useCallback(()=>{
    for(const [node,id] of nodes.current){blocked.current.add(id);node.onended=null;try{node.stop();}catch{/* Already ended. */}}
    nodes.current.clear();nextAudio.current=0;
    if(currentAudio.current)blocked.current.add(currentAudio.current);
  },[]);
  const releaseAudio=useCallback(()=>{
    if(watchdog.current){clearInterval(watchdog.current);watchdog.current=null;}
    ready.current=false;media.current?.getTracks().forEach(t=>t.stop());media.current=null;
    capture.current?.disconnect();capture.current=null;clearPlayback();
    if(context.current){void context.current.close().catch(()=>{});context.current=null;}
  },[clearPlayback]);
  useEffect(()=>{let active=true;api<VoiceConfig>('robot-voice/config').then(v=>{if(active)setConfig(v);}).catch(e=>{if(active)setError(e);});return()=>{active=false;socket.current?.close();releaseAudio();};},[releaseAudio]);
  function interrupt(){clearPlayback();send({type:'interrupt'});setState('interrupted');setNotice('旧回复已停止，可以继续说。');}
  function finish(){
    stopping.current=true;ready.current=false;media.current?.getTracks().forEach(t=>t.stop());clearPlayback();setLevel(0);setState('ending');
    setNotice('正在结束语音并保存最终文字，请稍候。');send({type:'finish'});
  }
  function playAudio(event:AudioDelta){
    const ctx=context.current,id=String(event.message_id||'');if(!ctx||blocked.current.has(id)||stopping.current)return;
    const binary=atob(event.audio);if(binary.length%2)throw Error('返回音频格式不正确。');
    const pcm=new DataView(Uint8Array.from(binary,c=>c.charCodeAt(0)).buffer),buffer=ctx.createBuffer(1,binary.length/2,24000);
    const samples=buffer.getChannelData(0);for(let i=0;i<samples.length;i++)samples[i]=pcm.getInt16(i*2,true)/32768;
    const begin=Math.max(ctx.currentTime+.025,nextAudio.current);
    if(begin-ctx.currentTime>30){interrupt();setNotice('回复较长，已停止播放。可以继续提问。');return;}
    const node=ctx.createBufferSource();node.buffer=buffer;node.connect(ctx.destination);nodes.current.set(node,id);currentAudio.current=id;
    node.onended=()=>{nodes.current.delete(node);if(![...nodes.current.values()].includes(id)&&audioDone.current.has(id)){send({type:'playback',state:'completed',message_id:id});if(!stopping.current)setState(micMuted.current?'muted':'listening');}if(finishAfterPlayback.current&&nodes.current.size===0){finishAfterPlayback.current=false;finish();}};
    node.start(begin);nextAudio.current=begin+buffer.duration;setState('playing');send({type:'playback',state:'playing',message_id:id});
  }
  function receive(event:VoiceEvent){
    if(event.type==='screening.result_failed'){setError(new Error(event.message));return;}
    if(event.type==='dialogue.finished'){if(nodes.current.size>0)finishAfterPlayback.current=true;else finish();return;}
    if(event.type==='session.ready'){ready.current=true;send({type:'unmute'});setState('listening');setNotice('已连接，可以直接说话；说话时插话可打断助手。');}
    else if(event.type==='transcript.delta'||event.type==='transcript.final'){
      if(event.role==='user'&&event.type==='transcript.final'){speech.current.active=false;replyWait.current=Date.now();setStalled(false);}
      if(event.role==='assistant'){replyWait.current=0;setStalled(false);}
      setLines(old=>{const line={...event,final:event.type==='transcript.final'} as Line;const index=old.findIndex(v=>v.message_id===line.message_id);return index<0?[...old,line]:old.map((v,i)=>i===index?line:v);});
    }else if(event.type==='audio.delta'){replyWait.current=0;setStalled(false);playAudio(event);}
    else if(event.type==='audio.done'){audioDone.current.add(event.message_id);if(![...nodes.current.values()].includes(event.message_id))send({type:'playback',state:'completed',message_id:event.message_id});}
    else if(event.type==='playback.clear'){finishAfterPlayback.current=false;clearPlayback();if(!stopping.current)setState(micMuted.current?'muted':'listening');}
    else if(event.type==='records.saved'){setRecording(event);setNotice('本次文字记录已保存，可查看历史和报告。');}
    else if(event.type==='records.pending'){setRecording(event);setNotice('文字记录待保存，可在结束后点击重试保存。');}
    else if(event.type==='records.error'){setRecording(event);setError(new Error(event.message));setNotice('保存状态需要处理，请保留当前页面的文字。');}
    else if(event.type==='screening.status'){setScreening(event);}
    else if(event.type==='status'){setNotice(event.message||'');}
    else if(event.type==='error'){setError(new Error(event.message||'语音连接异常，请稍后重试。'));setState('error');ready.current=false;media.current?.getTracks().forEach(t=>t.stop());}
  }
  async function start(){
    setDebug(null);
    socket.current?.close();socket.current=null;
    releaseAudio();setError(null);setLines([]);setRecording(null);setMuted(false);micMuted.current=false;stopping.current=false;
    blocked.current.clear();audioDone.current.clear();currentAudio.current='';finishAfterPlayback.current=false;replyWait.current=0;setStalled(false);setScreening(null);speech.current={active:false,lastVoice:0,started:0};setState('connecting');setNotice('正在准备音频环境…');
    try{
      if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia)throw Error('当前页面无法使用麦克风，请使用本机 localhost 页面或 HTTPS。');
      const token=localStorage.getItem('access_token');if(!token)throw Error('请先登录再开始语音。');
      const ctx=new AudioContext({latencyHint:'interactive'});context.current=ctx;await ctx.resume();
      setNotice('正在请求麦克风权限；如果浏览器弹窗询问，请选择允许。');
      const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});media.current=stream;
      setNotice('麦克风已就绪，正在初始化音频…');
      await ctx.audioWorklet.addModule('/audio/pcm-capture.js');
      const node=new AudioWorkletNode(ctx,'pcm-capture',{numberOfInputs:1,numberOfOutputs:1,channelCount:1});capture.current=node;
      const source=ctx.createMediaStreamSource(stream),silent=ctx.createGain();silent.gain.value=0;source.connect(node);node.connect(silent);silent.connect(ctx.destination);
      setNotice('音频已就绪，正在连接语音服务…');
      const ws=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/api/robot-voice/live`);socket.current=ws;
      ws.onopen=()=>{
        ws.send(JSON.stringify({type:'authenticate',token,device_id:'windows_browser'}));
        watchdog.current=setInterval(()=>{
          if(replyWait.current&&Date.now()-replyWait.current>25000&&!stopping.current){setStalled(true);setNotice('回复等待较久，可先发送当前这句话，或重新连接；已有最终文字会保留。');}
        },1000);
      };
      ws.onmessage=e=>{if(socket.current!==ws)return;try{receive(JSON.parse(e.data));}catch{setError(new Error('收到的语音数据无法处理，请重新开始。'));finish();}};
      ws.onerror=()=>{if(socket.current!==ws)return;setError(new Error('语音连接未能建立，请检查服务状态后重试。'));setState('error');releaseAudio();};
      ws.onclose=()=>{if(socket.current!==ws)return;socket.current=null;releaseAudio();setLevel(0);setState(old=>old==='error'?'error':'ended');if(reconnecting.current){reconnecting.current=false;window.setTimeout(()=>void start(),0);}};
      node.port.onmessage=e=>{
        if(!ready.current||micMuted.current)return;
        const now=Date.now();
        if(now-lastMeter.current>100){lastMeter.current=now;setLevel(Math.min(100,e.data.level*500));}
        if(ws.readyState===WebSocket.OPEN){
          if(ws.bufferedAmount>128000){setError(new Error('网络发送拥堵，本次收音已停止。'));finish();return;}
          ws.send(e.data.pcm);
          if(e.data.level>.015){if(!speech.current.active)speech.current.started=now;speech.current.active=true;speech.current.lastVoice=now;}
          if(speech.current.active&&(now-speech.current.lastVoice>2500||now-speech.current.started>30000)){
            send({type:'commit'});speech.current.active=false;replyWait.current=now;
          }
        }
      };
    }catch(e){releaseAudio();setState('error');setError(e instanceof Error?e:new Error('无法打开麦克风。'));}
  }
  function toggleMute(){const next=!micMuted.current;micMuted.current=next;setMuted(next);media.current?.getAudioTracks().forEach(t=>{t.enabled=!next;});send({type:next?'mute':'unmute'});setState(next?'muted':'listening');if(next)setLevel(0);}
  function recover(){const previous=socket.current;if(!previous){void start();return;}reconnecting.current=true;finish();window.setTimeout(()=>{if(socket.current===previous)previous.close();},7000);}
  async function retrySave(){try{const result=await api('robot-voice/retry-records',{method:'POST'});setNotice(result.pending?'仍有文字等待保存，请稍后重试。':'待保存记录已处理，可在历史中查看。');}catch(e){setError(e);}}
  async function readDiagnostics(){try{setDebug(await api<VoiceDiagnostics>('robot-voice/diagnostics'));}catch(e){setError(e);}}
  async function demoStart(){try{setError(null);await api('robot-voice/demo/start',{method:'POST'});setNotice('已排队手动启动演示，等待语音服务确认；结果会标记人工触发。');}catch(e){setError(e);}}
  async function demoReset(){try{setError(null);await api('robot-voice/demo/reset',{method:'POST'});setScreening(null);setLines([]);setRecording(null);setNotice('新一轮演示已准备好，已有演示记录仍保留。');}catch(e){setError(e);}}
  const connected=['listening','muted','playing','interrupted'].includes(state),canStart=['idle','ended','error'].includes(state);
  return <CareShell title="和陪伴助手聊一聊" subtitle="直接说话即可交流，实时文字会显示在这里。">
    {config?.demo_mode&&<section className="care-card" data-testid="short-collection-demo"><h2>快速采集演示 · 3项自定义指标</h2><p>先说一句自己的近况，例如“最近心情有点低落，做事情没什么兴致”。助手随后简短询问三项近两周情况。可回答“有时”“经常”“较少”，并核对助手复述是否正确。</p><p>已确认 {screening?.demo_progress?.answered??0}/3 项{screening?.demo_progress?.total!=null&&<strong data-testid="demo-live-total"> · 演示指标合计 {screening.demo_progress.total}/12</strong>}</p><p className="care-meta">本通话进度；结束并保存后可到量表页核对原话来源。不作为完整 PHQ-9／GAD-7 总分。</p>{screening?.trigger_origin==='manual_demo'&&<p className="care-notice">本轮为人工触发演示，未声称由模型自动判定。</p>}<div className="care-actions"><button className="care-btn secondary" disabled={!connected||!lines.some(l=>l.role==='user'&&l.final)||!['companionship','waiting_context'].includes(screening?.stage||'companionship')} onClick={demoStart}>手动启动演示（留痕）</button><button className="care-btn secondary" disabled={!canStart} onClick={demoReset}>准备新一轮演示</button><Link className="care-btn secondary" href="/robot-care/assessments">查看演示采集与分数</Link></div></section>}
    <div className="voice-layout"><section className="care-card voice-console"><div className={`voice-orb ${connected?'active':''}`} aria-hidden="true">声</div><h2>{names[state]||state}</h2><p className="voice-notice" role="status">{notice}</p>{config?.conditional_collection_enabled&&<div className={`voice-screening-state ${screening?.stage==='collecting'?'active':''}`} role="status"><span className="voice-screening-dot" aria-hidden="true"/><div><strong>{screeningLabels[screening?.stage||'']||'会话接通后开始留意'}</strong><p>{screening?.error_code?screeningErrors[screening.error_code]||'后台判断暂不可用，尚未开始进一步了解。':screening?.stage==='urgent'?'先关注此刻感受和安全支持，暂停信息采集。':screening?.stage==='reviewing'?'语音连接仍保持着；后台正在看刚才这段文字，并会尽快回来继续。':screening?.review_status==='pending'?'刚才的梳理还在后台继续；你可以照常和我聊。':screening?.review_status==='normal'?'这段对话暂未安排后续信息采集；可以继续自然聊聊。':screening?.detector_status==='checked'&&!screening?.triggered?'这轮后台判断已完成，目前没有足够线索进入近况梳理；可以继续聊。':(screening?.review_mode||config.concern_review_mode)==='post_session'&&!screening?.triggered?'通话结束并保存后，会结合近期对话整理近况；需要进一步了解的信息会在后续对话中继续补充。':screening?.stage==='waiting_context'?'有上次留下的信息需要继续了解，先等合适时机再自然梳理。':screening?.stage==='collecting'?'会沿着对话中相关的方向，一次聊一件；量表辅助结果与自定义指标分别保存、待核实，不等同正式施测或诊断。':'先听你慢慢说；是否继续了解会结合对话判断，不会只按轮数直接打分。'}</p></div></div>}<div className="voice-meter" aria-label="麦克风输入强度"><span style={{width:`${level}%`}}/></div><p className="care-meta">麦克风输入 · 建议使用耳机，减少回声</p><div className="voice-controls">{canStart?<button className="care-btn" disabled={!config?.enabled} onClick={start}>开始语音对话</button>:<><button className="care-btn secondary" disabled={!connected} onClick={toggleMute}>{muted?'继续收音':'暂停收音'}</button><button className="care-btn secondary" disabled={!connected} onClick={interrupt}>打断回复</button><button className="care-btn" disabled={!connected} onClick={finish}>结束并保存</button></>}</div>{config&&!config.enabled&&<p className="care-notice">{config.message}</p>}<ErrorBox error={error}/>{connected&&<div className="care-actions"><button className="care-btn secondary" disabled={!lines.some(l=>l.role==='user'&&!l.final)} onClick={()=>{send({type:'commit'});speech.current.active=false;replyWait.current=Date.now();}}>发送这句话</button><button className="care-btn secondary" onClick={recover}>{stalled?'回复卡住，重新连接并保留记录':'重新连接并保留记录'}</button></div>}<p className="care-meta">{config?.is_test?'当前为联调测试，文字记录带测试标记。':'当前记录带非测试标志；不代表已完成真实性或专业核验。'}</p></section>
    <section className="care-card voice-transcripts"><div className="voice-transcript-heading"><h2>正在聊的内容</h2><span className="care-badge">实时字幕</span></div>{!lines.length&&<div className="voice-empty">开始后，您说的话和助手回复会依次显示。<br/>语音对话中可以随时暂停收音或打断回复。</div>}<div aria-live="polite" aria-relevant="additions text" className="voice-lines">{lines.map(line=><article className={`voice-line ${line.role}`} key={line.message_id} data-testid={`voice-line-${line.message_id}`}><header><strong>{line.role==='user'?'您':'陪伴助手'}</strong><span>{line.interrupted?'已打断':line.final?'最终文字':'识别 / 回复中'}</span></header><p>{line.text}</p>{line.occurred_at&&<time>{date(line.occurred_at)}</time>}</article>)}</div></section></div>
    <section className="care-card voice-record-status"><h2>本次记录</h2><p>{recording?.type==='records.saved'?'双方最终文字已保存到历史。':connected?'已确认的最终文字写入持久队列，结束会话后上传到历史。':'结束后可查看本次文字记录与报告。'}</p><div className="care-actions">{recording?.recording_session_id&&<><Link className="care-btn secondary" href={`/robot-care/sessions/${recording.recording_session_id}`}>查看本次记录</Link><Link className="care-btn" href="/robot-care/report" onClick={()=>sessionStorage.setItem('care-report-scope',JSON.stringify({session_ids:[recording.recording_session_id]}))}>生成本次回顾</Link></>}<button className="care-btn secondary" disabled={!canStart} onClick={retrySave}>重试待保存记录</button></div></section>
    {config?.is_test&&<details className="care-card care-no-print"><summary>开发联调状态（仅测试环境）</summary><p className="care-meta">只查询本人当前通话的后台状态，不会强制触发采集。</p><button className="care-btn secondary" onClick={readDiagnostics}>查看后台状态</button>{debug&&<div role="status"><p>{debug.message}</p>{debug.active&&<p className="care-meta">用户最终转录：{debug.user_turns} 段 · 已检测到第 {debug.checked_user_turns} 段<br/>阶段：{debug.stage} · 检测状态：{debug.detector_status} · 最近错误：{debug.last_error_code||'无'}<br/>服务事件：{debug.transport?.last_remote_event??'无'}（{debug.transport?.last_remote_event_age_seconds??'未知'}秒前）· 上行音频帧：{debug.transport?.audio_frames??0} · 会话就绪：{debug.transport?.session_ready_ms??'未知'}毫秒<br/>最近文字：{debug.transport?.last_final_role??'无'}（{debug.transport?.last_final_age_seconds??'未知'}秒前）· 收音中断：{debug.transport?.capture_gap_count??0} 次<br/>指令版本：已发送 {debug.sent_policy_version??'无'} / 豆包已确认 {debug.applied_policy_version??'无'}</p>}</div>}</details>}
  </CareShell>;
}
