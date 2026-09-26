// UI phase 6: 설정 > 서비스 클라이언트 (service-clients.mjs) over a fake document and a fake request
// adapter. The create body is exactly what `service-clients-v1` takes (grantable scopes only, an
// expiry under the server's 24 hours, the portable profile); the one-time secret is shown once
// in a read-only field and cleared on 숨기기, and it is never written to storage or an attribute;
// rotation and revocation ask first; a refusal is said in words with the server's status, code
// and message folded under 기술 정보 — "이 배포에서는 …" only where it is certain (a page over
// plain http). The success path runs against the real server in browser-service-clients.test.mjs.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  EXPIRY_CHOICES, GRANTABLE_SCOPES, MAX_SERVER_TTL_SECONDS, MESSAGES, NETWORK_PROFILE, clientState,
  createServiceClientsPanel, creationBody, untilText, validName,
} from '../static/service-clients.mjs';

let focused = null;

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.dataset = {};
    this.parent = null;
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.value = '';
    this.open = false;
    this._text = '';
  }

  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }

  set textContent(value) { this._text = String(value); this.children = []; }

  set innerHTML(_value) { throw new Error('markup is never written'); }

  append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }

  replaceChildren(...nodes) { for (const child of this.children) child.parent = null; this.children = []; this._text = ''; this.append(...nodes); }

  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); this.parent = null; }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }

  removeAttribute(name) { this.attributes.delete(name); }

  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }

  async dispatch(type, event = {}) { for (const listener of this.listeners.get(type) ?? []) await listener({ preventDefault() {}, ...event }); }

  focus() { focused = this; }

  select() { this.selected = true; }

  get isConnected() { let node = this; while (node.parent) node = node.parent; return node.tagName === 'ROOT'; }

  // a compound selector: tag, #id, .class, [attr] and [attr="value"]
  matchesOne(selector) {
    const tag = /^[a-z0-9]+/i.exec(selector)?.[0];
    if (tag && this.tagName !== tag.toUpperCase()) return false;
    const id = /#([\w-]+)/.exec(selector)?.[1];
    if (id && this.getAttribute('id') !== id) return false;
    const classes = (this.getAttribute('class') ?? '').split(/\s+/);
    for (const [, name] of selector.matchAll(/\.([\w-]+)/g)) if (!classes.includes(name)) return false;
    for (const [, name, , value] of selector.matchAll(/\[([\w-]+)(="([^"]*)")?\]/g)) {
      if (!this.attributes.has(name) || (value !== undefined && this.getAttribute(name) !== value)) return false;
    }
    return true;
  }

  findAll(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.findAll(predicate, found);
    }
    return found;
  }

  querySelectorAll(selector) {
    const parts = selector.trim().split(/\s+/);
    let scope = [this];
    for (const part of parts) scope = [...new Set(scope.flatMap(node => node.findAll(child => child.matchesOne(part))))];
    return scope;
  }

  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
}

const CLIENT_ID = '00000000-0000-4000-8000-00000000c111';
const NOW = Date.parse('2026-09-26T09:00:00Z');
const client = (overrides = {}) => ({ client_id: CLIENT_ID, owner_id: 'owner', name: '리포트 봇',
  scopes: ['events.read', 'snapshot.read'], allowed_network_profile: NETWORK_PROFILE, created_at: NOW / 1000 - 60,
  expires_at: NOW / 1000 + 3 * 3600, revision: 1, state: 'active', ...overrides });

function panelWith(replies, { pageProtocol = 'https:', clipboard = null } = {}) {
  const root = new FakeElement('div');
  const top = new FakeElement('root');
  top.append(root);
  const sent = [];
  const request = async (path, options = {}) => {
    sent.push([path, JSON.parse(JSON.stringify(options))]);
    const next = replies.shift();
    if (next instanceof Error) throw next;
    return typeof next === 'function' ? next(path, options) : next;
  };
  const document = { createElement: tag => new FakeElement(tag), activeElement: null };
  const stored = [];
  globalThis.localStorage = { setItem: (...args) => stored.push(args) };
  globalThis.sessionStorage = { setItem: (...args) => stored.push(args) };
  const panel = createServiceClientsPanel({ root, document, request, basePath: '/', now: () => NOW,
    crypto: { randomUUID: () => '00000000-0000-4000-8000-0000000000aa' }, clipboard, pageProtocol });
  const find = selector => root.querySelector(selector);
  const all = selector => root.querySelectorAll(selector);
  const byText = (tag, text) => root.findAll(node => node.tagName === tag.toUpperCase() && node.textContent === text)[0] ?? null;
  return { root, panel, sent, stored, find, all, byText };
}

function refusal(status, code, message) {
  return Object.assign(new Error(message), { status, code: 'unavailable', serverCode: code,
    correlationId: '00000000-0000-4000-8000-0000000000cc' });
}

test('the create body is exactly the route\'s: grantable scopes, an expiry under 24 hours, the portable profile', () => {
  assert.deepEqual(Object.keys(GRANTABLE_SCOPES), ['snapshot.read', 'events.read']);
  assert.ok(EXPIRY_CHOICES.every(choice => choice.hours * 3600 < MAX_SERVER_TTL_SECONDS));
  assert.deepEqual(creationBody({ clientId: CLIENT_ID, name: '  리포트 봇 ', scopes: ['snapshot.read', 'events.read'], hours: 8, nowMs: NOW }), {
    client_id: CLIENT_ID, name: '리포트 봇', scopes: ['events.read', 'snapshot.read'], allowed_network_profile: 'portable_https',
    expires_at: NOW / 1000 + 8 * 3600 });
  for (const bad of [{ scopes: ['artifact.read'] }, { scopes: [] }, { scopes: ['events.read', 'events.read'] }, { hours: 24 },
    { name: '' }, { name: 'a\nb' }, { name: '가'.repeat(43) }, { clientId: 'x' }]) {
    assert.throws(() => creationBody({ clientId: CLIENT_ID, name: '봇', scopes: ['events.read'], hours: 1, nowMs: NOW, ...bad }), TypeError);
  }
  assert.equal(validName('가'.repeat(42)), '가'.repeat(42));  // 126 bytes
  assert.equal(validName('봇\u0007'), null);
  assert.equal(clientState(client(), NOW), 'active');
  assert.equal(clientState(client({ expires_at: NOW / 1000 - 1 }), NOW), 'expired');
  assert.equal(clientState(client({ state: 'revoked' }), NOW), 'revoked');
  assert.equal(untilText(NOW / 1000 + 3 * 3600 + 120, NOW), '3시간 2분 뒤');
  assert.equal(untilText(NOW / 1000 + 600, NOW), '10분 뒤');
  assert.equal(untilText(NOW / 1000 - 5, NOW), '지남');
});

test('create: the secret is shown once in a read-only field, copied on request, cleared on 숨기기, never stored', async () => {
  const copies = [];
  const secret = `dt_sc_${'Q'.repeat(43)}`;
  const { panel, sent, stored, find, all, byText, root } = panelWith([
    { items: [], next_cursor: null },
    { client: client({ client_id: '00000000-0000-4000-8000-0000000000aa' }), secret, secret_available_once: true },
  ], { clipboard: { writeText: async value => { copies.push(value); } } });
  await panel.load();
  assert.deepEqual(sent[0], ['/api/v1/service-clients', { query: { limit: '100' } }]);
  assert.equal(find('.service-clients-count').textContent, '아직 만든 서비스 클라이언트가 없습니다.');
  // a missing name and a missing scope are said before anything is sent
  await find('form').dispatch('submit');
  assert.equal(find('.service-client-form-error').textContent, MESSAGES.nameMissing);
  assert.equal(find('#service-client-name').getAttribute('aria-invalid'), 'true');
  find('#service-client-name').value = '리포트 봇';
  await find('form').dispatch('submit');
  assert.equal(find('.service-client-form-error').textContent, MESSAGES.scopeMissing);
  assert.equal(sent.length, 1);
  find('#service-client-scope-events-read').checked = true;
  find('#service-client-expiry').value = '1';
  const created = await panel.create();
  assert.equal(created.shown, true);
  assert.deepEqual(sent[1], ['/api/v1/service-clients', { method: 'POST', body: {
    client_id: '00000000-0000-4000-8000-0000000000aa', name: '리포트 봇', scopes: ['events.read'],
    allowed_network_profile: 'portable_https', expires_at: NOW / 1000 + 3600 } }]);
  const field = find('#service-client-secret');
  assert.equal(field.value, secret);
  assert.equal(field.getAttribute('readonly'), '');
  assert.ok(![...root.findAll(() => true)].some(node => [...node.attributes.values()].some(value => value.includes(secret))),
    'the secret is in no attribute');
  assert.ok(!root.textContent.includes(secret), 'nor in any text');
  assert.equal(focused?.textContent, '새 비밀 값 — 리포트 봇');
  assert.match(find('.secret-warning').textContent, /지금 한 번만 보입니다/);
  assert.equal(panel.secretShown, true);
  await byText('button', '복사').dispatch('click');
  assert.deepEqual(copies, [secret]);
  assert.equal(find('.secret-copy-status').textContent, MESSAGES.copied);
  // the list shows the client, never the secret
  assert.match(find('li.service-client').textContent, /리포트 봇✓사용 중허용현재 상태 스냅샷 읽기 · 사건 기록 읽기/);
  await byText('button', MESSAGES.hide).dispatch('click');
  assert.equal(field.value, '');
  assert.equal(find('#service-client-secret'), null);
  assert.equal(panel.secretShown, false);
  assert.equal(find('.service-clients-notice').textContent, MESSAGES.hidden);
  assert.deepEqual(stored, [], 'nothing is written to localStorage or sessionStorage');
  assert.equal(all('.service-clients-refusal').length, 0);
});

test('a copy the browser refuses selects the field and says so', async () => {
  const { panel, find, byText } = panelWith([
    { items: [], next_cursor: null },
    { client: client(), secret: 'dt_sc_x', secret_available_once: true },
  ], { clipboard: { writeText: async () => { throw new Error('denied'); } } });
  await panel.load();
  find('#service-client-name').value = '봇';
  find('#service-client-scope-snapshot-read').checked = true;
  await panel.create();
  await byText('button', '복사').dispatch('click');
  assert.equal(find('#service-client-secret').selected, true);
  assert.equal(find('.secret-copy-status').textContent, MESSAGES.copyFailed);
});

test('rotation and revocation ask first; 취소 changes nothing; each act sends the revision it was made from', async () => {
  const rotatedSecret = `dt_sc_${'R'.repeat(43)}`;
  const { panel, sent, find, all, byText } = panelWith([
    { items: [client({ revision: 3 })], next_cursor: null },
    { client: client({ revision: 4 }), secret: rotatedSecret, secret_available_once: true },
    client({ revision: 5, state: 'revoked' }),
  ]);
  await panel.load();
  assert.equal(find('.service-clients-count').textContent, '서비스 클라이언트 1개');
  const rotate = byText('button', MESSAGES.rotate);
  await rotate.dispatch('click');
  assert.match(find('.service-client-confirm').textContent, /지금 비밀 값은 바로 쓸 수 없게 됩니다/);
  assert.equal(focused?.textContent, MESSAGES.rotateYes);
  await byText('button', MESSAGES.cancel).dispatch('click');
  assert.equal(all('.service-client-confirm').length, 0);
  assert.equal(focused, rotate, '취소 returns the keyboard');
  assert.equal(sent.length, 1, 'a cancelled confirmation sends nothing');
  await rotate.dispatch('click');
  await byText('button', MESSAGES.rotateYes).dispatch('click');
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(sent[1], [`/api/v1/service-clients/${CLIENT_ID}/rotate`, { method: 'POST', body: { expected_revision: 3 } }]);
  assert.equal(find('#service-client-secret').value, rotatedSecret);
  assert.equal(find('.service-clients-notice').textContent, MESSAGES.rotated('리포트 봇'));
  await byText('button', MESSAGES.revoke).dispatch('click');
  assert.match(find('.service-client-confirm').textContent, /되돌릴 수 없습니다/);
  await byText('button', MESSAGES.revokeYes).dispatch('click');
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(sent[2], [`/api/v1/service-clients/${CLIENT_ID}/revoke`, { method: 'POST', body: { expected_revision: 4 } }]);
  const row = find('li.service-client');
  assert.equal(row.getAttribute('data-state'), 'revoked');
  assert.match(row.textContent, /폐기됨/);
  assert.equal(row.findAll(node => node.tagName === 'BUTTON').length, 0, 'nothing left to rotate or revoke');
  // an expired client may be revoked but not rotated
  const expired = panelWith([{ items: [client({ expires_at: NOW / 1000 - 10 })], next_cursor: null }]);
  await expired.panel.load();
  assert.match(expired.find('li.service-client').textContent, /만료됨/);
  assert.equal(expired.byText('button', MESSAGES.rotate), null);
  assert.ok(expired.byText('button', MESSAGES.revoke));
});

test('a refusal is said in words; "이 배포에서는 …" only where it is certain; the server\'s answer is folded', async () => {
  // a page over plain http can never be the portable HTTPS profile
  const loopback = panelWith([{ items: [], next_cursor: null }, refusal(422, 'invalid_state', '클라이언트를 만들 수 없습니다.')],
    { pageProtocol: 'http:' });
  await loopback.panel.load();
  loopback.find('#service-client-name').value = '봇';
  loopback.find('#service-client-scope-events-read').checked = true;
  await assert.rejects(loopback.panel.create());
  const block = loopback.find('.service-clients-refusal');
  assert.equal(block.getAttribute('role'), 'alert');
  assert.equal(block.querySelector('.refusal-headline').textContent, MESSAGES.refusedHere);
  const facts = block.querySelector('.tech-details').textContent;
  for (const fact of ['응답422', '서버 코드invalid_state', '서버 메시지클라이언트를 만들 수 없습니다.', '이 화면의 주소 방식http']) {
    assert.ok(facts.includes(fact), fact);
  }
  assert.equal(loopback.find('.service-clients-notice').textContent, '', 'said once, by the alert');
  assert.equal(loopback.find('#service-client-secret'), null);
  // over https the page cannot tell why: it says the server did not make it
  const https = panelWith([{ items: [], next_cursor: null }, refusal(422, 'invalid_state', '클라이언트를 만들 수 없습니다.')]);
  await https.panel.load();
  https.find('#service-client-name').value = '봇';
  https.find('#service-client-scope-events-read').checked = true;
  await assert.rejects(https.panel.create());
  assert.equal(https.find('.refusal-headline').textContent, MESSAGES.refused);
  assert.doesNotMatch(https.root.textContent, /이 배포에서는/);
  // a stale revision re-reads the list and says so
  const stale = panelWith([{ items: [client()], next_cursor: null }, refusal(409, 'state_conflict', '현재 리비전에서는 폐기할 수 없습니다.'),
    { items: [client({ revision: 2, state: 'revoked' })], next_cursor: null }]);
  await stale.panel.load();
  await assert.rejects(stale.panel.revoke(stale.panel.clients[0]));
  assert.equal(stale.find('.service-clients-notice').textContent, MESSAGES.conflict);
  assert.equal(stale.find('li.service-client').getAttribute('data-state'), 'revoked');
  // an unreadable list says so, without claiming there are no clients
  const failed = panelWith([refusal(503, 'state_unavailable', '저장된 클라이언트를 확인하지 못했습니다.')]);
  await assert.rejects(failed.panel.load());
  assert.equal(failed.find('.service-clients-status').textContent, MESSAGES.listFailed);
  assert.equal(failed.find('.service-clients-count').textContent, '');
});

test('the settings page titles the panel itself: with heading false the panel adds no second title', () => {
  const root = new FakeElement('div');
  createServiceClientsPanel({ root, document: { createElement: tag => new FakeElement(tag) }, request: async () => ({}),
    crypto: { randomUUID: () => CLIENT_ID }, heading: false });
  assert.equal(root.findAll(node => node.tagName === 'H2').length, 0);
  assert.ok(root.children.every(child => child instanceof FakeElement), 'no placeholder child');
  const titled = new FakeElement('div');
  createServiceClientsPanel({ root: titled, document: { createElement: tag => new FakeElement(tag) }, request: async () => ({}),
    crypto: { randomUUID: () => CLIENT_ID } });
  assert.deepEqual(titled.findAll(node => node.tagName === 'H2').map(node => node.textContent), [MESSAGES.title]);
});
