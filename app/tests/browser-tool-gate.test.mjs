// T087/T048 (2026-09-25): a gated external-effect tool call, end to end in a real
// browser (Chromium, `chrome` channel) against the real supported server (`create_app`
// through app/tests/fixtures/tool_gate_server.py). The stored graph binds the writer to
// the TEST-ACTOR tool `test_actor_notify` (registered in the worker's tool table only in
// that fixture process; it claims an external_irreversible effect and performs none)
// behind the human gate `tool-gate`. The run executes until the writer's first attempt,
// where the scheduler asks the ledger for exactly that attempt; the observe page's
// approval screen shows the exact run, gate, execution, executing node, attempt and the
// digest of the exact inputs; the owner decides through the screen:
//   - approve → resume → the real dispatcher claims the approval with the send and the
//     real transport runs the tool over the worker socket → the run completes;
//   - reject → the run is rejected;
//   - retry → attempt 1 is approved and the tool fails terminally; the owner's recovery
//     makes attempt 2, a new ask the screen marks as needing its own decision; approving
//     it and recovering again (the recovery is what admits attempt 2) completes the run.
// The owner is a scripted test actor: synthetic evidence of the mechanism, never user evidence.

import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = `/${'2'.repeat(32)}/`;
const READY = /TOOLGATE_SEED=(\{[^\n]*\})\nTOOLGATE_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
const PASSWORD = 'synthetic owner passphrase';
const CAPABILITY = Buffer.alloc(32, 'T').toString('base64url');
const GATE = 'tool-gate';
// the exact inputs the fixture's transport declares for each graph (tool_gate_server.py)
const OK_TEXT = 'synthetic test-actor notice\n';
const RETRY_TEXT = 'fail-once synthetic test-actor notice\n';

// tool_inputs_digest: sha256 of the canonical (sorted-key, compact) ordered declarations
function inputsDigest(text) {
  const bytes = Buffer.from(text, 'utf8');
  const declaration = { declared_size: bytes.length, media_type: 'text/plain', ordinal: 0, role: 'document_source',
    sha256: createHash('sha256').update(bytes).digest('hex') };
  return createHash('sha256').update(JSON.stringify([declaration])).digest('hex');
}

async function openServer(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-toolgate-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Tool gate fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/tool_gate_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 60000, label: 'Tool gate fixture' });
  const [, seedText, url] = READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1200, height: 1000 } });
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

async function read(page, path) {
  return page.evaluate(async ({ base, path }) => (await fetch(base + path)).json(), { base, path });
}

async function gatedRun(page, seed, graphRef, workRef) {
  const inputs = { graph_ref: graphRef, work_revision_ref: workRef,
    environment_ref: seed.environment_ref, budget_policy_ref: seed.budget_policy_ref };
  const consent = await owner(page, 'api/v1/run-consents', { schema_version: 'run-consent-command-v1',
    command_id: crypto.randomUUID(), ...inputs });
  assert.equal(consent.status, 201, JSON.stringify(consent.body));
  const started = await owner(page, 'api/v1/runs', { command_id: crypto.randomUUID(), ...inputs, consent_ref: consent.body.ref });
  assert.equal(started.status, 201, JSON.stringify(started.body));
  // the run executed up to the writer's first attempt and waits on exactly that attempt
  assert.equal(started.body.phase, 'awaiting_human');
  assert.deepEqual(started.body.outcome.awaiting_human, []);
  assert.equal(started.body.outcome.awaiting_execution.length, 1);
  const [gate, scope, executionId, nodeId, attemptNo] = started.body.outcome.awaiting_execution[0];
  assert.deepEqual([gate, nodeId, attemptNo], [GATE, 'writer', 1]);
  assert.deepEqual([...started.body.outcome.completed_node_ids].sort(), ['intake', GATE]);
  return { runId: started.body.run_id, scope, executionId };
}

async function choose(page, runId) {
  await page.getByRole('combobox', { name: '관제할 실행 선택' }).selectOption(runId);
  await page.locator(`#run-panel[data-run-id="${runId}"]`).waitFor();
}

function attemptItem(screen, attemptNo) {
  return screen.locator(`.approval-executions li[data-attempt="${attemptNo}"]`);
}

test('a gated external tool call waits for the owner\'s decision of its exact attempt', { timeout: 300000 }, async t => {
  const { page, url, errors, seed } = await openServer(t);
  await page.goto(url + 'work.html');
  await page.locator('#work-description').fill('합성 도구 게이트 업무');
  await page.getByRole('button', { name: '이 인스턴스에 저장', exact: true }).click();
  await page.getByText('이 인스턴스에 저장됨 · 수정본', { exact: false }).first().waitFor();
  const workId = await page.evaluate(key => JSON.parse(localStorage.getItem(key)).work_id, `deeptwin:intake:${base}`);
  const work = await read(page, `api/v1/works/${workId}`);
  const approveRun = await gatedRun(page, seed, seed.graphs.gated, work.ref);
  const rejectRun = await gatedRun(page, seed, seed.graphs.gated, work.ref);
  const retryRun = await gatedRun(page, seed, seed.graphs.retry, work.ref);

  const posted = [];
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/v1\/runs\/[0-9a-f-]{36}\/approvals/.test(request.url())) {
      posted.push({ url: new URL(request.url()).pathname, headers: request.headers(), body: JSON.parse(request.postData()) });
    }
  });

  await page.goto(url + 'observe.html');
  const screen = page.locator('#run-approvals');
  const panel = page.locator('#run-panel');

  // --- approve: the screen names the exact execution and attempt; the run completes
  await choose(page, approveRun.runId);
  await screen.getByText('결정할 일 1개가 있습니다.').waitFor();
  assert.equal(await screen.locator('.approval-gates li').count(), 0);  // no run-wide gate decision exists
  const first = attemptItem(screen, 1);
  assert.equal(await first.getAttribute('data-state'), 'pending');
  assert.equal(await first.getAttribute('data-execution-id'), approveRun.executionId);
  assert.equal(await first.locator('.approval-subject').textContent(),
    `실행 ${approveRun.runId} · ${GATE}/${approveRun.scope}: 실행 ${approveRun.executionId} (노드 writer) `
    + `시도 1 — 입력 sha256 ${inputsDigest(OK_TEXT)}`);
  // the local time of this device, to the second (UI phase 4: it read as UTC before)
  assert.match(await first.locator('.approval-expiry').textContent(), /시한 \d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/);
  assert.equal(await panel.getAttribute('data-phase'), 'awaiting_human');
  await first.getByRole('button', { name: '승인: 시도 1' }).click();
  await screen.getByText('이 시도에 대한 결정을 기록했습니다.').waitFor();
  assert.equal(posted.length, 1);
  assert.equal(posted[0].url, `${base}api/v1/runs/${approveRun.runId}/approvals/executions`);
  const csrf = await page.evaluate(async b => (await (await fetch(b + 'session')).json()).csrf_token, base);
  assert.equal(posted[0].headers['x-deeptwin-csrf'], csrf);
  assert.deepEqual({ ...posted[0].body, command_id: undefined }, { command_id: undefined, node_id: GATE,
    approval_scope: approveRun.scope, execution_id: approveRun.executionId, execution_node_id: 'writer',
    attempt_no: 1, inputs_digest: inputsDigest(OK_TEXT), decision: 'approved' });
  assert.equal(await attemptItem(screen, 1).getAttribute('data-state'), 'approved');
  await screen.getByText('이 시도는 승인되어 실행이 허가되었습니다.').waitFor();
  await page.locator('#run-panel[data-phase=running]').waitFor();
  await panel.getByRole('button', { name: '이어서 진행' }).click();
  await page.locator('#run-panel[data-phase=completed]').waitFor();
  const done = await read(page, `api/v1/runs/${approveRun.runId}`);
  assert.deepEqual([...done.outcome.completed_node_ids].sort(), ['intake', 'publish', GATE, 'writer'].sort());
  const writerResult = done.outcome.result_refs.find(([executionId]) => executionId === approveRun.executionId);
  assert.equal(writerResult[1].kind, 'artifact');  // the tool's sealed output is the writer's result

  // --- reject: the run is rejected and the attempt is not authorized
  await choose(page, rejectRun.runId);
  await screen.getByText('결정할 일 1개가 있습니다.').waitFor();
  assert.equal(await attemptItem(screen, 1).getAttribute('data-execution-id'), rejectRun.executionId);
  await attemptItem(screen, 1).getByRole('button', { name: '거절: 시도 1' }).click();
  await screen.getByText('이 시도에 대한 결정을 기록했습니다.').waitFor();
  await page.locator('#run-panel[data-phase=rejected]').waitFor();
  assert.equal(await attemptItem(screen, 1).getAttribute('data-state'), 'rejected');
  await screen.getByText('이 시도는 허가되지 않았습니다.').waitFor();
  assert.equal(posted.length, 2);
  assert.equal(posted[1].body.decision, 'rejected');
  const rejected = await read(page, `api/v1/runs/${rejectRun.runId}`);
  assert.deepEqual(rejected.outcome.rejected_execution,
    [[GATE, rejectRun.scope, rejectRun.executionId, 'writer', 1, 'rejected']]);
  assert.deepEqual(rejected.cancellation.attempts, []);  // nothing was reserved or sent

  // --- retry: attempt 1 fails terminally; the recovery's attempt 2 needs its own decision
  await choose(page, retryRun.runId);
  await screen.getByText('결정할 일 1개가 있습니다.').waitFor();
  assert.match(await attemptItem(screen, 1).locator('.approval-subject').textContent(),
    new RegExp(`시도 1 — 입력 sha256 ${inputsDigest(RETRY_TEXT)}$`));
  await attemptItem(screen, 1).getByRole('button', { name: '승인: 시도 1' }).click();
  await screen.getByText('이 시도에 대한 결정을 기록했습니다.').waitFor();
  await page.locator('#run-panel[data-phase=running]').waitFor();
  await panel.getByRole('button', { name: '이어서 진행' }).click();  // the tool fails: a refusal, then a re-read
  await panel.locator('[role=alert]:not([hidden])').waitFor();
  await page.locator('#run-panel[data-phase=running]').waitFor();
  const failed = await read(page, `api/v1/runs/${retryRun.runId}`);
  assert.deepEqual(failed.cancellation.attempts.map(item => [item.attempt_no, item.phase]), [[1, 'terminal']]);
  await panel.getByRole('button', { name: '복구 시도' }).click();
  await page.locator('#run-panel[data-phase=awaiting_human]').waitFor();
  await screen.getByRole('button', { name: '승인 요청 다시 읽기' }).click();
  await attemptItem(screen, 2).waitFor();
  assert.equal(await attemptItem(screen, 1).getAttribute('data-state'), 'approved');
  assert.equal(await attemptItem(screen, 2).getAttribute('data-state'), 'pending');
  assert.equal(await attemptItem(screen, 2).getAttribute('data-execution-id'), retryRun.executionId);
  await attemptItem(screen, 2).getByText('재시도 시도 — 이전 시도의 결정은 이 시도에 적용되지 않으므로 새 결정이 필요합니다.').waitFor();
  const waiting = await read(page, `api/v1/runs/${retryRun.runId}`);
  assert.deepEqual(waiting.outcome.awaiting_execution, [[GATE, retryRun.scope, retryRun.executionId, 'writer', 2]]);
  await attemptItem(screen, 2).getByRole('button', { name: '승인: 시도 2' }).click();
  await screen.getByText('이 시도에 대한 결정을 기록했습니다.').waitFor();
  assert.equal(posted.length, 4);
  assert.equal(posted[3].body.attempt_no, 2);
  await page.locator('#run-panel[data-phase=running]').waitFor();
  // the owner's recovery (it made attempt 2) now sends the approved attempt 2
  await panel.getByRole('button', { name: '복구 시도' }).click();
  await page.locator('#run-panel[data-phase=completed]').waitFor();
  const recovered = await read(page, `api/v1/runs/${retryRun.runId}`);
  assert.deepEqual(recovered.cancellation.attempts.map(item => item.attempt_no), [1, 2]);
  assert.deepEqual(errors, []);
});
