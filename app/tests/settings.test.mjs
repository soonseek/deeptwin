import test from 'node:test';
import assert from 'node:assert/strict';

import { readFileSync } from 'node:fs';

import {
  HUB_MESSAGES,
  SETTINGS_ENTRIES,
  SETTINGS_LINKED_PAGES,
  SETTINGS_MOUNT_ID,
  catalogURL,
  connectionOptions,
  hubStateLines,
  modelSelectionPayload,
  renderSettingsHub,
  settingsHub,
  usagePolicyPayload,
} from '../static/settings.mjs';
import { SHELL_SECONDARY } from '../static/ui-shell.mjs';

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this._text = '';
  }

  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }

  set textContent(value) { this._text = String(value); this.children = []; }

  append(...nodes) { this.children.push(...nodes); }

  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }

  findAll(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.findAll(predicate, found);
    }
    return found;
  }
}

test('the settings sub-navigation lists every operations section, none required', () => {
  const hub = settingsHub();
  assert.deepEqual(hub.map(entry => entry.id), ['account', 'models', 'budgets', 'backup', 'update', 'extensions', 'grants']);
  assert.ok(hub.every(entry => entry.required === false && entry.available === 'everywhere' && entry.exportRequired === false));
  // in-page links: each opens its own panel on this page, in any order
  assert.ok(hub.every(entry => entry.href === `#${entry.panel}`));
  const root = new FakeElement('nav');
  renderSettingsHub({ root, document: { createElement: tag => new FakeElement(tag) }, current: 'settings-backup',
    lines: hubStateLines({ backups: { worker: 'ready', backups: [{}, {}] },
      retention: { items: [{ eligible: true }, { eligible: false }] } }) });
  const links = root.findAll(el => el.tagName === 'A');
  assert.deepEqual(links.map(el => el.getAttribute('href')), SETTINGS_ENTRIES.map(entry => entry.href));
  assert.deepEqual(links.filter(el => el.getAttribute('aria-current') === 'true').map(el => el.textContent), ['백업·보존']);
  assert.match(root.textContent, new RegExp(HUB_MESSAGES.noFinalStep));
  // backup and retention share the 백업·보존 panel, so its entry carries both state lines
  const backup = root.findAll(el => el.getAttribute('data-entry') === 'backup')[0];
  assert.match(backup.textContent, /백업 워커 연결됨 · 만든 백업 2개/);
  assert.match(backup.textContent, /자동 삭제 없음 · 지금 정리할 수 있는 항목 1개/);
});

test('every signed-in page reaches settings from the shell; the start screen keeps its header link', () => {
  assert.deepEqual(SHELL_SECONDARY.map(item => [item.id, item.href]), [['settings', './settings.html']]);
  for (const page of ['work.html', 'observe.html', 'records.html', 'versions.html', 'settings.html']) {
    const html = readFileSync(new URL(`../static/${page}`, import.meta.url), 'utf8');
    assert.match(html, /<div id="app" class="app-shell" data-page="[a-z]+">/, page);
    assert.match(html, /<main id="main">/, page);
  }
  for (const page of SETTINGS_LINKED_PAGES) {
    const html = readFileSync(new URL(`../static/${page}`, import.meta.url), 'utf8');
    assert.match(html, /<nav class="app-settings" aria-label="설정"><a href="\.\/settings\.html"[^>]*>설정<\/a><\/nav>/, page);
  }
  const hub = readFileSync(new URL('../static/settings.html', import.meta.url), 'utf8');
  assert.match(hub, new RegExp(`id="${SETTINGS_MOUNT_ID}"`));
  assert.match(readFileSync(new URL('../static/index.html', import.meta.url), 'utf8'), /href="\/settings\.html"/);
});

const providers = [{
  id: 'codex', default_mode: 'subscription', modes: [
    { id: 'subscription', label: 'ChatGPT 구독', billing: 'subscription', auth_mode: 'chatgpt' },
    { id: 'api', label: '별도 API', billing: 'api', auth_mode: 'api_key' },
  ],
}, {
  id: 'claude', default_mode: 'api', modes: [
    { id: 'api', label: 'Claude API', billing: 'api', auth_mode: 'api_key' },
  ],
}];

test('provider modes preserve distinct billing paths and never invent Claude subscription', () => {
  const options = connectionOptions(providers);
  assert.deepEqual(options.map(item => [item.provider, item.mode]), [
    ['codex', 'subscription'], ['claude', 'api'], ['codex', 'api'],
  ]);
  assert.equal(options.some(item => item.provider === 'claude' && item.mode === 'subscription'), false);
  assert.equal(options.find(item => item.provider === 'codex' && item.mode === 'subscription').billing, 'subscription');
  assert.equal(options.find(item => item.provider === 'codex' && item.mode === 'api').billing, 'api');
});

test('catalog URL binds both provider and mode without accepting path injection', () => {
  assert.equal(catalogURL('codex', 'subscription'), '/api/model-catalogs/codex?mode=subscription');
  assert.equal(catalogURL('claude', 'api', { refresh: true }), '/api/model-catalogs/claude/refresh?mode=api');
  for (const [provider, mode] of [['claude', 'subscription'], ['../x', 'api'], ['codex', 'other']]) {
    assert.throws(() => catalogURL(provider, mode));
  }
});

test('model selection payload keeps the literal catalog path and optional thinking', () => {
  assert.deepEqual(modelSelectionPayload({
    provider: 'claude', mode: 'api', model: 'claude-account-model', effort: 'high',
    thinking: 'adaptive', catalog_id: 'catalog-123',
  }), {
    provider: 'claude', mode: 'api', model: 'claude-account-model', effort: 'high',
    thinking: 'adaptive', catalog_id: 'catalog-123',
  });
  assert.throws(() => modelSelectionPayload({
    provider: 'claude', mode: 'subscription', model: 'fake', effort: 'high', catalog_id: 'catalog-1',
  }));
});

test('usage policy remains finite and API mode requires an explicit positive money cap', () => {
  const subscription = usagePolicyPayload({
    provider_mode: 'subscription', max_model_calls: 64, max_tool_calls: 128,
    max_wall_seconds: 1200, max_output_bytes: 67108864,
  });
  assert.equal(subscription.currency, null);
  assert.equal(subscription.max_api_microunits, null);
  const api = usagePolicyPayload({
    provider_mode: 'api', max_model_calls: 64, max_tool_calls: 128,
    max_wall_seconds: 1200, max_output_bytes: 67108864,
    currency: 'USD', max_api_microunits: 5_000_000,
  });
  assert.equal(api.currency, 'USD');
  assert.equal(api.max_api_microunits, 5_000_000);
  for (const draft of [
    { ...api, max_api_microunits: 0 },
    { ...api, currency: null },
    { ...subscription, max_model_calls: Infinity },
    { ...subscription, max_wall_seconds: 0 },
  ]) assert.throws(() => usagePolicyPayload(draft));
});
