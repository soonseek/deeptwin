// T025 browser case: the owner's whole account lifecycle in real Chromium. The offline
// bootstrap page (file://, no network) generates the one-time capability and the
// non-secret deployment block; the real supported server is started from that block
// alone; the owner types the capability into the first screen, sets up, changes their
// password on the settings page (계정과 세션), and ends another browser's session. The raw
// capability is never passed to the server process, and no password is echoed.

import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:net';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const OLD = 'synthetic owner passphrase one';
const NEW = 'synthetic owner passphrase two';

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => { const { port } = server.address(); server.close(() => resolve(port)); });
  });
}

test('offline bootstrap → first-owner setup → password change → revoke others', { timeout: 120000 }, async t => {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-owner-lifecycle-'));
  const owned = join(dir, 'owned');
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Owner lifecycle fixture' }));
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1100, height: 900 } });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));

  // 1. the offline helper, as the operator would open it: no network
  const requests = [];
  page.on('request', request => { if (!request.url().startsWith('file:')) requests.push(request.url()); });
  await page.goto(pathToFileURL(join(root, 'deploy/bootstrap/index.html')).href);
  const port = await freePort();
  await page.getByLabel('DeepTwin 포트').fill(String(port));
  await page.getByRole('button', { name: '안전한 설정 값 만들기' }).click();
  await page.locator('#results:not([hidden])').waitFor();
  const capability = (await page.locator('#raw-capability').textContent()).trim();
  const configuration = JSON.parse(await page.locator('#configuration').textContent());
  assert.match(capability, /^[A-Za-z0-9_-]{43}$/);
  assert.equal(JSON.stringify(configuration).includes(capability), false);  // the block carries no secret
  assert.deepEqual(requests, []);
  page.removeAllListeners('request');

  // 2. the server starts from the non-secret block alone
  await (await import('node:fs/promises')).mkdir(owned);
  const configPath = join(dir, 'configuration.json');
  await writeFile(configPath, JSON.stringify(configuration));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/owner_lifecycle_server.py', '--owned-dir', owned,
    '--configuration', configPath], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  const announced = await waitForOwnedChildOutput(server, { pattern: /OWNER_LIFECYCLE_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/, timeoutMs: 30000, label: 'Owner lifecycle fixture' });
  const url = announced.split('=')[1];

  // 3. the first screen: the owner types the capability and chooses a password
  await page.goto(url);
  await page.getByLabel('일회용 capability').fill(capability);
  await page.getByLabel('소유자 이름').fill('owner');
  await page.getByLabel(/^비밀번호/).fill(OLD);
  await page.getByRole('button', { name: '최초 소유자 설정' }).click();
  await page.waitForURL(/work\.html$/);

  // a second browser logs in with the same password
  const second = await browser.newContext();
  const other = await second.newPage();
  await other.goto(url);
  await other.getByLabel('소유자 이름').fill('owner');
  await other.getByLabel('비밀번호').fill(OLD);
  await other.getByRole('button', { name: '로그인' }).click();
  await other.waitForURL(/work\.html$/);

  // 4. the settings page's account panel: end the other session, then change the password
  await page.goto(url + 'settings.html#settings-account');
  await page.getByRole('button', { name: '다른 세션 모두 끝내기' }).click();
  await page.getByText('다른 세션 1개를 끝냈습니다.').waitFor();
  const otherStatus = await other.evaluate(async base => (await fetch(base + 'api/v1/snapshot')).status, url);
  assert.equal(otherStatus, 401);
  await page.getByLabel('지금 비밀번호').fill(OLD);
  await page.getByLabel('새 비밀번호 (15자 이상)').fill(NEW);
  await page.getByLabel('새 비밀번호 확인').fill(NEW);
  await page.getByRole('button', { name: '비밀번호 바꾸기' }).click();
  await page.getByText('비밀번호를 바꿨습니다.', { exact: false }).waitFor();
  assert.equal(await page.getByLabel('지금 비밀번호').inputValue(), '');  // nothing kept in the form
  // this browser continues on its rotated session: the next command carries the adopted CSRF
  await page.getByRole('button', { name: '다른 세션 모두 끝내기' }).click();
  await page.getByText('끝낼 다른 세션이 없습니다.').waitFor();
  // the old password no longer logs in; the new one does
  const logins = await other.evaluate(async ({ base, OLD, NEW }) => {
    const login = password => fetch(base + 'session/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login_name: 'owner', password }) }).then(response => response.status);
    return [await login(OLD), await login(NEW)];
  }, { base: url, OLD, NEW });
  assert.deepEqual(logins, [401, 200]);
  assert.deepEqual(errors, []);
});
