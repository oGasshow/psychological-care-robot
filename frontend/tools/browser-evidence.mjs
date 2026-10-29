/** Real Chromium/Edge + real same-origin HTTP; no token/body is written to logs.
 * Requires an isolated, already prepared demo backend and its existing login.
 * npm run browser:evidence (DEMO_USER/DEMO_PASSWORD/CARE_BASE_URL/EVIDENCE_DIR).
 */
import { chromium } from 'playwright-core';
import { mkdir,writeFile } from 'node:fs/promises';
import path from 'node:path';

const base=process.env.CARE_BASE_URL;
const username=process.env.DEMO_USER, password=process.env.DEMO_PASSWORD;
const output=process.env.EVIDENCE_DIR;
if(!base||!username||!password||!output) throw new Error('Set CARE_BASE_URL, DEMO_USER, DEMO_PASSWORD and EVIDENCE_DIR for the isolated demo.');
const origin=new URL(base).origin;
const executablePath=process.env.BROWSER_EXE || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
await mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath,headless:true,args:['--no-first-run','--no-default-browser-check']});
const context=await browser.newContext({viewport:{width:1440,height:1050},locale:'zh-CN',timezoneId:'Asia/Shanghai'});
const page=await context.newPage();
const evidence={browser:await browser.version(),origin,started_at:new Date().toISOString(),checks:[],console_error_count:0,external_request_count:0,api_statuses:[]};
const record=(id,details)=>evidence.checks.push({id,status:'passed',...details});
page.on('pageerror',()=>{evidence.console_error_count++;});
page.on('request',req=>{if(new URL(req.url()).origin!==origin)evidence.external_request_count++;});
page.on('response',res=>{if(res.url().includes('/api/'))evidence.api_statuses.push({path:new URL(res.url()).pathname,status:res.status()});});
async function shot(name){await page.screenshot({path:path.join(output,name),fullPage:true});}
async function api(route,body,method){return await page.evaluate(async({route,body,method})=>{
  const response=await fetch(`/api/${route}`,{method:method||(body?'POST':'GET'),cache:'no-store',headers:{'Content-Type':'application/json',Authorization:`Bearer ${localStorage.getItem('access_token')}`},...(body?{body:JSON.stringify(body)}:{})});
  return {status:response.status,data:await response.json().catch(()=>null)};
},{route,body,method});}
function assert(condition,message){if(!condition)throw new Error(message);}
try{
  await page.goto(`${origin}/robot-care`,{waitUntil:'networkidle'});
  await page.getByRole('alert').first().waitFor();
  assert(await page.getByText('重新登录',{exact:true}).count()>0,'Anonymous page must require existing login');
  await shot('01_login_required.png');record('login_required');
  await page.goto(`${origin}/login`,{waitUntil:'networkidle'});
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL('**/robot-care');
  await page.getByTestId('history-list').waitFor();
  await page.waitForFunction(()=>document.querySelector('[data-testid="anonymous-id"]')?.textContent?.startsWith('KY-'));
  const anon=await page.getByTestId('anonymous-id').innerText();
  assert(!(await page.locator('body').innerText()).includes(username),'Care page must not display real username');
  await shot('02_history.png');record('real_login_anonymous_history',{anonymous_id:anon});
  const sessions=await api('robot-records/sessions?limit=100');assert(sessions.status===200 && sessions.data.items.length,'Demo sessions required');
  const session=sessions.data.items.find(s=>s.is_complete)||sessions.data.items[0];
  const sid=session.recording_session_id;
  const messages=await api(`robot-records/sessions/${sid}/messages?limit=100`);assert(messages.status===200,'Message HTTP read');
  const user=messages.data.items.find(m=>m.role==='user'&&m.text_status==='completed'&&m.content);assert(user,'Demo user/completed record required');
  // Separate September UI fixture; it never changes the fixed October 20-turn denominator.
  const uiSession=await api('robot-records/sessions',{source:'doubao_realtime',device_id:'browser_ui_simulator',external_session_id:`browser_ui_${Date.now()}`,started_at:'2026-09-15T23:59:00Z',is_test:true});
  assert(uiSession.status===201,'Create isolated UI fixture');
  const uiSid=uiSession.data.recording_session_id;
  for(let seq=1;seq<=52;seq++){
    const created=await api(`robot-records/sessions/${uiSid}/messages`,{external_message_id:`browser_ui_${seq}`,turn_id:`ui_turn_${seq}`,sequence_no:seq,role:seq===1?'user':'assistant',content:seq===1?'虚构原始转录：今天和朋友聊天很开心 😊\n第二行中文记录 <img src="https://invalid.example.invalid/source">':`虚构页面分页记录 ${seq}`,occurred_at:new Date(Date.parse('2026-09-15T23:59:00Z')+seq*1000).toISOString(),text_status:seq===2?'canceled':'completed',playback_status:seq===1?'not_applicable':seq===2?'interrupted':seq===3?'unknown':'completed'});
    assert(created.status===201,`Create UI fixture row ${seq}`);
  }
  assert((await api(`robot-records/sessions/${uiSid}/close`,{ended_at:'2026-09-16T00:01:00Z',last_sequence_no:53})).status===200,'Close deliberately incomplete UI fixture');
  await page.goto(`${origin}/robot-care/sessions/${uiSid}`,{waitUntil:'networkidle'});
  await page.getByTestId('session-summary').waitFor();
  assert(await page.locator('[data-testid^="message-"]').count()===50,'Initial real backend message page should contain 50 records');
  await page.getByRole('button',{name:'加载下一页对话'}).click();
  await page.waitForFunction(()=>document.querySelectorAll('[data-testid^="message-"]').length===52);
  const sequences=await page.locator('[data-testid^="message-"] header strong').allTextContents();
  assert(sequences.every((text,index)=>text.startsWith(`#${index+1} ·`)),'Paged history must keep sequence order');
  const uiText=await page.locator('body').innerText();
  assert(uiText.includes('文本取消')&&uiText.includes('播放中断')&&uiText.includes('播放情况未知')&&uiText.includes('尚未收齐'),'Separate text/playback/completeness states');
  assert(uiText.includes('2026/9/16')&&uiText.includes('UTC+8')&&uiText.includes('😊')&&uiText.includes('第二行中文记录'),'Chinese, emoji, newline and cross-day timezone rendering');
  assert(await page.locator('[data-testid^="message-"] .care-text img').count()===0,'Raw transcript external image must be escaped');
  await shot('03a_history_pagination_statuses.png');record('history_real_pagination_chinese_timezone_states',{recording_session_id:uiSid,page_size:50,total_loaded:52,close_boundary:53});
  await page.goto(`${origin}/robot-care/sessions/${sid}`,{waitUntil:'networkidle'});
  await page.getByTestId('session-summary').waitFor();
  await shot('03_session_summary.png');record('session_history_summary',{recording_session_id:sid,visible_messages:await page.locator('[data-testid^="message-"]').count()});
  const article=page.getByTestId(`message-${user.record_id}`);
  await article.getByRole('button',{name:'查看有效稿 / 更正转录'}).click();
  await page.getByTestId(`effective-${user.record_id}`).waitFor();
  const original=(await api(`robot-insights/messages/${user.record_id}/effective`)).data;
  const payload='<script>window.__careUnsafeExecuted=true</script>\n<img src="https://invalid.example.invalid/private" onerror="window.__careUnsafeExecuted=true">\n虚构更正：今天和朋友聊天很开心 😊';
  await page.locator(`#correction-${user.record_id}`).fill(payload);
  await article.getByRole('button',{name:'提交更正',exact:true}).click();
  await page.waitForFunction(({id,text})=>document.querySelector(`[data-testid="effective-${id}"]`)?.textContent===text,{id:user.record_id,text:payload});
  assert(await page.getByTestId(`original-${user.record_id}`).innerText()===original.original_content,'Original immutable text');
  assert(await page.getByTestId(`effective-${user.record_id}`).locator('script,img').count()===0,'Markup must remain plain text');
  assert(!await page.evaluate(()=>Boolean(window.__careUnsafeExecuted)),'Untrusted markup executed');
  await shot('04_correction_escaped.png');record('correction_original_effective_html_escaped',{record_id:user.record_id,revision_before:original.input_revision});
  await page.locator(`#correction-${user.record_id}`).fill(original.effective_content);
  await article.getByRole('button',{name:'提交更正',exact:true}).click();
  await page.waitForFunction(({id,text})=>document.querySelector(`[data-testid="effective-${id}"]`)?.textContent===text,{id:user.record_id,text:original.effective_content});
  record('correction_restored_by_new_revision');
  let fresh=(await api('robot-insights/analysis-jobs',{record_id:user.record_id})).data;
  for(let attempt=0;attempt<40&&fresh.status!=='succeeded'&&fresh.status!=='failed';attempt++){
    await page.waitForTimeout(500);
    fresh=(await api(`robot-insights/analysis-jobs/${fresh.task_id}`)).data;
  }
  assert(fresh.status==='succeeded'&&fresh.support_policy_id,'Restored revision should be analyzed by real worker');
  await page.goto(`${origin}/robot-care/sessions/${sid}`,{waitUntil:'networkidle'});
  await page.getByRole('button',{name:`查看策略 #${fresh.support_policy_id}`,exact:true}).click();
  await page.getByRole('button',{name:'交本地模拟器核对',exact:true}).click();
  await page.getByText('本地模拟器已接收',{exact:false}).waitFor();
  await shot('04b_strategy_simulator.png');record('real_worker_revision_and_local_simulator',{task_id:fresh.task_id,policy_id:fresh.support_policy_id,input_revision:fresh.input_revision,consumer_kind:'local_simulator'});
  await page.goto(`${origin}/robot-care/assessments`,{waitUntil:'networkidle'});
  await page.getByRole('heading',{name:'量表结果，只读展示'}).waitFor();await shot('05_assessments.png');record('assessments_read_only');
  await page.goto(`${origin}/robot-care/trends`,{waitUntil:'networkidle'});
  await page.getByRole('heading',{name:'情绪类别时间线'}).waitFor();await shot('06_trends.png');record('version_grouped_trends');
  await page.goto(`${origin}/robot-care/sessions/9223372036854775807`,{waitUntil:'networkidle'});
  await page.getByRole('alert').first().waitFor();await shot('07_safe_not_found.png');record('safe_missing_resource_error');
  const scope={time_from:process.env.REPORT_FROM||'2026-10-01T00:00:00Z',time_to:process.env.REPORT_TO||'2026-11-01T00:00:00Z'};
  await page.evaluate(scope=>sessionStorage.setItem('care-report-scope',JSON.stringify(scope)),scope);
  await page.goto(`${origin}/robot-care/report`,{waitUntil:'networkidle'});
  await page.getByTestId('report-dto').waitFor();
  assert(await page.getByTestId('report-dto').innerText().then(text=>text.includes('模拟数据演示')&&text.includes(anon)&&text.includes('非专业心理咨询师')),'Report nature/demo/anonymous marks');
  await shot('08_report_preview.png');record('complete_report_preview');
  await page.getByRole('link',{name:'打开专用打印页'}).click();await page.waitForURL('**/robot-care/report/print');await page.getByTestId('report-dto').waitFor();
  const before=evidence.api_statuses.filter(s=>s.path.endsWith('/reports/preview')).length;
  await page.evaluate(()=>{window.__carePrintInvoked=false;window.print=()=>{window.__carePrintInvoked=true;};});
  const sourceRefresh=page.waitForResponse(res=>new URL(res.url()).pathname.endsWith('/reports/preview')&&res.request().method()==='POST');
  await page.getByRole('button',{name:'重新核验来源并打印 / 保存 PDF'}).click();
  const latestReport=await (await sourceRefresh).json();
  await page.waitForFunction(()=>window.__carePrintInvoked===true);
  assert(await page.getByTestId('report-dto').getAttribute('data-generated-at')===latestReport.generated_at,'PDF and saved DTO must share the latest generated_at');
  await writeFile(path.join(output,'模拟陪伴报告.dto.json'),JSON.stringify(latestReport,null,2),'utf8');
  assert(evidence.api_statuses.filter(s=>s.path.endsWith('/reports/preview')).length>before,'Print must refresh DTO through HTTP');
  assert((await page.getByTestId('report-status').innerText()).includes('核验'),'Print revalidation visible');
  await shot('09_print_page_refreshed.png');
  await page.emulateMedia({media:'print'});
  assert(!await page.getByRole('button',{name:'重新核验来源并打印 / 保存 PDF'}).isVisible(),'Print controls must be hidden');
  assert(await page.locator('.care-print-stamp').isVisible(),'Repeated print demo stamp');
  await page.pdf({path:path.join(output,'模拟陪伴报告.pdf'),format:'A4',printBackground:true,preferCSSPageSize:true,displayHeaderFooter:false});
  record('browser_print_to_pdf',{file:'模拟陪伴报告.pdf',dto:'模拟陪伴报告.dto.json',generated_at:latestReport.generated_at,source_refreshed:true,controls_hidden:true,repeated_demo_footer:true});
  assert(evidence.console_error_count===0,'Browser page errors present');
  assert(evidence.external_request_count===0,'Unexpected external resource loaded');
  record('no_page_errors_or_external_input_loads');
  evidence.finished_at=new Date().toISOString();evidence.status='passed';
}catch(error){evidence.status='failed';evidence.failure=String(error.message);await shot('failure.png').catch(()=>{});process.exitCode=1;}
finally{await writeFile(path.join(output,'browser_evidence.json'),JSON.stringify(evidence,null,2),'utf8');await browser.close();}
console.log(JSON.stringify({status:evidence.status,checks:evidence.checks.length,evidence_dir:output}));
