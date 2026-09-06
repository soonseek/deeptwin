import test from 'node:test';
import assert from 'node:assert/strict';
import { ARTIFACTS, CASE, DESIGNS, LOGS, REVISED_DESIGN, ROUNDS, RUNS, WORK_MODEL } from '../fixtures.mjs';
import { context, createState, draftKey, noteKey, transition } from '../state.mjs';
import { e } from '../primitives.mjs';
import { render, overlay, sampleInspection } from '../workspace.mjs';

const select = (state, type, value, extra = {}) => transition(state, { type, value, ...extra });
const origin = Object.values(RUNS).find(run => run.attempts.some(attempt => attempt.outputs.includes(CASE.original)));

test('design comparison retains three full graphs, true focus contracts and a separate revised version', () => {
  let state = select(createState(), 'area', 'design');
  for (const focus of ['transfer', 'approval', 'memory', 'evaluation']) {
    state = select(state, 'focus', focus);
    const markup = render(state);
    const candidates = [...markup.matchAll(/<section class="candidate" data-design="([^"]+)">([\s\S]*?)<\/section>/g)];
    assert.equal(candidates.length, DESIGNS.length);
    for (const design of DESIGNS) {
      const candidate = candidates.find(match => match[1] === design.id)?.[2];
      assert.ok(candidate, design.id);
      assert.equal((candidate.match(/data-edge=/g) ?? []).length, design.edges.length);
      assert.ok(candidate.includes(e(design.contracts[focus])));
      for (const node of design.nodes) assert.ok(candidate.includes(`data-value="${design.id}:candidate:${node.id}"`));
      for (const id of design.focus[focus]) {
        const tag = [...candidate.matchAll(/<g class="node [^>]*>/g)].find(match => match[0].includes(`data-value="${design.id}:candidate:${id}"`))?.[0];
        assert.match(tag, /aria-pressed="true"/);
        assert.ok(candidate.includes(e(design.nodes.find(node => node.id === id).label)));
      }
      assert.ok(candidate.includes(e(design.review)));
    }
    assert.ok(markup.includes(`${state.design}:selected:`));
    for (const field of ['purpose', 'done', 'source', 'unknown']) assert.ok(markup.includes(e(WORK_MODEL[field])));
    assert.ok(markup.includes('data-field="workText"'));
    assert.ok(markup.includes('data-field="designText"'));
    assert.doesNotMatch(markup, /source-dependency@|uncertainty-gate@/);
  }
  state = select(state, 'design', REVISED_DESIGN.id);
  const revised = render(state);
  assert.ok(revised.includes(REVISED_DESIGN.version));
  assert.ok(revised.includes(e(REVISED_DESIGN.review)));
  assert.ok(revised.includes('사전 구성된 병합 예시 보기'));
  assert.ok(revised.includes('사용자 요청을 처리한 결과가 아닙니다'));
});

test('fresh growth keeps the real draft context and never inherits fixed example claims', () => {
  let state = select(createState(), 'draft', '\n새로운 자기 버전');
  const key = draftKey(state);
  state = select(state, 'area', 'growth');
  const markup = render(state);
  assert.ok(markup.includes('현재 입력의 개선 영역'));
  assert.ok(markup.includes('분석 결과 없음 · 실제 탐구·실험 엔진 미연결'));
  assert.ok(markup.includes(e(state.drafts[key])));
  assert.ok(markup.includes(e(context(state).attempt)));
  assert.ok(markup.includes('별도의 고정 합성 사례 탐색'));
  assert.doesNotMatch(markup, /data-hypothesis=|data-pair=|data-round=/);
  for (const difference of CASE.differences) for (const hypothesis of difference.hypotheses) assert.ok(!markup.includes(e(hypothesis.claim)));
});

test('fixed growth exposes the partial comparison and every exact paired round with its limits', () => {
  let state = select(select(createState(), 'area', 'growth'), 'sample', true);
  for (const round of ROUNDS) {
    state = select(state, 'round', round.id);
    const markup = render(state);
    assert.ok(markup.includes(`data-artifact="${CASE.original}"`));
    assert.ok(markup.includes(`data-artifact="${CASE.alternative}"`));
    assert.ok(markup.includes(CASE.region));
    assert.ok(markup.includes('현재 입력과 별개'));
    assert.ok(markup.includes('data-action="sampleNode"'));
    for (const entry of ROUNDS) assert.ok(markup.includes(`data-round="${entry.id}"`));
    for (const side of ['baseline', 'candidate']) {
      const runId = round[`${side}Run`];
      assert.ok(markup.includes(`data-pair="${side}" data-run="${runId}"`));
      const run = RUNS[runId];
      assert.ok(markup.includes(`data-value="${side}:${run.nodes[0].id}"`));
      const attempt = run.attempts.filter(item => item.outputs.length).at(-1);
      for (const id of [...attempt.inputs, ...attempt.outputs]) assert.ok(markup.includes(`data-artifact="${id}"`));
    }
    for (const difference of CASE.differences) for (const hypothesis of difference.hypotheses) {
      for (const field of ['claim', 'support', 'counter', 'unknown', 'probe', 'newEvidence']) assert.ok(markup.includes(e(hypothesis[field])));
    }
    for (const check of round.checks) assert.ok(markup.includes(`data-action="evidence" data-value="${check.evidence}"`));
    for (const field of ['result', 'limits', 'finalEvidence', 'approval']) assert.ok(markup.includes(e(round[field])));
    assert.ok(markup.includes('부분 밖 영향'));
    assert.ok(markup.includes('별도 최종 근거'));
  }
});

test('all areas and modes retain meaningful objects, scoped conversation and common utilities', () => {
  for (const area of ['design', 'run', 'growth']) for (const mode of ['workspace', 'conversation', 'graph']) {
    let state = select(select(createState(), 'area', area), 'mode', mode);
    state = select(state, 'note', '\n현재 맥락 메모');
    const markup = render(state);
    assert.ok(markup.includes(`class="shell" data-area="${area}" data-mode="${mode}"`));
    assert.ok(markup.includes('id="page-title" tabindex="-1"'));
    assert.ok(markup.includes('화면 시제품 · 합성 실행 기록 · AI/외부 도구/학습 미연결'));
    for (const value of ['connection', 'logs']) assert.ok(markup.includes(`data-action="overlay" data-value="${value}"`));
    assert.ok(markup.includes('id="storage-status" role="status"'));
    assert.ok(markup.includes('탭 보관 다시 시도'));
    assert.ok(markup.includes('시험용 작성 내용 초기화'));
    if (mode === 'conversation') {
      assert.ok(markup.includes('data-field="note"'));
      assert.ok(markup.includes(e(state.notes[noteKey(state)])));
    }
    if (area === 'design') assert.ok(markup.includes('class="candidates"'));
    if (area === 'run') assert.ok(markup.includes(`data-run="${state.run}"`));
    if (area === 'growth') assert.ok(markup.includes('현재 입력의 개선 영역'));
  }
});

test('run inspection retains exact failure, retry, outputs and consumer identities', () => {
  let state = createState();
  const failed = origin.attempts.find(attempt => attempt.status === 'failed');
  state = select(state, 'attempt', failed.id);
  let markup = render(state);
  assert.ok(markup.includes(failed.id));
  assert.ok(markup.includes('출력 없음 · 다른 시도의 최신 파일로 채우지 않음'));
  assert.doesNotMatch(markup, /data-field="draft"|id="alternative-file"/);
  for (const input of failed.inputs) assert.ok(markup.includes(`data-action="artifact" data-value="${input}"`));
  const completed = origin.attempts.find(attempt => attempt.outputs.includes(CASE.original));
  state = select(state, 'attempt', completed.id);
  markup = render(state);
  for (const attempt of origin.attempts.filter(item => item.node === completed.node)) assert.ok(markup.includes(`data-action="attempt" data-value="${attempt.id}"`));
  for (const consumer of completed.consumers) assert.ok(markup.includes(`data-action="consumer" data-value="${consumer.attempt}"`));
  assert.ok(markup.includes('data-field="draft"'));
  assert.ok(markup.includes('id="alternative-file"'));
  assert.ok(markup.includes('id="file-status"'));
  assert.ok(markup.includes('이유 불필요'));
  state = select(state, 'node', 'files');
  markup = render(state);
  assert.ok(markup.includes('실제 수행 기록 없음'));
  assert.doesNotMatch(markup, /data-field="draft"/);
});

test('graph mode keeps the full graph open and all run choices in a compact picker', () => {
  const state = createState();
  const markup = render(state);
  assert.match(markup, /<details class="run-picker"><summary>[^<]*run-j1-origin/);
  assert.match(markup, /<details class="run-graph" open>/);
  for (const run of Object.values(RUNS)) assert.ok(markup.includes(`data-action="run" data-value="${run.id}"`));
});

test('sample inspection shows exact attempt versions, full files and receivers without touching state', () => {
  const state = createState();
  const before = JSON.stringify(state);
  for (const attempt of origin.attempts.filter(item => item.node === 'draft')) {
    const markup = sampleInspection('draft', attempt.id);
    assert.ok(markup.includes(`data-inspected-attempt="${attempt.id}"`));
    assert.ok(markup.includes(`수행 ${attempt.stage} · 시도 ${attempt.try}`));
    for (const id of [...attempt.inputs, ...attempt.outputs]) assert.ok(markup.includes(`data-artifact="${id}"`));
    for (const consumer of attempt.consumers) assert.ok(markup.includes(`data-action="sampleConsumer" data-value="${consumer.attempt}"`));
    for (const event of attempt.events) assert.ok(markup.includes(e(event)));
    if (!attempt.outputs.length) assert.ok(markup.includes('출력 없음 · 다른 시도의 최신 파일로 채우지 않음'));
  }
  const latest = origin.attempts.filter(item => item.node === 'draft').at(-1);
  assert.ok(sampleInspection('draft').includes(`data-inspected-attempt="${latest.id}"`));
  assert.ok(sampleInspection('files').includes('실제 수행 기록 없음'));
  assert.ok(sampleInspection('draft', origin.attempts[0].id).includes('시도 미확인'));
  assert.equal(JSON.stringify(state), before);
});

test('paired no-attempt resources remain empty and histories stay bound to their side', () => {
  let state = select(select(createState(), 'area', 'growth'), 'sample', true);
  state = transition(state, { type: 'pair', side: 'baseline', value: '@files' });
  const markup = render(state);
  assert.ok(markup.includes('data-pair="baseline"'));
  assert.ok(markup.includes('실제 수행 기록 없음'));
  const run = RUNS[ROUNDS[0].candidateRun];
  const failedOrFirst = run.attempts[0];
  state = transition(state, { type: 'pair', side: 'candidate', value: failedOrFirst.id });
  const selected = render(state);
  assert.ok(selected.includes(`data-inspected-attempt="${failedOrFirst.id}"`));
  assert.ok(selected.includes(`data-action="pairAttempt" data-value="candidate:${failedOrFirst.id}"`));
});

test('user text is escaped in bounded fields and overlays remain honest read-only demonstrations', () => {
  const payload = '\n</textarea><script>alert("x")</script>';
  let state = select(createState(), 'draft', payload);
  state = select(state, 'note', payload);
  state = select(state, 'workText', payload);
  state = select(state, 'designText', payload);
  for (const area of ['design', 'run']) {
    const markup = render(select(select(state, 'area', area), 'mode', 'conversation'));
    assert.doesNotMatch(markup, /<script>|<textarea[^>]*>[\s\S]*?<\/textarea><script>/);
    assert.ok(markup.includes(e(payload)));
    for (const tag of markup.match(/<textarea[^>]*>/g) ?? []) assert.ok(tag.includes('maxlength="20000"'));
  }
  const connection = overlay(state, 'connection');
  assert.match(connection, /Claude/);
  assert.match(connection, /Codex/);
  assert.match(connection, /구독/);
  assert.match(connection, /API.*선택/);
  assert.match(connection, /자동.*과금/);
  assert.match(connection, /부분.*결과.*불명/);
  const approval = overlay(select(state, 'area', 'design'), 'approval');
  assert.ok(approval.includes('승인 대상 미리보기 · 실제 승인 미연결'));
  assert.match(approval, /<button[^>]*disabled/);
  assert.ok(approval.includes(DESIGNS[0].version));
  let logs = overlay(state, 'logs');
  for (const record of LOGS) assert.ok(logs.includes(`data-record="${record.id}"`));
  assert.ok(logs.includes('id="redact"'));
  assert.ok(logs.includes('출처 표지만 가림 · 본문 자동 가림 아님'));
  assert.ok(!logs.includes('synthetic-fixture'));
  logs = overlay(select(state, 'redact', false), 'logs');
  assert.ok(logs.includes('synthetic-fixture'));
  const audit = overlay(state, 'audit');
  for (const group of Object.values(CASE.audit)) for (const entry of group) assert.ok(audit.includes(e(entry)));
  assert.ok(overlay(state, 'artifact').includes(`data-artifact="${context(state).artifact}"`));
});
