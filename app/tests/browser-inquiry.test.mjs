// T060 (US5, UX-AC05/07), real Chromium against the supported server.
//
// 1. After a real freeze, the observed difference is sealed and shown with every unknown
//    stated — no explanation is invented, no question is put to the owner, no stand-in
//    answer appears, and the unreviewed area and pending impact stay visible.
// 2. The full owner inquiry flow, driven by a scripted TEST ACTOR through the real screens
//    (owner decision 2026-09-25: steps needing real human feedback run as a simulation).
//    Every answer, skip, evidence item and judgment is the test actor's own typing and
//    clicking, labelled `test-actor:`; the two model turns (competing explanations, one
//    proposed question) are offline scripted responses of the fixture's mock transport.
//    This is not real user feedback and qualifies nothing.

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { base, open, openEditor, saved } from './helpers/alternatives-fixture.mjs';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));

test('a frozen alternative shows its observed difference and no invented explanation or quiz', { timeout: 90000 }, async t => {
  const { page, url, errors, runId } = await open(t);
  await openEditor(page, url, runId);
  await page.getByRole('textbox', { name: '내 버전 텍스트' }).fill('첫 줄\n고친 둘째 줄\n셋째 줄\n');
  await saved(page, 1);
  await page.getByRole('button', { name: '분석용으로 고정' }).click();
  const panel = page.locator('#run-inquiry');
  await panel.getByText('관측된 차이 1개').waitFor();
  const text = await panel.textContent();
  assert.match(text, /원본 2–2행이 대안 2–2행으로 바뀌었다/);
  assert.match(text, /내가 바꾼 1곳이 근거입니다/);
  assert.match(text, /검토하지 않은 영역으로 남고, 영향 범위는 따로 조사합니다/);
  assert.match(text, /소유자가 요청할 때만 Claude 연결로 만든다/);
  assert.match(text, /새로운 조건부 판단: 검토되지 않음/);
  assert.match(text, /질문에 답하도록 요구하지 않습니다/);
  assert.match(text, /변경 후보를 만들지 않았다/);
  // nothing in the panel asks the owner for an answer
  assert.equal(await panel.locator('input, textarea, select').count(), 0);
  // the difference is a sealed record the server reads back the same way after a reload
  const reread = await page.evaluate(async ({ base, runId }) => {
    const artifacts = await (await fetch(`${base}api/v1/runs/${runId}/artifacts`)).json();
    const report = artifacts.artifacts.find(item => item.role === 'report');
    const drafts = await (await fetch(`${base}api/v1/runs/${runId}/artifacts/${report.artifact_id}/drafts`)).json();
    return drafts.drafts[0].frozen_revisions;
  }, { base, runId });
  assert.deepEqual(reread, [1]);
  assert.deepEqual(errors, []);
});

const INQUIRY_READY = /INQUIRY_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
const INQUIRY_SEED = /INQUIRY_SEED=(\{[^\n]*\})/;

async function openInquiryFixture(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-inquiry-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Inquiry fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/inquiry_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: INQUIRY_READY, timeoutMs: 30000, label: 'Inquiry fixture' });
  const url = INQUIRY_READY.exec(announced)[1];
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1200, height: 1400 } })).newPage();
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  const seeded = waitForOwnedChildOutput(server, { pattern: INQUIRY_SEED, timeoutMs: 30000, label: 'Inquiry seed' });
  // setup through the product routes: bootstrap, a test-only key held in server memory, the
  // catalog and the owner's model choice (whichever model the scripted catalog lists)
  const setup = await page.evaluate(async ({ base, capability }) => {
    const bootstrapped = (await fetch(base + 'session/bootstrap', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase', raw_capability_b64u: capability }) })).status;
    const session = await (await fetch(base + 'session')).json();
    const headers = { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrf_token };
    const claude = base + 'api/v1/connections/claude';
    const key = (await fetch(claude + '/key', { method: 'POST', headers, body: JSON.stringify({ secret: 'sk-ant-api03-test-only-never-real' }) })).status;
    const catalog = await (await fetch(claude + '/catalog', { method: 'POST', headers, body: '{}' })).json();
    const chosen = (await fetch(claude + '/model-choice', { method: 'POST', headers,
      body: JSON.stringify({ model_id: catalog.catalog.model_ids[0] }) })).status;
    return { bootstrapped, key, chosen };
  }, { base, capability: Buffer.alloc(32, 'T').toString('base64url') });
  assert.deepEqual(setup, { bootstrapped: 201, key: 200, chosen: 200 });
  const seed = JSON.parse(INQUIRY_SEED.exec(await seeded)[1]);
  const run = await page.evaluate(async ({ base, seed }) => {
    const session = await (await fetch(base + 'session')).json();
    const headers = { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrf_token };
    const consent = await (await fetch(base + 'api/v1/run-consents', { method: 'POST', headers, body: JSON.stringify({
      schema_version: 'run-consent-command-v1', command_id: crypto.randomUUID(), ...seed }) })).json();
    const started = await fetch(base + 'api/v1/runs', { method: 'POST', headers, body: JSON.stringify({
      command_id: crypto.randomUUID(), ...seed, consent_ref: consent.ref }) });
    return { status: started.status, body: await started.json() };
  }, { base, seed });
  assert.ok([200, 201].includes(run.status), JSON.stringify(run.body));
  return { page, url, errors, runId: run.body.run_id };
}

const fetchJson = (page, path) => page.evaluate(async ({ base, path }) => (await fetch(`${base}${path}`)).json(), { base, path });

test('test-actor: difference → explanations → inquiry → answer, skip, evidence, judgments → proposal → audit', { timeout: 150000 }, async t => {
  const { page, url, errors, runId } = await openInquiryFixture(t);
  await openEditor(page, url, runId, 'draft');
  await page.getByRole('textbox', { name: '내 버전 텍스트' }).fill('첫 줄\n고친 둘째 줄\n셋째 줄\n');
  await saved(page, 1);
  await page.getByRole('button', { name: '분석용으로 고정' }).click();
  const panel = page.locator('#run-inquiry');
  await panel.getByText('관측된 차이 1개').waitFor();
  // competing explanations only on the test actor's explicit request (scripted offline turn)
  await panel.getByRole('button', { name: '경쟁 설명 만들기' }).click();
  await panel.getByText('시스템 결손(정보 추출·검색·활용·전달 실패) · 제안').waitFor();
  // the inquiry stays closed until the test actor opens it
  const section = panel.locator('section[data-difference-id]');
  await section.getByRole('button', { name: '탐구 열기' }).waitFor();
  const differenceId = await section.getAttribute('data-difference-id');
  assert.equal((await fetchJson(page, `api/v1/inquiries/${differenceId}`)).state, 'not_opened');
  // pick the model so it may propose questions (it never answers), then open
  const picker = section.getByLabel('질문을 더 제안받을 모델 (선택)');
  const models = await picker.locator('option').evaluateAll(options => options.map(option => option.value).filter(Boolean));
  await picker.selectOption(models[0]);
  await section.getByRole('button', { name: '탐구 열기' }).click();
  await section.getByText('모든 질문은 선택입니다', { exact: false }).waitFor();
  await section.getByText('모델 제안 질문', { exact: false }).waitFor();
  const opened = await section.textContent();
  assert.match(opened, /다른 보고서에서도 둘째 줄을 이렇게 고치십니까/);
  assert.match(opened, /규칙을 인계하면 차이가 사라진다/);
  // right after opening nothing is anyone's answer: every question shows unanswered
  const questionCount = await section.locator('[data-question]').count();
  assert.ok(questionCount >= 3);
  assert.equal(await section.locator('[data-answer-state="unanswered"]').count(), questionCount);
  assert.deepEqual((await fetchJson(page, `api/v1/inquiries/${differenceId}`)).answers, []);

  // test-actor answers q1, skips q2 and leaves the rest unanswered
  const typed = 'test-actor: 규칙을 인계한 다음 보고서에서도 같은 수정을 했습니다.';
  await section.getByLabel('q1에 대한 내 답 (선택)').fill(typed);
  await section.getByRole('button', { name: 'q1 답 저장' }).click();
  await section.getByText(`내 답: ${typed}`).waitFor();
  await section.getByRole('button', { name: 'q2 건너뛰기' }).click();
  await section.locator('[data-question="q2"] [data-answer-state="skipped"]').waitFor();
  // evidence the test actor supplies
  await section.getByLabel('근거 내용').fill('test-actor: 7월·8월 보고서에서도 둘째 줄을 같은 방식으로 고쳤다.');
  await section.getByLabel('출처 (한 줄에 하나, 선택)').fill('보고서 2026-07\n보고서 2026-08');
  await section.getByRole('button', { name: '근거 추가' }).click();
  await section.getByText('(출처: 보고서 2026-07, 보고서 2026-08)', { exact: false }).waitFor();
  // confirming before the competitor is examined is refused with the reason
  await section.getByLabel('expert_judgment-1에 대한 내 판단').selectOption('confirmed');
  await section.getByLabel('expert_judgment-1: 근거 1 인용').check();
  await section.getByRole('button', { name: 'expert_judgment-1 판단 기록' }).click();
  await panel.locator('[role=status]', { hasText: '다른 설명을 먼저 반박하거나 미결로' }).waitFor();
  // refute the system explanation, then confirm the judgment one, both citing the evidence
  await section.getByLabel('system-0에 대한 내 판단').selectOption('refuted');
  await section.getByLabel('system-0: 근거 1 인용').check();
  await section.getByRole('button', { name: 'system-0 판단 기록' }).click();
  await section.getByText('system-0 · 시스템 결손(정보 추출·검색·활용·전달 실패) · 소유자 반박').waitFor();
  await section.getByLabel('expert_judgment-1에 대한 내 판단').selectOption('confirmed');
  await section.getByLabel('expert_judgment-1: 근거 1 인용').check();
  await section.getByRole('button', { name: 'expert_judgment-1 판단 기록' }).click();
  // a change candidate proposal is shown, never applied
  await section.getByText('학습 변경 제안 · 제안 · 적용되지 않음').waitFor();
  const done = await section.textContent();
  assert.match(done, /변경 후보는 제안일 뿐이며 여기서 적용되지 않습니다/);
  assert.match(done, /내 버전 문구 복사 검사: 통과/);
  // the audit detail: who/what/when, which model turns, which owner inputs
  await section.getByRole('button', { name: '감사 상세 보기' }).click();
  await section.getByText('소유자 입력: 답 1 · 건너뜀 1 · 근거 1 · 판단 2').waitFor();
  const audit = await section.textContent();
  assert.match(audit, /소유자 입력이 아닌 사람 답: 0/);
  assert.match(audit, /경쟁 설명 · [^·]+ · [^·]+ · 결과 completed/);
  assert.match(audit, /질문 제안 · [^·]+ · [^·]+ · 결과 completed/);
  assert.match(audit, /소유자 · 탐구 열기\(질문 고정\)/);
  assert.match(audit, /모델\(소유자 요청\) · 경쟁 설명 제안/);

  // nothing is recorded as a human answer without the test actor's own input
  const state = await fetchJson(page, `api/v1/inquiries/${differenceId}`);
  assert.deepEqual(state.answers.map(item => [item.question_id, item.state, item.text, item.origin]), [
    ['q1', 'answered', typed, 'owner_input'], ['q2', 'skipped', null, 'owner_input']]);
  assert.equal(state.unanswered_count, questionCount - 2);
  assert.ok(state.questions.filter(item => item.origin === 'model_proposal').every(item =>
    !state.answers.some(answer => answer.question_id === item.question_id)));
  const detail = await fetchJson(page, `api/v1/inquiries/${differenceId}/audit`);
  assert.equal(detail.inputs_not_from_owner, 0);
  assert.deepEqual(detail.model_turns.map(turn => turn.purpose), ['diagnosis_hypotheses', 'inquiry_questions']);
  assert.ok(detail.timeline.filter(item => ['answer', 'skip', 'evidence', 'judgment'].includes(item.kind))
    .every(item => item.actor === 'owner' && item.origin === 'owner_input'));
  assert.deepEqual(state.change_candidates.map(item => [item.kind, item.state, item.applied]), [['learn', 'proposed', false]]);
  assert.deepEqual(errors, []);
});
