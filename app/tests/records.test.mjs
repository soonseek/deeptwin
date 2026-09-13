// T073 (US7, UX-AC08): the records GUI logic — log/export/backup/retention
// sections reachable from anywhere, export consent bound to the ACTUAL
// previewed content, deletion bound to its exact preview, backup key modes
// closed with the recovery secret never stored, and NO mandatory final
// export step. Pure logic mirrored against the server contracts
// (app/operations/export.py, retention.py); the Python side holds a
// drift test over these constant lists.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  BACKUP_KEY_MODES,
  DELETION_REASONS,
  EXPORT_CATEGORIES,
  MISSING_REASONS,
  backupSettingsPayload,
  completionGate,
  deletionRequestPayload,
  exportConsent,
  exportRequestPayload,
  previewSummary,
  recordsRoutes,
} from '../static/records.mjs';

const REQUEST_ID = '11111111-2222-4333-8444-555555555555';
const STAMP = '2026-09-13T00:00:00.000000Z';
const POLICY_REF = { kind: 'access_policy', id: REQUEST_ID, version: 1 };
const CONSENT_REF = { kind: 'run_consent', id: REQUEST_ID, version: 1 };

function requestFields(overrides = {}) {
  return {
    requestId: REQUEST_ID,
    scope: 'work-7 journey',
    categories: ['events', 'originals'],
    includeRawRefs: [],
    redactionPolicyRef: POLICY_REF,
    authorConsentRef: CONSENT_REF,
    createdAt: STAMP,
    ...overrides,
  };
}

function preview() {
  return {
    request_id: REQUEST_ID,
    preview_sha: 'ab'.repeat(32),
    items: [
      { category: 'events', content_mode: 'redacted' },
      { category: 'events', content_mode: 'redacted' },
      { category: 'originals', content_mode: 'raw' },
    ],
    missing: [{ category: 'alternatives', reason: 'not_selected' }],
  };
}

test('every records section is reachable from anywhere with no ordering', () => {
  const routes = recordsRoutes();
  assert.deepEqual(routes.map(route => route.id),
    ['logs', 'export', 'backup', 'retention']);
  for (const route of routes) {
    assert.equal(route.available, 'everywhere');
    assert.equal('requires' in route, false); // no step ordering at all
  }
});

test('an export selects explicit closed categories or nothing at all', () => {
  const payload = exportRequestPayload(requestFields());
  assert.deepEqual(Object.keys(payload).sort(), [
    'author_consent_ref', 'created_at', 'include_raw_refs',
    'redaction_policy_ref', 'request_id', 'scope', 'selected_categories',
  ]);
  assert.deepEqual(payload.selected_categories, ['events', 'originals']);
  for (const categories of [
    [], ['events', 'events'], ['hidden_reasoning'], ['credentials'],
    ['events', 'everything'],
  ]) {
    assert.throws(() => exportRequestPayload(requestFields({ categories })));
  }
  assert.throws(() => exportRequestPayload(
    requestFields({ includeRawRefs: Array(65).fill(POLICY_REF) })));
});

test('the summary shows the actual included content per category', () => {
  const summary = previewSummary(preview());
  assert.deepEqual(summary.counts, { events: 2, originals: 1 });
  assert.deepEqual(summary.missing,
    [{ category: 'alternatives', reason: 'not_selected' }]);
  assert.equal(summary.previewSha, 'ab'.repeat(32));
  const foreign = preview();
  foreign.missing[0].reason = 'because-reasons';
  assert.throws(() => previewSummary(foreign));
});

test('consent binds the exact previewed content, never a stale one', () => {
  const summary = previewSummary(preview());
  const consent = exportConsent(summary,
    { previewSha: summary.previewSha, confirmed: true });
  assert.deepEqual(consent,
    { request_id: REQUEST_ID, preview_sha: 'ab'.repeat(32) });
  assert.throws(() => exportConsent(summary,
    { previewSha: 'cd'.repeat(32), confirmed: true }));
  assert.throws(() => exportConsent(summary,
    { previewSha: summary.previewSha, confirmed: false }));
  assert.throws(() => exportConsent(undefined,
    { previewSha: 'ab'.repeat(32), confirmed: true }));
});

test('a deletion request binds its exact preview and a closed reason', () => {
  const deletionPreview = {
    item_ids: ['item-1', 'item-2'], ledger_revision: 7,
    preview_sha: 'cd'.repeat(32), total_bytes: 2048,
  };
  const payload = deletionRequestPayload(deletionPreview, {
    reasonCode: 'user_requested', actor: 'owner-1',
    deletedAt: STAMP, requestId: REQUEST_ID,
  });
  assert.equal(payload.preview_sha, 'cd'.repeat(32));
  assert.equal(payload.ledger_revision, 7);
  assert.equal(payload.reason_code, 'user_requested');
  assert.throws(() => deletionRequestPayload(deletionPreview, {
    reasonCode: 'felt_like_it', actor: 'owner-1',
    deletedAt: STAMP, requestId: REQUEST_ID,
  }));
  assert.throws(() => deletionRequestPayload(
    { ...deletionPreview, item_ids: ['item-1', 'item-1'] }, {
      reasonCode: 'user_requested', actor: 'owner-1',
      deletedAt: STAMP, requestId: REQUEST_ID,
    }));
});

test('backup settings keep the closed key modes and never store a secret', () => {
  const payload = backupSettingsPayload({
    keyMode: 'instance_backup_key', schedule: 'weekly',
    location: 'volume://backups',
  });
  assert.equal(payload.key_mode, 'instance_backup_key');
  assert.equal('secret' in payload, false);
  const portable = backupSettingsPayload({
    keyMode: 'portable_recovery', schedule: 'manual',
    location: 'volume://backups', oneShotSecretProvided: true,
  });
  assert.equal(portable.key_mode, 'portable_recovery');
  assert.equal(Object.values(portable).includes('AGE-SECRET'), false);
  assert.throws(() => backupSettingsPayload({
    keyMode: 'portable_recovery', schedule: 'manual',
    location: 'volume://backups',
  })); // portable needs the one-shot masked input to have happened
  assert.throws(() => backupSettingsPayload({
    keyMode: 'my-own-crypto', schedule: 'manual', location: 'x',
  }));
  for (const smuggled of ['secret', 'recoverySecret', 'identity']) {
    assert.throws(() => backupSettingsPayload({
      keyMode: 'instance_backup_key', schedule: 'manual',
      location: 'x', [smuggled]: 'AGE-SECRET-KEY-1LEAK',
    }));
  }
});

test('finishing a journey NEVER requires a final export (UX-AC08)', () => {
  const gate = completionGate({ exported: false });
  assert.equal(gate.complete, true);
  assert.equal(gate.exportRequired, false);
  assert.equal(gate.exportOffered, true);
  assert.deepEqual(completionGate({ exported: true }),
    { complete: true, exportRequired: false, exportOffered: true });
});

test('the constant lists stay sorted, frozen and closed', () => {
  for (const list of [EXPORT_CATEGORIES, MISSING_REASONS,
                      DELETION_REASONS, BACKUP_KEY_MODES]) {
    assert.equal(Object.isFrozen(list), true);
    assert.deepEqual([...list].sort(), [...list]);
  }
  assert.equal(EXPORT_CATEGORIES.includes('hidden_reasoning'), false);
  assert.equal(EXPORT_CATEGORIES.includes('credentials'), false);
});
