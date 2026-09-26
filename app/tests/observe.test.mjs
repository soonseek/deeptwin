// T048/T025: the shell mount on the supported factory. `observe.html` is a
// public static page (served like every catalogued module, under the
// deployment base path with relative asset paths) whose module boots the
// supported session client, mounts the run list and the run panel, and says
// plainly when there is no session. No login UI here (T025's); no auto-boot
// under node (no document). Tested over a minimal fake document and fake
// fetch; the DOM half's browser case stays T049's.

import test from 'node:test';
import assert from 'node:assert/strict';

import { artifactFromHash, boot, bootPage, MOUNT_IDS, runFromHash } from '../static/observe.mjs';

const HEX = '2'.repeat(32);
const BASE = `/${HEX}/`;
const RUN_A = '00000000-0000-4000-8000-00000000b0b1';

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.listeners = new Map();
    this.hidden = false;
    this.disabled = false;
    this.value = '';
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

  async dispatch(type) { for (const listener of this.listeners.get(type) ?? []) await listener({ preventDefault() {} }); }

  find(predicate) {
    for (const child of this.children) {
      if (predicate(child)) return child;
      const found = child.find(predicate);
      if (found) return found;
    }
    return null;
  }
}

function fakeDocument(ids = MOUNT_IDS) {
  const byId = new Map(Object.values(ids).map(id => [id, new FakeElement('section')]));
  return {
    createElement: tag => new FakeElement(tag),
    getElementById: id => byId.get(id) ?? null,
    elements: byId,
  };
}

function jsonResponse(status, payload) {
  return { ok: status >= 200 && status < 300, status, async json() { return payload; } };
}

function snapshot(runs) {
  return { snapshot_version: 'public-snapshot-v1', event_cursor: 'c',
    state: { works: [], runs, attempts: [] }, links: { events: `/${HEX}/api/v1/events` } };
}

function receipt() {
  return {
    command_id: '11111111-2222-4333-8444-555555555555', run_id: RUN_A,
    graph_ref: { kind: 'graph', id: '33333333-3333-4333-8333-333333333333', version: 1, sha256: 'c'.repeat(64) },
    graph_digest: 'd'.repeat(64), phase: 'completed',
    outcome: { run_id: RUN_A, graph_digest: 'd'.repeat(64), completed_node_ids: ['intake'],
      execution_ids: [['intake', 'e-intake']],
      result_refs: [['e-intake', { kind: 'artifact', id: '44444444-4444-4444-8444-444444444444', version: 1, sha256: 'c'.repeat(64) }]],
      counters: { intake: 1 }, activations: [], awaiting_human: [], approvals: [], pending_node_ids: [], rejected_human: [] },
    links: { self: `/${HEX}/api/v1/runs/${RUN_A}`, approvals: `/${HEX}/api/v1/runs/${RUN_A}/approvals`, events: `/${HEX}/api/v1/events` },
    event_cursor: 'opaque-cursor', cancellation: { requested: false, attempts: [] },
  };
}

function booted(replies, { pathname = `${BASE}observe.html` } = {}) {
  const fetched = [];
  const document = fakeDocument();
  const crypto = { randomUUID: () => '77777777-7777-4777-8777-777777777777' };
  const promise = boot({
    document, location: { pathname }, crypto,
    fetch: async (path, options) => { fetched.push([path, options]); const reply = replies.shift(); if (reply instanceof Error) throw reply; return reply; },
  });
  return { promise, fetched, document };
}

test('the mount ids are the page\'s and the boot refuses a document without them', async () => {
  assert.deepEqual(MOUNT_IDS, { session: 'session-status', source: 'run-source', panel: 'run-panel',
    artifacts: 'run-artifacts' });
  const document = fakeDocument({ session: 'session-status' });
  await assert.rejects(boot({ document, location: { pathname: '/' }, fetch: async () => {}, crypto: { randomUUID: () => RUN_A } }), /mount/);
  await assert.rejects(boot({ document: fakeDocument(), location: { pathname: '/' }, fetch: 'no', crypto: { randomUUID: () => RUN_A } }));
  await assert.rejects(boot({ document: fakeDocument(), location: { pathname: '/' }, fetch: async () => {}, crypto: {} }), /crypto/);
});

test('without a session the page says so and mounts nothing that could send a command', async () => {
  const { promise, fetched, document } = booted([jsonResponse(401, { code: 'unauthenticated', message: 'x' })]);
  const mounted = await promise;
  assert.equal(fetched.length, 1);
  assert.equal(fetched[0][0], `/${HEX}/session`);
  assert.equal(mounted.established, false);
  assert.equal(mounted.list, null);
  assert.equal(mounted.panel, null);
  assert.equal(mounted.artifacts, null);
  const status = document.elements.get('session-status');
  assert.match(status.textContent, /세션/);
  assert.equal(status.dataset.state, 'unauthenticated');
  // the copy states the fact and names the start screen, which handles setup and login
  // alike (a fresh instance without an owner gets the same 401 here)
  assert.match(status.textContent, /시작 화면/);
  assert.doesNotMatch(status.textContent, /구현 중/);
  assert.equal(document.elements.get('run-panel').children.length, 0);
  assert.equal(document.elements.get('run-source').children.length, 0);
  // a network failure is the same honest shape, never a mount
  const offline = booted([new TypeError('offline')]);
  const result = await offline.promise;
  assert.equal(result.established, false);
  assert.equal(offline.document.elements.get('session-status').dataset.state, 'unavailable');
  assert.match(offline.document.elements.get('session-status').textContent, /연결하지 못했습니다/);
  // a server that answered outside the session grammar (a 404 detail shape, a 5xx) is not
  // a connection failure: the text names the status it saw, never a claim it cannot make
  const answered = booted([jsonResponse(404, { detail: 'Not Found' })]);
  await answered.promise;
  const status404 = answered.document.elements.get('session-status');
  assert.equal(status404.dataset.state, 'unavailable');
  assert.doesNotMatch(status404.textContent, /연결하지 못했습니다/);
  assert.match(status404.textContent, /404/);
});

test('a boot that fails outside the session exchange still reaches the status line', async () => {
  // review closure: the page's auto-boot must never leave the HTML's initial text standing
  const document = fakeDocument();
  const result = await bootPage({ document, location: { pathname: '/' }, fetch: async () => jsonResponse(200, {}), crypto: {} });
  assert.equal(result, null);
  const status = document.elements.get('session-status');
  assert.equal(status.dataset.state, 'unavailable');
  assert.match(status.textContent, /확인하지 못했습니다/);
  // and a normal boot through the same entry resolves the mount
  const fine = fakeDocument();
  const mounted = await bootPage({ document: fine, location: { pathname: '/' },
    fetch: async () => jsonResponse(401, { code: 'unauthenticated' }), crypto: { randomUUID: () => RUN_A } });
  assert.equal(mounted.established, false);
  assert.equal(fine.elements.get('session-status').dataset.state, 'unauthenticated');
});

test('with a session the list is read once and a choice reaches the panel on the base path', async () => {
  const { promise, fetched, document } = booted([
    jsonResponse(200, { state: 'authenticated', csrf_token: 'tok-1' }),
    jsonResponse(200, snapshot([{ id: RUN_A, phase: 'created', revision: 1 }])),
    jsonResponse(200, receipt()),
    jsonResponse(200, { run_id: RUN_A, artifacts: [] }),
  ]);
  const mounted = await promise;
  assert.equal(mounted.established, true);
  assert.equal(mounted.basePath, BASE);
  assert.deepEqual(fetched.map(([path]) => path), [`/${HEX}/session`, `/${HEX}/api/v1/snapshot`]);
  const status = document.elements.get('session-status');
  assert.equal(status.dataset.state, 'authenticated');
  assert.match(status.textContent, /세션/);
  const select = document.elements.get('run-source').find(el => el.tagName === 'SELECT');
  assert.equal(select.children.length, 2);
  select.value = RUN_A;
  await select.dispatch('change');
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(fetched[2][0], `/${HEX}/api/v1/runs/${RUN_A}`);
  assert.equal(fetched[2][1].headers['X-DeepTwin-CSRF'], undefined);  // a read never carries the token
  const panel = document.elements.get('run-panel');
  assert.equal(panel.dataset.runId, RUN_A);
  assert.equal(panel.dataset.phase, 'completed');
  assert.equal(typeof mounted.panel.read, 'function');
  // the same choice shows the run's artifacts on their own surface
  assert.equal(fetched[3][0], `/${HEX}/api/v1/runs/${RUN_A}/artifacts`);
  assert.equal(mounted.artifacts.runId, RUN_A);
  assert.match(document.elements.get('run-artifacts').textContent, /산출물 파일이 없습니다/);
  // the command id source is the platform's, never a constant of the module
  const commandId = mounted.commandId();
  assert.equal(commandId, '77777777-7777-4777-8777-777777777777');
  // the portable base path is derived the same way
  const portable = booted([jsonResponse(200, { state: 'authenticated', csrf_token: 't' }), jsonResponse(200, snapshot([]))],
    { pathname: '/observe.html' });
  const plain = await portable.promise;
  assert.equal(plain.basePath, '/');
  assert.equal(portable.fetched[0][0], '/session');
});

test('a failed first list read leaves the session established and the list honest', async () => {
  const { promise, fetched, document } = booted([
    jsonResponse(200, { state: 'authenticated', csrf_token: 'tok-1' }),
    jsonResponse(503, { code: 'unavailable' }),
  ]);
  const mounted = await promise;
  assert.equal(mounted.established, true);
  assert.equal(fetched.length, 2);
  assert.equal(mounted.list.snapshot().error.code, 'unavailable');
  assert.match(document.elements.get('run-source').find(el => el.getAttribute('role') === 'status').textContent, /읽지 못했습니다/);
  assert.equal(document.elements.get('session-status').dataset.state, 'authenticated');
});

test('where the page offers the approval mount, a choice also shows the run\'s approvals', async () => {
  const replies = new Map([
    [`/${HEX}/session`, jsonResponse(200, { state: 'authenticated', csrf_token: 'tok-1' })],
    [`/${HEX}/api/v1/snapshot`, jsonResponse(200, snapshot([{ id: RUN_A, phase: 'created', revision: 1 }]))],
    [`/${HEX}/api/v1/runs/${RUN_A}`, jsonResponse(200, receipt())],
    [`/${HEX}/api/v1/runs/${RUN_A}/artifacts`, jsonResponse(200, { run_id: RUN_A, artifacts: [] })],
    [`/${HEX}/api/v1/runs/${RUN_A}/approvals/executions`, jsonResponse(200, { run_id: RUN_A, requests: [], links: {} })],
  ]);
  const fetched = [];
  const document = fakeDocument({ ...MOUNT_IDS, approvals: 'run-approvals' });
  const mounted = await boot({ document, location: { pathname: `${BASE}observe.html` },
    crypto: { randomUUID: () => '77777777-7777-4777-8777-777777777777' },
    fetch: async path => { fetched.push(path); return replies.get(path); } });
  assert.equal(typeof mounted.approvals.show, 'function');
  const select = document.elements.get('run-source').find(el => el.tagName === 'SELECT');
  select.value = RUN_A;
  await select.dispatch('change');
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.ok(fetched.includes(`/${HEX}/api/v1/runs/${RUN_A}/approvals/executions`), JSON.stringify(fetched));
  assert.equal(mounted.approvals.runId, RUN_A);
  assert.match(document.elements.get('run-approvals').textContent, /지금 승인할 일이 없습니다/);
});

test('`#run=<id>` names a run only when it is a canonical run id', () => {
  assert.equal(runFromHash(`#run=${RUN_A}`), RUN_A);
  assert.equal(runFromHash(`run=${RUN_A}`), RUN_A);
  for (const value of ['', '#', '#run=', '#run=../x', `#other=${RUN_A}`, null, undefined, 7]) {
    assert.equal(runFromHash(value), null, String(value));
  }
});

// UI phase 4: the records page's artifact index links to `#run=<id>&artifact=<id>`
test('`#run=<id>&artifact=<id>` names one artifact of that run to preview, and nothing without the run', () => {
  const ARTIFACT = '00000000-0000-4000-8000-00000000a0a1';
  assert.equal(runFromHash(`#run=${RUN_A}&artifact=${ARTIFACT}`), RUN_A);
  assert.equal(artifactFromHash(`#run=${RUN_A}&artifact=${ARTIFACT}`), ARTIFACT);
  for (const value of [`#artifact=${ARTIFACT}`, `#run=${RUN_A}&artifact=x`, `#run=${RUN_A}`, null]) {
    assert.equal(artifactFromHash(value), null, String(value));
  }
});
