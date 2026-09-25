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

function panelWith(replies) {
  const root = new FakeElement('section');
  const asked = [];
  const request = async (path, options) => { asked.push([path, options]); const reply = replies.shift(); if (reply instanceof Error) throw reply; return reply; };
  return { root, asked, panel: createVersionsPanel({ root, document, request, crypto }) };
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

test('the consumed budget is shown exactly as the loop recorded it', () => {
  assert.equal(budgetText({ isolated_runs: 12, node_visits: 36 }), 'isolated_runs 12, node_visits 36');
  assert.equal(budgetText({}), '기록 없음');
  assert.equal(budgetText(undefined), '기록 없음');
});
