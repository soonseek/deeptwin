// T066/T087/UX-AC06 (DOM half): the owner's approval screen on the observe page.
// For the selected run it shows, from what the server recorded:
//   - every pending human gate (v1 run approval) of the run's own read, by its
//     exact run, node and scope, with approve / reject;
//   - every execution-bound (v2) ask the ledger lists at
//     GET {base}api/v1/runs/{run}/approvals/executions, by its exact run, node,
//     execution, executing node, attempt and inputs digest (approvals.mjs
//     executionApprovalPrompt). A pending ask has approve / reject; a retry
//     attempt of an execution that was decided before is its own pending ask and
//     says it needs a new decision; a superseded decision says it authorizes
//     nothing; a decided one says whether that exact attempt is authorized
//     (approvals.mjs attemptAuthorized).
// Every decision is posted through the existing owner routes by the injected
// request (the supported session client adds the CSRF header), built only by
// approvals.mjs (approvalCommand / executionApprovalCommand) with one fresh
// command id; the screen never decides anything itself and always re-reads the
// server after a decision. Server text reaches the DOM through textContent only.

import {
  DECISIONS, approvalCommand, approvalRoutes, attemptAuthorized, awaitingHumanView,
  executionApprovalCommand, executionApprovalPrompt, executionApprovalRoutes, executionRequestsView,
  receiptSummary,
} from './approvals.mjs';
import { runRoutes, runView } from './runtime.mjs';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export const DECISION_LABELS = Object.freeze({ approved: '승인', rejected: '거절' });

export const STATE_LABELS = Object.freeze({
  pending: '결정 대기',
  approved: '승인됨',
  rejected: '거절됨',
  superseded: '대체됨 — 소유자 복구 이전의 결정이라 아무것도 허가하지 않습니다',
  expired: '만료됨 — 요청 시한이 지나 이 시도는 허가되지 않으며 다시 결정할 수 없습니다',
});

// the ask's server-set expiry as the owner reads it (UTC, to the second)
export function expiryText(expiresAtMs) {
  if (expiresAtMs === null || expiresAtMs === undefined) return '';
  return ` · 시한 ${new Date(expiresAtMs).toISOString().slice(0, 19).replace('T', ' ')} UTC`;
}

export const MESSAGES = Object.freeze({
  idle: '실행을 선택하면 승인할 일을 보여 줍니다.',
  loading: '승인할 일을 확인하는 중…',
  none: '이 실행에는 지금 승인할 일이 없습니다.',
  retry: '재시도 시도 — 이전 시도의 결정은 이 시도에 적용되지 않으므로 새 결정이 필요합니다.',
  sending: '결정을 기록하는 중…',
  gateRecorded: '결정을 기록했습니다. 실행을 이어서 진행하는 것은 실행 명령에서 따로 합니다.',
  attemptRecorded: '이 시도에 대한 결정을 기록했습니다.',
  authorized: '이 시도는 승인되어 실행이 허가되었습니다.',
  notAuthorized: '이 시도는 허가되지 않았습니다.',
});

export const ERROR_MESSAGES = Object.freeze({
  invalid_input: '요청 형식이 맞지 않습니다.',
  unauthenticated: '브라우저 세션이 없습니다. 세션을 다시 연결해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다. 화면을 새로고침한 뒤 다시 시도해 주세요.',
  not_found: '해당 실행이나 승인 요청을 찾지 못했습니다.',
  conflict: '이미 다른 결정이 기록되었거나 지금은 결정할 수 없습니다. 아래는 다시 읽은 최신 상태입니다.',
  superseded: '이 결정은 소유자 복구 이전의 것이라 대체되었습니다.',
  too_large: '요청이 허용 크기를 넘었습니다.',
  unavailable: '서버가 요청을 처리하지 못했습니다. 아래는 다시 읽은 최신 상태입니다.',
});

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

// a pending ask whose execution already has a decided (or superseded) earlier attempt
export function isRetryAttempt(view, entry) {
  return entry.state === 'pending' && view.requests.some(other => other !== entry
    && other.executionId === entry.executionId && other.nodeId === entry.nodeId
    && other.scope === entry.scope && other.attemptNo < entry.attemptNo && other.state !== 'pending');
}

export function createApprovalScreen({ root, document, basePath = '/', request, commandId, onDecided } = {}) {
  if (typeof root !== 'object' || root === null || typeof root.replaceChildren !== 'function') fail('a root is required');
  if (typeof document !== 'object' || document === null || typeof document.createElement !== 'function') {
    fail('a document is required');
  }
  if (typeof request !== 'function') fail('an injected request function is required');
  if (typeof commandId !== 'function') fail('a command id source is required');
  const runs = runRoutes(basePath); // refuse a bad base before anything is built

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', MESSAGES.idle, { role: 'status', 'aria-live': 'polite' });
  status.dataset.state = 'idle';
  const alert = element('p', '', { role: 'alert' });
  alert.hidden = true;
  const gates = element('ul', undefined, { class: 'approval-gates', 'aria-label': '사람 승인 대기 (게이트)' });
  const attempts = element('ul', undefined, { class: 'approval-executions', 'aria-label': '실행별 승인 요청' });
  const refresh = element('button', '승인 요청 다시 읽기', { type: 'button' });
  refresh.disabled = true;
  root.replaceChildren(element('h2', '승인'), status, alert, element('h3', '게이트 승인'), gates,
    element('h3', '실행 시도 승인'), attempts, refresh);

  let current = null; // run id shown
  let generation = 0;
  let busy = false;

  function say(text, state) {
    status.textContent = text;
    status.dataset.state = state;
  }

  function refused(error) {
    const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
    alert.hidden = false;
    alert.dataset.code = code;
    alert.textContent = ERROR_MESSAGES[code];
  }

  function clearAlert() {
    alert.hidden = true;
    alert.dataset.code = '';
    alert.textContent = '';
  }

  function decisionButtons(label, act) {
    return DECISIONS.map(decision => {
      const button = element('button', `${DECISION_LABELS[decision]}: ${label}`, { type: 'button',
        'data-decision': decision });
      button.addEventListener('click', () => act(decision).catch(() => {}));
      return button;
    });
  }

  function drawGates(runId, view) {
    const pending = awaitingHumanView({ run_id: runId, awaiting_human: view.awaiting.map(gate => [gate.nodeId, gate.scope]),
      completed_node_ids: [] }, basePath);
    gates.replaceChildren(...pending.gates.map(gate => {
      const item = element('li', undefined, { 'data-node-id': gate.nodeId, 'data-scope': gate.scope });
      const text = `실행 ${runId} · 노드 ${gate.nodeId} · 범위 ${gate.scope}`;
      item.append(element('span', text, { class: 'approval-subject' }),
        ...decisionButtons(`${gate.nodeId}/${gate.scope}`, decision => decideGate(runId, gate, decision)));
      return item;
    }));
    return pending.gates.length;
  }

  function drawAttempts(listing) {
    attempts.replaceChildren(...listing.requests.map(entry => {
      const item = element('li', undefined, { 'data-state': entry.state, 'data-attempt': String(entry.attemptNo),
        'data-execution-id': entry.executionId });
      item.append(element('span', `실행 ${entry.runId} · ${executionApprovalPrompt(entry)}`, { class: 'approval-subject' }),
        element('span', ` · ${STATE_LABELS[entry.state]}`, { class: 'approval-state' }),
        element('span', expiryText(entry.expiresAtMs), { class: 'approval-expiry' }));
      if (entry.state === 'pending') {
        if (isRetryAttempt(listing, entry)) item.append(element('p', MESSAGES.retry, { class: 'approval-retry' }));
        item.append(...decisionButtons(`시도 ${entry.attemptNo}`, decision => decideAttempt(entry, decision)));
      } else if (entry.state !== 'superseded') {
        const ok = attemptAuthorized(listing, entry);
        item.append(element('p', ok ? MESSAGES.authorized : MESSAGES.notAuthorized,
          { class: 'approval-authorized', 'data-authorized': String(ok) }));
      }
      return item;
    }));
    return listing.pending.length;
  }

  async function show(runId, { keepAlert = false } = {}) {
    if (typeof runId !== 'string' || !UUID.test(runId)) fail('run id is not a canonical UUID');
    const mine = ++generation;
    current = runId;
    refresh.disabled = true;
    if (!keepAlert) clearAlert();
    say(MESSAGES.loading, 'loading');
    // the two surfaces are read side by side; a refusal of one never hides the other
    const [gateRead, attemptRead] = await Promise.allSettled([
      request(runs.read(runId)).then(receipt => runView(receipt, basePath)),
      request(executionApprovalRoutes(runId, basePath).list).then(listed => executionRequestsView(listed, basePath)),
    ]);
    if (mine !== generation) return null;
    refresh.disabled = false;
    let open = 0;
    if (gateRead.status === 'fulfilled') open += drawGates(runId, gateRead.value);
    else gates.replaceChildren();
    if (attemptRead.status === 'fulfilled') open += drawAttempts(attemptRead.value);
    else attempts.replaceChildren();
    const failed = [gateRead, attemptRead].find(result => result.status === 'rejected');
    if (failed) {
      refused(failed.reason);
      say(open ? `결정할 일 ${open}개가 있습니다. 일부 요청은 읽지 못했습니다.` : MESSAGES.idle, 'unavailable');
      throw failed.reason;
    }
    say(open ? `결정할 일 ${open}개가 있습니다.` : MESSAGES.none, open ? 'pending' : 'none');
    return Object.freeze({ gates: gateRead.value.awaiting, listing: attemptRead.value });
  }

  async function decide(runId, send, recorded) {
    if (busy || current !== runId) return null;
    busy = true;
    clearAlert();
    say(MESSAGES.sending, 'sending');
    let value = null;
    try {
      value = await send();
      say(recorded, 'recorded');
    } catch (error) {
      refused(error);
    } finally {
      busy = false;
    }
    // the server has the last word: read it again, keeping any refusal on screen
    try {
      await show(runId, { keepAlert: value === null });
      if (value !== null) say(recorded, 'recorded');
    } catch {
      // the read's own refusal is on screen
    }
    if (value !== null && typeof onDecided === 'function') {
      try { await onDecided(runId); } catch { /* the panel shows its own refusal */ }
    }
    return value;
  }

  function decideGate(runId, gate, decision) {
    return decide(runId, async () => {
      const id = commandId();
      const body = approvalCommand({ commandId: id, nodeId: gate.nodeId, approvalScope: gate.scope, decision });
      // only a recorded receipt for this exact run/node/scope counts
      const summary = receiptSummary(await request(approvalRoutes(runId, basePath).record, { method: 'POST', body }));
      if (summary.runId !== runId || summary.nodeId !== gate.nodeId || summary.scope !== gate.scope
          || summary.decision !== decision) fail('the receipt is not for this gate', 'unavailable');
      return summary;
    }, MESSAGES.gateRecorded);
  }

  function decideAttempt(entry, decision) {
    return decide(entry.runId, async () => {
      const body = executionApprovalCommand(entry, { commandId: commandId(), decision });
      return request(executionApprovalRoutes(entry.runId, basePath).record, { method: 'POST', body });
    }, MESSAGES.attemptRecorded);
  }

  refresh.addEventListener('click', () => {
    if (current !== null) show(current).catch(() => {});
  });

  return Object.freeze({ show, get runId() { return current; } });
}
