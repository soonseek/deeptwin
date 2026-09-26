// UI phase 3 (§5.3 of docs/ui/2026-09-26-product-ux-redesign.md): the run detail screen in a
// real browser against the real supported server (fixtures/trace_server.py). The fixture's
// scripted test actor ran a graph whose trace has content in every section: a model call with
// recorded tokens, a gate the owner approved, a tool step that failed once and succeeded on
// attempt 2, and a final report. The journey: the run opens on its final result; the store
// step's attempt 1 shows its own inputs and error and none of attempt 2's outputs; the tools
// and models tab shows the tool call and the model call with its tokens; another node shows
// its own artifacts; "내 버전" opens in place from the final result and autosaves; and a run
// waiting at the gate shows the approval banner and the node marker. Synthetic evidence of
// the mechanism, never user evidence; no provider is called and no key is read.

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const READY = /TRACE_SEED=(\{[^\n]*\})\nTRACE_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;

async function open(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  assert.equal(process.env.DEEPTWIN_LIVE_ANTHROPIC_API_KEY, undefined, 'the trace fixture runs with the live key unset');
  // a short owned directory: the extension worker's socket path must fit AF_UNIX
  const dir = await mkdtemp(join(tmpdir(), 'dt-trace-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Trace fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/trace_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 60000, label: 'Trace fixture' });
  const [, seedText, url] = READY.exec(announced);
  const seed = JSON.parse(seedText);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  const base = new URL(url).pathname;
  const status = await page.evaluate(async ({ base }) => (await fetch(base + 'session/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase' }) })).status, { base });
  assert.equal(status, 200);
  return { page, url, seed, errors };
}

async function openRun(page, url, runId) {
  await page.goto(`${url}observe.html#run=${runId}`);
  await page.locator('#run-final .final-result, #run-final .empty-state').first().waitFor();
}

const node = (page, id) => page.locator(`#run-graph .graph-nodes button[data-node="${id}"]`);
const panel = (page, id) => page.locator(`#detail-${id}-panel`);

test('the run detail: final result first, attempts kept apart, calls with tokens, per-node artifacts, 내 버전 in place',
  { timeout: 150000 }, async t => {
    const { page, url, seed, errors } = await open(t);
    assert.equal(seed.label, 'synthetic/test-actor');
    await openRun(page, url, seed.run_id);

    // the header and the final result come first
    await page.locator('#run-summary .run-title', { hasText: '화요일 공간 안내' }).waitFor();
    assert.match(await page.locator('#run-summary').textContent(), /완료/);
    assert.match(await page.locator('#run-summary .run-stats').textContent(), /모델 호출 1회 · 도구 호출 2회 · 시도 2회\(재시도 1회\)/);
    assert.match(await page.locator('#run-summary .run-stats').textContent(), /입력 812 · 출력 164/);
    assert.equal(await page.locator('#run-final h2').textContent(), '최종 결과');
    const final = page.locator('#run-final .final-result');
    assert.equal(await final.count(), 1);
    assert.equal(await final.locator('h3').textContent(), 'report');
    await final.locator('.final-preview pre', { hasText: '저장 도구 기록을 확인한 최종본입니다' }).waitFor();
    assert.equal(await page.locator('#run-banner').isHidden(), true);
    // the 20-row text list is no longer the primary element, but its accessible equivalent remains
    assert.equal(await page.locator('#run-panel details.run-rows > summary').textContent(), '노드별 상태를 글로 보기');

    // the two-attempt node: latest by default, then attempt 1 with its own inputs and error
    await node(page, 'publish').click();
    const attemptPick = page.getByRole('combobox', { name: '시도 선택' });
    assert.equal(await attemptPick.inputValue(), '2');
    assert.equal(await page.locator('#run-selection .selection-error').count(), 0);
    await attemptPick.selectOption('1');
    await page.locator('#run-selection .selection-error', { hasText: '시도 1 오류' }).waitFor();
    assert.match(await page.locator('#run-selection .past-attempt').textContent(), /지난 시도입니다/);
    await page.locator('#run-artifacts [role=status]', { hasText: '시도 1의 산출물이 없습니다.' }).waitFor();
    assert.equal(await page.locator('#run-artifacts li[data-artifact-id]').count(), 0);
    await page.getByRole('tab', { name: '입력' }).click();
    assert.match(await panel(page, 'inputs').textContent(), /\(tool-gate\)/);
    assert.match(await panel(page, 'inputs').textContent(), /draft/);
    assert.match(await panel(page, 'inputs').textContent(), /test_actor_notify가 받은 정확한 입력/);
    // attempt 1's own tool call, failed; never attempt 2's
    await page.getByRole('tab', { name: '도구·모델' }).click();
    const calls = panel(page, 'calls');
    assert.equal(await calls.locator('.call-item').count(), 1);
    assert.match(await calls.locator('.call-item').textContent(), /test_actor_notify/);
    assert.match(await calls.locator('.call-item').textContent(), /publish · 시도 1/);
    assert.match(await calls.locator('.call-item .status-chip').first().textContent(), /실패/);
    // the records tab links to the records page filtered to this run
    await page.getByRole('tab', { name: '기록' }).click();
    assert.equal(await panel(page, 'records').locator('a.records-link').getAttribute('href'), `./records.html#run=${seed.run_id}`);

    // attempt 2 again: its successful tool call
    await attemptPick.selectOption('2');
    await page.getByRole('tab', { name: '도구·모델' }).click();
    assert.match(await calls.locator('.call-item').textContent(), /publish · 시도 2/);

    // the writer: the model call with its recorded tokens and an honest unknown cost
    await node(page, 'writer').click();
    await calls.locator('.call-item', { hasText: '모델 호출' }).waitFor();
    const model = calls.locator('.call-item', { hasText: '모델 호출' });
    assert.match(await model.textContent(), /입력 812 · 출력 164/);
    assert.match(await model.textContent(), /미확인/);
    assert.match(await model.textContent(), /숨은 추론은 저장하지 않으므로 볼 수 없습니다/);

    // a different node shows THAT node's artifacts
    await page.getByRole('tab', { name: '산출물' }).click();
    await page.locator('#run-artifacts [role=status]', { hasText: '수행 1의 산출물 1개' }).waitFor();
    assert.deepEqual(await page.locator('#run-artifacts li[data-artifact-id] .artifact-label').allTextContents(),
      [await page.locator('#run-artifacts li[data-artifact-id] .artifact-label').first().textContent()]);
    assert.match(await page.locator('#run-artifacts li[data-artifact-id] .artifact-label').first().textContent(), /^draft · writer/);
    await node(page, 'intake').click();
    await page.locator('#run-artifacts li[data-artifact-id] .artifact-label', { hasText: /^source · intake/ }).waitFor();
    assert.equal(await page.locator('#run-artifacts li[data-artifact-id]').count(), 1);
    // the timeline shares the selection
    await page.getByRole('tab', { name: '타임라인' }).click();
    await page.locator('#run-timeline button.timeline-entry[data-node="publish"][data-attempt="1"]').click();
    assert.equal(await attemptPick.inputValue(), '1');
    assert.equal(await page.locator('#run-timeline button.timeline-entry[data-node="publish"][data-attempt="1"]').getAttribute('aria-pressed'), 'true');
    await page.getByRole('tab', { name: '그래프' }).click();

    // 내 버전 opens in place from the final result: the title names the artifact, role and step
    await final.getByRole('button', { name: '내 버전 만들기' }).click();
    const editor = final.locator('#run-alternative');
    await editor.waitFor();
    assert.match(await editor.locator('.alternative-title').textContent(), /내 버전 — report \(최종 안내문을 보고서로 묶는다 · 수행 1\)/);
    const area = page.getByRole('textbox', { name: '내 버전 텍스트' });
    await area.fill((await area.inputValue()).replace('3층 세미나실', '4층 큰 회의실'));
    await page.locator('#run-alternative [role=status]', { hasText: '자동 저장됨 (수정본 1)' }).waitFor();
    assert.equal(await page.getByRole('button', { name: '차이 살펴보기' }).count(), 1);
    assert.equal(await page.getByRole('button', { name: '분석용으로 고정' }).count(), 0);
    assert.deepEqual(errors, []);

    await t.test('a run waiting at the gate shows the approval banner and the node marker', async () => {
      await openRun(page, url, seed.waiting_run_id);
      await page.locator('#run-banner', { hasText: '사람 승인이 필요합니다.' }).waitFor();
      assert.match(await page.locator('#run-banner').textContent(), /tool-gate/);
      assert.match(await node(page, 'tool-gate').textContent(), /승인 대기/);
      await page.locator('#run-final', { hasText: '아직 최종 결과가 없습니다.' }).waitFor();
      await page.getByRole('button', { name: '승인 화면 열기' }).click();
      await page.locator('#run-approvals button').first().waitFor();
      assert.deepEqual(errors, []);
    });
  });
