// T037: the design workspace over a fake document and request — the honest pool, the
// side-by-side comparison with one node in focus, and the commands with their states.
// The view data is a TEST-ACTOR shape (a scripted critic's recorded verdicts). No markup
// is ever written.

import test from 'node:test';
import assert from 'node:assert/strict';

import { differenceSummary, compareGraphs, unionNodeIds } from '../static/graph.mjs';
import { createDesignWorkspace, exclusionText, poolSummary, verdictText } from '../static/workspace.mjs';

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
  querySelectorAll(selector) { return selector === '[data-node]' ? this.findAll(el => el.getAttribute('data-node') !== null) : []; }
}
const document = { createElement: tag => new FakeElement(tag), createElementNS: (_ns, tag) => new FakeElement(tag) };
const buttons = (root, command) => root.findAll(el => el.tagName === 'BUTTON' && el.getAttribute('data-command') === command);

const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const ref = (kind, n) => ({ kind, id: id(n), version: 1, sha256: String(n % 10).repeat(64) });
const slot = name => ({ slot_id: name, artifact_contract_id: 'notes', multiplicity: 'one' });
const agent = (name, responsibility, tools = []) => ({ node_id: name, kind: 'agent', responsibility, input_slots: [], output_slots: [slot('out')],
  grant_refs: [], required_approval_scopes: [], failure_policy: 'block_dependants',
  config: { model_binding_id: 'm', required_model_capabilities: ['text'], tool_binding_ids: tools, memory_policy_id: null } });
const graphA = { entry_node_ids: ['research'], nodes: [agent('research', '자료 조사', ['browse']), agent('write', '대본 작성')],
  edges: [{ edge_id: 'e1', kind: 'artifact', source_node_id: 'research', target_node_id: 'write', loop_id: null }],
  model_bindings: [{ binding_id: 'm', model_choice_ref: ref('model_choice', 3), capabilities: ['text'] }],
  tool_bindings: [{ binding_id: 'browse', tool_definition_ref: ref('tool_definition', 4), grant_ref: ref('grant', 5), capabilities: ['browser.read'] }],
  artifact_contracts: [{ artifact_contract_id: 'notes', max_items: 2 }] };
const graphB = { ...graphA, nodes: [graphA.nodes[0], agent('write', '근거 기반 대본 작성')],
  artifact_contracts: [{ artifact_contract_id: 'notes', max_items: 1 }] };
const verdict = { status: 'passed', reasons: [], source: 'persisted_criticism', model_ids: ['test-actor-critic'],
  profile_digests: ['a'.repeat(64)], call_count: 2, criticism_record_id: id(90) };
const REQUEST = id(1);

function viewData({ derivations = [], review = { available: false, reason: 'critic_model_not_configured', critic_model_id: null } } = {}) {
  return {
    schema_version: 'design-workspace-v1',
    request: { request_id: REQUEST, version: 1, requested_candidate_count: 3, design_disposition: 'multi_agent', work_model_ref: ref('work_model', 2) },
    pool: { pool_size: 3, presented_candidate_ids: [id(11), id(12)], presented_count: 2, passed_count: 3, candidate_count: 4,
      excluded: [{ candidate_id: id(13), reason: 'rejected:review_fail:shape:disposition' }, { candidate_id: id(14), reason: 'structural_duplicate' }],
      supplementation_available: true },
    candidates: [
      { candidate_id: id(11), version: 1, graph_ref: ref('graph', 21), graph: graphA, parent_candidate_ids: [], verdict, presented: true },
      { candidate_id: id(12), version: 1, graph_ref: ref('graph', 22), graph: graphB, parent_candidate_ids: [], verdict, presented: true },
      { candidate_id: id(13), version: 1, graph_ref: ref('graph', 23), graph: graphA, parent_candidate_ids: [],
        verdict: { ...verdict, status: 'rejected', reasons: ['review_fail:shape:disposition'] }, presented: false },
    ],
    derivations,
    review,
    preparation: { environment_id: id(99), approvable: false,
      critic_qualification: { schema_version: 'critic-qualification-v1', configuration_digest: 'c'.repeat(64), status: 'unknown', reason: 'no_suite_record', design_id: null, record_sha256: null },
      reason: 'the critic configuration is not qualified (unknown: no_suite_record)' },
  };
}

function harness(overrides = {}) {
  const calls = [];
  let current = viewData(overrides);
  const replies = [];
  const request = async (path, options = {}) => {
    calls.push({ path, ...options });
    if (options.method === 'POST') {
      const reply = replies.shift();
      if (reply instanceof Error) throw reply;
      if (reply?.next) current = reply.next;
      return reply?.value ?? {};
    }
    if (path.endsWith('/design-requests')) return { requests: [{ request_id: REQUEST, version: 1, requested_candidate_count: 3 }] };
    return current;
  };
  const root = new FakeElement('section');
  let n = 500;
  const workspace = createDesignWorkspace({ root, document, request, commandId: () => id(n++) });
  return { root, workspace, calls, replies };
}

test('graph differences read as lines and the node union keeps the left order', () => {
  const lines = differenceSummary(compareGraphs(graphA, graphB));
  assert.deepEqual(lines, ['노드: 변경 write(responsibility)', '산출물 계약: 변경 notes(max_items)']);
  assert.deepEqual(unionNodeIds(graphA, { ...graphB, nodes: [...graphB.nodes, agent('check', '검토')] }), ['research', 'write', 'check']);
});

test('the pool states the real count, each exclusion reason and the verdict as a recorded one', () => {
  assert.match(poolSummary(viewData().pool), /후보 2개를 제시합니다 \(기본 3안\) — 3개를 채우지 못했습니다/);
  assert.equal(exclusionText('structural_duplicate'), '이미 제시된 후보와 구조가 같습니다');
  assert.equal(exclusionText('rejected:review_fail:x'), '필수 결함으로 탈락 (review_fail:x)');
  assert.equal(verdictText(verdict), '기록된 평가: 통과 · 평가자 test-actor-critic (호출 2회)');
  assert.equal(verdictText(null), '평가 없음 — 재검토가 필요합니다');
});

test('loading shows the pool, the qualification refusal, and both candidates side by side with a focus', async () => {
  const { root, workspace } = harness();
  await workspace.load();
  const text = root.textContent;
  assert.match(text, /통과한 구조적으로 다른 후보 2개/);
  assert.match(text, /평가자 구성의 자격: 자격 기록 없음 \(unknown: no_suite_record\)/);
  assert.match(text, /실시간 평가가 아닙니다/);
  assert.match(text, /이미 제시된 후보와 구조가 같습니다/);
  assert.match(text, /지금은 승인할 수 없습니다: the critic configuration is not qualified \(unknown: no_suite_record\)/);
  assert.match(text, /노드: 변경 write\(responsibility\)/);
  const sides = root.findAll(el => el.getAttribute('class') === 'design-compare-side');
  assert.equal(sides.length, 2);
  // the focus shows the same node on both sides, model and tool bindings included
  const focus = root.findAll(el => el.getAttribute('class') === 'design-focus')[0];
  assert.match(focus.textContent, /research: 같음/);
  assert.match(focus.textContent, /모델model_choice:/);
  assert.match(focus.textContent, /도구browse → tool_definition:/);
  const picker = root.findAll(el => el.getAttribute('aria-label') === '같은 노드 비교')[0];
  picker.value = 'write';
  await picker.dispatch('change');
  assert.match(focus.textContent, /write: 다름 \(responsibility\)/);
  // merging needs two picks
  assert.equal(buttons(root, 'merge')[0].disabled, true);
});

test('select, edit and merge post derivations; review is disabled with its reason; prepare shows the exact refusal', async () => {
  const derivation = { derivation_id: id(70), action: 'select', parent_candidate_ids: [id(11)], instruction: null,
    re_review_required: true, inherited_verdict: null, created_at_utc: '2026-09-25T00:00:00.000000Z', reviewed_candidate: null };
  const { root, workspace, calls, replies } = harness();
  await workspace.load();
  replies.push({ value: derivation, next: viewData({ derivations: [derivation] }) });
  await buttons(root, 'select')[0].dispatch('click');
  const posted = calls.filter(call => call.method === 'POST');
  assert.equal(posted[0].path, `/api/v1/design-requests/${REQUEST}/derivations`);
  assert.deepEqual({ ...posted[0].body, command_id: undefined }, { schema_version: 'design-derivation-command-v1', command_id: undefined,
    action: 'select', parent_candidate_ids: [id(11)], instruction: null });
  assert.match(root.textContent, /재검토 필요 · 원본의 평가·승인은 이어지지 않습니다/);
  const review = buttons(root, 'review')[0];
  assert.equal(review.disabled, true);
  assert.match(root.textContent, /평가 모델이 설정되지 않아 재검토를 실행할 수 없습니다/);
  // an edit without an instruction sends nothing
  const before = calls.length;
  await buttons(root, 'edit')[0].dispatch('click');
  assert.equal(calls.length, before);
  const box = root.findAll(el => el.getAttribute('aria-label') === '후보 1 수정 지시')[0];
  box.value = '검토 단계를 더한다';
  replies.push({ value: { ...derivation, derivation_id: id(71), action: 'edit' } });
  await buttons(root, 'edit')[0].dispatch('click');
  assert.equal(calls.at(-2).body.instruction, '검토 단계를 더한다');
  // merge: two checked candidates
  for (const box of root.findAll(el => el.getAttribute('type') === 'checkbox')) { box.checked = true; await box.dispatch('change'); }
  assert.equal(buttons(root, 'merge')[0].disabled, false);
  replies.push({ value: { ...derivation, derivation_id: id(72), action: 'merge' } });
  await buttons(root, 'merge')[0].dispatch('click');
  assert.deepEqual(calls.filter(call => call.method === 'POST').at(-1).body.parent_candidate_ids, [id(11), id(12)]);
  // prepare: the server's exact refusal is shown on the candidate
  replies.push(Object.assign(new Error('refused'), { code: 'not_approvable',
    reason: 'the critic configuration is not qualified (unknown: no_suite_record)' }));
  await buttons(root, 'prepare')[0].dispatch('click');
  const outcome = root.findAll(el => el.getAttribute('class') === 'design-command-status' && el.dataset.state === 'not_approvable');
  assert.equal(outcome.length, 1);
  assert.equal(outcome[0].textContent, '준비하지 않았습니다: the critic configuration is not qualified (unknown: no_suite_record)');
});

test('a reviewed derived version shows its own recorded verdict and can be prepared', async () => {
  const reviewed = { candidate_id: id(80), version: 1, graph_ref: ref('graph', 21), graph: graphA, parent_candidate_ids: [id(11)], verdict, presented: false };
  const derivation = { derivation_id: id(70), action: 'select', parent_candidate_ids: [id(11)], instruction: null,
    re_review_required: false, inherited_verdict: null, created_at_utc: '2026-09-25T00:00:00.000000Z', reviewed_candidate: reviewed };
  const { root, workspace, calls, replies } = harness({ derivations: [derivation],
    review: { available: true, reason: null, critic_model_id: 'test-actor-critic' } });
  await workspace.load();
  const row = root.findAll(el => el.getAttribute('data-derivation') === id(70))[0];
  assert.match(row.textContent, /기록된 평가: 통과/);
  replies.push({ value: { status: 'prepared', environment_version: { version: 1, status: 'prepared' } } });
  await buttons(row, 'prepare')[0].dispatch('click');
  assert.equal(calls.at(-1).body.candidate_id, id(80));
  assert.match(row.textContent, /환경 버전 1을 준비했습니다. 준비는 활성화가 아니며 작업을 시작하지 않습니다./);
});

test('an instance without design requests says so and refuses a malformed id', async () => {
  const root = new FakeElement('section');
  const workspace = createDesignWorkspace({ root, document, commandId: () => id(1), request: async () => ({ requests: [] }) });
  await workspace.load();
  assert.match(root.textContent, /비교할 설계 요청이 없습니다/);
  await assert.rejects(workspace.show('nope'), /canonical UUID/);
  assert.throws(() => createDesignWorkspace({ root, document, request: async () => ({}) }), /command id/);
});
