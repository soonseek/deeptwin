// The design-arc fixture (app/tests/fixtures/design_arc_server.py) for the T038/T048
// real-browser cases: the real supported server, the owner bootstrapped from the page, a
// real work saved through the work page, and the TEST-ACTOR scenarios registered over it
// by the fixture's test-only route (SIMULATED qualification, labelled).

import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../../', import.meta.url));
export const base = `/${'2'.repeat(32)}/`;
const READY = /ARC_SEED=(\{[^\n]*\})\nARC_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;

export async function openArc(t, { args = [] } = {}) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-arc-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Design arc fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/design_arc_server.py', '--owned-dir', dir, ...args],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 60000, label: 'Design arc fixture' });
  const [, , url] = READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1400, height: 1100 } });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  const bootstrapped = await page.evaluate(async ({ base, capability }) => (await fetch(base + 'session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase', raw_capability_b64u: capability }),
  })).status, { base, capability: Buffer.alloc(32, 'T').toString('base64url') });
  assert.equal(bootstrapped, 201);
  return { page, url, errors };
}

// a real work with one original, saved through the work page; returns its id
export async function saveWork(page, url) {
  await page.goto(url + 'work.html');
  await page.locator('#work-description').fill('유튜브 대본을 조사·작성·검토하는 합성 업무');
  await page.getByLabel('원본 자료 선택').setInputFiles({ name: '자료.txt', mimeType: 'text/plain',
    buffer: Buffer.from('합성 원본 자료\n') });
  await page.getByRole('button', { name: '이 인스턴스에 저장', exact: true }).click();
  await page.locator('#work-deletion').getByLabel('자료.txt', { exact: false }).waitFor();
  return page.evaluate(key => JSON.parse(localStorage.getItem(key)).work_id, `deeptwin:intake:${base}`);
}

// TEST ACTOR: the scripted design scenarios over this work (the fixture's test-only route)
export async function seedArc(page, workId, scenarios) {
  const seeded = await page.evaluate(async ({ id, scenarios }) => {
    const response = await fetch('/__test__/seed-design-arc', { method: 'POST', body: JSON.stringify({ work_id: id, scenarios }) });
    return { status: response.status, body: await response.json() };
  }, { id: workId, scenarios });
  assert.equal(seeded.status, 200, JSON.stringify(seeded.body));
  return seeded.body;
}

// the owner's own routes, called from the page with the session's CSRF value (setup only)
export async function owner(page, path, body) {
  return page.evaluate(async ({ base, path, body }) => {
    const session = await (await fetch(base + 'session')).json();
    const response = await fetch(base + path, { method: 'POST', body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrf_token } });
    return { status: response.status, body: await response.json().catch(() => null) };
  }, { base, path, body });
}

export async function read(page, path) {
  return page.evaluate(async ({ base, path }) => (await fetch(base + path)).json(), { base, path });
}
