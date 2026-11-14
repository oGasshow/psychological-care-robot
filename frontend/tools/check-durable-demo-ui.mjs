/** Deliberately late collection trigger; the independent worker must reconcile. */
import {chromium} from 'playwright-core';
import {writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const base=process.env.CARE_BASE_URL,output=process.env.EVIDENCE_DIR;
const browser=await chromium.launch({executablePath:'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream','--mute-audio']});
const proof={status:'running',checks:[],page_errors:0};
try{
 const context=await browser.newContext({permissions:['microphone']});const page=await context.newPage();page.on('pageerror',()=>proof.page_errors++);
 await page.goto(base+'/login',{waitUntil:'networkidle'});
 await page.locator('input[name=username]').fill(process.env.DEMO_USER);await page.locator('input[name=password]').fill(process.env.DEMO_PASSWORD);
 await page.locator('button[type=submit]').click();await page.waitForURL('**/robot-care');
 await page.goto(base+'/robot-care/voice',{waitUntil:'networkidle'});
 await page.getByRole('button',{name:'准备新一轮演示'}).click();
 await page.getByRole('button',{name:'开始语音对话',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('.voice-line.user').length>=4);
 await page.waitForFunction(async()=>{const r=await fetch('/api/robot-voice/diagnostics',{headers:{Authorization:'Bearer '+localStorage.getItem('access_token')}});const d=await r.json();return d.checked_user_turns>=3&&!d.detector_running;});
 await page.getByRole('button',{name:'手动启动演示（留痕）'}).click();
 await page.waitForFunction(()=>document.querySelector('[data-testid=short-collection-demo]')?.textContent.includes('人工触发'));
 assert((await page.getByTestId('short-collection-demo').innerText()).includes('已确认 0/3'));proof.checks.push('no_live_answers_before_save');
 await page.getByRole('button',{name:'结束并保存',exact:true}).click();
 const saved=page.getByRole('link',{name:'查看本次记录',exact:true});await saved.waitFor();
 const sid=Number((await saved.getAttribute('href')).split('/').at(-1));
 await page.waitForFunction(async id=>{const r=await fetch('/api/robot-voice/screening-results/'+id,{headers:{Authorization:'Bearer '+localStorage.getItem('access_token')}});const d=await r.json();return d.result?.automatic_saved_answer_review===true&&d.result.scales[0].total===6&&d.result.source_status==='current_original_text';},sid,{timeout:30000});
 proof.checks.push('independent_worker_recovered_three_grounded_answers');
 await page.goto(base+'/robot-care/assessments',{waitUntil:'networkidle'});
 const row=page.getByTestId('collection-'+sid);await page.waitForFunction(id=>document.querySelector('[data-testid=collection-'+id+']')?.textContent.includes('已确认 3/3 项'),sid);proof.rendered_row=await row.innerText();assert((await row.innerText()).includes('已确认 3/3 项'));assert((await row.innerText()).includes('自定义指标分 6/12'));proof.checks.push('automatic_score_visible');
 assert.equal(proof.page_errors,0);proof.status='passed';
}catch(e){proof.status='failed';proof.failure=e.message;process.exitCode=1;}
finally{await mkdir(output,{recursive:true});await writeFile(path.join(output,'durable-demo-browser.json'),JSON.stringify(proof,null,2));await browser.close();}
console.log(JSON.stringify(proof));
