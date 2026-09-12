# T010 persistent permission registry — implementation evidence

2026-09-08 · bounded T010 storage/authorization slice; later T016 root/server integration is
tracked in its own evidence and does not expand this slice's completion claim.

## Result

The release constructor is structurally bound to one initialized canonical domain vault:

```python
create_persistent_policy(
    domain_store: DomainStore,
    *,
    authenticate_session,
    verify_projection,
    clock,
)
```

It rejects a legacy `Store`, subclasses, arbitrary record resolvers/verifiers, and alternate
persistence callbacks. The vault ID comes only from `DomainStore.roots()`. Permission state
uses that exact object's database path, hardened `_connection`, and shared domain writer lock.
`domain_vault` must exist and contain exactly the same canonical vault ID. The separate
`create_policy(...)` constructor remains available only for deliberately process-local unit
services and cannot be configured with persistence arguments.

The additive content-hashed `permission_migrations/policy@1` component verifies every owned
table/index definition on synchronization. It rejects every trigger anywhere in the shared
database whose SQL references a `permission_*` identifier, regardless of identifier case or
the table to which the trigger is attached. This prevents a cross-table trigger from silently
resetting permission generation. Descriptor, grant, projection and control rows are canonical
and digest-bound; an already-running host additionally refuses any observed policy revision
below its prior revision.

`permission_control` persists a digest-bound `last_observed` trusted-clock watermark beside
the policy revision. Every persistent authority entry synchronizes through a write transaction
and compares the current clock with that watermark. Successful later observations are stored
with CAS semantics. Both same-process clock rollback and restart with a clock earlier than a
previously observed expiry attempt fail closed. Live principals are intentionally not
serialized: restart requires a newly authenticated human, an exact trusted runtime binding,
and explicit `claim_grant(grant_id, issuer, subject)` before a persisted grant can be used.

Grant rows durably bind issuer actor, subject actor/kind/purpose, exact immutable ref, action,
purpose, optional episode, finite expiry, state and policy revision. Revocation and projection
withdrawal are retained as durable state, advance policy revision, and invalidate old handles.
Each descriptor is resolved from the same `DomainStore`; permission storage never stores a
second copy of domain record bytes. Missing, foreign, cyclic, rewritten, relabelled, unavailable
or transitively sensitive evidence fails closed.

Compiler projections are rebuilt from canonical bytes and compared exactly with the supplied
frozen value before any projection-row or policy-revision mutation, again inside the transaction,
and again through the persisted row before commit. Every projected value must still exactly match its canonical
hypothesis source. The current contract allowlist for direct observed-behavior support is only
`original_execution` and `comparison_result`; audit, lens, design, work-model, hypothesis and
user-alternative records are not permissive substitutes. Extending the allowlist requires a
reviewed/versioned contract change.

The public `PolicyGate.authorize(...)` is a decision-only surface and returns `None`; it never
releases a `ResourceDescriptor`, raw immutable record, or source private metadata. Authorized
bytes remain available only through `read(..., loader=...)`. Compiler data is available only
through `compiler_input(...)`, whose exact allowlisted, deeply immutable shape is target/change
kind, condition/action/exception/prediction and field-level support refs.

## Same-transaction T016 seam

`PolicyGate._authorize_in_transaction(db, principal, ref, *, action, purpose, grants,
episode_id=None) -> None` is the private root-command seam. It requires a persistent host and
an already-active, writable SQLite transaction for the exact canonical main database, with the
DomainStore hardened pragmas and no attached database. It opens and commits no connection. All
schema/domain/control/clock, canonical record, descriptor, principal, grant, revision,
revocation and expiry checks use only the supplied `db`. The resolver uses DomainStore's
bounded `_read_roots`, `_check_graph` and `_load` routines directly, avoiding a nested
`DomainStore.get()` transaction.

If a root business transaction rolls back after authorization, its in-transaction clock update
rolls back even though the process-local clock floor has advanced. The implemented T016 root
captures that observed permission floor together with any observed runtime and budget floors,
then persists all available floors in one recovery transaction while retaining the shared writer
lock. `HostPolicy._persist_clock_watermark_in_transaction(db, observed)` validates the exact
schema/domain/control binding and only raises the durable floor; a floor already durably higher
is a successful no-op. It changes no policy revision, resource, grant or projection. The older
standalone helper delegates to this same primitive for permission-only callers. This preserves
business rollback without allowing an expired authority observation to disappear.

## Failure-first and adversarial checks

Before remediation, isolated audit repros demonstrated the six boundary failures:

- a policy for vault A accepted vault B resolver/verifier callbacks and authorized a foreign
  canonical record;
- an expired grant observed at 1200 could be reclaimed after restart with the clock reset to
  1000;
- a dataclass-substituted projection could reuse a verified digest while changing protected
  target or values;
- `lens_definition` could be supplied as if it were direct behavioral evidence;
- public compiler authorization returned a record-bearing descriptor containing raw private
  data; and
- an uppercase trigger attached to legacy `events` reset `PERMISSION_CONTROL`, resurrecting a
  stale revision-one grant.

The green suite now has explicit regressions for those repros plus:

- exact same-path/connection ownership and exact `permission_control` schema;
- rejection of the old callback-based persistent API and a foreign `DomainStore` record;
- restart reauthentication/claim and exact action/purpose/ref/episode/expiry/generation checks;
- persisted clock rollback after a denied expired-grant claim;
- canonical projection substitution before any row or revision mutation;
- the narrow registered-kind behavior-evidence allowlist;
- decision-only public authorization and the compiler-input-only projection surface;
- cross-table uppercase trigger rejection and an in-process self-consistent revision rollback;
- exact same-transaction authorization with a monkeypatched guard proving no nested database
  connection and rejection of foreign/nonpersistent transactions; an independent review also
  probed and confirmed rejection of a same-vault read-only connection;
- outer business rollback followed by clock-only durable stabilization, plus rollback rejection
  in both same-transaction authorization and the stabilization helper;
- migration/control/schema/descriptor/grant/projection tamper detection, concurrent writers,
  peer invalidation, transaction rollback, transitive taint, durable revocation and projection
  withdrawal.

## Verification

Fresh focused run:

```text
$ python -m pytest app/tests/test_domain_permissions.py -q
69 passed in 4.19s
```

Fresh permission/shared-domain compatibility run:

```text
$ python -m pytest app/tests/test_domain_permissions.py app/tests/test_local_session.py \
    app/tests/test_domain_storage.py app/tests/test_runtime_budgets.py -q
248 passed in 11.72s
```

Syntax compilation of both production and test modules also passed. The subsequently implemented
T016 root-command coordinator now exercises this private seam, including exact authenticator
binding, continuous writer ownership, `BaseException` rollback, atomic three-clock recovery,
lower-floor no-op and fatal global dispatch inhibition; its independently reviewed focused suite
passes all 23 tests.
That later integration result is supporting compatibility evidence rather than part of the green
T010 count above.

| File | SHA-256 |
|---|---|
| `app/domain/permissions.py` | `3e1d631fad40dfdf61b7924ca69dbb497086ff1639a6fd83ad58e67c8aee79b9` |
| `app/tests/test_domain_permissions.py` | `787301a1132db965343dad85686bd727afaff71d8bb3aeba0cb042c7f0fd10f0` |

## Deliberately open integration boundaries

This permission slice is not itself an authenticated HTTP command boundary. The T016 root-command
coordinator now uses the same-transaction seam to provide the atomic permission + domain mutation
+ budget reservation + dispatch/event transaction, translates opaque denials, and stabilizes all
observed clock floors after outer rollback. HTTP command/SSE/snapshot delivery is implemented and
reviewed under the separate T016 server evidence; any unresolved delivery finding remains there
rather than being treated as permission-slice completion.
Tool/version/recipient/use-count/byte-limit grants remain the richer T047 dispatcher contract.
T057 and later evaluation work must provide durable semantic-verification receipts and prove
the truth/effect of compiler candidates.

The digests and in-process revision floor detect corruption and rollback relative to live
state; they are not a cryptographic monotonic anchor against a same-OS actor coherently
replacing the entire database and all application history with an older snapshot. Safe
backup/restore needs its own authenticated snapshot generation/receipt contract. The
process-local constructor is not release persistence. No credential, network call, paid model
call or user database was used.
