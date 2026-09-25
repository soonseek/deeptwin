// T037: the design workspace on the work page in a real browser against the real supported
// server. The fixture persists one design request whose candidates and verdicts come from
// scripted TEST-ACTOR generator/critic turns (labelled as such on the page); the owner
// compares two pooled candidates side by side, focuses one node, selects / edits / merges
// into new versions that require re-review, sees review unavailable (no critic model turn)
// and the exact refusal of preparation (the critic is not qualified).

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
const READY = /DESIGN_SEED=(\{[^\n]*\})\nDESIGN_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
const REFUSAL = 'the critic configuration is not qualified (unknown: no_suite_record)';

async function open(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-design-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Design workspace fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/design_workspace_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 60000, label: 'Design workspace fixture' });
  const [, seedText, url] = READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1400, height: 1100 } });
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
  return { page, url, errors, seed: JSON.parse(seedText) };
}

test('the owner compares pooled candidates, derives new versions and sees the honest refusals', { timeout: 120000 }, async t => {
  const { page, url, errors, seed } = await open(t);
  await page.goto(url + 'work.html');
  const workspace = page.locator('#design-workspace');
  await workspace.locator('[role=status]').first().filter({ hasText: '후보를 보여 줍니다' }).waitFor();
  // the honest pool: the real count, every exclusion reason, the recorded (not live) verdicts
  const pool = workspace.locator('.design-pool');
  assert.match(await pool.locator('.design-pool-count').textContent(), /후보 2개를 제시합니다 \(기본 3안\) — 3개를 채우지 못했습니다.*전체 후보 4개 · 통과 3개/);
  assert.match(await pool.locator('.design-qualification').textContent(), /자격 기록 없음 \(unknown: no_suite_record\).*실시간 평가가 아닙니다/);
  const exclusions = await pool.locator('.design-exclusions li').allTextContents();
  assert.equal(exclusions.length, 2);
  assert.ok(exclusions.some(text => text.startsWith(seed.duplicate.slice(0, 8)) && /이미 제시된 후보와 구조가 같습니다/.test(text)));
  assert.ok(exclusions.some(text => text.startsWith(seed.rejected.slice(0, 8)) && /필수 결함으로 탈락 \(review_fail:/.test(text)));
  const cards = pool.locator('.design-candidate');
  assert.equal(await cards.count(), 2);
  assert.match(await cards.first().locator('.design-verdict').textContent(), /기록된 평가: 통과 · 평가자 test-actor-critic/);
  // the large side-by-side comparison: both graphs drawn, what differs, one node in focus
  const compare = workspace.locator('.design-compare');
  assert.equal(await compare.locator('.design-compare-side').count(), 2);
  assert.equal(await compare.locator('.design-compare-side svg .graph-node').count() > 0, true);
  assert.match(await compare.locator('.design-differences').textContent(), /산출물 계약: 변경 final-script/);
  const box = await compare.locator('.design-compare-side svg').first().boundingBox();
  assert.ok(box.width >= 400, `the drawing is large enough to read (${box.width}px)`);
  const focusPicker = compare.getByRole('combobox', { name: '같은 노드 비교' });
  const agentNode = await page.evaluate(async ({ base, id }) => {
    const view = await (await fetch(`${base}api/v1/design-requests/${id}`)).json();
    return view.candidates[0].graph.nodes.find(node => node.kind === 'agent').node_id;
  }, { base, id: seed.request_id });
  await focusPicker.selectOption(agentNode);
  const focus = compare.locator('.design-focus');
  await focus.getByText(`${agentNode}: 같음`).waitFor();
  assert.match(await focus.textContent(), /모델model_choice:/);
  assert.match(await focus.textContent(), /도구/);
  // prepare: attempted, and the exact refusal is shown
  assert.match(await cards.first().locator('.design-not-approvable').textContent(), new RegExp(REFUSAL.replace(/[()]/g, '\\$&')));
  await cards.first().getByRole('button', { name: '이 설계로 준비' }).click();
  await cards.first().locator('.design-command-status').filter({ hasText: `준비하지 않았습니다: ${REFUSAL}` }).waitFor();
  // select → a new version that requires re-review; review is unavailable and says why
  await cards.first().getByRole('button', { name: '이 설계 선택' }).click();
  const derived = workspace.locator('.design-derivation');
  await derived.first().waitFor();
  assert.match(await derived.first().textContent(), /선택 · 원본 .*재검토 필요 · 원본의 평가·승인은 이어지지 않습니다/);
  assert.equal(await derived.first().getByRole('button', { name: '재검토' }).isDisabled(), true);
  assert.match(await derived.first().locator('.design-review-unavailable').textContent(), /평가 모델이 설정되지 않아/);
  // edit with an instruction, then merge both
  await pool.locator('.design-candidate').nth(1).getByRole('textbox', { name: '후보 2 수정 지시' }).fill('검토 단계를 하나 더 둔다');
  await pool.locator('.design-candidate').nth(1).getByRole('button', { name: '지시대로 수정' }).click();
  await workspace.locator('.design-derivation', { hasText: '지시 "검토 단계를 하나 더 둔다"' }).waitFor();
  await pool.getByRole('checkbox', { name: '후보 1 합치기에 포함' }).check();
  await pool.getByRole('checkbox', { name: '후보 2 합치기에 포함' }).check();
  await pool.getByRole('button', { name: '선택한 후보 합치기' }).click();
  await workspace.locator('.design-derivation', { hasText: '합치기 · 원본' }).waitFor();
  assert.equal(await derived.count(), 3);
  for (const text of await derived.allTextContents()) assert.match(text, /재검토 필요/);
  // the server holds exactly these three derived versions, none with a verdict
  const stored = await page.evaluate(async ({ base, id }) => (await (await fetch(`${base}api/v1/design-requests/${id}`)).json()).derivations,
    { base, id: seed.request_id });
  assert.deepEqual(stored.map(item => [item.action, item.re_review_required, item.inherited_verdict]).sort(),
    [['edit', true, null], ['merge', true, null], ['select', true, null]]);
  assert.deepEqual(errors, []);
});
