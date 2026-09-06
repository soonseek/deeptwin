import test from 'node:test';
import assert from 'node:assert/strict';
import { ARTIFACTS, RUNS, DESIGNS, CASE, ROUNDS, REVISED_DESIGN, WORK_MODEL, LOGS } from '../fixtures.mjs';
import { ASSET_FILES, renderAssets, validateAssetPath, pdfBytes, pagePreview } from '../build-assets.mjs';

const nodeIds = graph => new Set(graph.nodes.map(node => node.id));
const topology = graph => graph.edges.map(e => `${e.from}>${e.to}:${e.kind}`).sort().join('|');

test('all fixture records and artifacts identify their synthetic status', () => {
  assert.match(WORK_MODEL.source, /synthetic/i);
  assert.equal(Object.isFrozen(ARTIFACTS), true);
  assert.ok(LOGS.length >= 8);
  for (const artifact of Object.values(ARTIFACTS)) {
    assert.doesNotMatch(artifact.id, /:/);
    assert.equal(typeof artifact.body, 'string');
    assert.ok(artifact.body.length > 30, artifact.id);
    assert.match(artifact.label, /synthetic/i, artifact.id);
    validateAssetPath(artifact.path);
    assert.ok(artifact.regions.length > 0, artifact.id);
    assert.equal(new Set(artifact.regions.map(region => region.id)).size, artifact.regions.length);
    for (const region of artifact.regions) assert.ok(region.text.length > 0);
  }
  assert.equal(new Set(Object.values(ARTIFACTS).map(a => a.path)).size, Object.keys(ARTIFACTS).length);
  for (const log of LOGS) assert.equal(log.source, 'synthetic-fixture');
});

test('every graph reference, focus and coordinate is valid', () => {
  for (const graph of [...DESIGNS, REVISED_DESIGN, ...Object.values(RUNS)]) {
    assert.doesNotMatch(graph.id, /:/);
    const ids = nodeIds(graph);
    assert.equal(ids.size, graph.nodes.length, graph.id);
    for (const node of graph.nodes) {
      assert.doesNotMatch(node.id, /:/);
      assert.ok(['agent', 'control', 'resource'].includes(node.kind));
      assert.ok(node.x >= 80 && node.x <= 750 && node.y >= 50 && node.y <= 450);
    }
    for (const edge of graph.edges) {
      assert.ok(ids.has(edge.from), `${graph.id}: ${edge.from}`);
      assert.ok(ids.has(edge.to), `${graph.id}: ${edge.to}`);
    }
    if (graph.focus) {
      for (const axis of ['transfer', 'approval', 'memory', 'evaluation']) {
        assert.ok(graph.focus[axis].length > 0);
        graph.focus[axis].forEach(id => assert.ok(ids.has(id)));
        assert.ok(graph.contracts[axis].length > 30);
      }
    }
  }
});

test('the three candidates differ in authority, memory, evaluation and real topology', () => {
  assert.equal(DESIGNS.length, 3);
  assert.equal(new Set(DESIGNS.map(topology)).size, 3);
  for (let i = 0; i < DESIGNS.length; i += 1) {
    for (let j = i + 1; j < DESIGNS.length; j += 1) {
      const changed = ['transfer', 'approval', 'memory', 'evaluation']
        .filter(axis => DESIGNS[i].contracts[axis] !== DESIGNS[j].contracts[axis]);
      assert.ok(changed.length >= 2);
    }
  }
  assert.notEqual(REVISED_DESIGN.version, DESIGNS[0].version);
  assert.match(REVISED_DESIGN.review, /대기|상속하지/);
  assert.match(CASE.audit.generation.join(' '), /declined|rejected/i);
  assert.match(CASE.audit.critic.join(' '), /independence.*not.*verified/i);
});

test('run artifacts and exact consumers resolve without latest-output substitution', () => {
  for (const run of Object.values(RUNS)) {
    const ids = nodeIds(run);
    const attempts = new Map(run.attempts.map(attempt => [attempt.id, attempt]));
    assert.equal(attempts.size, run.attempts.length);
    for (const attempt of run.attempts) {
      assert.doesNotMatch(attempt.id, /:/);
      assert.ok(ids.has(attempt.node));
      assert.ok(attempt.stage >= 1 && attempt.try >= 1);
      assert.ok(attempt.events.length > 0);
      [...attempt.inputs, ...attempt.outputs].forEach(id => assert.ok(ARTIFACTS[id], id));
      const expected = attempt.outputs.flatMap(artifact => run.attempts
        .filter(receiver => receiver.inputs.includes(artifact))
        .map(receiver => ({ attempt: receiver.id, artifact })));
      assert.deepEqual(attempt.consumers, expected);
      for (const consumer of attempt.consumers) {
        assert.ok(attempt.outputs.includes(consumer.artifact));
        assert.ok(attempts.get(consumer.attempt).inputs.includes(consumer.artifact));
      }
    }
    assert.equal(new Set(run.attempts.flatMap(a => a.outputs)).size, run.attempts.flatMap(a => a.outputs).length);
  }
  const run = RUNS['run-j1-origin'];
  const writer = run.attempts.filter(a => a.node === 'draft');
  assert.deepEqual(writer.map(a => [a.stage, a.try, a.status]), [[1, 1, 'failed'], [1, 2, 'complete'], [2, 1, 'complete']]);
  assert.deepEqual(writer[0].outputs, []);
  assert.deepEqual(writer[0].consumers, []);
  assert.ok(writer[2].outputs.length >= 2);
  assert.notEqual(writer[1].outputs[0], writer[2].outputs[0]);
});

test('partial alternative, competing explanations and evidence remain scoped and qualified', () => {
  const original = ARTIFACTS[CASE.original];
  assert.equal(original.type, 'pdf');
  assert.ok(original.regions.some(region => region.id === CASE.region));
  assert.equal(ARTIFACTS[CASE.alternative].regions.length, 1);
  assert.equal(ARTIFACTS[CASE.alternative].regions[0].id, 'p1-summary');
  assert.ok(original.regions.length > ARTIFACTS[CASE.alternative].regions.length);
  assert.match(ARTIFACTS[CASE.alternative].label, /부분/);
  for (const difference of CASE.differences) {
    assert.ok(difference.original.length && difference.alternative.length);
    difference.nodes.forEach(id => assert.ok(nodeIds(RUNS['run-j1-origin']).has(id)));
    assert.ok(difference.hypotheses.some(h => h.kind === 'system'));
    assert.ok(difference.hypotheses.some(h => h.kind === 'judgment'));
    for (const hypothesis of difference.hypotheses) {
      for (const field of ['claim', 'support', 'counter', 'unknown', 'probe', 'newEvidence']) {
        assert.ok(hypothesis[field].length > 15, `${hypothesis.id}.${field}`);
      }
    }
  }
  assert.match(CASE.audit.diagnosis.join(' '), /not.*candidate inputs|excluded.*candidate inputs/i);
});

test('two jobs by two rounds preserve losses, outside-region effects and exact pending versions', () => {
  assert.equal(ROUNDS.length, 4);
  assert.equal(new Set(ROUNDS.map(round => round.job)).size, 2);
  for (const job of new Set(ROUNDS.map(round => round.job))) {
    assert.equal(ROUNDS.filter(round => round.job === job).length, 2);
  }
  for (const round of ROUNDS) {
    assert.equal(RUNS[round.baselineRun].job, round.job);
    assert.equal(RUNS[round.candidateRun].job, round.job);
    assert.notEqual(round.baselineRun, 'run-j1-origin');
    assert.equal(RUNS[round.candidateRun].env, round.candidate);
    assert.equal(topology(RUNS[round.baselineRun]), topology(RUNS[round.candidateRun]));
    assert.match(round.limits, /합성|인과.*없/);
    assert.match(round.finalEvidence, /없음|미수집/);
    assert.match(round.approval, /승인 대기|미승인/);
    assert.ok(round.checks.some(check => /부분 밖|후속/.test(check.label)));
    for (const check of round.checks) assert.ok(ARTIFACTS[check.evidence], check.evidence);
  }
  assert.ok(ROUNDS.some(round => /악화|탈락/.test(round.result)));
  assert.ok(ROUNDS.some(round => /혼재/.test(round.result)));
  assert.match(ARTIFACTS['handoff-j1-c2'].body, /setupMinutes/);
  assert.doesNotMatch(ARTIFACTS['handoff-j1-b2'].body, /setupMinutes=/);
  assert.match(ARTIFACTS['slots-j1-c2'].body, /Workshop,15:00,17:00/);
  assert.match(ARTIFACTS['slots-j1-b2'].body, /Workshop,14:00,16:00/);
  assert.match(ARTIFACTS['slots-j2-c2'].body, /Workshop,14:00,16:00/);
});

test('asset renderer emits actual formats, exact PDF text and a separate escaped derivative', () => {
  const rendered = renderAssets();
  assert.ok(rendered.files instanceof Map);
  assert.deepEqual(new Set(ASSET_FILES), new Set(rendered.files.keys()));
  for (const artifact of Object.values(ARTIFACTS)) {
    const bytes = rendered.files.get(artifact.path);
    assert.ok(Buffer.isBuffer(bytes));
    if (artifact.type === 'pdf') {
      const pdf = bytes.toString('latin1');
      assert.ok(pdf.startsWith('%PDF-1.4'));
      assert.ok(pdf.endsWith('%%EOF\n'));
      const offset = Number(pdf.match(/startxref\n(\d+)\n/)[1]);
      assert.equal(pdf.slice(offset, offset + 4), 'xref');
      const xref = pdf.slice(offset).split('\n');
      const count = Number(xref[1].split(' ')[1]);
      for (let object = 1; object < count; object += 1) {
        const objectOffset = Number(xref[object + 2].slice(0, 10));
        assert.equal(pdf.slice(objectOffset, objectOffset + `${object} 0 obj`.length), `${object} 0 obj`);
      }
      const stream = pdf.match(/\/Length (\d+) >>\nstream\n([\s\S]*?)endstream/);
      assert.equal(Buffer.byteLength(stream[2], 'ascii'), Number(stream[1]));
      const decoded = [...pdf.matchAll(/\(((?:\\.|[^\\)])*)\) Tj/g)]
        .map(match => match[1].replace(/\\([\\()])/g, '$1'));
      assert.deepEqual(decoded, artifact.body.split('\n'));
      assert.ok(rendered.files.has(artifact.preview));
      const preview = rendered.files.get(artifact.preview).toString('utf8');
      assert.match(preview, /DERIVATIVE PREVIEW/);
      assert.match(preview, /<svg/);
      const previewLines = [...preview.matchAll(/<text x="54"[^>]*>([\s\S]*?)<\/text>/g)]
        .map(match => match[1].replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&'));
      assert.deepEqual(previewLines, artifact.body.split('\n'));
    } else if (artifact.type === 'svg') assert.match(bytes.toString('utf8'), /<svg/);
    else assert.equal(bytes.toString('utf8'), artifact.body);
  }
  const manifest = JSON.parse(rendered.files.get('assets/manifest.json').toString('utf8'));
  assert.equal(manifest.synthetic, true);
  assert.equal(manifest.entries.length, rendered.files.size - 1);
  assert.ok(manifest.entries.every(entry => /^[0-9a-f]{64}$/.test(entry.sha256)));
  assert.match(pagePreview(['A < B & C', '(one) \\ two']), /A &lt; B &amp; C/);
  assert.match(pdfBytes(['(one) \\ two']).toString('ascii'), /\\\(one\\\)/);
});

test('renderer rejects traversal, extension mismatch, active SVG and non-ASCII PDF sources', () => {
  for (const path of ['../secret.md', '/tmp/file.md', 'assets/../file.md', 'assets/nested/file.md', 'assets/file.html', 'assets/file%2f.md']) {
    assert.throws(() => validateAssetPath(path), /asset path/i);
  }
  assert.throws(() => renderAssets({ x: { ...ARTIFACTS[CASE.original], path: 'assets/wrong.svg' } }), /extension/i);
  assert.throws(() => pdfBytes(['한글']), /printable ASCII/i);
  assert.throws(() => pdfBytes(Array.from({ length: 80 }, () => 'line')), /page capacity/i);
  const badSVG = { id: 'bad', label: 'synthetic', type: 'svg', path: 'assets/bad.svg', body: '<svg><script>alert(1)</script></svg>', regions: [] };
  assert.throws(() => renderAssets({ bad: badSVG }), /active SVG/i);
});
