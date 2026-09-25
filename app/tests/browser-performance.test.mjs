// T080: browser responsiveness under the plan's declared workload, in a real Chromium
// against the real supported server (test-owned fixture, synthetic data). Measured in
// the page itself with performance.now():
//   - command acknowledgment: typing a work description and saving it until the save
//     status names the new revision (the owner's visible acknowledgment), N samples;
//   - core event visibility: a committed work revision until the first event read after
//     it returns that revision's event (matched by its object ref) (the server has no push channel: this is the
//     read-your-writes delay a reader sees, not a live UI update);
//   - the 1,000-event records log: first page, then every "다음 기록 보기" page until all
//     1,000 seeded events are listed;
//   - main-thread long tasks while typing and while opening the 20-node / 40-edge run.
// Results (with browser, CPU, memory and sample counts) are written as JSON to
// DEEPTWIN_PERF_OUT when set. The plan's targets are asserted: ack p95 < 500 ms, event
// p95 < 1 s, no long task > 200 ms in the measured interactions.

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { cpus, tmpdir, totalmem, release } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = `/${'2'.repeat(32)}/`;
const READY = /PERFORMANCE_SEED=(\{[^\n]*\})\nPERFORMANCE_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
const SAMPLES = 30;

function stats(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const at = q => sorted[Math.min(sorted.length - 1, Math.ceil(q * sorted.length) - 1)];
  const round = value => Math.round(value * 10) / 10;
  return { samples: sorted.length, min: round(sorted[0]), p50: round(at(0.5)), p95: round(at(0.95)),
    max: round(sorted[sorted.length - 1]) };
}

async function openFixture(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-performance-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Performance fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/performance_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 60000, label: 'Performance fixture' });
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
  })).status, { base, capability: Buffer.alloc(32, 'T').toString('base64url') });
  assert.equal(bootstrapped, 201);
  return { browser, page, url, seed, errors };
}

// observe main-thread long tasks from now on; `take()` returns and clears them
async function watchLongTasks(page) {
  await page.evaluate(() => {
    window.__longTasks = [];
    new PerformanceObserver(list => { for (const entry of list.getEntries()) window.__longTasks.push(entry.duration); })
      .observe({ type: 'longtask', buffered: false });
  });
  return async () => page.evaluate(() => window.__longTasks.splice(0));
}

test('responsiveness under the declared workload', { timeout: 600000 }, async t => {
  const { browser, page, url, seed, errors } = await openFixture(t);
  const results = { measured_at: new Date().toISOString(), workload: { graph_nodes: 20, graph_edges: 40, events: 1000 },
    environment: { browser: browser.version(), cpu: cpus()[0]?.model ?? null, cpu_count: cpus().length,
      memory_bytes: totalmem(), os_release: release(), headless: true, server: 'uvicorn, one process, local loopback' } };

  // 1. command acknowledgment on the work screen (typing, save, visible "수정본 N")
  await page.goto(url + 'work.html');
  await page.locator('#work-description').waitFor();
  const takeTyping = await watchLongTasks(page);
  const acks = [];
  for (let index = 0; index < SAMPLES; index += 1) {
    const elapsed = await page.evaluate(async revision => {
      const area = document.getElementById('work-description');
      const status = document.getElementById('save-status');
      const started = performance.now();
      area.value = `측정용 업무 설명 ${revision}: 분기 보고서 초안을 세 문단으로 정리한다.`;
      area.dispatchEvent(new Event('input', { bubbles: true }));
      document.querySelector('#work-form button[type=submit]').click();
      while (!status.textContent.includes(`수정본 ${revision}`)) {
        if (performance.now() - started > 10000) throw new Error(`no acknowledgment for revision ${revision}`);
        await new Promise(resolve => requestAnimationFrame(resolve));
      }
      return performance.now() - started;
    }, index + 1);
    acks.push(elapsed);
  }
  results.command_acknowledgment_ms = stats(acks);

  // typing: 2,000 characters through real key events
  await page.locator('#work-description').fill('');
  const typedStarted = Date.now();
  await page.locator('#work-description').pressSequentially('가나다라마바사아자차카타파하 '.repeat(143).slice(0, 2000), { delay: 0 });
  results.typing = { characters: 2000, wall_ms: Date.now() - typedStarted, long_tasks_ms: await takeTyping() };

  // 2. core event visibility after commit (read-your-writes through GET /api/v1/events)
  const visibility = await page.evaluate(async ({ base, samples }) => {
    const session = await (await fetch(base + 'session')).json();
    const headers = { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrf_token };
    const created = await (await fetch(base + 'api/v1/works', { method: 'POST', headers, body: JSON.stringify({
      schema_version: 'work-create-command-v1', command_id: crypto.randomUUID(), text: '이벤트 측정' }) })).json();
    let cursor = null;
    for (;;) {  // page to the end of the journal once
      const query = new URLSearchParams({ limit: '100', ...(cursor ? { cursor } : {}) });
      const page = await (await fetch(base + 'api/v1/events?' + query)).json();
      if (!page.events.length || !page.next_cursor) break;
      cursor = page.next_cursor;
    }
    const delays = [];
    for (let index = 0; index < samples; index += 1) {
      const commandId = crypto.randomUUID();
      const response = await fetch(base + `api/v1/works/${created.work_id}/revisions`, { method: 'POST', headers,
        body: JSON.stringify({ schema_version: 'work-revise-command-v1', command_id: commandId,
          expected_revision: index + 1, text: `이벤트 측정 ${index}` }) });
      if (!response.ok) throw new Error(`revision ${index} refused: ${response.status}`);
      const committed = performance.now();
      let seen = false;
      while (!seen) {
        const query = new URLSearchParams({ limit: '50', ...(cursor ? { cursor } : {}) });
        const page = await (await fetch(base + 'api/v1/events?' + query)).json();
        if (page.next_cursor) cursor = page.next_cursor;
        // public events carry no correlation id; the revision's own object ref names it
        seen = page.events.some(event => (event.object_refs ?? []).some(ref =>
          ref.kind === 'work_revision' && ref.id === created.work_id && ref.version === index + 2));
        if (!seen && performance.now() - committed > 10000) throw new Error('event never became visible');
      }
      delays.push(performance.now() - committed);
    }
    return delays;
  }, { base, samples: SAMPLES });
  results.event_visible_after_commit_ms = stats(visibility);

  // 3. the 1,000-event records log, paged by the owner
  await page.goto(url + 'records.html');
  const log = await page.evaluate(async () => {
    const started = performance.now();
    const status = () => document.querySelector('#records-logs [role=status]')?.textContent ?? '';
    const rows = () => document.querySelectorAll('#records-logs ol.event-log li').length;
    const wait = async predicate => {
      const began = performance.now();
      while (!predicate()) {
        if (performance.now() - began > 20000) throw new Error('records log stalled');
        await new Promise(resolve => requestAnimationFrame(resolve));
      }
      return performance.now() - began;
    };
    await wait(() => rows() > 0);
    const first = performance.now() - started;
    const pages = [];
    for (;;) {
      const more = [...document.querySelectorAll('#records-logs button')].find(button => button.textContent === '다음 기록 보기');
      if (!more || more.hidden) break;
      const before = rows();
      more.click();
      // the page after the last one is empty and hides the button
      const took = await wait(() => rows() > before || more.hidden);
      if (rows() > before) pages.push(took);
    }
    return { first_page_ms: first, next_page_ms: pages, rows: rows(), total_ms: performance.now() - started,
      status: status() };
  });
  assert.ok(log.rows >= 1000, `the log listed ${log.rows} events`);
  results.records_log = { rows: log.rows, first_page_ms: Math.round(log.first_page_ms), total_ms: Math.round(log.total_ms),
    next_page_ms: stats(log.next_page_ms) };

  // 4. starting and opening the 20-node / 40-edge run on the observe page
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
  await page.goto(url + 'observe.html');
  const takeSelection = await watchLongTasks(page);
  const picker = page.getByRole('combobox', { name: '관제할 실행 선택' });
  await picker.waitFor();
  const selectStarted = Date.now();
  await picker.selectOption(runId);
  await page.locator('#run-panel li, li', { hasText: 'n19' }).first().waitFor();
  results.run_view = { nodes: 20, open_wall_ms: Date.now() - selectStarted, long_tasks_ms: await takeSelection() };

  if (process.env.DEEPTWIN_PERF_OUT) await writeFile(process.env.DEEPTWIN_PERF_OUT, JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 1));
  assert.deepEqual(errors, []);
  assert.ok(results.command_acknowledgment_ms.p95 < 500, `ack p95 ${results.command_acknowledgment_ms.p95} ms`);
  assert.ok(results.event_visible_after_commit_ms.p95 < 1000, `event p95 ${results.event_visible_after_commit_ms.p95} ms`);
  for (const [label, tasks] of [['typing', results.typing.long_tasks_ms], ['run view', results.run_view.long_tasks_ms]]) {
    assert.ok(tasks.every(duration => duration <= 200), `${label} long tasks ${tasks.join(', ')} ms`);
  }
});
