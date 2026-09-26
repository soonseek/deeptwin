// The settings page (2026-09-26 phase 2): the operations sections moved here from the records
// page. Over a fake document: without a session the sub-navigation still lists every section
// and says so, and backup and retention state only what this server does (no backup claimed
// without a worker, no automatic deletion); one panel is shown at a time, chosen by the
// address's fragment, and an old deep link to a section opens the panel that holds it.

import test from 'node:test';
import assert from 'node:assert/strict';

import { HUB_MESSAGES, SETTINGS_ENTRIES, SETTINGS_MOUNT_ID } from '../static/settings.mjs';
import { BACKUP_MOUNT_ID, MESSAGES, RETENTION_MOUNT_ID, bootSettings, panelFor, showPanel } from '../static/settings-page.mjs';

class FakeElement {
  constructor(tagName, id = null) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.parent = null;
    this.hidden = false;
    this._text = '';
    if (id) this.attributes.set('id', id);
  }

  get id() { return this.attributes.get('id') ?? ''; }

  set id(value) { this.attributes.set('id', String(value)); }

  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }

  set textContent(value) { this._text = String(value); this.children = []; }

  set innerHTML(_value) { throw new Error('markup is never written'); }

  append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }

  replaceChildren(...nodes) { this.children = []; this._text = ''; this.append(...nodes); }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }

  removeAttribute(name) { this.attributes.delete(name); }

  closest(selector) {
    const name = selector.slice(1, -1);
    for (let node = this; node; node = node.parent) if (node.attributes.has(name)) return node;
    return null;
  }

  findAll(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.findAll(predicate, found);
    }
    return found;
  }
}

// settings.html's panels and mounts, as a tree
function settingsDocument() {
  const body = new FakeElement('body');
  const status = new FakeElement('p', 'session-status');
  const hub = new FakeElement('nav', SETTINGS_MOUNT_ID);
  body.append(status, hub);
  const panels = {
    'settings-account': ['records-account'], 'settings-models': ['records-connection', 'records-credentials'],
    'settings-budgets': ['records-budgets'], 'settings-backup': [BACKUP_MOUNT_ID, RETENTION_MOUNT_ID],
    'settings-update': ['records-update'], 'settings-extensions': [], 'settings-grants': [],
  };
  for (const [id, mounts] of Object.entries(panels)) {
    const panel = new FakeElement('section', id);
    panel.setAttribute('data-settings-panel', id.replace('settings-', ''));
    for (const mount of mounts) panel.append(new FakeElement('section', mount));
    body.append(panel);
  }
  const all = () => [body, ...body.findAll(() => true)];
  const document = {
    createElement: tag => new FakeElement(tag),
    getElementById: id => all().find(node => node.id === id) ?? null,
    querySelectorAll(selector) {
      if (selector === '[data-settings-panel]') return all().filter(node => node.attributes.has('data-settings-panel'));
      if (selector === `#${SETTINGS_MOUNT_ID} a[data-panel]`) return hub.findAll(node => node.tagName === 'A' && node.attributes.has('data-panel'));
      throw new Error(`unexpected selector ${selector}`);
    },
  };
  return { document, body, hub, status };
}

const unauthenticated = async () => ({ ok: false, status: 401, headers: { get: () => 'application/json' },
  json: async () => ({ code: 'unauthenticated' }), text: async () => '{"code":"unauthenticated"}' });

test('without a session the list still offers every section, and backup and retention say what the server does', async () => {
  const { document, hub, status } = settingsDocument();
  const result = await bootSettings({ document, location: { pathname: '/settings.html', hash: '' }, fetch: unauthenticated,
    window: null });
  assert.equal(result.established, false);
  assert.equal(status.textContent, HUB_MESSAGES.unauthenticated);
  assert.equal(hub.findAll(el => el.tagName === 'A').length, SETTINGS_ENTRIES.length);
  assert.match(document.getElementById(BACKUP_MOUNT_ID).textContent, /백업 워커가 아직 연결되어 있지 않습니다/);
  assert.match(document.getElementById(BACKUP_MOUNT_ID).textContent, new RegExp(MESSAGES.backupHow.slice(0, 20)));
  assert.match(document.getElementById(RETENTION_MOUNT_ID).textContent, /자동 삭제는 없습니다/);
  // nothing that could send a command was mounted
  assert.equal(document.getElementById('records-account').children.length, 0);
  assert.equal(document.getElementById('records-credentials').children.length, 0);
});

test('one panel at a time: the fragment picks it, an old deep link opens the panel that holds it', async () => {
  const { document, hub } = settingsDocument();
  await bootSettings({ document, location: { pathname: '/settings.html', hash: '#records-credentials' }, fetch: unauthenticated,
    window: null });
  const shown = () => document.querySelectorAll('[data-settings-panel]').filter(panel => !panel.hidden).map(panel => panel.id);
  assert.deepEqual(shown(), ['settings-models']);
  const current = () => hub.findAll(el => el.tagName === 'A' && el.getAttribute('aria-current') === 'true').map(el => el.textContent);
  assert.deepEqual(current(), ['모델 연결']);
  assert.equal(showPanel(document, '#settings-backup'), 'settings-backup');
  assert.deepEqual(shown(), ['settings-backup']);
  assert.deepEqual(current(), ['백업·보존']);
  // the first panel when nothing (or nothing known) is named
  assert.equal(panelFor(document, '').id, 'settings-account');
  assert.equal(panelFor(document, '#no-such-section').id, 'settings-account');
  assert.equal(panelFor(document, '#%E0%A4%A').id, 'settings-account');  // a malformed escape names nothing
  assert.equal(showPanel(document, '#settings-extensions'), 'settings-extensions');
  assert.deepEqual(current(), ['확장']);
});
