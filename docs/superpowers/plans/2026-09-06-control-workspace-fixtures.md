# Control Workspace Synthetic Fixture Packet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Supply a coherent, explicitly synthetic public-library room-use scenario for reviewing graph comparison, exact execution history, typed artifacts, partial alternatives, and paired-run inspection without pretending to run DeepTwin.

**Architecture:** This appendix is part of the revised control-workspace UI plan, not a separate engine project. Immutable fixture exports describe the scenario; a deterministic Node-only builder creates actual served Markdown, CSV, SVG and PDF files from those records. Every PDF and its explicitly derivative SVG page preview use the same printable page lines; the original PDF remains separately accessible.

**Tech Stack:** Node.js built-ins (`node:test`, `node:assert/strict`, `node:fs/promises`, `node:path`, `node:url`, `node:crypto`). No package installation, model call, external data, browser automation, uploaded document renderer, or hidden evaluator.

---

## Scope and interface

This document contains future implementation code only. Writing this plan does not create the three implementation files or any asset. All examples, approval states, failures, hypotheses, review observations and audit entries are authored synthetic UI fixtures, not measurements or verified philosophical claims. Neither this scenario nor its alternative is the user's earlier YouTube task, failed POC, personal feedback, or actual work evidence.

Files to create during the separately authorized implementation:

| File | Responsibility |
| --- | --- |
| `control-prototype/fixtures.mjs` | Eight immutable public exports: `ARTIFACTS`, `RUNS`, `DESIGNS`, `CASE`, `ROUNDS`, `REVISED_DESIGN`, `WORK_MODEL`, `LOGS`. |
| `control-prototype/build-assets.mjs` | Validate fixture asset paths; render actual format bytes; build a SHA-256 asset manifest; write only direct generated children of this prototype's `assets/`. |
| `control-prototype/tests/fixtures.test.mjs` | Reference, history, graph diversity, partial coverage, rejected candidate, PDF/preview identity and safe-path tests. |

Coordinates are **node-box top-left positions**, using `140 × 48` boxes in a `900 × 520` graph viewBox. Asset paths are relative to `control-prototype/`, never arbitrary upload paths. `pdf.body` is the exact printable line source, not the PDF bytes; `preview` is a different SVG derivative asset. `regions[].text` preserves each section's full paragraph before page-line wrapping. The renderer must label derivative previews and synthetic records. `ASSET_FILES` is an additional builder export containing the exact relative served paths (including derivative previews and `assets/manifest.json`); importing it does not write files.

General UI labels, contracts, competing explanations, result limits and approval descriptions use Korean work language. The original Markdown/CSV/PDF/SVG fixture contents remain English; the deliberate PDF writer supports printable ASCII only. This is a bounded rendering choice for these neutral test artifacts, not an English-only product policy or a limitation of eventual Korean document support. Raw synthetic audit entries remain English and are shown only in the explicitly identified audit view.

`CASE` is one pre-authored demonstration. Its fixed `original` is `brief-j1-origin`, its fixed partial `alternative` is `alternative-summary`, and its only reviewed region is `p1-summary`. User-entered drafts must have separate state and identifiers and must **not** inherit `CASE.differences`, its hypotheses, rounds or fixed audit results. Selecting a region without actual new content does not create an alternative.

`RUNS` contains the frozen demonstration original plus two independent baseline/candidate comparison pairs for each of two jobs. The baseline in a round is explicitly referenced; the UI must not substitute the original for that baseline. Every produced artifact's actual consumers are derived from exact receiver input references. Planned graph edges are not those actual transfers. The same environment graph can carry different handoff contracts; those changes are recorded in attempt events and artifacts rather than invented topology changes.

## Task 1: Install the complete synthetic fixture packet

**Files:**

- Create: `control-prototype/tests/fixtures.test.mjs`
- Create: `control-prototype/fixtures.mjs`
- Create: `control-prototype/build-assets.mjs`

- [ ] **Step 1: Write the failing reference and format tests.** Create `control-prototype/tests/fixtures.test.mjs` with the complete content below.

```js
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
```

- [ ] **Step 2: Run the tests and confirm the first missing implementation.**

Run from the UI worktree: `node --test control-prototype/tests/fixtures.test.mjs`

Expected: non-zero exit with `ERR_MODULE_NOT_FOUND` for `control-prototype/fixtures.mjs`. A different failure must be resolved before continuing.

- [ ] **Step 3: Create the complete immutable fixture module.** Create `control-prototype/fixtures.mjs` with this content.

```js
const freeze = value => {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
};
const N = (id, label, kind, x, y) => ({ id, label, kind, x, y });
const E = (from, to, kind = 'task') => ({ from, to, kind });
const mark = label => `${label} · synthetic UI fixture`;
const artifactRecords = {};
function addArtifact(id, label, type, body, regions, preview) {
  const extension = { text: 'md', csv: 'csv', svg: 'svg', pdf: 'pdf' }[type];
  const artifact = { id, label: mark(label), type, path: `assets/${id}.${extension}`, body,
    regions: regions ?? [{ id: 'whole', label: '산출물 전체', text: body }] };
  if (preview) artifact.preview = preview;
  artifactRecords[id] = artifact;
  return id;
}
function wrap(text, width = 76) {
  const lines = [];
  let line = '';
  for (const word of text.split(/\s+/)) {
    if (word.length > width) throw new Error('Fixture word exceeds page width');
    if (line && line.length + word.length + 1 > width) { lines.push(line); line = word; }
    else line += `${line ? ' ' : ''}${word}`;
  }
  if (line) lines.push(line);
  return lines;
}
function addPDF(id, title, summary, schedule, notes) {
  const regions = [
    { id: 'p1-summary', label: '1쪽: 요약 문단', text: summary },
    { id: 'p1-schedule', label: '1쪽: 공간별 일정', text: schedule },
    { id: 'p1-notes', label: '1쪽: 예약·공개 유의사항', text: notes },
  ];
  const lines = ['SYNTHETIC UI FIXTURE - NOT AN ACTUAL LIBRARY PLAN', title, '',
    'SUMMARY', ...wrap(summary), '', 'ROOM SCHEDULE', ...wrap(schedule), '',
    'BOOKING AND PUBLICATION NOTES', ...wrap(notes), '',
    'No reservation, public post, approval or model execution has occurred.'];
  const displayTitle = title.replace('Tuesday', '화요일').replace('Thursday', '목요일')
    .replace('room-use briefing - draft 1', '공간 이용 안내문 · 1차').replace('room-use briefing - draft 2', '공간 이용 안내문 · 2차');
  return addArtifact(id, displayTitle, 'pdf', lines.join('\n'), regions, `assets/${id}-page-1.svg`);
}
const escapeXML = value => String(value).replace(/[<>&"']/g, character => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' }[character]));
function timeline(rows, caption) {
  const minute = time => Number(time.slice(0, 2)) * 60 + Number(time.slice(3));
  const bars = rows.map((row, index) => {
    const start = 190 + (minute(row.start) - 14 * 60) * 3;
    const width = (minute(row.end) - minute(row.start)) * 3;
    const y = 125 + index * 85;
    return `<g><text x="28" y="${y + 24}" fill="#173b3f">${escapeXML(row.room)} (${row.capacity})</text><rect x="${start}" y="${y}" width="${width}" height="36" rx="5" fill="#167880"/><text x="${start + 9}" y="${y + 24}" fill="white">${row.start}-${row.end}</text></g>`;
  }).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="820" height="410" viewBox="0 0 820 410" role="img"><title>${escapeXML(caption)}</title><rect width="820" height="410" fill="#f5faf9"/><g font-family="Arial,sans-serif" font-size="16"><text x="28" y="35" fill="#173b3f">SYNTHETIC UI FIXTURE - ROOM WINDOWS</text><text x="28" y="65" fill="#456366">${escapeXML(caption)}</text>${[14, 15, 16, 17].map(hour => `<text x="${190 + (hour - 14) * 180}" y="103" fill="#456366">${hour}:00</text>`).join('')}${bars}<text x="28" y="395" fill="#456366">Intervals are displayed records, not live bookings or evaluated evidence.</text></g></svg>`;
}

const pipelineNodes = [N('source', '입력 자료', 'resource', 90, 75), N('extract', '근거 확인', 'agent', 255, 75),
  N('slots', '이용 시간 구성', 'agent', 420, 75), N('draft', '안내문 작성', 'agent', 585, 200),
  N('review', '안내문 검토', 'agent', 585, 355), N('approve', '공개 승인', 'control', 750, 355),
  N('files', '파일·버전 보관', 'resource', 255, 445), N('model', '모델 연결', 'resource', 420, 445),
  N('observe', '실행 기록·검사', 'resource', 750, 75)];
const pipelineEdges = [E('source', 'extract'), E('extract', 'slots'), E('slots', 'draft'), E('draft', 'review'),
  E('review', 'draft', 'revisit'), E('review', 'approve', 'control'), E('files', 'extract', 'memory'),
  E('files', 'draft', 'memory'), E('model', 'extract', 'tool'), E('model', 'draft', 'tool'),
  E('model', 'review', 'tool'), E('draft', 'observe', 'telemetry'), E('review', 'observe', 'telemetry')];
const designs = [
  { id: 'pipeline', label: '단계별 근거 전달', version: 'design-a-v1', nodes: pipelineNodes, edges: pipelineEdges,
    focus: { transfer: ['extract', 'slots', 'draft'], approval: ['review', 'approve'], memory: ['files', 'extract', 'draft'], evaluation: ['review', 'observe'] },
    contracts: {
      transfer: '예정된 전달: 근거 확인 → 정리된 제약 → 이용 시간 CSV → 완결된 PDF·문서 → 별도 안내문 검토로 이어집니다. 필수 항목이 빠지면 해당 전달을 멈춥니다.',
      approval: '예정된 권한: 사람이 검토된 최종 안내문의 공개를 승인합니다. 앞 단계 에이전트는 공개·예약 권한이 없으며 해결되지 않은 결함을 그대로 남깁니다.',
      memory: '예정된 기억: 단계마다 원 파일과 버전을 보존합니다. 후속 역할은 공용 편집판의 최신값 대신 명시적으로 전달받은 파일 버전을 읽습니다.',
      evaluation: '예정된 평가: 이용 시간 전달 시 출처·시간 제약을 검사하고, 공개 결정 전에는 완결된 안내문을 별도로 검토합니다.',
    }, review: '합성 설계 검토: 단계별 책임을 읽기 쉽지만 전달에서 빠진 맥락이 후속 산출물로 퍼질 수 있습니다. 실제 실행하거나 점수를 측정한 후보가 아닙니다.' },
  { id: 'supervised', label: '감독자와 작성 전 확인', version: 'design-b-v1',
    nodes: [N('source', '입력 자료', 'resource', 90, 75), N('supervise', '업무 감독', 'control', 255, 75),
      N('extract', '근거 확인', 'agent', 420, 75), N('slots', '이용 시간 구성', 'agent', 420, 230),
      N('approve', '근거 충돌 확인', 'control', 585, 230), N('draft', '안내문 작성', 'agent', 750, 230),
      N('files', '역할별 자료 범위', 'resource', 255, 445), N('model', '모델 연결', 'resource', 420, 445),
      N('observe', '판단 기록·검사', 'resource', 750, 75)],
    edges: [E('source', 'supervise'), E('supervise', 'extract', 'control'), E('supervise', 'slots', 'control'),
      E('extract', 'approve'), E('slots', 'approve'), E('approve', 'draft', 'control'), E('draft', 'supervise', 'revisit'),
      E('files', 'extract', 'memory'), E('files', 'slots', 'memory'), E('model', 'draft', 'tool'),
      E('model', 'extract', 'tool'), E('approve', 'observe', 'telemetry')],
    focus: { transfer: ['supervise', 'extract', 'slots', 'approve', 'draft'], approval: ['supervise', 'approve'],
      memory: ['files', 'extract', 'slots'], evaluation: ['approve', 'observe'] },
    contracts: {
      transfer: '예정된 전달: 감독자가 근거 확인과 시간 구성 역할에 범위를 정해 병렬로 맡깁니다. 두 결과의 버전을 작성 전 확인 지점에서 대조합니다.',
      approval: '예정된 권한: 수용 인원이나 시간대의 충돌이 미해결이면 공개 가능한 안내문을 쓰기 전에 사람이 판단합니다. 감독자는 업무 배분만 담당합니다.',
      memory: '예정된 기억: 역할별 읽기 범위와 감독자의 충돌 해결 기록을 분리합니다. 근거 확인 역할끼리 상대 결과나 최종 승인 권한을 덮어쓸 수 없습니다.',
      evaluation: '예정된 평가: 작성 전 역할 사이의 충돌을 확인한 뒤 명시적 규칙으로 산출물을 검사합니다. 공개 권한을 주는 행위는 이 검사와 별개입니다.',
    }, review: '합성 설계 검토: 문구가 만들어지기 전에 불확실성을 다룰 수 있지만 감독자와 앞선 확인 절차가 병목이 될 수 있습니다. 지연·품질을 실측한 결과는 없습니다.' },
  { id: 'shared', label: '공유 근거 작업공간', version: 'design-c-v1',
    nodes: [N('source', '입력 자료', 'resource', 90, 75), N('board', '공유 근거판', 'resource', 255, 230),
      N('extract', '근거 확인', 'agent', 420, 75), N('slots', '이용 시간 구성', 'agent', 420, 230),
      N('draft', '안내문 작성', 'agent', 585, 75), N('review', '충돌 검토', 'agent', 585, 355),
      N('approve', '공개 승인', 'control', 750, 355), N('model', '모델 연결', 'resource', 420, 445),
      N('observe', '버전 검사·기록', 'resource', 750, 75)],
    edges: [E('source', 'board'), E('board', 'extract', 'memory'), E('extract', 'board', 'memory'),
      E('board', 'slots', 'memory'), E('slots', 'board', 'memory'), E('board', 'draft', 'memory'),
      E('draft', 'board', 'memory'), E('board', 'review'), E('review', 'board', 'revisit'), E('review', 'approve', 'control'),
      E('model', 'extract', 'tool'), E('model', 'draft', 'tool'), E('board', 'observe', 'telemetry')],
    focus: { transfer: ['board', 'extract', 'slots', 'draft'], approval: ['review', 'approve'],
      memory: ['board', 'extract', 'slots', 'draft'], evaluation: ['review', 'observe'] },
    contracts: {
      transfer: '예정된 전달: 공간 정보·가능한 시간대·문서 초안을 형식과 버전이 있는 공유 근거판에 올립니다. 읽는 역할은 실제 소비한 출처 버전을 기록해야 합니다.',
      approval: '예정된 권한: 충돌 검토자가 버전을 정리하고 사람이 최종 공개를 승인하기 전에는 각 역할의 결과를 잠정 상태로 둡니다. 에이전트가 스스로 승인하지 않습니다.',
      memory: '예정된 기억: 단계별 파일이나 감독자 전용 상태 대신 버전 있는 근거와 충돌·변경 이력을 함께 보관하는 공유 작업공간을 사용합니다.',
      evaluation: '예정된 평가: 협업 도중 오래된 자료 읽기·상충하는 시간대·출처를 계속 확인하고 최종 공개 전에는 완결된 안내문을 다시 검사합니다.',
    }, review: '합성 설계 검토: 반복 작업과 맥락 공유가 유연하지만 동시 수정 충돌과 오래된 자료 사용을 통제해야 합니다. 최적 설계나 실제 평가 결과라고 주장하지 않습니다.' },
];
export const DESIGNS = freeze(designs);
export const REVISED_DESIGN = freeze({ ...designs[0], id: 'pipeline-gate', label: '단계별 전달 + 근거 확인', version: 'design-a-b-v2',
  nodes: [...pipelineNodes, N('evidence-gate', '근거 충돌 확인', 'control', 585, 75)],
  edges: [...pipelineEdges.filter(edge => !(edge.from === 'slots' && edge.to === 'draft')),
    E('slots', 'evidence-gate'), E('evidence-gate', 'draft', 'control')],
  focus: { ...designs[0].focus, transfer: ['extract', 'slots', 'evidence-gate', 'draft'], approval: ['evidence-gate', 'review', 'approve'] },
  contracts: { ...designs[0].contracts,
    transfer: '수정된 전달 계획: 삽입한 확인 지점이 시간대·충돌 항목을 가진 새 자료를 받습니다. 소비 버전과 누락 항목 처리가 잘 결합되는지 다시 검토해야 합니다.',
    approval: '수정된 권한 계획: 앞선 확인 지점은 근거 충돌을 해결하고 최종 공개는 별도의 사람 권한으로 남깁니다. 승인 책임의 중복·충돌을 다시 검토해야 합니다.',
  }, review: '합성 병합 예시: design-a-b-v2의 결합 검토 대기 상태입니다. 원 후보의 합격·점수·승인을 상속하지 않습니다. 실제 구성이나 실행 권한은 주어지지 않았습니다.' });

export const WORK_MODEL = freeze({
  purpose: '도서관 담당자가 가능한 2시간 이용안을 비교할 수 있도록 출처가 있는 안내문을 만듭니다. 시작 시간이 다른 공간을 동시에 이용 가능한 것으로 혼동하지 않도록 합니다.',
  done: '완결된 안내문·공간별 이용 시간 CSV·시각 일정을 통해 수용 인원, 준비 시간과 공개 전 확인사항을 읽을 수 있어야 합니다. 사람의 실제 공개 승인은 이 화면 예시와 별개입니다.',
  source: '인터페이스 검토를 위해 만든 전부 합성(synthetic)인 도서관 공간 자료입니다. 규칙과 이용 기록은 실제 장소·사람·예약을 가리키지 않습니다.',
  unknown: '실제 개관 시간·접근성 규칙·근무 인원·실시간 예약은 확인하지 않았습니다. 외부 시스템은 연결되어 있지 않습니다.',
});
addArtifact('source-policy', '공간 이용 규칙', 'text', `# Synthetic room-use policy\n\nAll offered sessions must have a continuous two-hour room window. A room becomes available only after the previous booking ends and its setup buffer has elapsed. Setup time is not visitor time. Capacity applies to that room, not to every interval mentioned in a brief.\n\nThe quiet room supports 8 visitors, the workshop 20, and the hall 40. A total capacity may be added only for the same offered start and end times. A coordinator must approve publication; this packet neither reserves a room nor grants publication permission.\n\nThe planner must preserve source date, previous booking end, setup minutes, closing time, candidate start and candidate end in every scheduling handoff. If any required value is missing, the next stage must show an unresolved constraint rather than guess.\n`);
const jobs = {
  j1: { label: '화요일 공간 이용', day: 'Tuesday', workshopPrevious: '14:30', workshopSetup: 30, workshopCorrect: '15:00',
    source: 'room,previous_end,setup_minutes,closes,capacity\nQuiet,14:00,0,17:00,8\nWorkshop,14:30,30,17:00,20\nHall,14:00,0,17:00,40\n',
    baseline: 'Tuesday afternoon offers three rooms for a shared 14:00-16:00 activity window. The quiet room holds 8 visitors, the workshop 20, and the hall 40, allowing us to present a combined capacity of 68. Publish these options together once the coordinator has reviewed the briefing.',
    c1: 'Offer the quiet room and hall from 14:00 to 16:00, with a combined capacity of 48. Offer the workshop separately from 15:00 to 17:00. The workshop should not appear in the simultaneous 14:00 capacity total; publication still requires the coordinator to release the briefing.',
    c2: 'The 14:00-16:00 group comprises the quiet room and hall, providing 48 places in total. The workshop first becomes ready at 15:00 after its recorded booking and 30-minute setup period, so its 20 places belong to a separate 15:00-17:00 option. These are proposed windows, not confirmed reservations.',
  },
  j2: { label: '목요일 공간 이용', day: 'Thursday', workshopPrevious: '13:30', workshopSetup: 30, workshopCorrect: '14:00',
    source: 'room,previous_end,setup_minutes,closes,capacity\nQuiet,14:00,0,17:00,8\nWorkshop,13:30,30,17:00,20\nHall,14:00,0,16:00,40\n',
    baseline: 'Thursday offers the quiet room, workshop and hall together from 14:00 to 16:00, providing a combined capacity of 68. The workshop setup finishes before that window begins. The hall closes at 16:00, so later alternatives must not silently extend its session. Publication remains subject to coordinator release.',
    c1: 'Offer the quiet room and hall together from 14:00 to 16:00, giving a combined capacity of 48. Keep the workshop in a separate 15:00-17:00 option with 20 places. This draft applies a blanket later-workshop rule, even though Thursday source records show that the workshop is already ready at 14:00.',
    c2: 'All three rooms have a feasible common 14:00-16:00 window on Thursday, for a combined capacity of 68. The workshop booking ends at 13:30 and its 30-minute setup finishes by 14:00. The hall closes at 16:00; the complete two-hour session fits exactly and must not be extended without a new source record.',
  },
};
for (const [id, job] of Object.entries(jobs)) addArtifact(`source-${id}`, `${job.label} 현황 원자료`, 'csv', job.source,
  job.source.trim().split('\n').slice(1).map((line, index) => ({ id: `row-${index + 1}`, label: `원자료 ${index + 1}행`, text: line })));

const runs = {};
function makeRun(jobId, suffix, mode, minute) {
  const job = jobs[jobId];
  const roomLabel = room => ({ Quiet: '조용한 공간', Workshop: '작업실', Hall: '다목적실' }[room]);
  const key = `${jobId}-${suffix}`;
  const runId = `run-${key}`;
  const finalId = `brief-${key}`;
  const stageOneId = `brief-${key}-v1`;
  const summary = job[mode];
  const workshopStart = mode === 'c2' ? job.workshopCorrect : '14:00';
  const workshopEnd = workshopStart === '15:00' ? '17:00' : '16:00';
  const rows = [{ room: 'Quiet', start: '14:00', end: '16:00', capacity: 8 },
    { room: 'Workshop', start: workshopStart, end: workshopEnd, capacity: 20 },
    { room: 'Hall', start: '14:00', end: '16:00', capacity: 40 }];
  const schedule = rows.map(row => `${row.room}: ${row.start}-${row.end}, ${row.capacity} places.`).join(' ');
  const notes = 'Retain the dated occupancy source and room-use policy with this brief. Capacity figures describe people, not bookings. A release decision must inspect the complete schedule and unresolved constraints; viewing this fixture cannot publish, reserve, or approve anything.';
  const handoff = mode === 'c2'
    ? `# Synthetic source-derived handoff v2\n\nJob=${jobId}; policy=source-policy; source=source-${jobId}.\nWorkshop previousEnd=${job.workshopPrevious}; setupMinutes=${job.workshopSetup}; derivedAvailable=${job.workshopCorrect}; closes=17:00; capacity=20.\nQuiet previousEnd=14:00; setupMinutes=0; closes=17:00; capacity=8. Hall previousEnd=14:00; setupMinutes=0; closes=${jobId === 'j2' ? '16:00' : '17:00'}; capacity=40.\nThe slot planner must derive a continuous two-hour interval from these source fields. It cannot take the diagnostic alternative or interpretive audit as an operational input.\n`
    : `# Synthetic capacity-only handoff v1\n\nJob=${jobId}; source=source-${jobId}; requestedWindow=14:00-16:00.\nQuiet capacity=8; Workshop capacity=20; Hall capacity=40.\nThe recorded payload does not carry previous-booking end, setup duration or closing-time fields. This omission is observable in the fixture; causal attribution is not established by the display.\n`;
  addArtifact(`handoff-${key}`, `${job.label} 전달 자료 ${suffix}`, 'text', handoff);
  const csv = `room,start,end,capacity\n${rows.map(row => `${row.room},${row.start},${row.end},${row.capacity}`).join('\n')}\n`;
  addArtifact(`slots-${key}`, `${job.label} 시간표 ${suffix}`, 'csv', csv,
    rows.map((row, index) => ({ id: `row-${index + 1}`, label: `${roomLabel(row.room)} 이용 시간`, text: `${row.room},${row.start},${row.end},${row.capacity}` })));
  addArtifact(`diagram-${key}`, `${job.label} 시각 일정 ${suffix}`, 'svg', timeline(rows, `${job.day}: ${mode} displayed schedule`),
    rows.map((row, index) => ({ id: `row-${index + 1}`, label: `${roomLabel(row.room)} 시각 영역`, text: `${row.room} ${row.start}-${row.end}, capacity ${row.capacity}` })));
  addPDF(stageOneId, `${job.day} room-use briefing - draft 1`, `Draft awaiting a full brief check. ${summary}`, schedule, notes);
  addArtifact(`review-${key}-v1`, `${job.label} 1차 문서 검토 ${suffix}`, 'text', `# Synthetic draft review\n\nThe submitted PDF is ${stageOneId}, not the latest PDF in another attempt. Preserve a complete room schedule and distinguish a release decision from the mere display of proposed windows. Add an explicit statement that this packet creates no booking.\n\nThis first review records wording and publication-scope observations only. It does not establish that the setup constraint has been transmitted or that all source calculations are correct. A later complete-brief review remains a distinct stage occurrence.\n`);
  addPDF(finalId, `${job.day} room-use briefing - draft 2`, summary, schedule, notes);
  addArtifact(`brief-note-${key}`, `${job.label} 동봉 안내문 ${suffix}`, 'text', `# Synthetic briefing companion\n\n${summary}\n\n## Complete proposed schedule\n\n${schedule}\n\n## Publication boundary\n\n${notes}\n`);
  const assessment = mode === 'c2'
    ? 'The displayed schedule carries source-derived ready times into both the paragraph and the slot table. The downstream visual schedule reflects those same intervals. This synthetic authored agreement is not measured improvement or unseen transfer evidence.'
    : mode === 'c1'
      ? 'The summary applies a later-workshop rule, while the slot CSV and diagram still use 14:00-16:00. Tuesday wording can appear better while downstream disagreement remains. On Thursday the blanket rule suppresses a valid shared window. This candidate is not suitable for release.'
      : jobId === 'j1'
        ? 'The summary, slot CSV and diagram agree on 14:00, but the workshop source booking ends at 14:30 and requires 30 minutes of setup. Agreement between artifacts therefore does not establish correctness. The demonstration records an unresolved release-blocking inconsistency.'
        : 'The Thursday 14:00-16:00 interval is consistent with the displayed source values. The capacity-only handoff still omits safety-relevant fields, so success on this one fixture is not a general correctness claim.';
  addArtifact(`assessment-${key}`, `${job.label} 완결 산출물 검토 ${suffix}`, 'text', `# Synthetic complete-brief check\n\n${assessment}\n\nSource references: source-policy, source-${jobId}. Checked artifacts: ${finalId}, slots-${key}, diagram-${key}, brief-note-${key}. No evaluator, philosophical source review, external reservation or model has run.\n`);
  const attempt = (name, node, stage, attemptNumber, status, inputs, outputs, events) => ({
    id: `${runId}-${name}`, node, stage, try: attemptNumber, status, inputs, outputs, consumers: [], events,
  });
  const attempts = [
    attempt('extract-1', 'extract', 1, 1, 'complete', [`source-${jobId}`, 'source-policy'], [`handoff-${key}`],
      [mark('기록된 버전의 원자료를 읽은 예시입니다.'), mode === 'c2' ? '전달 규약 v2는 이전 예약 종료·준비 시간·종료 시각을 포함합니다. 진단용 자기 대안과 해석 기록은 실행 입력에서 제외됩니다.' : '전달 규약 v1에는 시간 의존성 항목이 없습니다. 이 누락 상태를 그대로 보존합니다.']),
    attempt('slots-1', 'slots', 1, 1, 'complete', [`handoff-${key}`], [`slots-${key}`, `diagram-${key}`],
      [mark(mode === 'c2' ? '원자료 항목에서 이용 가능 시간을 도출한 상태를 표시합니다.' : '불완전한 전달 자료의 요청 시간대를 복사한 상태입니다. 실제 계산을 수행한 기록이 아닙니다.')]),
  ];
  if (mode === 'baseline') attempts.push(attempt('draft-1-failed', 'draft', 1, 1, 'failed', [`slots-${key}`, 'source-policy'], [],
    [mark('파일 저장 전에 시간이 초과된 예시입니다. 산출물도 후속 수신자도 없습니다.')]));
  attempts.push(
    attempt('draft-1-complete', 'draft', 1, mode === 'baseline' ? 2 : 1, 'complete', [`slots-${key}`, 'source-policy'], [stageOneId],
      [mark('첫 수행의 PDF를 고유 버전으로 보관한 예시입니다.'), mode === 'c1' ? '후보 c1은 작성 지시만 바꿔 모든 작업실을 늦은 별도 시간대로 나눕니다. 이용 시간 전달의 누락 항목은 복원하지 않습니다.' : '실행 입력에 전문가 대안 원문은 포함되어 있지 않습니다.']),
    attempt('review-1', 'review', 1, 1, 'complete', [stageOneId, `source-${jobId}`], [`review-${key}-v1`], [mark('이 검토는 1차 초안을 받습니다. 이후 재방문 결과를 소급하여 받지 않습니다.')]),
    attempt('draft-2', 'draft', 2, 1, 'complete', [stageOneId, `review-${key}-v1`, `slots-${key}`], [finalId, `brief-note-${key}`],
      [mark('검토 뒤 새로 수행한 단계입니다. 실패한 저장의 재시도와 구별하며 PDF와 동봉 문서를 함께 산출합니다.')]),
    attempt('review-2', 'review', 2, 1, 'complete', [finalId, `brief-note-${key}`, `slots-${key}`, `diagram-${key}`, `source-${jobId}`, 'source-policy'], [`assessment-${key}`],
      [mark('완결 산출물의 별도 검토에서 후속 일정과 공개 제약을 확인한 예시입니다.')]),
    attempt('release-1', 'approve', 1, 1, 'waiting', [finalId, `assessment-${key}`], [],
      [mark('사람의 공개 승인은 기록되지 않았습니다. 이 예시 열람은 승인이나 외부 작업 실행이 아닙니다.')]),
  );
  for (const producer of attempts) producer.consumers = producer.outputs.flatMap(artifact => attempts
    .filter(receiver => receiver.inputs.includes(artifact)).map(receiver => ({ attempt: receiver.id, artifact })));
  runs[runId] = { id: runId, job: jobId, env: mode === 'baseline' ? 'env-demo-0.2' : `env-demo-0.3-${mode}`,
    observedAt: `2026-09-06T09:${String(minute).padStart(2, '0')}:00Z (synthetic observation)`,
    nodes: pipelineNodes, edges: pipelineEdges, attempts };
}
makeRun('j1', 'origin', 'baseline', 0);
makeRun('j2', 'origin', 'baseline', 1);
makeRun('j1', 'b1', 'baseline', 10);
makeRun('j1', 'c1', 'c1', 11);
makeRun('j2', 'b1', 'baseline', 12);
makeRun('j2', 'c1', 'c1', 13);
makeRun('j1', 'b2', 'baseline', 20);
makeRun('j1', 'c2', 'c2', 21);
makeRun('j2', 'b2', 'baseline', 22);
makeRun('j2', 'c2', 'c2', 23);

const alternative = 'Offer the quiet room and hall from 14:00 to 16:00, with a combined capacity of 48. Offer the workshop as a separate 15:00-17:00 option only after its setup window. Do not advertise three simultaneous rooms.';
addArtifact('alternative-summary', '자기 버전 예시 · 요약 부분만', 'text', alternative,
  [{ id: 'p1-summary', label: '원본의 요약 문단만 제공한 자기 버전', text: alternative }]);
export const CASE = freeze({ id: 'case-summary-window', original: 'brief-j1-origin', alternative: 'alternative-summary', region: 'p1-summary',
  differences: [
    { id: 'd-window', label: '동시 이용 시간과 별도로 가능한 시간의 구별', original: jobs.j1.baseline, alternative,
      nodes: ['extract', 'slots', 'draft', 'review'], hypotheses: [
        { id: 'h-transfer', kind: 'system', claim: '기록된 전달에서 시간 의존성 항목이 빠져 작성자가 성립하지 않는 공통 시간대를 받았을 가능성이 있습니다.',
          support: '원 전달에는 수용 인원과 요청 시간대만 있고 이전 예약 종료·준비 시간은 없습니다. 그 이용 시간 CSV는 작업실을 14시에 시작합니다.',
          counter: '작성자는 전체 이용 규칙도 받았습니다. 전달 항목의 누락만으로 최종 문구의 원인이 확정되지는 않습니다.',
          unknown: '이 항목만 복원했을 때 해당 시간 계산과 최종 안내문이 함께 바뀌는지 실제 개입으로 확인한 적이 없습니다.',
          probe: '후속 통제 시험에서는 모델을 바꾸거나 자기 대안 문구를 복사하지 않은 채 원자료의 시간 의존성 항목만 복원해 봅니다.',
          newEvidence: '미수집입니다. 표시한 회차는 작성된 합성 예시이며 이 설명을 뒷받침하는 실제 실험 증거가 아닙니다.' },
        { id: 'h-grouping', kind: 'judgment', claim: '자기 대안은 늦은 시간 자체를 선호하기보다 동시 이용 인원과 각각 가능한 이용안을 구별한 것일 수 있습니다.',
          support: '14시 동시 이용 인원에서만 작업실을 제외합니다. 준비 시간이 지난 뒤에는 작업실을 별도 이용안으로 여전히 제안합니다.',
          counter: '일회성 표현 수정이나 잘못된 대안도 일부 양상을 만들 수 있습니다. 이 문단만으로 재사용 가능한 판단 규칙이 확정되지는 않습니다.',
          unknown: '모든 공간이 동시에 준비된 경우에도 같은 구분 원칙을 쓰는지 확인할 독립적인 새 업무 응답이 없습니다.',
          probe: '작업실이 더 일찍 준비되는 새 사례를 출처와 함께 제시하고 실제 자기 대안이나 선택을 받습니다. 개인 성향을 분류하는 설문은 요구하지 않습니다.',
          newEvidence: '미수집입니다. 목요일 비교는 합성 UI 예시이지 이 사용자의 응답이나 검증된 해석 근거가 아닙니다.' },
      ] },
  ],
  audit: {
    generation: [
      'SYNTHETIC GEN-01: hypothetical micro-unit source-dependency@fixture-1 produced the pipeline candidate. This is not a verified philosopher source.',
      'SYNTHETIC GEN-02: hypothetical uncertainty-gate@fixture-1 produced the supervisor candidate; work-contract evidence remains separate from lens interpretation.',
      'SYNTHETIC GEN-03: hypothetical source-dependency@fixture-1 + shared-evidence@fixture-1 hybrid produced the shared workspace. Internal hybrid generation is not user structural merging.',
      'SYNTHETIC GEN-04 declined: a four-writer candidate changed role count without two genuine structural differences. Rejection is retained; no numeric score is invented.',
      'SYNTHETIC MERGE-01: user-structural-merge illustration creates design-a-b-v2; composition checks are pending and candidate approvals are not inherited.',
    ],
    critic: [
      'SYNTHETIC CRIT-01: separately authored criterion-based trace for each candidate records handoff gaps, authority conflicts, stale reads and abstentions; no model was called.',
      'SYNTHETIC CRIT-02: blindness and information separation are design intentions. Judgment-error independence has not been verified by these fixtures.',
      'SYNTHETIC CRIT-03: invalid diversity is declined rather than hidden by an average score. Source fidelity, task fitness and empirical usefulness are distinct unverified checks.',
    ],
    diagnosis: [
      'SYNTHETIC DIAG-01: fixed example alternative covers only p1-summary; unchanged schedule and notes are neither authored nor approved by the example contributor.',
      'SYNTHETIC DIAG-02: hypothetical contrast question and prediction are separate from new work evidence, which is absent. Interpretive H_phi/S_phi records are not candidate inputs.',
      'SYNTHETIC DIAG-03: system-normal, one-off exception, alternative error, unknown cause and no generalizable knowledge remain possible; no personality profile is produced.',
      'SYNTHETIC DIAG-04: new drafts entered in the UI have no generated hypotheses or evaluation. They must not be attached to this pre-authored demonstration result.',
    ],
  },
});
function round(job, number) {
  const key = `${job}-c${number}`;
  const improved = number === 2;
  return { id: `round-${job}-${number}`, job, candidate: `env-demo-0.3-c${number}`,
    baselineRun: `run-${job}-b${number}`, candidateRun: `run-${key}`,
    result: improved ? '합성 예시: 연결된 결과가 일치함 · 실제 개선 검증 아님' : job === 'j1' ? '합성 예시: 변화가 혼재함 · 후속 불일치 남음' : '합성 예시: 다른 업무에서 악화 · c1 공개 후보 탈락',
    checks: [
      { label: '선택한 요약 부분', result: improved ? '원자료를 반영한 문구의 예시' : '문구만 바뀐 예시', evidence: `brief-${key}` },
      { label: '부분 밖 영향 · 후속 이용 시간표', result: improved ? '일정이 함께 맞춰진 예시' : '전달 시간표가 그대로여서 문구와 불일치함', evidence: `slots-${key}` },
      { label: '부분 밖 영향 · 시각 일정', result: improved ? '원자료에서 도출한 이용 시간을 표시함' : '이전의 작업실 14시 일정이 남아 있음', evidence: `diagram-${key}` },
      { label: '완결 산출물 검토와 남은 한계', result: improved ? '실제 검증 통과를 주장하지 않음' : '공개를 막아야 할 후보의 한계', evidence: `assessment-${key}` },
    ],
    limits: '합성 비교 기록입니다. 입력·규칙 버전은 같게 구성했지만 실제 모델·실행기·외부 상태·소요 시간·확률적 반복·인과 추정은 없습니다. 부분 증거가 후속 영향의 범위를 제한하지 않습니다.',
    finalEvidence: '별도의 봉인·미관측·후속 수집 근거 없음. 이 사례는 조정 과정의 비교를 설명하는 예시이며 최종 검증 자료로 셀 수 없습니다.',
    approval: `정확한 env-demo-0.3-c${number}에 대한 사람의 승인 대기 상태입니다. 현재 환경은 env-demo-0.2이며 실제 적용이나 되돌리기는 수행하지 않았습니다.`,
  };
}
export const ROUNDS = freeze([round('j1', 1), round('j2', 1), round('j1', 2), round('j2', 2)]);
export const RUNS = freeze(runs);
export const ARTIFACTS = freeze(artifactRecords);
export const LOGS = freeze([
  { id: 'log-start', label: '최초 사용 기록의 합성 예시입니다. 계정이나 외부 도구는 연결되지 않았습니다.', source: 'synthetic-fixture' },
  { id: 'log-work', label: '업무 모델과 source-policy/source-j1/source-j2의 합성 자료 버전을 등록한 예시입니다.', source: 'synthetic-fixture' },
  { id: 'log-design', label: 'GEN-01–04의 생성 경로·탈락 설계·별도 검토의 한계를 보존합니다.', source: 'synthetic-fixture' },
  { id: 'log-merge', label: 'MERGE-01의 design-a-b-v2는 표시용 병합 기록이며 결합 검토 대기 상태입니다.', source: 'synthetic-fixture' },
  { id: 'log-original', label: 'run-j1-origin과 원 산출물 버전은 회차별 비교 기준 실행과 별도로 보존합니다.', source: 'synthetic-fixture' },
  { id: 'log-alternative', label: 'case-summary-window는 고정된 부분 자기 대안을 p1-summary에만 연결합니다.', source: 'synthetic-fixture' },
  { id: 'log-inquiry', label: 'DIAG-01–04는 경쟁 설명과 새 근거의 부재를 보여 주는 예시이지 엔진 실행 결과가 아닙니다.', source: 'synthetic-fixture' },
  { id: 'log-rounds', label: '네 비교 회차에 혼재·악화 사례, 이후 일치 예시와 선택한 부분 밖 산출물을 모두 남깁니다.', source: 'synthetic-fixture' },
  { id: 'log-approval', label: '정확한 후보의 승인·운영 적용은 기록되지 않았습니다. 예시를 보는 행위는 이를 승인하지 않습니다.', source: 'synthetic-fixture' },
  { id: 'log-export', label: '추출 범위의 합성 예시입니다. 실제 추출·전송은 수행하지 않았으며 인증정보도 포함하지 않습니다.', source: 'synthetic-fixture' },
]);
```

- [ ] **Step 4: Run the tests and confirm the missing asset builder.**

Run: `node --test control-prototype/tests/fixtures.test.mjs`

Expected: non-zero exit with `ERR_MODULE_NOT_FOUND` for `control-prototype/build-assets.mjs`. This step must not generate files or claim any fixture tests passed.

- [ ] **Step 5: Create the deterministic asset builder.** Create `control-prototype/build-assets.mjs` with the following complete content. `renderAssets()` is pure in-memory rendering. `buildAssets()` is the only file writer and has a fixed prototype-local destination. It never renders user uploads.

```js
import { mkdir, lstat, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { ARTIFACTS } from './fixtures.mjs';

const prototypeRoot = path.dirname(fileURLToPath(import.meta.url));
const extensions = { text: 'md', csv: 'csv', svg: 'svg', pdf: 'pdf' };
export const ASSET_FILES = Object.freeze([...Object.values(ARTIFACTS)
  .flatMap(artifact => [artifact.path, ...(artifact.preview ? [artifact.preview] : [])]), 'assets/manifest.json']);
const xml = value => String(value).replace(/[<>&"']/g, character => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' }[character]));
export function validateAssetPath(relative) {
  if (typeof relative !== 'string' || !/^assets\/[a-z0-9][a-z0-9-]*\.(?:md|csv|svg|pdf|json)$/.test(relative)) {
    throw new Error(`Invalid asset path: ${String(relative)}`);
  }
  return relative;
}
function checkLines(lines) {
  if (!Array.isArray(lines) || !lines.length || lines.length > 45 || lines.some(line => line.length > 76)) {
    throw new Error('PDF page capacity exceeded: at most 45 lines of 76 characters');
  }
  if (lines.some(line => /[^\x20-\x7e]/.test(line))) throw new Error('PDF source must use printable ASCII page lines');
}
export function pdfBytes(lines) {
  checkLines(lines);
  const literal = text => text.replace(/([\\()])/g, '\\$1');
  const stream = `BT\n/F1 11 Tf\n14 TL\n54 736 Td\n${lines.map((line, index) => `${index ? 'T*\n' : ''}(${literal(line)}) Tj`).join('\n')}\nET\n`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>',
    `<< /Length ${Buffer.byteLength(stream, 'ascii')} >>\nstream\n${stream}endstream`,
  ];
  let source = '%PDF-1.4\n';
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(source, 'ascii'));
    source += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const startxref = Buffer.byteLength(source, 'ascii');
  source += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  source += offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  source += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${startxref}\n%%EOF\n`;
  return Buffer.from(source, 'ascii');
}
export function pagePreview(lines) {
  checkLines(lines);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="612" height="822" viewBox="0 0 612 822" role="img"><title>Derivative preview of a synthetic PDF page</title><rect width="612" height="822" fill="#edf4f3"/><text x="20" y="19" font-family="Arial,sans-serif" font-size="10" fill="#486064">DERIVATIVE PREVIEW - OPEN THE PDF FOR THE ORIGINAL FORMAT</text><g transform="translate(0 30)"><rect width="612" height="792" fill="white" stroke="#bccdca"/>${lines.map((line, index) => `<text x="54" y="${56 + index * 14}" font-family="Courier,monospace" font-size="11" fill="#162b2d" xml:space="preserve">${xml(line)}</text>`).join('')}</g></svg>`;
}
export function renderAssets(artifacts = ARTIFACTS) {
  const files = new Map();
  const entries = [];
  const put = (relative, bytes, sourceArtifact, derivativeOf = null) => {
    validateAssetPath(relative);
    if (files.has(relative)) throw new Error(`Duplicate generated asset: ${relative}`);
    files.set(relative, bytes);
    entries.push({ path: relative, sourceArtifact, derivativeOf, bytes: bytes.length,
      sha256: createHash('sha256').update(bytes).digest('hex') });
  };
  for (const artifact of Object.values(artifacts)) {
    validateAssetPath(artifact.path);
    const extension = extensions[artifact.type];
    if (!extension || path.extname(artifact.path) !== `.${extension}`) throw new Error(`Artifact extension mismatch: ${artifact.id}`);
    if (typeof artifact.body !== 'string') throw new Error(`Artifact body is not text source: ${artifact.id}`);
    if (artifact.type === 'pdf') {
      const lines = artifact.body.split('\n');
      if (!artifact.preview || path.extname(artifact.preview) !== '.svg') throw new Error(`Missing derivative SVG path: ${artifact.id}`);
      put(artifact.path, pdfBytes(lines), artifact.id);
      put(artifact.preview, Buffer.from(pagePreview(lines), 'utf8'), artifact.id, artifact.path);
    } else {
      if (artifact.type === 'svg' && (/<(?:script|foreignObject|iframe|image|use)\b/i.test(artifact.body)
        || /\bon[a-z]+\s*=|\b(?:href|src)\s*=|url\s*\(/i.test(artifact.body))) {
        throw new Error(`Active SVG is forbidden in synthetic fixtures: ${artifact.id}`);
      }
      put(artifact.path, Buffer.from(artifact.body, 'utf8'), artifact.id);
    }
  }
  files.set('assets/manifest.json', Buffer.from(`${JSON.stringify({ synthetic: true,
    description: 'Deterministic UI fixture assets; not actual work, lens or evaluation evidence.', entries }, null, 2)}\n`, 'utf8'));
  return { files, entries };
}
async function statOrNull(target) {
  try { return await lstat(target); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}
export async function buildAssets() {
  const directory = path.join(prototypeRoot, 'assets');
  const existingDirectory = await statOrNull(directory);
  if (existingDirectory && (!existingDirectory.isDirectory() || existingDirectory.isSymbolicLink())) {
    throw new Error('Refusing a non-directory or symbolic-link assets destination');
  }
  await mkdir(directory, { recursive: false }).catch(error => { if (error.code !== 'EEXIST') throw error; });
  const createdDirectory = await lstat(directory);
  if (!createdDirectory.isDirectory() || createdDirectory.isSymbolicLink()) throw new Error('Refusing changed assets destination');
  const { files } = renderAssets();
  let created = 0;
  let unchanged = 0;
  for (const [relative, bytes] of files) {
    const target = path.join(prototypeRoot, validateAssetPath(relative));
    const existing = await statOrNull(target);
    if (existing) {
      if (!existing.isFile() || existing.isSymbolicLink()) throw new Error(`Refusing non-regular asset: ${relative}`);
      if (!(await readFile(target)).equals(bytes)) throw new Error(`Asset differs; preserve and review before replacing: ${relative}`);
      unchanged += 1;
    } else {
      await writeFile(target, bytes, { flag: 'wx' });
      created += 1;
    }
  }
  return { created, unchanged, total: files.size };
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  buildAssets().then(result => process.stdout.write(`${JSON.stringify(result)}\n`)).catch(error => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
```

- [ ] **Step 6: Run the tests without writing any generated assets.**

Run: `node --test control-prototype/tests/fixtures.test.mjs`

Expected: eight tests pass; no skipped or failed tests. The tests call `renderAssets()` in memory and never `buildAssets()`. A passing test is a fixture-format/reference assertion, not a DeepTwin effect or user-experience acceptance claim.

- [ ] **Step 7: Generate the served fixture files only during authorized implementation.**

Run: `node control-prototype/build-assets.mjs`

Expected: one JSON record with `created > 0`, `unchanged: 0`, and `total === created` on a clean first run. Run the same command once more; expected `created: 0`, `unchanged === total`. The builder refuses to overwrite an existing changed asset or symlink. If that occurs, inspect the exact reported file, preserve the conflicting file in a named backup within the project with the user's changes intact, and agree on the affected target before any replacement; do not delete or overwrite the whole directory.

The main UI plan must visually inspect the served PDF, derivative preview, CSV table and SVG timeline. Byte tests cannot establish pagination readability or graphical usability. The interface must offer the actual PDF separately and label the SVG preview as derived. Generated assets are this fixture's finite demonstration coverage, not the eventual framework's full format support.

- [ ] **Step 8: Commit only these implementation files and their generated fixture assets.**

Run after successful tests and scope review:

```sh
git add -- control-prototype/fixtures.mjs control-prototype/build-assets.mjs control-prototype/tests/fixtures.test.mjs control-prototype/assets
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: add typed control-workspace synthetic fixtures"
```

Expected: only the explicit new prototype fixture files/assets are staged. Do not stage an unrelated dirty plan, old prototype, source PDF, local account configuration, or main-worktree untracked document. If the index already contains unrelated files, preserve it and use the main implementation plan's scoped-commit process rather than committing those files.

## Self-review and integration notes

- The substantive complete brief, partial summary alternative, complete downstream CSV and SVG schedule share one coherent policy/source context. Tuesday's writer-only candidate leaves downstream inconsistency, while Thursday exposes its overgeneralization. The later illustrated contract transmits source timing fields, changes outputs outside the selected paragraph and does not receive the alternative as an input.
- Original demonstration runs, per-round baselines and candidates have distinct IDs. The failed write has no output/consumer, the retry consumes its recorded inputs, and the later post-review draft has a new stage number and two outputs. Whole-graph topology is intentionally unchanged across paired runs; internal handoff and writer contracts remain inspectable.
- Candidate comparison includes sequential immutable handoffs, supervised parallel evidence with an early gate, and a shared versioned workspace. All have resources, authority, evaluation and memory. A declined fourth path and separate merge review are preserved; no numeric score, verified lens provenance or independence result is invented.
- No file-change percentage, authored round result, one-case similarity or partial review is a learned rule, final validation, human approval or version application. New user drafts must remain unanalysed prototype drafts. The UI may inspect `CASE` only as the pre-authored synthetic example, with separate navigation and explicit labeling.
- `renderAssets` is not a general security sanitizer or upload facility. It only serves immutable code-owned fixture text and simple generated SVG. A future arbitrary PDF/image/HTML upload facility needs its own sandbox, trust boundary, format validation, resource limits and user-facing unsupported-state contract.
- Before this appendix is executed, the main worker must read the applicable PDF skill and use the required render-and-inspect workflow for the newly generated PDFs. This writing-only task has not run the builder, extracted any implementation block into a live module, or created a PDF.
