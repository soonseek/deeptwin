// T048 (DOM half): the run panel renders the observer's state into a DOM the
// caller owns — one status line, one accessible text row per node (the same
// rows runtime.mjs spells out, never colour alone), the closed error text,
// and three commands (resume / cancel / recover) that send one fresh command
// id each through the injected request. The panel never decides a phase: the
// controls are gated by the server-derived view, and a refused command is
// shown as the server's code. Tested over a minimal fake document (no
// browser on this host; T049's Playwright case stays open) and over the real
// session client + run observer so the DOM half is proven wired to the
// supported routes.

import test from 'node:test';
import assert from 'node:assert/strict';

import { ERROR_CODES, PHASES, PHASE_LABELS, accessibleRows, createRunObserver, runView } from '../static/runtime.mjs';
import { createSupportedSession } from '../static/session.mjs';
import { CONTROL_LABELS, ERROR_MESSAGES, controlsFor, createRunPanel } from '../static/run-panel.mjs';

const RUN_ID = '00000000-0000-4000-8000-00000000b0b1';
const COMMAND_ID = '11111111-2222-4333-8444-555555555555';
const HEX = '2'.repeat(32);
const BASE = `/${HEX}/`;

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.listeners = new Map();
    this.hidden = false;
    this.disabled = false;
    this.className = '';
    this.type = '';
    this._text = '';
  }

  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }

  set textContent(value) { this._text = String(value); this.children = []; }

  append(...nodes) { this.children.push(...nodes); }

  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }

  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }

  async click() { for (const listener of this.listeners.get('click') ?? []) await listener({ preventDefault() {} }); }

  find(predicate) {
    for (const child of this.children) {
      if (predicate(child)) return child;
      const found = child.find(predicate);
      if (found) return found;
    }
    return null;
  }

  all(predicate, into = []) {
    for (const child of this.children) {
      if (predicate(child)) into.push(child);
      child.all(predicate, into);
    }
    return into;
  }
}

const fakeDocument = { createElement: tag => new FakeElement(tag) };

function ref(kind, id = '33333333-3333-4333-8333-333333333333') {
  return { kind, id, version: 1, sha256: 'c'.repeat(64) };
}

function outcome(changes = {}) {
  return {
    run_id: RUN_ID, graph_digest: 'd'.repeat(64),
    completed_node_ids: ['intake', 'writer'], counters: { intake: 1, writer: 1 },
    execution_ids: [['intake', 'e-intake'], ['writer', 'e-writer']],
    result_refs: [['e-writer', ref('artifact', '66666666-6666-4666-8666-666666666666')]],
    activations: [], awaiting_human: [], approvals: [], pending_node_ids: [], rejected_human: [],
    ...changes,
  };
}

function receipt(changes = {}, base = '/') {
  const prefix = base.slice(0, -1);
  return {
    command_id: COMMAND_ID, run_id: RUN_ID, graph_ref: ref('graph'), graph_digest: 'd'.repeat(64),
    phase: 'awaiting_human',
    outcome: outcome({ awaiting_human: [['owner-gate', 'release-output']], pending_node_ids: ['owner-gate'] }),
    links: { self: `${prefix}/api/v1/runs/${RUN_ID}`, approvals: `${prefix}/api/v1/runs/${RUN_ID}/approvals`,
             events: `${prefix}/api/v1/events` },
    event_cursor: 'opaque-cursor', cancellation: { requested: false, attempts: [] }, ...changes,
  };
}

function completed(base = '/') {
  return receipt({ phase: 'completed', outcome: outcome() }, base);
}

function running(base = '/') {
  return receipt({ phase: 'running', outcome: outcome({ pending_node_ids: ['owner-gate'] }) }, base);
}

function jsonResponse(status, payload) {
  return { ok: status >= 200 && status < 300, status, async json() { return payload; } };
}

function mounted(script, { basePath = '/', commandIds = [COMMAND_ID] } = {}) {
  const calls = [];
  const root = new FakeElement('section');
  const ids = [...commandIds];
  const panel = createRunPanel({
    root, document: fakeDocument, basePath,
    request: async (path, options = {}) => {
      calls.push([path, options]);
      const step = script.shift();
      if (step instanceof Error) throw step;
      if (step === undefined) throw Object.assign(new Error('script exhausted'), { status: 404 });
      return step;
    },
    commandId: () => ids.shift(),
  });
  const button = name => root.find(el => el.tagName === 'BUTTON' && el.dataset.command === name);
  const rows = () => root.find(el => el.tagName === 'OL').children.map(li => li.textContent);
  const status = () => root.find(el => el.getAttribute('role') === 'status');
  const alert = () => root.find(el => el.getAttribute('role') === 'alert');
  return { panel, root, calls, button, rows, status, alert };
}

test('the controls are gated by the server-derived view, never by a phase the panel decides', () => {
  const view = phase => runView(receipt({ phase, outcome: outcome(
    phase === 'awaiting_human' ? { awaiting_human: [['owner-gate', 'release-output']], pending_node_ids: ['owner-gate'] }
      : phase === 'rejected' ? { rejected_human: [['owner-gate', 'release-output']], pending_node_ids: ['owner-gate'] }
        : phase === 'completed' ? {}
          : phase === 'created' ? { completed_node_ids: [], counters: {}, execution_ids: [], result_refs: [] }
            : { pending_node_ids: ['owner-gate'] }),
  cancellation: { requested: phase === 'cancelled', attempts: [] } }));
  const idle = view => controlsFor({ busy: false, view, error: null });
  assert.deepEqual(idle(null), { resume: false, cancel: false, recover: false });
  // review MUST: resume on a waiting gate is a server no-op; the head runs again on
  // `running` (an approved gate, a failed execution) and `created`; recover (one more
  // billed attempt) only on `running`, only by the owner's explicit choice
  assert.deepEqual(idle(view('awaiting_human')), { resume: false, cancel: true, recover: false });
  assert.deepEqual(idle(view('running')), { resume: true, cancel: true, recover: true });
  assert.deepEqual(idle(view('created')), { resume: true, cancel: true, recover: false });
  assert.deepEqual(idle(view('rejected')), { resume: false, cancel: true, recover: false });
  assert.deepEqual(idle(view('completed')), { resume: false, cancel: false, recover: false });
  assert.deepEqual(idle(view('cancelled')), { resume: false, cancel: false, recover: false });
  // nothing is sent while an exchange is in flight
  assert.deepEqual(controlsFor({ busy: true, view: view('awaiting_human'), error: null }),
    { resume: false, cancel: false, recover: false });
  assert.deepEqual(Object.keys(CONTROL_LABELS).sort(), ['cancel', 'recover', 'resume']);
  assert.deepEqual(Object.keys(PHASE_LABELS).sort(), [...PHASES].sort());
  assert.throws(() => controlsFor(null));
});

test('every closed error code has text the owner can act on, and none claims what the view cannot know', () => {
  assert.deepEqual(Object.keys(ERROR_MESSAGES).sort(), [...ERROR_CODES].sort());
  for (const message of Object.values(ERROR_MESSAGES)) assert.equal(typeof message === 'string' && message.length > 0, true);
  assert.equal(Object.isFrozen(ERROR_MESSAGES), true);
  // review MUST: a 503 may have run a node and recorded a stop; the text must not deny it
  assert.doesNotMatch(ERROR_MESSAGES.unavailable, /바뀌지 않|변경되지 않/);
  // a server 400 was sent; the text must not say it was not
  assert.doesNotMatch(ERROR_MESSAGES.invalid_input, /보내지 않/);
  // an absent or rotated token needs the session re-established, not a login
  assert.doesNotMatch(ERROR_MESSAGES.unauthenticated, /로그인/);
});

test('a running head is shown as unfinished, never as live work the view cannot see', async () => {
  // review SHOULD: the receipt carries no liveness; after a failed execution the head is
  // `running` with nothing live, so the status must not read 실행 중
  const { panel, status, root } = mounted([running()]);
  await panel.read(RUN_ID);
  assert.doesNotMatch(status().textContent, /실행 중/);
  assert.match(status().textContent, /미완료/);
  // the status reads the short id; the full id is one technical fold away
  assert.match(status().textContent, new RegExp(`실행 ${RUN_ID.slice(0, 8)}$`));
  const fold = root.find(el => el.tagName === 'DETAILS');
  assert.equal(fold.hidden, false);
  assert.equal(fold.textContent, `기술 정보실행 ID${RUN_ID}`);
});

test('a command id source that yields a non-UUID is a recorded invalid_input, never a send', async () => {
  const { panel, calls, button, alert } = mounted([running()], { commandIds: ['not-a-uuid'] });
  await panel.read(RUN_ID);
  await button('resume').click();
  assert.equal(calls.length, 1);
  assert.equal(alert().hidden, false);
  assert.equal(alert().dataset.code, 'invalid_input');
  assert.equal(panel.snapshot().error.code, 'invalid_input');  // the screen and the snapshot agree
  assert.equal(panel.snapshot().view.runId, RUN_ID);
});

test('the panel renders the observer state: status, one text row per node, gated controls', async () => {
  const { panel, root, rows, status, alert, button } = mounted([receipt()]);
  assert.equal(root.getAttribute('aria-busy'), 'false');
  assert.equal(root.dataset.phase, '');
  assert.equal(status().getAttribute('aria-live'), 'polite');
  assert.equal(alert().hidden, true);
  for (const name of ['resume', 'cancel', 'recover']) {
    assert.equal(button(name).disabled, true);
    assert.equal(button(name).type, 'button');
    assert.equal(button(name).textContent, CONTROL_LABELS[name]);
  }
  const seen = [];
  const original = panel.observer;
  assert.equal(typeof original.read, 'function');
  const promise = panel.read(RUN_ID);
  seen.push(root.getAttribute('aria-busy'));
  const view = await promise;
  assert.deepEqual(seen, ['true']);
  assert.equal(root.getAttribute('aria-busy'), 'false');
  assert.equal(root.dataset.phase, 'awaiting_human');
  assert.equal(root.dataset.runId, RUN_ID);
  assert.match(status().textContent, new RegExp(PHASE_LABELS.awaiting_human));
  assert.deepEqual(rows(), accessibleRows(view));
  assert.equal(rows().length, 3);
  assert.match(root.find(el => el.tagName === 'OL').getAttribute('aria-label'), /시도/);
  assert.equal(button('resume').disabled, true);  // a waiting gate: resume would be a no-op
  assert.equal(button('cancel').disabled, false);
  assert.equal(button('recover').disabled, true);
  assert.equal(alert().hidden, true);
  assert.deepEqual(panel.snapshot(), panel.observer.snapshot());
});

test('a command sends one fresh command id and a refusal is shown as the server code, the view kept', async () => {
  const conflict = Object.assign(new Error('Run request could not be admitted'), { code: 'conflict', status: 409 });
  const { panel, calls, button, alert, rows, status } = mounted([running(), completed(), conflict],
    { commandIds: ['77777777-7777-4777-8777-777777777777', '88888888-8888-4888-8888-888888888888'] });
  await panel.read(RUN_ID);
  await button('resume').click();
  assert.deepEqual(calls[1], [`/api/v1/runs/${RUN_ID}/resume`,
    { method: 'POST', body: { command_id: '77777777-7777-4777-8777-777777777777' } }]);
  assert.match(status().textContent, new RegExp(PHASE_LABELS.completed));
  assert.equal(button('resume').disabled, true);
  assert.equal(button('cancel').disabled, true);
  // a completed run cannot be cancelled: the control is disabled and a click sends nothing
  await button('cancel').click();
  assert.equal(calls.length, 2);
  // a refused command (the server's conflict) is text with its code; the run is read again
  // at once (a 503 may have changed it — review MUST) and the refusal stays on screen
  // beside the fresh view until the owner's next command or read
  const { panel: again, calls: laterCalls, button: laterButton, alert: laterAlert, rows: laterRows } = mounted(
    [receipt(), conflict, completed()], { commandIds: ['88888888-8888-4888-8888-888888888888'] });
  await again.read(RUN_ID);
  await laterButton('cancel').click();
  assert.deepEqual(laterCalls[1], [`/api/v1/runs/${RUN_ID}/cancel`,
    { method: 'POST', body: { command_id: '88888888-8888-4888-8888-888888888888' } }]);
  assert.deepEqual(laterCalls[2], [`/api/v1/runs/${RUN_ID}`, {}]);
  assert.equal(laterAlert().hidden, false);
  assert.equal(laterAlert().dataset.code, 'conflict');
  assert.equal(laterAlert().textContent, ERROR_MESSAGES.conflict);
  assert.equal(laterRows().length, 2);  // the fresh (completed) view
  assert.equal(again.snapshot().view.phase, 'completed');
  assert.equal(again.snapshot().error.code, 'conflict');  // the screen and the snapshot agree
  assert.equal(laterButton('cancel').disabled, true);
  await again.read(RUN_ID).catch(() => {});
  assert.equal(laterAlert().dataset.code, 'not_found');  // the script ran out: a fresh exchange replaces the refusal
  // the first panel is untouched by the second: still the completed run's two rows, no alert
  assert.equal(alert().hidden, true);
  assert.equal(rows().length, 2);
});

test('a read failure for another run clears the screen and names the code', async () => {
  const missing = Object.assign(new Error('x'), { status: 404 });
  const { panel, alert, rows, status, root, button } = mounted([receipt(), missing]);
  await panel.read(RUN_ID);
  await assert.rejects(panel.read('99999999-9999-4999-8999-999999999999'));
  assert.equal(alert().dataset.code, 'not_found');
  assert.equal(alert().textContent, ERROR_MESSAGES.not_found);
  assert.deepEqual(rows(), []);
  assert.equal(root.dataset.phase, '');
  assert.equal(root.dataset.runId, '');
  assert.match(status().textContent, /실행/);
  assert.equal(button('cancel').disabled, true);
});

test('the panel refuses a root, document, request or command id source it cannot use', () => {
  const good = { root: new FakeElement('section'), document: fakeDocument, request: async () => ({}), commandId: () => COMMAND_ID };
  assert.throws(() => createRunPanel({ ...good, root: null }), /root/);
  assert.throws(() => createRunPanel({ ...good, document: {} }), /document/);
  assert.throws(() => createRunPanel({ ...good, request: 'no' }));
  assert.throws(() => createRunPanel({ ...good, commandId: 'no' }), /command id/);
  assert.throws(() => createRunPanel({ ...good, basePath: '/nope/' }));
  assert.throws(() => createRunPanel());
  assert.equal(Object.isFrozen(createRunPanel(good)), true);
});

test('the DOM half is wired to the supported routes through the session client', async () => {
  const fetched = [];
  const script = [
    jsonResponse(200, { state: 'authenticated', csrf_token: 'tok-1' }),
    jsonResponse(200, running(BASE)),
    jsonResponse(200, completed(BASE)),
  ];
  const session = createSupportedSession({
    fetch: async (path, options) => { fetched.push([path, options]); return script.shift(); }, basePath: BASE,
  });
  await session.establish();
  const root = new FakeElement('section');
  const panel = createRunPanel({ root, document: fakeDocument, basePath: BASE, request: session.request,
    commandId: () => COMMAND_ID });
  await panel.read(RUN_ID);
  assert.equal(fetched[1][0], `/${HEX}/api/v1/runs/${RUN_ID}`);
  assert.equal(fetched[1][1].headers['X-DeepTwin-CSRF'], undefined);
  await root.find(el => el.tagName === 'BUTTON' && el.dataset.command === 'resume').click();
  assert.equal(fetched[2][0], `/${HEX}/api/v1/runs/${RUN_ID}/resume`);
  assert.equal(fetched[2][1].headers['X-DeepTwin-CSRF'], 'tok-1');
  assert.equal(fetched[2][1].body, JSON.stringify({ command_id: COMMAND_ID }));
  assert.equal(root.dataset.phase, 'completed');
  // the observer the panel exposes is the real one
  assert.equal(typeof createRunObserver, 'function');
});
