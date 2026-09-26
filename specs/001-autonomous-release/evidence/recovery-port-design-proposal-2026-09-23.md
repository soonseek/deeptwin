# Proposal — the T025 deployment-authority recovery port (2026-09-23)

Status: **approved by the owner on 2026-09-26** (decisions.md, "Owner decisions after T038 attempt 6"),
as reconciled in `owner-recovery-reconcile-t025-2026-09-25.md`. The approval covers the design only;
implementation state is in that reconcile record. T025 and T072 stay open.

Original status (2026-09-23): proposal only. Nothing here is implemented or approved.

## Why this is a proposal and not code

The contracts require the following, but do not define the exact wire formats:

- a "valid deployment recovery receipt"
- `session-root-maintenance` advancing to "a new generation with a higher epoch"
- a restricted reconciliation start (operations.md §2, api.md, decisions.md ADR-010)

The only receipts that exist today are the extension-staging ones. Their public trust set
(`deployment-public-trust-set-v1`) pins `adapter_ids` to exactly `["deeptwin-stage-operator-v1"]`
and `adapters` to that one adapter. Epoch 1 is fixed as a constant across the codebase:

- the deployment configuration schema (`owner_auth_schema.py`: `recovery_epoch const 1`)
- `setup.build_bootstrap_configuration`
- `session_root` (`initialize`, `open`)

Building recovery would therefore mean inventing security-contract details (receipt schema,
trust-set version, signer adapter) that no reviewed design fixes. Those details need an explicit
design decision first. Below is a concrete proposal to decide on.

## Proposed design

### 1. Trust set v2 (new schema; v1 unchanged)

- `deployment-public-trust-set-v2`, domain `deeptwin-deployment-public-trust-set-v2`. It is v1
  plus one adapter entry `{operator_adapter: "deeptwin-recovery-operator-v1", operator_version:
  "1.0.0", deployment_profile_id}`.
- Each key lists exactly the adapters it may sign for. A recovery signature requires
  `"deeptwin-recovery-operator-v1"` in that key's `adapter_ids`, so a stage-only key can never
  sign a recovery.
- `deployment-receipt-root-init` writes v2 on new instances. An existing v1 instance gets v2 only
  through the same update-safe maintenance path (the exact prior v1 digest is bound in the v2
  preimage).

### 2. Recovery request (`deployment-request-v1`, kind `owner_recovery`)

- Common fields as today: request nonce, digest, instance/`OriginProfile`, created/expires.
- `preconditions`: `{current_recovery_epoch: N, current_session_root_generation_id,
  current_session_root_manifest_sha256}`.
- `effect_payload`: `{target_recovery_epoch: N+1}`. Skipping an epoch is rejected at parse time.
- The request is sealed by the product (owner-authenticated or, when the owner is locked out,
  produced by the operator surface from the public config). It never carries a raw capability
  or a verifier.

### 3. Recovery receipt (`deployment-recovery-receipt-v1`)

- Domain `deeptwin-deployment-recovery-receipt-v1`, a detached PureEd25519 signature over the
  ADR-008 canonical JSON of every other field. It binds:
  - `request_id`, `request_digest`, `request_nonce`, `kind`
  - `instance_id`, `origin_profile_digest`
  - `previous_{epoch,generation_id,manifest_sha256}`
  - `new_{epoch,generation_id,manifest_sha256}`
  - `new_verifier_sha256`
  - `completed_at`, `key_id`, `trust_set_digest`
- It is verified with the existing `receipt_crypto.verify_detached` against the v2 trust set.

### 4. `session-root-maintenance` (control plane stopped)

- **Layout.** A new generation layout inside the same volume: `generations/<generation_id>/{root.key,
  manifest.json}` plus a `current` file written by atomic rename. The existing flat
  `initial_genesis` layout is read as epoch 1.
- **Preconditions.** It advances only from the exact current generation named by the receipt's
  `previous_*` fields, and only to epoch N+1.
- **Manifest.** The new manifest is `state: "recovered"`, carrying `parent_generation_id` and
  `recovery_receipt_sha256`.
- **Idempotence.** Re-running over the already-advanced state is a verify-only no-op. Any other
  existing state fails closed and is never replaced.

### 5. Restricted reconciliation start (`app/server.py`)

- **Equal epochs** (config = root = DB control) start normally.
- **Recovery start.** Config and root at N+1, the DB at N, and a receipt that verifies and binds
  exactly these generations. The server then opens only `/health` (reporting
  `recovery_reconciliation`) and runs **one DB transaction** that:
  - inserts `owner_auth_control(epoch=N+1)`
  - revokes every authenticator and session
  - revokes every service client
  - revokes every unconsumed human/bootstrap capability and verifier
  - expires every pending approval and consent challenge (`approval.decided(expired)`)
  - revokes every open run consent (`approval.decided(revoked)`; the revocation path exists)
  - appends a `security.recovery_completed` event

  Historical evidence stays and is non-authoritative. Only after the commit do bootstrap and
  login open, using the new verifier.
- **Anything else fails closed at start, with no plaintext fallback:** rollback, a skipped
  epoch, a missing, stale or malformed receipt, or a generation mismatch.

### 6. Tests (named in T025)

`test_deployment_control.py`, `test_session_security.py` and `test_owner_sessions.py` must cover:

- bad key, bad signature, bad schema
- stage-only key signing a recovery
- stale/replayed and cross-instance/cross-origin receipts
- skipped and rolled-back epochs
- crash between the root advance and the DB transaction (the next start re-runs
  reconciliation idempotently)
- every revoked authority actually refusing afterwards
- bootstrap opening only after the commit

## Decision needed

Approve, amend or reject §1–§5 (in particular the trust-set v2 adapter split and the
`owner_recovery` request kind). Once approved, the implementation is local engineering with
offline Ed25519 fixtures; no live provider or host is required.
