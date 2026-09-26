// UI phase 5 (docs/ui/2026-09-26-product-ux-redesign.md §5.2, §5.5–§5.7) in a real browser against the
// real supported server (fixtures/trace_server.py: two scripted test-actor runs — A completed, B
// waiting at its gate; no provider is called and no key is read):
// - the run list is a table whose rows open the run detail;
// - the records log filters by run and by kind (server filters) and by period (applied to the loaded
//   records, said so), and the artifact index follows the run filter;
// - the versions page is four tabs with plain empty states;
// - a frozen 내 버전 stays reachable after a reload ("내 버전 1개 · 차이 보기"), and pressing
//   차이 살펴보기 again on the same saved revision reopens that alternative instead of freezing another;
// - the feedback box lists its earlier revisions under "이전 기록 N건".

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';
import { EVENT_GROUPS } from '../static/ui-format.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const READY = /TRACE_SEED=(\{[^\n]*\})\nTRACE_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;

async function open(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  assert.equal(process.env.DEEPTWIN_LIVE_ANTHROPIC_API_KEY, undefined, 'the trace fixture runs with the live key unset');
  const dir = await mkdtemp(join(tmpdir(), 'dt-ux5-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Trace fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/trace_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 60000, label: 'Trace fixture' });
  const [, seedText, url] = READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  const base = new URL(url).pathname;
  const status = await page.evaluate(async ({ base }) => (await fetch(base + 'session/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase' }) })).status, { base });
  assert.equal(status, 200);
  return { page, url, seed: JSON.parse(seedText), errors };
}

test('the run list table opens a run; records filter by run and kind; versions are tabs', { timeout: 150000 }, async t => {
  const { page, url, seed, errors } = await open(t);
  // §5.2: no #run= — a table, newest first, a row per run, the facts only the trace recorded
  await page.goto(url + 'observe.html');
  const table = page.locator('#run-table table');
  await table.locator(`tr[data-run-row="${seed.run_id}"][data-state="read"]`).waitFor();
  await table.locator(`tr[data-run-row="${seed.waiting_run_id}"][data-state="read"]`).waitFor();
  assert.deepEqual(await table.locator('th').allTextContents(),
    ['업무', '환경 버전*', '상태', '시작', '걸린 시간', '비용*', '사람 대기']);
  assert.deepEqual(await table.locator('tbody tr').evaluateAll(rows => rows.map(row => row.dataset.runRow)),
    [seed.waiting_run_id, seed.run_id]);
  const done = table.locator(`tr[data-run-row="${seed.run_id}"]`);
  assert.match(await done.textContent(), /화요일 공간 안내/);
  assert.match(await done.locator('.run-cell-status').textContent(), /완료/);
  assert.equal((await done.locator('.run-cell-environment').textContent()).trim(), '—');
  assert.match(await done.locator('.run-cell-cost').textContent(), /미확인/);
  const waiting = table.locator(`tr[data-run-row="${seed.waiting_run_id}"]`);
  assert.match(await waiting.locator('.run-cell-status').textContent(), /사람 승인 대기/);
  assert.match(await waiting.locator('.run-cell-waiting').textContent(), /승인 대기 1건/);
  assert.match(await waiting.locator('.run-cell-cost').textContent(), /추정/);
  assert.match(await page.locator('#run-table .run-table-notes').textContent(), /환경 버전을 싣지 않아/);
  assert.equal(await page.locator('#run-view').isHidden(), true);
  // a row opens its detail; the header's "다른 실행" switch and "← 실행 목록" stay compact
  await done.locator('a.run-link').click();
  await page.waitForURL(new RegExp(`observe\\.html#run=${seed.run_id}$`));
  await page.locator('#run-summary .run-title', { hasText: '화요일 공간 안내' }).waitFor();
  assert.equal(await page.locator('#run-empty').isHidden(), true);
  assert.equal(await page.getByRole('combobox', { name: '다른 실행 열기' }).inputValue(), seed.run_id);
  await page.getByRole('link', { name: '← 실행 목록' }).click();
  await page.locator('#run-empty').waitFor();
  assert.equal(await page.locator('#run-view').isHidden(), true);

  // §5.7: the records log by run (the server's run_id), then by kind (its event_type), then a period
  await page.goto(`${url}records.html#run=${seed.run_id}`);
  const log = page.locator('#records-log');
  await log.locator('ol.event-log li').first().waitFor();
  const filters = page.getByRole('form', { name: '기록 거르기' });
  assert.equal(await filters.getByRole('combobox', { name: '실행 거르기' }).inputValue(), seed.run_id);
  const runTypes = await log.locator('ol.event-log > li').evaluateAll(rows => rows.map(row => row.dataset.eventType));
  assert.ok(runTypes.includes('run.started') && runTypes.includes('run.stopped'), runTypes.join());
  assert.ok(!runTypes.includes('work.created'), 'another subject\'s events are not listed');
  await filters.getByRole('combobox', { name: '종류 거르기' }).selectOption('approval');
  await page.waitForURL(new RegExp(`#run=${seed.run_id}&kind=approval$`));
  await log.locator('[role=status][data-state="listed"]').waitFor();
  const approvalTypes = new Set(EVENT_GROUPS.find(group => group.id === 'approval').types);
  const kinds = await log.locator('ol.event-log > li').evaluateAll(rows => rows.map(row => row.dataset.eventType));
  assert.ok(kinds.every(type => approvalTypes.has(type)), kinds.join());
  // kind alone, over the whole log
  await filters.getByRole('combobox', { name: '실행 거르기' }).selectOption('');
  await filters.getByRole('combobox', { name: '종류 거르기' }).selectOption('work');
  await page.waitForURL(/#kind=work$/);
  await log.locator('ol.event-log li[data-event-type="work.created"]').first().waitFor();
  const workTypes = new Set(EVENT_GROUPS.find(group => group.id === 'work').types);
  assert.ok((await log.locator('ol.event-log > li').evaluateAll(rows => rows.map(row => row.dataset.eventType)))
    .every(type => workTypes.has(type)));
  await filters.getByRole('combobox', { name: '기간 거르기' }).selectOption('24h');
  await log.locator('[role=status]', { hasText: /불러온 사건 \d+개 중 기간에 맞는 \d+개/ }).waitFor();
  assert.match(await filters.textContent(), /기간은 서버가 거르지 않아, 지금까지 불러온 기록 안에서만 거릅니다/);
  // a link names the filter (a new load; only the hash differs, so reload); the artifact index follows a run filter
  await page.goto(`${url}records.html#run=${seed.run_id}`);
  await page.reload();
  const index = page.locator('#artifacts');
  await index.locator('.artifact-scope', { hasText: `실행 ${seed.run_id.slice(0, 8)}의 산출물만 봅니다` }).waitFor();
  await index.locator('.artifact-index-list li').first().waitFor();
  assert.deepEqual([...new Set(await index.locator('.artifact-index-list li').evaluateAll(rows => rows.map(row => row.dataset.runId)))],
    [seed.run_id]);

  // §5.6: versions and experiments are four tabs, each with a plain empty state
  await page.goto(url + 'versions.html');
  const versions = page.locator('#versions');
  await versions.getByRole('tab', { name: '운영 버전' }).waitFor();
  assert.deepEqual(await versions.getByRole('tab').allTextContents(), ['운영 버전', '후보', '실험', '승인·적용·롤백']);
  await versions.getByText('아직 운영 버전이 없습니다. 새 환경에서는 정상입니다.').waitFor();
  await versions.getByRole('tab', { name: '후보' }).click();
  await versions.getByText('검증을 마친 후보가 없습니다.').waitFor();
  await versions.getByRole('tab', { name: '실험' }).click();
  await versions.getByText('기록된 성장 실험이 없습니다.').waitFor();
  await versions.getByText('기록된 비교 라운드가 없습니다', { exact: false }).waitFor();
  await versions.getByRole('tab', { name: '승인·적용·롤백' }).click();
  await versions.getByText('결정할 후보도, 되돌릴 이전 버전도 없습니다.').waitFor();
  assert.equal(await versions.getByRole('button', { name: '승인' }).count(), 0);
  // keyboard: the tabs move with the arrow keys
  await versions.getByRole('tab', { name: '승인·적용·롤백' }).press('Home');
  assert.equal(await versions.getByRole('tab', { name: '운영 버전' }).getAttribute('aria-selected'), 'true');
  assert.deepEqual(errors, []);
});

test('a frozen 내 버전 stays reachable after a reload, and the feedback box lists its earlier records', { timeout: 150000 }, async t => {
  const { page, url, seed, errors } = await open(t);
  const posted = [];
  page.on('request', request => { if (request.method() === 'POST') posted.push(new URL(request.url()).pathname); });
  await page.goto(`${url}observe.html#run=${seed.run_id}`);
  const final = page.locator('#run-final .final-result');
  await final.first().waitFor();
  assert.equal(await final.locator('.own-version-line').isHidden(), true, 'no own version yet');
  await final.getByRole('button', { name: '내 버전 만들기' }).click();
  const area = page.getByRole('textbox', { name: '내 버전 텍스트' });
  await area.fill((await area.inputValue()).replace('3층 세미나실', '4층 큰 회의실'));
  await page.locator('#run-alternative [role=status]', { hasText: '자동 저장됨 (수정본 1)' }).waitFor();
  await page.getByRole('button', { name: '차이 살펴보기' }).click();
  await page.locator('#run-difference .difference-status', { hasText: '관측한 차이입니다' }).waitFor();
  assert.equal(posted.filter(path => path.endsWith('/freeze')).length, 1);

  // two feedback revisions on the whole result
  const runBox = page.locator('#run-final [data-feedback-for="feedback-run"]');
  await runBox.getByRole('button', { name: '확인 필요', exact: true }).click();
  await runBox.getByRole('button', { name: '저장', exact: true }).click();
  await runBox.locator('.feedback-status', { hasText: '저장됨' }).waitFor();
  assert.equal(await runBox.locator('.feedback-history').isHidden(), true, 'a first record has no earlier one');
  await runBox.getByRole('button', { name: '괜찮음', exact: true }).click();
  await runBox.getByRole('button', { name: '메모 쓰기' }).click();
  await runBox.getByRole('textbox', { name: /메모/ }).fill('test-actor: 다시 보니 괜찮습니다.');
  await runBox.getByRole('button', { name: '저장', exact: true }).click();
  await runBox.locator('.feedback-history summary', { hasText: '이전 기록 1건' }).waitFor();

  // a reload: the difference is one click away on the result it answers, without a new freeze
  await page.reload();
  await final.first().waitFor();
  const line = final.locator('.own-version-line');
  await line.waitFor();
  assert.match(await line.textContent(), /내 버전 1개 · 차이 살펴본 수정본 1개/);
  const freezesBefore = posted.filter(path => path.endsWith('/freeze')).length;
  await line.getByRole('button', { name: 'report의 내 버전 차이 보기' }).click();
  const view = page.locator('#run-final #run-difference');
  await view.locator('.difference-status', { hasText: '관측한 차이입니다' }).waitFor();
  assert.match(await view.locator('.difference-part').first().textContent(), /3층 세미나실/);
  assert.match(await view.locator('.difference-part-mine').textContent(), /4층 큰 회의실/);
  // pressing 차이 살펴보기 again on the same saved revision reopens the sealed alternative
  await final.getByRole('button', { name: '내 버전 만들기' }).click();
  await page.locator('#run-alternative [role=status]', { hasText: '저장된 내 버전을 이어서 편집합니다' }).waitFor();
  await page.getByRole('button', { name: '차이 살펴보기' }).click();
  await page.locator('#run-alternative').getByText('이미 고정했습니다', { exact: false }).waitFor();
  await view.locator('.difference-status', { hasText: '관측한 차이입니다' }).waitFor();
  assert.equal(posted.filter(path => path.endsWith('/freeze')).length, freezesBefore, 'no second freeze');
  const frozen = await page.evaluate(async runId => {
    const base = location.pathname.replace(/[^/]*$/, '');
    const artifacts = await (await fetch(`${base}api/v1/runs/${runId}/artifacts`)).json();
    const report = artifacts.artifacts.find(item => item.role === 'report');
    return (await (await fetch(`${base}api/v1/runs/${runId}/artifacts/${report.artifact_id}/drafts`)).json()).drafts[0].frozen_alternatives;
  }, seed.run_id);
  assert.equal(frozen.length, 1);

  // the feedback's earlier record, read only when the owner opens it
  const history = runBox.locator('.feedback-history');
  assert.match(await history.locator('summary').textContent(), /이전 기록 1건/);
  await history.locator('summary').click();
  await history.locator('li[data-revision="1"]').waitFor();
  assert.match(await history.textContent(), /수정본 1 · 확인 필요/);
  assert.deepEqual(errors, []);
});
