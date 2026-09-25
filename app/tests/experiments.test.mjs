// T066: paired comparison rounds as recorded — pairs, honest validity, no score on
// an invalid round, unreadable records listed rather than dropped.

import test from 'node:test';
import assert from 'node:assert/strict';

import { MESSAGES, outcomeText, renderRounds, roundsByLineage } from '../static/experiments.mjs';
import { createVersionsPanel } from '../static/versions.mjs';

class FakeElement {
  constructor(tagName) { this.tagName = tagName.toUpperCase(); this.children = []; this.attributes = new Map(); this.dataset = {}; this._text = ''; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(_value) { throw new Error('markup is never written'); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener() {}
  findAll(predicate, found = []) { for (const child of this.children) { if (predicate(child)) found.push(child); child.findAll(predicate, found); } return found; }
}

const document = { createElement: tag => new FakeElement(tag) };
const ref = (kind, n) => ({ kind, id: `${String(n).padStart(8, '0')}-0000-4000-8000-000000000000`, version: 1, sha256: String(n % 10).repeat(64) });
const LINEAGE = 'abcdef12-0000-4000-8000-000000000000';

function round(index, overrides = {}) {
  return { readable: true, round_record: ref('decision_record', 90 + index), lineage_id: LINEAGE, plan_mode: 'automatic',
    baseline_environment_ref: ref('environment', 1), round_id: `round-${index}`, round_index: index,
    candidate_ref: ref('change_candidate', 5),
    pairs: [{ baseline_run_ref: ref('run_manifest', 11), candidate_run_ref: ref('run_manifest', 21) },
      { baseline_run_ref: ref('run_manifest', 12), candidate_run_ref: ref('run_manifest', 22) }],
    validity: 'valid', validity_reasons: [], metric_vector: { accuracy: '0.9' }, utility: '0.85', evidence_refs: [ref('artifact', 7)],
    ...overrides };
}

test('rounds are grouped by lineage in recorded order; unreadable ones are kept', () => {
  const { lineages, unreadable } = roundsByLineage([round(2), round(0), { readable: false, round_record: ref('decision_record', 99) }]);
  assert.deepEqual(lineages.get(LINEAGE).map(item => item.round_index), [0, 2]);
  assert.equal(unreadable.length, 1);
});

test('only a valid round shows measurements and utility', () => {
  assert.match(outcomeText(round(0)), /유효 · accuracy 0\.9 · 효용 0\.85/);
  const invalid = outcomeText(round(1, { validity: 'invalid', validity_reasons: ['기준 실행 중단'], metric_vector: null, utility: null }));
  assert.match(invalid, /무효 · 사유: 기준 실행 중단/);
  assert.ok(invalid.includes(MESSAGES.noScore));
  assert.doesNotMatch(invalid, /효용 [0-9]/);
  assert.ok(outcomeText(round(2, { validity: 'pending', metric_vector: null, utility: null })).startsWith('판정 대기'));
});

test('each baseline run is shown next to the candidate run it was paired with', () => {
  const root = new FakeElement('section');
  const counts = renderRounds({ root, document, rounds: [round(0), { readable: false, round_record: ref('decision_record', 99) }] });
  assert.deepEqual(counts, { lineages: 1, unreadable: 1 });
  const rows = root.findAll(el => el.tagName === 'TR').slice(1);
  assert.deepEqual(rows.map(row => row.children.map(cell => cell.textContent)), [
    ['run_manifest 00000011 (111111111111)', 'run_manifest 00000021 (111111111111)'],
    ['run_manifest 00000012 (222222222222)', 'run_manifest 00000022 (222222222222)'],
  ]);
  assert.match(root.textContent, /짝지은 실행 2쌍/);
  assert.ok(root.textContent.includes(MESSAGES.artifacts));
  assert.ok(root.textContent.includes(MESSAGES.unreadable));
});

test('no rounds says so, and the versions panel renders the rounds it read', async () => {
  const empty = new FakeElement('section');
  renderRounds({ root: empty, document, rounds: [] });
  assert.ok(empty.textContent.includes(MESSAGES.none));
  const root = new FakeElement('section');
  const panel = createVersionsPanel({ root, document, crypto: { randomUUID: () => 'x' },
    request: async () => ({ state: null, candidates: [], experiments: [], rounds: [round(0)] }) });
  await panel.load();
  assert.match(root.textContent, /라운드 0 \(round-0\)/);
});

test('a round shows both sides\' node results side by side, changes and out-of-scope nodes marked', async () => {
  const { outputsView, MESSAGES: TEXT } = await import('../static/experiments.mjs');
  const made = [];
  const element = (tag, text, attributes = {}) => {
    const node = { tag, text: text ?? '', attributes, children: [], append(...nodes) { this.children.push(...nodes); } };
    made.push(node);
    return node;
  };
  const [table] = outputsView(element, [{ item_index: 0, changed_nodes: ['writer'], unexplained_nodes: [],
    baseline: [{ node_id: 'writer', result_text: '{"text":"a"}', truncated: false, result_bytes: 12 },
      { node_id: 'intake', result_text: '{"x":1}', truncated: false, result_bytes: 7 }],
    candidate: [{ node_id: 'writer', result_text: '{"text":"b"}', truncated: true, result_bytes: 9000 },
      { node_id: 'intake', result_text: '{"x":1}', truncated: false, result_bytes: 7 }] }]);
  const rows = table.children.filter(child => child.tag === 'tr' && child.attributes['data-changed'] !== undefined);
  assert.deepEqual(rows.map(row => [row.children[0].text, row.attributes['data-changed']]),
    [['intake', 'false'], ['writer · 다름', 'true']]);
  assert.match(rows[1].children[2].text, /\(9000바이트 중 일부\)/);
  assert.equal(outputsView(element, null)[0].text, TEXT.noOutputs);
  assert.equal(outputsView(element, 'unreadable')[0].text, TEXT.outputsUnreadable);
});

test('G-14: a round lists each item outcome and the isolation boundary each tool call used', async () => {
  const { itemOutcomesView, effectText, MESSAGES: TEXT } = await import('../static/experiments.mjs');
  const element = (tag, text, attributes = {}) => ({ tag, text: text ?? '', attributes, children: [],
    append(...nodes) { this.children.push(...nodes); } });
  const replay = { tool_id: 'test_actor_notify', version: '1.0.0', effect_class: 'external_irreversible',
    boundary: 'replay', inputs_digest: 'a'.repeat(64), tool_call_id: 'x', tool_call_sha256: 'b'.repeat(64),
    record_sha256: 'c'.repeat(64) };
  const sink = { ...replay, boundary: 'isolated_sink', sink_id: 'g14-sink', inputs_digest: 'd'.repeat(64) };
  const [note, list] = itemOutcomesView(element, [
    { item_index: 0, outcome: 'compared', reasons: [], past_tool_effects: [], baseline_effects: [], candidate_effects: [] },
    { item_index: 1, outcome: 'compared', reasons: [], past_tool_effects: [{ tool_id: 'test_actor_notify', version: '1.0.0',
      tool_call_sha256: 'b'.repeat(64) }], baseline_effects: [replay], candidate_effects: [sink] },
    { item_index: 2, outcome: 'not_comparable', reasons: ['the replay boundary is not approved'], past_tool_effects: [],
      baseline_effects: [], candidate_effects: [] },
  ]);
  assert.equal(note.text, TEXT.effects);
  const [plain, sent, refused] = list.children;
  assert.equal(plain.text, '항목 0: 비교함');
  assert.equal(plain.children[0].children[0].text, '도구 호출 없음');
  assert.equal(sent.text, `항목 1: 비교함 · 과거 외부 효과 1건: test_actor_notify 1.0.0 (ToolCall 기록 ${'b'.repeat(12)})`);
  assert.deepEqual(sent.children[0].children.map(child => child.text), [`기준: ${effectText(replay)}`, `후보: ${effectText(sink)}`]);
  assert.match(effectText(replay), /기록 재생: ToolCall 기록 b{12}의 결과 · 실제 서비스로 다시 보내지 않음$/);
  assert.match(effectText(sink), /격리 싱크 g14-sink에 보관\(입력 sha256 d{12}\) · 실제 서비스로 보내지 않음$/);
  assert.equal(refused.text, '항목 2: 비교 불가 · 사유: the replay boundary is not approved');
  assert.equal(refused.attributes['data-item-outcome'], 'not_comparable');
  assert.deepEqual(itemOutcomesView(element, null), []);
  assert.equal(itemOutcomesView(element, 'unreadable')[0].text, TEXT.outcomesUnreadable);
});
