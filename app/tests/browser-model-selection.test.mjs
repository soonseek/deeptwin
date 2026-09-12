import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, readFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { openModelSettings, saveModelSelection } from './helpers/model-selection.mjs';
import { localContextOptions, localGet, mintLaunchURL } from './helpers/local-session.mjs';

let browser;
const root = fileURLToPath(new URL('../../', import.meta.url));
test.before(async () => {
  assert.ok(process.env.CONTROL_PLAYWRIGHT_MODULE, 'Bundled Playwright is required; no skipped browser cases');
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
});
test.after(async () => browser?.close());

async function open(t, { ready = false, width = 1024, colorScheme = 'light' } = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-model-selection-'));
  const args = ['app/tests/fixtures/understanding_server.py', '--data-dir', dir, '--port', '0'];
  if (!ready) args.push('--not-ready');
  const server = spawn(process.env.CONTROL_PYTHON || 'python3', args, { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  t.after(async () => {
    if (server.exitCode === null) await new Promise(resolve => { server.once('exit', resolve); server.kill('SIGTERM'); });
    await rm(dir, { recursive: true, force: true });
  });
  const url = await new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error(`Fixture not ready: ${output}`)), 15000);
    const read = bytes => { output += bytes; const match = output.match(/http:\/\/127\.0\.0\.1:\d+/); if (match) { clearTimeout(timer); resolve(match[0]); } };
    server.stdout.on('data', read); server.stderr.on('data', read);
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${output}`)); });
  });
  const context = await browser.newContext(localContextOptions({ baseURL: url, viewport: { width, height: 900 }, colorScheme }));
  t.after(() => context.close());
  const page = await context.newPage();
  const requests = [], errors = [], external = [];
  page.on('request', request => {
    requests.push({ method: request.method(), path: new URL(request.url()).pathname, body: request.postData() });
    if (!request.url().startsWith(url + '/')) external.push(request.url());
  });
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(await mintLaunchURL(url)); await page.locator('#app[data-ready="true"]').waitFor();
  page.setDefaultTimeout(6000);
  return { page, context, url, requests, errors, external, calls: async () => {
    try { return (await readFile(join(dir, 'model-calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse); }
    catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  } };
}

async function save(page, text) {
  await page.locator('#work-text').fill(text);
  await page.locator('#save-status[data-state="saved"]').waitFor();
  const id = await page.locator('#app').getAttribute('data-work-id');
  return (await localGet(page, `/api/works/${id}`)).json();
}
async function selected(page) {
  const id = await page.locator('#app').getAttribute('data-work-id');
  return (await localGet(page, `/api/works/${id}/model-selection`)).json();
}

test('model settings query only on explicit refresh and save a literal first work without sending it to a model', async t => {
  const { page, requests, calls, errors, external } = await open(t);
  assert.equal(await page.locator('#model-settings').count(), 1);
  assert.equal(await page.locator('#model-settings').evaluate(el => el.open), false);
  await openModelSettings(page);
  assert.equal(requests.filter(item => item.method === 'POST' && item.path !== '/api/session/bootstrap').length, 0);
  assert.deepEqual(await (await localGet(page, '/api/works')).json(), []);
  await page.locator('#refresh-model-catalog').click();
  await page.locator('#model-settings[data-catalog-status="ready"]').waitFor();
  assert.equal(await page.locator('#save-model-selection').isDisabled(), true, 'model browsing alone creates no blank work');
  const literal = '\n  처음 선택하는 업무 <script>그대로</script>  ';
  await page.locator('#work-text').fill(literal);
  await page.locator('#model-choice').selectOption('gpt-fixture-deep');
  assert.deepEqual(await page.locator('#model-effort option').evaluateAll(items => items.map(item => item.value)), ['high']);
  await page.locator('#save-model-selection').click();
  await page.locator('#model-selection-status[data-state="saved"]').waitFor();
  const selection = await selected(page);
  assert.equal(selection.version, 1);
  assert.equal(selection.selection.model, 'gpt-fixture-deep');
  assert.equal(selection.selection.effort, 'high');
  assert.equal(selection.selection.mode, 'subscription');
  assert.equal(await page.locator('#work-text').inputValue(), literal);
  assert.equal(await page.locator('#prepare-design').isDisabled(), true, 'saved model selection does not lift the actual isolation gate');
  assert.match(await page.locator('#understanding-readiness').textContent(), /Codex ChatGPT 구독.*저장.*실행 연결.*준비되지.*보내지/s);
  assert.match(await page.locator('#model-billing-note').textContent(), /ChatGPT 구독.*API.*자동 전환|구독.*API 사용 금액/);
  assert.doesNotMatch(await page.locator('#model-billing-note').textContent(), /무료/);
  assert.equal(requests.filter(item => /\/providers\/.*\/(login|check)/.test(item.path)).length, 0);
  assert.deepEqual(await calls(), []); assert.deepEqual(errors, []); assert.deepEqual(external, []);
});

test('work-specific model versions restore across work switching and reload without changing input revisions', async t => {
  const { page } = await open(t);
  const first = await save(page, '첫 업무'); await saveModelSelection(page, 'gpt-fixture', 'low');
  assert.equal((await (await localGet(page, `/api/works/${first.id}`)).json()).revision, first.revision);
  await page.locator('#new-work').click();
  const second = await save(page, '두 번째 업무'); await saveModelSelection(page, 'gpt-fixture-deep', 'high');
  await page.locator('#work-select').selectOption(first.id);
  await page.locator('#model-selection-status[data-state="saved"]').waitFor();
  await openModelSettings(page);
  assert.equal(await page.locator('#model-connection').inputValue(), 'codex:subscription');
  assert.equal(await page.locator('#model-choice').inputValue(), 'gpt-fixture');
  assert.equal(await page.locator('#model-effort').inputValue(), 'low');
  assert.equal((await selected(page)).version, 1);
  await page.reload(); await page.locator('#app[data-ready="true"]').waitFor(); await openModelSettings(page);
  assert.equal(await page.locator('#model-connection').inputValue(), 'codex:subscription');
  assert.equal(await page.locator('#model-effort').inputValue(), 'low');
  assert.equal((await (await localGet(page, `/api/works/${second.id}/model-selection`)).json()).selection.model, 'gpt-fixture-deep');
});

test('work switch clears the previous saved marker before the selected model read completes', async t => {
  const { page } = await open(t);
  const first = await save(page, '첫 업무'); await saveModelSelection(page, 'gpt-fixture', 'low');
  await page.locator('#new-work').click();
  await save(page, '두 번째 업무'); await saveModelSelection(page, 'gpt-fixture-deep', 'high');

  let releaseRead;
  const gate = new Promise(resolve => { releaseRead = resolve; });
  t.after(() => releaseRead());
  let observeRead;
  const requested = new Promise(resolve => { observeRead = resolve; });
  await page.route(`**/api/works/${first.id}/model-selection`, async route => {
    observeRead();
    await gate;
    await route.continue();
  }, { times: 1 });

  await page.locator('#work-select').selectOption(first.id);
  await requested;
  assert.equal(await page.locator('#model-selection-status').getAttribute('data-state'), 'loading');
  assert.equal(await page.locator('#save-model-selection').isDisabled(), true);
  releaseRead();
  await page.locator('#model-selection-status[data-state="saved"]').waitFor();
  assert.equal(await page.locator('#model-choice').inputValue(), 'gpt-fixture');
  assert.equal(await page.locator('#model-effort').inputValue(), 'low');
});

test('selection save failure retains both the work input and the unsaved choice without claiming success', async t => {
  const { page } = await open(t);
  const work = await save(page, '실패해도 남길 원 입력'); await saveModelSelection(page);
  await page.route(`**/api/works/${work.id}/model-selection`, route => route.request().method() === 'PUT' ? route.abort() : route.continue());
  await page.locator('#model-choice').selectOption('gpt-fixture-deep');
  await page.locator('#save-model-selection').click();
  await page.locator('#model-selection-status[data-state="error"]').waitFor();
  assert.equal(await page.locator('#model-choice').inputValue(), 'gpt-fixture-deep');
  assert.equal(await page.locator('#work-text').inputValue(), work.text);
  assert.equal((await selected(page)).selection.model, 'gpt-fixture');
});

test('a model-setting version conflict preserves the local choice and explicitly reloads the other saved choice', async t => {
  const { page, context, url } = await open(t);
  const work = await save(page, '모델 설정을 따로 저장하는 업무'); await saveModelSelection(page);
  const other = await context.newPage();
  await other.goto(url); await other.locator('#app[data-ready="true"]').waitFor(); await openModelSettings(other);
  await other.locator('#model-choice').selectOption('gpt-fixture-deep');
  await other.locator('#save-model-selection').click();
  await other.locator('#model-selection-status[data-state="saved"]').waitFor();
  await page.locator('#model-effort').selectOption('low');
  await page.locator('#save-model-selection').click();
  await page.locator('#model-selection-status[data-state="error"]').waitFor();
  assert.equal(await page.locator('#model-effort').inputValue(), 'low');
  assert.equal(await page.locator('#work-text').inputValue(), work.text);
  assert.equal((await selected(page)).selection.model, 'gpt-fixture-deep');
  assert.match(await page.locator('#model-selection-status').textContent(), /다른 화면.*모델/);
  await page.locator('#reload-model-selection').click();
  await page.locator('#model-selection-status[data-state="saved"]').waitFor();
  assert.equal(await page.locator('#model-choice').inputValue(), 'gpt-fixture-deep');
  assert.equal((await (await localGet(page, `/api/works/${work.id}`)).json()).revision, work.revision);
});

test('Claude unavailability and catalog failure do not fabricate choices or erase a saved model', async t => {
  const { page, requests } = await open(t);
  await save(page, '지원 경계 확인'); await saveModelSelection(page);
  await page.locator('#model-connection').selectOption('claude:api');
  await page.locator('#refresh-model-catalog').click();
  await page.locator('#model-settings[data-catalog-status="unavailable"]').waitFor();
  assert.equal(await page.locator('#model-choice option[value]:not([value=""])').count(), 0);
  assert.equal(await page.locator('#save-model-selection').isDisabled(), true);
  assert.match(await page.locator('#model-catalog-message').textContent(), /Claude|구독|지원|목록/);
  assert.equal((await selected(page)).selection.provider, 'codex');
  await page.locator('#model-connection').selectOption('codex:subscription');
  await page.route('**/api/model-catalogs/codex/refresh?mode=subscription', route => route.abort());
  await page.locator('#refresh-model-catalog').click();
  await page.locator('#model-settings[data-catalog-status="error"]').waitFor();
  assert.equal((await selected(page)).selection.model, 'gpt-fixture');
  assert.equal(requests.filter(item => item.method === 'POST' && item.path.includes('/providers/')).length, 0);
});

test('understanding carries the exact model-selection version and a model-only change marks its old result', async t => {
  const { page, requests } = await open(t, { ready: true });
  const work = await save(page, 'PDF로 정리할 업무');
  assert.equal(await page.locator('#prepare-design').isDisabled(), true, 'a working test engine still requires explicit model selection');
  await saveModelSelection(page);
  const old = await selected(page);
  await page.locator('#prepare-design').click();
  await page.locator('#understanding-record[data-status="succeeded"]').waitFor();
  const request = requests.find(item => item.method === 'POST' && item.path.endsWith('/understanding-requests'));
  assert.equal(JSON.parse(request.body).model_selection_version, old.version);
  await saveModelSelection(page, 'gpt-fixture-deep', 'high');
  assert.equal((await (await localGet(page, `/api/works/${work.id}`)).json()).revision, work.revision);
  assert.equal(await page.locator('#understanding-record').getAttribute('data-stale'), 'true');
  assert.match(await page.locator('#understanding-revision').textContent(), /모델.*달라|모델.*이전|모델.*바뀌/);
});

test('the saved model and supported effort fit narrow and desktop layouts in both color schemes', async t => {
  const out = join(root, 'app/review-output'); await mkdir(out, { recursive: true });
  for (const width of [390, 1024]) for (const colorScheme of ['light', 'dark']) {
    const { page, errors, external } = await open(t, { width, colorScheme });
    await save(page, '이 업무에서 사용할 모델을 선택합니다.'); await saveModelSelection(page, 'gpt-fixture-deep', 'high');
    await page.locator('#model-settings').scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    await page.screenshot({ path: join(out, `model-selection-${width}-${colorScheme}.png`) });
  }
});
