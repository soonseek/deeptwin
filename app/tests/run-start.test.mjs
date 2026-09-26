// T048: the work page's run section over a fake document and request — the honest
// absence (production: no approved design, no qualifiable critic), exactly what a run
// uses, the consent through the run-consents route, the start through the runs route and
// the link to the observation page. The environment data is a TEST-ACTOR shape
// (a simulated qualification, labelled). No markup is ever written.

import test from 'node:test';
import assert from 'node:assert/strict';

import { ABSENCE_TEXT, absenceText, createRunStart, usageRows } from '../static/run-start.mjs';

class FakeElement {
  constructor(tagName) { this.tagName = tagName.toUpperCase(); this.children = []; this.attributes = new Map(); this.dataset = {}; this.listeners = new Map(); this._text = ''; this.value = ''; this.checked = false; this.disabled = false; }
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
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const ref = (kind, n, version = 1) => ({ kind, id: id(n), version, sha256: String(n % 10).repeat(64) });
const WORK = id(1);

const entry = {
  environment_ref: ref('environment', 30), environment_id: id(30), version: 1, status: 'prepared', activation: 'not_activated',
  extension_binding_revisions: [], work_revision_ref: ref('work_revision', 1, 2), graph_ref: ref('graph', 31),
  graph: { graph_id: id(31), version: 1, digest: 'd'.repeat(64),
    nodes: [{ node_id: 'research', kind: 'agent', responsibility: '조사' }, { node_id: 'owner-gate', kind: 'human_gate', responsibility: '승인' }],
    model_bindings: [{ binding_id: 'research-model', model_choice_ref: ref('model_choice', 213) }],
    tool_bindings: [{ binding_id: 'browser-read', grant_ref: ref('grant', 214), tool_definition_ref: ref('tool_definition', 215), capabilities: ['browser.read'] }],
    grant_refs: [ref('grant', 214)] },
  approval: { candidate_id: id(40), approved_at: '2026-09-26T00:00:00.000000Z', model_bindings_ref: ref('model_choice', 213),
    tool_permissions_ref: ref('grant', 214), observation_contract_ref: ref('observation_contract', 216) },
  critic_qualification: { status: 'qualified', reason: 'suite_pass', design_id: 'test-actor-v3-verifying-design', simulated: true },
  revision_current: true, usable: true, unusable_reason: null,
};
const policy = { budget_policy_ref: ref('budget_policy', 50), policy_hash: 'e'.repeat(64), profile: 'execution', provider_mode: 'subscription',
  max_model_calls: 3, max_tool_calls: 5, max_node_visits: 9, max_loop_rounds: 2, max_output_bytes: 1000, max_concurrency: 2,
  max_wall_seconds: 60, max_candidates: 1, currency: null, max_api_microunits: null, created_at_utc: '2026-09-26T00:00:00.000000Z' };
const view = (changes = {}) => ({ schema_version: 'run-environments-v1', work: { work_id: WORK, current_revision_ref: ref('work_revision', 1, 2) },
  runs: { available: true, reason: null }, environments: [entry], unresolved: [], absence: null, ...changes });

function harness({ environments = view(), policies = [policy], fail = null } = {}) {
  const calls = [];
  const request = async (path, options = {}) => {
    calls.push({ path, ...options });
    if (path.endsWith('/budget-policies')) return { policies };
    if (path.includes('/run-environments/')) return environments;
    if (fail && path.endsWith(fail.path)) throw Object.assign(new Error(fail.code), { code: fail.code });
    if (path.endsWith('/run-consents')) return { ref: ref('run_consent', 60) };
    if (path.endsWith('/runs')) return { run_id: id(70), phase: 'awaiting_human' };
    return {};
  };
  const root = new FakeElement('section');
  let n = 800;
  const start = createRunStart({ root, document, request, basePath: `/${'2'.repeat(32)}/`, commandId: () => id(n++), workId: () => WORK });
  return { root, start, calls };
}
const startButton = root => root.findAll(el => el.getAttribute('data-command') === 'start')[0];
const checkbox = root => root.findAll(el => el.getAttribute('type') === 'checkbox')[0];

test('production: no prepared environment says exactly why and offers no start', async () => {
  const absent = view({ environments: [], absence: { code: 'no_prepared_environment', reason: 'no_approved_design', critic_qualifiable: false },
    runs: { available: false, reason: 'run_executor_not_configured' } });
  const { root, start, calls } = harness({ environments: absent });
  await start.load();
  assert.equal(calls[0].path, `/${'2'.repeat(32)}/api/v1/run-environments/${WORK}`);
  assert.equal(root.textContent.includes(ABSENCE_TEXT.unqualifiable), true);
  assert.match(root.textContent, /평가자\(critic\) 구성과 렌즈의 자격이 필요한데.*V3 오류 독립성 미검증/);
  assert.equal(startButton(root), undefined);
  assert.equal(calls.some(item => item.method === 'POST'), false);
  assert.equal(absenceText({ absence: { critic_qualifiable: true } }), ABSENCE_TEXT.not_yet);
});

test('what the run uses is shown exactly, with the simulated qualification and the consent scope', async () => {
  const rows = Object.fromEntries(usageRows(entry, policy));
  assert.match(rows['환경 버전'], /버전 1 · 준비됨 \(활성화 아님\)/);
  assert.match(rows['그래프'], /graph 00000000 v1 · 노드 2개: research\(agent\), owner-gate\(human_gate\)/);
  assert.match(rows['작업 수정본'], /수정본 2 \(현재 수정본\)/);
  assert.match(rows['모델 연결'], /research-model → model_choice/);
  assert.match(rows['도구 연결'], /browser-read \[browser.read\] 권한 grant/);
  assert.match(rows['승인된 권한'], /관측 계약 observation_contract/);
  assert.match(rows['평가자 자격'], /qualified \(suite_pass\) — 시뮬레이션\(테스트 행위자\) 자격이며 출시 자격이 아닙니다/);
  assert.match(rows['예산 정책'], /모델 호출 3 · 도구 호출 5/);
  assert.match(rows['동의 범위'], /실행 한 번에만.*외부 쓰기·결제 변경·승격은 포함하지 않습니다/);
  const stale = Object.fromEntries(usageRows({ ...entry, revision_current: false }, null));
  assert.match(stale['작업 수정본'], /더 새 수정본이 있습니다/);
  assert.equal(stale['예산 정책'], '선택되지 않음');
});

test('consent then start through the owner routes, with the exact inputs, then a link to observe', async () => {
  const { root, start, calls } = harness();
  await start.load();
  const button = startButton(root);
  assert.equal(button.disabled, true, 'no start before the owner consents');
  checkbox(root).checked = true;
  await checkbox(root).dispatch('change');
  assert.equal(button.disabled, false);
  await button.dispatch('click');
  const [consent, run] = calls.filter(item => item.method === 'POST');
  const inputs = { graph_ref: entry.graph_ref, work_revision_ref: entry.work_revision_ref, environment_ref: entry.environment_ref,
    budget_policy_ref: policy.budget_policy_ref };
  assert.deepEqual(consent.body, { schema_version: 'run-consent-command-v1', command_id: id(800), ...inputs });
  assert.ok(consent.path.endsWith('/api/v1/run-consents'));
  assert.deepEqual(run.body, { command_id: id(801), ...inputs, consent_ref: ref('run_consent', 60) });
  assert.ok(run.path.endsWith('/api/v1/runs'));
  const link = root.findAll(el => el.tagName === 'A')[0];
  assert.equal(link.getAttribute('href'), `./observe.html#run=${id(70)}`);
  assert.match(root.textContent, /실행 00000000을 시작했습니다 · 상태 awaiting_human/);
});

test('blockers: no budget, no executor; a refused start says why', async () => {
  const noBudget = harness({ policies: [] });
  await noBudget.start.load();
  checkbox(noBudget.root).checked = true;
  await checkbox(noBudget.root).dispatch('change');
  assert.equal(startButton(noBudget.root).disabled, true);
  assert.match(noBudget.root.textContent, /예산 정책이 없습니다/);
  const noRuns = harness({ environments: view({ runs: { available: false, reason: 'run_executor_not_configured' },
    environments: [{ ...entry, usable: false, unusable_reason: 'run_executor_not_configured' }] }) });
  await noRuns.start.load();
  assert.match(noRuns.root.textContent, /실행기가 설정되지 않아/);
  const refused = harness({ fail: { path: '/runs', code: 'access_denied' } });
  await refused.start.load();
  checkbox(refused.root).checked = true;
  await checkbox(refused.root).dispatch('change');
  await startButton(refused.root).dispatch('click');
  assert.match(refused.root.textContent, /시작하지 않았습니다: 서버가 이 입력으로는 실행을 허용하지 않았습니다/);
  assert.throws(() => createRunStart({ root: new FakeElement('div'), document, request: async () => ({}), commandId: () => id(1) }), /work id/);
});
