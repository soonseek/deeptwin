// T037/T048: layered layout, node details, graph comparison and the run view's states,
// over a fake document and request. No markup is ever written.

import test from 'node:test';
import assert from 'node:assert/strict';

import { compareGraphs, createGraphView, focusDifference, layers, nodeDetails, runStates } from '../static/graph.mjs';

class FakeElement {
  constructor(tagName) { this.tagName = tagName.toUpperCase(); this.children = []; this.attributes = new Map(); this.dataset = {}; this.listeners = new Map(); this._text = ''; }
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

const ref = (kind, n) => ({ kind, id: `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`, version: 1, sha256: String(n % 10).repeat(64) });
const slot = id => ({ slot_id: id, artifact_contract_id: 'text-document', multiplicity: 'one' });
const node = (id, kind, responsibility, extra = {}) => ({ node_id: id, kind, responsibility, input_slots: [], output_slots: [slot('out')],
  grant_refs: [], required_approval_scopes: [], failure_policy: 'block_dependants',
  config: kind === 'agent' ? { model_binding_id: 'm', required_model_capabilities: ['text'], tool_binding_ids: [], memory_policy_id: null } : { handler_id: 'h' }, ...extra });
const edge = (id, from, to, kind = 'artifact') => ({ edge_id: id, kind, source_node_id: from, target_node_id: to, loop_id: null });
const graph = {
  entry_node_ids: ['intake'],
  nodes: [node('intake', 'deterministic', '원자료 정리'), node('writer', 'agent', '초안 작성'), node('review', 'human_gate', '승인'),
    node('publish', 'deterministic', '확정')],
  edges: [edge('e1', 'intake', 'writer'), edge('e2', 'writer', 'review'), edge('e3', 'review', 'publish'),
    edge('o1', 'intake', 'publish', 'observation')],
  model_bindings: [{ binding_id: 'm', model_choice_ref: ref('model_choice', 3), capabilities: ['text'] }],
  tool_bindings: [], artifact_contracts: [{ artifact_contract_id: 'text-document' }],
};

test('layers follow triggering edges only and every node is placed once', () => {
  const positions = layers(graph);
  assert.deepEqual(['intake', 'writer', 'review', 'publish'].map(id => positions.get(id).column), [0, 1, 2, 3]);
  // a cycle cannot grow the drawing
  const looped = { ...graph, edges: [...graph.edges, { ...edge('back', 'publish', 'writer', 'control'), loop_id: 'l' }] };
  assert.equal(layers(looped).get('writer').column, 1);
});

test('node details state what the graph says, bindings included', () => {
  const lines = Object.fromEntries(nodeDetails(graph, 'writer'));
  assert.equal(lines['종류'], '에이전트');
  assert.equal(lines['책임'], '초안 작성');
  assert.match(lines['모델'], /model_choice:00000000-0000-4000-8000-000000000003 v1 · text/);
  assert.equal(lines['들어오는 연결'], 'intake (artifact)');
  assert.deepEqual(nodeDetails(graph, 'absent'), []);
});

test('two graphs compare by node, edge and binding, and one node is compared in focus', () => {
  const other = { ...graph,
    nodes: [graph.nodes[0], { ...graph.nodes[1], responsibility: '근거 기반 초안 작성' }, node('check', 'agent', '사실 검토'),
      graph.nodes[3]],
    edges: [edge('e1', 'intake', 'writer'), edge('e4', 'writer', 'check'), edge('e5', 'check', 'publish')] };
  const difference = compareGraphs(graph, other);
  assert.deepEqual(difference.nodes.added, ['check']);
  assert.deepEqual(difference.nodes.removed, ['review']);
  assert.deepEqual(difference.nodes.changed, [{ id: 'writer', fields: ['responsibility'] }]);
  assert.deepEqual(difference.edges.removed, ['e2', 'e3', 'o1']);
  assert.equal(focusDifference(graph, other, 'writer').state, 'changed');
  assert.equal(focusDifference(graph, other, 'review').state, 'removed');
  assert.equal(focusDifference(graph, other, 'intake').state, 'same');
});

test('the view draws every node, selecting shows details, and a run shows its recorded states', async () => {
  const root = new FakeElement('section');
  const asked = [];
  const receipt = { graph_ref: ref('graph', 7), outcome: { completed_node_ids: ['intake', 'writer'], failed_node_ids: [],
    pending_node_ids: ['publish'], awaiting_human: [['review', 'release-output']] } };
  const request = async path => { asked.push(path); return path.includes('/graphs/') ? { graph_ref: receipt.graph_ref, graph } : receipt; };
  const view = createGraphView({ root, document, request });
  const run = '00000000-0000-4000-8000-00000000e0e1';
  await view.showRun(run);
  assert.deepEqual(asked, [`/api/v1/runs/${run}`, `/api/v1/graphs/${receipt.graph_ref.id}/versions/1`]);
  const buttons = root.findAll(el => el.tagName === 'BUTTON');
  assert.deepEqual(buttons.map(button => button.textContent),
    ['intake · 정해진 처리 · 완료', 'writer · 에이전트 · 완료', 'review · 사람 승인 · 승인 대기', 'publish · 정해진 처리 · 대기']);
  await buttons[1].dispatch('click');
  assert.match(root.textContent, /실행 상태완료/);
  assert.match(root.textContent, /책임초안 작성/);
  assert.equal(buttons[1].getAttribute('aria-pressed'), 'true');
  assert.equal(runStates({ outcome: {} }, graph).get('writer'), 'not_visited');
});
