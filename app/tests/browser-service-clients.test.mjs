// UI phase 6: 설정 > 서비스 클라이언트 in real Chromium against the real supported server on the
// portable HTTPS profile (fixtures/portable_https_server.py: create_app under uvicorn over TLS with
// a throwaway test CA made here by openssl; the browser maps the test's dotted name to 127.0.0.1).
// The owner creates a scoped client and sees its one-time secret exactly once (copy, warning,
// nothing in localStorage, sessionStorage, the address or any attribute), the secret reads what a
// bearer may read, a rotation (after a confirmation) kills the old secret and shows a new one once,
// a revocation (after a confirmation) kills the client. The refusal of a loopback instance is
// covered in browser-a11y.test.mjs (journey f). Synthetic test-actor evidence only.

import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';
import { AUDIT_LAUNCH_ARGS, auditPage } from './helpers/a11y-audit.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
// the portable profile requires a dotted DNS name; the browser resolves it to the loopback listener
const HOST = 'deeptwin.test';
const CAPABILITY = Buffer.alloc(32, 'S').toString('base64url');
const READY = /PORTABLE_HTTPS_URL=(https:\/\/deeptwin\.test:\d+)/;

function certificates(directory) {
  const openssl = (...args) => execFileSync('openssl', args, { cwd: directory, stdio: 'ignore', timeout: 60000 });
  const curve = ['-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes'];
  openssl('req', '-x509', ...curve, '-keyout', 'ca.key', '-out', 'ca.pem', '-days', '2', '-subj', '/CN=deeptwin ui phase 6 test ca',
    '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign');
  return writeFile(join(directory, 'leaf.cnf'), `subjectAltName=DNS:${HOST}\nbasicConstraints=critical,CA:FALSE\n`
    + 'keyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n').then(() => {
    openssl('req', ...curve, '-keyout', 'leaf.key', '-out', 'leaf.csr', '-subj', `/CN=${HOST}`);
    openssl('x509', '-req', '-in', 'leaf.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key', '-CAcreateserial', '-out', 'leaf.pem',
      '-days', '2', '-extfile', 'leaf.cnf');
    return { leaf: join(directory, 'leaf.pem'), key: join(directory, 'leaf.key') };
  });
}

async function openFixture(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'dt-clients-'));
  const tls = join(dir, 'tls');
  const owned = join(dir, 'owned');
  await mkdir(tls);
  await mkdir(owned);
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Portable HTTPS fixture' }));
  const { leaf, key } = await certificates(tls);
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/portable_https_server.py', '--owned-dir', owned,
    '--certificate', leaf, '--private-key', key, '--host-name', HOST],
  { cwd: root, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  // the capability travels on stdin only
  server.stdin.end(`${CAPABILITY}\n`);
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 60000, label: 'Portable HTTPS fixture' });
  const [, origin] = READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true,
    // never through any outbound proxy of the host: the name is mapped to the loopback listener
    args: [...AUDIT_LAUNCH_ARGS, `--host-resolver-rules=MAP ${HOST} 127.0.0.1`, '--no-proxy-server'] });
  // the test's own throwaway CA is not in the browser's store; this context accepts it
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, ignoreHTTPSErrors: true,
    permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  for (let tries = 0; ; tries += 1) {
    try {
      await page.goto(`${origin}/`);
      break;
    } catch (error) {
      if (tries > 40) throw error;
      await new Promise(resolve => setTimeout(resolve, 250));
    }
  }
  const status = await page.evaluate(async capability => (await fetch('/session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase', raw_capability_b64u: capability }),
  })).status, CAPABILITY);
  assert.equal(status, 201);
  return { page, origin, errors };
}

// what a bearer reads with the secret, from the page, with no cookie
const bearerRead = (page, secret) => page.evaluate(async secret => {
  const response = await fetch('/api/v1/events', { credentials: 'omit', headers: { Authorization: `Bearer ${secret}` } });
  return response.status;
}, secret);

// the secret is nowhere but the one read-only field while it is shown
const secretLeaks = (page, secret) => page.evaluate(secret => {
  const stored = [];
  for (const storage of [localStorage, sessionStorage]) {
    for (let index = 0; index < storage.length; index += 1) stored.push(storage.key(index), storage.getItem(storage.key(index)));
  }
  return {
    storage: stored.some(value => String(value).includes(secret)),
    markup: document.documentElement.outerHTML.includes(secret),
    address: location.href.includes(secret),
    title: document.title.includes(secret),
  };
}, secret);

test('설정 > 서비스 클라이언트 on the portable HTTPS profile: create, the secret once, rotate and revoke with confirmation',
  { timeout: 240000 }, async t => {
    const { page, origin, errors } = await openFixture(t);
    await page.goto(`${origin}/settings.html#settings-service-clients`);
    const panel = page.locator('#service-clients');
    await panel.locator('.service-clients-count', { hasText: '아직 만든 서비스 클라이언트가 없습니다.' }).waitFor();
    assert.equal(await page.locator('#settings-hub a[aria-current="true"]').textContent(), '서비스 클라이언트');
    // only the scopes a bearer is granted are offered
    assert.deepEqual(await panel.locator('fieldset input[type=checkbox]').evaluateAll(nodes => nodes.map(node => node.value)),
      ['snapshot.read', 'events.read']);
    assert.deepEqual(await panel.getByLabel('만료').locator('option').allTextContents(), ['1시간', '8시간', '23시간 (가장 긺)']);

    // the form says what is missing before anything is sent
    await panel.getByRole('button', { name: '클라이언트 만들기' }).click();
    await panel.getByText('이름을 적어 주세요.').waitFor();
    assert.equal(await panel.getByLabel('이름').getAttribute('aria-invalid'), 'true');
    await panel.getByLabel('이름').fill('리포트 봇');
    await panel.getByRole('button', { name: '클라이언트 만들기' }).click();
    await panel.getByText('허용할 읽기를 하나 이상 골라 주세요.').waitFor();

    await panel.getByLabel('사건 기록 읽기').check();
    await panel.getByLabel('현재 상태 스냅샷 읽기').check();
    await panel.getByLabel('만료').selectOption('1');
    await panel.getByRole('button', { name: '클라이언트 만들기' }).click();
    const reveal = panel.locator('.service-client-secret');
    await reveal.waitFor();
    assert.equal(await reveal.getByRole('heading').textContent(), '새 비밀 값 — 리포트 봇');
    assert.equal(await page.evaluate(() => document.activeElement?.textContent), '새 비밀 값 — 리포트 봇', 'the secret box takes the keyboard');
    assert.match(await reveal.textContent(), /지금 한 번만 보입니다/);
    const field = reveal.getByLabel('비밀 값');
    assert.equal(await field.getAttribute('readonly'), '');
    const secret = await field.inputValue();
    assert.match(secret, /^dt_sc_[A-Za-z0-9_-]{20,}$/);
    assert.deepEqual(await secretLeaks(page, secret), { storage: false, markup: false, address: false, title: false });
    assert.deepEqual(await auditPage(page, { label: 'secret shown' }), []);
    // copy puts exactly the secret on the clipboard
    await reveal.getByRole('button', { name: '복사' }).click();
    await reveal.getByText('비밀 값을 복사했습니다.').waitFor();
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), secret);
    // the secret reads what the bearer is granted
    assert.equal(await bearerRead(page, secret), 200);

    // listed without the secret; hiding clears the field and says so
    const row = panel.locator('li.service-client', { hasText: '리포트 봇' });
    assert.match(await row.textContent(), /사용 중/);
    assert.match(await row.textContent(), /현재 상태 스냅샷 읽기 · 사건 기록 읽기/);
    assert.match(await row.locator('.service-client-facts').textContent(), /만료\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \((?:\d+분|1시간) 뒤\)/);
    await reveal.getByRole('button', { name: '다 옮겼습니다 · 숨기기' }).click();
    await reveal.waitFor({ state: 'detached' });
    await panel.getByText('비밀 값을 화면에서 지웠습니다. 다시 볼 수 없습니다.').waitFor();
    assert.equal(await page.evaluate(secret => document.body.innerText.includes(secret)
      || [...document.querySelectorAll('input')].some(input => input.value === secret), secret), false);

    // rotation asks first; 취소 changes nothing and returns the keyboard
    const rotate = row.getByRole('button', { name: '비밀 값 다시 만들기' });
    await rotate.click();
    const confirm = row.locator('.service-client-confirm');
    await confirm.getByText(/지금 비밀 값은 바로 쓸 수 없게 됩니다/).waitFor();
    assert.equal(await page.evaluate(() => document.activeElement?.textContent), '새 비밀 값으로 바꾸기');
    await confirm.getByRole('button', { name: '취소' }).click();
    await confirm.waitFor({ state: 'detached' });
    assert.equal(await page.evaluate(() => document.activeElement?.textContent), '비밀 값 다시 만들기');
    assert.equal(await bearerRead(page, secret), 200, 'a cancelled rotation changes nothing');
    await rotate.click();
    await row.getByRole('button', { name: '새 비밀 값으로 바꾸기' }).click();
    await reveal.waitFor();
    const rotated = await reveal.getByLabel('비밀 값').inputValue();
    assert.match(rotated, /^dt_sc_/);
    assert.notEqual(rotated, secret);
    await panel.getByText('“리포트 봇”의 비밀 값을 바꿨습니다. 이전 비밀 값은 더 이상 쓰이지 않습니다.').waitFor();
    assert.equal(await bearerRead(page, secret), 401, 'the old secret is dead');
    assert.equal(await bearerRead(page, rotated), 200);
    assert.deepEqual(await secretLeaks(page, rotated), { storage: false, markup: false, address: false, title: false });

    // revocation asks first, then the client can no longer read
    await panel.locator('li.service-client', { hasText: '리포트 봇' }).getByRole('button', { name: '폐기', exact: true }).click();
    const revoke = panel.locator('li.service-client', { hasText: '리포트 봇' }).locator('.service-client-confirm');
    await revoke.getByText(/폐기하면 이 클라이언트는 더 이상 읽을 수 없고 되돌릴 수 없습니다/).waitFor();
    await revoke.getByRole('button', { name: '폐기하기' }).click();
    const revoked = panel.locator('li.service-client[data-state="revoked"]', { hasText: '리포트 봇' });
    await revoked.waitFor();
    assert.match(await revoked.textContent(), /폐기됨/);
    assert.equal(await revoked.getByRole('button').count(), 0, 'nothing left to rotate or revoke');
    assert.equal(await bearerRead(page, rotated), 401);

    // after a reload the list reads the server's state; no secret comes back
    await page.reload();
    await panel.locator('li.service-client[data-state="revoked"]').waitFor();
    assert.equal(await panel.locator('.service-client-secret').count(), 0);
    for (const value of [secret, rotated]) {
      assert.deepEqual(await secretLeaks(page, value), { storage: false, markup: false, address: false, title: false });
    }
    assert.deepEqual(await auditPage(page, { label: 'service clients listed' }), []);
    assert.deepEqual(errors, []);
  });
