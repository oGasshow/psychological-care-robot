/** Fictional standard-scale history, real rendering and PDF export. */
import {chromium} from 'playwright-core';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const base=process.env.CARE_BASE_URL,out=process.env.EVIDENCE_DIR;
const fixture=JSON.parse(await readFile(process.env.REPORT_FIXTURE,'utf8'));
await mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.BROWSER_EXE||'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true});
const proof={checks:[],page_errors:0,source:'fictional_standard_history_real_browser_and_pdf'};
try{
 const ctx=await browser.newContext({viewport:{width:1440,height:1050},timezoneId:'UTC',locale:'zh-CN'}),p=await ctx.newPage();p.on('pageerror',()=>proof.page_errors++);
 await p.goto(base+'/login',{waitUntil:'networkidle'});await p.locator('input[name=username]').fill(process.env.DEMO_USER);await p.locator('input[name=password]').fill(process.env.DEMO_PASSWORD);await p.locator('button[type=submit]').click();await p.waitForURL('**/robot-care');
 await p.route('**/api/robot-insights/reports/preview',r=>r.fulfill({json:fixture}));
 await p.route('**/api/robot-insights/reports/narrative',r=>r.fulfill({json:{source_snapshot_hash:fixture.source_snapshot_hash,narrative:fixture.narrative}}));
 await p.goto(base+'/robot-care/report',{waitUntil:'networkidle'});await p.getByTestId('scale-trend-PHQ-9').waitFor();
 for(const [id,before,after] of [['PHQ-9',12,6],['GAD-7',9,4]]){
  const g=p.getByTestId('scale-trend-'+id);assert.equal(await g.getAttribute('data-completed-count'),'2');assert((await g.innerText()).includes(`${before} → ${after} 分`));assert.equal(await g.locator('tbody tr').count(),2);
 }
 proof.checks.push('standard_histories_deduplicated_and_plotted');
 const generated=new Date(fixture.generated_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});assert((await p.getByTestId('report-generated-time').innerText()).includes(generated));proof.checks.push('explicit_beijing_time_even_with_utc_browser');
 await p.screenshot({path:path.join(out,'standard-trends.png'),fullPage:true,animations:'disabled'});
 await p.setViewportSize({width:390,height:844});assert(await p.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));proof.checks.push('mobile_no_horizontal_overflow');
 await p.setViewportSize({width:1440,height:1050});await p.emulateMedia({media:'print'});await p.pdf({path:path.join(out,'standard-history.pdf'),format:'A4',printBackground:true,margin:{top:'12mm',bottom:'12mm',left:'12mm',right:'12mm'}});proof.checks.push('standard_pdf_exported');
 assert.equal(proof.page_errors,0);proof.status='passed';await ctx.close();
}catch(e){proof.status='failed';proof.failure=e.message;process.exitCode=1;}
finally{await browser.close();await writeFile(path.join(out,'browser.json'),JSON.stringify(proof,null,2));}
console.log(JSON.stringify(proof));
