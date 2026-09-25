// T072: the pure view of the read-only update guidance (records-update.mjs).
import test from 'node:test';
import assert from 'node:assert/strict';
import { GUIDANCE_SCHEMA, STEP_LABELS, updateGuidanceView } from '../static/records-update.mjs';

const base = { schema_version: GUIDANCE_SCHEMA, product_authority: 'read_only', current_release: null,
  request: null, backup: { required: false, state: 'not_required' }, last_refusal: null, next_steps: [], history: [] };

test('no update: no release recorded, no request, nothing to do', () => {
  const view = updateGuidanceView(base);
  assert.match(view.release, /기록된 릴리스가 없습니다/);
  assert.equal(view.requestState, 'none');
  assert.deepEqual(view.steps, []);
});

test('a stale gate says so and names the next steps in order', () => {
  const view = updateGuidanceView({ ...base,
    current_release: { release_id: '1.0.0', release_manifest_sha256: 'a'.repeat(64), image_lock_set_sha256: 'b'.repeat(64),
      installed_at: '2026-09-25T00:00:00.000Z' },
    request: { request_id: 'r', state: 'backup_verified', revision: 2, target_release_id: '1.1.0',
      target_release_manifest_sha256: 'c'.repeat(64), target_image_lock_set_sha256: 'd'.repeat(64), recovery_epoch: 1,
      created_at: 'x', expires_at: 'y', recorded_at: 'z', failure_code: null },
    backup: { required: true, state: 'stale', backup_id: 'b1', state_digest: 'e'.repeat(64) },
    last_refusal: { code: 'backup_stale', component: null, recorded_at: 'z' },
    next_steps: ['stop_control_plane', 'take_verified_backup_again'] });
  assert.match(view.release, /현재 릴리스 1\.0\.0/);
  assert.match(view.request, /1\.1\.0 · 백업 확인됨/);
  assert.match(view.backup, /백업 뒤에 새 자료가 기록되어/);
  assert.match(view.refusal, /백업 뒤에 새 자료가 있어/);
  assert.deepEqual(view.steps.map(step => step.text), [STEP_LABELS.stop_control_plane, STEP_LABELS.take_verified_backup_again]);
});

test('anything but the read-only guidance is refused', () => {
  assert.throws(() => updateGuidanceView({ ...base, product_authority: 'owner' }), /malformed/);
  assert.throws(() => updateGuidanceView(null), /malformed/);
});
