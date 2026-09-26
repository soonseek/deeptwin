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

## 2026-09-25 (later): the stopped-control-plane maintenance tool and the recovery screen

Status: **still a partial slice. T025 stays open.** This section closes three of the open items
above for offline, test-owned instances: the operator maintenance tool (with cancel-versus-import),
the recovery screen, and a real-browser recovery. The signing stays outside the product, and no
real deployment (Compose, Portainer or HTTPS) was recovered.

### The maintenance tool (`app/operations/deployment_control.py`)

`python -m app.operations.deployment_control {status,prepare,cancel,import}` is operator tooling
(the operator side of `app/services/deployment_control.py`, the file T025 names), never an
end-user journey. It takes the data directory's serving lock (`ServingLock`, `create=False`), so
it refuses `busy` while a control plane runs and `unavailable` for a data directory that never
served. It then works on the following:

- **`prepare --new-verifier V`**
  - reads the current session-root generation, which the deployment configuration and the
    database's current `owner_auth_control` row must both name (same epoch N, generation and
    manifest digest)
  - refuses `reconciliation_pending` when the database is still one epoch behind (an imported
    recovery whose start has not run yet)
  - seals one `owner_recovery` request with a fresh 32-byte nonce and the vault's system actor
    as `created_by`, and writes it to `W/requests/<request_id>.json` for the trust-set holder to
    sign
  - only the non-secret verifier of the new capability reaches the tool. The operator makes the
    capability offline, for example on `deploy/bootstrap/index.html`. A verifier equal to the
    current one is refused.
- **`import --receipt R --trust-set T`**
  - verifies the receipt against the pending request and the v2 trust set
    (`verify_recovery_receipt`)
  - binds `new_verifier_sha256` to the prepared verifier, and `previous_*` to the root as it is
    now
  - journals `importing` with the receipt digest, then advances the root to N+1
    (`advance_session_root`)
  - rewrites the deployment configuration with epoch N+1 and the new verifier (temporary file,
    fsync, rename, directory fsync; the file's mode is kept), then records `imported`
  - the next start with `--recovery-trust-set` runs the restricted reconciliation start
- **`cancel`** ends a `prepared` request. A receipt for it is then refused (`cancelled`, and
  `replayed` once a new request is pending). A request whose import has begun cannot be
  cancelled (`import_in_progress`), and a completed one answers `already_imported`.
- **Idempotency and crash safety**
  - `W/pending.json` is the single commit pointer: `prepared → importing → imported`, or
    `prepared → cancelled`. Every file is replaced with a temporary name, fsync, rename and a
    directory fsync.
  - A crash after `importing` is recorded, after the root advance or after the configuration
    rewrite is completed by re-running `import` with the same receipt. Only the journaled receipt
    completes it, and a different one is `import_in_progress`.
  - Re-running `prepare` with the same verifier returns the same sealed request.
  - Re-importing the identical receipt after completion is a no-op.
  - A request file left by a crash before the pointer named it is inert.
  - In the window where the root has advanced but the configuration has not, the control plane
    fails closed (a rollback), until `import` is re-run.
- **Refusals.** Every refusal is a closed code in one canonical JSON line with no secret, and
  exits 2.

### The recovery screen (`app/static/start.mjs`, `/health`)

- After a recovery (a served epoch above 1), `/health` adds `"recovered": true`. An instance
  that was never recovered answers exactly as before.
- The first screen then turns its setup form into the owner's re-setup, with the button
  "소유자 다시 설정" and status `data-state="recovered"`. The status text says what the recovery
  ended: sessions, passwords, capabilities, service clients, pending approvals (expired) and open
  run consents (revoked). It says that the operator's new one-time capability sets the owner up
  again, and that earlier records stay.
- `{"state": "recovery_reconciliation"}` renders a no-form "reconciling" state. The server never
  actually serves it to a browser, because the reconciliation commits before any route is
  composed.

### Tests (serial, offline, `env -u DEEPTWIN_LIVE_ANTHROPIC_API_KEY`)

- `app/tests/test_deployment_control_tool.py` (11 cases, in-test Ed25519 keys via
  `recovery_fixture`, the test signing adapter). Each case is checked against a real
  `create_app` start afterwards: the old cookie gets 401, the old capability and password are
  refused, the new capability returns 201, and the database control epochs are `[1, 2]` (or 3).
  - the CLI round trip `status → prepare (re-run) → import (re-run) →` start, whose
    reconciliation actually ran
  - `busy` while the control plane runs
  - a second recovery 2→3, which needs the first one reconciled and refuses the first receipt as
    `replayed`
  - cancel versus import
  - no-pending, old-verifier and malformed-verifier refusals
  - wrong, forged and foreign receipts, none of which change anything: a wrong verifier binding,
    a zero signature, a key outside the trust set, a stage-only key, another trust set, a skipped
    epoch, a non-receipt, and a receipt for a request the tool never sealed
  - a crash at each import step (`importing_recorded`, `root_advanced`, `config_written`),
    completed by re-running
  - a crash after the request file
  - no leftover temporary files, and modes 0700/0600
- `app/tests/start.test.mjs` adds three cases: the recovered re-setup, a recovered instance's
  login, and the reconciling state. The health parser accepts only `recovered: true`.
- `app/tests/browser-owner-recovery-t025.test.mjs` runs one real-Chromium case end to end:
  1. the offline page makes capability 1
  2. the supported server starts and the owner sets up
  3. the tool refuses `busy`
  4. the server stops and the offline page makes capability 2
  5. `prepare` with its verifier, a test-only signer (`app/tests/fixtures/recovery_signer.py`)
     signs, and `import`
  6. the server restarts from the rewritten configuration
     (`app/tests/fixtures/owner_recovery_server.py`)
  7. the old browser session gets 401, and the first screen shows the recovered state
  8. the old capability is refused and the new one sets the owner up (to `work.html`)
  9. the old password gets 401 and the new one 200
  10. the tool's `status` reads epoch 2 in the configuration, the root and the database

  No page error occurs. The owner's cookie is carried across the restart in a fresh browser
  context, because a half-closed keep-alive socket would otherwise hold the fixed port.
- `test_owner_sessions.py` now expects `recovered: true` on the post-recovery health reading.

Observed runs in this worktree:

- **Python:** one serial `pytest -q -p no:cacheprovider` invocation over 24 files passed
  **444**. The files were the new tool test, test_deployment_control, test_owner_sessions,
  test_session_security, test_web_owner_integration, test_first_party, test_web_shell_assets,
  test_session_root, the deployment/domain schema-export and receipt-session suites,
  test_first_party_dependencies, test_local_session, test_owner_admission,
  test_owner_password_change, test_server_session_integration, test_service_clients_persistent,
  test_session_gui_mirror, test_run_approvals, test_run_consents, test_deployment_receipt_api,
  test_deployment_prepare_api and test_provider_source_startup.
- **Node unit tests:** every non-browser `app/tests/*.test.mjs` passed, **204/204**.
- **Real browser:** browser-owner-recovery-t025, browser-owner-lifecycle-t025 and
  browser-first-use-integration-t023 passed, **10/10**.

### What remains open after this section

- **The real signing adapter.** No instance-operator recovery adapter signs with a real key.
  The tool only accepts receipts, and the signer exists only in tests.
- **No real deployment recovery.** No Compose, Portainer or HTTPS instance was recovered, and no
  `deploy/` step wraps the tool.
- **The lifecycle CAS.** T025's "separate lifecycle/consumption CAS" and "separate sealed
  request/signed receipt channels" are approximated: there is one pending pointer in the
  operator's work directory, and the database's consumption binding (the epoch-N+1 control row
  names the request id, nonce and receipt digest). It is not a separate CAS store or a pair of
  channels.
- **Items not addressed here.** The earlier open items still stand: the authorship of
  recovery-written decisions, already-approved v1 gates, and `CredentialVault`/`credential_client`.
- **The design's approval.** The recovery design file still says "proposal only". The repository
  holds no record of the owner's approval other than the 2026-09-24 test docstring: nothing in
  `decisions.md`, the tasks, the evidence or the commit messages. It was therefore left
  unchanged, and no approval is recorded here.
  *2026-09-26:* the owner has since approved the design, and that approval is recorded in `decisions.md`. The proposal's status line
  was updated. The other open items above are unchanged.
