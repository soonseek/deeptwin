// T073: the records page over a fake document and a fake fetch. The log is the
// public event feed, paged by the server's cursor, one human sentence per event with the
// raw type in a technical fold; export points to the work screen where its preview and
// consent are. Backup and retention moved to the settings page (settings-page.test.mjs).

import test from 'node:test';
import assert from 'node:assert/strict';

import { MESSAGES, MOUNT_IDS, PAGE_SIZE, boot, createEventLog, eventRow } from '../static/records-page.mjs';

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.listeners = new Map();
    this._text = '';
    this.hidden = false;
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

function event(sequence, overrides = {}) {
  return { sequence, event_type: 'work.created', observed_at_utc: '2026-09-23T00:00:00.000000Z',
    status: 'succeeded', error_code: null, object_refs: [{}], ...overrides };
}

function pageDocument() {
  const nodes = Object.fromEntries(Object.values(MOUNT_IDS).map(id => [id, new FakeElement('section')]));
  return { nodes, document: { getElementById: id => nodes[id] ?? null, createElement: tag => new FakeElement(tag) } };
}

test('an event row names what happened, its outcome, the time and the count of records it names', () => {
  process.env.TZ = 'Asia/Seoul';
  const now = Date.parse('2026-09-23T00:03:10Z');
  const failed = eventRow(event(3, { status: 'failed', error_code: 'storage_failed', object_refs: [{}, {}] }), now);
  // a failed record never reads as done: the topic, not the past-tense sentence
  assert.equal(failed.text, '업무 만들기 · 실패 · 관련 기록 2개 · 오류: 저장 실패 · 2026-09-23 09:00:00');
  assert.equal(failed.time.relative, '3분 전');
  assert.equal(failed.tone, 'error');
  assert.equal(failed.type, 'work.created');
  const revised = eventRow(event(4, { event_type: 'work.revised', public_metadata: { revision: 4, source_count: 0 } }), now);
  assert.equal(revised.sentence, '업무 설명을 고쳤습니다 (수정본 4)');
  assert.equal(revised.status, '성공');
  const unknown = eventRow(event(5, { event_type: 'future.kind' }), now);
  assert.equal(unknown.sentence, '기록된 사건');
  assert.equal(unknown.known, false);
  assert.throws(() => eventRow({ event_type: 'x' }));
});

test('each listed event keeps its raw type, sequence and UTC stamp in the technical fold only', async () => {
  const root = new FakeElement('section');
  const request = async () => ({ events: [event(7, { event_type: 'run.started', public_metadata: { node_count: 20 } })],
    next_cursor: 'c', gap: null });
  const log = createEventLog({ root, document: { createElement: tag => new FakeElement(tag) }, request });
  await log.load();
  const row = root.findAll(el => el.tagName === 'LI')[0];
  assert.equal(row.getAttribute('data-event-type'), 'run.started');
  const fold = row.findAll(el => el.tagName === 'DETAILS')[0];
  assert.match(fold.textContent, /^기술 정보사건 종류run\.started순번7기록 시각\(UTC\)2026-09-23T00:00:00\.000000Z$/);
  const reading = row.children.filter(child => child.tagName !== 'DETAILS').map(child => child.textContent).join(' ');
  assert.match(reading, /실행을 시작했습니다 \(노드 20개\)/);
  assert.doesNotMatch(reading, /run\.started/);
  assert.equal(row.findAll(el => el.tagName === 'LI').length, 0, 'a row holds no nested list items');
});

test('the log pages by the server cursor and states gaps', async () => {
  const root = new FakeElement('section');
  const asked = [];
  const replies = [
    { events: [event(1), event(2)], next_cursor: 'c2', gap: null },
    { events: [event(3)], next_cursor: 'c3', gap: { from: 1 } },
    { events: [], next_cursor: 'c3', gap: null },
  ];
  const request = async (path, options) => { asked.push([path, options]); return replies.shift(); };
  const log = createEventLog({ root, document: { createElement: tag => new FakeElement(tag) }, request, basePath: `/${'a'.repeat(32)}/` });
  await log.load();
  assert.deepEqual(asked[0], [`/${'a'.repeat(32)}/api/v1/events`, { query: { limit: PAGE_SIZE } }]);
  assert.match(root.textContent, /사건 2개/);
  const more = root.findAll(el => el.tagName === 'BUTTON')[0];
  assert.equal(more.hidden, false);
  await more.dispatch('click');
  assert.deepEqual(asked[1][1], { query: { limit: PAGE_SIZE, cursor: 'c2' } });
  assert.match(root.textContent, new RegExp(MESSAGES.gap));
  await more.dispatch('click');
  assert.equal(more.hidden, true);  // an empty page ends the paging
  assert.equal(log.shown, 3);
});

test('the page holds only the log and the export entry, and links export to the work screen', async () => {
  assert.deepEqual(MOUNT_IDS, { session: 'session-status', logs: 'records-logs', export: 'records-export' });
  const { nodes, document } = pageDocument();
  const fetch = async () => ({ ok: false, status: 401, headers: { get: () => 'application/json' },
    json: async () => ({ code: 'unauthenticated' }), text: async () => '{"code":"unauthenticated"}' });
  const result = await boot({ document, location: { pathname: '/records.html' }, fetch });
  assert.equal(result.established, false);
  assert.match(nodes[MOUNT_IDS.export].textContent, /내보내기는 선택 사항입니다/);
  assert.match(nodes[MOUNT_IDS.export].textContent, new RegExp(MESSAGES.settingsHere));
  const link = nodes[MOUNT_IDS.export].findAll(el => el.tagName === 'A')[0];
  assert.equal(link.getAttribute('href'), './work.html#work-records');
  assert.equal(nodes[MOUNT_IDS.logs].children.length, 0);  // no log without a session
});
