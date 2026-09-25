// T067 G-14 (2026-09-25, growth.md §5/§9): a prior-work queue with a past gated send,
// re-evaluated in isolation, in a real browser (Chromium, `chrome` channel) against the
// real supported server (app/tests/fixtures/growth_effects_server.py).
//   1. The owner performs the original send: starts the tool-gated run, approves the
//      writer's exact attempt on the observe screen and resumes; the real dispatcher and
//      extension transport invoke the TEST-ACTOR tool `test_actor_notify` (it claims an
//      external_irreversible effect and performs none) over the worker socket, once.
//   2. The test-owned growth driver (the product has none) freezes a queue naming that
//      recorded ToolCall by its record digest and runs three paired rounds in isolated
//      vaults: an approved replay boundary, an approved isolated sink (the candidate sends
//      a changed notice) and an unapproved replay boundary.
//   3. The owner's versions page shows each round's per-item outcome and the boundary every
//      isolated call used; the unapproved round is invalid with the item's stated reason.
// Across the rounds the tool's invocation counter, the production transport factory, the
// worker channel, the authenticated worker connection and the attempt dispatcher factory
// never move, and the original run still has its one attempt. Synthetic test-actor evidence.

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = `/${'2'.repeat(32)}/`;
const READY = /G14_SEED=(\{[^\n]*\})\nG14_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
const CAPABILITY = Buffer.alloc(32, 'T').toString('base64url');
const GATE = 'tool-gate';
const LINEAGES = { REPLAY: '67014000-0000-4000-8000-000000000000', SINK: '67014100-0000-4000-8000-000000000000',
  UNAPPROVED: '67014200-0000-4000-8000-000000000000' };
const TOOL = 'test_actor_notify 1.0.0';

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

async function waitForFile(path, timeoutMs) {
  const end = Date.now() + timeoutMs;
  for (;;) {
    try {
      return JSON.parse(await readFile(path, 'utf8'));
    } catch (error) {
      if (error.code !== 'ENOENT' || Date.now() > end) throw error;
      await new Promise(resolve => setTimeout(resolve, 200));
    }
  }
}

test('G-14: a queue with a past gated send is re-evaluated without sending it again', { timeout: 300000 }, async t => {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-g14-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'G-14 fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/growth_effects_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 60000, label: 'G-14 fixture' });
  const [, seedText, url] = READY.exec(announced);
  const seed = JSON.parse(seedText);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1200, height: 1000 } })).newPage();
  page.setDefaultTimeout(20000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  const bootstrapped = await page.evaluate(async ({ base, capability }) => (await fetch(base + 'session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase', raw_capability_b64u: capability }),
  })).status, { base, capability: CAPABILITY });
  assert.equal(bootstrapped, 201);

  // --- 1. the original send, by the owner, through the product
  await page.goto(url + 'work.html');
  await page.locator('#work-description').fill('합성 과거 발송 업무');
  await page.getByRole('button', { name: '이 인스턴스에 저장', exact: true }).click();
  await page.getByText('이 인스턴스에 저장됨 · 수정본', { exact: false }).first().waitFor();
  const workId = await page.evaluate(key => JSON.parse(localStorage.getItem(key)).work_id, `deeptwin:intake:${base}`);
  const work = await read(page, `api/v1/works/${workId}`);
  const inputs = { graph_ref: seed.graphs.gated, work_revision_ref: work.ref,
    environment_ref: seed.environment_ref, budget_policy_ref: seed.budget_policy_ref };
  const consent = await owner(page, 'api/v1/run-consents', { schema_version: 'run-consent-command-v1',
    command_id: crypto.randomUUID(), ...inputs });
  assert.equal(consent.status, 201, JSON.stringify(consent.body));
  const started = await owner(page, 'api/v1/runs', { command_id: crypto.randomUUID(), ...inputs, consent_ref: consent.body.ref });
  assert.equal(started.status, 201, JSON.stringify(started.body));
  const runId = started.body.run_id;
  assert.equal(started.body.outcome.awaiting_execution[0][0], GATE);
  await page.goto(url + 'observe.html');
  await page.getByRole('combobox', { name: '관제할 실행 선택' }).selectOption(runId);
  await page.locator(`#run-panel[data-run-id="${runId}"]`).waitFor();
  const screen = page.locator('#run-approvals');
  await screen.locator('.approval-executions li[data-attempt="1"]').getByRole('button', { name: '승인: 시도 1' }).click();
  await screen.getByText('이 시도에 대한 결정을 기록했습니다.').waitFor();
  await page.locator('#run-panel[data-phase=running]').waitFor();
  await page.locator('#run-panel').getByRole('button', { name: '이어서 진행' }).click();
  await page.locator('#run-panel[data-phase=completed]').waitFor();
  const sent = await read(page, `api/v1/runs/${runId}`);
  assert.deepEqual(sent.cancellation.attempts.map(item => [item.attempt_no, item.phase]), [[1, 'terminal']]);

  // --- 2. the paired rounds over a queue naming that recorded call
  await writeFile(join(dir, 'g14-request.json'), JSON.stringify({ run_id: runId }));
  const done = await waitForFile(join(dir, 'g14-done.json'), 120000);
  assert.equal(done.error, undefined, done.error);
  assert.equal(done.evidence_label, 'synthetic/test-actor');
  const [binding] = done.bindings;
  assert.equal(done.bindings.length, 1);
  assert.equal(binding.run_id, runId);
  assert.equal(done.before.tool_calls, 1);  // the original send reached the tool exactly once
  // the counters are live: installed at start, they saw the original send's whole path
  for (const name of ['transport_build', 'channel', 'connect', 'dispatcher_build']) assert.ok(done.before[name] >= 1, name);
  // nothing reached the tool again, and no isolated run entered the production path at all
  assert.deepEqual(done.after, done.before);
  assert.deepEqual(Object.keys(done.after).sort(), ['channel', 'connect', 'dispatcher_build', 'tool_calls', 'transport_build']);
  assert.deepEqual(Object.fromEntries(Object.entries(done.rounds).map(([name, item]) => [name, item.validity])),
    { REPLAY: 'valid', SINK: 'valid', UNAPPROVED: 'invalid' });
  const after = await read(page, `api/v1/runs/${runId}`);
  assert.deepEqual(after.cancellation.attempts, sent.cancellation.attempts);

  // --- 3. the owner's versions page shows each item's outcome and boundary
  await page.goto(url + 'versions.html');
  await page.locator('#versions [role=status][data-state=loaded]').waitFor({ state: 'attached' });
  const rounds = page.locator('#versions section[aria-label="비교 라운드"]');
  const round = name => rounds.locator(`section[aria-label="계보 ${LINEAGES[name].slice(0, 8)}"] article[aria-label="라운드 0"]`);
  const outcome = (name, index) => round(name).locator('ul[aria-label="항목별 결과"] > li').nth(index);
  const call = binding.tool_call_sha256.slice(0, 12);
  const pastText = `과거 외부 효과 1건: ${TOOL} (ToolCall 기록 ${call})`;

  // REPLAY: both sides answered from the record; nothing sent again
  assert.equal(await round('REPLAY').getAttribute('data-validity'), 'valid');
  assert.match(await round('REPLAY').textContent(), /과거 발송·게시는 다시 실행하지 않았습니다/);
  assert.equal(await outcome('REPLAY', 0).locator('ul > li').textContent(), '도구 호출 없음');
  assert.equal(await outcome('REPLAY', 0).getAttribute('data-item-outcome'), 'compared');
  assert.equal(await outcome('REPLAY', 1).getAttribute('data-item-outcome'), 'compared');
  assert.match(await outcome('REPLAY', 1).textContent(), new RegExp(`^항목 1: 비교함 · ${pastText.replace(/[()]/g, '\\$&')}`));
  const replayed = outcome('REPLAY', 1).locator('li[data-boundary=replay]');
  assert.equal(await replayed.count(), 2);
  for (const [index, side] of [[0, '기준'], [1, '후보']]) {
    assert.equal(await replayed.nth(index).textContent(), `${side}: ${TOOL} (external_irreversible) · 기록 재생: `
      + `ToolCall 기록 ${call}의 결과 · 실제 서비스로 다시 보내지 않음`);
  }

  // SINK: both sides delivered to the isolated sink; the candidate's changed notice is visible
  assert.equal(await round('SINK').getAttribute('data-validity'), 'valid');
  const sunk = outcome('SINK', 1).locator('li[data-boundary=isolated_sink]');
  assert.equal(await sunk.count(), 2);
  const [left, right] = [await sunk.nth(0).textContent(), await sunk.nth(1).textContent()];
  assert.match(left, /^기준: test_actor_notify 1\.0\.0 \(external_irreversible\) · 격리 싱크 g14-isolated-sink에 보관\(입력 sha256 [0-9a-f]{12}\) · 실제 서비스로 보내지 않음$/);
  assert.match(right, /^후보: .* · 격리 싱크 g14-isolated-sink에 보관/);
  assert.notEqual(left.match(/sha256 ([0-9a-f]{12})/)[1], right.match(/sha256 ([0-9a-f]{12})/)[1]);
  const { item_outcomes: sinkOutcomes } = done.rounds.SINK;
  assert.equal(left.match(/sha256 ([0-9a-f]{12})/)[1], sinkOutcomes[1].baseline_effects[0].inputs_digest.slice(0, 12));

  // UNAPPROVED: that item is not comparable with its reason; the round is invalid and unscored
  const reason = `the replay boundary for ${TOOL} is not approved`;
  assert.equal(await round('UNAPPROVED').getAttribute('data-validity'), 'invalid');
  assert.match(await round('UNAPPROVED').textContent(),
    new RegExp(`무효 · 사유: item 1: not comparable: ${reason} · 유효한 라운드가 아니므로 측정값과 효용을 표시하지 않습니다`));
  assert.equal(await outcome('UNAPPROVED', 1).getAttribute('data-item-outcome'), 'not_comparable');
  assert.match(await outcome('UNAPPROVED', 1).textContent(), new RegExp(`^항목 1: 비교 불가 · 사유: ${reason}`));
  assert.equal(await outcome('UNAPPROVED', 1).locator('li[data-boundary]').count(), 0);
  assert.match(await round('UNAPPROVED').textContent(), /짝지은 실행 1쌍/);
  assert.deepEqual(errors, []);
});
