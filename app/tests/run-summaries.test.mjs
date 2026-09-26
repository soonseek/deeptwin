// UI phase 5 (docs/ui/2026-09-26-product-ux-redesign.md §5.2): the run list table and the work
// page's runs. The snapshot names the runs; each row's facts come only from that run's trace. No
// route carries a run's environment version, so that cell is "—" with a note. Fake document/request.

import test from 'node:test';
import assert from 'node:assert/strict';

import { COLUMNS, MESSAGES, createRunSummaries, createRunTable, createWorkRuns, runRow } from '../static/run-summaries.mjs';
import { RUN, id, sampleTrace } from './helpers/run-trace-sample.mjs';

class FakeElement {
  constructor(tagName) { this.tagName = tagName.toUpperCase(); this.children = []; this.attributes = new Map(); this.dataset = {}; this.listeners = new Map(); this._text = ''; this.hidden = false; this.value = ''; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(_value) { throw new Error('markup is never written'); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }
  async dispatch(type, event = {}) { for (const listener of this.listeners.get(type) ?? []) await listener(event); }
  findAll(predicate, found = []) { for (const child of this.children) { if (predicate(child)) found.push(child); child.findAll(predicate, found); } return found; }
}
const document = { createElement: tag => new FakeElement(tag) };
const BASE = `/${'2'.repeat(32)}/`;
const OTHER = id(9001);
const WORK = id(8001);
const snapshot = runs => ({ snapshot_version: 'public-snapshot-v1', event_cursor: 'c', links: {},
  state: { works: [], attempts: [], runs: runs.map(runId => ({ id: runId, phase: 'created', revision: 1 })) } });

function traced(runId, overrides = {}) {
  return { ...sampleTrace(), run_id: runId, ...overrides };
}

test('a row says only what the run\'s trace recorded: work, status, times, cost basis and who waits', () => {
  const done = runRow(traced(RUN));
  assert.equal(done.runId, RUN);
  assert.equal(done.phase, 'completed');
  assert.equal(done.phaseLabel, '완료');
  assert.equal(done.waiting, 0);
  assert.equal(done.waitingText, '없음');
  assert.equal(done.cost, '미확인');
  assert.ok(done.duration);
  const waiting = runRow(traced(OTHER, { phase: 'awaiting_human', ended_at_utc: 'not_recorded',
    work: { title: 'not_recorded', work_id: WORK, revision: 2 },
    approvals: { gates: [{ node_id: 'gate', approval_scope: 'release-output', state: 'pending' }], executions: [] },
    totals: { ...sampleTrace().totals, cost: { state: 'estimate', microunits: 6500, currency: 'USD', method: 'reservation' } } }));
  assert.equal(waiting.title, `실행 ${OTHER.slice(0, 8)}`, 'an unrecorded work title is never invented');
  assert.equal(waiting.duration, null);
  assert.equal(waiting.waitingText, '승인 대기 1건');
  assert.match(waiting.cost, /^약 \$0\.0065 \(.*추정\)$/);
  assert.equal(waiting.workId, WORK);
});

test('the table lists the snapshot\'s runs newest first, each row linking to its run detail', async () => {
  const asked = [];
  const traces = { [RUN]: traced(RUN), [OTHER]: traced(OTHER, { phase: 'awaiting_human',
    approvals: { gates: [{ node_id: 'gate', approval_scope: 'release-output', state: 'pending' }], executions: [] } }) };
  const request = async path => {
    asked.push(path);
    if (path.endsWith('/snapshot')) return snapshot([RUN, OTHER]);
    const runId = path.split('/runs/')[1].split('/')[0];
    return traces[runId];
  };
  const root = new FakeElement('div');
  const table = createRunTable({ root, document, request, basePath: BASE });
  await table.load();
  assert.deepEqual(table.ids, [OTHER, RUN]);
  assert.equal(asked[0], `${BASE}api/v1/snapshot`);
  assert.ok(asked.includes(`${BASE}api/v1/runs/${RUN}/trace`));
  const heads = root.findAll(el => el.tagName === 'TH').map(el => el.textContent);
  assert.deepEqual(heads, COLUMNS.map(([key, label]) => (key === 'environment' || key === 'cost' ? `${label}*` : label)));
  const rows = root.findAll(el => el.tagName === 'TR' && el.getAttribute('data-run-row'));
  assert.deepEqual(rows.map(row => row.getAttribute('data-run-row')), [OTHER, RUN]);
  const links = root.findAll(el => el.tagName === 'A');
  assert.deepEqual(links.map(link => link.getAttribute('href')), [`#run=${OTHER}`, `#run=${RUN}`]);
  assert.match(rows[0].textContent, /사람 승인 대기/);
  assert.match(rows[0].textContent, /승인 대기 1건/);
  const environment = rows[1].findAll(el => el.getAttribute('data-label') === '환경 버전')[0];
  assert.equal(environment.textContent, '—');
  assert.ok(root.textContent.includes(MESSAGES.environmentNote));
  assert.equal(asked.filter(path => path.endsWith('/trace')).length, 2);
});

test('an empty vault says so, and an unreadable trace keeps its row honest', async () => {
  const root = new FakeElement('div');
  const empty = createRunTable({ root, document, basePath: BASE, request: async () => snapshot([]) });
  await empty.load();
  assert.match(root.textContent, new RegExp(MESSAGES.empty));
  const broken = new FakeElement('div');
  const table = createRunTable({ root: broken, document, basePath: BASE, request: async path => {
    if (path.endsWith('/snapshot')) return snapshot([RUN]);
    throw Object.assign(new Error('x'), { code: 'unavailable' });
  } });
  await table.load();
  assert.match(broken.textContent, new RegExp(MESSAGES.unreadable));
  assert.doesNotMatch(broken.textContent, /완료/);
});

test('the work page lists the runs whose trace names this work', async () => {
  const request = async path => {
    if (path.endsWith('/snapshot')) return snapshot([RUN, OTHER]);
    return path.includes(RUN) ? traced(RUN, { work: { title: '화요일', work_id: WORK, revision: 1 } })
      : traced(OTHER, { work: { title: '다른 업무', work_id: id(8002), revision: 1 } });
  };
  const root = new FakeElement('section');
  const runs = createWorkRuns({ root, document, request, basePath: BASE, workId: () => WORK,
    summaries: createRunSummaries({ request, basePath: BASE }) });
  const found = await runs.load();
  assert.deepEqual(found.map(row => row.runId), [RUN]);
  assert.equal(root.findAll(el => el.tagName === 'A')[0].getAttribute('href'), `./observe.html#run=${RUN}`);
  const none = createWorkRuns({ root: new FakeElement('section'), document, request, basePath: BASE, workId: () => null });
  assert.deepEqual(await none.load(), []);
});
