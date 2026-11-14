/** Isolated backend and mock speech protocol; uses a fake microphone only. */
import {chromium} from 'playwright-core';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';

const base=process.env.CARE_BASE_URL,output=process.env.EVIDENCE_DIR;
if(!base||!output||!process.env.DEMO_USER||!process.env.DEMO_PASSWORD)throw Error('Set isolated demo browser parameters.');
await mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.BROWSER_EXE||'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true,
  args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream','--mute-audio']});
const proof={source:'mock_speech_protocol_real_browser_and_http',checks:[],page_errors:0,status:'running'};
try{
  const context=await browser.newContext({viewport:{width:1440,height:1050},permissions:['microphone']});
  const page=await context.newPage();page.on('pageerror',()=>proof.page_errors++);
  await page.goto(base+'/login',{waitUntil:'networkidle'});
  await page.locator('[data-testid="deployment-mode"][data-mode="demo"]').waitFor();proof.checks.push('explicit_demo_entry');
  await page.locator('input[name="username"]').fill(process.env.DEMO_USER);
  await page.locator('input[name="password"]').fill(process.env.DEMO_PASSWORD);
  await page.locator('button[type="submit"]').click();await page.waitForURL('**/robot-care');
  await page.goto(base+'/robot-care/voice',{waitUntil:'networkidle'});
  await page.getByTestId('short-collection-demo').waitFor();
  await page.getByRole('button',{name:'准备新一轮演示'}).click();
  await page.getByRole('button',{name:'开始语音对话',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.voice-line.user').length>0);
  await page.getByRole('button',{name:'手动启动演示（留痕）'}).click();
  await page.getByTestId('demo-live-total').waitFor();
  assert((await page.getByTestId('demo-live-total').innerText()).includes('6/12'));proof.checks.push('three_real_confirmations_sum_to_six');
  assert((await page.getByTestId('short-collection-demo').innerText()).includes('人工触发'));proof.checks.push('manual_trigger_provenance');
  await page.getByRole('button',{name:'结束并保存',exact:true}).click();
  await page.getByRole('link',{name:'查看本次记录',exact:true}).waitFor();proof.checks.push('voice_records_saved');
  await page.goto(base+'/robot-care/assessments',{waitUntil:'networkidle'});
  const result=page.getByTestId('conversation-collection-results');await result.waitFor();
  await page.waitForFunction(()=>document.querySelector('[data-testid="conversation-collection-results"]')?.textContent.includes('自定义指标分 6/12'));
  assert((await result.innerText()).includes('快速演示'));proof.checks.push('saved_score_and_demo_label');
  await page.screenshot({path:path.join(output,'short-demo-score.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));proof.checks.push('mobile_layout');
  assert.equal(proof.page_errors,0);proof.status='passed';
}catch(error){proof.status='failed';proof.failure=error.message;process.exitCode=1;}
finally{await writeFile(path.join(output,'short-demo-browser.json'),JSON.stringify(proof,null,2),'utf8');await browser.close();}
console.log(JSON.stringify({status:proof.status,checks:proof.checks.length,page_errors:proof.page_errors}));
