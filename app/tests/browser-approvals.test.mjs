// T066/T087/UX-AC06: the owner's approval screen on the observe page, in a real
// browser (Chromium, `chrome` channel) against the real supported server
// (`create_app` through app/tests/fixtures/records_server.py). The owner starts two
// runs of a graph with a human gate through the product's own consent and run
// routes, opens the observe page, chooses each run and decides its pending gate on
// the approval screen: the screen names the exact run, node and scope, posts the
// closed command through the owner route with the session's CSRF header, and the
// run panel re-reads the run (approved: resumable, then completed; rejected:
// rejected). No execution-bound (v2) ask exists in this fixture, and the screen
// says so instead of inventing one. The owner is a scripted test actor: synthetic
// evidence of the mechanism, never user evidence.

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';
import { openRunFromList } from './helpers/run-list.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = `/${'2'.repeat(32)}/`;
const READY = /RECORDS_SEED=(\{[^\n]*\})\nRECORDS_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
const PASSWORD = 'synthetic owner passphrase';
const CAPABILITY = Buffer.alloc(32, 'T').toString('base64url');

async function openServer(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-approvals-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Approvals fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/records_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 30000, label: 'Approvals fixture' });
  const [, seedText, url] = READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1200, height: 1000 } });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  const bootstrapped = await page.evaluate(async ({ base, capability, password }) => (await fetch(base + 'session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password, raw_capability_b64u: capability }),
  })).status, { base, capability: CAPABILITY, password: PASSWORD });
  assert.equal(bootstrapped, 201);
  return { page, url, errors, seed: JSON.parse(seedText) };
}

// the owner's own routes, called from the page with the session's CSRF value (setup only)
async function owner(page, path, body) {
  return page.evaluate(async ({ base, path, body }) => {
    const session = await (await fetch(base + 'session')).json();
    const response = await fetch(base + path, { method: 'POST', body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrf_token } });
    return { status: response.status, body: await response.json().catch(() => null) };
  }, { base, path, body });
}

async function gatedRun(page, seed, workRef) {
  const inputs = { graph_ref: seed.graphs.gated, work_revision_ref: workRef,
    environment_ref: seed.environment_ref, budget_policy_ref: seed.budget_policy_ref };
  const consent = await owner(page, 'api/v1/run-consents', { schema_version: 'run-consent-command-v1',
    command_id: crypto.randomUUID(), ...inputs });
  assert.equal(consent.status, 201, JSON.stringify(consent.body));
  const started = await owner(page, 'api/v1/runs', { command_id: crypto.randomUUID(), ...inputs, consent_ref: consent.body.ref });
  assert.equal(started.status, 201, JSON.stringify(started.body));
  assert.equal(started.body.phase, 'awaiting_human');
  return started.body.run_id;
}

async function readDecision(page, runId) {
  return page.evaluate(async ({ base, runId }) => {
    const response = await fetch(`${base}api/v1/runs/${runId}/approvals/owner-gate/release-output`);
    return { status: response.status, body: await response.json().catch(() => null) };
  }, { base, runId });
}

test('the approval screen decides a pending gate through the owner route and the run follows', { timeout: 180000 }, async t => {
  const { page, url, errors, seed } = await openServer(t);
  // a work saved through the work screen, and two gated runs of it
  await page.goto(url + 'work.html');
  await page.locator('#work-description').fill('합성 승인 화면 업무');
  await page.getByRole('button', { name: '이 인스턴스에 저장', exact: true }).click();
  await page.getByText('이 인스턴스에 저장됨 · 수정본', { exact: false }).first().waitFor();
  const workId = await page.evaluate(key => JSON.parse(localStorage.getItem(key)).work_id, `deeptwin:intake:${base}`);
  const work = await page.evaluate(async ({ base, id }) => (await fetch(`${base}api/v1/works/${id}`)).json(), { base, id: workId });
  const approveRun = await gatedRun(page, seed, work.ref);
  const rejectRun = await gatedRun(page, seed, work.ref);

  // every decision the screen posts, as the browser sent it
  const posted = [];
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/v1\/runs\/[0-9a-f-]{36}\/approvals/.test(request.url())) {
      posted.push({ url: new URL(request.url()).pathname, headers: request.headers(), body: JSON.parse(request.postData()) });
    }
  });

  await page.goto(url + 'observe.html');
  const screen = page.locator('#run-approvals');
  const panel = page.locator('#run-panel');
  await openRunFromList(page, approveRun);
  await screen.getByText('결정할 일 1개가 있습니다.').waitFor();
  const [gate] = await screen.locator('.approval-gates li .approval-subject').allTextContents();
  assert.equal(gate, `실행 ${approveRun} · 노드 owner-gate · 범위 release-output`);
  assert.equal(await screen.locator('.approval-executions li').count(), 0);
  assert.equal(await panel.getAttribute('data-phase'), 'awaiting_human');
  assert.equal((await readDecision(page, approveRun)).status, 404);  // nothing recorded before the click

  await screen.getByRole('button', { name: '승인: owner-gate/release-output' }).click();
  await screen.getByText('결정을 기록했습니다.', { exact: false }).waitFor();
  assert.equal(await screen.locator('.approval-gates li').count(), 0);
  assert.equal(posted.length, 1);
  assert.equal(posted[0].url, `${base}api/v1/runs/${approveRun}/approvals`);
  const csrf = await page.evaluate(async b => (await (await fetch(b + 'session')).json()).csrf_token, base);
  assert.equal(posted[0].headers['x-deeptwin-csrf'], csrf);
  assert.deepEqual(Object.keys(posted[0].body).sort(), ['approval_scope', 'command_id', 'decision', 'node_id']);
  assert.deepEqual({ ...posted[0].body, command_id: undefined }, { command_id: undefined, node_id: 'owner-gate',
    approval_scope: 'release-output', decision: 'approved' });
  const recorded = await readDecision(page, approveRun);
  assert.equal(recorded.status, 200);
  assert.equal(recorded.body.decision, 'approved');
  assert.equal(recorded.body.command_id, posted[0].body.command_id);
  // the panel re-read the run: the approved gate no longer waits, and resuming completes it
  await page.locator('#run-panel[data-phase=running]').waitFor();
  await panel.getByRole('button', { name: '이어서 진행' }).click();
  await page.locator('#run-panel[data-phase=completed]').waitFor();

  // the other run's gate is rejected on the same screen
  await openRunFromList(page, rejectRun);
  await screen.getByText('결정할 일 1개가 있습니다.').waitFor();
  assert.match(await screen.locator('.approval-gates li').textContent(), new RegExp(`실행 ${rejectRun}`));
  await screen.getByRole('button', { name: '거절: owner-gate/release-output' }).click();
  await screen.getByText('결정을 기록했습니다.', { exact: false }).waitFor();
  await page.locator('#run-panel[data-phase=rejected]').waitFor();
  assert.equal(posted.length, 2);
  assert.equal(posted[1].body.decision, 'rejected');
  assert.equal((await readDecision(page, rejectRun)).body.decision, 'rejected');
  assert.equal(await screen.locator('.approval-gates li').count(), 0);
  assert.deepEqual(errors, []);
});
