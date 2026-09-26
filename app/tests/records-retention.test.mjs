// T073: the records page's retention section over a fake document and a fake request
// adapter. Per category it states what the server keeps, for how long, that nothing is
// deleted automatically, and where the owner may clean up; a cleanup needs a selection,
// the server's actual preview and a separate consent bound to that preview's digest; a
// scope that changed is stated as stale; kept items are never selectable.

import test from 'node:test';
import assert from 'node:assert/strict';

import { cleanupConsent, cleanupPreviewSummary, retentionState } from '../static/records.mjs';
import { MESSAGES, categoryText, createRetentionPanel, retentionRoutes } from '../static/records-retention.mjs';

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.listeners = new Map();
    this._text = '';
    this.hidden = false;
    this.checked = false;
    this.disabled = false;
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

const BASE = `/${'a'.repeat(32)}/`;
const REQUEST_ID = '11111111-1111-4111-8111-111111111111';
const OLD = 'backup:22222222-2222-4222-8222-222222222222';
const NEW = 'backup:44444444-4444-4444-8444-444444444444';
const FAILED = 'restore:33333333-3333-4333-8333-333333333333';
const SHA = 'e'.repeat(64);

function category(name, kept, cleanup, extra = {}) {
  return { category: name, kept, automatic_deletion: 'never', owner_cleanup: cleanup, reason: 'r', ...extra };
}

function stateValue(overrides = {}) {
  return {
    schema_version: 'retention-state-v1',
    policy: { core_mode: 'manual_only', automatic_deletion: 'none', policy_ref: { kind: 'retention_policy' } },
    categories: [
      category('core_records', 'forever', 'not_offered', { reason: 'append_only_history', count: 12, events: 30 }),
      category('deletion_tombstones', 'forever', 'not_offered', { reason: 'record_of_a_deletion', count: 1 }),
      category('originals', 'until_owner_deletes', 'work_screen', { count: 2, bytes: 4096, deleted_count: 1 }),
      category('backups', 'until_owner_cleanup', 'this_screen', { reason: 'newest_backup_kept', count: 2, bytes: 8192,
        eligible_count: 1, eligible_bytes: 4096 }),
      category('staged_restores', 'until_owner_cleanup', 'this_screen', { count: 1, bytes: 10, eligible_count: 1 }),
      category('regenerable_caches', 'not_stored', 'nothing_stored', { count: 0 }),
      category('raw_audio', 'not_stored', 'nothing_stored', { reason: 'ephemeral_only', count: 0 }),
    ],
    items: [
      { item_id: NEW, category: 'backups', created_at: 't2', bytes: 4096, state: 'stored', eligible: false,
        reason: 'newest_backup_kept', removes: 'encrypted_backup_file', keeps: ['external_receipt'] },
      { item_id: OLD, category: 'backups', created_at: 't1', bytes: 4096, state: 'stored', eligible: true,
        reason: 'older_backup', removes: 'encrypted_backup_file', keeps: ['external_receipt', 'tombstone'] },
      { item_id: FAILED, category: 'staged_restores', created_at: 't3', bytes: 10, state: 'failed', eligible: true,
        reason: 'failed_restore', removes: 'staged_restore_copy', keeps: ['restore_status'] },
    ],
    cleanups: [],
    ...overrides,
  };
}

function previewValue(items = [OLD], overrides = {}) {
  return { schema_version: 'retention-cleanup-preview-v1', request_id: REQUEST_ID, reason_code: 'user_requested',
    items: items.map(item_id => ({ item_id, category: 'backups', bytes: 4096, removes: 'encrypted_backup_file',
      keeps: ['external_receipt', 'tombstone'] })),
    item_count: items.length, byte_count: 4096 * items.length,
    not_reached: ['copies_already_downloaded'], never_deleted: ['core_records', 'newest_backup'],
    preview_sha256: SHA, ...overrides };
}

function panel(replies, state = stateValue()) {
  const root = new FakeElement('section');
  const asked = [];
  const request = async (path, options) => {
    asked.push([path, options]);
    if (path.endsWith('/api/v1/retention') && options === undefined) return state;
    const reply = replies.shift();
    if (reply instanceof Error) throw reply;
    return reply;
  };
  const created = createRetentionPanel({ root, document: { createElement: tag => new FakeElement(tag) }, basePath: BASE,
    request, crypto: { randomUUID: () => REQUEST_ID } });
  return { root, asked, panel: created };
}

const find = (root, predicate) => root.findAll(predicate);
const button = (root, text) => find(root, el => el.tagName === 'BUTTON' && el.textContent === text)[0];
const byId = (root, id) => find(root, el => el.getAttribute('id') === id)[0];
const box = (root, itemId) => find(root, el => el.tagName === 'INPUT' && el.getAttribute('value') === itemId)[0];

test('the state is closed: core records are always kept and nothing deletes automatically', () => {
  assert.equal(retentionState(stateValue()).categories.length, 7);
  assert.throws(() => retentionState(stateValue({ policy: { core_mode: 'expiring', automatic_deletion: 'none' } })));
  const auto = stateValue();
  auto.categories[3] = { ...auto.categories[3], automatic_deletion: 'after_90_days' };
  assert.throws(() => retentionState(auto));
  const offered = stateValue();
  offered.categories[0] = { ...offered.categories[0], owner_cleanup: 'this_screen' };
  assert.throws(() => retentionState(offered));
  assert.throws(() => retentionState(stateValue({ items: [{ item_id: 'core:x', eligible: true, bytes: 1 }] })));
  assert.match(categoryText(stateValue().categories[0]), /핵심 기록.*기한 없이 보존 · 자동 삭제 없음 · 12개 · 사건 30개 · 정리 대상이 아닙니다/);
  assert.match(categoryText(stateValue().categories[2]), /업무 화면의 "원본 삭제"/);
  assert.equal(retentionRoutes(BASE).preview, `${BASE}api/v1/retention/cleanup/preview`);
  assert.throws(() => retentionRoutes('/x/'));
});

test('consent binds the exact previewed scope and is never implicit', () => {
  const summary = cleanupPreviewSummary(previewValue());
  assert.throws(() => cleanupConsent(summary, { confirmed: false, previewSha: SHA }));
  assert.throws(() => cleanupConsent(summary, { confirmed: true, previewSha: 'f'.repeat(64) }));
  assert.deepEqual(cleanupConsent(summary, { confirmed: true, previewSha: SHA }), {
    schema_version: 'retention-cleanup-v1', request_id: REQUEST_ID, item_ids: [OLD], reason_code: 'user_requested',
    preview_sha256: SHA, confirmed: true });
  assert.throws(() => cleanupPreviewSummary(previewValue([], { items: [] })));
  assert.throws(() => cleanupPreviewSummary(previewValue([OLD], { reason_code: 'because' })));
});

test('categories render from the server state; kept items are not selectable', async () => {
  const { root, panel: retention } = panel([]);
  await retention.load();
  assert.match(root.textContent, /자동 삭제는 없습니다/);
  const rows = find(root, el => el.getAttribute('data-category'));
  assert.deepEqual(rows.map(el => el.getAttribute('data-category')), ['core_records', 'deletion_tombstones', 'originals',
    'backups', 'staged_restores', 'regenerable_caches', 'raw_audio']);
  assert.ok(rows.every(el => el.getAttribute('data-automatic-deletion') === 'never'));
  assert.equal(box(root, NEW).disabled, true);
  assert.equal(box(root, OLD).disabled, false);
  assert.equal(box(root, OLD).checked, false);  // nothing is preselected
  assert.match(root.textContent, /가장 최근 백업은 항상 남깁니다/);
});

test('a cleanup needs a selection, the actual preview and a separate consent', async () => {
  const receipt = { request_id: REQUEST_ID, removed: [{ item_id: OLD, bytes_removed: true }], byte_count: 4096,
    preview_sha256: SHA };
  const { root, asked, panel: retention } = panel([previewValue(), receipt]);
  await retention.load();
  await button(root, '선택한 항목 정리 미리보기').dispatch('click');
  assert.equal(asked.length, 1);  // nothing selected: nothing asked
  assert.match(root.textContent, new RegExp(MESSAGES.pick));
  box(root, OLD).checked = true;
  await button(root, '선택한 항목 정리 미리보기').dispatch('click');
  assert.deepEqual(asked[1], [`${BASE}api/v1/retention/cleanup/preview`, { method: 'POST', body: {
    schema_version: 'retention-cleanup-preview-v1', request_id: REQUEST_ID, item_ids: [OLD], reason_code: 'user_requested' } }]);
  assert.match(root.textContent, new RegExp(`미리보기 SHA-256 ${SHA}`));
  assert.match(root.textContent, /지움: 암호화된 백업 파일 · 남김: 외부 영수증, 삭제 표시/);
  assert.match(root.textContent, /닿지 않는 것: 이미 내려받은 사본/);
  assert.match(root.textContent, /어떤 경우에도 지우지 않는 것: 핵심 기록, 가장 최근 백업/);
  await button(root, '이 내용대로 정리').dispatch('click');
  assert.equal(asked.length, 2);  // no consent, no request
  assert.match(root.textContent, new RegExp(MESSAGES.needConsent));
  byId(root, 'retention-consent').checked = true;
  await button(root, '이 내용대로 정리').dispatch('click');
  assert.deepEqual(asked[2], [`${BASE}api/v1/retention/cleanup`, { method: 'POST', body: {
    schema_version: 'retention-cleanup-v1', request_id: REQUEST_ID, item_ids: [OLD], reason_code: 'user_requested',
    preview_sha256: SHA, confirmed: true } }]);
  assert.match(root.textContent, new RegExp(MESSAGES.cleaned));
});

test('a scope that changed since its preview is stated as stale and cleared', async () => {
  const stale = Object.assign(new Error('x'), { code: 'conflict' });
  const { root, panel: retention } = panel([previewValue(), stale]);
  await retention.load();
  box(root, OLD).checked = true;
  await button(root, '선택한 항목 정리 미리보기').dispatch('click');
  byId(root, 'retention-consent').checked = true;
  await button(root, '이 내용대로 정리').dispatch('click');
  assert.match(root.textContent, new RegExp(MESSAGES.stale));
  assert.equal(button(root, '이 내용대로 정리'), undefined);
});
