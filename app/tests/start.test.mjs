// T025 / UX-AC01 (experience.md §5.1.3): the instance's first screen. On an
// instance without an owner the page shows the first-owner setup form — the
// one-time capability is typed in (never in the URL) and the owner password
// is created; on an instance with an owner it shows the login form. The
// server alone decides: the page reads the public setup state from
// {base}health, posts to the establishment routes, and on success moves to
// the work screen. Tested over a fake document/fetch/location; the
// browser case stays T049's.

import test from 'node:test';
import assert from 'node:assert/strict';

import { CAPABILITY, MIN_PASSWORD_CHARS, MOUNT_IDS, boot, setupState } from '../static/start.mjs';

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

  async dispatch(type) {
    let prevented = false;
    for (const listener of this.listeners.get(type) ?? []) await listener({ preventDefault() { prevented = true; } });
    return prevented;
  }

  find(predicate) {
    for (const child of this.children) {
      if (predicate(child)) return child;
      const found = child.find(predicate);
      if (found) return found;
    }
    return null;
  }
}

function fakeDocument() {
  const byId = new Map(Object.values(MOUNT_IDS).map(id => [id, new FakeElement(id.endsWith('form') ? 'form' : 'section')]));
  return { createElement: tag => new FakeElement(tag), getElementById: id => byId.get(id) ?? null, elements: byId };
}

function jsonResponse(status, payload) {
  return { ok: status >= 200 && status < 300, status, async json() { return payload; } };
}

function booted(replies, { pathname = `${BASE}` } = {}) {
  const fetched = [];
  const document = fakeDocument();
  const navigated = [];
  const location = { pathname, assign: url => navigated.push(url) };
  const promise = boot({
    document, location,
    fetch: async (path, options) => { fetched.push([path, options]); const reply = replies.shift(); if (reply instanceof Error) throw reply; return reply; },
  });
  return { promise, fetched, document, navigated };
}

function field(document, id) { return document.getElementById(id); }

test('the setup state is read from the public health route and nothing else decides the form', async () => {
  assert.deepEqual(MOUNT_IDS, { status: 'start-status', setup: 'setup-form', login: 'login-form' });
  assert.equal(MIN_PASSWORD_CHARS, 15);
  assert.deepEqual(setupState({ state: 'available', owner: false, setup: 'available' }), { owner: false, setup: 'available' });
  for (const bad of [{ state: 'available' }, { state: 'available', owner: 'no', setup: 'available' },
    { state: 'available', owner: false, setup: 'weird' }, null, 'x']) {
    assert.throws(() => setupState(bad));
  }
});

test('an established session goes straight to the work screen', async () => {
  const { promise, fetched, navigated } = booted([jsonResponse(200, { state: 'authenticated', csrf_token: 't' })]);
  const result = await promise;
  assert.equal(result.mode, 'established');
  assert.deepEqual(fetched.map(([path]) => path), [`/${HEX}/session`]);
  assert.deepEqual(navigated, [`/${HEX}/work.html`]);
});

test('an instance without an owner shows the setup form only, and a typed capability is never in a URL', async () => {
  const { promise, fetched, document, navigated } = booted([
    jsonResponse(401, { code: 'unauthenticated' }),
    jsonResponse(200, { state: 'available', owner: false, setup: 'available' }),
    jsonResponse(201, { state: 'authenticated', csrf_token: 't' }),
  ]);
  const result = await promise;
  assert.equal(result.mode, 'setup');
  assert.deepEqual(fetched.map(([path]) => path), [`/${HEX}/session`, `/${HEX}/health`]);
  assert.equal(field(document, 'setup-form').hidden, false);
  assert.equal(field(document, 'login-form').hidden, true);
  assert.match(field(document, 'start-status').textContent, /최초 소유자/);
  // the form's inputs: capability, login name, password; the page validates before sending
  const setup = field(document, 'setup-form');
  const inputs = { capability: setup.find(el => el.dataset.field === 'capability'),
    login: setup.find(el => el.dataset.field === 'login_name'), password: setup.find(el => el.dataset.field === 'password') };
  assert.equal(inputs.password.type, 'password');
  assert.equal(inputs.capability.type, 'password');  // typed, never shown or logged
  inputs.capability.value = 'not-a-capability';
  inputs.login.value = 'owner';
  inputs.password.value = 'short';
  assert.equal(await setup.dispatch('submit'), true);  // the native submit is always prevented
  assert.equal(fetched.length, 2);  // nothing sent
  assert.match(field(document, 'start-status').textContent, /capability|비밀번호/);
  // review closure: the client mirrors the server's byte bounds and names the field
  inputs.capability.value = 'A'.repeat(43);
  inputs.password.value = 'x'.repeat(1_025);
  assert.equal(await setup.dispatch('submit'), true);
  assert.equal(fetched.length, 2);
  assert.match(field(document, 'start-status').textContent, /비밀번호.*1024/);
  inputs.capability.value = 'A'.repeat(43);
  inputs.login.value = '가'.repeat(43);  // 129 UTF-8 bytes
  inputs.password.value = 'a passphrase of fifteen characters';
  assert.equal(await setup.dispatch('submit'), true);
  assert.equal(fetched.length, 2);
  assert.match(field(document, 'start-status').textContent, /이름.*128/);
  inputs.capability.value = 'A'.repeat(43);
  inputs.login.value = 'owner';
  inputs.password.value = 'a passphrase of fifteen characters';
  assert.equal(await setup.dispatch('submit'), true);
  assert.equal(fetched.length, 3);
  const [path, options] = fetched[2];
  assert.equal(path, `/${HEX}/session/bootstrap`);
  assert.equal(options.method, 'POST');
  assert.equal(options.credentials, 'same-origin');
  assert.equal(options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(options.body), { login_name: 'owner', password: 'a passphrase of fifteen characters',
    raw_capability_b64u: 'A'.repeat(43) });
  assert.equal(CAPABILITY.test('A'.repeat(43)), true);
  assert.equal(CAPABILITY.test('A'.repeat(42)), false);
  assert.deepEqual(navigated, [`/${HEX}/work.html`]);
  // the inputs are cleared after the exchange, success or not
  assert.equal(inputs.password.value, '');
  assert.equal(inputs.capability.value, '');
});

test('an instance with an owner shows the login form only, and a refusal is typed text', async () => {
  const { promise, fetched, document, navigated } = booted([
    jsonResponse(401, { code: 'unauthenticated' }),
    jsonResponse(200, { state: 'available', owner: true, setup: 'completed' }),
    jsonResponse(401, { code: 'credentials', message: 'x' }),
    jsonResponse(200, { state: 'authenticated', csrf_token: 't' }),
  ]);
  const result = await promise;
  assert.equal(result.mode, 'login');
  assert.equal(field(document, 'setup-form').hidden, true);
  assert.equal(field(document, 'login-form').hidden, false);
  const login = field(document, 'login-form');
  const name = login.find(el => el.dataset.field === 'login_name');
  const password = login.find(el => el.dataset.field === 'password');
  name.value = 'owner';
  password.value = 'wrong';
  assert.equal(await login.dispatch('submit'), true);
  assert.equal(fetched[2][0], `/${HEX}/session/login`);
  assert.deepEqual(JSON.parse(fetched[2][1].body), { login_name: 'owner', password: 'wrong' });
  assert.equal(field(document, 'start-status').dataset.state, 'credentials');
  assert.match(field(document, 'start-status').textContent, /맞지 않/);
  assert.deepEqual(navigated, []);
  assert.equal(password.value, '');
  name.value = 'owner';
  password.value = 'right';
  await login.dispatch('submit');
  assert.deepEqual(navigated, [`/${HEX}/work.html`]);
});

test('a setup that is no longer available says so and offers no form', async () => {
  // review closure: a consumed claim cannot complete here — only the deployment operator's
  // recovery can (api.md: no automatic restoration); the text says so, never "try again"
  for (const [setup, pattern] of [['consumed', /운영자.*복구|복구.*운영자/], ['expired', /만료/], ['exhausted', /소진/]]) {
    const { promise, document } = booted([
      jsonResponse(401, { code: 'unauthenticated' }),
      jsonResponse(200, { state: 'available', owner: false, setup }),
    ]);
    const result = await promise;
    assert.equal(result.mode, 'unavailable', setup);
    assert.equal(field(document, 'setup-form').hidden, true);
    assert.equal(field(document, 'login-form').hidden, true);
    assert.match(field(document, 'start-status').textContent, pattern, setup);
  }
  // a health read outside the contract, or a connection failure, is honest text
  const broken = booted([jsonResponse(401, { code: 'unauthenticated' }), jsonResponse(200, { state: 'available' })]);
  assert.equal((await broken.promise).mode, 'unavailable');
  const offline = booted([new TypeError('offline')]);
  assert.equal((await offline.promise).mode, 'unavailable');
  assert.match(offline.document.getElementById('start-status').textContent, /연결하지 못했습니다/);
});

test('the server codes of the establishment routes are text the owner can act on', async () => {
  for (const [status, code, pattern] of [
    [429, 'capacity', /시도가 너무 많/], [409, 'setup_incomplete', /운영자/], [409, 'setup_unavailable', /사용할 수 없/],
    [400, 'invalid_input', /형식/], [503, 'unavailable', /처리하지 못했/],
  ]) {
    const { promise, document } = booted([
      jsonResponse(401, { code: 'unauthenticated' }),
      jsonResponse(200, { state: 'available', owner: false, setup: 'available' }),
      jsonResponse(status, { code }),
    ]);
    await promise;
    const setup = document.getElementById('setup-form');
    setup.find(el => el.dataset.field === 'capability').value = 'A'.repeat(43);
    setup.find(el => el.dataset.field === 'login_name').value = 'owner';
    setup.find(el => el.dataset.field === 'password').value = 'a passphrase of fifteen characters';
    await setup.dispatch('submit');
    assert.equal(document.getElementById('start-status').dataset.state, code);
    assert.match(document.getElementById('start-status').textContent, pattern, code);
  }
});
