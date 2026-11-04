import { chromium } from 'playwright-core';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
const origin = process.env.CARE_BASE_URL;
const output = process.env.EVIDENCE_DIR;
await mkdir(output,{recursive:true});
const browser = await chromium.launch({executablePath:process.env.BROWSER_EXE,headless:true,args:['--no-first-run','--no-default-browser-check']});
const context = await browser.newContext({viewport:{width:1440,height:1050},locale:'zh-CN',timezoneId:'Asia/Shanghai'});
const page = await context.newPage();
const result={status:'running',browser:await browser.version(),checks:[],console_errors:0,external_requests:0,fixture_content:'[]'};
page.on('pageerror',()=>result.console_errors++);
page.on('request',request=>{if(new URL(request.url()).origin!==new URL(origin).origin)result.external_requests++;});
const assert=(condition,message)=>{if(!condition)throw new Error(message);};
const record=(id,details={})=>result.checks.push({id,status:'passed',...details});
async function api(route,body) {
 return page.evaluate(async({route,body})=>{
  const response=await fetch('/api/robot-insights/'+route,{method:body?'POST':'GET',cache:'no-store',
   headers:{'Content-Type':'application/json',Authorization:'Bearer '+localStorage.getItem('access_token')},
   ...(body?{body:JSON.stringify(body)}:{})});
  return {http_status:response.status,data:await response.json()};
 },{route,body});
}
const scope={time_from:'2026-10-01T00:00:00Z',time_to:'2026-11-01T00:00:00Z'};
try {
 await page.goto(origin+'/login',{waitUntil:'networkidle'});
 await page.locator('input[name="username"]').fill(process.env.DEMO_USER);
 await page.locator('input[name="password"]').fill(process.env.DEMO_PASSWORD);
 await page.locator('button[type="submit"]').click();
 await page.waitForURL('**/robot-care');
 const assessments=await api('assessments');
 assert(assessments.http_status===200&&assessments.data.status==='query_failed'&&assessments.data.reason_code==='fixture_schema_invalid'&&assessments.data.items.length===0,'Controlled provider failure');
 record('assessment_api_controlled',assessments);
 await page.goto(origin+'/robot-care/assessments',{waitUntil:'networkidle'});
 await page.getByText(/来源状态：查询失败/).waitFor();
 assert((await page.locator('body').innerText()).includes('fixture_schema_invalid'),'UI reason');
 await page.screenshot({path:path.join(output,'01_assessment_query_failed.png'),fullPage:true});
 record('assessment_page_query_failed');
 const trends=await api('trends');
 assert(trends.http_status===200&&trends.data.assessment_status==='query_failed'&&trends.data.assessments.length===0,'Trend provider failure without score invention');
 record('trends_api_degraded',{http_status:trends.http_status,assessment_status:trends.data.assessment_status});
 await page.goto(origin+'/robot-care/trends',{waitUntil:'networkidle'});
 await page.getByText('情绪类别时间线',{exact:true}).waitFor();
 assert((await page.locator('body').innerText()).includes('暂无满足条件的量表趋势'),'No fabricated trend');
 await page.screenshot({path:path.join(output,'02_trend_without_scale.png'),fullPage:true});
 record('trends_page_no_fake_scores');
 const report=await api('reports/preview',{scope});
 assert(report.http_status===200&&report.data.assessment_status==='query_failed'&&report.data.assessments.length===0,'Report keeps failure state');
 assert(report.data.warnings.some(value=>value.includes('查询失败')),'Report warning');
 record('report_api_degraded',{http_status:report.http_status,assessment_status:report.data.assessment_status});
 await page.evaluate(scope=>sessionStorage.setItem('care-report-scope',JSON.stringify(scope)),scope);
 await page.goto(origin+'/robot-care/report',{waitUntil:'networkidle'});
 await page.getByTestId('report-dto').waitFor();
 assert((await page.locator('body').innerText()).includes('量表数据未启用、无记录或查询失败'),'Report visible failure warning');
 await page.screenshot({path:path.join(output,'03_report_query_failed.png'),fullPage:true});
 record('report_page_warning');
 assert(result.console_errors===0&&result.external_requests===0,'No page errors or external input loading');
 result.status='passed';
} catch(error) {
 result.status='failed'; result.failure=String(error.message); process.exitCode=1;
 await page.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{});
} finally {
 await writeFile(path.join(output,'browser_d03_evidence.json'),JSON.stringify(result,null,2),'utf8');
 await browser.close();
}
console.log(JSON.stringify({status:result.status,checks:result.checks.length}));
