// T073/T070: the records page's backup section over a fake document and fake adapters.
// The state is the server's (no worker, ready, key lost, unreachable); a backup is
// created only after the actual preview and an explicit consent bound to its digest;
// a stale preview is stated; downloads are the bundle and its external receipt; a
// restore is staged as restored_review with every required step shown as required.

import test from 'node:test';
import assert from 'node:assert/strict';

import { backupConsent, backupPreviewSummary, restoreReview, RESTORE_REQUIREMENTS } from '../static/records.mjs';
import { MESSAGES, backupRoutes, createBackupPanel, excludedText, includedText } from '../static/records-backup.mjs';

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
    this.files = [];
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
const BACKUP_ID = '22222222-2222-4222-8222-222222222222';
const RESTORE_ID = '33333333-3333-4333-8333-333333333333';
const SHA = 'b'.repeat(64);

function previewValue(overrides = {}) {
  return {
    request_id: REQUEST_ID, preview_sha: SHA, records: 7, key_mode: 'instance_backup_key',
    recoverable_after_host_or_volume_loss: false,
    included: [{ category: 'records_and_lineage', rows: 7 }, { category: 'work_history', rows: 2 },
      { category: 'originals', count: 1, bytes: 2048 }],
    excluded: [
      { category: 'owner_authenticators_sessions_and_bootstrap_verifiers', reason: 'authenticator_never_restored', rows: 3 },
      { category: 'provider_credential_root', reason: 'separate_private_root', rows: null },
      { category: 'backup_key_volume', reason: 'separate_private_root', rows: null },
    ],
    ...overrides,
  };
}

const RECEIPT = { backup_id: BACKUP_ID, ciphertext_sha256: 'c'.repeat(64), ciphertext_size: 4096,
  encryption_profile_ref: 'age-x25519-v1', completed_at: '2026-09-25T00:00:00.000000Z',
  restore_verification_ref: { verified_at: 'x', scope: ['archive_members', 'record_lineage'] },
  key_mode: 'instance_backup_key', recoverable_after_host_or_volume_loss: false };

function reviewView() {
  return { restore_id: RESTORE_ID, state: 'restored_review', review: {
    dispatch: 'blocked', requires: [...RESTORE_REQUIREMENTS], environment_reactivation: 'explicit_required',
    active_vault_changed: false, not_restored: ['session_root', 'provider_credential_root'],
    in_flight_requests: 'remote_survival_unknown_until_confirmed', vault_id: 'v', backup_id: BACKUP_ID } };
}

function panel(replies, { worker = 'ready' } = {}) {
  const root = new FakeElement('section');
  const asked = [];
  const uploads = [];
  const request = async (path, options) => {
    asked.push([path, options]);
    if (path.endsWith('/api/v1/backups') && options === undefined) {
      return { worker, backups: [], restores: [], key_mode: 'instance_backup_key' };
    }
    const reply = replies.shift();
    if (reply instanceof Error) throw reply;
    return reply;
  };
  const upload = async (path, bytes) => { uploads.push([path, bytes]); return replies.shift(); };
  const crypto = { randomUUID: () => REQUEST_ID };
  const created = createBackupPanel({ root, document: { createElement: tag => new FakeElement(tag) }, basePath: BASE,
    request, upload, crypto });
  return { root, asked, uploads, panel: created };
}

const find = (root, predicate) => root.findAll(predicate);
const button = (root, text) => find(root, el => el.tagName === 'BUTTON' && el.textContent === text)[0];
const byId = (root, id) => find(root, el => el.getAttribute('id') === id)[0];

test('the preview summary and consent are exact and closed', () => {
  const summary = backupPreviewSummary(previewValue());
  assert.equal(summary.previewSha, SHA);
  assert.deepEqual(summary.included.map(entry => entry.category), ['records_and_lineage', 'work_history', 'originals']);
  assert.throws(() => backupPreviewSummary(previewValue({ included: [{ category: 'credentials', rows: 1 }] })));
  assert.throws(() => backupPreviewSummary(previewValue({ excluded: [] })));  // must state the exclusions
  assert.throws(() => backupConsent(summary, { confirmed: false, previewSha: SHA }));
  assert.throws(() => backupConsent(summary, { confirmed: true, previewSha: 'd'.repeat(64) }));
  assert.deepEqual(backupConsent(summary, { confirmed: true, previewSha: SHA }),
    { schema_version: 'backup-create-v1', request_id: REQUEST_ID, preview_sha: SHA, confirmed: true });
  assert.equal(includedText(summary.included[2]), '저장한 원본 1개 · 2.0 KiB');
  assert.match(excludedText(summary.excluded[0]), /인증 수단은 복원하지 않습니다.* · 지금 3행/);
  assert.throws(() => restoreReview({ ...reviewView(), review: { ...reviewView().review, dispatch: 'open' } }));
  assert.throws(() => restoreReview({ ...reviewView(), review: { ...reviewView().review, environment_reactivation: 'automatic' } }));
  assert.equal(backupRoutes(BASE).bundle(RESTORE_ID), `${BASE}api/v1/backups/restores/${RESTORE_ID}/bundle`);
  assert.throws(() => backupRoutes(BASE).ciphertext('../x'));
});

test('states are the server\'s: no worker, key lost, unreachable', async () => {
  for (const [worker, text] of [['not_configured', MESSAGES.notConfigured], ['key_unavailable', MESSAGES.keyLost],
    ['unreachable', MESSAGES.unreachable]]) {
    const { root, panel: backup } = panel([], { worker });
    await backup.load();
    assert.match(root.textContent, new RegExp(text.slice(0, 20)));
    const restoreArea = find(root, el => el.getAttribute('class') === 'backup-restore')[0];
    assert.equal(restoreArea.hidden, true, worker);  // no restore offered without a ready worker
  }
});

test('create needs the actual preview and a consent bound to its digest; downloads follow', async () => {
  const { root, asked, panel: backup } = panel([previewValue(), { backup_id: BACKUP_ID, receipt: RECEIPT, states: [] }]);
  await backup.load();
  await button(root, '백업에 포함될 내용 미리보기').dispatch('click');
  assert.deepEqual(asked[1], [`${BASE}api/v1/backups/preview`,
    { method: 'POST', body: { schema_version: 'backup-preview-request-v1', request_id: REQUEST_ID } }]);
  assert.match(root.textContent, /기록과 계보 7행/);
  assert.match(root.textContent, /소유자 인증 수단·세션·초기 설정 검증값: 인증 수단은 복원하지 않습니다/);
  assert.match(root.textContent, /별도 비공개 저장소라 백업하지 않습니다/);
  assert.match(root.textContent, new RegExp(`미리보기 SHA-256 ${SHA}`));
  const go = button(root, '이 내용으로 백업 만들기');
  await go.dispatch('click');
  assert.equal(asked.length, 2);  // no consent, no request
  assert.match(root.textContent, new RegExp(MESSAGES.needConsent));
  byId(root, 'backup-consent').checked = true;
  await go.dispatch('click');
  assert.deepEqual(asked[2], [`${BASE}api/v1/backups`, { method: 'POST',
    body: { schema_version: 'backup-create-v1', request_id: REQUEST_ID, preview_sha: SHA, confirmed: true } }]);
  const links = find(root, el => el.tagName === 'A').map(el => el.getAttribute('href'));
  assert.ok(links.includes(`${BASE}api/v1/backups/${BACKUP_ID}/ciphertext`));
  assert.ok(links.includes(`${BASE}api/v1/backups/${BACKUP_ID}/receipt`));
  assert.match(root.textContent, new RegExp(MESSAGES.notRecoverable));
});

test('a stale preview is stated and cleared; a lost key says so', async () => {
  const stale = Object.assign(new Error('x'), { code: 'conflict' });
  const { root, panel: backup } = panel([previewValue(), stale]);
  await backup.load();
  await button(root, '백업에 포함될 내용 미리보기').dispatch('click');
  byId(root, 'backup-consent').checked = true;
  await button(root, '이 내용으로 백업 만들기').dispatch('click');
  assert.match(root.textContent, new RegExp(MESSAGES.stale));
  assert.equal(button(root, '이 내용으로 백업 만들기'), undefined);
  const lost = Object.assign(new Error('x'), { code: 'unavailable', reason: 'backup_key_unavailable' });
  const second = panel([previewValue(), lost]);
  await second.panel.load();
  await button(second.root, '백업에 포함될 내용 미리보기').dispatch('click');
  byId(second.root, 'backup-consent').checked = true;
  await button(second.root, '이 내용으로 백업 만들기').dispatch('click');
  assert.match(second.root.textContent, /backup-key 볼륨이 없거나 손상되었습니다/);
});

test('without a ready worker the preview is shown but nothing can be created', async () => {
  const { root, panel: backup } = panel([previewValue()], { worker: 'not_configured' });
  await backup.load();
  await button(root, '백업에 포함될 내용 미리보기').dispatch('click');
  assert.match(root.textContent, /기록과 계보 7행/);
  assert.equal(byId(root, 'backup-consent'), undefined);
});

test('a restore uploads the bundle after its receipt and shows the staged review as required steps', async () => {
  const { root, asked, uploads, panel: backup } = panel([{ restore_id: RESTORE_ID, state: 'awaiting_bundle' }, reviewView()]);
  await backup.load();
  byId(root, 'restore-receipt').files = [{ text: async () => JSON.stringify(RECEIPT) }];
  const bytes = new Uint8Array([1, 2, 3]);
  byId(root, 'restore-bundle').files = [{ arrayBuffer: async () => bytes.buffer }];
  await button(root, '스테이징 영역에 복원').dispatch('click');
  assert.deepEqual(asked[1], [`${BASE}api/v1/backups/restores`, { method: 'POST',
    body: { schema_version: 'backup-restore-v1', request_id: REQUEST_ID, receipt: RECEIPT } }]);
  assert.equal(uploads[0][0], `${BASE}api/v1/backups/restores/${RESTORE_ID}/bundle`);
  assert.deepEqual([...uploads[0][1]], [1, 2, 3]);
  const steps = find(root, el => el.getAttribute('data-required') === 'true' && el.getAttribute('data-step'));
  assert.deepEqual(steps.map(el => el.getAttribute('data-step')), [...RESTORE_REQUIREMENTS]);
  assert.match(root.textContent, /검토 대기\(restored_review\)/);
  assert.match(root.textContent, new RegExp(MESSAGES.reactivation));
  assert.match(root.textContent, new RegExp(MESSAGES.staged));
});

test('a failed restore is stated and stages nothing', async () => {
  const { root, panel: backup } = panel([{ restore_id: RESTORE_ID, state: 'awaiting_bundle' },
    { restore_id: RESTORE_ID, state: 'failed', failure: 'the backup file differs from its external receipt',
      failure_code: 'restore_failed' }]);
  await backup.load();
  byId(root, 'restore-receipt').files = [{ text: async () => JSON.stringify(RECEIPT) }];
  byId(root, 'restore-bundle').files = [{ arrayBuffer: async () => new Uint8Array([9]).buffer }];
  await button(root, '스테이징 영역에 복원').dispatch('click');
  assert.match(root.textContent, /복원하지 못했습니다/);
  assert.equal(find(root, el => el.getAttribute('data-step')).length, 0);
  // missing files are asked for, not guessed
  byId(root, 'restore-bundle').files = [];
  await button(root, '스테이징 영역에 복원').dispatch('click');
  assert.ok(root.textContent.includes(MESSAGES.pickFiles));
});

const IDENTITY = `AGE-SECRET-KEY-1${'QPZRY9X8GF2TVDW0S3JN54KHCE6MUA7L'.repeat(2).slice(0, 58)}`;
const PORTABLE = { ...RECEIPT, key_mode: 'portable_recovery', recoverable_after_host_or_volume_loss: true };

function attributesAndText(root) {
  const all = [root, ...find(root, () => true)];
  return all.map(el => `${el._text} ${[...el.attributes.values()].join(' ')} ${JSON.stringify(el.dataset)}`).join('\n');
}

test('a portable restore takes the kept identity once: masked, cleared, framed, zeroed, never shown', async () => {
  const { root, asked, uploads, panel: backup } = panel([{ restore_id: RESTORE_ID, state: 'awaiting_bundle' },
    { ...reviewView(), key_mode: 'portable_recovery' }]);
  await backup.load();
  const input = byId(root, 'restore-recovery-identity');
  assert.equal(input.getAttribute('type'), 'password');
  assert.equal(input.getAttribute('autocomplete'), 'off');
  byId(root, 'restore-receipt').files = [{ text: async () => JSON.stringify(PORTABLE) }];
  byId(root, 'restore-bundle').files = [{ arrayBuffer: async () => new Uint8Array([7, 8]).buffer }];
  // without the identity nothing is asked of the server
  input.value = '';
  await button(root, '스테이징 영역에 복원').dispatch('click');
  assert.equal(asked.length, 1);
  assert.match(root.textContent, /휴대용 복구 백업입니다/);
  input.value = `  ${IDENTITY}  `;
  const sent = [];
  const original = uploads.push.bind(uploads);
  uploads.push = entry => { sent.push(new Uint8Array(entry[1])); return original(entry); };
  await button(root, '스테이징 영역에 복원').dispatch('click');
  assert.equal(input.value, '');  // cleared as soon as it was read
  assert.equal(uploads[0][0], `${BASE}api/v1/backups/restores/${RESTORE_ID}/portable-bundle`);
  const framed = new TextDecoder().decode(sent[0]);
  assert.equal(framed, `${IDENTITY}\n\u0007\u0008`);  // the identity line, then the bundle bytes
  assert.ok(uploads[0][1].every(byte => byte === 0), 'the sent buffer is zeroed afterwards');
  assert.ok(!attributesAndText(root).includes('AGE-SECRET-KEY'), 'the identity never reaches the DOM');
  assert.match(root.textContent, new RegExp(MESSAGES.portableStaged));
  assert.equal(find(root, el => el.getAttribute('data-step')).length, 3);
});

test('an instance-key restore never sends a typed identity; a removed backup offers only its receipt', async () => {
  const { root, uploads, panel: backup } = panel([{ restore_id: RESTORE_ID, state: 'awaiting_bundle' }, reviewView()]);
  await backup.load();
  byId(root, 'restore-recovery-identity').value = IDENTITY;
  byId(root, 'restore-receipt').files = [{ text: async () => JSON.stringify(RECEIPT) }];
  byId(root, 'restore-bundle').files = [{ arrayBuffer: async () => new Uint8Array([1]).buffer }];
  await button(root, '스테이징 영역에 복원').dispatch('click');
  assert.equal(uploads[0][0], `${BASE}api/v1/backups/restores/${RESTORE_ID}/bundle`);
  assert.deepEqual([...uploads[0][1]], [1]);
  assert.equal(byId(root, 'restore-recovery-identity').value, '');
  assert.match(root.textContent, new RegExp(MESSAGES.identityNotUsed));

  const listed = new FakeElement('section');
  const deleted = createBackupPanel({ root: listed, document: { createElement: tag => new FakeElement(tag) },
    basePath: BASE, upload: async () => ({}), crypto: { randomUUID: () => REQUEST_ID },
    request: async () => ({ worker: 'ready', restores: [], backups: [
      { backup_id: BACKUP_ID, completed_at: 't', ciphertext_size: 10, ciphertext_sha256: 'c'.repeat(64),
        ciphertext_state: 'deleted' }] }) });
  await deleted.load();
  const links = find(listed, el => el.tagName === 'A').map(el => el.getAttribute('href'));
  assert.deepEqual(links, [`${BASE}api/v1/backups/${BACKUP_ID}/receipt`]);
  assert.match(listed.textContent, new RegExp(MESSAGES.deleted));
});
