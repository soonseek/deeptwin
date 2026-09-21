import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, mkdir, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const evidence = join(root, '.superpowers/sdd/resumption-plan/task-29-screenshots');
const base = `/${'2'.repeat(32)}/`;
const key = `deeptwin:intake:${base}`;

async function open(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-owner-material-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Owner material fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/owner_material_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false', DD_TRACE_ENABLED: 'false' } });
  const url = await waitForOwnedChildOutput(server, { pattern: /http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\//, timeoutMs: 15000, label: 'Owner material fixture' });
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1024, height: 1000 }, acceptDownloads: true });
  const page = await context.newPage();
  page.setDefaultTimeout(7000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  const status = await page.evaluate(async ({ base, capability }) => (await fetch(base + 'session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase', raw_capability_b64u: capability }),
  })).status, { base, capability: Buffer.alloc(32, 'T').toString('base64url') });
  assert.equal(status, 201);
  await page.goto(url + 'work.html');
  await page.locator('#work-form:not([hidden])').waitFor();
  return { page, context, url, errors, server };
}

async function saved(page, revision) {
  await page.waitForFunction(n => document.querySelector('#save-status')?.textContent.includes(`수정본 ${n}`)
    && !document.querySelector('#save-status')?.textContent.includes('저장하는 중'), revision);
}

test('actual owner file-first originals survive download/reload with keyboard and six layouts', { timeout: 60000 }, async t => {
  const { page, errors } = await open(t);
  await page.getByRole('button', { name: '자료 추가', exact: true }).focus();
  const chooserPromise = page.waitForEvent('filechooser');
  await page.keyboard.press('Enter');
  const chooser = await chooserPromise;
  const bytes = Buffer.from('%PDF-1.7\n원본 <script>never execute</script>\0');
  await chooser.setFiles({ name: '검토할 원본.pdf', mimeType: 'application/pdf', buffer: bytes });
  await page.getByRole('button', { name: '이 인스턴스에 저장', exact: true }).click();
  await saved(page, 2);
  assert.equal(await page.locator('textarea').inputValue(), '');
  assert.equal(await page.getByText('원본 보관됨', { exact: true }).count(), 1);
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', { name: '다운로드' }).click();
  const download = await downloadPromise;
  assert.equal(download.suggestedFilename(), '검토할 원본.pdf');
  assert.deepEqual(await readFile(await download.path()), bytes);
  await page.locator('textarea').fill('이 자료를 검토할 업무 설명');
  await page.getByRole('button', { name: '이 인스턴스에 저장', exact: true }).click();
  await saved(page, 3);
  await page.reload();
  await saved(page, 3);
  assert.equal(await page.locator('textarea').inputValue(), '이 자료를 검토할 업무 설명');
  assert.equal(await page.getByText('원본 보관됨', { exact: true }).count(), 1);
  await mkdir(evidence, { recursive: true });
  for (const width of [360, 1024, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const colorScheme of ['light', 'dark']) {
      await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' });
      await page.getByRole('button', { name: '자료 추가', exact: true }).focus();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(await page.evaluate(() => document.activeElement.textContent), '자료 추가');
      const layout = await page.evaluate(() => {
        const box = selector => document.querySelector(selector).getBoundingClientRect();
        return { lefts: ['h1', '#session-status', '#intake-notice', '#work-form', '#materials'].map(selector => box(selector).left),
          addTop: box('.original-toolbar button').top, textTop: box('textarea').top };
      });
      assert.ok(layout.lefts.every(left => Math.abs(left - layout.lefts[0]) < 1), 'one aligned work container');
      assert.ok(layout.addTop < layout.textTop && layout.addTop < 640, 'file-first action appears above input and within first screen');
      await page.screenshot({ path: join(evidence, `${width}-${colorScheme}.png`), fullPage: true });
    }
  }
  assert.deepEqual(errors, []);
});

test('actual delayed upload cancellation keeps newer draft and recovers receipt after reload', { timeout: 45000 }, async t => {
  const { page, errors, server } = await open(t);
  const started = waitForOwnedChildOutput(server, { pattern: /OWNER_UPLOAD_STARTED=[0-9a-f-]{36}/,
    timeoutMs: 7000, label: 'Actual delayed publication' });
  await page.getByLabel('원본 자료 선택').setInputFiles({ name: 'slow-original.txt', mimeType: 'text/plain', buffer: Buffer.from('original') });
  await page.getByRole('button', { name: '이 인스턴스에 저장', exact: true }).click();
  await page.getByText('받는 중', { exact: true }).waitFor();
  await started;
  await page.locator('textarea').fill('전송 중에 쓴 새 초안');
  await page.getByRole('button', { name: '전송 중지', exact: true }).click();
  await page.waitForFunction(key => !!JSON.parse(localStorage.getItem(key)).pending_command, key);
  const pending = await page.evaluate(key => JSON.parse(localStorage.getItem(key)).pending_command, key);
  assert.equal(pending.operation, 'upload');
  // Finite polling only for the actual local server's receipt, never fake success.
  let confirmed;
  for (let attempt = 0; attempt < 50; attempt++) {
    confirmed = await page.evaluate(async ({ base, id }) => (await fetch(`${base}api/v1/works/commands/${id}`)).json(),
      { base, id: pending.payload.command_id });
    if (confirmed.revision === 2) break;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  assert.equal(confirmed.revision, 2, JSON.stringify(confirmed));
  await page.reload();
  try {
    await page.getByText('원본 보관됨', { exact: true }).waitFor();
  } catch (error) {
    throw new Error(`${error.message}; page=${await page.locator('body').innerText()}; draft=${await page.evaluate(key => localStorage.getItem(key), key)}; errors=${errors.join('|')}`);
  }
  assert.equal(await page.locator('textarea').inputValue(), '전송 중에 쓴 새 초안');
  const state = await page.evaluate(key => JSON.parse(localStorage.getItem(key)), key);
  assert.equal(state.pending_command, undefined);
  assert.equal(state.revision, 2);
  assert.equal(state.draft_text, '전송 중에 쓴 새 초안');
  assert.deepEqual(errors, []);
});

test('lost actual empty-create response recovers exact receipt without a second draft', { timeout: 45000 }, async t => {
  const { page } = await open(t);
  let lost = false;
  await page.route('**/api/v1/works', async route => {
    if (route.request().method() !== 'POST' || lost) return route.continue();
    lost = true;
    const originalUrl = new URL(route.request().url());
    const target = new URL(originalUrl); target.hostname = '127.0.0.1';
    const response = await route.fetch({ url: target.href, headers: { ...await route.request().allHeaders(),
      host: originalUrl.host, origin: originalUrl.origin, 'sec-fetch-site': 'same-origin' } });
    assert.equal(response.status(), 201);
    await route.abort('connectionfailed');
  });
  await page.getByLabel('원본 자료 선택').setInputFiles({ name: 'first.txt', mimeType: 'text/plain', buffer: Buffer.from('first') });
  await page.getByRole('button', { name: '이 인스턴스에 저장', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#save-status').dataset.state === 'unavailable');
  const pending = await page.evaluate(key => JSON.parse(localStorage.getItem(key)).pending_command, key);
  assert.equal(pending.payload.schema_version, 'work-create-command-v2');
  assert.equal(pending.payload.text, '');
  await page.unroute('**/api/v1/works');
  await page.reload();
  await saved(page, 1);
  const state = await page.evaluate(key => JSON.parse(localStorage.getItem(key)), key);
  assert.equal(state.pending_command, undefined);
  const receipt = await page.evaluate(async ({ base, id }) => (await fetch(`${base}api/v1/works/commands/${id}`)).json(),
    { base, id: pending.payload.command_id });
  assert.equal(state.work_id, receipt.work_id);
  assert.equal(state.revision, 1);
});
