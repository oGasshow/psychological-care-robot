/** Mock speech timings; actual HTTP persistence must advance before call close. */
import {chromium} from 'playwright-core';
import {writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const base=process.env.CARE_BASE_URL,output=process.env.EVIDENCE_DIR;
const browser=await chromium.launch({executablePath:'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream','--mute-audio']});
const proof={status:'running',source:'mock_protocol_real_live_http_persistence',checks:[],page_errors:0};
try{
 const ctx=await browser.newContext({permissions:['microphone']});const p=await ctx.newPage();p.on('pageerror',()=>proof.page_errors++);
 await p.goto(base+'/login',{waitUntil:'networkidle'});await p.locator('input[name=username]').fill(process.env.DEMO_USER);await p.locator('input[name=password]').fill(process.env.DEMO_PASSWORD);await p.locator('button[type=submit]').click();await p.waitForURL('**/robot-care');
 await p.goto(base+'/robot-care/voice',{waitUntil:'networkidle'});await p.getByRole('button',{name:'准备新一轮演示'}).click();await p.getByRole('button',{name:'开始语音对话',exact:true}).click();
 await p.waitForFunction(()=>document.querySelectorAll('.voice-line.user').length>0);await p.getByRole('button',{name:'手动启动演示（留痕）'}).click();
 await p.waitForFunction(async()=>{const h={Authorization:'Bearer '+localStorage.getItem('access_token')};const r=await fetch('/api/robot-insights/assessments',{headers:h});const d=await r.json();return d.collection_plan?.scales?.[0]?.answered===1&&d.conversation_collections?.[0]?.scales?.[0]?.answered===1;});proof.checks.push('one_item_saved_before_end');
 await p.waitForFunction(async()=>{const h={Authorization:'Bearer '+localStorage.getItem('access_token')};const r=await fetch('/api/robot-insights/assessments',{headers:h});const d=await r.json();return d.collection_plan?.scales?.[0]?.answered===2&&d.conversation_collections?.[0]?.scales?.[0]?.answered===2;});proof.checks.push('second_natural_sentence_saved_same_call');
 await p.getByTestId('demo-live-total').waitFor();assert((await p.getByTestId('demo-live-total').innerText()).includes('6/12'));
 await p.waitForFunction(async()=>{const h={Authorization:'Bearer '+localStorage.getItem('access_token')};const r=await fetch('/api/robot-insights/assessments',{headers:h});const d=await r.json();const c=d.conversation_collections?.[0];return d.collection_plan?.scales?.[0]?.answered===3&&c?.scales?.[0]?.total===6&&c.source_status==='current_original_text';});proof.checks.push('third_pronoun_followup_saved_same_call');
 assert(await p.evaluate(async()=>{const r=await fetch('/api/robot-voice/diagnostics',{headers:{Authorization:'Bearer '+localStorage.getItem('access_token')}});return (await r.json()).active===true;}));proof.checks.push('call_still_active_when_all_results_persisted');
 await p.getByTestId('collection-save-status').waitFor();assert((await p.getByTestId('collection-save-status').innerText()).includes('后台保存'));proof.checks.push('save_receipt_visible');
 await p.getByRole('button',{name:'结束并保存',exact:true}).click();await p.getByRole('link',{name:'查看本次记录',exact:true}).waitFor();proof.checks.push('final_archive_confirmed');
 await p.goto(base+'/robot-care/assessments',{waitUntil:'networkidle'});assert((await p.getByTestId('scale-summary-mood_interest').innerText()).includes('已确认 3/3'));proof.checks.push('result_page_consistent');
 assert.equal(proof.page_errors,0);proof.status='passed';
}catch(e){proof.status='failed';proof.failure=e.message;process.exitCode=1;}
finally{await mkdir(output,{recursive:true});await writeFile(path.join(output,'live-collection-browser.json'),JSON.stringify(proof,null,2));await browser.close();}
console.log(JSON.stringify(proof));
