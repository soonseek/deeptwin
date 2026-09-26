// T037: the design workspace over a fake document and request — the honest pool, the
// side-by-side comparison with one node in focus, and the commands with their states.
// The view data is a TEST-ACTOR shape (a scripted critic's recorded verdicts). No markup
// is ever written.

import test from 'node:test';
import assert from 'node:assert/strict';

import { differenceSummary, compareGraphs, unionNodeIds } from '../static/graph.mjs';
import { createDesignWorkspace, exclusionText, generationRunText, poolSummary, qualificationText, verdictText } from '../static/workspace.mjs';

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

// T038: the design arc on the workspace — generate, cancel, each run's recorded outcome,
// an edit's re-review through the generation turn, and the simulated-qualification label
const GENERATION = { available: true, reason: null, generator_model_id: 'test-actor-generator',
  critic_model_id: 'test-actor-critic', max_rounds: 3, running: false, cancel_requested: false, runs: [] };
const run = changes => ({ run_id: id(60), command_id: id(61), max_rounds: 3, rounds: 3, outcome: 'shortfall', model_calls: 7,
  generator_model_id: 'test-actor-generator', critic_model_id: 'test-actor-critic', refusals: [], candidate_ids: [id(11), id(12)],
  unreviewed_candidate_ids: [], presented_count: 1, started_at_utc: '2026-09-26T00:00:00.000000Z',
  ended_at_utc: '2026-09-26T00:00:01.000000Z', ...changes });

test('without a generation turn the arc says why and offers no command', async () => {
  const { root, workspace } = harness();
  await workspace.load();
  assert.equal(buttons(root, 'generate').length, 0);
  const withReason = { ...viewData(), generation: { ...GENERATION, available: false, reason: 'generator_model_not_configured' } };
  const other = createDesignWorkspace({ root, document, commandId: () => id(1), request: async path => (
    path.endsWith('/design-requests') ? { requests: [{ request_id: REQUEST, version: 1, requested_candidate_count: 3 }] } : withReason) });
  await other.load();
  assert.equal(buttons(root, 'generate').length, 0);
  assert.match(root.textContent, /설계 생성 모델이 설정되지 않아 후보를 만들 수 없습니다/);
});

test('generate posts the bounded command; cancel posts while it runs; the texts say what was recorded', async () => {
  const withArc = { ...viewData(), generation: GENERATION };
  const calls = [];
  let current = withArc;
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  const cancelled = run({ outcome: 'cancelled', rounds: 1, model_calls: 4, candidate_ids: [id(11), id(12), id(13)],
    unreviewed_candidate_ids: [id(12), id(13)] });
  const request = async (path, options = {}) => {
    calls.push({ path, ...options });
    if (path.endsWith('/generations')) { await pending; current = { ...withArc, generation: { ...GENERATION, runs: [cancelled] } }; return cancelled; }
    if (path.endsWith('/cancellations')) return { schema_version: 'design-generation-cancel-v1', state: 'cancel_requested', running: true };
    if (path.endsWith('/design-requests')) return { requests: [{ request_id: REQUEST, version: 1, requested_candidate_count: 3 }] };
    return current;
  };
  const root = new FakeElement('section');
  let n = 700;
  const workspace = createDesignWorkspace({ root, document, request, commandId: () => id(n++) });
  await workspace.load();
  assert.match(root.textContent, /생성자 test-actor-generator · 평가자 test-actor-critic/);
  const [start] = buttons(root, 'generate');
  const [stop] = buttons(root, 'cancel');
  assert.equal(stop.disabled, true);
  const running = start.dispatch('click');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(start.disabled, true);
  assert.equal(stop.disabled, false);
  assert.deepEqual(calls.find(item => item.path.endsWith('/generations')).body,
    { command_id: id(700), schema_version: 'design-generation-command-v1', max_rounds: 3 });
  await stop.dispatch('click');
  assert.equal(calls.at(-1).body.schema_version, 'design-generation-cancel-command-v1');
  assert.match(root.textContent, /다음 모델 호출 전에 멈춥니다/);
  release();
  await running;
  assert.match(root.textContent, /소유자가 취소했습니다: 다음 모델 호출 전에 멈췄습니다 \(생성 1회\). 평가를 마치지 못한 후보 2개는 제시하지 않습니다./);
  assert.equal(root.findAll(el => el.getAttribute('data-outcome') === 'cancelled').length, 1);
});

test('a run text is the real count, never padding, with each refused call', () => {
  assert.equal(generationRunText(run({ presented_count: 0, refusals: [{ round: 1, stage: 'generation', reason: 'model response is not valid JSON' }] })),
    '통과한 구조적으로 다른 후보가 0개뿐입니다 (생성 3회 한도). 채워 넣지 않았습니다. 후보 2개 · 모델 호출 7회 · 생성자 test-actor-generator · 평가자 test-actor-critic. 거절된 호출 1개: 1회차 생성 — model response is not valid JSON.');
  assert.match(generationRunText(run({ outcome: 'filled', rounds: 1, presented_count: 3 })), /^기본 3안을 채웠습니다 \(생성 1회\)\./);
});

test('an edit is re-reviewable when the generation turn realizes it; a simulated qualification is labelled', async () => {
  const derivation = { derivation_id: id(71), action: 'edit', parent_candidate_ids: [id(11)], instruction: '줄인다',
    re_review_required: true, inherited_verdict: null, created_at_utc: '2026-09-25T00:00:00.000000Z', reviewed_candidate: null };
  const { root, workspace, calls, replies } = harness({ derivations: [derivation],
    review: { available: true, reason: null, critic_model_id: 'test-actor-critic', realizes: ['select', 'edit'] } });
  await workspace.load();
  const row = root.findAll(el => el.getAttribute('data-derivation') === id(71))[0];
  const [review] = buttons(row, 'review');
  assert.equal(review.disabled, false);
  replies.push({ value: {} });
  await review.dispatch('click');
  assert.ok(calls.some(item => item.path.endsWith('/reviews') && item.body.derivation_id === id(71)));
  assert.match(qualificationText({ simulated_qualification: true,
    critic_qualification: { status: 'qualified', reason: 'suite_pass' } }), /시뮬레이션\(테스트 행위자\) 자격이며 출시 자격이 아닙니다/);
  assert.doesNotMatch(qualificationText(viewData().preparation), /시뮬레이션/);
});

test('T038: without a qualified lens the create section states the exact reason and offers no button', async () => {
  const reason = 'no qualified lens decision exists for this work model: no lens is qualified in this installation';
  const root = new FakeElement('section');
  const workspace = createDesignWorkspace({ root, document, commandId: () => id(1),
    workModel: () => ({ work_model_id: id(7), state: 'confirmed' }),
    request: async () => ({ requests: [], unrestorable: [{ request_id: id(8), code: 'not_restorable', reason: 'the stored basis does not belong to this request' }],
      creation: { available: false, reason, source: null } }) });
  await workspace.load();
  const text = root.textContent;
  assert.match(text, /설계 요청을 만들 수 없습니다\. 자격을 갖춘 렌즈 결정이 없기 때문입니다/);
  assert.ok(text.includes(`사유: ${reason}`));
  assert.match(text, /다시 만들지 못했습니다: the stored basis does not belong to this request/);
  assert.equal(buttons(root, 'create-request').length, 0);
});

test('T038: with a qualified lens and an accepted work model the owner creates a request and it is shown', async () => {
  const calls = [];
  let created = false;
  let model = null;
  const request = async (path, options = {}) => {
    calls.push([path, options]);
    if (options.method === 'POST') { created = true; return { request_id: REQUEST, version: 1, requested_candidate_count: 3 }; }
    if (path.endsWith('/design-requests')) {
      return { requests: created ? [{ request_id: REQUEST, version: 1, requested_candidate_count: 3 }] : [], unrestorable: [],
        creation: { available: true, reason: null, source: 'test-actor (SIMULATED lens qualification)' } };
    }
    return viewData();
  };
  const root = new FakeElement('section');
  const workspace = createDesignWorkspace({ root, document, request, commandId: () => id(9), workModel: () => model });
  await workspace.load();
  assert.match(root.textContent, /수락한 작업 모델이 있어야 설계 요청을 만들 수 있습니다/);
  assert.equal(buttons(root, 'create-request').length, 0);
  model = { work_model_id: id(7), state: 'confirmed' };
  workspace.refreshCreation();
  assert.match(root.textContent, /SIMULATED lens qualification/);
  await buttons(root, 'create-request')[0].dispatch('click');
  const post = calls.find(([, options]) => options.method === 'POST');
  assert.deepEqual(post[1].body, { schema_version: 'design-request-create-command-v1', command_id: id(9), work_model_id: id(7) });
  assert.ok(calls.some(([path]) => path.endsWith(`/design-requests/${REQUEST}`)));
  assert.match(root.textContent, /통과한 구조적으로 다른 후보 2개/);
});
