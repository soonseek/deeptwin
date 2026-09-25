// T037/T048: a large, readable functional graph and a same-focus comparison of two graphs.
// The graph is the parsed `graph-version-v1` the server returns (GET {base}api/v1/graphs/…);
// nothing here edits, compiles or runs one. Layout is layered by the triggering edges
// (observation edges are drawn but never order nodes), every node shows its id, kind and
// responsibility, and selecting a node shows everything the graph says about it — slots,
// model and tool bindings, grants, required approvals, failure policy. `compareGraphs`
// lists what two graphs differ in; `focusDifference` says it for one node present in
// either. A run's node states come only from its recorded outcome. All text goes through
// textContent; nothing is ever written as markup.

const SVG = 'http://www.w3.org/2000/svg';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
const COLUMN = 240;
const ROW = 96;
const BOX_W = 200;
const BOX_H = 64;

export const KIND_LABELS = Object.freeze({
  agent: '에이전트', deterministic: '정해진 처리', router: '분기', join: '합류', human_gate: '사람 승인',
  bounded_loop: '제한 반복',
});
export const STATE_LABELS = Object.freeze({
  completed: '완료', failed: '실패', pending: '대기', awaiting: '승인 대기', not_visited: '미방문',
});

function fail(message) {
  throw Object.assign(new Error(message), { code: 'invalid_input' });
}

function triggering(edge) {
  return edge.kind !== 'observation';
}

// breadth-first layering over triggering edges from the entries: each node sits one
// column after the nearest node that triggers it, so a bounded loop's cycle cannot
// grow the drawing (every node is placed once)
export function layers(graph) {
  const ids = graph.nodes.map(node => node.node_id);
  const depth = new Map(ids.map(id => [id, null]));
  const queue = graph.entry_node_ids.filter(id => depth.has(id));
  for (const id of queue) depth.set(id, 0);
  for (let index = 0; index < queue.length; index += 1) {
    const from = queue[index];
    for (const edge of graph.edges) {
      if (!triggering(edge) || edge.source_node_id !== from || depth.get(edge.target_node_id) !== null) continue;
      depth.set(edge.target_node_id, depth.get(from) + 1);
      queue.push(edge.target_node_id);
    }
  }
  const unreachable = Math.max(0, ...[...depth.values()].filter(value => value !== null)) + 1;
  const columns = new Map();
  for (const id of ids) {
    const column = depth.get(id) ?? unreachable;
    columns.set(column, [...(columns.get(column) ?? []), id]);
  }
  const positions = new Map();
  for (const [column, members] of columns) members.forEach((id, row) => positions.set(id, { column, row }));
  return positions;
}

function describe(value) {
  if (value === null || value === undefined) return '없음';
  if (typeof value === 'object' && value.kind && value.id) return `${value.kind}:${value.id} v${value.version}`;
  return typeof value === 'string' ? value : JSON.stringify(value);
}

// everything the graph states about one node, as labelled lines
export function nodeDetails(graph, nodeId) {
  const node = graph.nodes.find(item => item.node_id === nodeId);
  if (!node) return [];
  const lines = [
    ['종류', KIND_LABELS[node.kind] ?? node.kind],
    ['책임', node.responsibility],
    ['입력', node.input_slots.map(slot => `${slot.slot_id} (${slot.artifact_contract_id}${slot.required ? ', 필수' : ''})`).join(', ') || '없음'],
    ['출력', node.output_slots.map(slot => `${slot.slot_id} (${slot.artifact_contract_id})`).join(', ') || '없음'],
    ['실패 시', node.failure_policy],
    ['필요한 승인', node.required_approval_scopes.join(', ') || '없음'],
    ['권한', node.grant_refs.map(describe).join(', ') || '없음'],
  ];
  const config = node.config ?? {};
  if (node.kind === 'agent') {
    const model = graph.model_bindings.find(item => item.binding_id === config.model_binding_id);
    lines.push(['모델', model ? `${describe(model.model_choice_ref)} · ${model.capabilities.join(', ')}` : '연결 없음']);
    const tools = config.tool_binding_ids.map(id => graph.tool_bindings.find(item => item.binding_id === id))
      .filter(Boolean).map(item => `${item.binding_id} → ${describe(item.tool_definition_ref)}`);
    lines.push(['도구', tools.join(', ') || '없음']);
    lines.push(['기억', config.memory_policy_id ?? '없음']);
  } else {
    lines.push(['설정', JSON.stringify(config)]);
  }
  const incoming = graph.edges.filter(edge => edge.target_node_id === nodeId).map(edge => `${edge.source_node_id} (${edge.kind})`);
  const outgoing = graph.edges.filter(edge => edge.source_node_id === nodeId).map(edge => `${edge.target_node_id} (${edge.kind})`);
  lines.push(['들어오는 연결', incoming.join(', ') || '없음'], ['나가는 연결', outgoing.join(', ') || '없음']);
  return lines;
}

function byId(items, key) {
  return new Map(items.map(item => [item[key], item]));
}

function changedFields(left, right) {
  return [...new Set([...Object.keys(left), ...Object.keys(right)])]
    .filter(name => JSON.stringify(left[name]) !== JSON.stringify(right[name])).sort();
}

// what two graphs differ in: nodes, edges and bindings added, removed or changed
export function compareGraphs(left, right) {
  const result = {};
  for (const [name, collection, key] of [['nodes', 'nodes', 'node_id'], ['edges', 'edges', 'edge_id'],
    ['model_bindings', 'model_bindings', 'binding_id'], ['tool_bindings', 'tool_bindings', 'binding_id'],
    ['artifact_contracts', 'artifact_contracts', 'artifact_contract_id']]) {
    const a = byId(left[collection], key);
    const b = byId(right[collection], key);
    result[name] = {
      added: [...b.keys()].filter(id => !a.has(id)).sort(),
      removed: [...a.keys()].filter(id => !b.has(id)).sort(),
      changed: [...a.keys()].filter(id => b.has(id)).map(id => ({ id, fields: changedFields(a.get(id), b.get(id)) }))
        .filter(item => item.fields.length),
    };
  }
  result.entry_node_ids = JSON.stringify(left.entry_node_ids) === JSON.stringify(right.entry_node_ids)
    ? null : { left: left.entry_node_ids, right: right.entry_node_ids };
  return result;
}

// the difference for one node, with its details on each side
export function focusDifference(left, right, nodeId) {
  const a = left.nodes.find(item => item.node_id === nodeId) ?? null;
  const b = right.nodes.find(item => item.node_id === nodeId) ?? null;
  const state = a && b ? (changedFields(a, b).length ? 'changed' : 'same') : a ? 'removed' : b ? 'added' : 'absent';
  return { node_id: nodeId, state, fields: a && b ? changedFields(a, b) : [],
    left: a ? nodeDetails(left, nodeId) : [], right: b ? nodeDetails(right, nodeId) : [] };
}

// node states from a run's recorded outcome only; a node never visited says so
export function runStates(receipt, graph) {
  const outcome = receipt?.outcome ?? {};
  const states = new Map(graph.nodes.map(node => [node.node_id, 'not_visited']));
  for (const id of outcome.pending_node_ids ?? []) states.set(id, 'pending');
  for (const id of outcome.completed_node_ids ?? []) states.set(id, 'completed');
  for (const id of outcome.failed_node_ids ?? []) states.set(id, 'failed');
  for (const entry of outcome.awaiting_human ?? []) states.set(Array.isArray(entry) ? entry[0] : entry, 'awaiting');
  // T087: a gated tool node waiting on its own attempt's decision (entry[3] is the executing node)
  for (const entry of outcome.awaiting_execution ?? []) if (Array.isArray(entry)) states.set(entry[3], 'awaiting');
  return states;
}

export function createGraphView({ root, document, request = null, basePath = '/' } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const api = `${basePath.slice(0, -1)}/api/v1`;
  const svgElement = tag => (typeof document.createElementNS === 'function'
    ? document.createElementNS(SVG, tag) : document.createElement(tag));

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', '', { role: 'status', 'aria-live': 'polite' });
  const canvas = element('div', undefined, { class: 'graph-canvas' });
  const details = element('dl', undefined, { class: 'graph-details', 'aria-label': '선택한 노드' });
  root.replaceChildren(element('h2', '작업 그래프'), status, canvas, details);
  let current = null;

  function select(nodeId) {
    if (!current) return;
    const lines = nodeDetails(current.graph, nodeId);
    const state = current.states?.get(nodeId);
    details.replaceChildren(element('dt', '노드'), element('dd', nodeId),
      ...(state ? [element('dt', '실행 상태'), element('dd', STATE_LABELS[state] ?? state)] : []),
      ...lines.flatMap(([label, value]) => [element('dt', label), element('dd', String(value))]));
    for (const box of canvas.querySelectorAll?.('[data-node]') ?? []) {
      box.setAttribute('aria-pressed', box.getAttribute('data-node') === nodeId ? 'true' : 'false');
    }
  }

  function show(graph, { states = null } = {}) {
    current = { graph, states };
    const positions = layers(graph);
    const columns = Math.max(1, ...[...positions.values()].map(item => item.column + 1));
    const rows = Math.max(1, ...[...positions.values()].map(item => item.row + 1));
    const svg = svgElement('svg');
    svg.setAttribute('viewBox', `0 0 ${columns * COLUMN} ${rows * ROW}`);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `노드 ${graph.nodes.length}개, 연결 ${graph.edges.length}개`);
    const center = id => {
      const at = positions.get(id);
      return { x: at.column * COLUMN + 20, y: at.row * ROW + 16 };
    };
    for (const edge of graph.edges) {
      const from = center(edge.source_node_id);
      const to = center(edge.target_node_id);
      const line = svgElement('line');
      for (const [name, value] of Object.entries({ x1: from.x + BOX_W, y1: from.y + BOX_H / 2, x2: to.x,
        y2: to.y + BOX_H / 2, class: `graph-edge graph-edge-${edge.kind}`, 'data-edge': edge.edge_id })) {
        line.setAttribute(name, String(value));
      }
      svg.append(line);
    }
    // nodes as keyboard-reachable buttons beside the drawing, in layer order
    const list = element('ol', undefined, { class: 'graph-nodes', 'aria-label': '노드' });
    const ordered = [...graph.nodes].sort((a, b) => {
      const pa = positions.get(a.node_id); const pb = positions.get(b.node_id);
      return pa.column - pb.column || pa.row - pb.row;
    });
    for (const node of ordered) {
      const at = center(node.node_id);
      const state = states?.get(node.node_id) ?? null;
      const box = svgElement('g');
      box.setAttribute('class', `graph-node graph-node-${node.kind}${state ? ` graph-state-${state}` : ''}`);
      box.setAttribute('data-node', node.node_id);
      const rect = svgElement('rect');
      for (const [name, value] of Object.entries({ x: at.x, y: at.y, width: BOX_W, height: BOX_H, rx: 8 })) {
        rect.setAttribute(name, String(value));
      }
      const title = svgElement('text');
      title.setAttribute('x', String(at.x + 10)); title.setAttribute('y', String(at.y + 22));
      title.textContent = `${node.node_id} · ${KIND_LABELS[node.kind] ?? node.kind}`;
      const body = svgElement('text');
      body.setAttribute('x', String(at.x + 10)); body.setAttribute('y', String(at.y + 44));
      body.textContent = node.responsibility.length > 24 ? `${node.responsibility.slice(0, 23)}…` : node.responsibility;
      box.append(rect, title, body);
      box.addEventListener?.('click', () => select(node.node_id));
      svg.append(box);
      const item = element('li');
      const button = element('button', `${node.node_id} · ${KIND_LABELS[node.kind] ?? node.kind}${state ? ` · ${STATE_LABELS[state]}` : ''}`,
        { type: 'button', 'data-node': node.node_id, 'aria-pressed': 'false' });
      button.addEventListener('click', () => select(node.node_id));
      item.append(button);
      list.append(item);
    }
    canvas.replaceChildren(svg, list);
    details.replaceChildren();
    status.textContent = `노드 ${graph.nodes.length}개 · 연결 ${graph.edges.length}개. 노드를 고르면 자세한 내용을 봅니다.`;
    status.dataset.state = 'shown';
  }

  // the run's own graph with its recorded node states
  async function showRun(runId) {
    if (typeof request !== 'function') fail('a request adapter is required');
    if (typeof runId !== 'string' || !UUID.test(runId)) fail('run id is not a canonical UUID');
    status.textContent = '작업 그래프를 읽는 중…';
    try {
      const receipt = await request(`${api}/runs/${runId}`, {});
      const ref = receipt.graph_ref;
      const read = await request(`${api}/graphs/${ref.id}/versions/${ref.version}`, {});
      show(read.graph, { states: runStates(receipt, read.graph) });
      return read.graph;
    } catch (error) {
      status.textContent = '작업 그래프를 읽지 못했습니다.';
      status.dataset.state = error?.code ?? 'unavailable';
      throw error;
    }
  }

  return Object.freeze({ show, showRun, select });
}
