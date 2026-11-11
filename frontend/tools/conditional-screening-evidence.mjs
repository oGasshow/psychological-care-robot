/** Actual Edge + same-origin API. Only an isolated fictional demo runtime. */
import {chromium} from 'playwright-core';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';

const runtime=process.env.CONDITIONAL_RUNTIME,output=process.env.CONDITIONAL_EVIDENCE;
if(!runtime||!output)throw Error('Set CONDITIONAL_RUNTIME and CONDITIONAL_EVIDENCE.');
const cfg=JSON.parse(await readFile(path.join(runtime,'access.json'),'utf8'));
if(cfg.seed_sample_data!==false)throw Error('Use a dedicated --empty demo.');
const origin=`http://127.0.0.1:${cfg.frontend_port}`;
await mkdir(path.join(output,'browser'),{recursive:true});
const browser=await chromium.launch({executablePath:process.env.BROWSER_EXE||'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true,args:['--no-first-run','--no-default-browser-check']});
const context=await browser.newContext({viewport:{width:1440,height:1050},locale:'zh-CN',timezoneId:'Asia/Shanghai'});
const page=await context.newPage();const checks=[];let pageErrors=0;
page.on('pageerror',()=>pageErrors++);
const assert=(condition,message)=>{if(!condition)throw Error(message);};
try{
  await page.goto(origin+'/login',{waitUntil:'networkidle'});
  await page.locator('input[name="username"]').fill(cfg.users[0].username);
  await page.locator('input[name="password"]').fill(cfg.users[0].password);
  await page.locator('button[type="submit"]').click();await page.waitForURL('**/robot-care');
  await page.goto(origin+'/robot-care/voice',{waitUntil:'networkidle'});
  assert(await page.getByRole('checkbox').count()===0,'Voice page still has opt-in checkbox');
  assert(await page.getByRole('button',{name:/准备好了|同意|愿意慢慢聊/}).count()===0,'Voice page still requires readiness or consent');
  await page.screenshot({path:path.join(output,'browser','01_voice_no_questionnaire_gate.png'),fullPage:true});
  checks.push('voice_has_no_optin_or_consent_gate');
  for(const name of ['ordinary','depressive_concern']){
    const voice=JSON.parse(await readFile(path.join(output,'voice',`voice_${name}.json`),'utf8'));
    const sid=voice.recording_session_id;
    await page.evaluate(sid=>sessionStorage.setItem('care-report-scope',JSON.stringify({session_ids:[sid]})),sid);
    await page.goto(origin+'/robot-care/report',{waitUntil:'domcontentloaded'});
    await page.getByTestId('report-dto').waitFor({timeout:15000});
    await page.waitForFunction(()=>!document.querySelector('[data-testid="report-status"]')?.textContent?.includes('正在'),{},{timeout:65000});
    const reportText=await page.getByTestId('report-dto').innerText();
    if(name==='ordinary'){
      assert(!/PHQ-9|GAD-7|对话辅助采集|总分未生成/.test(reportText),'Ordinary report has empty scales');
      assert(reportText.includes('这段时间，记录告诉我们'),'Ordinary narrative missing');
      checks.push('ordinary_report_no_assessment_section');
    }else{
      assert(reportText.includes('PHQ-9')&&reportText.includes('待核实'),'Triggered result missing');
      assert(!reportText.includes('GAD-7'),'Unrequested GAD-7 appeared');
      assert(reportText.includes('信息未齐，总分未生成'),'Incomplete answers must not show a total');
      checks.push('triggered_report_only_collected_target_and_missing_total');
    }
    await page.screenshot({path:path.join(output,'browser',`02_report_${name}.png`),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(output,'browser',`03_mobile_${name}.png`),fullPage:true});
    await page.setViewportSize({width:1440,height:1050});
  }
  assert(pageErrors===0,'Unexpected browser errors');
  const receipt={passed:true,checks,page_errors:pageErrors,browser:await browser.version(),all_input_fictional:true,physical_microphone_opened:false};
  await writeFile(path.join(output,'browser','receipt.json'),JSON.stringify(receipt,null,2));
  console.log(JSON.stringify(receipt,null,2));
}catch(error){await page.screenshot({path:path.join(output,'browser','failure.png'),fullPage:true}).catch(()=>{});throw error;}
finally{await browser.close();}
