// T073: the records page over a fake document and a fake fetch. The log is the
// public event feed, paged by the server's cursor; backup and retention say only
// what this server does (no backup claimed without a worker, no automatic
// deletion); export points to the work screen where its preview and consent are.

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
  return { sequence, event_type: 'work.created', recorded_at_utc: '2026-09-23T00:00:00.000000Z',
    status: 'succeeded', error_code: null, object_refs: [{}], ...overrides };
}

function pageDocument() {
  const nodes = Object.fromEntries(Object.values(MOUNT_IDS).map(id => [id, new FakeElement('section')]));
  return { nodes, document: { getElementById: id => nodes[id] ?? null, createElement: tag => new FakeElement(tag) } };
}

test('an event row names time, kind, outcome and the count of records it names', () => {
  assert.equal(eventRow(event(3, { status: 'failed', error_code: 'unavailable', object_refs: [{}, {}] })).text,
    '2026-09-23T00:00:00.000000Z · work.created · 실패 · 오류 unavailable · 관련 기록 2개');
  assert.throws(() => eventRow({ event_type: 'x' }));
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

test('the page says what backup and retention actually do, and links export to the work screen', async () => {
  const { nodes, document } = pageDocument();
  const fetch = async () => ({ ok: false, status: 401, headers: { get: () => 'application/json' },
    json: async () => ({ code: 'unauthenticated' }), text: async () => '{"code":"unauthenticated"}' });
  const result = await boot({ document, location: { pathname: '/records.html' }, fetch });
  assert.equal(result.established, false);
  assert.match(nodes[MOUNT_IDS.backup].textContent, /백업 워커가 아직 연결되어 있지 않습니다/);
  assert.match(nodes[MOUNT_IDS.retention].textContent, /자동 삭제는 없습니다/);
  const link = nodes[MOUNT_IDS.export].findAll(el => el.tagName === 'A')[0];
  assert.equal(link.getAttribute('href'), './work.html');
  assert.equal(nodes[MOUNT_IDS.logs].children.length, 0);  // no log without a session
});
