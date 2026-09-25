// The owner's Claude connection panel over a fake document and request: the key is
// masked, sent once and cleared from the field; the catalog read and the model choice
// are explicit; no response ever carries the key.

import test from 'node:test';
import assert from 'node:assert/strict';

import { ERROR_MESSAGES, MESSAGES, createClaudeConnection } from '../static/claude-connection.mjs';

class FakeElement {
  constructor(tagName) { this.tagName = tagName.toUpperCase(); this.children = []; this.attributes = new Map(); this.dataset = {}; this.listeners = new Map(); this._text = ''; this.value = ''; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(_value) { throw new Error('markup is never written'); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }
  async dispatch(type) { for (const listener of this.listeners.get(type) ?? []) await listener({}); }
  findAll(predicate, found = []) { for (const child of this.children) { if (predicate(child)) found.push(child); child.findAll(predicate, found); } return found; }
}

const document = { createElement: tag => new FakeElement(tag) };
const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const button = (root, text) => root.findAll(el => el.tagName === 'BUTTON' && el.textContent === text)[0];
const byId = (root, id) => root.findAll(el => el.getAttribute('id') === id)[0];

function panel(replies) {
  const root = new FakeElement('section');
  const asked = [];
  const request = async (path, options) => { asked.push([path, options]); const reply = replies.shift(); if (reply instanceof Error) throw reply; return reply; };
  return { root, asked, connection: createClaudeConnection({ root, document, request }) };
}

const empty = { provider: 'claude', mode: 'api', key_present: false, key_storage: 'server_memory_only', catalog: null };
const keyed = { ...empty, key_present: true };
const cataloged = { ...keyed, catalog: { model_ids: ['claude-opus-5', 'claude-sonnet-5'], fetched_at_ms: 1 } };

test('the key is masked, sent once, and cleared from the field', async () => {
  const { root, asked, connection } = panel([empty, keyed]);
  await connection.load();
  assert.match(root.textContent, new RegExp(MESSAGES.intro.slice(0, 20)));
  // the direct-adapter key is independent of the credential gateway's, and the page says so
  assert.ok(root.textContent.includes(MESSAGES.independent));
  const key = byId(root, 'claude-key');
  assert.equal(key.getAttribute('type'), 'password');
  assert.equal(key.getAttribute('autocomplete'), 'off');
  key.value = 'sk-ant-test-only';
  await button(root, '키 저장').dispatch('click');
  await flush();
  assert.equal(key.value, '');
  assert.deepEqual(asked[1], ['/api/v1/connections/claude/key', { method: 'POST', body: { secret: 'sk-ant-test-only' } }]);
  assert.match(root.textContent, new RegExp(MESSAGES.keyStored));
});

test('catalog read and model choice are explicit owner actions', async () => {
  const { root, asked, connection } = panel([keyed, cataloged, { ...cataloged, model_choice_ref: {} }]);
  await connection.load();
  assert.equal(asked.length, 1);  // loading reads state only
  await button(root, '모델 목록 읽기').dispatch('click');
  await flush();
  const select = byId(root, 'claude-model');
  assert.deepEqual(select.children.map(option => option.getAttribute('value')), ['claude-opus-5', 'claude-sonnet-5']);
  select.value = 'claude-opus-5';
  await button(root, '이 모델 선택').dispatch('click');
  await flush();
  assert.deepEqual(asked[2][1].body, { model_id: 'claude-opus-5' });
  assert.match(root.textContent, /모델 선택을 기록했습니다\. \(claude-opus-5\)/);
});

test('a refused key and an unavailable provider say so', async () => {
  const rejected = Object.assign(new Error('x'), { code: 'provider_rejected' });
  const { root, connection } = panel([keyed, rejected]);
  await connection.load();
  await button(root, '모델 목록 읽기').dispatch('click');
  await flush();
  assert.match(root.textContent, new RegExp(ERROR_MESSAGES.provider_rejected));
});
