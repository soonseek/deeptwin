// Shared real-browser fixture for the backup, portable-restore and retention cases (T073):
// app/tests/fixtures/backup_server.py runs the production backup-crypto worker as a
// separate networkless process and the supported app under the control identity; this
// helper starts it, opens a real browser and bootstraps the scripted test owner. It also
// hands over the directory of the fixture's "elsewhere" portable backup (bundle, external
// receipt and the identity the owner kept). Needs Linux, root and DEEPTWIN_AGE_RUNTIME_ROOT.

import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../../', import.meta.url));
export const base = `/${'2'.repeat(32)}/`;
const READY = /BACKUP_WORKER_NETWORKLESS=(true|false)\nBACKUP_PORTABLE_DIR=([^\n]+)\n(?:[^\n]*\n)*?BACKUP_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
export const PASSWORD = 'synthetic owner passphrase';
export const CAPABILITY = Buffer.alloc(32, 'T').toString('base64url');
export const unavailable = process.platform !== 'linux' || process.getuid?.() !== 0 || !process.env.DEEPTWIN_AGE_RUNTIME_ROOT
  ? 'the real backup worker fixture needs Linux, root and DEEPTWIN_AGE_RUNTIME_ROOT' : false;

export async function openBackup(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-backup-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 8000, serverForceMs: 3000, label: 'Backup fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/backup_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 60000, label: 'Backup fixture' });
  const [, networkless, portableDir, url] = READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1200, height: 1400 }, acceptDownloads: true });
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  const bootstrapped = await page.evaluate(async ({ base, capability, password }) => (await fetch(base + 'session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password, raw_capability_b64u: capability }),
  })).status, { base, capability: CAPABILITY, password: PASSWORD });
  assert.equal(bootstrapped, 201);
  return { context, page, url, errors, networkless: networkless === 'true', portableDir };
}

export async function bytesOf(page, href) {
  return Buffer.from(await page.evaluate(async target => [...new Uint8Array(await (await fetch(target)).arrayBuffer())], href));
}

// one backup through the records page: the actual preview, a separate consent, then create
export async function makeBackup(page, url) {
  await page.goto(url + 'records.html');
  const panel = page.locator('#records-backup');
  await panel.locator('.backup-worker[data-state="ready"]').waitFor();
  await panel.getByRole('button', { name: '백업에 포함될 내용 미리보기' }).click();
  await panel.locator('#backup-consent').check();
  await panel.getByRole('button', { name: '이 내용으로 백업 만들기' }).click();
  await panel.getByText('백업을 만들고 복원 확인을 마쳤습니다.', { exact: false }).first().waitFor();
  const receiptHref = await panel.locator('.backup-preview').getByRole('link', { name: '외부 영수증 내려받기' }).getAttribute('href');
  return JSON.parse((await bytesOf(page, receiptHref)).toString('utf8'));
}
