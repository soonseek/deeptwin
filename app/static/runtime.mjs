// T048 (logic half): the run observation GUI over the fixed runs-v1 routes
// (POST {base}api/v1/runs, GET .../{run}, POST .../{run}/resume).
// Pure logic only: route builders that honour the deployment base path and
// refuse path injection, the closed create/resume commands mirrored from
// app/api/runs.py, an honest view of the server's run receipt, accessible
// text rows, and an observer over an injected request. The GUI never
// decides a phase itself: the server derives it from the durable head, and
// this module only refuses a receipt that contradicts that rule (a waiting
// or pending run is never shown complete; a result is never attached to a
// node or visit that did not produce it). Only the projection's allowlisted
// identities, references and counters are consumed — never raw graph state.
//
// Vocabulary (experience.md §7): a "visit" (수행) is one recorded execution
// of a node — a loop's iterations are distinct visits with their own
// results. Failed retries (시도) reuse the execution and are not in this
// receipt; they come from the ledger's attempt records, not from here.
// The node universe is what the run has touched unless the caller supplies
// the graph's node ids (`nodeIds`), which makes never-visited nodes visible.

export const PHASES = Object.freeze(['created', 'running', 'awaiting_human', 'rejected', 'cancelled', 'completed']);
// experience.md §9/§12: the state is named in text, never by colour alone
export const PHASE_LABELS = Object.freeze({
  created: '시작 전',
  running: '실행 중',
  awaiting_human: '사람 대기',
  rejected: '거절됨',
  cancelled: '취소됨',
  completed: '완료',
});
export const NODE_STATES = Object.freeze(['completed', 'pending', 'awaiting_human', 'rejected', 'not_visited']);
export const NODE_STATE_LABELS = Object.freeze({
  completed: '완료',
  pending: '수행 예정',
  awaiting_human: '사람 대기',
  rejected: '거절됨',
  not_visited: '미수행',
});
// the create command's named inputs and their exact record kinds (app/services/runs.py)
export const INPUT_KINDS = Object.freeze({
  graph_ref: 'graph',
  work_revision_ref: 'work_revision',
  environment_ref: 'environment',
  consent_ref: 'run_consent',
  budget_policy_ref: 'budget_policy',
});
// the closed error partition of the run routes (app/api/runs.py)
export const ERROR_CODES = Object.freeze(['invalid_input', 'unauthenticated', 'access_denied', 'not_found',
  'conflict', 'too_large', 'unavailable']);
const CODE_BY_STATUS = Object.freeze({
  400: 'invalid_input', 401: 'unauthenticated', 403: 'access_denied', 404: 'not_found',
  409: 'conflict', 413: 'too_large', 503: 'unavailable',
});

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const LOCAL = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/;
const SHA256 = /^[0-9a-f]{64}$/;
// the deployment base path is "/" (portable) or "/<32 hex>/" (local profile)
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
const REF_FIELDS = ['kind', 'id', 'version', 'sha256'];
const COMMAND_FIELDS = Object.freeze({
  commandId: 'command_id',
  graphRef: 'graph_ref',
  workRevisionRef: 'work_revision_ref',
  environmentRef: 'environment_ref',
  consentRef: 'consent_ref',
  budgetPolicyRef: 'budget_policy_ref',
});

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

function requireUuid(value, label) {
  if (typeof value !== 'string' || !UUID.test(value)) fail(`${label} is not a canonical UUID`);
  return value;
}

function requireLocal(value, label) {
  if (typeof value !== 'string' || !LOCAL.test(value)) fail(`${label} is not a local identifier`);
  return value;
}

function requireBase(value) {
  if (typeof value !== 'string' || !BASE_PATH.test(value)) fail('base path is not a deployment base path');
  return value.slice(0, -1); // "" or "/<32 hex>"
}

function requireRef(value, label, kind = null) {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) fail(`${label} must be a reference`);
  const names = Object.keys(value).sort();
  if (names.join(',') !== [...REF_FIELDS].sort().join(',')) fail(`${label} must carry exactly kind, id, version, sha256`);
  if (typeof value.kind !== 'string' || !LOCAL.test(value.kind)) fail(`${label} kind is not an identifier`);
  if (kind !== null && value.kind !== kind) fail(`${label} must reference a ${kind}`);
  requireUuid(value.id, `${label} id`);
  if (!Number.isInteger(value.version) || value.version < 1) fail(`${label} version is not positive`);
  if (typeof value.sha256 !== 'string' || !SHA256.test(value.sha256)) fail(`${label} digest is not sha256`);
  return Object.freeze({ kind: value.kind, id: value.id, version: value.version, sha256: value.sha256 });
}

export function runRoutes(basePath = '/') {
  const prefix = requireBase(basePath);
  const create = `${prefix}/api/v1/runs`;
  return Object.freeze({
    create,
    read(runId) {
      return `${create}/${requireUuid(runId, 'run id')}`;
    },
    resume(runId) {
      return `${create}/${requireUuid(runId, 'run id')}/resume`;
    },
    cancel(runId) {
      return `${create}/${requireUuid(runId, 'run id')}/cancel`;
    },
    recover(runId) {
      return `${create}/${requireUuid(runId, 'run id')}/recover`;
    },
  });
}

export function runCommand(fields) {
  if (typeof fields !== 'object' || fields === null) fail('command must be an object');
  for (const name of Object.keys(fields)) {
    if (!(name in COMMAND_FIELDS)) fail(`unexpected command field ${name}`);
  }
  const command = { command_id: requireUuid(fields.commandId, 'command id') };
  for (const [name, wire] of Object.entries(COMMAND_FIELDS)) {
    if (wire === 'command_id') continue;
    command[wire] = requireRef(fields[name], wire, INPUT_KINDS[wire]);
  }
  return command;
}

// the closed `{command_id}` body shared by resume, cancel and recover
export function commandBody(fields) {
  if (typeof fields !== 'object' || fields === null) fail('command must be an object');
  for (const name of Object.keys(fields)) {
    if (name !== 'commandId') fail(`unexpected command field ${name}`);
  }
  return { command_id: requireUuid(fields.commandId, 'command id') };
}

export const resumeCommand = commandBody;

function pairs(value, label) {
  if (!Array.isArray(value)) fail(`${label} must be a list`);
  return value.map(entry => {
    if (!Array.isArray(entry) || entry.length !== 2) fail(`${label} entries are (node, scope) pairs`);
    return Object.freeze({ nodeId: requireLocal(entry[0], 'node id'), scope: requireLocal(entry[1], 'approval scope') });
  });
}

function identifiers(value, label) {
  if (!Array.isArray(value)) fail(`${label} must be a list`);
  return value.map(item => requireLocal(item, `${label} entry`));
}

function scopesByNode(list) {
  const map = new Map();
  for (const { nodeId, scope } of list) map.set(nodeId, [...(map.get(nodeId) ?? []), scope]);
  return map;
}

// The phase is the server's (app/services/runs.py `_phase`); the receipt is
// refused when its own identities contradict it (대기를 완료 처리 금지).
function checkPhase(phase, { cancelled, awaiting, rejected, pending, visited }) {
  const expected = cancelled ? 'cancelled'
    : awaiting.length ? 'awaiting_human'
      : rejected.length ? 'rejected'
        : pending.length ? 'running'
          : visited ? 'completed' : 'created';
  if (phase !== expected) {
    fail(phase === 'completed' ? 'a waiting run cannot be complete' : `a ${expected} run cannot be ${phase}`);
  }
}

// The honest view of one server receipt: the phase the server derived, the
// nodes with states taken only from the projection's identities, one row per
// recorded visit carrying only its own result reference, the sealed router
// activations (the "실제 전달" lines) and the consumed approval references.
export function runView(receipt, basePath = '/', { nodeIds = null } = {}) {
  if (typeof receipt !== 'object' || receipt === null) fail('receipt must be an object');
  const routes = runRoutes(basePath);
  const runId = requireUuid(receipt.run_id, 'run id');
  const commandId = requireUuid(receipt.command_id, 'command id');
  if (!PHASES.includes(receipt.phase)) fail('phase is outside the closed set');
  const phase = receipt.phase;
  if (typeof receipt.graph_digest !== 'string' || !SHA256.test(receipt.graph_digest)) fail('graph digest is not sha256');
  const graphRef = requireRef(receipt.graph_ref, 'graph ref', 'graph');
  const links = receipt.links;
  if (typeof links !== 'object' || links === null) fail('receipt must carry links');
  if (links.self !== routes.read(runId)) fail('receipt self link must be the fixed read route');
  if (typeof links.approvals !== 'string' || typeof links.events !== 'string') fail('receipt must link approvals and events');
  if (typeof receipt.event_cursor !== 'string' || receipt.event_cursor === '') fail('receipt must carry an event cursor');
  const outcome = receipt.outcome;
  if (typeof outcome !== 'object' || outcome === null) fail('outcome must be an object');
  if (outcome.run_id !== runId) fail('outcome run id must match the receipt');
  if (outcome.graph_digest !== receipt.graph_digest) fail('outcome graph digest must match the receipt');
  const completed = identifiers(outcome.completed_node_ids, 'completed node ids');
  const pending = identifiers(outcome.pending_node_ids, 'pending node ids');
  const awaiting = pairs(outcome.awaiting_human, 'awaiting_human');
  const rejected = pairs(outcome.rejected_human, 'rejected_human');
  const counters = outcome.counters;
  if (typeof counters !== 'object' || counters === null || Array.isArray(counters)) fail('counters must be a map');
  for (const [nodeId, count] of Object.entries(counters)) {
    requireLocal(nodeId, 'counter node id');
    if (!Number.isInteger(count) || count < 0) fail('a visit counter is a nonnegative integer');
  }
  if (!Array.isArray(outcome.execution_ids)) fail('execution ids must be a list');
  if (!Array.isArray(outcome.result_refs)) fail('result refs must be a list');
  if (!Array.isArray(outcome.activations)) fail('activations must be a list');
  if (!Array.isArray(outcome.approvals)) fail('approvals must be a list');
  const visited = Object.values(counters).some(count => count > 0);
  // experience.md §9: new dispatch closed and each call's termination are two facts
  const cancellation = receipt.cancellation;
  if (typeof cancellation !== 'object' || cancellation === null || typeof cancellation.requested !== 'boolean'
      || !Array.isArray(cancellation.attempts)) fail('receipt must carry its cancellation facts');
  const attempts = cancellation.attempts.map(entry => {
    if (typeof entry !== 'object' || entry === null) fail('cancellation attempts are objects');
    for (const name of ['phase', 'cancel_state', 'dispatch_gate', 'remote_terminal_observed']) {
      if (typeof entry[name] !== 'string') fail(`cancellation attempt ${name} is not a string`);
    }
    if (!Number.isInteger(entry.attempt_no) || entry.attempt_no < 1) fail('cancellation attempt number is not positive');
    return Object.freeze({
      attemptId: requireUuid(entry.attempt_id, 'attempt id'),
      executionId: requireUuid(entry.execution_id, 'execution id'),
      attemptNo: entry.attempt_no,
      phase: entry.phase, cancelState: entry.cancel_state, dispatchGate: entry.dispatch_gate,
      remoteTerminalObserved: entry.remote_terminal_observed,
    });
  });
  if (cancellation.requested && awaiting.length) fail('a cancelled run waits on nobody');
  checkPhase(phase, { cancelled: cancellation.requested, awaiting, rejected, pending, visited });
  const complete = phase === 'completed';

  const resultByExecution = new Map();
  for (const entry of outcome.result_refs) {
    if (!Array.isArray(entry) || entry.length !== 2) fail('result refs are (execution, ref) pairs');
    const [executionId, ref] = entry;
    if (typeof executionId !== 'string' || executionId === '') fail('result execution id is not a string');
    if (resultByExecution.has(executionId)) fail('an execution has at most one result');
    resultByExecution.set(executionId, requireRef(ref, 'result ref'));
  }
  const visits = [];
  const indexByNode = new Map();
  const seenExecutions = new Set();
  for (const entry of outcome.execution_ids) {
    if (!Array.isArray(entry) || entry.length !== 2) fail('execution ids are (node, execution) pairs');
    const [nodeId, executionId] = entry;
    requireLocal(nodeId, 'execution node id');
    if (typeof executionId !== 'string' || executionId === '' || seenExecutions.has(executionId)) {
      fail('execution ids are distinct strings');
    }
    seenExecutions.add(executionId);
    const loopIndex = indexByNode.get(nodeId) ?? 0;
    indexByNode.set(nodeId, loopIndex + 1);
    visits.push(Object.freeze({
      nodeId, executionId, loopIndex, resultRef: resultByExecution.get(executionId) ?? null,
    }));
  }
  for (const executionId of resultByExecution.keys()) {
    if (!seenExecutions.has(executionId)) fail('a result must belong to a recorded execution');
  }
  // the server lists one execution per counted visit that produced a result:
  // a visited node records every result or none, never a gap
  for (const [nodeId, count] of indexByNode) {
    if (count !== (counters[nodeId] ?? 0)) fail('a visited node records every result or none');
  }

  const routesTaken = outcome.activations.map(entry => {
    if (!Array.isArray(entry) || entry.length !== 3 || !Array.isArray(entry[2])) fail('activations are (router, activation, targets)');
    const [routerId, activationId, targets] = entry;
    if (typeof activationId !== 'string' || activationId === '') fail('activation id is not a string');
    return Object.freeze({
      routerId: requireLocal(routerId, 'router id'), activationId,
      targets: Object.freeze(targets.map(target => requireLocal(target, 'activation target'))),
    });
  });
  const approvalRefsByNode = new Map();
  for (const entry of outcome.approvals) {
    if (!Array.isArray(entry) || entry.length !== 2 || !Array.isArray(entry[1])) fail('approvals are (node, refs) pairs');
    const [nodeId, refs] = entry;
    approvalRefsByNode.set(requireLocal(nodeId, 'approval node id'),
      Object.freeze(refs.map(ref => requireRef(ref, 'approval ref', 'action_approval'))));
  }

  const awaitingScopes = scopesByNode(awaiting);
  const rejectedScopes = scopesByNode(rejected);
  const touched = new Set([...Object.keys(counters), ...completed, ...pending,
    ...awaitingScopes.keys(), ...rejectedScopes.keys(), ...visits.map(row => row.nodeId),
    ...routesTaken.flatMap(route => [route.routerId, ...route.targets]), ...approvalRefsByNode.keys()]);
  let universe = touched;
  if (nodeIds !== null) {
    universe = new Set(identifiers(nodeIds, 'node ids'));
    for (const nodeId of touched) {
      if (!universe.has(nodeId)) fail('the receipt names a node outside the graph');
    }
  }
  const completedSet = new Set(completed);
  const pendingSet = new Set(pending);
  const nodes = [...universe].sort().map(nodeId => {
    const count = counters[nodeId] ?? 0;
    if (completedSet.has(nodeId) && count === 0) fail('a completed node must have a recorded visit');
    let state = 'not_visited';
    if (awaitingScopes.has(nodeId)) state = 'awaiting_human';
    else if (rejectedScopes.has(nodeId)) state = 'rejected';
    else if (pendingSet.has(nodeId)) state = 'pending';
    else if (completedSet.has(nodeId)) state = 'completed';
    // the aggregate over every visit of this node; each visit row keeps its own
    const resultRefs = visits.filter(row => row.nodeId === nodeId && row.resultRef !== null)
      .map(row => row.resultRef);
    return Object.freeze({
      nodeId, state, stateLabel: NODE_STATE_LABELS[state], visits: count,
      awaitingScopes: Object.freeze(awaitingScopes.get(nodeId) ?? []),
      rejectedScopes: Object.freeze(rejectedScopes.get(nodeId) ?? []),
      resultRefs: Object.freeze(resultRefs),
      approvalRefs: approvalRefsByNode.get(nodeId) ?? Object.freeze([]),
    });
  });

  return Object.freeze({
    runId,
    commandId,
    phase,
    phaseLabel: PHASE_LABELS[phase],
    graphDigest: receipt.graph_digest,
    graphRef,
    complete,
    nodes: Object.freeze(nodes),
    visits: Object.freeze(visits),
    routes: Object.freeze(routesTaken),
    awaiting: Object.freeze(awaiting),
    rejected: Object.freeze(rejected),
    cancellation: Object.freeze({ requested: cancellation.requested, attempts: Object.freeze(attempts) }),
    approvalsPath: links.approvals,
    eventsPath: links.events,
    eventCursor: receipt.event_cursor,
  });
}

// experience.md §12: one accessible text row per node reading the same
// relation as the graph; the state is spelled out, never colour alone.
export function accessibleRows(view) {
  if (typeof view !== 'object' || view === null || !Array.isArray(view.nodes)) fail('view must be a run view');
  const rows = [];
  // experience.md §9 row 294: new dispatch closed and each call's termination, separately
  if (view.cancellation?.requested) rows.push('취소 요청됨: 새 dispatch 중단');
  // experience.md §7 / UX-AC04: every past attempt stays a distinct row, cancelled or not
  for (const call of view.cancellation?.attempts ?? []) {
    const gate = call.dispatchGate === 'closed' ? '게이트 닫힘' : '게이트 열림';
    const remote = call.remoteTerminalObserved === 'not_observed' ? '원격 종료 미확인' : `원격 종료 확인됨 (${call.remoteTerminalObserved})`;
    rows.push(`시도 ${call.attemptNo} 호출 ${call.attemptId}: ${gate}, ${remote}`);
  }
  return rows.concat(view.nodes.map(node => {
    const parts = [`${node.nodeId}: ${node.stateLabel}`, `수행 ${node.visits}회`, `산출물 ${node.resultRefs.length}건`];
    if (node.awaitingScopes.length) parts.push(`대기 근거: ${node.awaitingScopes.join(', ')}`);
    if (node.rejectedScopes.length) parts.push(`거절: ${node.rejectedScopes.join(', ')}`);
    if (node.approvalRefs.length) parts.push(`승인 기록 ${node.approvalRefs.length}건`);
    return parts.join(', ');
  }));
}

function viewKey(view) {
  return JSON.stringify(view);
}

// The observer talks to the server only through the injected request. The
// DOM half's adapter must preserve the error envelope's `code` (or at least
// the HTTP `status`) on thrown errors and send `X-DeepTwin-CSRF` on POSTs
// (app.mjs's `api` helper does; its CSRF source and root-absolute paths are
// still the preview's, so it is not this module's caller yet). Reads never
// post; a reply becomes the view only when runView accepts it; exchanges are
// ordered by generation so a late reply never replaces a newer view, and an
// unchanged view is not re-announced.
export function createRunObserver({ request, basePath = '/', onChange = () => {} } = {}) {
  if (typeof request !== 'function') fail('an injected request function is required');
  if (typeof onChange !== 'function') fail('onChange must be a function');
  const routes = runRoutes(basePath);
  let state = Object.freeze({ busy: false, view: null, error: null });
  let generation = 0;
  let inflight = 0;

  function publish(changes) {
    const merged = { ...state, ...changes };
    // an unchanged view keeps its reference so renderers see one announcement
    if (merged.view && state.view && merged.view !== state.view
        && viewKey(merged.view) === viewKey(state.view)) {
      merged.view = state.view;
    }
    const next = Object.freeze(merged);
    if (next.busy === state.busy && next.error === state.error && next.view === state.view) return;
    state = next;
    onChange(state);
  }

  function partition(error) {
    if (ERROR_CODES.includes(error?.code)) return error.code;
    return CODE_BY_STATUS[error?.status] ?? 'unavailable';
  }

  async function exchange(prepare) {
    const mine = ++generation;
    inflight += 1;
    let path = null;
    try {
      // inside the boundary: a throwing renderer must not leave the observer busy forever
      publish({ busy: true, error: null });
      const [target, options] = prepare();
      path = target;
      const view = runView(await request(target, options), basePath);
      inflight -= 1;
      if (mine === generation) publish({ busy: inflight > 0, view });
      else publish({ busy: inflight > 0 });
      return view;
    } catch (error) {
      inflight -= 1;
      const failure = Object.freeze({
        code: partition(error), message: String(error?.message ?? error), target: path,
      });
      // a superseded exchange never touches the view or the error the newer one owns
      if (mine !== generation) {
        publish({ busy: inflight > 0 });
        throw error;
      }
      // an error for another run never leaves the previous run on screen
      const sameRun = state.view !== null && path !== null
        && [routes.read, routes.resume, routes.cancel, routes.recover]
          .some(route => path === route(state.view.runId));
      publish({ busy: inflight > 0, error: failure, view: sameRun ? state.view : null });
      throw error;
    }
  }

  return Object.freeze({
    start(fields) {
      return exchange(() => [routes.create, { method: 'POST', body: runCommand(fields) }]);
    },
    read(runId) {
      return exchange(() => [routes.read(runId), {}]);
    },
    resume(runId, commandId) {
      return exchange(() => [routes.resume(runId), { method: 'POST', body: resumeCommand({ commandId }) }]);
    },
    cancel(runId, commandId) {
      return exchange(() => [routes.cancel(runId), { method: 'POST', body: commandBody({ commandId }) }]);
    },
    recover(runId, commandId) {
      return exchange(() => [routes.recover(runId), { method: 'POST', body: commandBody({ commandId }) }]);
    },
    snapshot() {
      return state;
    },
  });
}
