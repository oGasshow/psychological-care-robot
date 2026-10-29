/** D02: real same-origin HTTP + existing login + browser printing.
 * All new text is fictional, including rows deliberately marked is_test=false.
 * Uses the prepared fixture provider; never changes a provider or its file.
 * Same CARE_BASE_URL/DEMO_USER/DEMO_PASSWORD/EVIDENCE_DIR env as browser:evidence.
 */
import { chromium } from 'playwright-core';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const base = process.env.CARE_BASE_URL, username = process.env.DEMO_USER, password = process.env.DEMO_PASSWORD;
const output = process.env.EVIDENCE_DIR;
if (!base || !username || !password || !output) throw new Error('Set the isolated demo origin, credentials and a new evidence directory.');
const origin = new URL(base).origin;
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.BROWSER_EXE || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe', headless: true, args: ['--no-first-run', '--no-default-browser-check'] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1050 }, locale: 'zh-CN', timezoneId: 'Asia/Shanghai' });
const page = await context.newPage();
const evidence = { browser: await browser.version(), origin, started_at: new Date().toISOString(), test_data_notice: 'All bodies are fictional. Non-test flags are deliberate metadata boundary tests, not real personal data.', checks: [], api_statuses: [], console_error_count: 0, external_request_count: 0 };
page.on('pageerror', () => { evidence.console_error_count++; });
page.on('request', req => { if (new URL(req.url()).origin !== origin) evidence.external_request_count++; });
page.on('response', res => { if (res.url().includes('/api/')) evidence.api_statuses.push({ path: new URL(res.url()).pathname, status: res.status() }); });
const assert = (condition, message) => { if (!condition) throw new Error(message); };
async function api(route, body) {
  return await page.evaluate(async ({ route, body }) => {
    const response = await fetch(`/api/${route}`, { method: body ? 'POST' : 'GET', cache: 'no-store', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('access_token')}` }, ...(body ? { body: JSON.stringify(body) } : {}) });
    return { status: response.status, data: await response.json().catch(() => null) };
  }, { route, body });
}
async function seed(isTest, occurredAt) {
  const unique = `d02_browser_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
  const session = await api('robot-records/sessions', { source: 'doubao_realtime', device_id: 'd02_browser_metadata_simulator', external_session_id: unique, started_at: occurredAt, is_test: isTest });
  assert(session.status === 201, 'D02 isolated session creation');
  const sid = session.data.recording_session_id;
  const message = await api(`robot-records/sessions/${sid}/messages`, { external_message_id: `${unique}_m1`, turn_id: `${unique}_turn1`, sequence_no: 1, role: 'user', content: '虚构元数据边界测试：今天和朋友聊天很开心。', occurred_at: occurredAt, text_status: 'completed', playback_status: 'not_applicable' });
  assert(message.status === 201, 'D02 fictional source creation');
  assert((await api(`robot-records/sessions/${sid}/close`, { ended_at: new Date(Date.parse(occurredAt) + 1000).toISOString(), last_sequence_no: 1 })).status === 200, 'D02 session closure');
  let job = (await api('robot-insights/analysis-jobs', { record_id: message.data.record_id })).data;
  for (let attempt = 0; attempt < 80 && job.status !== 'succeeded' && job.status !== 'failed'; attempt++) {
    await page.waitForTimeout(250);
    job = (await api(`robot-insights/analysis-jobs/${job.task_id}`)).data;
  }
  assert(job.status === 'succeeded', 'Real worker must finish D02 source analysis');
  return { sid, record_id: message.data.record_id, is_test: isTest };
}
const labels = { test_only: '模拟数据演示', non_test_only: '非测试标志数据', mixed: '混合来源：测试与非测试分流', empty: '当前范围无纳入来源' };
function metadata(dto) {
  return { data_nature: dto.data_nature, is_test: dto.is_test, data_nature_summary: dto.data_nature_summary, emotion_counts_by_nature: dto.emotion_counts_by_nature, emotion_groups: dto.emotion_groups.map(g => ({ is_test: g.is_test, record_ids: g.points.map(p => p.record_id), point_is_test: g.points.map(p => p.is_test), status: g.status })), assessment_groups: dto.assessment_groups.map(g => ({ source_kind: g.source_kind, is_test: g.is_test, source_record_ids: g.points.map(p => p.source_record_id), point_is_test: g.points.map(p => p.is_test), status: g.status })) };
}
async function checkReport(id, scope, expected, { pdf = false, singlePoints = false, expectedIds = null } = {}) {
  const response = await api('robot-insights/reports/preview', { scope });
  assert(response.status === 200, `${id}: report HTTP`);
  const dto = response.data;
  assert(dto.data_nature === expected && dto.is_test === (expected === 'test_only'), `${id}: accurate nature and strict is_test`);
  assert(dto.source_references.every(s => typeof s.is_test === 'boolean') && dto.messages.every(m => typeof m.is_test === 'boolean'), `${id}: per-source flags retained`);
  for (const group of [...dto.emotion_groups, ...dto.assessment_groups]) {
    assert(typeof group.is_test === 'boolean' && group.points.every(p => p.is_test === group.is_test), `${id}: groups must not mix test flags`);
  }
  if (expectedIds) assert(dto.messages.length === expectedIds.length && dto.messages.every(m => expectedIds.includes(m.record_id)), `${id}: scope excludes outside sources`);
  await page.evaluate(scope => sessionStorage.setItem('care-report-scope', JSON.stringify(scope)), scope);
  await page.emulateMedia({ media: 'screen' });
  const previewResponse = page.waitForResponse(res => new URL(res.url()).pathname.endsWith('/reports/preview') && res.request().method() === 'POST');
  await page.goto(`${origin}/robot-care/report`, { waitUntil: 'networkidle' });
  const previewDto = await (await previewResponse).json();
  const article = page.getByTestId('report-dto');
  await article.waitFor();
  assert(await article.getAttribute('data-data-nature') === expected && await article.getAttribute('data-is-test') === String(expected === 'test_only'), `${id}: UI flags`);
  const notice = await page.getByTestId('report-nature-notice').innerText();
  assert(notice.includes(labels[expected]), `${id}: clear source nature notice`);
  assert(!notice.includes('所有内容来自专用虚构测试数据'), `${id}: no unsupported all-fiction assertion`);
  if (expected === 'non_test_only') assert(notice.includes('不等于真实来源'), `${id}: non-test flag must not promise authenticity`);
  for (const kind of ['dialogue', 'assessments']) for (const flag of ['test', 'non_test']) {
    assert(await page.getByTestId(`nature-${kind}-${flag}`).innerText() === String(dto.data_nature_summary[kind][flag]), `${id}: visible nature source counts`);
  }
  for (const kind of ['test', 'non_test']) {
    const counters = page.getByTestId(`emotion-counts-${kind}`);
    if (await counters.count()) for (const emotion of ['positive', 'neutral', 'negative']) {
      assert(await counters.locator(`[data-emotion="${emotion}"] strong`).innerText() === String(dto.emotion_counts_by_nature[kind][emotion]), `${id}: visible split emotion counts`);
    }
  }
  if (expected === 'mixed') {
    assert(await page.getByTestId('emotion-counts-test').count() === 1 && await page.getByTestId('emotion-counts-non_test').count() === 1, `${id}: separate classification counts`);
  }
  if (singlePoints) {
    const groups = page.getByTestId('emotion-trend-group');
    assert(await groups.count() === 2, `${id}: two independent nature groups`);
    for (const g of await groups.all()) assert(await g.getAttribute('data-independent-count') === '1' && await g.locator('.care-timeline').count() === 0, `${id}: one plus one must not form a timeline`);
  }
  await page.screenshot({ path: path.join(output, `${id}.png`), fullPage: true });
  await writeFile(path.join(output, `${id}.preview.dto.json`), JSON.stringify(previewDto, null, 2), 'utf8');
  let finalDto = previewDto;
  if (pdf) {
    await page.getByRole('link', { name: '打开专用打印页' }).click();
    await page.waitForURL('**/robot-care/report/print'); await article.waitFor();
    const before = evidence.api_statuses.filter(s => s.path.endsWith('/reports/preview')).length;
    await page.evaluate(() => { window.__carePrintInvoked = false; window.print = () => { window.__carePrintInvoked = true; }; });
    const printResponse = page.waitForResponse(res => new URL(res.url()).pathname.endsWith('/reports/preview') && res.request().method() === 'POST');
    await page.getByRole('button', { name: '重新核验来源并打印 / 保存 PDF' }).click();
    finalDto = await (await printResponse).json();
    await page.waitForFunction(() => window.__carePrintInvoked === true);
    assert(await article.getAttribute('data-generated-at') === finalDto.generated_at, `${id}: PDF and exact saved DTO share generated_at`);
    assert(evidence.api_statuses.filter(s => s.path.endsWith('/reports/preview')).length > before, `${id}: print refreshes source DTO`);
    await page.emulateMedia({ media: 'print' });
    assert(!await page.getByRole('button', { name: '重新核验来源并打印 / 保存 PDF' }).isVisible(), `${id}: print controls hidden`);
    assert((await page.getByTestId('report-print-nature').innerText()).includes(labels[expected]), `${id}: accurate print stamp`);
    await documentFonts();
    await page.pdf({ path: path.join(output, `${id}.pdf`), format: 'A4', printBackground: true, preferCSSPageSize: true, displayHeaderFooter: false });
  }
  await writeFile(path.join(output, `${id}.dto.json`), JSON.stringify(finalDto, null, 2), 'utf8');
  evidence.checks.push({ id, status: 'passed', scope, ...metadata(finalDto), dto: `${id}.dto.json`, ...(pdf ? { pdf: `${id}.pdf`, generated_at: finalDto.generated_at, expected_page_footer: labels[expected] } : {}) });
  return dto;
}
async function documentFonts() { await page.evaluate(() => document.fonts.ready.then(() => true)); }

try {
  await page.goto(`${origin}/login`, { waitUntil: 'networkidle' });
  await page.locator('input[name="username"]').fill(username); await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click(); await page.waitForURL('**/robot-care');
  await page.waitForFunction(() => document.querySelector('[data-testid="anonymous-id"]')?.textContent?.startsWith('KY-'));
  // A fresh future window prevents retries from colliding with preserved evidence.
  const anchor = Date.UTC(2040, 0, 1) + Math.floor(Math.random() * 5256000) * 60000;
  const at = minutes => new Date(anchor + minutes * 60000).toISOString();
  const windowScope = minutes => ({ time_from: at(minutes - 0.1), time_to: at(minutes + 0.9) });
  const test = await seed(true, at(0));
  const nonTest = await seed(false, at(2));
  const sharedTest = await seed(true, at(4));
  const sharedNonTest = await seed(false, at(4.2));
  await checkReport('01_test_only_session', { session_ids: [test.sid] }, 'test_only', { pdf: true, expectedIds: [test.record_id] });
  await checkReport('02_non_test_only_session', { session_ids: [nonTest.sid] }, 'non_test_only', { pdf: true, expectedIds: [nonTest.record_id] });
  await checkReport('03_mixed_session', { session_ids: [sharedTest.sid, sharedNonTest.sid] }, 'mixed', { pdf: true, singlePoints: true, expectedIds: [sharedTest.record_id, sharedNonTest.record_id] });
  await checkReport('04_test_only_time', windowScope(0), 'test_only', { expectedIds: [test.record_id] });
  await checkReport('05_non_test_only_time', windowScope(2), 'non_test_only', { expectedIds: [nonTest.record_id] });
  await checkReport('06_mixed_time', windowScope(4), 'mixed', { singlePoints: true, expectedIds: [sharedTest.record_id, sharedNonTest.record_id] });
  await checkReport('07_empty_time', windowScope(10), 'empty', { pdf: true, expectedIds: [] });
  const fixtures = (await api('robot-insights/assessments')).data.items.filter(a => a.source_kind === 'fixture' && a.verification_status === 'verified_fixture' && a.completed_at);
  let fixtureScope;
  for (const fixture of fixtures) {
    const candidate = { time_from: fixture.completed_at, time_to: new Date(Date.parse(fixture.completed_at) + 1000).toISOString() };
    const result = await api('robot-insights/reports/preview', { scope: candidate });
    if (result.status === 200 && result.data.data_nature_summary.dialogue.test === 0 && result.data.data_nature_summary.dialogue.non_test === 0 && result.data.data_nature_summary.assessments.test > 0) { fixtureScope = candidate; break; }
  }
  assert(fixtureScope, 'Prepared isolated fixture time must allow an assessment-only report');
  const onlyFixture = await checkReport('08_fixture_only_time', fixtureScope, 'test_only', { pdf: true, expectedIds: [] });
  const mixedFixtureSource = await seed(false, new Date(Date.parse(fixtureScope.time_from) + 100).toISOString());
  const fixtureMixed = await checkReport('09_non_test_with_fixture_time', fixtureScope, 'mixed', { pdf: true, expectedIds: [mixedFixtureSource.record_id] });
  assert(fixtureMixed.data_nature_summary.assessments.test === onlyFixture.data_nature_summary.assessments.test && fixtureMixed.assessments.every(a => a.source_kind === 'fixture' && a.is_test === true), 'Fixture namespace and metadata must remain unchanged');
  assert(evidence.console_error_count === 0 && evidence.external_request_count === 0, 'No browser errors or external resource requests');
  evidence.status = 'passed'; evidence.finished_at = new Date().toISOString();
} catch (error) {
  evidence.status = 'failed'; evidence.failure = String(error.message); process.exitCode = 1;
  await page.emulateMedia({ media: 'screen' }).catch(() => {});
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
} finally {
  await writeFile(path.join(output, 'browser_data_nature.json'), JSON.stringify(evidence, null, 2), 'utf8');
  await browser.close();
}
console.log(JSON.stringify({ status: evidence.status, checks: evidence.checks.length, evidence_dir: output }));
