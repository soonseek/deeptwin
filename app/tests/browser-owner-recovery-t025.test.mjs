// T025 browser case: an owner recovery end to end in real Chromium. The owner sets up
// an instance from the offline bootstrap page and holds a live browser session. The
// deployment operator then runs the owner-recovery maintenance tool
// (`python -m app.operations.deployment_control`): it refuses while the control plane runs,
// and with the control plane stopped it prepares the recovery request for a new
// one-time capability made on the same offline page. A test-only signing adapter plays
// the holder of the recovery trust set, the tool imports the signed receipt, and the
// supported server restarts from the configuration the tool rewrote. The first screen
// then says honestly what the recovery ended; the owner sets up again with the new
// capability, and the old session, the old capability and the old password no longer
// work. The raw capabilities never reach a server, tool or signer process.

import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:net';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFile, spawn } from 'node:child_process';
import { closeOwnedFixture, terminateOwnedChild, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

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

function python(args) {
  return new Promise((resolve, reject) => {
    execFile(process.env.CONTROL_PYTHON, ['-B', ...args], { cwd: root, timeout: 60000 }, (error, stdout, stderr) => {
      if (error && typeof error.code !== 'number') reject(new Error(`${error.message}\n${stderr}`));
      else resolve({ code: error ? error.code : 0, stdout, stderr });
    });
  });
}

async function offlineCapability(page, port) {
  await page.goto(pathToFileURL(join(root, 'deploy/bootstrap/index.html')).href);
  await page.getByLabel('DeepTwin 포트').fill(String(port));
  await page.getByRole('button', { name: '안전한 설정 값 만들기' }).click();
  await page.locator('#results:not([hidden])').waitFor();
  const capability = (await page.locator('#raw-capability').textContent()).trim();
  const configuration = JSON.parse(await page.locator('#configuration').textContent());
  assert.match(capability, /^[A-Za-z0-9_-]{43}$/);
  assert.equal(JSON.stringify(configuration).includes(capability), false);
  return { capability, configuration };
}

async function setUp(page, url, capability, password) {
  await page.goto(url);
  await page.getByLabel('일회용 capability').fill(capability);
  await page.getByLabel('소유자 이름').fill('owner');
  await page.getByLabel(/^비밀번호/).fill(password);
}

test('owner recovery: maintenance tool → restart → honest first screen → re-setup; old authority ends',
  { timeout: 180000 }, async t => {
    assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
    const dir = await mkdtemp(join(tmpdir(), 'deeptwin-owner-recovery-'));
    const owned = join(dir, 'owned');
    const signerState = join(dir, 'signer');
    let server, browser;
    t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
      { serverGraceMs: 5000, serverForceMs: 2000, label: 'Owner recovery fixture' }));
    const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
    browser = await chromium.launch({ channel: 'chrome', headless: true });
    let context = await browser.newContext({ viewport: { width: 1100, height: 900 } });
    let page = await context.newPage();
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    // 1. the instance as the owner set it up: offline block, supported server, first screen
    const port = await freePort();
    const first = await offlineCapability(page, port);
    await mkdir(owned);
    await mkdir(signerState);
    const configPath = join(dir, 'configuration.json');
    await writeFile(configPath, JSON.stringify(first.configuration));
    server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/owner_lifecycle_server.py', '--owned-dir', owned,
      '--configuration', configPath], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
    const url = (await waitForOwnedChildOutput(server, { pattern: /OWNER_LIFECYCLE_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/,
      timeoutMs: 30000, label: 'Owner lifecycle fixture' })).split('=')[1];
    await setUp(page, url, first.capability, OLD);
    await page.getByRole('button', { name: '최초 소유자 설정' }).click();
    await page.waitForURL(/work\.html$/);
    let snapshot = () => page.evaluate(async base => (await fetch(base + 'api/v1/snapshot')).status, url);
    assert.equal(await snapshot(), 200);

    // 2. the maintenance tool refuses while the control plane runs
    const common = ['--data-dir', join(owned, 'data'), '--session-root-dir', join(owned, 'root'),
      '--deployment-config', configPath, '--work-dir', join(dir, 'work'),
      '--expected-uid', String(process.getuid()), '--expected-gid', String(process.getgid())];
    const tool = async (...args) => {
      const { code, stdout } = await python(['-m', 'app.operations.deployment_control', ...args]);
      return { code, result: JSON.parse(stdout) };
    };
    const second = await offlineCapability(await context.newPage(), port);
    const verifier = second.configuration.verifier_b64u;
    assert.notEqual(verifier, first.configuration.verifier_b64u);
    assert.deepEqual(await tool('prepare', ...common, '--new-verifier', verifier),
      { code: 2, result: { state: 'refused', code: 'busy' } });

    // 3. the control plane stops; the operator prepares, the trust set holder signs, the tool imports
    // the owner's browser keeps its session cookie across the restart, but not its
    // connections (a half-closed keep-alive socket would hold the fixed port)
    const kept = await context.storageState();
    assert.equal(kept.cookies.filter(cookie => cookie.name === 'deeptwin_session').length, 1);
    await context.close();
    await terminateOwnedChild(server, { graceMs: 5000, forceMs: 2000, label: 'Owner lifecycle fixture' });
    server = undefined;
    const prepared = await tool('prepare', ...common, '--new-verifier', verifier);
    assert.equal(prepared.code, 0);
    assert.equal(prepared.result.state, 'prepared');
    assert.equal(prepared.result.target_epoch, 2);
    const request = await readFile(prepared.result.request_path, 'utf8');
    assert.equal(request.includes(first.capability) || request.includes(second.capability) || request.includes(verifier), false);
    const signer = ['app/tests/fixtures/recovery_signer.py', '--state-dir', signerState, '--configuration', configPath];
    assert.equal((await python([...signer.slice(0, 1), 'keygen', ...signer.slice(1)])).code, 0);
    const receipt = join(dir, 'receipt.json');
    assert.equal((await python([...signer.slice(0, 1), 'sign', ...signer.slice(1), '--request', prepared.result.request_path,
      '--new-verifier', verifier, '--receipt', receipt])).code, 0);
    const trust = join(signerState, 'trust.json');
    const imported = await tool('import', ...common, '--receipt', receipt, '--trust-set', trust);
    assert.equal(imported.code, 0, JSON.stringify(imported.result));
    assert.equal(imported.result.state, 'imported');
    assert.equal(imported.result.recovery_epoch, 2);
    const rewritten = JSON.parse(await readFile(configPath, 'utf8'));
    assert.equal(rewritten.recovery_epoch, 2);
    assert.equal(rewritten.verifier_b64u, verifier);
    assert.equal(JSON.stringify(rewritten).includes(second.capability), false);

    // 4. the supported server restarts from the rewritten configuration and reconciles
    server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/owner_recovery_server.py', '--owned-dir', owned,
      '--configuration', configPath, '--recovery-trust-set', trust], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
    const recoveredUrl = (await waitForOwnedChildOutput(server, { pattern: /OWNER_RECOVERY_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/,
      timeoutMs: 30000, label: 'Owner recovery fixture' })).split('=')[1];
    assert.equal(recoveredUrl, url);  // the same instance and origin
    context = await browser.newContext({ viewport: { width: 1100, height: 900 }, storageState: kept });
    page = await context.newPage();
    page.setDefaultTimeout(10000);
    page.on('pageerror', error => errors.push(error.message));
    snapshot = () => page.evaluate(async base => (await fetch(base + 'api/v1/snapshot')).status, url);
    await page.goto(url + 'health');
    // the old browser session no longer works
    assert.equal(await snapshot(), 401);

    // 5. the first screen: the honest recovered state and the re-setup with the new capability
    await page.goto(url);
    const status = page.locator('#start-status');
    await page.getByRole('button', { name: '소유자 다시 설정' }).waitFor();
    assert.equal(await status.getAttribute('data-state'), 'recovered');
    const text = await status.textContent();
    for (const pattern of [/소유자 복구/, /세션·비밀번호·capability/, /운영자가 새로 만든 일회용 capability/, /이전 기록은 그대로/]) {
      assert.match(text, pattern);
    }
    assert.equal(await page.locator('#login-form').isHidden(), true);
    // the old capability is refused
    await setUp(page, url, first.capability, NEW);
    await page.getByRole('button', { name: '소유자 다시 설정' }).click();
    await page.locator('#start-status[data-state="credentials"]').waitFor();
    // the new capability sets the owner up again
    await setUp(page, url, second.capability, NEW);
    await page.getByRole('button', { name: '소유자 다시 설정' }).click();
    await page.waitForURL(/work\.html$/);
    assert.equal(await snapshot(), 200);

    // 6. the old password no longer logs in, the new one does; the tool's status shows all three at epoch 2
    const other = await (await browser.newContext()).newPage();
    await other.goto(url);
    await other.getByRole('button', { name: '로그인' }).waitFor();
    const logins = await other.evaluate(async ({ base, OLD, NEW }) => {
      const login = password => fetch(base + 'session/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ login_name: 'owner', password }) }).then(response => response.status);
      return [await login(OLD), await login(NEW)];
    }, { base: url, OLD, NEW });
    assert.deepEqual(logins, [401, 200]);
    await terminateOwnedChild(server, { graceMs: 5000, forceMs: 2000, label: 'Owner recovery fixture' });
    server = undefined;
    const status2 = await tool('status', ...common);
    assert.deepEqual([status2.result.configuration_epoch, status2.result.root_epoch, status2.result.database_epoch], [2, 2, 2]);
    assert.deepEqual(errors, []);
  });
