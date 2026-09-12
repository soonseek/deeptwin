import { ARTIFACTS } from './fixtures.mjs';

export const e = value => String(value ?? '').replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[character]));

export function button(label, action, value = '', active = false) {
  return `<button type="button" data-action="${e(action)}" data-value="${e(value)}" aria-pressed="${Boolean(active)}">${e(label)}</button>`;
}

export const list = items => `<ul>${items.map(item => `<li>${e(item)}</li>`).join('')}</ul>`;
// Presentation only: keep the exact fixture label, ID and original bytes.
export const artifactLabel = file => file.label.replace(/ · synthetic UI fixture$/, '');

const NODE_WIDTH = 140;
const NODE_HEIGHT = 48;
const nodeKinds = { agent: '에이전트', control: '통제', resource: '자원' };
const edgeKinds = { task: '산출물', control: '통제', memory: '기억', tool: '도구·모델', telemetry: '관측', revisit: '되돌아감' };
let graphInstance = 0;

function port(node, side, offset = 0) {
  if (side === 'left' || side === 'right') {
    return { x: node.x + (side === 'right' ? NODE_WIDTH : 0), y: node.y + NODE_HEIGHT / 2 + offset };
  }
  return { x: node.x + NODE_WIDTH / 2 + offset, y: node.y + (side === 'bottom' ? NODE_HEIGHT : 0) };
}

function outside(point, side, distance) {
  return {
    x: point.x + (side === 'right' ? distance : side === 'left' ? -distance : 0),
    y: point.y + (side === 'bottom' ? distance : side === 'top' ? -distance : 0),
  };
}

function crossesNode(a, b, node) {
  return a.x === b.x
    ? a.x > node.x && a.x < node.x + NODE_WIDTH
      && Math.max(a.y, b.y) > node.y && Math.min(a.y, b.y) < node.y + NODE_HEIGHT
    : a.y > node.y && a.y < node.y + NODE_HEIGHT
      && Math.max(a.x, b.x) > node.x && Math.min(a.x, b.x) < node.x + NODE_WIDTH;
}

function compact(points) {
  const result = [];
  for (const point of points) {
    const last = result.at(-1);
    if (last?.x === point.x && last?.y === point.y) continue;
    const previous = result.at(-2);
    if (previous && ((previous.x === last.x && last.x === point.x)
      || (previous.y === last.y && last.y === point.y))) result.pop();
    result.push(point);
  }
  return result;
}

const distance = (a, b) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y);

// The fixture layouts use fixed boxes. Try their free horizontal/vertical
// channels instead of changing positions or introducing a layout engine.
function routeEdge(graph, edge, index) {
  const source = graph.nodes.find(node => node.id === edge.from);
  const target = graph.nodes.find(node => node.id === edge.to);
  let sourceSide;
  let targetSide;
  if (edge.kind === 'revisit') {
    sourceSide = targetSide = 'left';
  } else if (source.x !== target.x) {
    sourceSide = source.x < target.x ? 'right' : 'left';
    targetSide = source.x < target.x ? 'left' : 'right';
  } else {
    sourceSide = source.y < target.y ? 'bottom' : 'top';
    targetSide = source.y < target.y ? 'top' : 'bottom';
  }
  const paired = graph.edges.some(other => other.from === edge.to && other.to === edge.from);
  const offset = paired ? (edge.from < edge.to ? -8 : 8) : 0;
  const start = port(source, sourceSide, offset);
  const end = port(target, targetSide, offset);
  const clearance = 10 + (index % 3) * 4;
  const a = outside(start, sourceSide, clearance);
  const b = outside(end, targetSide, clearance);
  const candidates = [
    [a, { x: b.x, y: a.y }, b],
    [a, { x: a.x, y: b.y }, b],
  ];
  const xs = new Set(graph.nodes.flatMap(node => [node.x - clearance, node.x + NODE_WIDTH + clearance]));
  const ys = new Set(graph.nodes.flatMap(node => [node.y - clearance, node.y + NODE_HEIGHT + clearance]));
  for (const x of xs) candidates.push([a, { x, y: a.y }, { x, y: b.y }, b]);
  for (const y of ys) candidates.push([a, { x: a.x, y }, { x: b.x, y }, b]);
  const routes = candidates.map(candidate => compact([start, ...candidate, end]))
    .filter(points => points.every((point, position) => position === 0
      || !graph.nodes.some(node => crossesNode(points[position - 1], point, node))));
  const cost = points => points.slice(1).reduce((total, point, position) => total + distance(points[position], point), 0)
    + points.length * 8;
  routes.sort((left, right) => cost(left) - cost(right));
  if (!routes.length) throw new Error(`No clear fixture edge route: ${graph.id}/${edge.from}/${edge.to}`);
  return routes[0];
}

export function graph(g, selected = [], action = 'node', prefix = '') {
  const marker = `graph-arrow-${++graphInstance}`;
  const identity = JSON.stringify([g.id, action, prefix]);
  const edges = g.edges.map((edge, index) => {
    const route = routeEdge(g, edge, index);
    const path = route.map((point, step) => `${step ? 'L' : 'M'} ${point.x} ${point.y}`).join(' ');
    const source = g.nodes.find(node => node.id === edge.from);
    const target = g.nodes.find(node => node.id === edge.to);
    const label = `${source.label} → ${target.label} · ${edgeKinds[edge.kind] ?? edge.kind}`;
    return `<path data-edge="${index}" class="edge ${e(edge.kind)}" d="${e(path)}" fill="none" marker-end="url(#${marker})" role="img" aria-label="${e(label)}"><title>${e(label)}</title></path>`;
  }).join('');
  const nodes = g.nodes.map(node => {
    const active = selected.includes(node.id);
    return `<g class="node ${e(node.kind)}${active ? ' selected' : ''}" transform="translate(${e(node.x)} ${e(node.y)})" role="button" tabindex="0" aria-label="${e(node.label)}" aria-pressed="${active}" data-action="${e(action)}" data-value="${e(prefix + node.id)}">`
      + `<rect width="140" height="48" rx="6"/><text x="12" y="20">${e(node.label)}</text><text class="kind" x="12" y="37">${e(nodeKinds[node.kind] ?? node.kind)}</text></g>`;
  }).join('');
  const legend = [...new Set(g.edges.map(edge => edge.kind))]
    .map(kind => `<span class="edge-key ${e(kind)}" role="listitem">${e(edgeKinds[kind] ?? kind)}</span>`).join('');
  return `<div class="graph-legend" role="list" aria-label="관계선 종류">${legend}</div>`
    + `<div class="graph-scroll" tabindex="0" aria-label="관계도 가로 탐색" data-graph-id="${e(identity)}">`
    + `<svg class="graph" viewBox="0 0 900 520" role="group" aria-label="${e(g.label ?? g.id)} 관계도">`
    + `<defs><marker id="${marker}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke"/></marker></defs>`
    + edges + nodes + '</svg></div>';
}

function scopeControls(file, scope) {
  const region = scope.kind === 'region' ? file.regions.find(item => item.id === scope.id) : null;
  const textScope = scope.kind === 'text' && file.type === 'text';
  const current = region ? region.label : textScope ? `문자 ${scope.start}–${scope.end}` : '전체';
  const excerpt = region ? region.text : textScope ? file.body.slice(scope.start, scope.end) : null;
  return '<div class="artifact-scopes">'
    + button('전체', 'scope', 'whole', !region && !textScope)
    + file.regions.filter(item => item.id !== 'whole').map(item => button(item.label, 'scope', item.id, region?.id === item.id)).join('')
    + (file.type === 'text' ? button('선택한 실제 문구', 'textScope', '', textScope) : '')
    + `</div><p class="scope-summary">현재 범위: ${e(current)}</p>`
    + (excerpt === null ? '' : `<blockquote data-selected-region="${e(region?.id ?? 'text')}">${e(excerpt)}</blockquote>`);
}

export function artifact(id, { selectable = false, scope = { kind: 'whole' } } = {}) {
  if (id == null) return '<p class="empty-artifact">출력 없음 · 다른 시도의 최신 파일로 채우지 않음</p>';
  if (!Object.hasOwn(ARTIFACTS, id)) return '<p class="empty-artifact">산출물 미확인</p>';
  const file = ARTIFACTS[id];
  let content;
  if (file.type === 'text') {
    content = `<pre${selectable ? ' id="original-body"' : ''}>${e(file.body)}</pre>`;
  } else if (file.type === 'csv') {
    // These authored fixtures contain unquoted cells, not imported CSV data.
    const [header, ...rows] = file.body.trimEnd().split('\n').map(row => row.split(','));
    const cells = (row, tag) => row.map(cell => `<${tag}>${e(cell)}</${tag}>`).join('');
    content = `<table><thead><tr>${cells(header, 'th')}</tr></thead><tbody>`
      + rows.map(row => `<tr>${cells(row, 'td')}</tr>`).join('') + '</tbody></table>';
  } else if (file.type === 'svg') {
    content = `<div class="artifact-canvas"><img class="artifact-image" src="${e(file.path)}" alt="${e(file.label)} · 전체 시각 일정"/></div>`;
  } else if (file.type === 'pdf') {
    content = '<p class="preview-notice">원 PDF의 동일 조판 자료로 만든 SVG 파생 미리보기 · 원본은 아래 파일에서 확인</p>'
      + `<div class="artifact-canvas"><img class="artifact-image pdf" src="${e(file.preview)}" alt="${e(file.label)} · 원 PDF의 SVG 파생 미리보기"/></div>`;
  }
  return `<article data-artifact="${e(file.id)}"><header title="${e(file.label)}"><strong>${e(artifactLabel(file))}</strong><small>${e(file.id)} · ${e(file.type)}</small></header>`
    + (selectable ? scopeControls(file, scope) : '') + content
    + `<a href="${e(file.path)}" target="_blank" rel="noopener" download>원본 파일 열기/받기</a></article>`;
}
