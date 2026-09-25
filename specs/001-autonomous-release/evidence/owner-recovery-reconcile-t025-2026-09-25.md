# T025 — owner recovery: the restricted reconciliation start (2026-09-25)

Status: **partial slice of the recovery port. T025 stays open.** This implements the
database side of an owner recovery (recovery port design §5, from
`recovery-port-design-proposal-2026-09-23.md`; the only record of that design's approval is the
test docstring in `app/tests/test_owner_sessions.py`, which cites 2026-09-24). Everything is
exercised offline, with Ed25519 keys generated in-test. No real deployment was recovered.

## What is implemented

### Contracts and schemas

`app/deployment/recovery_contracts.py` and `app/deployment/recovery_schema_exports.py` define four
wire formats, exported under `schemas/v2/deployment/`:

- `deployment-public-trust-set-v2`: the v1 trust set plus exactly the recovery adapter. v1 is
  unchanged.
- the sealed `owner_recovery` request (`request-owner-recovery-v1`)
- the signed `deployment-recovery-receipt-v1` (`receipt-recovery-v1`)
- the recovered session-root manifest (`session-root-recovered-v2`)

These contracts also provide:

- the canonical receipt preimage
- Ed25519 verification against an `instance_operator` key that holds the recovery adapter
- the rule that the epoch rises by exactly one (N→N+1)

### Session root

`app/operations/session_root.py` provides `advance_session_root`, a library function. It adds a
`generations/<id>/` generation for N+1 beside the untouched flat genesis and names it in `current`
by atomic rename. Opening the root walks back to genesis and fails closed on any stray, partial or
rolled-back layout.

### Start-up

`app/server.py`, `app/services/owner_auth.py` and `app/services/deployment_control.py` handle the
start. `create_app` takes `recovery_trust_set` bytes (the CLI option is `--recovery-trust-set`).

- **Equal epochs** (configuration, root and database) start normally.
- **Configuration and root at N+1 over a database at N** start restricted:
  1. `verify_recovery_start` binds the receipt to the recovered root generation, to the configured
     verifier's digest, and to the database's exact epoch-N generation, manifest and binding.
  2. While the start is restricted, every authority method fails closed with `unavailable`.
     `/health` reports only `{"state": "recovery_reconciliation"}`.
  3. `reconcile_recovery_in_transaction` then runs **one** DB transaction before any route is
     composed. The steps are listed in the next section.
- **Anything else fails closed**, with no plaintext fallback. This covers a rollback, a skipped
  epoch, a missing or foreign trust set, and a wrong verifier.

### The reconciliation transaction

The single transaction does the following:

- **Epoch N+1:** inserts `owner_auth_control(epoch=N+1)`, bound to the request id, nonce and
  receipt digest that opened it. A replayed request, nonce or receipt can never open a later
  epoch.
- **Bootstrap:** expires every still-available bootstrap claim of an earlier epoch and installs the
  N+1 claim with the new verifier.
- **Owner credentials:** revokes every authenticator and every browser session.
- **Service clients:** revokes every service client. `_revoke_all_in_transaction` is shared with
  the existing `revoke_all_for_recovery`, and the service-client epoch only moves forward.
- **Challenges:** expires every unconsumed conversation challenge.
- **Gates:** `expire_pending_in_transaction` gives every gate request that has no v1 decision a v1
  `action_approval` with decision `expired`, plus `approval.decided(expired)`. The scheduler reads
  it as a refusal, and a later v1 owner command for that gate conflicts.
- **Consents:** `revoke_open_in_transaction` revokes every open run consent, with
  `approval.decided(revoked)`. A revoked consent starts no run.
- **Events and audit:** appends `auth.recovery_completed` and a `recovered` private-auth audit row.

If the process crashes before the commit, epoch N stays in place and the next start verifies and
reconciles again. After the commit, the next start is an ordinary equal-epoch start.

### Private-auth storage

Private-auth storage is now version 2 (`owner_auth_storage.py`):

- It keeps one control row per recovery epoch, forming a 1..N chain.
- A verified v1 database is rebuilt into v2 inside the opening writer, and every unchanged row
  keeps its exact digest.
- Historical sessions and claims stay as evidence.

### After recovery

The recovered owner re-binds the **same** owner actor, so every earlier authored record stays
attributable:

- the owner bootstraps with the new capability
- the new authenticator is sealed as the next revision
- `auth_epoch` and `recovery_epoch` advance
- only the new password logs in

### Execution-bound (v2) approvals across a recovery (added on merge, 2026-09-25)

Upstream added `run-approval-v2`, a decision bound to one attempt of one execution, which a
dispatcher consumes via `lookup_execution` and `resolve`. A v2 decision authorizes a future
dispatch, so it must not outlive the authority that made it. The merge applies this rule:

- **Superseded decisions:** a v2 record whose `approval.decided` event sequence precedes the latest
  `auth.recovery_completed` event is **superseded**. `lookup_execution` and `resolve` raise
  `RunApprovalError("superseded")`. The extension transport refuses such a decision twice:
  - at build, `_require_execution_bound_approval` refuses it as unavailable
  - before the send, `_verify_execution_approval` refuses it as `transport_invalid`,
    `definitely_not_sent`
- **Fail-closed barrier:** if the recovery event is no longer held in the event stream, the
  barrier is the stream's first available sequence.
- **No rewrite:** the record itself is never rewritten.
- **Later decisions:** a v2 decision the recovered owner records after the recovery is current.
- **v1 decisions:** a v1 decision already recorded before the recovery stays historical gate
  evidence that the scheduler replays. It never authorizes a dispatch.

## Tests (run serially, offline, `env -u DEEPTWIN_LIVE_ANTHROPIC_API_KEY`)

### Recovery tests

- `app/tests/test_deployment_control.py` covers:
  - schema-first refusal
  - a stage-only key, a v1 trust set or a foreign trust set never verifying
  - a skipped epoch, and another previous generation
  - the fixture's completeness
  - fresh schema-export bytes beside unchanged v1
- `app/tests/test_owner_sessions.py` covers:
  - every earlier authority refusing after the commit: the old cookie and CSRF token, the service
    client, the pending gate (now `expired`, later approve → `conflict`), the consent (a run start
    → 403), the old capability and the old password
  - bootstrap and login opening only after the commit
  - a crash before the commit being reconciled again
  - rollback, skipped epoch, missing or foreign trust set and wrong verifier failing closed
  - **new:** a pre-recovery v2 approval being `superseded` for both `resolve` and
    `lookup_execution`, while a post-recovery v2 decision is current
- `app/tests/test_session_security.py` covers the old CSRF token and cookie under the recovered
  root, a replayed request nonce never opening a later epoch, and forward-only service-client epoch
  revocation.

### Full serial run (after the merge with `codex/ui-structure`)

The 32 files listed below were run in one serial `pytest -q -p no:cacheprovider` invocation, and
all **554 passed**. They are the recovery files above plus the owner, session, service-client,
run-approval, run-consent, first-party, tool-binding, transport, conformance-storage and
schema-export suites:

- test_deployment_control
- test_deployment_prepare_v2_schema_exports
- test_deployment_receipt_schema_exports
- test_deployment_receipt_session_fixture
- test_domain_schema_exports
- test_extension_attempt_transport
- test_first_party
- test_first_party_dependencies
- test_local_session
- test_owner_admission
- test_owner_decisions
- test_owner_material_intake
- test_owner_material_upload_boundary
- test_owner_material_upload_lock
- test_owner_password_change
- test_owner_sessions
- test_provider_conformance_storage
- test_provider_prepare_api_schema_exports
- test_provider_receipt_schema_exports
- test_run_approval_api
- test_run_approvals
- test_run_consents
- test_server_session_integration
- test_service_client_auth
- test_service_client_routes
- test_service_clients
- test_service_clients_persistent
- test_session_gui_mirror
- test_session_root
- test_session_security
- test_tool_execution_binding
- test_web_owner_integration

## What remains open

- **The stopped-control-plane maintenance tool.** `advance_session_root` and
  `make_recovery_request` are library functions exercised by the test fixture only. No operator
  CLI or `deploy/` step prepares, seals, imports, verifies or consumes a recovery request, and there
  is no separate lifecycle/consumption CAS or cancel-vs-import handling.
- **The instance-operator recovery adapter**, which signs a receipt with a real key, does not
  exist. Only in-test keys are used.
- **No UI.** `start.mjs` does not render `recovery_reconciliation`, which is never served to a
  browser in practice because reconciliation runs before routes are composed. There is no GUI
  recovery guidance.
- **No real deployment** (Compose, Portainer or HTTPS) has been recovered, and no browser case
  covers recovery.
- **Authorship of recovery-written decisions.** The `expired` approvals and the recovery consent
  revocations are sealed under the owner's actor ref with `actor_kind="human"`, because the readers
  accept only owner-authored decisions. Their command ids are derived from the recovery request id.
  A dedicated system authorship for recovery-written decisions is not modeled.
- **Already-approved v1 gates.** A v1 gate decision recorded as `approved` before the recovery but
  not yet consumed by the scheduler is not expired. It stays historical gate evidence.
  Revoking the run's consent is what stops such a run.
- **The credential vault.** `CredentialVault`/`CredentialRootPort`, the typed `credential_client`
  and `test_bootstrap_delivery.py`/`test_credential_vault.py` are not part of this slice.
