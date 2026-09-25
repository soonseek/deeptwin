// T073 (US7): records GUI logic — logs/export/backup/retention reachable
// from anywhere, export consent bound to the ACTUAL previewed content,
// deletion bound to its exact preview, closed backup key modes with the
// recovery secret never stored, and no mandatory final export (UX-AC08).
// The constant lists mirror the server contracts in
// app/operations/export.py and app/operations/retention.py; the Python
// suite holds a drift test over them.

export const EXPORT_CATEGORIES = Object.freeze([
  'alternatives', 'artifacts_metadata', 'evaluation_evidence', 'events',
  'model_final_responses', 'originals', 'tool_observations',
]);

export const MISSING_REASONS = Object.freeze([
  'access_denied', 'deleted', 'not_recorded', 'not_selected',
  'redacted', 'rights_restricted', 'unavailable',
]);

export const DELETION_REASONS = Object.freeze([
  'migration', 'policy_cleanup', 'rights_request', 'user_requested',
]);

export const BACKUP_KEY_MODES = Object.freeze([
  'instance_backup_key', 'portable_recovery',
]);

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const STAMP = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$/;
const SHA256 = /^[0-9a-f]{64}$/;

function fail(message) {
  throw new Error(message);
}

function requireText(value, label, maximum = 256) {
  if (typeof value !== 'string' || value.length < 1 || value.length > maximum) {
    fail(`${label} is out of bounds`);
  }
  return value;
}

// Every records section is a plain route with no prerequisite: the user
// reaches logs, export, backup and retention from any screen, in any
// order — the GUI never sequences them.
export function recordsRoutes() {
  return Object.freeze([
    Object.freeze({ id: 'logs', path: '/records/logs', available: 'everywhere' }),
    Object.freeze({ id: 'export', path: '/records/export', available: 'everywhere' }),
    Object.freeze({ id: 'backup', path: '/records/backup', available: 'everywhere' }),
    Object.freeze({ id: 'retention', path: '/records/retention', available: 'everywhere' }),
  ]);
}

export function exportRequestPayload({
  requestId, scope, categories, includeRawRefs,
  redactionPolicyRef, authorConsentRef, createdAt,
}) {
  if (typeof requestId !== 'string' || !UUID.test(requestId)) {
    fail('request id is not a canonical UUID');
  }
  if (!Array.isArray(categories) || categories.length < 1 || categories.length > 8
      || new Set(categories).size !== categories.length
      || categories.some(item => !EXPORT_CATEGORIES.includes(item))) {
    // Hidden reasoning and credentials are not selectable items at all.
    fail('selected categories are out of bounds');
  }
  if (!Array.isArray(includeRawRefs) || includeRawRefs.length > 64) {
    fail('raw inclusion refs are out of bounds');
  }
  if (typeof createdAt !== 'string' || !STAMP.test(createdAt)) {
    fail('created time must be a canonical UTC timestamp');
  }
  return {
    request_id: requestId,
    scope: requireText(scope, 'scope', 512),
    selected_categories: [...categories].sort(),
    include_raw_refs: includeRawRefs,
    redaction_policy_ref: redactionPolicyRef,
    author_consent_ref: authorConsentRef,
    created_at: createdAt,
  };
}

// The consent screen shows what the export ACTUALLY contains: per-category
// item counts plus every omission with its closed-set reason.
export function previewSummary(preview) {
  if (typeof preview !== 'object' || preview === null
      || typeof preview.preview_sha !== 'string'
      || !SHA256.test(preview.preview_sha)
      || !Array.isArray(preview.items) || !Array.isArray(preview.missing)) {
    fail('a full preview is required before consent');
  }
  const counts = {};
  for (const item of preview.items) {
    if (!EXPORT_CATEGORIES.includes(item.category)) {
      fail('a previewed item is outside the closed categories');
    }
    counts[item.category] = (counts[item.category] ?? 0) + 1;
  }
  const missing = preview.missing.map(entry => {
    if (!MISSING_REASONS.includes(entry.reason)) {
      fail('a missing reason is outside the closed set');
    }
    return { category: entry.category, reason: entry.reason };
  });
  return {
    requestId: preview.request_id,
    previewSha: preview.preview_sha,
    counts,
    missing,
  };
}

export function exportConsent(summary, ack) {
  if (typeof summary !== 'object' || summary === null
      || typeof summary.previewSha !== 'string') {
    fail('consent requires the shown content summary');
  }
  if (typeof ack !== 'object' || ack === null || ack.confirmed !== true) {
    fail('consent is never implicit');
  }
  if (ack.previewSha !== summary.previewSha) {
    fail('consent must bind the exact previewed content');
  }
  return { request_id: summary.requestId, preview_sha: summary.previewSha };
}

export function deletionRequestPayload(preview, {
  reasonCode, actor, deletedAt, requestId,
}) {
  if (typeof preview !== 'object' || preview === null
      || !Array.isArray(preview.item_ids)
      || typeof preview.preview_sha !== 'string'
      || !Number.isInteger(preview.ledger_revision)) {
    fail('a deletion needs its exact preview first');
  }
  if (new Set(preview.item_ids).size !== preview.item_ids.length) {
    fail('a deletion scope never repeats an item');
  }
  if (!DELETION_REASONS.includes(reasonCode)) {
    fail('the deletion reason is outside the closed set');
  }
  if (typeof requestId !== 'string' || !UUID.test(requestId)) {
    fail('request id is not a canonical UUID');
  }
  if (typeof deletedAt !== 'string' || !STAMP.test(deletedAt)) {
    fail('deletion time must be a canonical UTC timestamp');
  }
  return {
    request_id: requestId,
    item_ids: [...preview.item_ids],
    preview_sha: preview.preview_sha,
    ledger_revision: preview.ledger_revision,
    reason_code: reasonCode,
    actor: requireText(actor, 'actor'),
    deleted_at: deletedAt,
  };
}

const BACKUP_FIELDS = new Set([
  'keyMode', 'schedule', 'location', 'oneShotSecretProvided',
]);

export function backupSettingsPayload(fields) {
  if (typeof fields !== 'object' || fields === null) {
    fail('backup settings must be an object');
  }
  for (const name of Object.keys(fields)) {
    if (!BACKUP_FIELDS.has(name)) {
      // A recovery secret is one-shot masked input to the worker; it is
      // never part of stored settings, whatever the field is called.
      fail(`backup settings never store ${name}`);
    }
  }
  const { keyMode, schedule, location, oneShotSecretProvided } = fields;
  if (!BACKUP_KEY_MODES.includes(keyMode)) {
    fail('the backup key mode is outside the closed set');
  }
  if (keyMode === 'portable_recovery' && oneShotSecretProvided !== true) {
    fail('portable recovery requires the one-shot masked input first');
  }
  return {
    key_mode: keyMode,
    schedule: requireText(schedule, 'schedule', 64),
    location: requireText(location, 'location', 512),
  };
}

// UX-AC08: export is offered, never required — a journey completes
// whether or not anything was exported.
export function completionGate(journey) {
  void journey?.exported;
  return { complete: true, exportRequired: false, exportOffered: true };
}

// T070/T073: a backup made through the isolated backup-crypto worker. The preview is
// the server's count of what a backup made NOW carries (row counts per included
// history category, originals by count and bytes) and every excluded category with
// its closed reason; consent binds that exact digest. The lists mirror
// app/operations/backup.py (drift test: app/tests/test_records_contract_mirror.py).
export const BACKUP_INCLUDED = Object.freeze([
  'approvals_and_permissions', 'conversations', 'event_log', 'originals', 'other_history',
  'records_and_lineage', 'run_history', 'work_history',
]);

export const BACKUP_EXCLUDED_REASONS = Object.freeze([
  'authenticator_never_restored', 'credential_never_restored', 'deleted_by_owner',
  'deployment_private_state', 'not_retained', 'recreated_after_restore', 'regenerable',
  'separate_private_root', 'unconsumed_capability',
]);

// what a staged restore still needs before it can serve: each is required, none is done here
export const RESTORE_REQUIREMENTS = Object.freeze([
  'new_owner_bootstrap', 'recreate_connections_and_service_clients', 'review_and_activate_exact_environment',
]);

export function backupPreviewSummary(preview) {
  if (typeof preview !== 'object' || preview === null || typeof preview.preview_sha !== 'string'
      || !SHA256.test(preview.preview_sha) || typeof preview.request_id !== 'string' || !UUID.test(preview.request_id)
      || !Array.isArray(preview.included) || !Array.isArray(preview.excluded)
      || !Number.isInteger(preview.records) || preview.records < 0) {
    fail('a full backup preview is required before consent');
  }
  const included = preview.included.map(entry => {
    if (!BACKUP_INCLUDED.includes(entry?.category)) fail('an included category is outside the closed set');
    return entry.category === 'originals'
      ? { category: 'originals', count: Number(entry.count), bytes: Number(entry.bytes) }
      : { category: entry.category, rows: Number(entry.rows) };
  });
  const excluded = preview.excluded.map(entry => {
    if (typeof entry?.category !== 'string' || !BACKUP_EXCLUDED_REASONS.includes(entry.reason)) {
      fail('an excluded reason is outside the closed set');
    }
    return { category: entry.category, reason: entry.reason, rows: Number.isInteger(entry.rows) ? entry.rows : null };
  });
  if (!excluded.some(entry => entry.category === 'owner_authenticators_sessions_and_bootstrap_verifiers')) {
    fail('a backup preview must state that authenticators are excluded');
  }
  return {
    requestId: preview.request_id, previewSha: preview.preview_sha, records: preview.records,
    keyMode: preview.key_mode, recoverable: preview.recoverable_after_host_or_volume_loss === true,
    included, excluded,
  };
}

export function backupConsent(summary, ack) {
  if (typeof summary !== 'object' || summary === null || typeof summary.previewSha !== 'string') {
    fail('consent requires the shown backup preview');
  }
  if (typeof ack !== 'object' || ack === null || ack.confirmed !== true) {
    fail('consent is never implicit');
  }
  if (ack.previewSha !== summary.previewSha) {
    fail('consent must bind the exact previewed content');
  }
  return {
    schema_version: 'backup-create-v1', request_id: summary.requestId,
    preview_sha: summary.previewSha, confirmed: true,
  };
}

export function restoreReview(view) {
  const review = view?.review;
  if (view?.state !== 'restored_review' || typeof review !== 'object' || review === null
      || review.dispatch !== 'blocked' || review.environment_reactivation !== 'explicit_required'
      || review.active_vault_changed !== false
      || !Array.isArray(review.requires) || RESTORE_REQUIREMENTS.some(step => !review.requires.includes(step))) {
    fail('a staged restore must stay blocked until its review steps are done');
  }
  return {
    restoreId: view.restore_id, backupId: review.backup_id, requires: [...RESTORE_REQUIREMENTS],
    notRestored: Array.isArray(review.not_restored) ? [...review.not_restored] : [],
  };
}
