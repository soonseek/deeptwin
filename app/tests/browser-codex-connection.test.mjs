import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { localContextOptions, localGet, mintLaunchURL } from './helpers/local-session.mjs';

let browser;
test.before(async () => {
  assert.ok(process.env.CONTROL_PLAYWRIGHT_MODULE, 'CONTROL_PLAYWRIGHT_MODULE must point to bundled Playwright; no skips');
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
});
test.after(async () => { await browser?.close(); });

async function open(t, scenario, options = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-connection-ui-'));
  const args = scenario
    ? ['app/tests/fixtures/connection_server.py', '--scenario', scenario, '--data-dir', dir, '--port', '0']
    : ['app/tests/fixtures/development_server.py', '--data-dir', dir, '--port', '0'];
  const server = spawn(process.env.CONTROL_PYTHON || 'python3', args, { cwd: fileURLToPath(new URL('../../', import.meta.url)), stdio: ['ignore', 'pipe', 'pipe'] });
  t.after(async () => {
    if (server.exitCode === null) await new Promise(resolve => { server.once('exit', resolve); server.kill('SIGTERM'); });
    await rm(dir, { recursive: true, force: true });
  });
  const announced = await new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error(`Fixture server did not start: ${output}`)), 15000);
    const read = bytes => { output += bytes; const match = output.match(/DEE?PTWIN_URL=(http:\/\/127\.0\.0\.1:\d+(?:\/#bootstrap=[A-Za-z0-9_%~-]+)?)/); if (match) { clearTimeout(timer); resolve(match[1]); } };
    server.stdout.on('data', read); server.stderr.on('data', read);
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture server exited ${code}: ${output}`)); });
  });
  const url = new URL(announced).origin;
  const launchURL = announced.includes('#bootstrap=') ? announced : await mintLaunchURL(url);
  const context = await browser.newContext(localContextOptions({ baseURL: url, ...options }));
  t.after(() => context.close());
  const page = await context.newPage();
  const requests = [], errors = [], external = [];
  page.on('request', request => {
    requests.push({ method: request.method(), path: new URL(request.url()).pathname, body: request.postData() });
    if (!request.url().startsWith(url + '/')) external.push(request.url());
  });
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(launchURL);
  await page.locator('#app[data-ready="true"]').waitFor();
  return { page, context, requests, errors, external };
}

async function connections(page) {
  await page.locator('#open-connections').click();
  await page.locator('#codex-connection').waitFor();
}

test('connection controls are available without creating work or implicitly checking the account', async t => {
  // No account actions are invoked in this real-server contract test.
  const { page, requests } = await open(t);
  assert.equal(await page.locator('#open-connections').count(), 1, 'the input space needs a connection entry independent of saving');
  await connections(page);
  assert.equal(await page.getByRole('button', { name: '연결 확인', exact: true }).count(), 1);
  assert.equal(await page.getByRole('button', { name: 'ChatGPT로 로그인', exact: true }).count(), 1);
  assert.ok(['unchecked', 'unavailable'].includes(await page.locator('#codex-connection').getAttribute('data-state')), 'installation discovery is not an account check');
  const providers = (await (await localGet(page, '/api/providers')).json()).providers;
  const codex = providers.find(provider => provider.id === 'codex');
  assert.match(codex.message, /DeepTwin 인스턴스.*사전 출시 호스트 어댑터/);
  assert.match(codex.message, /웹 릴리스.*서버 소유 관리형 Codex 실행기/s);
  assert.doesNotMatch(codex.message, /이 컴퓨터|앱에 포함할 설치 안내/);
  const connectionCopy = await page.locator('#codex-connection').textContent();
  assert.match(connectionCopy, /현재 개발 미리보기.*사전 출시 호스트 어댑터/s);
  assert.match(connectionCopy, /웹 릴리스.*관리형 실행기/s);
  assert.match(connectionCopy, /브라우저 기기.*자동 공유하지/);
  assert.doesNotMatch(connectionCopy, /이 컴퓨터/);
  assert.deepEqual(await (await localGet(page, '/api/works')).json(), []);
  assert.equal(requests.filter(request => request.method === 'POST' && request.path !== '/api/session/bootstrap').length, 0);
});

test('server-confirmed ChatGPT account and remaining limits do not claim the design engine is working', async t => {
  const { page, requests, errors, external } = await open(t, 'connected');
  await connections(page);
  await page.getByRole('button', { name: '연결 확인', exact: true }).click();
  await page.locator('#codex-connection[data-state="connected"]').waitFor();
  assert.match(await page.locator('#codex-connection').textContent(), /ChatGPT.*연결|구독.*확인/);
  assert.match(await page.locator('#codex-connection').textContent(), /75%/);
  assert.match(await page.locator('#codex-connection').textContent(), /설계.*아직|실행.*미연결/);
  assert.equal(requests.filter(request => request.path.endsWith('/login')).length, 0);
  assert.equal(await page.locator('svg, .graph').count(), 0);
  assert.deepEqual(errors, []);
  assert.deepEqual(external, []);
});

test('account checks proceed while a text save is blocked and never replace literal input or its selection', async t => {
  const { page } = await open(t, 'connected');
  await connections(page);
  await page.route('**/api/works', route => route.request().method() === 'POST' ? route.abort() : route.continue());
  const literal = '\n한글 조합과 <script>입력</script> 그대로  ';
  await page.locator('#work-text').fill(literal);
  await page.locator('#save-status[data-state="error"]').waitFor();
  await page.locator('#work-text').evaluate(el => { el.focus(); el.setSelectionRange(2, 6); });
  await page.getByRole('button', { name: '연결 확인', exact: true }).click();
  await page.locator('#codex-connection[data-state="connected"]').waitFor();
  assert.equal(await page.locator('#work-text').inputValue(), literal);
  assert.deepEqual(await page.locator('#work-text').evaluate(el => [el.selectionStart, el.selectionEnd]), [2, 6]);
  assert.equal(await page.locator('#save-status').getAttribute('data-state'), 'error');
});

test('API-key account is not subscription access and login changes only after the explicit login action', async t => {
  const { page, requests } = await open(t, 'api-key');
  await connections(page);
  await page.getByRole('button', { name: '연결 확인', exact: true }).click();
  await page.locator('#codex-connection[data-state="api_key"]').waitFor();
  assert.match(await page.locator('#codex-connection').textContent(), /API.*구독|구독.*API/);
  assert.equal(requests.filter(request => request.path.endsWith('/login')).length, 0);
  await page.getByRole('button', { name: 'ChatGPT로 로그인', exact: true }).click();
  await page.locator('#codex-connection[data-login-status="pending"]').waitFor();
  assert.equal(requests.filter(request => request.path.endsWith('/login') && request.method === 'POST').length, 1);
});

test('checking the account does not wait behind an in-flight work save', async t => {
  const { page } = await open(t, 'connected');
  await connections(page);
  let release, announce;
  const gate = new Promise(resolve => { release = resolve; });
  const started = new Promise(resolve => { announce = resolve; });
  t.after(() => release());
  await page.route('**/api/works', async route => {
    if (route.request().method() === 'POST') { announce(); await gate; }
    await route.continue();
  });
  await page.locator('#work-text').fill('저장 응답을 기다리는 업무 설명');
  await started;
  await page.getByRole('button', { name: '연결 확인', exact: true }).click();
  await page.locator('#codex-connection[data-state="connected"]').waitFor();
  assert.equal(await page.locator('#save-status').getAttribute('data-state'), 'saving');
  assert.equal(await page.locator('#work-text').inputValue(), '저장 응답을 기다리는 업무 설명');
  release();
  await page.locator('#save-status[data-state="saved"]').waitFor();
});

test('reopening the connection panel during a check does not invalidate its result or leave controls busy', async t => {
  const { page } = await open(t, 'connected');
  await connections(page);
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  t.after(() => release());
  let announce;
  const started = new Promise(resolve => { announce = resolve; });
  await page.route('**/api/providers/codex/check', async route => { announce(); await gate; await route.continue(); });
  await page.getByRole('button', { name: '연결 확인', exact: true }).click();
  await started;
  await page.locator('#open-connections').click();
  release();
  await page.locator('#codex-connection[data-state="connected"]').waitFor({ timeout: 5000 });
  assert.equal(await page.getByRole('button', { name: '연결 확인', exact: true }).isEnabled(), true);
});

test('keyboard connection check returns focus to its control without repainting the input', async t => {
  const { page } = await open(t, 'connected');
  await connections(page);
  const check = page.getByRole('button', { name: '연결 확인', exact: true });
  await check.focus();
  await check.press('Enter');
  await page.locator('#codex-connection[data-state="connected"]').waitFor();
  assert.equal(await page.evaluate(() => document.activeElement.dataset.connectionAction), 'check');
});

test('a stale panel-read failure cannot replace a newer successful account-check message', async t => {
  const { page } = await open(t, 'connected');
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  t.after(() => release());
  await page.route('**/api/providers', async route => { await gate; await route.abort(); });
  await connections(page);
  await page.getByRole('button', { name: '연결 확인', exact: true }).click();
  await page.locator('#codex-connection[data-state="connected"]').waitFor();
  release();
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.equal(await page.locator('#connection-message').textContent(), '');
});

test('the official login link retains keyboard focus when pending status is polled', async t => {
  const { page } = await open(t, 'pending');
  await connections(page);
  await page.getByRole('button', { name: 'ChatGPT로 로그인', exact: true }).click();
  const link = page.getByRole('link', { name: '공식 로그인 열기', exact: true });
  await link.waitFor();
  await link.focus();
  await page.waitForResponse(response => new URL(response.url()).pathname === '/api/providers/codex');
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.equal(await page.evaluate(() => document.activeElement.textContent), '공식 로그인 열기');
});

test('explicit login presents a safe official link without a popup, can cancel, and keeps auth data out of storage', async t => {
  const { page, context, requests, external } = await open(t, 'pending');
  await connections(page);
  await page.getByRole('button', { name: 'ChatGPT로 로그인', exact: true }).click();
  await page.locator('#codex-connection[data-login-status="pending"]').waitFor();
  const link = page.getByRole('link', { name: '공식 로그인 열기', exact: true });
  assert.match(await link.getAttribute('href'), /^https:\/\/(auth\.openai\.com|chatgpt\.com)\//);
  assert.equal(await link.getAttribute('target'), '_blank');
  assert.match(await link.getAttribute('rel'), /noopener/);
  assert.match(await link.getAttribute('rel'), /noreferrer/);
  assert.equal(context.pages().length, 1, 'no automatic authentication popup');
  assert.deepEqual(await page.evaluate(() => Object.fromEntries(Object.entries(localStorage))), {});
  await page.getByRole('button', { name: '로그인 취소', exact: true }).click();
  await page.locator('#codex-connection[data-login-status="cancelled"]').waitFor();
  assert.equal(await link.count(), 0);
  assert.equal(requests.filter(request => request.path.endsWith('/login/cancel')).length, 1);
  assert.deepEqual(external, []);
});

test('pending login completion is read from the server and finished status stops polling', async t => {
  const { page, requests } = await open(t, 'complete');
  await connections(page);
  await page.getByRole('button', { name: 'ChatGPT로 로그인', exact: true }).click();
  await page.locator('#codex-connection[data-state="connected"]').waitFor();
  const count = requests.filter(request => request.path === '/api/providers/codex').length;
  await page.waitForTimeout(2300);
  assert.equal(requests.filter(request => request.path === '/api/providers/codex').length, count);
  assert.equal(await page.getByRole('link', { name: '공식 로그인 열기' }).count(), 0);
  assert.deepEqual(await page.evaluate(() => Object.fromEntries(Object.entries(localStorage))), {});
});

test('a failed login stays a failure and an unsafe auth URL is never offered as an official link', async t => {
  for (const scenario of ['failure', 'unsafe-url']) {
    const { page } = await open(t, scenario);
    await connections(page);
    await page.getByRole('button', { name: 'ChatGPT로 로그인', exact: true }).click();
    if (scenario === 'failure') await page.locator('#codex-connection[data-login-status="failed"]').waitFor();
    else await page.locator('#connection-message:not(:empty)').waitFor();
    assert.notEqual(await page.locator('#codex-connection').getAttribute('data-state'), 'connected');
    assert.equal(await page.getByRole('link', { name: '공식 로그인 열기' }).count(), 0);
  }
});

test('pending polling stops when the panel leaves the current work or page becomes hidden', async t => {
  const { page, requests } = await open(t, 'pending');
  await connections(page);
  await page.getByRole('button', { name: 'ChatGPT로 로그인', exact: true }).click();
  await page.locator('#codex-connection[data-login-status="pending"]').waitFor();
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  const hiddenCount = requests.filter(request => request.path === '/api/providers/codex').length;
  await page.waitForTimeout(2300);
  assert.equal(requests.filter(request => request.path === '/api/providers/codex').length, hiddenCount);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.locator('#new-work').click();
  const workCount = requests.filter(request => request.path === '/api/providers/codex').length;
  await page.waitForTimeout(2300);
  assert.equal(requests.filter(request => request.path === '/api/providers/codex').length, workCount);
});

test('unknown limits stay unknown and connection content fits a narrow Korean viewport', async t => {
  const { page, errors, external } = await open(t, 'unknown-limits', { viewport: { width: 390, height: 844 }, colorScheme: 'dark' });
  await connections(page);
  await page.getByRole('button', { name: '연결 확인', exact: true }).click();
  await page.locator('#codex-connection[data-state="connected"]').waitFor();
  assert.match(await page.locator('#codex-connection').textContent(), /사용량.*확인|사용량.*알 수/);
  assert.doesNotMatch(await page.locator('#codex-connection').textContent(), /남음.*0%|남음.*100%/);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(errors, []);
  assert.deepEqual(external, []);
});

test('unchanged pending login has a finite sixty-poll budget rather than an endless timer', async t => {
  const { page, requests } = await open(t, 'pending');
  await connections(page);
  await page.clock.install();
  await page.getByRole('button', { name: 'ChatGPT로 로그인', exact: true }).click();
  await page.locator('#codex-connection[data-login-status="pending"]').waitFor();
  for (let index = 0; index < 60; index++) {
    const response = page.waitForResponse(response => new URL(response.url()).pathname === '/api/providers/codex');
    await page.clock.runFor(2000);
    await response;
    // The HTTP body/DOM update is real; only the browser's two-second timer is accelerated.
    await new Promise(resolve => setTimeout(resolve, 25));
  }
  await page.waitForFunction(() => document.querySelector('#connection-message').textContent.includes('자동 확인은 멈췄습니다'));
  assert.equal(requests.filter(request => request.path === '/api/providers/codex').length, 60);
  await page.clock.runFor(20000);
  assert.equal(requests.filter(request => request.path === '/api/providers/codex').length, 60);
});
