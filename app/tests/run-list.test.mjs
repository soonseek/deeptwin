// T048: the run panel's run source. The shell cannot compose a run creation
// yet (no production path records a run consent, an environment or a work
// revision — the design/consent line), so the honest source of runs to observe
// is the public snapshot (GET {base}api/v1/snapshot, session-protected): its
// durable run rows (id, durable phase, revision). This module lists them,
// lets the owner pick one, and hands the id to the run panel, which reads the
// server-derived receipt. Tested over a minimal fake document and over the
// real session client + run panel so the source is proven wired.

import test from 'node:test';
import assert from 'node:assert/strict';

import { createRunPanel } from '../static/run-panel.mjs';
import { createSupportedSession } from '../static/session.mjs';
import {
  MAX_RUNS,
  RUN_PHASES,
  RUN_PHASE_LABELS,
  SNAPSHOT_VERSION,
  createRunList,
  runList,
  snapshotRoute,
} from '../static/run-list.mjs';

const RUN_A = '00000000-0000-4000-8000-00000000b0b1';
const RUN_B = '00000000-0000-4000-8000-00000000b0b2';
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

const fakeDocument = { createElement: tag => new FakeElement(tag) };

// the server mints v5 run ids (app/services/runs.py); one fixture id is v5 so the accepted
// shape is the served one, and links are prefixed by the deployment base path as served
const RUN_C = '360df7c5-9ad6-583b-8f1e-0c2a4b6d8e10';

function snapshot(runs = [{ id: RUN_A, phase: 'created', revision: 3 }, { id: RUN_B, phase: 'cancelled', revision: 5 }],
                  base = '/') {
  return {
    snapshot_version: 'public-snapshot-v1',
    event_cursor: 'opaque-cursor',
    state: { works: [{ id: '11111111-2222-4333-8444-555555555555', revision: 1, file_count: 0 }], runs, attempts: [] },
    links: { events: `${base.slice(0, -1)}/api/v1/events` },
  };
}

test('the snapshot route binds the base path and the version string is the server\'s', () => {
  assert.equal(SNAPSHOT_VERSION, 'public-snapshot-v1');
  assert.equal(snapshotRoute('/'), '/api/v1/snapshot');
  assert.equal(snapshotRoute(BASE), `/${HEX}/api/v1/snapshot`);
  assert.throws(() => snapshotRoute('/nope/'));
  // the durable run phases of the runtime ledger (a run row's own phase, not the derived one)
  assert.deepEqual([...RUN_PHASES].sort(), ['cancelled', 'created']);
  assert.deepEqual(Object.keys(RUN_PHASE_LABELS).sort(), [...RUN_PHASES].sort());
  for (const label of Object.values(RUN_PHASE_LABELS)) assert.equal(typeof label === 'string' && label.length > 0, true);
});

test('a public snapshot becomes a frozen list of runs to observe, in recorded order', () => {
  const list = runList(snapshot());
  assert.deepEqual(list, [
    { runId: RUN_A, phase: 'created', phaseLabel: RUN_PHASE_LABELS.created, revision: 3 },
    { runId: RUN_B, phase: 'cancelled', phaseLabel: RUN_PHASE_LABELS.cancelled, revision: 5 },
  ]);
  assert.equal(Object.isFrozen(list) && Object.isFrozen(list[0]), true);
  assert.deepEqual(runList(snapshot([])), []);
  assert.equal(runList(snapshot([{ id: RUN_C, phase: 'created', revision: 1 }]))[0].runId, RUN_C);
  // review MUST: the bound is the server's own snapshot item bound, never below it
  const many = count => Array.from({ length: count }, (_, index) =>
    ({ id: `${index.toString(16).padStart(8, '0')}-0000-4000-8000-000000000000`, phase: 'created', revision: 1 }));
  assert.equal(MAX_RUNS, 10_000);
  assert.equal(runList(snapshot(many(MAX_RUNS))).length, MAX_RUNS);
  assert.throws(() => runList(snapshot(many(MAX_RUNS + 1))), error => error.code === 'unavailable');
  for (const bad of [
    { ...snapshot(), snapshot_version: 'public-snapshot-v2' },
    { ...snapshot(), state: { works: [], attempts: [] } },
    snapshot([{ id: 'not-a-uuid', phase: 'created', revision: 1 }]),
    snapshot([{ id: RUN_A, phase: 'running', revision: 1 }]),  // a derived phase is not a durable one
    snapshot([{ id: RUN_A, phase: 'created', revision: 0 }]),
    snapshot([{ id: RUN_A, phase: 'created', revision: 1, extra: true }]),
    snapshot([{ id: RUN_A, phase: 'created', revision: 1 }, { id: RUN_A, phase: 'created', revision: 2 }]),
    { ...snapshot(), state: { ...snapshot().state, runs: 'nope' } },
    null, 'x', [],
  ]) {
    assert.throws(() => runList(bad), () => true);
  }
});

function mounted(script, { basePath = '/', onSelect = () => {} } = {}) {
  const calls = [];
  const root = new FakeElement('section');
  const list = createRunList({
    root, document: fakeDocument, basePath, onSelect,
    request: async (path, options = {}) => {
      calls.push([path, options]);
      const step = script.shift();
      if (step instanceof Error) throw step;
      if (step === undefined) throw Object.assign(new Error('script exhausted'), { status: 503 });
      return step;
    },
  });
  const select = () => root.find(el => el.tagName === 'SELECT');
  const status = () => root.find(el => el.getAttribute('role') === 'status');
  const refresh = () => root.find(el => el.tagName === 'BUTTON');
  return { list, root, calls, select, status, refresh };
}

test('the list reads the snapshot through the injected request and renders one option per run', async () => {
  const { list, calls, select, status, refresh } = mounted([snapshot()]);
  assert.equal(select().disabled, true);
  assert.match(status().textContent, /불러오기 전/);
  const runs = await list.refresh();
  assert.deepEqual(calls, [['/api/v1/snapshot', {}]]);  // a read never posts
  assert.equal(runs.length, 2);
  const options = select().children;
  assert.equal(options[0].value, '');  // the empty choice first: nothing is auto-selected
  assert.deepEqual(options.slice(1).map(option => [option.value, option.textContent]), [
    [RUN_A, `${RUN_PHASE_LABELS.created} · ${RUN_A}`],
    [RUN_B, `${RUN_PHASE_LABELS.cancelled} · ${RUN_B}`],
  ]);
  assert.equal(select().disabled, false);
  assert.match(status().textContent, /2개/);
  assert.equal(refresh().disabled, false);
  assert.deepEqual(list.snapshot(), { busy: false, runs, error: null, selected: null });
});

test('an empty vault and a refused read are honest text, never a selection', async () => {
  const { list, select, status } = mounted([snapshot([])]);
  await list.refresh();
  assert.match(status().textContent, /아직 없습니다/);
  assert.equal(select().disabled, true);
  const refused = Object.assign(new Error('Session request could not be admitted'), { code: 'unauthenticated', status: 401 });
  const failing = mounted([refused]);
  await assert.rejects(failing.list.refresh());
  assert.equal(failing.list.snapshot().error.code, 'unauthenticated');
  assert.match(failing.status().textContent, /세션/);
  assert.equal(failing.select().disabled, true);
  // a reply that is not a public snapshot never becomes the list
  const lying = mounted([{ ...snapshot(), snapshot_version: 'other' }]);
  await assert.rejects(lying.list.refresh());
  assert.equal(lying.list.snapshot().error.code, 'unavailable');
  assert.deepEqual(lying.list.snapshot().runs, []);
  // an error code that is a prototype key is never a label (review closure)
  const proto = mounted([Object.assign(new Error('x'), { code: 'constructor' })]);
  await assert.rejects(proto.list.refresh());
  assert.equal(proto.list.snapshot().error.code, 'unavailable');
  assert.doesNotMatch(proto.status().textContent, /native code|object Object/);
});

test('a failed refresh keeps the last honest list and the choice, and says so', async () => {
  // review closure: run rows are never deleted, so a failed re-read is the only way a chosen
  // run could vanish from the list while the panel still shows it — the list stays, the
  // error is shown, and the panel is never left pointing at a run the list disowned
  const chosen = [];
  const { list, select, status } = mounted([snapshot(), Object.assign(new Error('x'), { status: 503 })],
    { onSelect: runId => chosen.push(runId) });
  await list.refresh();
  select().value = RUN_A;
  await select().dispatch('change');
  await assert.rejects(list.refresh());
  assert.equal(list.snapshot().runs.length, 2);
  assert.equal(list.snapshot().selected, RUN_A);
  assert.equal(list.snapshot().error.code, 'unavailable');
  assert.equal(select().disabled, false);
  assert.equal(select().value, RUN_A);
  assert.match(status().textContent, /마지막으로 읽은 목록/);
  assert.deepEqual(chosen, [RUN_A]);
});

test('choosing a run hands its id to the observer once, and clearing hands nothing', async () => {
  const chosen = [];
  const { list, select } = mounted([snapshot()], { onSelect: runId => chosen.push(runId) });
  await list.refresh();
  select().value = RUN_B;
  await select().dispatch('change');
  assert.deepEqual(chosen, [RUN_B]);
  assert.equal(list.snapshot().selected, RUN_B);
  select().value = '';
  await select().dispatch('change');
  assert.deepEqual(chosen, [RUN_B]);
  assert.equal(list.snapshot().selected, null);
  // a value the list never offered is refused (a DOM edit is not a choice)
  select().value = '99999999-9999-4999-8999-999999999999';
  await select().dispatch('change');
  assert.deepEqual(chosen, [RUN_B]);
  assert.equal(list.snapshot().selected, null);
});

test('overlapping refreshes never publish a stale list', async () => {
  let release;
  const first = new Promise(resolve => { release = resolve; });
  const script = [first.then(() => snapshot([{ id: RUN_A, phase: 'created', revision: 1 }])), snapshot()];
  const { list } = mounted(script);
  const slow = list.refresh();
  const fast = list.refresh();
  await fast;
  release();
  const stale = await slow;
  assert.equal(list.snapshot().runs.length, 2);  // the newer reply stands
  assert.equal(stale.length, 2);  // a superseded refresh resolves with the list that stands
  assert.equal(list.snapshot().busy, false);
});

test('the source is wired to the run panel through the session client on the deployment base path', async () => {
  const receipt = {
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
  const fetched = [];
  const replies = [
    { ok: true, status: 200, async json() { return { state: 'authenticated', csrf_token: 'tok-1' }; } },
    { ok: true, status: 200, async json() { return snapshot(undefined, BASE); } },
    { ok: true, status: 200, async json() { return receipt; } },
  ];
  const session = createSupportedSession({ fetch: async (path, options) => { fetched.push([path, options]); return replies.shift(); }, basePath: BASE });
  await session.establish();
  const panelRoot = new FakeElement('section');
  const panel = createRunPanel({ root: panelRoot, document: fakeDocument, basePath: BASE, request: session.request,
    commandId: () => '77777777-7777-4777-8777-777777777777' });
  const listRoot = new FakeElement('section');
  const list = createRunList({ root: listRoot, document: fakeDocument, basePath: BASE, request: session.request,
    onSelect: runId => panel.read(runId).catch(() => {}) });
  await list.refresh();
  assert.equal(fetched[1][0], `/${HEX}/api/v1/snapshot`);
  const select = listRoot.find(el => el.tagName === 'SELECT');
  select.value = RUN_A;
  await select.dispatch('change');
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(fetched[2][0], `/${HEX}/api/v1/runs/${RUN_A}`);
  assert.equal(panelRoot.dataset.runId, RUN_A);
  assert.equal(panelRoot.dataset.phase, 'completed');
  assert.throws(() => createRunList({ root: listRoot, document: fakeDocument, request: session.request, onSelect: 'no' }));
  assert.throws(() => createRunList({ document: fakeDocument, request: session.request }));
});
