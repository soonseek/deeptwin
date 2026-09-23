// Shared real-browser fixture for the own-version and inquiry cases (T054/T060): the
// supported server with one recorded run, the owner bootstrapped, the run started
// through the owner's own consent and run routes.

import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../../', import.meta.url));
export const base = `/${'2'.repeat(32)}/`;
const READY = /ALTERNATIVES_SEED=(\{[^\n]*\})\nALTERNATIVES_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;

export async function open(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-alternatives-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Alternatives fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/alternatives_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 30000, label: 'Alternatives fixture' });
  const [, seedText, url] = READY.exec(announced);
  const seed = JSON.parse(seedText);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1200, height: 1000 } });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  const bootstrapped = await page.evaluate(async ({ base, capability }) => (await fetch(base + 'session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase', raw_capability_b64u: capability }),
  })).status, { base, capability: Buffer.alloc(32, 'T').toString('base64url') });
  assert.equal(bootstrapped, 201);
  // the owner consents to exactly these inputs and starts the run through the product routes
  const runId = await page.evaluate(async ({ base, seed }) => {
    const session = await (await fetch(base + 'session')).json();
    const headers = { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrf_token };
    const consent = await (await fetch(base + 'api/v1/run-consents', { method: 'POST', headers, body: JSON.stringify({
      schema_version: 'run-consent-command-v1', command_id: crypto.randomUUID(), graph_ref: seed.graph_ref,
      work_revision_ref: seed.work_revision_ref, environment_ref: seed.environment_ref,
      budget_policy_ref: seed.budget_policy_ref }) })).json();
    const run = await (await fetch(base + 'api/v1/runs', { method: 'POST', headers, body: JSON.stringify({
      command_id: crypto.randomUUID(), ...seed, consent_ref: consent.ref }) })).json();
    return run.run_id;
  }, { base, seed });
  assert.match(runId, /^[0-9a-f-]{36}$/);
  return { browser, context, page, url, errors, runId };
}

export async function openEditor(page, url, runId, role = 'report') {
  await page.goto(url + 'observe.html');
  await page.getByRole('combobox', { name: '관제할 실행 선택' }).selectOption(runId);
  const row = page.locator('li', { hasText: `${role} ·` });
  await row.getByRole('button', { name: '내 버전 편집' }).click();
  await page.locator('#run-alternative [role=status]').filter({ hasText: /원본을 복사해|이어서 편집/ }).waitFor();
}

export const saved = (page, revision) => page.locator('#run-alternative [role=status]', { hasText: `저장됨 (수정본 ${revision})` }).waitFor();

