// UI phase 3 (logic half): the run trace (GET {base}api/v1/runs/{run}/trace, run-trace-v1) read
// for the run detail screen (docs/ui/2026-09-26-product-ux-redesign.md §5.3, experience.md §7).
// Pure functions only: no DOM, no network. They never compute a missing fact: a value the
// server marked `not_recorded` stays "기록 없음", a cost is shown with its basis, and a past
// attempt only ever carries its own outputs — never the visit's later result.

import {
  ATTEMPT_OUTCOME_TEXT, MODEL_CALL_STATE_TEXT, NOT_RECORDED, RESULT_REASON_LABELS, RUN_PHASE_TEXT,
  TOOL_CALL_STATE_TEXT, TRACE_NODE_STATE_TEXT, VISIT_STATUS_TEXT, costText, countText, durationText, shortId,
  stateText,
} from './ui-format.mjs';

export const TRACE_SCHEMA = 'run-trace-v1';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
export const MAX_NODES = 256;

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

export function traceRoute(basePath, runId) {
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  if (typeof runId !== 'string' || !UUID.test(runId)) fail('run id is not a canonical UUID');
  return `${basePath.slice(0, -1)}/api/v1/runs/${runId}/trace`;
}

const recorded = value => value !== NOT_RECORDED && value !== null && value !== undefined;

// the trace as the server sent it, refused when its own shape is not the contract's
export function traceView(payload) {
  if (typeof payload !== 'object' || payload === null || payload.schema_version !== TRACE_SCHEMA) {
    fail('not a run trace', 'unavailable');
  }
  if (typeof payload.run_id !== 'string' || !UUID.test(payload.run_id)) fail('trace run id is malformed', 'unavailable');
  for (const name of ['nodes', 'handoffs', 'timeline', 'final_results', 'stopped_at', 'gaps', 'stops']) {
    if (!Array.isArray(payload[name])) fail(`trace ${name} is not a list`, 'unavailable');
  }
  if (payload.nodes.length > MAX_NODES) fail('trace names too many nodes', 'unavailable');
  for (const node of payload.nodes) {
    if (typeof node?.node_id !== 'string' || !Array.isArray(node.visits)) fail('a trace node is malformed', 'unavailable');
    for (const visit of node.visits) {
      if (!Number.isSafeInteger(visit?.visit_no) || !Array.isArray(visit.attempts) || !Array.isArray(visit.outputs)
          || !Array.isArray(visit.inputs) || !Array.isArray(visit.model_calls)) {
        fail('a trace visit is malformed', 'unavailable');
      }
      for (const attempt of visit.attempts) {
        if (!Number.isSafeInteger(attempt?.attempt_no) || !Array.isArray(attempt.outputs)
            || !Array.isArray(attempt.tool_calls) || !Array.isArray(attempt.journal)) {
          fail('a trace attempt is malformed', 'unavailable');
        }
      }
    }
  }
  if (typeof payload.totals !== 'object' || payload.totals === null) fail('trace totals are missing', 'unavailable');
  if (typeof payload.approvals !== 'object' || !Array.isArray(payload.approvals?.gates)
      || !Array.isArray(payload.approvals?.executions)) fail('trace approvals are malformed', 'unavailable');
  // the owner's process feedback (UI phase 4): optional, but a present one has its shape
  if (payload.feedback !== undefined && (typeof payload.feedback !== 'object' || payload.feedback === null
      || !Array.isArray(payload.feedback.steps))) fail('trace feedback is malformed', 'unavailable');
  return payload;
}

// the run header's facts
// the context bar's mode badge (ui-shell.mjs MODE_LABELS) from what the ledger froze in the
// run spec: a live run is an operating run, an isolated-comparison run is an isolated
// experiment round. A replay, a snapshot, an older trace without the field or an unrecorded
// value names no mode: the badge stays empty rather than guessed (UI phase 6).
export const RUN_MODE_BADGES = Object.freeze({ live: 'operating', 'isolated-comparison': 'isolated_experiment' });

export function traceMode(trace) {
  const mode = trace?.run_mode;
  return typeof mode === 'string' && Object.hasOwn(RUN_MODE_BADGES, mode) ? RUN_MODE_BADGES[mode] : null;
}

export function runSummary(trace) {
  const [phaseLabel, tone] = stateText(RUN_PHASE_TEXT, trace.phase);
  const title = recorded(trace.work?.title) ? trace.work.title : `실행 ${shortId(trace.run_id)}`;
  const totals = trace.totals;
  const tokens = totals.model_calls
    ? `입력 ${countText(totals.input_tokens)} · 출력 ${countText(totals.output_tokens)} 토큰`
      + (totals.tokens_complete ? '' : ' (일부 호출은 토큰 기록 없음)')
    : '모델 호출 없음';
  const calls = `모델 호출 ${countText(totals.model_calls, '회')} · 도구 호출 ${countText(totals.tool_calls, '회')}`
    + (totals.attempts ? ` · 시도 ${totals.attempts}회${totals.retries ? `(재시도 ${totals.retries}회)` : ''}` : '');
  return Object.freeze({
    title, titleRecorded: recorded(trace.work?.title), phase: trace.phase, phaseLabel, tone,
    startedAt: recorded(trace.started_at_utc) ? trace.started_at_utc : null,
    endedAt: recorded(trace.ended_at_utc) ? trace.ended_at_utc : null,
    duration: recorded(trace.ended_at_utc) ? durationText(trace.started_at_utc, trace.ended_at_utc) : null,
    calls, tokens, cost: costText(totals.cost),
  });
}

export function nodeLabel(trace, nodeId) {
  const node = trace.nodes.find(item => item.node_id === nodeId);
  return node ? `${node.responsibility}` : nodeId;
}

// what the run produced at the graph's declared exit, or where it stopped
export function finalResults(trace) {
  const items = trace.final_results.map(item => Object.freeze({
    artifactId: item.artifact_id, role: item.role, mediaType: item.declared_media_type, size: item.size,
    sha256: item.sha256, nodeId: item.node_id, visitNo: item.visit_no, ordinal: item.ordinal,
    attemptNo: recorded(item.produced_by_attempt_no) ? item.produced_by_attempt_no : null,
    responsibility: nodeLabel(trace, item.node_id), resultRef: item.result_ref,
  }));
  const stopped = trace.stopped_at.map(item => {
    const [label, tone] = stateText(TRACE_NODE_STATE_TEXT, item.state);
    return Object.freeze({ nodeId: item.node_id, state: item.state, label, tone,
      responsibility: nodeLabel(trace, item.node_id) });
  });
  return Object.freeze({ items: Object.freeze(items), stopped: Object.freeze(stopped),
    exitNodeIds: Object.freeze([...(trace.exit?.node_ids ?? [])]), basis: trace.exit?.basis ?? null });
}

function attemptOutcome(attempt) {
  const [label, tone] = stateText(ATTEMPT_OUTCOME_TEXT, attempt.terminal_outcome);
  return { label: recorded(attempt.terminal_outcome) ? label : '진행 중', tone: recorded(attempt.terminal_outcome) ? tone : 'info' };
}

export function errorText(error) {
  if (error === null || error === undefined) return '';
  if (error === NOT_RECORDED) return '오류: 기록 없음';
  const [outcome] = stateText(ATTEMPT_OUTCOME_TEXT, error.outcome);
  const reason = recorded(error.reason_code) ? (RESULT_REASON_LABELS[error.reason_code] ?? error.reason_code) : '이유 기록 없음';
  return `${outcome} — ${reason}`;
}

// visits, attempts and model calls in time order, each naming what it selects
export function timelineRows(trace) {
  const nodes = new Map(trace.nodes.map(node => [node.node_id, node]));
  return Object.freeze(trace.timeline.map((entry, index) => {
    const node = nodes.get(entry.node_id);
    const visit = node?.visits.find(item => item.visit_no === entry.visit_no) ?? null;
    let text;
    let tone;
    let detail = '';
    if (entry.kind === 'attempt') {
      const attempt = visit?.attempts.find(item => item.attempt_no === entry.attempt_no) ?? null;
      const outcome = attemptOutcome(attempt ?? { terminal_outcome: entry.status });
      text = `시도 ${entry.attempt_no}`;
      ({ label: detail, tone } = outcome);
      if (attempt?.error) detail = errorText(attempt.error);
      if (attempt?.tool_calls?.length) detail += ` · 도구 호출 ${attempt.tool_calls.length}회`;
      // a model attempt's tokens, only when its provider reported them
      if (Number.isSafeInteger(attempt?.tokens?.input) || Number.isSafeInteger(attempt?.tokens?.output)) {
        detail += ` · 입력 ${countText(attempt.tokens.input)}/출력 ${countText(attempt.tokens.output)} 토큰`;
      }
    } else if (entry.kind === 'model_call') {
      const call = visit?.model_calls[0] ?? null;
      [detail, tone] = stateText(MODEL_CALL_STATE_TEXT, entry.status);
      text = '모델 호출';
      if (call) detail += ` · 입력 ${countText(call.tokens.input)}/출력 ${countText(call.tokens.output)} 토큰`;
    } else {
      [detail, tone] = stateText(VISIT_STATUS_TEXT, entry.status);
      text = `수행 ${entry.visit_no}`;
    }
    return Object.freeze({
      key: `${index}`, at: entry.at_utc, kind: entry.kind, nodeId: entry.node_id, visitNo: entry.visit_no,
      attemptNo: entry.attempt_no ?? null, text, detail, tone,
      responsibility: node?.responsibility ?? entry.node_id,
    });
  }));
}

export function findNode(trace, nodeId) {
  return trace.nodes.find(item => item.node_id === nodeId) ?? null;
}

// the selection the detail panel shows: a node's visit and one of its attempts. The default
// is the latest visit and its latest attempt; a named past attempt keeps its own facts only.
export function resolveSelection(trace, { nodeId = null, visitNo = null, attemptNo = null } = {}) {
  if (nodeId === null) return Object.freeze({ nodeId: null, visitNo: null, attemptNo: null });
  const node = findNode(trace, nodeId);
  if (node === null) return Object.freeze({ nodeId: null, visitNo: null, attemptNo: null });
  const visit = node.visits.find(item => item.visit_no === visitNo) ?? node.visits.at(-1) ?? null;
  const attempts = visit?.attempts ?? [];
  const attempt = attempts.find(item => item.attempt_no === attemptNo) ?? attempts.at(-1) ?? null;
  return Object.freeze({ nodeId, visitNo: visit?.visit_no ?? null, attemptNo: attempt?.attempt_no ?? null });
}

function artifactIds(list) {
  return list.map(item => item.artifact_id);
}

// every fact the detail tabs show for one selection (or the whole run when none)
export function selectionView(trace, selection) {
  const resolved = resolveSelection(trace, selection);
  if (resolved.nodeId === null) {
    const outputs = new Set();
    for (const node of trace.nodes) for (const visit of node.visits) for (const item of visit.outputs) outputs.add(item.artifact_id);
    const tools = [];
    const models = [];
    for (const node of trace.nodes) {
      for (const visit of node.visits) {
        for (const attempt of visit.attempts) {
          for (const call of attempt.tool_calls) tools.push({ nodeId: node.node_id, visitNo: visit.visit_no, attemptNo: attempt.attempt_no, call });
        }
        for (const call of visit.model_calls) models.push({ nodeId: node.node_id, visitNo: visit.visit_no, call });
      }
    }
    return Object.freeze({
      scope: 'run', ...resolved, node: null, visit: null, attempt: null, attempts: [],
      outputIds: Object.freeze([...outputs]), outputsFrom: 'run',
      inputs: Object.freeze([]), handoffsIn: Object.freeze([]), handoffsOut: Object.freeze(trace.handoffs),
      toolCalls: Object.freeze(tools), modelCalls: Object.freeze(models), journal: Object.freeze([]),
      approvals: trace.approvals, error: null,
    });
  }
  const node = findNode(trace, resolved.nodeId);
  const visit = node.visits.find(item => item.visit_no === resolved.visitNo) ?? null;
  const attempt = visit?.attempts.find(item => item.attempt_no === resolved.attemptNo) ?? null;
  const latest = visit?.attempts.at(-1) ?? null;
  // a ledger attempt shows only its own outputs; a visit without ledger attempts its own result
  const outputs = attempt ? attempt.outputs : visit ? visit.outputs : [];
  const executionId = visit?.execution_id ?? null;
  const handoffsIn = trace.handoffs.filter(item => item.to_execution_id === executionId);
  const handoffsOut = trace.handoffs.filter(item => item.from_execution_id === executionId);
  const tools = (attempt?.tool_calls ?? []).map(call => ({ nodeId: node.node_id, visitNo: visit.visit_no, attemptNo: attempt.attempt_no, call }));
  const models = (visit?.model_calls ?? []).map(call => ({ nodeId: node.node_id, visitNo: visit.visit_no, call }));
  const gates = trace.approvals.gates.filter(item => item.node_id === node.node_id);
  const executions = trace.approvals.executions.filter(item => item.execution_node_id === node.node_id
    && (attempt === null || item.attempt_no === attempt.attempt_no));
  return Object.freeze({
    scope: attempt ? 'attempt' : 'visit', ...resolved, node, visit, attempt,
    attempts: Object.freeze(visit?.attempts ?? []), isLatestAttempt: attempt === latest,
    outputIds: Object.freeze(artifactIds(outputs)), outputsFrom: attempt ? 'attempt' : 'visit',
    inputs: Object.freeze(visit?.inputs ?? []), handoffsIn: Object.freeze(handoffsIn),
    handoffsOut: Object.freeze(handoffsOut), toolCalls: Object.freeze(tools), modelCalls: Object.freeze(models),
    journal: Object.freeze(attempt?.journal ?? []), approvals: Object.freeze({ gates, executions }),
    error: attempt?.error ?? null,
  });
}

// the owner's pending decisions, for the header banner and the node marker
export function pendingApprovals(trace) {
  const gates = trace.approvals.gates.filter(item => item.state === 'pending')
    .map(item => Object.freeze({ nodeId: item.node_id, scope: item.approval_scope, attemptNo: null }));
  const executions = trace.approvals.executions.filter(item => item.state === 'pending')
    .map(item => Object.freeze({ nodeId: item.execution_node_id, gateId: item.node_id, scope: item.approval_scope,
      attemptNo: item.attempt_no }));
  return Object.freeze([...gates, ...executions]);
}

// UI phase 4 (§5.5): the run segment an artifact the owner answered came from — the step, its
// visit and attempt, the exact inputs it received and its tool and model calls — for the
// difference view's first screen. Only what the trace recorded; an unknown step is null.
export function differenceSegment(trace, { nodeId = null, visitNo = null, attemptNo = null } = {}) {
  if (trace === null || typeof nodeId !== 'string') return null;
  const view = selectionView(trace, { nodeId, visitNo, attemptNo });
  if (view.scope === 'run' || view.visit === null) return null;
  const inputs = view.inputs.map(input => Object.freeze({
    nodeId: input.from_node_id, responsibility: nodeLabel(trace, input.from_node_id),
    attemptNo: recorded(input.from_attempt_no) ? input.from_attempt_no : null,
    roles: Object.freeze(input.artifacts.map(item => item.role)),
  }));
  const models = view.modelCalls.map(entry => Object.freeze({
    label: recorded(entry.call.model_label) ? entry.call.model_label : null,
    tokens: `입력 ${countText(entry.call.tokens.input)} · 출력 ${countText(entry.call.tokens.output)} 토큰`,
    state: stateText(MODEL_CALL_STATE_TEXT, entry.call.state)[0],
  }));
  const tools = view.toolCalls.map(entry => Object.freeze({
    toolId: entry.call.tool_id, attemptNo: entry.attemptNo,
    state: stateText(TOOL_CALL_STATE_TEXT, entry.call.state)[0],
  }));
  return Object.freeze({
    nodeId: view.nodeId, responsibility: view.node.responsibility, kind: view.node.kind,
    visitNo: view.visitNo, attemptNo: view.attemptNo, attempts: view.attempts.length,
    inputs: Object.freeze(inputs), models: Object.freeze(models), tools: Object.freeze(tools),
    error: view.error ? errorText(view.error) : null,
  });
}

// "시도 1 (실패)", "시도 2 (완료, 최신)"
export function attemptOptionText(attempt, latest) {
  const { label } = attemptOutcome(attempt);
  return `시도 ${attempt.attempt_no} (${label}${attempt === latest ? ', 최신' : ''})`;
}
