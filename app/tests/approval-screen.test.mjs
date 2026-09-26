// T066/T087: the observe page's approval screen over a fake document and a fake
// request. Pending gates and execution-bound asks are shown by their exact
// run/node/scope and execution/attempt/digest; a decision is the closed command of
// approvals.mjs posted through the owner routes; a retry attempt needs its own
// decision; a superseded decision authorizes nothing; the server is re-read after
// every decision and a refusal is shown by its code.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ERROR_MESSAGES, MESSAGES, STATE_LABELS, createApprovalScreen, foldText, isRetryAttempt,
} from '../static/approval-screen.mjs';

process.env.TZ = 'Asia/Seoul';
import { executionRequestsView } from '../static/approvals.mjs';

const HEX = '2'.repeat(32);
const BASE = `/${HEX}/`;
const RUN = '00000000-0000-4000-8000-00000000c0c1';
const EXEC = '00000000-0000-4000-8000-00000000e0e1';
const OTHER = '00000000-0000-4000-8000-00000000e0e2';
const CMD = '77777777-7777-4777-8777-777777777777';
const DIGEST = 'ab'.repeat(32);

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.listeners = new Map();
    this.hidden = false;
    this.disabled = false;
    this._text = '';
  }

  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }

  set textContent(value) { this._text = String(value); this.children = []; }

  set innerHTML(_value) { throw new Error('markup is never written'); }

  append(...nodes) { this.children.push(...nodes); }

  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }

  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }

  async dispatch(type) { for (const listener of this.listeners.get(type) ?? []) await listener({}); }

  findAll(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.findAll(predicate, found);
    }
    return found;
  }
}

const document = { createElement: tag => new FakeElement(tag) };

function runReceipt({ awaiting = [['owner-gate', 'release-output']] } = {}) {
  return {
    command_id: '11111111-2222-4333-8444-555555555555', run_id: RUN,
    graph_ref: { kind: 'graph', id: '33333333-3333-4333-8333-333333333333', version: 1, sha256: 'c'.repeat(64) },
    graph_digest: 'd'.repeat(64), phase: awaiting.length ? 'awaiting_human' : 'running',
    outcome: { run_id: RUN, graph_digest: 'd'.repeat(64), completed_node_ids: [], execution_ids: [],
      result_refs: [], counters: {}, activations: [], awaiting_human: awaiting, approvals: [],
      pending_node_ids: awaiting.length ? [] : ['tool'], rejected_human: [] },
    links: { self: `/${HEX}/api/v1/runs/${RUN}`, approvals: `/${HEX}/api/v1/runs/${RUN}/approvals`,
      events: `/${HEX}/api/v1/events` },
    event_cursor: 'c', cancellation: { requested: false, attempts: [] },
  };
}

function ask(attempt, state, execution = EXEC) {
  return { run_id: RUN, node_id: 'tool-gate', approval_scope: 'tool-call', execution_id: execution,
    execution_node_id: 'tool', attempt_no: attempt, inputs_digest: attempt === 3 ? null : DIGEST, state,
    approval_ref: null };
}

function listing(requests) {
  return { run_id: RUN, requests, links: {} };
}

function gateReceipt(decision) {
  return { command_id: CMD, state: 'recorded', decision,
    approval_ref: { kind: 'action_approval', id: '88888888-8888-4888-8888-888888888888', version: 1, sha256: 'e'.repeat(64) },
    links: { self: `/${HEX}/api/v1/runs/${RUN}/approvals/owner-gate/release-output`, events: `/${HEX}/api/v1/events` } };
}

// the fake server answers by path, so concurrent reads never depend on their order
function screen(routes, { onDecided } = {}) {
  const root = new FakeElement('section');
  const asked = [];
  const request = async (path, options = {}) => {
    asked.push([path, options]);
    const key = `${options.method ?? 'GET'} ${path}`;
    const queue = routes[key];
    if (!queue?.length) throw Object.assign(new Error(`unexpected ${key}`), { code: 'not_found' });
    const reply = queue.length > 1 ? queue.shift() : queue[0];
    if (reply instanceof Error) throw reply;
    return structuredClone(reply);
  };
  const approvals = createApprovalScreen({ root, document, basePath: BASE, request, commandId: () => CMD, onDecided });
  return { root, asked, approvals };
}

const READ = `GET /${HEX}/api/v1/runs/${RUN}`;
const LIST = `GET /${HEX}/api/v1/runs/${RUN}/approvals/executions`;
const RECORD = `POST /${HEX}/api/v1/runs/${RUN}/approvals`;
const RECORD_V2 = `POST /${HEX}/api/v1/runs/${RUN}/approvals/executions`;
const buttons = root => root.findAll(el => el.tagName === 'BUTTON');
const items = (root, cls) => root.findAll(el => el.getAttribute('class') === cls)[0].children;

test('the screen refuses a bad mount and says it is idle before a run is chosen', async () => {
  assert.throws(() => createApprovalScreen({ root: null, document, request: async () => {}, commandId: () => CMD }));
  assert.throws(() => createApprovalScreen({ root: new FakeElement('s'), document, basePath: '/x/',
    request: async () => {}, commandId: () => CMD }));
  const { root, approvals } = screen({});
  assert.match(root.textContent, new RegExp(MESSAGES.idle));
  await assert.rejects(approvals.show('../x'));
});

test('pending gates and every execution ask are shown with their exact identities', async () => {
  const { root, approvals } = screen({ [READ]: [runReceipt()], [LIST]: [listing([
    ask(1, 'approved'), ask(2, 'pending'), ask(3, 'superseded', OTHER), ask(4, 'pending', OTHER)])] });
  await approvals.show(RUN);
  const [gate] = items(root, 'approval-gates');
  assert.equal(gate.getAttribute('data-node-id'), 'owner-gate');
  assert.match(gate.textContent, new RegExp(`실행 ${RUN} · 노드 owner-gate · 범위 release-output`));
  const rows = items(root, 'approval-executions');
  assert.deepEqual(rows.map(row => row.dataset?.state ?? row.getAttribute('data-state')),
    ['approved', 'pending', 'superseded', 'pending']);
  assert.match(rows[0].textContent, new RegExp(`실행 ${RUN} · tool-gate/tool-call: 실행 ${EXEC} \\(노드 tool\\) 시도 1 — 입력 sha256 ${DIGEST}`));
  assert.match(rows[0].textContent, new RegExp(MESSAGES.authorized));
  // the retry attempt of a decided execution is its own ask, with its own buttons
  assert.match(rows[1].textContent, new RegExp(MESSAGES.retry));
  assert.equal(rows[1].findAll(el => el.tagName === 'BUTTON').length, 2);
  assert.match(rows[2].textContent, /입력 digest 없음/);
  assert.ok(rows[2].textContent.includes(STATE_LABELS.superseded));
  assert.equal(rows[2].findAll(el => el.tagName === 'BUTTON').length, 0);
  // after a superseded decision the next attempt needs a new decision as well
  assert.match(rows[3].textContent, new RegExp(MESSAGES.retry));
  assert.match(root.textContent, /결정할 일 3개가 있습니다/);
});

test('isRetryAttempt looks only at earlier decided attempts of the same execution', () => {
  const view = executionRequestsView(listing([ask(1, 'pending'), ask(2, 'pending'), ask(1, 'rejected', OTHER),
    ask(2, 'pending', OTHER)]), BASE);
  assert.deepEqual(view.requests.map(entry => isRetryAttempt(view, entry)), [false, false, false, true]);
});

test('a gate decision is the closed command posted through the owner route, then everything is re-read', async () => {
  const decided = [];
  const { root, asked, approvals } = screen({
    [READ]: [runReceipt(), runReceipt({ awaiting: [] })], [LIST]: [listing([])], [RECORD]: [gateReceipt('approved')],
  }, { onDecided: runId => decided.push(runId) });
  await approvals.show(RUN);
  const approve = buttons(root).find(el => el.getAttribute('data-decision') === 'approved');
  assert.equal(approve.textContent, '승인: owner-gate/release-output');
  await approve.dispatch('click');
  const posted = asked.find(([path, options]) => `${options.method} ${path}` === RECORD);
  assert.deepEqual(posted[1].body, { command_id: CMD, node_id: 'owner-gate', approval_scope: 'release-output',
    decision: 'approved' });
  assert.equal(asked.filter(([path]) => `GET ${path}` === READ).length, 2);
  assert.deepEqual(decided, [RUN]);
  assert.equal(items(root, 'approval-gates').length, 0);
  assert.match(root.textContent, new RegExp(MESSAGES.gateRecorded));
});

test('an execution decision echoes the listed attempt verbatim', async () => {
  const { root, asked, approvals } = screen({
    [READ]: [runReceipt({ awaiting: [] })], [LIST]: [listing([ask(2, 'pending')]), listing([ask(2, 'rejected')])],
    [RECORD_V2]: [{ state: 'recorded' }],
  });
  await approvals.show(RUN);
  await buttons(root).find(el => el.getAttribute('data-decision') === 'rejected').dispatch('click');
  const posted = asked.find(([path, options]) => `${options.method} ${path}` === RECORD_V2);
  assert.deepEqual(posted[1].body, { command_id: CMD, node_id: 'tool-gate', approval_scope: 'tool-call',
    execution_id: EXEC, execution_node_id: 'tool', attempt_no: 2, inputs_digest: DIGEST, decision: 'rejected' });
  const [row] = items(root, 'approval-executions');
  assert.equal(row.getAttribute('data-state'), 'rejected');
  assert.match(row.textContent, new RegExp(MESSAGES.notAuthorized));
  assert.match(root.textContent, new RegExp(MESSAGES.attemptRecorded));
});

test('a refused decision is shown by its code beside the state read again', async () => {
  const conflict = Object.assign(new Error('x'), { code: 'conflict' });
  const decided = [];
  const { root, asked, approvals } = screen({
    [READ]: [runReceipt()], [LIST]: [listing([])], [RECORD]: [conflict],
  }, { onDecided: runId => decided.push(runId) });
  await approvals.show(RUN);
  await buttons(root).find(el => el.getAttribute('data-decision') === 'rejected').dispatch('click');
  const alert = root.findAll(el => el.getAttribute('role') === 'alert')[0];
  assert.equal(alert.hidden, false);
  assert.equal(alert.dataset.code, 'conflict');
  assert.equal(alert.textContent, ERROR_MESSAGES.conflict);
  assert.equal(asked.filter(([path]) => `GET ${path}` === READ).length, 2);
  assert.deepEqual(decided, []);
});

test('a read refusal leaves nothing to decide on screen', async () => {
  const { root, approvals } = screen({ [READ]: [Object.assign(new Error('x'), { code: 'unavailable' })],
    [LIST]: [Object.assign(new Error('x'), { code: 'unavailable' })] });
  await assert.rejects(approvals.show(RUN));
  assert.equal(buttons(root).filter(el => el.getAttribute('data-decision')).length, 0);
  assert.match(root.textContent, new RegExp(ERROR_MESSAGES.unavailable));
});

test('a refused execution listing never hides the gate that can still be decided', async () => {
  const { root, approvals } = screen({ [READ]: [runReceipt()],
    [LIST]: [Object.assign(new Error('x'), { code: 'unavailable' })] });
  await assert.rejects(approvals.show(RUN));
  assert.equal(items(root, 'approval-gates').length, 1);
  assert.equal(items(root, 'approval-executions').length, 0);
  assert.match(root.textContent, /일부 요청은 읽지 못했습니다/);
});

// T087 expiry slice (2026-09-25): an expired ask is listed as expired, offers no
// decision, says the attempt is not authorized, and every ask shows its server-set time
test('an expired ask offers no decision and every ask shows its server-set time limit', async () => {
  const expires = Date.UTC(2026, 8, 25, 12, 30, 5);
  const { root, approvals } = screen({ [READ]: [runReceipt({ awaiting: [] })], [LIST]: [listing([
    { ...ask(1, 'expired'), expires_at_ms: expires }, { ...ask(2, 'pending'), expires_at_ms: expires }])] });
  await approvals.show(RUN);
  const rows = items(root, 'approval-executions');
  assert.equal(rows[0].getAttribute('data-state'), 'expired');
  assert.ok(rows[0].textContent.includes(STATE_LABELS.expired));
  assert.equal(rows[0].findAll(el => el.tagName === 'BUTTON').length, 0);
  assert.match(rows[0].textContent, new RegExp(MESSAGES.notAuthorized));
  // the local time of this device (Asia/Seoul here), never a bare UTC stamp (UI phase 4)
  assert.match(rows[0].textContent, /시한 2026-09-25 21:30:05/);
  assert.doesNotMatch(rows[0].textContent, /UTC/);
  // the attempt after an expired one is its own ask and needs a new decision
  assert.match(rows[1].textContent, new RegExp(MESSAGES.retry));
  assert.equal(rows[1].findAll(el => el.tagName === 'BUTTON').length, 2);
  assert.match(root.textContent, /결정할 일 1개가 있습니다/);
});

// UI phase 4: nothing to decide folds the card to one line; the records stay one click away
test('with nothing pending the card is one line that opens the records; a pending ask keeps it open', async () => {
  assert.equal(foldText(2), '이 실행의 승인 기록 2건 · 보기');
  assert.equal(foldText(0), '이 실행에는 결정할 승인이 없습니다');
  const { root, approvals } = screen({ [READ]: [runReceipt({ awaiting: [] })],
    [LIST]: [listing([ask(1, 'approved'), ask(2, 'approved')])] });
  await approvals.show(RUN);
  const fold = root.findAll(el => el.getAttribute('class') === 'approval-fold')[0];
  const body = root.findAll(el => el.getAttribute('class') === 'approval-body')[0];
  assert.equal(fold.hidden, false);
  assert.equal(fold.textContent, '이 실행의 승인 기록 2건 · 보기');
  assert.equal(body.hidden, true);
  assert.equal(root.dataset.folded, 'true');
  assert.equal(fold.getAttribute('aria-expanded'), 'false');
  await fold.dispatch('click');
  assert.equal(body.hidden, false);
  assert.equal(fold.getAttribute('aria-expanded'), 'true');
  // the records are all there, unchanged: two decided attempts, authorized
  assert.equal(items(root, 'approval-executions').length, 2);
  const pending = screen({ [READ]: [runReceipt()], [LIST]: [listing([])] });
  await pending.approvals.show(RUN);
  const open = pending.root.findAll(el => el.getAttribute('class') === 'approval-fold')[0];
  assert.equal(open.hidden, true);
  assert.equal(pending.root.findAll(el => el.getAttribute('class') === 'approval-body')[0].hidden, false);
  assert.match(pending.root.textContent, /결정할 일 1개가 있습니다/);
});
