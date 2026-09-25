# Web-release update/recovery over the T025 `DeploymentControlPort` (T072), 2026-09-25

Status: **landed as operator tooling with a real backup gate, a revisioned CAS lifecycle, unique
receipt consumption inside the migration transaction and read-only browser guidance. T072 is
not ticked** (see "What stays open"): no real web release (T081 images, a published release
manifest and image-lock set) exists to update to, and the update receipt has no reviewed
contract of its own yet.

## What binds to what

| Thing | Bound to | Where it is checked |
|---|---|---|
| `deployment-request-v1`, kind `release_update` (immutable canonical bytes, `request_digest` over all other fields) | instance id, origin-profile digest, target release id, **target web-release manifest SHA-256**, **target image-lock-set SHA-256** (which the manifest itself names), target data-schema SHA-256, **current recovery epoch** plus its session-root generation id and manifest digest (target epoch equals current: an update never moves authority), current release manifest SHA-256 (or `null` while none is recorded), current data-schema ledgers SHA-256, 32-byte nonce, creator, creation/expiry | sealed by `updates.prepare`; the manifest must name exactly the image-lock bytes given (`parse_image_lock`) |
| Lifecycle `prepared → backup_verified → migrating → completed`, `prepared/backup_verified → cancelled`, `migrating → failed` | one request; each move inserts revision r+1 only while the head is r (primary key `(request_id, revision)`, inside `BEGIN IMMEDIATE`) | `UpdateStore.advance_in_transaction` |
| Gate backup | a backup made through the backup-crypto port (the networkless worker's `BackupCryptoClient` in a deployment), its external receipt checked against the ciphertext, the archive decrypted again through the same port, and the **archived database's restorable-state digest equal to the live digest** before and after | `updates.backup`; the lifecycle row stores backup id, ciphertext SHA-256 and that state digest |
| `deployment-update-receipt-v1` (Ed25519 over canonical JSON of every field but `signature`) | request id/digest/nonce/kind, instance, origin, deployment profile, the epoch, previous release manifest, target release manifest, image-lock set, `outcome: applied`, completion inside the request window, a `deployment-public-trust-set-v2` key holding the recovery-operator adapter (a stage-only key never signs one) | `verify_update_receipt` |
| Receipt consumption | `deployment_update_consumptions`: receipt SHA-256 primary key, request id UNIQUE, nonce UNIQUE, migration id UNIQUE, trust-set SHA-256 | inserted **in the same transaction** as the migration steps, the target-schema check, the migration record, the release head and the `completed` CAS |
| Migration | only code-owned steps (`_builtin_steps`: today the domain store's real migration 2); every family the target manifest names must hold a prefix of the target rows and every missing row needs a step | `plan_migration` at prepare and again inside the transaction |

The lifecycle family (`deployment_update_*`) lives in the vault database itself and is
classified as `deployment_receipt_private_state` in `app/operations/backup.py`: never carried by
a backup, never moving the state digest.

## What landed

- `app/operations/updates.py` — `python -m app.operations.updates status|prepare|backup|cancel|migrate`.
  Runs only with the control plane stopped (the T025 `_Maintenance` serving lock; `busy`
  otherwise) and refuses while an owner recovery is prepared/importing (`recovery_pending`).
  `migrate` rechecks epoch/root/configuration (`epoch_changed`), the components, the backup
  files (`backup_missing`) and the live digest (`backup_stale`), journals `migrating` with the
  receipt digest, then runs the one transaction. A step failure rolls the steps back and ends
  `failed` (data exactly the backed-up state). Output is one canonical JSON line.
- **Missing component handshake.** Every component the target manifest lists must answer the
  code-owned probe with its exact protocol (`backup-crypto` = the worker's `describe` over
  `cp-backup` and `deeptwin-backup-crypto-request-v1`); an absent, unreachable or wrong-version
  component refuses `component_unavailable`/`component_version_mismatch` with the lifecycle
  unchanged and the refusal recorded.
- `app/operations/recovery.py` — `update_guidance` (the one closed projection), operator input
  intake (`read_operator_input`: an operator-owned regular file, singly linked, not
  group/world writable, no symlink, **outside the data directory and the session root**, where
  every browser upload lands), `import_owner_recovery` (the T025 import through that intake,
  refused while an update is `migrating`), `restore_update_backup` (the gate backup into an
  empty staging directory as `restored_review`, never inside or over the active vault; refused
  `new_data_after_backup` unless the operator names the exact live state digest being left
  out), `refuse_start_during_migration`.
- `app/server.py` — the start refuses (before the store's first write) while an update is
  `migrating`: only the operator's `migrate` with the journaled receipt finishes it.
- `platform-update-v1` (`GET|HEAD /api/v1/platform/update`, `deployment.read`, browser
  session) and `app/static/records-update.mjs` mounted at `#records-update` on the records
  page: current release, pending request (target, manifest and image-lock digests, epoch,
  expiry), the required backup and whether it still holds the live state, the last refusal
  and the operator's next steps. No button, form or file input; no route takes an update or
  recovery receipt from a browser.

## Evidence

| Case | Surface | Result | Label |
|---|---|---|---|
| Exact request, idempotent prepare, `pending`, foreign image lock / non-canonical manifest / unsupported target refused | `test_update_recovery.py::test_the_request_binds_…` | pass | synthetic |
| `busy` while serving; `recovery_pending` during an owner recovery | `…::test_the_tool_refuses_while_…` | pass | synthetic |
| No verified backup → `backup_required`; backup without its component → `component_unavailable` | `…::test_migration_refuses_without_a_verified_backup` | pass | synthetic |
| Full update over a domain-v1 vault: real domain migration 2 applied once, one consumption row with receipt/nonce/migration id, lifecycle `prepared, backup_verified, migrating, completed`, release head, replay no-op, other receipt `replayed`, cancel `already_completed`, the migrated vault starts and the owner's session holds, guidance over HTTP, POST refused | `…::test_a_full_update_migrates_once_…` | pass, real age 1.3.2 | synthetic |
| A record written after the backup → guidance `stale`, `backup_stale`, nothing consumed; new backup → migrates and keeps the record | `…::test_a_write_after_the_backup_…` | pass, real age | synthetic |
| Gate ciphertext deleted / altered / tombstoned → `backup_missing` | `…::test_a_missing_or_altered_gate_backup_refuses` (3) | pass, real age | synthetic |
| Cancel committed between receipt verification and the journal → `cancelled`, nothing consumed; journaled receipt → cancel `migration_in_progress`, start refused, completion, start again | `…::test_a_committed_cancel_wins…`, `…::test_a_journaled_receipt_wins…` | pass, real age | synthetic |
| Prepared cancel refuses every later receipt; a new request is independent | `…::test_a_prepared_cancel_…` | pass, real age | synthetic |
| Crash at `receipt_verified`, `migrating_recorded`, `migration_applied` (inside the transaction), `committed` → re-run completes exactly once; other receipt `migration_in_progress` | `…::test_a_crash_at_every_migration_step_…` (4) | pass, real age | synthetic |
| Crash after the request file / after the backup file → inert, re-runs | `…::test_a_crash_while_preparing_or_backing_up_…` | pass, real age | synthetic |
| Missing, unreachable and wrong-version component → safe state, refusal in the guidance; then completes | `…::test_a_missing_or_wrong_component_…` | pass, real age | synthetic |
| The real `BackupCryptoClient` with no reachable worker → CLI `component_unavailable` | `…::test_the_real_backup_client_…` | pass | synthetic |
| Failing step → `failed`, digest and schema unchanged, half-made table rolled back, guidance steps | `…::test_a_failing_step_rolls_back_…` | pass, real age | synthetic |
| Forged signature, non-canonical bytes, stage-only key, unknown key, wrong image lock / manifest / epoch / nonce / origin, expired, foreign request → refused, nothing consumed | `…::test_forged_foreign_and_mismatched_receipts_…` | pass, real age | synthetic |
| Owner recovery (through `recovery.import_owner_recovery`) between backup and receipt → `epoch_changed` | `…::test_an_owner_recovery_between_…` | pass, real age | synthetic |
| Receipts from the data directory (restore upload), via a symlink into it, from the session root, or group/world writable → `input_source_refused`; the only `/api/v1/platform` route is the GET | `…::test_the_recovery_path_refuses_browser_uploaded_…` | pass | synthetic |
| Restore of the gate backup after the update → `new_data_after_backup` unless the live digest is named; staged `restored_review`, active vault unchanged | `…::test_restoring_a_gate_backup_…` | pass, real age | synthetic |
| No process/package-manager imports in the tooling; an audit hook over a whole update sees only the verified age binary spawned (no pip/npm/npx/uv/apt/docker/yarn) | `…::test_the_tooling_never_imports_…`, `…::test_a_whole_update_spawns_only_…` | pass | synthetic |
| Real Chromium: owner set up, records page shows no update; tool `busy` while serving; stopped: `prepare`, `backup` refused `component_unavailable`; restart; the page shows the prepared request with its digests and epoch, backup absent, the refusal naming `backup-crypto`, the five steps; no control in the section; POST refused | `app/tests/browser-update-guidance-t072.test.mjs` (`update_guidance_server.py`) | pass | synthetic, test actor |
| The guidance view | `app/tests/records-update.test.mjs` (3) | pass | unit |

`test_update_recovery.py`: 25 passed with `DEEPTWIN_AGE_RUNTIME_ROOT` set to the verified locked
age 1.3.2; without it the 18 backup cases skip and say why.

## What stays open

- **No real web release.** `deeptwin-web-release-manifest-v1` and `deeptwin-image-lock-set-v1`
  are defined and enforced here, but no release publishes them yet; T081 owns the images, the
  image-lock set and the manifest. Until then the update binds to operator-supplied inputs that
  follow these formats.
- **Update receipt contract.** `deployment-update-receipt-v1` is verified against the reviewed
  `deployment-public-trust-set-v2` and signed by a key holding the recovery-operator adapter
  (the stopped-control-plane deployment authority). A dedicated update adapter and exported JSON
  schemas under `schemas/v2/deployment` wait for the same contract decision the T025 recovery
  port waits for (evidence/recovery-port-design-proposal-2026-09-23.md). The trust set is an
  operator input here; pinning it to the `deployment-verify-public` volume is T081 wiring.
- **The real worker process.** The gate backup ran through the in-process port with the real age
  binaries and a real backup-key volume. The worker-process path (`BackupCryptoClient` over
  `cp-backup`) is exercised only for its refusal; its create/restore across the process
  boundary is T070's test, and the Compose `backup` service has no image yet (T081).
- **In-place migration at open.** `DomainStore` still applies domain migration 1→2 when it opens
  a v1 vault (pre-T072 behavior, also in the restore verification). A future release that ships
  a new in-place step must route it through `updates migrate`; the start does not yet refuse an
  ungated schema step, only a journaled `migrating` update.
- **A restart between backup and migrate** writes the store's start event, so the gate becomes
  `stale` and the guidance asks for a new backup. That is the intended refusal, not a loss.
