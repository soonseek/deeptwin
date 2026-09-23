// T025 tail: the account panel over a fake document, fetch and session adapter.
// Passwords are checked before any request, cleared after every attempt, and the
// rotated session's CSRF value is adopted.

import test from 'node:test';
import assert from 'node:assert/strict';

import { ERROR_MESSAGES, MESSAGES, createAccountPanel, passwordProblem } from '../static/account.mjs';

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
  findAll(predicate, found = []) { for (const child of this.children) { if (predicate(child)) found.push(child); child.findAll(predicate, found); } return found; }
}

const document = { createElement: tag => new FakeElement(tag) };

function panelWith(responses) {
  const root = new FakeElement('section');
  const sent = [];
  let csrf = 'c'.repeat(43);
  const session = { csrfToken: () => csrf, adopt: value => { csrf = value; } };
  const fetch = async (path, options) => {
    sent.push([path, options]);
    const [status, body] = responses.shift();
    return { ok: status < 400, status, json: async () => body };
  };
  const panel = createAccountPanel({ root, document, fetch, basePath: `/${'2'.repeat(32)}/`, session });
  const field = id => root.findAll(el => el.getAttribute('id') === id)[0];
  return { root, sent, panel, field, csrf: () => csrf };
}

test('the new password rule is checked before any request', () => {
  assert.equal(passwordProblem('old password here', 'x', 'x'), MESSAGES.short);
  assert.equal(passwordProblem('same same same 1', 'same same same 1', 'same same same 1'), MESSAGES.same);
  assert.equal(passwordProblem('a', 'fifteen letters!', 'fifteen letters?'), MESSAGES.mismatch);
  assert.equal(passwordProblem('a', '열다섯글자의한글비밀번호입니다다', '열다섯글자의한글비밀번호입니다다'), null);
});

test('a change sends both passwords once, clears the fields and adopts the rotated CSRF', async () => {
  const { root, sent, panel, field, csrf } = panelWith([[200, { state: 'authenticated', csrf_token: 'n'.repeat(43) }]]);
  field('account-current').value = 'old synthetic passphrase';
  field('account-new').value = 'new synthetic passphrase';
  field('account-confirm').value = 'new synthetic passphrase';
  await panel.changePassword();
  const [path, options] = sent[0];
  assert.equal(path, `/${'2'.repeat(32)}/session/password`);
  assert.equal(options.headers['X-DeepTwin-CSRF'], 'c'.repeat(43));
  assert.deepEqual(JSON.parse(options.body), { current_password: 'old synthetic passphrase', new_password: 'new synthetic passphrase' });
  for (const id of ['account-current', 'account-new', 'account-confirm']) assert.equal(field(id).value, '');
  assert.equal(csrf(), 'n'.repeat(43));
  assert.match(root.textContent, /다른 곳의 세션은 모두 끝났고/);
});

test('a wrong current password is said plainly and nothing is kept', async () => {
  const { root, panel, field } = panelWith([[401, { code: 'credentials' }]]);
  field('account-current').value = 'wrong synthetic phrase';
  field('account-new').value = 'new synthetic passphrase';
  field('account-confirm').value = 'new synthetic passphrase';
  await assert.rejects(panel.changePassword());
  assert.match(root.textContent, new RegExp(ERROR_MESSAGES.credentials));
  assert.equal(field('account-current').value, '');
});

test('revoke-others reports how many sessions ended', async () => {
  const { root, sent, panel } = panelWith([[200, { state: 'revoked_others', revoked: 2 }]]);
  await panel.revokeOthers();
  assert.equal(sent[0][0], `/${'2'.repeat(32)}/session/revoke-others`);
  assert.match(root.textContent, /다른 세션 2개를 끝냈습니다/);
});
