// T054 (US4, SC-006): the owner's own version in a real browser against the real
// supported server. A run that produced a text and a CSV artifact is started through
// the owner's own consent and run routes; the observe page lists its artifacts; the
// in-place editor autosaves revisions, switches between the original, the owner's
// version and the observed differences, survives a page refresh, and recovers from a
// stale tab's conflicting save (reload the newer revision, or keep the text as a new
// draft) without ever overwriting. Everything the owner "types" here is a scripted
// test actor: this is synthetic evidence of the mechanism, never user evidence.

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
const READY = /ALTERNATIVES_SEED=(\{[^\n]*\})\nALTERNATIVES_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;

async function open(t) {
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

async function openEditor(page, url, runId, role = 'report') {
  await page.goto(url + 'observe.html');
  await page.getByRole('combobox', { name: '관제할 실행 선택' }).selectOption(runId);
  const row = page.locator('li', { hasText: `${role} ·` });
  await row.getByRole('button', { name: '내 버전 편집' }).click();
  await page.locator('#run-alternative [role=status]').filter({ hasText: /원본을 복사해|이어서 편집/ }).waitFor();
}

const saved = (page, revision) => page.locator('#run-alternative [role=status]', { hasText: `저장됨 (수정본 ${revision})` }).waitFor();

test('three views, autosave, refresh and freeze on a real run artifact', { timeout: 90000 }, async t => {
  const { page, url, errors, runId } = await open(t);
  await openEditor(page, url, runId);
  const area = page.getByRole('textbox', { name: '내 버전 텍스트' });
  assert.equal(await area.inputValue(), '첫 줄\n둘째 줄\n셋째 줄\n');
  await area.fill('첫 줄\n고친 둘째 줄\n셋째 줄\n');
  await saved(page, 1);
  // the original view is the recorded artifact, read-only
  await page.getByRole('button', { name: '원본', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: '원본', exact: true }).getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('#run-alternative pre').textContent(), '첫 줄\n둘째 줄\n셋째 줄\n');
  assert.equal(await page.getByRole('textbox', { name: '내 버전 텍스트' }).count(), 0);
  // the differences view is what the framework observed on the saved revision
  await page.getByRole('button', { name: '차이', exact: true }).click();
  await page.getByText('수정본 1에서 관측한 차이 1개', { exact: false }).waitFor();
  assert.match(await page.locator('#run-alternative').textContent(), /원본 2–2행이 대안 2–2행으로 바뀌었다/);
  await page.getByRole('button', { name: '내 버전', exact: true }).click();
  assert.equal(await area.inputValue(), '첫 줄\n고친 둘째 줄\n셋째 줄\n');
  // a refresh resumes the saved revision from the server, not from the page
  await openEditor(page, url, runId);
  await page.getByText('저장된 내 버전을 이어서 편집합니다. (수정본 1)').waitFor();
  assert.equal(await page.getByRole('textbox', { name: '내 버전 텍스트' }).inputValue(), '첫 줄\n고친 둘째 줄\n셋째 줄\n');
  // freezing is explicit; the changed line alone is the evidence
  await page.getByRole('button', { name: '분석용으로 고정' }).click();
  await page.getByText('바꾼 부분 1곳을 내 근거로 기록했습니다.', { exact: false }).waitFor();
  assert.deepEqual(errors, []);
});

test('a stale tab never overwrites: reload the newer revision or keep the text as a new draft', { timeout: 90000 }, async t => {
  const { context, page, url, errors, runId } = await open(t);
  await openEditor(page, url, runId);
  const first = page.getByRole('textbox', { name: '내 버전 텍스트' });
  await first.fill('A의 첫 수정\n');
  await saved(page, 1);
  const other = await context.newPage();
  await openEditor(other, url, runId);  // both tabs now edit from revision 1
  await first.fill('A의 둘째 수정\n');
  await saved(page, 2);
  const second = other.getByRole('textbox', { name: '내 버전 텍스트' });
  await second.fill('B의 늦은 수정\n');
  await other.getByText('다른 화면에서 이 버전을 먼저 저장했습니다.', { exact: false }).waitFor();
  assert.equal(await second.inputValue(), 'B의 늦은 수정\n');  // the owner's text is kept
  await other.getByRole('button', { name: '지금 내용을 새 초안으로 저장' }).click();
  await saved(other, 1);  // a new draft of its own, revision 1
  // the first draft still holds A's revision 2: nothing was overwritten
  await openEditor(page, url, runId);
  const listed = await page.evaluate(async ({ base, runId }) => {
    const artifacts = await (await fetch(`${base}api/v1/runs/${runId}/artifacts`)).json();
    const report = artifacts.artifacts.find(item => item.role === 'report');
    return (await fetch(`${base}api/v1/runs/${runId}/artifacts/${report.artifact_id}/drafts`)).json();
  }, { base, runId });
  assert.deepEqual(listed.drafts.map(item => item.revision).sort(), [1, 2]);
  // a stale tab can instead reload the newer revision
  const third = await context.newPage();
  await openEditor(third, url, runId);
  await page.getByRole('textbox', { name: '내 버전 텍스트' }).fill('B 초안의 새 수정\n');
  await saved(page, 2);
  await third.getByRole('textbox', { name: '내 버전 텍스트' }).fill('낡은 탭의 수정\n');
  await third.getByRole('button', { name: '최신 수정본 불러오기' }).click();
  await third.getByText('(수정본 2)', { exact: false }).waitFor();
  assert.equal(await third.getByRole('textbox', { name: '내 버전 텍스트' }).inputValue(), 'B 초안의 새 수정\n');
  assert.deepEqual(errors, []);
});

test('a table is edited cell by cell with the keyboard', { timeout: 90000 }, async t => {
  const { page, url, errors, runId } = await open(t);
  await openEditor(page, url, runId, 'table');
  const cell = page.getByRole('textbox', { name: '2행 2열' });
  await cell.focus();
  await page.keyboard.press('Control+A');
  await page.keyboard.type('10');
  await saved(page, 1);
  await page.getByRole('button', { name: '차이', exact: true }).click();
  await page.getByText('원본 2행 2열과 대안 2행 2열의 값이 다르다.', { exact: false }).waitFor();
  assert.deepEqual(errors, []);
});
