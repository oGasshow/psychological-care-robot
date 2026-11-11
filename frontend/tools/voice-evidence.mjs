/** Real browser + real same-origin voice broker + real cloud, fictional WAV only.
 * Run against an isolated demo runtime. Never uses a physical microphone.
 */
import {chromium} from 'playwright-core';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';

const runtime=process.env.VOICE_CHECK_RUNTIME,output=process.env.VOICE_CHECK_OUTPUT,wav=process.env.VOICE_CHECK_WAV;
if(!runtime||!output||!wav)throw Error('Set VOICE_CHECK_RUNTIME/OUTPUT/WAV. Use only a fictional 16k mono WAV.');
const cfg=JSON.parse(await readFile(path.join(runtime,'access.json'),'utf8'));
const origin=`http://127.0.0.1:${cfg.frontend_port}`;
await mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.BROWSER_EXE||'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true,args:['--no-first-run','--no-default-browser-check','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',`--use-file-for-fake-audio-capture=${wav}%noloop`,'--autoplay-policy=no-user-gesture-required']});
const context=await browser.newContext({viewport:{width:1440,height:1000},locale:'zh-CN',timezoneId:'Asia/Shanghai'});
await context.addInitScript(()=>{
  const evidence={sent_frames:0,events:{},scheduled_audio:0,ended_audio:0,voice_errors:[]};window.__voiceEvidence=evidence;
  const NativeWS=window.WebSocket;
  window.WebSocket=class extends NativeWS{
    constructor(...args){super(...args);this.addEventListener('message',event=>{try{const e=JSON.parse(event.data);evidence.events[e.type]=(evidence.events[e.type]||0)+1;if(e.type==='error')evidence.voice_errors.push(e.code);}catch{}});}
    send(data){if(data instanceof ArrayBuffer)evidence.sent_frames++;return super.send(data);}
  };
  const start=AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start=function(...args){evidence.scheduled_audio++;this.addEventListener('ended',()=>evidence.ended_audio++);return start.apply(this,args);};
});
const page=await context.newPage();let errors=0;page.on('pageerror',()=>errors++);
const reportResults=[];
page.on('response',async response=>{if(response.url().endsWith('/reports/narrative')){const value=await response.json().catch(()=>({}));reportResults.push({status:response.status(),mode:value.narrative?.mode,reason_code:value.narrative?.reason_code,error_code:value.error?.code});}});
try{
  await page.goto(origin+'/login',{waitUntil:'networkidle'});
  await page.locator('input[name="username"]').fill(cfg.users[0].username);
  await page.locator('input[name="password"]').fill(cfg.users[0].password);
  await page.locator('button[type="submit"]').click();await page.waitForURL('**/robot-care');
  await page.goto(origin+'/robot-care/voice',{waitUntil:'networkidle'});
  await page.getByRole('button',{name:'开始语音对话',exact:true}).click();
  await page.waitForFunction(()=>window.__voiceEvidence.events['audio.delta']>0,{},{timeout:30000});
  await page.getByRole('button',{name:'打断回复',exact:true}).click();
  await page.waitForFunction(()=>[...document.querySelectorAll('.voice-line.user')].some(e=>e.innerText.includes('最终文字')),{},{timeout:35000});
  await page.waitForFunction(()=>document.querySelectorAll('.voice-line.assistant').length>=2,{},{timeout:30000});
  await page.getByRole('button',{name:'暂停收音',exact:true}).click();
  await page.getByRole('button',{name:'继续收音',exact:true}).waitFor();
  await page.screenshot({path:path.join(output,'01_voice_live.png'),fullPage:true});
  await page.waitForTimeout(4000);
  await page.getByRole('button',{name:'结束并保存',exact:true}).click();
  await page.getByRole('link',{name:'查看本次记录',exact:true}).waitFor({timeout:20000});
  await page.screenshot({path:path.join(output,'02_voice_saved.png'),fullPage:true});
  const receipt=await page.evaluate(()=>({...window.__voiceEvidence,text:document.querySelector('.voice-lines')?.innerText,mic_stopped:document.querySelector('.voice-meter span')?.style.width==='0%'}));
  receipt.page_errors=errors;receipt.real_cloud=true;receipt.input_fictional=true;receipt.browser=await browser.version();
  receipt.session_href=await page.getByRole('link',{name:'查看本次记录',exact:true}).getAttribute('href');
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'03_voice_mobile.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:1000});
  await page.getByRole('link',{name:'生成本次回顾',exact:true}).click();
  await page.getByText('模型生成 · 可查看依据',{exact:true}).waitFor({timeout:60000});
  receipt.report_model_visible=true;
  receipt.report_results=reportResults;
  await page.screenshot({path:path.join(output,'04_voice_model_report.png'),fullPage:true});
  if(receipt.voice_errors.length||errors||!receipt.sent_frames||!receipt.scheduled_audio)throw Error('Voice browser checks failed');
  await writeFile(path.join(output,'browser_voice_receipt.json'),JSON.stringify(receipt,null,2));
  console.log(JSON.stringify({...receipt,text:undefined},null,2));
}catch(error){await page.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(path.join(output,'failure_metadata.json'),JSON.stringify({report_results:reportResults,page_errors:errors,voice:await page.evaluate(()=>window.__voiceEvidence).catch(()=>null)},null,2));throw error;}finally{await browser.close();}
