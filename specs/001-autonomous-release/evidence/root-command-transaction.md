# T016 root command transaction — offline implementation evidence

Verified 2026-09-08 in the authoritative worktree
`<repo>`. The implementation and a
fresh independent adversarial review are complete for this root-transaction slice. The
authenticated HTTP delivery is recorded separately in `evidence/server-api-v1.md`. No provider,
tool, network, credential store, paid API or user vault was accessed.

## Implemented boundary

`RootCommandCoordinator.execute_budgeted_dispatch` accepts one authenticated, CSRF-verified
local mutation request and an exact registered `attempt.dispatch` command. It binds the command
target/revision/hash, selected grant, operational resource, frozen attempt owner, budget policy,
budget request digest, reservation and runtime identity before dispatch authorization can pass.

The coordinator requires the exact same session authenticator object as the permission host. It
holds the process writer lock continuously across the business transaction, any rollback clock
recovery, and post-commit permit activation. One hardened `DomainStore` connection owns the
SQLite write transaction, which performs, in order:

1. durable API command intent;
2. permission/grant/revocation/revision/expiry verification on the supplied connection;
3. conservative budget reservation plus the runtime may-have-sent barrier, journal, internal
   event and runtime command result;
4. one typed `EventEnvelope` and allowlisted `PublicEventView` cursor;
5. one completed durable API receipt whose product state remains `pending`.

The command/event/runtime/budget/permission components recheck exact type, canonical path,
single main database, vault identity, inode/link boundary, schema/migration state and hardened
SQLite settings. Because no production trigger is registered in the shared schema, any trigger
in the database blocks the transaction. Cross-vault API rows and attached databases are rejected.

`RuntimeLedger` now separates transactional send-intent staging from process-local capability
activation. The root transaction receives an unregistered `DispatchPermit`; only after SQLite
commit succeeds, while the writer lock is still held, does it add that exact capability to the
one-shot permit registry. Rollback at any earlier stage exposes no permit. Exact API replay
returns the original receipt and `permit=None`; concurrent duplicates therefore produce one
durable result and one post-commit capability.

Permission, runtime and budget clocks each maintain a process-monotonic observed floor. If the
root transaction rolls back after permission evaluation, one recovery transaction atomically
persists all floors that were reached; a floor already durably higher is valid and remains
unchanged. `BaseException` paths are covered, so interruption cannot silently discard these
observations. Keeping the writer lock across rollback and recovery prevents a later command from
overtaking the recovery boundary.

If an observed floor cannot be captured or the atomic recovery cannot persist, the coordinator
emits only the fixed `root_clock_watermark_failed` fatal code and retains no raw exception or path
text. It then globally inhibits runtime dispatch for that process: all outstanding one-shot
permits are revoked, and new staging, activation and consumption are rejected. Permit removal,
durable validation and return share the same writer-lock order, closing the pop-before-writer
race in which a consumer could otherwise overtake fatal inhibition.

Public event pages are materialized with their cursors in one read snapshot. The local session is
authenticated both before and after materialization, so expiry or revocation during the read does
not release the projection. Browser-visible event values omit actor, vault, access-policy and
private-evidence references.

## Failure-first and current verification

The initial contract was intentionally 1 pass / 11 failures because
`app.api.transaction.RootCommandCoordinator` did not exist. The completed focused contract now
covers success, failure injection after each of five transactional stages, exact replay, changed
payload under the same command ID, revoked permission, stale target revision, duplicate races,
continuous writer ownership through recovery, all three clock floors, lower-floor no-op,
`BaseException`, capture/persistence failure redaction, global inhibition and outstanding-permit
revocation:

```text
python -m pytest -q app/tests/test_api_command_transaction.py
23 passed in 19.10s (independent review run)
```

The latest combined transaction/session/event/permission/budget/runtime regression is:

```text
python -m pytest -q app/tests/test_api_command_transaction.py \
  app/tests/test_local_session.py app/tests/test_public_events.py \
  app/tests/test_runtime_budgets.py app/tests/test_runtime_budget_dispatch.py \
  app/tests/test_runtime_ledger.py app/tests/test_domain_permissions.py
251 passed in 36.17s (independent review run)
```

| File | SHA-256 |
|---|---|
| `app/api/transaction.py` | `55497d520ecdde1105bee5148b053e0647aa16a7520af71ffc6e855e5cd6d514` |
| `app/api/commands.py` | `f7c1512edbab66123dd5110127824bfd41442f6f50ea4be8fb4c57722cf1de71` |
| `app/api/views.py` | `cfc655fa5c52bf53a938ff422839ae10b9e4e87015ad40e3f855b450dd58d51b` |
| `app/runtime/ledger.py` | `e2ecc5988694d406fb8807196ff8d7abbc8fe68ae15f380637ce34e545714044` |
| `app/runtime/budgets.py` | `6ab615d5491437ad92ba6c989e5e90e9f8b5c2b2de18c314ccf4e7dac1a8d6d6` |
| `app/domain/permissions.py` | `3e1d631fad40dfdf61b7924ca69dbb497086ff1639a6fd83ad58e67c8aee79b9` |
| `app/tests/test_api_command_transaction.py` | `c91fe2ad0590d86bfac5be567d55f3de71a7aff941541e1424677dd371f2eaef` |

These hashes identify the independently reviewed implementation snapshot; they are integrity
references for this evidence, not release signatures.

## Honest limits

This proves local transaction atomicity up to the may-have-sent barrier. It does not prove remote
exactly-once delivery, provider acceptance, terminal result reconciliation, artifact sealing or
tool execution. No provider/tool call is made by this coordinator or its tests.

The root coordinator is wired to the authenticated HTTP command route by the server delivery
slice. Public SSE/Last-Event-ID, gap and snapshot HTTP behavior, including the default resolver's
fail-closed no-effect response, is covered in `evidence/server-api-v1.md`. Neither slice proves a
full future product-state projection for graph/design/growth features that have not yet been
implemented; those feature projections remain owned by their later tasks.
