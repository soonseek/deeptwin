// UI phase 3: the run trace's pure logic (run-trace.mjs) over a synthetic run-trace-v1 payload
// shaped like the server's (services/run_traces.py): a writer model call recorded by the
// executor, a store step whose attempt 1 failed and attempt 2 succeeded, a final report.
// Nothing here is computed to fill a gap: unrecorded values stay "기록 없음".

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  attemptOptionText, errorText, finalResults, pendingApprovals, resolveSelection, runSummary, selectionView,
  timelineRows, traceRoute, traceView,
} from '../static/run-trace.mjs';

import { costText, ratesText } from '../static/ui-format.mjs';

import { RUN, id, ref, sampleTrace } from './helpers/run-trace-sample.mjs';

test('the trace route is the fixed run route under the deployment base, and nothing else', () => {
  assert.equal(traceRoute('/', RUN), `/api/v1/runs/${RUN}/trace`);
  assert.equal(traceRoute(`/${'2'.repeat(32)}/`, RUN), `/${'2'.repeat(32)}/api/v1/runs/${RUN}/trace`);
  assert.throws(() => traceRoute('/', '../x'));
  assert.throws(() => traceRoute('/x/', RUN));
});

test('a payload outside the contract is refused, never half shown', () => {
  assert.equal(traceView(sampleTrace()).run_id, RUN);
  assert.throws(() => traceView({ ...sampleTrace(), schema_version: 'run-trace-v0' }), { code: 'unavailable' });
  assert.throws(() => traceView({ ...sampleTrace(), nodes: {} }), { code: 'unavailable' });
  const broken = sampleTrace();
  broken.nodes[2].visits[0].attempts[0].outputs = null;
  assert.throws(() => traceView(broken), { code: 'unavailable' });
});

test('the header names the work, the phase in words, the calls and an unrecorded cost as unknown', () => {
  const summary = runSummary(sampleTrace());
  assert.equal(summary.title, '화요일 공간 안내');
  assert.deepEqual([summary.phaseLabel, summary.tone], ['완료', 'ok']);
  assert.equal(summary.duration, '22초');
  assert.match(summary.calls, /모델 호출 1회 · 도구 호출 2회 · 시도 2회\(재시도 1회\)/);
  assert.equal(summary.tokens, '입력 812 · 출력 164 토큰');
  assert.equal(summary.cost, '미확인');
  const untitled = runSummary(sampleTrace({ work: { title: 'not_recorded' }, ended_at_utc: 'not_recorded', phase: 'running' }));
  assert.equal(untitled.title, `실행 ${RUN.slice(0, 8)}`);
  assert.equal(untitled.duration, null);
  assert.equal(untitled.phaseLabel, '미완료');
  // a run total may add estimates of either method, so it names the ceiling, not the method
  const estimated = runSummary(sampleTrace({ totals: { ...sampleTrace().totals, tokens_complete: false,
    cost: { state: 'estimate', microunits: 34_000, currency: 'USD' } } }));
  assert.equal(estimated.cost, '약 $0.034 (상한 기준 추정)');
  assert.match(estimated.tokens, /일부 호출은 토큰 기록 없음/);
});

test('a cost says its basis: settled, an estimate by its method, a subscription, or unknown', () => {
  const rates = { currency: 'USD', unit: 'microunits_per_million_tokens', input_microunits_per_mtok: 4_000_000,
    output_microunits_per_mtok: 20_000_000, cache_creation_microunits_per_mtok: null,
    cache_read_microunits_per_mtok: 400_000 };
  assert.equal(costText({ state: 'settled', basis: 'budget_settlement', microunits: 9_000, currency: 'USD' }),
    '$0.009 (정산 기록)');
  assert.equal(costText({ state: 'estimate', basis: 'reserved_ceiling', method: 'reservation', microunits: 25_000,
    currency: 'USD' }), '약 $0.025 (예약 상한 기준 추정)');
  assert.equal(costText({ state: 'estimate', basis: 'reserved_ceiling', method: 'recorded_tokens_at_ceiling_rates',
    microunits: 6_528, currency: 'USD', rates }), '약 $0.0065 (기록된 토큰 × 설정된 상한 단가 추정)');
  // an unknown method is still only an estimate, never a settled amount
  assert.equal(costText({ state: 'estimate', method: 'constructor', microunits: 1_000, currency: 'USD' }),
    '약 $0.001 (상한 기준 추정)');
  assert.equal(costText({ state: 'unknown', basis: 'subscription_mode' }), '미확인 (구독 방식: 호출별 금액 없음)');
  assert.equal(costText({ state: 'unknown', basis: 'not_recorded' }), '미확인');
  assert.equal(ratesText(rates), '입력 $4 · 출력 $20 · 캐시 읽음 $0.4 (100만 토큰당)');
  assert.equal(ratesText(null), '기록 없음');
});

test('a model attempt names the tokens its provider reported in the timeline', () => {
  const trace = sampleTrace();
  const second = trace.nodes[2].visits[0].attempts[1];
  second.budget_reservation.reserved.model_calls = 1;
  second.tokens = { input: 812, output: 164, cache_creation_input: 0, cache_read_input: 'not_recorded' };
  const rows = timelineRows(trace);
  assert.match(rows[3].detail, /입력 812\/출력 164 토큰$/);
  assert.doesNotMatch(rows[2].detail, /토큰/);  // attempt 1's provider reported none
});

test('final results come from the graph exit; without them the stop points are named', () => {
  const view = finalResults(sampleTrace());
  assert.deepEqual(view.items.map(item => [item.role, item.nodeId, item.attemptNo]), [['report', 'report', null]]);
  assert.equal(view.items[0].responsibility, '최종 보고서로 묶는다');
  const stopped = finalResults(sampleTrace({ final_results: [], stopped_at: [{ node_id: 'publish', state: 'failed' }] }));
  assert.deepEqual(stopped.items, []);
  assert.deepEqual(stopped.stopped.map(item => [item.nodeId, item.label, item.tone]), [['publish', '실패', 'error']]);
});

test('the default selection is the latest attempt, and a past attempt carries only its own facts', () => {
  const trace = sampleTrace();
  assert.deepEqual({ ...resolveSelection(trace, { nodeId: 'publish' }) }, { nodeId: 'publish', visitNo: 1, attemptNo: 2 });
  const latest = selectionView(trace, { nodeId: 'publish' });
  assert.equal(latest.scope, 'attempt');
  assert.equal(latest.isLatestAttempt, true);
  assert.equal(latest.error, null);
  assert.equal(latest.toolCalls[0].call.state, 'succeeded');
  const past = selectionView(trace, { nodeId: 'publish', attemptNo: 1 });
  assert.equal(past.attemptNo, 1);
  assert.equal(past.isLatestAttempt, false);
  assert.deepEqual(past.outputIds, []);  // never the visit's later result
  assert.equal(past.outputsFrom, 'attempt');
  assert.equal(past.error.outcome, 'failed');
  assert.deepEqual(past.toolCalls.map(entry => [entry.attemptNo, entry.call.state]), [[1, 'failed']]);
  assert.deepEqual(past.journal.map(entry => entry.transition), ['reserved', 'send_intent']);
  assert.deepEqual(past.approvals.executions.map(item => item.attempt_no), [1]);
  // the inputs and hand-offs are the visit's: the same exact producer result for every attempt
  assert.deepEqual(past.inputs.map(item => item.from_node_id), ['writer']);
  assert.deepEqual(past.handoffsIn.map(item => item.from_node_id), ['writer']);
});

test('a visit without ledger attempts shows its own result and its model call', () => {
  const writer = selectionView(sampleTrace(), { nodeId: 'writer' });
  assert.equal(writer.scope, 'visit');
  assert.equal(writer.attemptNo, null);
  assert.deepEqual(writer.outputIds, [id(200)]);
  assert.equal(writer.modelCalls.length, 1);
  assert.equal(writer.modelCalls[0].call.tokens.input, 812);
  assert.deepEqual(writer.handoffsOut.map(item => item.to_node_id), ['publish']);
});

test('no selection is the whole run; an unknown node is no selection', () => {
  const run = selectionView(sampleTrace(), { nodeId: null });
  assert.equal(run.scope, 'run');
  assert.deepEqual([...run.outputIds].sort(), [id(100), id(200), id(300)].sort());
  assert.equal(run.toolCalls.length, 2);
  assert.equal(run.modelCalls.length, 1);
  assert.equal(selectionView(sampleTrace(), { nodeId: 'nope' }).scope, 'run');
});

test('the timeline names each visit, model call and attempt in time order, with its outcome in words', () => {
  const rows = timelineRows(sampleTrace());
  assert.deepEqual(rows.map(row => [row.kind, row.nodeId, row.text]), [
    ['visit', 'intake', '수행 1'], ['model_call', 'writer', '모델 호출'], ['attempt', 'publish', '시도 1'],
    ['attempt', 'publish', '시도 2']]);
  assert.match(rows[1].detail, /입력 812\/출력 164 토큰/);
  assert.match(rows[2].detail, /^실패 — 도구·제공자의 응답으로 끝남 · 도구 호출 1회$/);
  assert.equal(rows[2].tone, 'error');
  assert.equal(rows[3].tone, 'ok');
});

test('pending approvals, attempt options and error text are spelled out', () => {
  assert.deepEqual(pendingApprovals(sampleTrace()), []);
  const waiting = sampleTrace();
  waiting.approvals.gates.push({ node_id: 'tool-gate', approval_scope: 'release-output', state: 'pending' });
  waiting.approvals.executions[1].state = 'pending';
  assert.deepEqual(pendingApprovals(waiting).map(item => [item.nodeId, item.attemptNo]), [['tool-gate', null], ['publish', 2]]);
  const [first, second] = sampleTrace().nodes[2].visits[0].attempts;
  assert.equal(attemptOptionText(first, second), '시도 1 (실패)');
  assert.equal(attemptOptionText(second, second), '시도 2 (완료, 최신)');
  assert.equal(errorText({ outcome: 'timed_out', reason_code: 'not_recorded' }), '시간 초과 — 이유 기록 없음');
  assert.equal(errorText('not_recorded'), '오류: 기록 없음');
  assert.equal(errorText(null), '');
});

// UI phase 6: the context bar's mode badge comes only from the trace's own `run_mode` (the
// ledger's frozen run spec); a replay, a snapshot or an older trace without it names no mode
test('the run mode badge is the trace\'s recorded mode or nothing', async () => {
  const { RUN_MODE_BADGES, traceMode } = await import('../static/run-trace.mjs');
  assert.deepEqual({ ...RUN_MODE_BADGES }, { live: 'operating', 'isolated-comparison': 'isolated_experiment' });
  assert.equal(traceMode({ run_mode: 'live' }), 'operating');
  assert.equal(traceMode({ run_mode: 'isolated-comparison' }), 'isolated_experiment');
  for (const value of ['replay', 'snapshot', 'not_recorded', undefined, null, 'operating', 7]) {
    assert.equal(traceMode({ run_mode: value }), null, String(value));
  }
  assert.equal(traceMode(null), null);
});
