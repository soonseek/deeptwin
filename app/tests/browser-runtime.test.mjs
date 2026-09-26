// T049 (2026-09-25): the controlled producer→consumer run, end to end, in a real browser
// (Chromium, `chrome` channel) against the real supported server and real worker processes
// (app/tests/fixtures/runtime_e2e_server.py; root on Linux — the workers run under their
// own numeric identities and the browser worker in its own network namespace):
//   - `page-reader` (browser_read) and `page-shooter` (browser_screenshot) each dispatch one
//     real attempt through the sandboxed browser worker, which reaches the local fixture
//     site only through the fetch service under the attempt's grant;
//   - `documents` renders a PDF, a CSV table and a PNG figure with the document adapter;
//   - `gather` joins all three, `release-gate` holds the release for the owner;
//   - `consumer` reads every producer artifact WHOLE (the PDF's text through the isolated
//     document worker) and reports each input's exact sha256.
// The observe page shows the graph states, every attempt as its own row, each artifact
// (the PDF page rendered by the document worker, the CSV as a table, both images, the page
// text) and the consumer's report whose input digests are exactly the producers'. The
// server process is SIGKILLed while the run waits on the owner and restarted on the same
// data: the trace (every attempt row, every artifact digest) is unchanged. A second run's
// first read outlasts its deadline; the owner's recovery makes attempt 2 (a distinct row)
// and the owner then cancels that run mid-way; both attempts stay distinct.
// Scripted test actor only: synthetic evidence of the mechanism, never user evidence.

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = `/${'2'.repeat(32)}/`;
const READY = /E2E_SEED=(\{[^\n]*\})\nE2E_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
const RESTARTED = /E2E_RESTARTED\n(?:[^\n]*\n)*?E2E_SEED=\{[^\n]*\}\nE2E_URL=http[^\n]*\n/;
const PASSWORD = 'synthetic owner passphrase';
const PRODUCER_ROLES = ['figure', 'page_text', 'paper', 'screenshot', 'table'];
const rootOnly = process.platform !== 'linux' || process.getuid?.() !== 0
  ? 'the T049 deployment starts workers under their own identities: Linux and root only' : false;

async function openDeployment(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-t049-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 20000, serverForceMs: 5000, label: 'T049 deployment' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/runtime_e2e_server.py', 'launch', '--owned-dir', dir],
    { cwd: root, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 120000, label: 'T049 deployment' });
  const [, seedText, url] = READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1200, height: 1400 } });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  // the fixture set up the owner (it created the owner's browser grant through its route);
  // the browser logs in as that owner
  const loggedIn = await page.evaluate(async ({ base, password }) => (await fetch(base + 'session/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password }),
  })).status, { base, password: PASSWORD });
  assert.equal(loggedIn, 200);
  async function restart() {
    const again = waitForOwnedChildOutput(server, { pattern: RESTARTED, timeoutMs: 120000, label: 'T049 restart',
      maxOutputChars: 65536 });
    server.stdin.write('restart\n');
    await again;
  }
  return { page, url, errors, seed: JSON.parse(seedText), restart };
}

async function owner(page, path, body) {
  return page.evaluate(async ({ base, path, body }) => {
    const session = await (await fetch(base + 'session')).json();
    const response = await fetch(base + path, { method: 'POST', body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrf_token } });
    return { status: response.status, body: await response.json().catch(() => null) };
  }, { base, path, body });
}

async function read(page, path) {
  return page.evaluate(async ({ base, path }) => {
    const response = await fetch(base + path);
    return { status: response.status, body: await response.json().catch(() => null) };
  }, { base, path });
}

async function startRun(page, seed, graphRef) {
  const inputs = { graph_ref: graphRef, work_revision_ref: seed.work_revision_ref,
    environment_ref: seed.environment_ref, budget_policy_ref: seed.budget_policy_ref };
  const consent = await owner(page, 'api/v1/run-consents', { schema_version: 'run-consent-command-v1',
    command_id: crypto.randomUUID(), ...inputs });
  assert.equal(consent.status, 201, JSON.stringify(consent.body));
  return owner(page, 'api/v1/runs', { command_id: crypto.randomUUID(), ...inputs, consent_ref: consent.body.ref });
}

async function choose(page, runId) {
  await page.getByRole('combobox', { name: '관제할 실행 선택' }).selectOption(runId);
  await page.locator(`#run-panel[data-run-id="${runId}"]`).waitFor();
}

async function imageLoaded(page, selector) {
  await page.waitForFunction(sel => {
    const image = document.querySelector(sel);
    return image && image.complete && image.naturalWidth > 0;
  }, selector);
  return page.evaluate(sel => {
    const image = document.querySelector(sel);
    return { width: image.naturalWidth, height: image.naturalHeight, src: image.getAttribute('src') };
  }, selector);
}

async function preview(page, role) {
  await page.locator('#run-artifacts li', { hasText: `${role} ·` }).getByRole('button', { name: '미리보기' }).click();
}

async function panelRows(page) {
  return page.locator('#run-panel li').allTextContents();
}

async function snapshotRuns(page) {
  const snapshot = await read(page, 'api/v1/snapshot');
  assert.equal(snapshot.status, 200);
  return snapshot.body.state.runs;
}

async function ensureSession(page) {
  // after the server restart the browser session is re-read; a lost one logs in again
  const status = await page.evaluate(async base => (await fetch(base + 'session')).status, base);
  if (status === 200) return 'kept';
  const login = await page.evaluate(async ({ base, password }) => (await fetch(base + 'session/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password }) })).status, { base, password: PASSWORD });
  assert.equal(login, 200);
  return 'logged_in_again';
}

test('producers → consumer over real browser, document and fetch workers, with restart, recovery and cancel',
  { timeout: 600000, skip: rootOnly }, async t => {
    const { page, url, errors, seed, restart } = await openDeployment(t);

    // the owner's persisted browser grant the graph binds: active, pure navigation to the three pages
    const grants = (await read(page, 'api/v1/browser-grants')).body.grants;
    const grant = grants.find(item => item.grant_id === seed.grant_ref.id);
    assert.equal(grant.state, 'active', JSON.stringify(grants));
    assert.deepEqual(grant.tools, ['browser_read', 'browser_screenshot']);
    assert.deepEqual(grant.projection.entries.map(entry => [entry.url, entry.parameters]),
      [['https://granted.test/report', []], ['https://granted.test/chart', []], ['https://granted.test/slow-once', []]]);
    assert.deepEqual(grant.projection.data_sources, []);

    // --- run A: three producers in parallel, the join, then the owner's gate
    const started = await startRun(page, seed, seed.graphs.main);
    assert.equal(started.status, 201, JSON.stringify(started.body));
    const runA = started.body.run_id;
    assert.equal(started.body.phase, 'awaiting_human', JSON.stringify(started.body.outcome));
    assert.deepEqual(started.body.outcome.awaiting_human, [['release-gate', 'release-output']]);
    assert.deepEqual([...started.body.outcome.completed_node_ids].sort(), ['documents', 'gather', 'page-reader', 'page-shooter']);
    // one real browser attempt per browser role, each observed terminal by control
    const attemptsA = started.body.cancellation.attempts;
    assert.deepEqual(attemptsA.map(item => [item.attempt_no, item.phase, item.remote_terminal_observed]),
      [[1, 'terminal', 'succeeded'], [1, 'terminal', 'succeeded']]);
    assert.equal(new Set(attemptsA.map(item => item.attempt_id)).size, 2);

    // --- run B: the reader's first read outlasts its 3 s deadline (the node fails; the run stops unfinished)
    const before = new Set((await snapshotRuns(page)).map(row => row.id));
    const failed = await startRun(page, seed, seed.graphs.recovery);
    assert.equal(failed.status, 503, JSON.stringify(failed.body));
    const runB = (await snapshotRuns(page)).map(row => row.id).find(id => !before.has(id));
    assert.match(runB, /^[0-9a-f-]{36}$/);
    const beforeRestartB = (await read(page, `api/v1/runs/${runB}`)).body.cancellation.attempts;

    // --- the observe page: graph states, one row per attempt, every artifact viewable
    await page.goto(url + 'observe.html');
    await choose(page, runA);
    const graph = page.locator('#run-graph');
    await graph.getByText('노드 6개', { exact: false }).waitFor();
    assert.deepEqual(await graph.locator('.graph-nodes button').allTextContents(), [
      'documents · 정해진 처리 · 완료', 'page-reader · 에이전트 · 완료', 'page-shooter · 에이전트 · 완료',
      'gather · 합류 · 완료', 'release-gate · 사람 승인 · 승인 대기', 'consumer · 정해진 처리 · 미방문']);
    await graph.getByRole('button', { name: 'page-reader · 에이전트 · 완료' }).click();
    assert.match(await graph.locator('.graph-details').textContent(), /보고서 페이지를 읽는다/);
    // the run detail (UI phase 3): a selected node lists its own outputs; "실행 전체 보기"
    // returns to the whole run's list
    await page.locator('#run-artifacts [role=status][data-state=filtered]', { hasText: '의 산출물 1개' }).waitFor();
    assert.deepEqual((await page.locator('#run-artifacts li[data-artifact-id] .artifact-label').allTextContents())
      .map(label => label.split(' · ').slice(0, 2).join(' · ')), ['page_text · page-reader']);
    await page.locator('#run-selection').getByRole('button', { name: '실행 전체 보기' }).click();
    const panel = page.locator('#run-panel');
    assert.equal(await panel.getAttribute('data-phase'), 'awaiting_human');
    const rowsBefore = await panelRows(page);
    for (const item of attemptsA) {
      assert.ok(rowsBefore.includes(`시도 1 호출 ${item.attempt_id}: 게이트 닫힘, 원격 종료 확인됨 (succeeded)`), rowsBefore.join('\n'));
    }
    assert.ok(rowsBefore.includes('release-gate: 사람 대기, 수행 0회, 산출물 0건, 대기 근거: release-output'));

    const listedBefore = (await read(page, `api/v1/runs/${runA}/artifacts`)).body.artifacts;
    assert.deepEqual(listedBefore.map(item => item.role).sort(), PRODUCER_ROLES);
    const byRole = Object.fromEntries(listedBefore.map(item => [item.role, item]));
    assert.deepEqual([byRole.page_text.node_id, byRole.screenshot.node_id, byRole.paper.node_id, byRole.table.node_id,
      byRole.figure.node_id], ['page-reader', 'page-shooter', 'documents', 'documents', 'documents']);
    await page.locator('#run-artifacts').getByText('산출물 5개', { exact: true }).waitFor();
    const viewer = page.locator('#run-artifacts .artifact-viewer');
    // the PDF: page 1 rendered by the isolated document worker
    await preview(page, 'paper');
    await viewer.getByText('전체 1쪽 중 1쪽 표시', { exact: false }).waitFor();
    const pdfPage = await imageLoaded(page, '#run-artifacts img.artifact-page');
    assert.match(pdfPage.src, /\/pages\/1\/image$/);
    assert.match(await viewer.textContent(), /문서 변환 워커|isolated document worker/);
    // the CSV table, cell by cell
    await preview(page, 'table');
    await viewer.locator('table.artifact-table').waitFor();
    const cells = await viewer.locator('table.artifact-table tr').evaluateAll(rows => rows.map(row =>
      [...row.querySelectorAll('td')].map(cell => cell.textContent)));
    assert.deepEqual(cells, [['region', 'quarter', 'units'], ['north', 'Q3', '120'], ['south', 'Q3', '75'],
      ['east', 'Q3', '42'], ['west', 'Q3', '63']]);
    // the figure the adapter drew and the screenshot the browser worker took
    await preview(page, 'figure');
    const figure = await imageLoaded(page, `#run-artifacts img.artifact-image[src*="${byRole.figure.artifact_id}"]`);
    assert.deepEqual([figure.width, figure.height], [240, 120]);
    await preview(page, 'screenshot');
    const shotSelector = `#run-artifacts img.artifact-image[src*="${byRole.screenshot.artifact_id}"]`;
    const shot = await imageLoaded(page, shotSelector);
    assert.deepEqual([shot.width, shot.height], [320, 200]);
    const shotPixels = await page.evaluate(sel => {
      const image = document.querySelector(sel);
      const canvas = document.createElement('canvas');
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const context = canvas.getContext('2d');
      context.drawImage(image, 0, 0);
      return [[...context.getImageData(80, 100, 1, 1).data].slice(0, 3), [...context.getImageData(240, 100, 1, 1).data].slice(0, 3)];
    }, shotSelector);
    assert.deepEqual(shotPixels, [[220, 30, 30], [30, 30, 220]]);  // the chart page was really rendered
    // the page text the browser worker read (scripts never run in the worker)
    await preview(page, 'page_text');
    assert.match(await viewer.locator('pre.artifact-text').textContent(), /Revenue grew 12 percent in the third quarter\./);
    await page.screenshot({ path: join(tmpdir(), 'deeptwin-t049-before-restart.png'), fullPage: true });

    // --- crash (SIGKILL) and restart the server while run A waits on the owner: the trace is unchanged
    await restart();
    await page.goto(url + 'observe.html');
    const session = await ensureSession(page);
    await page.goto(url + 'observe.html');
    await choose(page, runA);
    await page.locator('#run-panel[data-phase=awaiting_human]').waitFor();
    assert.deepEqual(await panelRows(page), rowsBefore);
    const listedAfter = (await read(page, `api/v1/runs/${runA}/artifacts`)).body.artifacts;
    assert.deepEqual(listedAfter, listedBefore);

    // --- the owner approves the gate and resumes: the consumer reads every producer artifact whole
    const screen = page.locator('#run-approvals');
    await screen.getByRole('button', { name: '승인: release-gate/release-output' }).click();
    await screen.getByText('결정을 기록했습니다.', { exact: false }).waitFor();
    await panel.getByRole('button', { name: '이어서 진행' }).click();
    await page.locator('#run-panel[data-phase=completed]').waitFor();
    await page.goto(url + 'observe.html');  // the graph view and artifacts are read on selection
    await choose(page, runA);
    await graph.getByRole('button', { name: 'consumer · 정해진 처리 · 완료' }).waitFor();
    assert.deepEqual((await graph.locator('.graph-nodes button').allTextContents()).map(label => label.split(' · ').pop()),
      ['완료', '완료', '완료', '완료', '완료', '완료']);
    await page.locator('#run-artifacts').getByText('산출물 6개', { exact: true }).waitFor();
    const listedDone = (await read(page, `api/v1/runs/${runA}/artifacts`)).body.artifacts;
    const report = listedDone.find(item => item.role === 'report');
    assert.equal(report.node_id, 'consumer');
    // run A's attempts are still exactly the two producer attempts: nothing was sent again
    const doneA = (await read(page, `api/v1/runs/${runA}`)).body;
    assert.deepEqual(doneA.cancellation.attempts.map(item => item.attempt_id).sort(),
      attemptsA.map(item => item.attempt_id).sort());
    await preview(page, 'report');
    const reportText = await viewer.locator('pre.artifact-text').textContent();
    const parsed = await page.evaluate(async ({ base, runId, artifactId }) => (await fetch(
      `${base}api/v1/runs/${runId}/artifacts/${artifactId}/content`)).json(), { base, runId: runA, artifactId: report.artifact_id });
    // the consumer's inputs are exactly the producers' artifacts: digest, size, result record, ordinal
    const ref = value => `${value.kind}:${value.id}:${value.version}:${value.sha256}`;
    const key = item => [item.role, item.sha256, item.size, ref(item.result_ref), item.ordinal];
    assert.deepEqual(parsed.inputs.map(key).sort(), listedBefore.map(key).sort());
    for (const item of listedBefore) assert.ok(reportText.includes(item.sha256), `the report shows ${item.role}'s digest`);
    const reads = Object.fromEntries(parsed.inputs.map(item => [item.role, item.read]));
    assert.equal(reads.paper.by, 'isolated document worker (extract_pdf_text)');
    assert.deepEqual([reads.paper.page_count, reads.paper.has_title, reads.paper.has_every_region], [1, true, true]);
    assert.deepEqual([reads.table.rows, reads.table.units_total], [5, 300]);
    assert.deepEqual([reads.screenshot.width, reads.screenshot.height, reads.figure.width, reads.figure.height],
      [320, 200, 240, 120]);
    assert.equal(reads.page_text.mentions_revenue, true);
    await page.screenshot({ path: join(tmpdir(), 'deeptwin-t049-completed.png'), fullPage: true });

    // --- run B: the owner's recovery makes the reader's attempt 2; then the owner cancels mid-run
    await choose(page, runB);
    await page.locator(`#run-panel[data-run-id="${runB}"][data-phase=running]`).waitFor();
    const firstB = (await read(page, `api/v1/runs/${runB}`)).body.cancellation.attempts;
    assert.deepEqual(firstB, beforeRestartB);  // run B's trace survived the restart too
    assert.ok(firstB.some(item => item.attempt_no === 1 && item.remote_terminal_observed === 'timed_out'), JSON.stringify(firstB));
    await panel.getByRole('button', { name: '복구 시도' }).click();
    await page.locator(`#run-panel[data-run-id="${runB}"][data-phase=awaiting_human]`).waitFor();
    const attemptsB = (await read(page, `api/v1/runs/${runB}`)).body.cancellation.attempts;
    assert.deepEqual(attemptsB.map(item => [item.attempt_no, item.remote_terminal_observed]).sort(),
      [[1, 'succeeded'], [1, 'timed_out'], [2, 'succeeded']]);
    assert.equal(new Set(attemptsB.map(item => item.attempt_id)).size, 3);
    for (const item of firstB) assert.ok(attemptsB.some(other => other.attempt_id === item.attempt_id));
    const rowsB = await panelRows(page);
    for (const item of attemptsB) {
      assert.ok(rowsB.some(row => row.startsWith(`시도 ${item.attempt_no} 호출 ${item.attempt_id}: `)), rowsB.join('\n'));
    }
    await panel.getByRole('button', { name: '새 작업 보내기 중단' }).click();
    await page.locator(`#run-panel[data-run-id="${runB}"][data-phase=cancelled]`).waitFor();
    const cancelledRows = await panelRows(page);
    assert.equal(cancelledRows[0], '취소 요청됨: 새 작업 보내기 중단');
    for (const item of attemptsB) {
      assert.ok(cancelledRows.some(row => row.startsWith(`시도 ${item.attempt_no} 호출 ${item.attempt_id}: `)), cancelledRows.join('\n'));
    }
    const cancelledB = (await read(page, `api/v1/runs/${runB}`)).body;
    assert.equal(cancelledB.phase, 'cancelled');
    assert.deepEqual(cancelledB.cancellation.attempts.map(item => item.attempt_id).sort(),
      attemptsB.map(item => item.attempt_id).sort());
    const listedB = (await read(page, `api/v1/runs/${runB}/artifacts`)).body.artifacts;
    assert.deepEqual(listedB.map(item => item.role).sort(), PRODUCER_ROLES);
    await page.screenshot({ path: join(tmpdir(), 'deeptwin-t049-cancelled.png'), fullPage: true });
    console.log(`T049 evidence: session after restart ${session}; run A ${runA} attempts `
      + `${attemptsA.map(item => item.attempt_id).join(',')}; run B ${runB} attempts `
      + `${attemptsB.map(item => `${item.attempt_no}:${item.remote_terminal_observed}:${item.attempt_id}`).join(',')}; `
      + `artifacts ${listedBefore.map(item => `${item.role}=${item.sha256}`).join(' ')} report=${report.sha256}`);
    assert.deepEqual(errors, []);
  });
