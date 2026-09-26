// T066: the versions panel over a fake document and request.

import test from 'node:test';
import assert from 'node:assert/strict';

import { ERROR_MESSAGES, MESSAGES, budgetText, createVersionsPanel } from '../static/versions.mjs';

class FakeElement {
  constructor(tagName) { this.tagName = tagName.toUpperCase(); this.children = []; this.attributes = new Map(); this.dataset = {}; this.listeners = new Map(); this._text = ''; this.value = ''; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(_value) { throw new Error('markup is never written'); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }
  async dispatch(type) { for (const listener of this.listeners.get(type) ?? []) await listener({}); }
  findAll(predicate, found = []) { for (const child of this.children) { if (predicate(child)) found.push(child); child.findAll(predicate, found); } return found; }
}

const document = { createElement: tag => new FakeElement(tag) };
const crypto = { randomUUID: () => '00000000-0000-4000-8000-000000000077' };
const ref = (kind, n) => ({ kind, id: `${String(n).padStart(8, '0')}-0000-4000-8000-000000000000`, version: 1, sha256: String(n % 10).repeat(64) });
const env = ref('environment', 1);
const bundle = ref('environment', 2);
const report = ref('validation_report', 3);
const gates = Object.fromEntries(['reconstruction', 'heldout_transfer', 'boundary_exclusion', 'regression', 'leakage', 'side_effects']
  .map(name => [name, { status: 'pass', reasons: [], rounds: 1 }]));

function view(overrides = {}) {
  return { state: { current_environment_ref: env, history: [], applied_approvals: 0, external_effects_reverted: false, revision: 1 },
    candidates: [{ readable: true, report_record: ref('decision_record', 4), validation_report_ref: report, candidate_bundle_ref: bundle,
      change_candidate_ref: ref('change_candidate', 5), mode: 'sealed_offline', status: 'passed', approvable: true, gates }],
    experiments: [{ readable: true, lineage_id: '12345678-0000-4000-8000-000000000000', revision: 3, status: 'stopped', floor_reached: true,
      best_observed: { round_id: 'round-0', utility: '0.80' }, progress_reference: null, non_improving_valid_count: 0,
      completed_round_ids: ['round-0'], consumed_budget: {}, stop_reason: 'human_stop' }], ...overrides };
}

// the boundary routes (G-14) answer from their own queue, so the versions replies stay in order
function panelWith(replies, boundaryReplies = []) {
  const root = new FakeElement('section');
  const asked = [];
  const boundaryAsked = [];
  const request = async (path, options) => {
    const own = path.includes('/tool-effect-boundaries');
    (own ? boundaryAsked : asked).push([path, options]);
    const reply = own ? (boundaryReplies.length ? boundaryReplies.shift() : { plans: [] }) : replies.shift();
    if (reply instanceof Error) throw reply;
    return reply;
  };
  return { root, asked, boundaryAsked, panel: createVersionsPanel({ root, document, request, crypto }) };
}

const button = (root, text) => root.findAll(el => el.tagName === 'BUTTON' && el.textContent === text)[0];

test('the current version, candidate gates and the recorded stop reason are shown', async () => {
  const { root, panel } = panelWith([view()]);
  await panel.load();
  const text = root.textContent;
  assert.match(text, /지금 운영: environment 00000001/);
  assert.match(text, /검증 passed \(sealed_offline\)/);
  assert.match(text, /회귀: pass · 비교 라운드 1개/);
  assert.match(text, /사용자가 멈춤\(운영 적용 동의가 아님\)/);
  assert.match(text, /최고 0\.80/);
  assert.match(text, /소비 기록 없음/);
});

test('approve is separate from apply, and apply names the exact revision shown', async () => {
  const applied = view({ state: { ...view().state, current_environment_ref: bundle, history: [{ environment_ref: env, lifecycle: 'retired' }], revision: 2 } });
  const { root, asked, panel } = panelWith([view(), { approval_ref: ref('action_approval', 6), decision: 'approve' }, applied]);
  await panel.load();
  assert.equal(button(root, '승인한 이 버전 적용'), undefined);
  await button(root, '승인').dispatch('click');
  assert.deepEqual(asked[1][1].body, { command_id: crypto.randomUUID(), decision: 'approve', validation_report_ref: report });
  assert.match(root.textContent, /적용은 따로 합니다/);
  await button(root, '승인한 이 버전 적용').dispatch('click');
  assert.deepEqual(asked[2][1].body, { approval_ref: ref('action_approval', 6), expected_revision: 1 });
  assert.match(root.textContent, /지금 운영: environment 00000002/);
});

test('a failed candidate offers no approve; rollback needs a reason and says what it cannot undo', async () => {
  const failed = view({ candidates: [{ ...view().candidates[0], status: 'failed', approvable: false,
    gates: { ...gates, regression: { status: 'fail', reasons: ['보고서 누락'], rounds: 1 } } }],
  state: { ...view().state, history: [{ environment_ref: bundle, lifecycle: 'retired' }], revision: 4 } });
  const rolled = view({ state: { ...view().state, revision: 5 } });
  const { root, asked, panel } = panelWith([failed, rolled]);
  await panel.load();
  assert.equal(button(root, '승인'), undefined);
  assert.match(root.textContent, new RegExp(MESSAGES.notApprovable));
  assert.match(root.textContent, /회귀: fail · 비교 라운드 1개 · 보고서 누락/);
  await button(root, '이전 버전으로 되돌리기').dispatch('click');
  assert.equal(asked.length, 1);  // no reason, nothing sent
  root.findAll(el => el.getAttribute('id') === 'versions-rollback-reason')[0].value = '현장 품질 저하';
  await button(root, '이전 버전으로 되돌리기').dispatch('click');
  assert.deepEqual(asked[1][1].body, { reason: '현장 품질 저하', expected_revision: 4 });
  assert.match(root.textContent, /외부로 이미 나간 효과는 되돌리지 않았습니다/);
});

test('a moved version is refused plainly', async () => {
  const { root, panel } = panelWith([view(), Object.assign(new Error('x'), { code: 'conflict' })]);
  await panel.load();
  await button(root, '거절').dispatch('click');
  assert.match(root.textContent, new RegExp(ERROR_MESSAGES.conflict.slice(0, 10)));
});

// G-14 approvals: each tool's required boundary, what it means, and the owner's decision
const policy = ref('observation_contract', 7);
const planRecord = ref('decision_record', 8);
const replayBoundary = { tool_id: 'test_actor_notify', version: '1.0.0', effect_class: 'external_irreversible',
  boundary: 'replay', sink_id: null, state: 'pending', decisions: 0, approval_ref: null, decided_at_utc: null,
  boundary_sha256: 'a'.repeat(64) };
const sinkBoundary = { ...replayBoundary, tool_id: 'test_actor_publish', version: '2.0.0', boundary: 'isolated_sink',
  sink_id: 'g14-isolated-sink', boundary_sha256: 'b'.repeat(64) };
const plans = (...boundaries) => ({ plans: [{ plan_record: planRecord, lineage_id: '67014000-0000-4000-8000-000000000000',
  tool_effect_policy_ref: policy, readable: true, reason: null, boundaries }] });
const labelled = (root, label) => root.findAll(el => el.tagName === 'BUTTON' && el.getAttribute('aria-label') === label)[0];

test('each boundary a plan needs is shown with what it means and nothing is sent to a real service', async () => {
  const { root, panel } = panelWith([view()], [plans(replayBoundary, sinkBoundary)]);
  await panel.load();
  const [section] = root.findAll(el => el.getAttribute('aria-label') === '도구 효과 경계');
  const text = section.textContent;
  assert.match(text, /어느 경계도 실제 서비스로 보내지 않습니다/);
  assert.match(text, /test_actor_notify 1\.0\.0 \(external_irreversible\) · 기록 재생 · 과거 호출의 기록된 결과를 그대로 돌려줍니다\. 실제 서비스로 다시 보내지 않습니다\. · 경계 sha256 aaaaaaaaaaaa · 상태: 결정 대기/);
  assert.match(text, /test_actor_publish 2\.0\.0 \(external_irreversible\) · 격리 싱크 g14-isolated-sink · 보내려던 내용을 격리된 실행의 보관소 안에만 남깁니다\. 실제 서비스로 보내지 않습니다\./);
  assert.ok(labelled(root, '경계 승인: test_actor_notify 1.0.0 (기록 재생)'));
  assert.ok(labelled(root, '경계 거절: test_actor_publish 2.0.0 (격리 싱크 g14-isolated-sink)'));
});

test('approving a boundary sends the exact boundary shown and shows the recorded decision', async () => {
  const approved = { ...replayBoundary, state: 'approved', decisions: 1, approval_ref: ref('action_approval', 9),
    decided_at_utc: '2026-09-25T00:00:00.000000Z' };
  const reply = { approval_ref: approved.approval_ref, decision: 'approve', plan_record_ref: planRecord, boundary: approved };
  const { root, boundaryAsked, panel } = panelWith([view()], [plans(replayBoundary), reply]);
  await panel.load();
  await labelled(root, '경계 승인: test_actor_notify 1.0.0 (기록 재생)').dispatch('click');
  const [path, options] = boundaryAsked[1];
  assert.match(path, /\/api\/v1\/versions\/tool-effect-boundaries\/decisions$/);
  assert.deepEqual(options, { method: 'POST', body: { command_id: crypto.randomUUID(), plan_record_ref: planRecord,
    tool_id: 'test_actor_notify', version: '1.0.0', boundary_sha256: 'a'.repeat(64), decision: 'approve' } });
  assert.match(root.textContent, /상태: 승인됨 \(2026-09-25T00:00:00\.000000Z\)/);
  assert.match(root.textContent, /경계 승인을 기록했습니다/);
  // an approved boundary offers reject (a later decision replaces it), not approve again
  assert.equal(labelled(root, '경계 승인: test_actor_notify 1.0.0 (기록 재생)'), undefined);
  assert.ok(labelled(root, '경계 거절: test_actor_notify 1.0.0 (기록 재생)'));
});

test('a boundary conflict, an unreadable policy and an unavailable list are said plainly', async () => {
  const unreadable = { plans: [{ plan_record: planRecord, lineage_id: '67014000-0000-4000-8000-000000000000',
    tool_effect_policy_ref: policy, readable: false, reason: "the plan's tool effect policy could not be read", boundaries: [] }] };
  const conflict = panelWith([view()], [plans(replayBoundary), Object.assign(new Error('x'), { code: 'conflict' })]);
  await conflict.panel.load();
  await labelled(conflict.root, '경계 거절: test_actor_notify 1.0.0 (기록 재생)').dispatch('click');
  assert.match(conflict.root.textContent, /이 경계의 내용이 화면에 보인 것과 다르거나/);
  assert.match(conflict.root.textContent, /상태: 결정 대기/);
  const bad = panelWith([view()], [unreadable]);
  await bad.panel.load();
  assert.match(bad.root.textContent, /도구 효과 정책을 정확히 읽지 못했습니다.*could not be read/);
  assert.equal(bad.root.findAll(el => el.tagName === 'BUTTON' && /^경계/.test(el.textContent)).length, 0);
  const down = panelWith([view()], [Object.assign(new Error('x'), { code: 'unavailable' })]);
  await down.panel.load();
  assert.match(down.root.textContent, /도구 효과 경계를 불러오지 못했습니다/);
  assert.match(down.root.textContent, /지금 운영: environment 00000001/);  // the rest of the page still loads
  const none = panelWith([view()]);
  await none.panel.load();
  assert.match(none.root.textContent, /도구 효과 경계를 정한 비교 계획이 없습니다/);
});

test('the consumed budget is shown exactly as the loop recorded it', () => {
  assert.equal(budgetText({ isolated_runs: 12, node_visits: 36 }), 'isolated_runs 12, node_visits 36');
  assert.equal(budgetText({}), '기록 없음');
  assert.equal(budgetText(undefined), '기록 없음');
});

test('UI phase 5: four tabs — 운영 버전 · 후보 · 실험 · 승인·적용·롤백 — each with a plain empty state', async () => {
  const { TABS } = await import('../static/versions.mjs');
  assert.deepEqual(TABS.map(([, label]) => label), ['운영 버전', '후보', '실험', '승인·적용·롤백']);
  const { root, panel } = panelWith([view({ state: null, candidates: [], experiments: [] })]);
  await panel.load();
  const tabs = root.findAll(el => el.getAttribute('role') === 'tab');
  assert.deepEqual(tabs.map(tab => tab.textContent), ['운영 버전', '후보', '실험', '승인·적용·롤백']);
  assert.equal(tabs[0].getAttribute('aria-selected'), 'true');
  const text = root.textContent;
  assert.match(text, /아직 운영 버전이 없습니다\. 새 환경에서는 정상입니다\./);
  assert.match(text, new RegExp(MESSAGES.noCandidates));
  assert.match(text, new RegExp(MESSAGES.noDecisions));
  assert.equal(button(root, '승인'), undefined);
  // with a candidate, the gates are in 후보 and the decisions in 승인·적용·롤백; the tab names count
  const filled = panelWith([view()]);
  await filled.panel.load();
  const panels = filled.root.findAll(el => el.getAttribute('role') === 'tabpanel');
  assert.match(panels[1].textContent, /회귀: pass/);
  assert.equal(panels[1].findAll(el => el.tagName === 'BUTTON').length, 0);
  assert.ok(panels[3].findAll(el => el.tagName === 'BUTTON' && el.textContent === '승인').length === 1);
  assert.deepEqual(filled.root.findAll(el => el.getAttribute('role') === 'tab').map(tab => tab.textContent),
    ['운영 버전', '후보 1', '실험 1', '승인·적용·롤백']);
});
