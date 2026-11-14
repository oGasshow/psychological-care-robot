/** Browser-only regression with fictional API responses, never production data. */
import { chromium } from 'playwright-core';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';

const base=process.env.CARE_BASE_URL, output=process.env.EVIDENCE_DIR;
if(!base||!output)throw Error('Set CARE_BASE_URL and EVIDENCE_DIR for the isolated frontend.');
const origin=new URL(base).origin;
await mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.BROWSER_EXE||'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1050},locale:'zh-CN'});
await context.addInitScript(()=>localStorage.setItem('access_token','fictional-browser-test-token'));
let phase='pending', reads=0, retries=0;
const evidence={source:'fictional_api_browser_regression',checks:[],page_errors:0,status:'running'};
await context.route(origin+'/api/**',async route=>{
  const pathname=new URL(route.request().url()).pathname;
  let body={};
  if(pathname.endsWith('/profile'))body={anonymous_id:'KY-fictional-ui-test'};
  if(pathname.endsWith('/sega/status'))body={message:'虚构测试：模型实验状态。',installed:false,probe_allowed:false};
  if(pathname.endsWith('/retry')){retries++;phase='pending';body={status:'queued'};}
  if(pathname.endsWith('/assessments')){
    reads++;
    body={provider:'disabled',status:'no_records',items:[],after_call_review_mode:'post_session',
      collection_plan:{needs_collection:true,status:'waiting_context',scales:[{scale:'PHQ-9',answered:1,required:9}]},
      conversation_collections:[{recording_session_id:101,started_at:'2026-11-14T08:00:00Z',is_test:true,
        stage:'collecting',detector_status:'checked',source_status:'current_original_text',
        scales:[{scale:'PHQ-9',answered:1,required:9,total:null}]}],
      after_call_reviews:[{recording_session_id:101,state:phase,updated_at:'2026-11-14T08:01:00Z',attempt:1,
        decision:phase==='succeeded'?'follow_up':null,target_scales:['PHQ-9','mood_interest'],
        error_code:phase==='failed'?'after_call_review_timeout':null,message:'虚构测试：复核状态与采集进度分别保留。'}]};
  }
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
});
const page=await context.newPage();
page.on('pageerror',()=>evidence.page_errors++);
async function jobHas(text){await page.waitForFunction(text=>document.querySelector('[data-testid="after-call-101"]')?.textContent.includes(text),text);}
try{
  await page.goto(origin+'/robot-care/assessments',{waitUntil:'networkidle'});
  await jobHas('等待后台复核');evidence.checks.push('pending_state');
  assert((await page.getByTestId('persistent-collection-plan').innerText()).includes('1/9'));
  evidence.checks.push('partial_progress_preserved');
  phase='succeeded';await jobHas('发现需要进一步了解的线索');assert(reads>=2);
  evidence.checks.push('automatic_status_refresh');
  await page.screenshot({path:path.join(output,'after-call-desktop.png'),fullPage:true});
  phase='failed';await page.getByRole('button',{name:'刷新采集与指标结果'}).click();
  await page.getByRole('button',{name:'重试后台复核'}).click();await jobHas('等待后台复核');assert.equal(retries,1);
  evidence.checks.push('failed_review_retry');
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
  await page.screenshot({path:path.join(output,'after-call-mobile.png'),fullPage:true});
  evidence.checks.push('mobile_layout');assert.equal(evidence.page_errors,0);evidence.checks.push('no_page_errors');
  evidence.status='passed';
}catch(error){evidence.status='failed';evidence.failure=error.message;process.exitCode=1;}
finally{await writeFile(path.join(output,'after-call-browser.json'),JSON.stringify(evidence,null,2),'utf8');await browser.close();}
console.log(JSON.stringify({status:evidence.status,checks:evidence.checks.length,page_errors:evidence.page_errors}));
