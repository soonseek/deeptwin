import test from 'node:test';
import assert from 'node:assert/strict';
import { ARTIFACTS, DESIGNS, REVISED_DESIGN, RUNS } from '../fixtures.mjs';
import { e, button, list, graph, artifact } from '../primitives.mjs';

const graphs = [...DESIGNS, REVISED_DESIGN, ...Object.values(RUNS)];
const attributes = markup => Object.fromEntries([...markup.matchAll(/([\w-]+)="([^"]*)"/g)].map(match => [match[1], match[2]]));
const edgePaths = markup => [...markup.matchAll(/<path\b[^>]*data-edge="\d+"[^>]*>/g)].map(match => attributes(match[0]));
const points = path => [...path.matchAll(/[ML]\s*(-?[\d.]+)[ ,]+(-?[\d.]+)/g)].map(match => ({ x: Number(match[1]), y: Number(match[2]) }));

test('text helpers escape content and every action attribute', () => {
  assert.equal(e(null), '');
  assert.equal(e(undefined), '');
  assert.equal(e('&<>"\''), '&amp;&lt;&gt;&quot;&#39;');
  assert.equal(e('</textarea><script>'), '&lt;/textarea&gt;&lt;script&gt;');
  assert.equal(button('<go>', 'a"', 'v"', true), '<button type="button" data-action="a&quot;" data-value="v&quot;" aria-pressed="true">&lt;go&gt;</button>');
  assert.match(button('Go', 'go'), /data-value="" aria-pressed="false"/);
  assert.equal(list(['<one>', '&two']), '<ul><li>&lt;one&gt;</li><li>&amp;two</li></ul>');
});

test('every fixture graph renders all nodes and edges with accessible focus and stable identity', () => {
  for (const design of graphs) {
    const selected = design.focus?.transfer ?? design.nodes.slice(0, 2).map(node => node.id);
    const markup = graph(design, selected, 'designNode', `${design.id}:selected:`);
    assert.match(markup, /class="graph-scroll"[^>]*tabindex="0"[^>]*aria-label="관계도 가로 탐색"/);
    assert.match(markup, /<svg[^>]*class="graph"[^>]*viewBox="0 0 900 520"[^>]*role="group"[^>]*aria-label="[^"]*관계도/);
    assert.equal((markup.match(/<g class="node /g) ?? []).length, design.nodes.length);
    assert.equal(edgePaths(markup).length, design.edges.length);
    for (const node of design.nodes) {
      const tag = [...markup.matchAll(/<g class="node [^>]*>/g)].map(match => attributes(match[0]))
        .find(item => item['data-value'] === `${design.id}:selected:${node.id}`);
      assert.ok(tag, node.id);
      assert.equal(tag.role, 'button');
      assert.equal(tag.tabindex, '0');
      assert.equal(tag['aria-label'], e(node.label));
      assert.equal(tag['aria-pressed'], String(selected.includes(node.id)));
      assert.equal(tag['data-action'], 'designNode');
      assert.ok(tag.class.includes(node.kind));
    }
    assert.match(markup, /width="140" height="48"/);
    assert.match(markup, /class="kind"[^>]*>에이전트/);
    assert.match(markup, /class="kind"[^>]*>통제/);
    assert.match(markup, /class="kind"[^>]*>자원/);
    const second = graph(design, [], 'designNode', `${design.id}:selected:`);
    assert.equal(attributes(markup)['data-graph-id'], attributes(second)['data-graph-id']);
  }
});

test('graph instances have distinct marker IDs and escaped graph content', () => {
  const first = graph(DESIGNS[0]);
  const second = graph(DESIGNS[0]);
  const ids = [...(first + second).matchAll(/<marker id="([^"]+)"/g)].map(match => match[1]);
  assert.equal(new Set(ids).size, ids.length);
  for (const markup of [first, second]) {
    const localIds = new Set([...markup.matchAll(/<marker id="([^"]+)"/g)].map(match => match[1]));
    for (const edge of edgePaths(markup)) assert.ok(localIds.has(edge['marker-end'].slice(5, -1)));
  }
  const escaped = graph({ id: 'x"', label: '<script>', nodes: [{ id: 'n"', label: '</textarea><script>', kind: 'agent', x: 90, y: 75 }], edges: [] }, [], 'a"', 'p"');
  assert.ok(escaped.includes('&lt;/textarea&gt;&lt;script&gt;'));
  assert.ok(escaped.includes('data-action="a&quot;"'));
  assert.ok(escaped.includes('data-value="p&quot;n&quot;"'));
  assert.ok(!escaped.includes('<script>'));
});

test('graph legends identify actual edge kinds without labels overlapping narrow node gaps', () => {
  for (const model of graphs) {
    const markup = graph(model);
    assert.match(markup, /class="graph-legend"[^>]*aria-label="관계선 종류"/);
    const keys = [...markup.matchAll(/class="edge-key ([^"]+)"/g)].map(match => match[1]);
    assert.deepEqual(keys, [...new Set(model.edges.map(edge => edge.kind))]);
    assert.doesNotMatch(markup, /class="edge-label"/);
    for (const edge of model.edges) {
      const source = model.nodes.find(node => node.id === edge.from);
      const target = model.nodes.find(node => node.id === edge.to);
      assert.ok(markup.includes(`<title>${e(source.label)} → ${e(target.label)} · `));
    }
  }
});

test('direction-aware routes avoid node interiors and distinguish opposite directions', () => {
  const kindLabels = { task: '산출물', control: '통제', memory: '기억', tool: '도구·모델', telemetry: '관측', revisit: '되돌아감' };
  for (const design of graphs) {
    const paths = edgePaths(graph(design));
    paths.forEach((path, index) => {
      const edge = design.edges[index];
      assert.equal(path['data-edge'], String(index));
      assert.ok(path.class.split(' ').includes(edge.kind));
      assert.ok(path['aria-label'].includes(kindLabels[edge.kind]));
      const route = points(path.d);
      assert.ok(route.length >= 2);
      for (let step = 1; step < route.length; step += 1) {
        const a = route[step - 1];
        const b = route[step];
        assert.ok(a.x === b.x || a.y === b.y, 'routes use readable orthogonal segments');
        for (const node of design.nodes) {
          const crosses = a.x === b.x
            ? a.x > node.x && a.x < node.x + 140 && Math.max(a.y, b.y) > node.y && Math.min(a.y, b.y) < node.y + 48
            : a.y > node.y && a.y < node.y + 48 && Math.max(a.x, b.x) > node.x && Math.min(a.x, b.x) < node.x + 140;
          assert.equal(crosses, false, `${design.id} ${edge.from}→${edge.to} crosses ${node.id}`);
        }
      }
      const reverse = design.edges.findIndex(other => other.from === edge.to && other.to === edge.from);
      if (reverse !== -1) assert.notDeepEqual(route, points(paths[reverse].d).reverse());
    });
  }
  const pipeline = edgePaths(graph(DESIGNS[0]));
  const forward = DESIGNS[0].edges.findIndex(edge => edge.from === 'draft' && edge.to === 'review');
  const revisit = DESIGNS[0].edges.findIndex(edge => edge.kind === 'revisit');
  assert.notEqual(pipeline[forward].d, pipeline[revisit].d);
  assert.ok(points(pipeline[revisit].d).some(point => point.x < 585), 'revisit has its own side lane');
});

test('every artifact uses its complete typed contents and its actual original file', () => {
  for (const file of Object.values(ARTIFACTS)) {
    const markup = artifact(file.id);
    assert.ok(markup.includes(`data-artifact="${file.id}"`));
    assert.ok(markup.includes(`<strong>${e(file.label.replace(/ · synthetic UI fixture$/, ''))}</strong>`));
    assert.ok(markup.includes(`<header title="${e(file.label)}">`), 'exact fixture label remains available');
    assert.ok(markup.includes(`href="${file.path}" target="_blank" rel="noopener" download`));
    assert.ok(markup.includes('원본 파일 열기/받기'));
    assert.doesNotMatch(markup, /<(?:object|iframe)\b/);
    if (file.type === 'text') assert.ok(markup.includes(`<pre>${e(file.body)}</pre>`));
    if (file.type === 'csv') {
      assert.match(markup, /<table><thead><tr><th>room<\/th>/);
      assert.equal((markup.match(/<tbody>/g) ?? []).length, 1);
      assert.equal((markup.match(/<tr>/g) ?? []).length, file.body.trimEnd().split('\n').length);
    }
    if (file.type === 'svg') assert.ok(markup.includes(`class="artifact-image" src="${file.path}"`));
    if (file.type === 'pdf') {
      assert.ok(markup.includes(`class="artifact-image pdf" src="${file.preview}"`));
      assert.ok(markup.includes('원 PDF의 동일 조판 자료로 만든 SVG 파생 미리보기 · 원본은 아래 파일에서 확인'));
    }
  }
});

test('empty and unrecognized artifact IDs never substitute another attempt output', () => {
  assert.match(artifact(null), /출력 없음 · 다른 시도의 최신 파일로 채우지 않음/);
  assert.match(artifact('missing'), /산출물 미확인/);
  assert.match(artifact('toString'), /산출물 미확인/);
  assert.doesNotMatch(artifact(null) + artifact('missing'), /href=|<img|<pre/);
});

test('selectable regions preserve real excerpts and reflect current scope', () => {
  const file = ARTIFACTS['brief-j1-origin'];
  const region = file.regions[0];
  const markup = artifact(file.id, { selectable: true, scope: { kind: 'region', id: region.id } });
  assert.ok(markup.includes('data-action="scope" data-value="whole" aria-pressed="false">전체'));
  for (const item of file.regions) assert.ok(markup.includes(`data-value="${item.id}" aria-pressed="${item.id === region.id}">${e(item.label)}`));
  assert.ok(markup.includes(`현재 범위: ${e(region.label)}`));
  assert.ok(markup.includes(`<blockquote data-selected-region="${region.id}">${e(region.text)}</blockquote>`));
  assert.doesNotMatch(markup, /data-action="textScope"/);
  const whole = artifact(file.id, { selectable: true });
  assert.ok(whole.includes('현재 범위: 전체'));
  assert.ok(whole.includes('data-value="whole" aria-pressed="true"'));
});

test('text scopes show only actual source characters and allow selecting actual text', () => {
  const file = ARTIFACTS['source-policy'];
  const markup = artifact(file.id, { selectable: true, scope: { kind: 'text', start: 2, end: 20 } });
  assert.ok(markup.includes(`<pre id="original-body">${e(file.body)}</pre>`));
  assert.ok(markup.includes('data-action="textScope"'));
  assert.ok(markup.includes('선택한 실제 문구'));
  assert.ok(markup.includes('현재 범위: 문자 2–20'));
  assert.ok(markup.includes(`<blockquote data-selected-region="text">${e(file.body.slice(2, 20))}</blockquote>`));
  assert.doesNotMatch(artifact(file.id), /data-action="scope"|id="original-body"/);
});
