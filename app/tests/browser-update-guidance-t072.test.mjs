// T072 browser case: the web-release update guidance, read only, in real Chromium. The
// owner sets up an instance from the offline bootstrap page and opens the records page:
// no update is pending and no release is recorded. The deployment operator then stops
// the control plane and runs the update tool (`python -m app.operations.updates`): it
// refuses while the server runs, prepares an exact request for a target web-release
// manifest and its image-lock set, and refuses the gate backup because no backup worker
// answers its handshake (a safe state: nothing changed). The server restarts over the
// same instance and the records page shows what is true: the pending request with its
// exact target, manifest and image-lock digests and epoch, that a verified backup is
// required and absent, the last refusal naming the missing component, and the operator's
// next steps. The section is read only: no button, form or file input, and a POST to its
// route is refused. The owner is a scripted test actor: synthetic evidence of the
// mechanism, never user evidence. No image is pulled and nothing is installed.

import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:net';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFile, spawn } from 'node:child_process';
import { closeOwnedFixture, terminateOwnedChild, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const PASSWORD = 'synthetic owner passphrase for updates';
const URL_PATTERN = /UPDATE_GUIDANCE_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;

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

// the target release inputs as the operator receives them: canonical JSON bytes
const RELEASE_INPUTS = `
import hashlib, sys
from app.domain.refs import canonical_json
from app.domain import store
lock = canonical_json({"schema": "deeptwin-image-lock-set-v1", "release_id": "1.1.0",
    "services": {"backup": "sha256:" + "b" * 64, "control": "sha256:" + "c" * 64}})
manifest = canonical_json({"schema": "deeptwin-web-release-manifest-v1", "release_id": "1.1.0",
    "image_lock_set_sha256": hashlib.sha256(lock).hexdigest(),
    "data_schema": {"domain": [[1, store.MIGRATION_SHA256], [2, store.MIGRATION_2_SHA256]]},
    "components": [{"component_id": "backup-crypto", "protocol": "deeptwin-backup-crypto-request-v1"}]})
open(sys.argv[1], "wb").write(manifest)
open(sys.argv[2], "wb").write(lock)
print(hashlib.sha256(manifest).hexdigest(), hashlib.sha256(lock).hexdigest())
`;

test('update guidance: operator tool prepares while stopped; the records page shows it read only',
  { timeout: 180000 }, async t => {
    assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
    const dir = await mkdtemp(join(tmpdir(), 'deeptwin-update-guidance-'));
    const owned = join(dir, 'owned');
    const operator = join(dir, 'operator');
    let server, browser;
    t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
      { serverGraceMs: 5000, serverForceMs: 2000, label: 'Update guidance fixture' }));
    const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
    browser = await chromium.launch({ channel: 'chrome', headless: true });
    let context = await browser.newContext({ viewport: { width: 1100, height: 900 } });
    let page = await context.newPage();
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    // 1. the instance as the owner set it up, and the records page before any update
    const port = await freePort();
    await page.goto(pathToFileURL(join(root, 'deploy/bootstrap/index.html')).href);
    await page.getByLabel('DeepTwin 포트').fill(String(port));
    await page.getByRole('button', { name: '안전한 설정 값 만들기' }).click();
    await page.locator('#results:not([hidden])').waitFor();
    const capability = (await page.locator('#raw-capability').textContent()).trim();
    const configuration = JSON.parse(await page.locator('#configuration').textContent());
    await mkdir(owned);
    await mkdir(operator, { mode: 0o700 });
    const configPath = join(operator, 'configuration.json');
    await writeFile(configPath, JSON.stringify(configuration), { mode: 0o600 });
    const start = async () => {
      server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/update_guidance_server.py', '--owned-dir', owned,
        '--configuration', configPath], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
      return (await waitForOwnedChildOutput(server, { pattern: URL_PATTERN, timeoutMs: 30000,
        label: 'Update guidance fixture' })).split('=')[1];
    };
    const url = await start();
    await page.goto(url);
    await page.getByLabel('일회용 capability').fill(capability);
    await page.getByLabel('소유자 이름').fill('owner');
    await page.getByLabel(/^비밀번호/).fill(PASSWORD);
    await page.getByRole('button', { name: '최초 소유자 설정' }).click();
    await page.waitForURL(/work\.html$/);
    await page.goto(url + 'records.html');
    const section = page.locator('#records-update');
    await section.locator('.update-request[data-state="none"]').waitFor();
    assert.match(await section.textContent(), /기록된 릴리스가 없습니다/);
    assert.match(await section.textContent(), /진행 중인 업데이트 요청이 없습니다/);

    // 2. the operator tool refuses while the control plane runs
    const common = ['--data-dir', join(owned, 'data'), '--session-root-dir', join(owned, 'root'),
      '--deployment-config', configPath, '--work-dir', join(dir, 'work'),
      '--expected-uid', String(process.getuid()), '--expected-gid', String(process.getgid())];
    const tool = async (...args) => {
      const { code, stdout, stderr } = await python(['-m', 'app.operations.updates', ...args]);
      assert.ok(stdout, stderr);
      return { code, result: JSON.parse(stdout) };
    };
    const manifestPath = join(operator, 'manifest.json');
    const lockPath = join(operator, 'image-lock.json');
    const made = await python(['-c', RELEASE_INPUTS, manifestPath, lockPath]);
    assert.equal(made.code, 0, made.stderr);
    const [manifestSha, lockSha] = made.stdout.trim().split(' ');
    assert.deepEqual(await tool('prepare', ...common, '--target-manifest', manifestPath, '--image-lock', lockPath),
      { code: 2, result: { state: 'refused', code: 'busy' } });

    // 3. stopped: prepare the exact request; the gate backup refuses without its worker
    const kept = await context.storageState();
    await context.close();
    await terminateOwnedChild(server, { graceMs: 5000, forceMs: 2000, label: 'Update guidance fixture' });
    server = undefined;
    const prepared = await tool('prepare', ...common, '--target-manifest', manifestPath, '--image-lock', lockPath);
    assert.equal(prepared.code, 0, JSON.stringify(prepared.result));
    assert.equal(prepared.result.state, 'prepared');
    assert.equal(prepared.result.target_release_manifest_sha256, manifestSha);
    assert.equal(prepared.result.target_image_lock_set_sha256, lockSha);
    assert.equal(prepared.result.recovery_epoch, 1);
    const workerConfig = join(operator, 'backup-worker.json');
    await writeFile(workerConfig, JSON.stringify({ schema: 'none', pair_root: join(dir, 'no-worker'), requester_boot_id: '0'.repeat(32) }));
    assert.deepEqual(await tool('backup', ...common, '--backup-worker-config', workerConfig),
      { code: 2, result: { state: 'refused', code: 'component_unavailable', component: 'backup-crypto' } });
    const status = await tool('status', ...common);
    assert.equal(status.result.request.state, 'prepared');

    // 4. the server restarts over the same instance; the records page shows the guidance
    const again = await start();
    assert.equal(again, url);
    context = await browser.newContext({ viewport: { width: 1100, height: 900 }, storageState: kept });
    page = await context.newPage();
    page.setDefaultTimeout(10000);
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(url + 'records.html');
    const panel = page.locator('#records-update');
    const request = panel.locator('.update-request[data-state="prepared"]');
    await request.waitFor();
    const requestText = await request.textContent();
    assert.match(requestText, /업데이트 요청 → 1\.1\.0 · 준비됨/);
    assert.ok(requestText.includes(manifestSha.slice(0, 12)) && requestText.includes(lockSha.slice(0, 12)));
    assert.match(requestText, /권한 세대 1/);
    assert.equal(await panel.locator('.update-backup').getAttribute('data-state'), 'absent');
    assert.match(await panel.locator('.update-backup').textContent(), /검증된 백업이 필요합니다/);
    assert.match(await panel.locator('.update-refusal').textContent(), /필요한 구성 요소가 응답하지 않아.*\(backup-crypto\)/);
    const steps = await panel.locator('.update-steps li').evaluateAll(nodes => nodes.map(node => node.dataset.step));
    assert.deepEqual(steps, ['stop_control_plane', 'take_verified_backup', 'apply_image_lock_and_sign_receipt',
      'migrate_with_receipt', 'start_new_release']);
    assert.match(await panel.textContent(), /이 화면은 읽기만 합니다/);
    // read only: nothing to press, fill or upload, and the route takes no command
    assert.equal(await panel.locator('button, form, input, textarea, select').count(), 0);
    const answers = await page.evaluate(async base => {
      const session = await (await fetch(base + 'session')).json();
      const post = await fetch(base + 'api/v1/platform/update', { method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrf_token }, body: '{}' });
      const read = await fetch(base + 'api/v1/platform/update');
      return { post: post.status, read: read.status, body: await read.json() };
    }, url);
    assert.ok(answers.post >= 400, `a POST is refused (${answers.post})`);
    assert.equal(answers.read, 200);
    assert.equal(answers.body.product_authority, 'read_only');
    assert.equal(answers.body.request.request_id, prepared.result.request_id);
    // the owner's other records still read (nothing was migrated or lost)
    await page.locator('#records-logs li').first().waitFor();
    assert.deepEqual(errors, []);
  });
