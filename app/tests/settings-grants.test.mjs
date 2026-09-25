// T043: the settings page's browser grants section (static/browser-grants.mjs), node unit
// cases: the owner's form becomes one exact `browser-grant-command-v1` (or is refused
// locally), a grant view becomes the lines the screen shows — recipients, sources, the
// projection (pure navigation, or a parameter with a count of declared values: never a
// value), tools, expiry, state — and the section renders server text through textContent
// only, with a revoke control on active grants alone.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  COMMAND_SCHEMA,
  DEFAULT_LIMITS,
  GRANTS_MOUNT_ID,
  MESSAGES,
  OWNER_SOURCE,
  bootGrants,
  grantCommand,
  grantLines,
  renderGrants,
} from '../static/browser-grants.mjs';

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this._text = '';
  }

  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }

  set textContent(value) { this._text = String(value); this.children = []; }

  set innerHTML(_value) { throw new Error('innerHTML is never used'); }

  append(...nodes) { this.children.push(...nodes); }

  prepend(...nodes) { this.children.unshift(...nodes); }

  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }

  addEventListener(name, listener) { this.listeners.set(name, listener); }

  findAll(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.findAll(predicate, found);
    }
    return found;
  }
}

const document = { createElement: tag => new FakeElement(tag) };
const NOW = new Date('2026-09-25T00:00:00.000Z');

function view(changes = {}) {
  return {
    grant_id: '11111111-1111-5111-8111-111111111111', label: '공개 문서 검색 <b>', state: 'active',
    tools: ['browser_read', 'browser_screenshot'], sources: ['https://docs.example.org/'],
    recipients: ['docs.example.org', 'cdn.example.org'],
    projection: {
      entries: [{ url: 'https://docs.example.org/', parameters: [] },
        { url: 'https://docs.example.org/search', parameters: [{ name: 'q', source: 'topic' }] }],
      data_sources: [{ source_id: 'topic', value_count: 2, value_sha256: ['a'.repeat(64), 'b'.repeat(64)] }],
    },
    expires_at_utc: '2026-10-02T00:00:00.000000Z', decided_at_utc: '2026-09-25T00:00:00.000000Z',
    ...changes,
  };
}

test('the owner form becomes one exact grant command', () => {
  const command = grantCommand({
    label: ' 공개 문서 검색 ', url: 'https://docs.example.org/api/search', parameter: 'q',
    values: 'deeptwin\n공개 자료\n', recipients: 'CDN.example.org', days: 7,
    tools: ['browser_screenshot', 'browser_read', 'browser_read', 'browser_click'],
  }, { now: NOW, commandId: '22222222-2222-4222-8222-222222222222' });
  assert.deepEqual(command, {
    schema_version: COMMAND_SCHEMA, command_id: '22222222-2222-4222-8222-222222222222', label: '공개 문서 검색',
    tools: ['browser_read', 'browser_screenshot'], sources: ['https://docs.example.org/api/'],
    recipients: ['docs.example.org', 'cdn.example.org'],
    entries: [{ url: 'https://docs.example.org/api/search', parameters: [{ name: 'q', source: OWNER_SOURCE }] }],
    data_sources: [{ source_id: OWNER_SOURCE, values: ['deeptwin', '공개 자료'] }],
    limits: { ...DEFAULT_LIMITS }, expires_at_utc: '2026-10-02T00:00:00.000000Z',
  });
  const pure = grantCommand({ label: 'x', url: 'https://docs.example.org/', days: 1, tools: ['browser_read'] },
    { now: NOW, commandId: '33333333-3333-4333-8333-333333333333' });
  assert.deepEqual(pure.entries, [{ url: 'https://docs.example.org/', parameters: [] }]);
  assert.deepEqual(pure.data_sources, []);
  for (const broken of [
    { url: 'http://docs.example.org/' }, { url: 'https://docs.example.org/?q=1' },
    { url: 'https://docs.example.org:8443/' }, { url: 'https://u:p@docs.example.org/' }, { url: 'not a url' },
    { tools: [] }, { label: '' }, { days: 0 }, { days: 91 }, { parameter: 'q', values: '' },
    { parameter: 'q', values: 'a\na' }, { values: 'orphan value' }, { parameter: 'a b', values: 'x' },
    { recipients: 'bad host!' },
  ]) {
    assert.throws(() => grantCommand({ label: 'x', url: 'https://docs.example.org/', days: 7,
      tools: ['browser_read'], ...broken }, { now: NOW, commandId: 'c' }), TypeError, JSON.stringify(broken));
  }
});

test('a grant view shows recipients, sources, projection, tools, expiry and state, never a value', () => {
  const lines = grantLines(view());
  assert.equal(lines.recipients, '받는 곳: docs.example.org, cdn.example.org');
  assert.equal(lines.sources, '탐색 범위: https://docs.example.org/');
  assert.deepEqual(lines.projection, [
    `https://docs.example.org/ · ${MESSAGES.pureNavigation}`,
    `https://docs.example.org/search?q ← 선언한 값 2개 · ${MESSAGES.valuesOnlyDigests}`,
  ]);
  assert.equal(lines.tools, '도구: 본문 읽기, 화면 캡처');
  assert.match(lines.expiry, /^만료: .*2026.*UTC$/);
  assert.equal(lines.state, '유효');
  assert.equal(grantLines(view({ state: 'revoked' })).state, '철회됨');
  assert.equal(grantLines(view({ state: 'expired' })).state, '만료됨');
});

test('the section renders text only, with revoke on active grants and the create form', () => {
  const root = new FakeElement('section');
  const revoked = [];
  const created = [];
  renderGrants({ root, document, state: { grants: [view(), view({ grant_id: 'g2', state: 'revoked' })] },
    status: '상태', onRevoke: item => revoked.push(item.grant_id), onCreate: form => created.push(form) });
  const rows = root.findAll(node => node.tagName === 'LI' && node.getAttribute('data-grant-id') !== null);
  assert.deepEqual(rows.map(row => row.getAttribute('data-state')), ['active', 'revoked']);
  assert.match(rows[0].textContent, /공개 문서 검색 <b>/);  // markup-looking text stays text
  assert.match(rows[0].textContent, /받는 곳: docs\.example\.org, cdn\.example\.org/);
  assert.ok(!rows[0].textContent.includes('a'.repeat(64)), 'digests are not shown either');
  const buttons = root.findAll(node => node.tagName === 'BUTTON' && node.getAttribute('type') === 'button');
  assert.equal(buttons.length, 1);
  buttons[0].listeners.get('click')();
  assert.deepEqual(revoked, ['11111111-1111-5111-8111-111111111111']);
  const form = root.findAll(node => node.tagName === 'FORM')[0];
  assert.ok(form, 'the create form is offered');
  assert.equal(root.findAll(node => node.getAttribute('role') === 'status')[0].textContent, '상태');
  const empty = new FakeElement('section');
  renderGrants({ root: empty, document, state: { grants: [] } });
  assert.match(empty.textContent, /아직 만든 브라우저 접근 허가가 없습니다/);
});

test('without an owner session the section says so and offers nothing', async () => {
  const root = new FakeElement('section');
  const fakeDocument = { ...document, getElementById: id => (id === GRANTS_MOUNT_ID ? root : null) };
  const result = await bootGrants({ document: fakeDocument, location: { pathname: `/${'2'.repeat(32)}/settings.html` },
    fetch: async () => ({ ok: false, status: 401, json: async () => ({ code: 'unauthenticated', message: 'no' }) }) });
  assert.deepEqual(result, { established: false });
  assert.match(root.textContent, new RegExp(MESSAGES.unauthenticated));
  assert.equal(root.findAll(node => node.tagName === 'FORM').length, 0);
});

test('the settings page mounts the section and loads its module', () => {
  const html = readFileSync(new URL('../static/settings.html', import.meta.url), 'utf8');
  assert.match(html, /<section id="settings-grants"/);
  assert.match(html, /<script type="module" src="\.\/browser-grants\.mjs"><\/script>/);
});
