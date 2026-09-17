# Evidence — Task 24 step (e2b): the service consume transaction

- Date: 2026-09-18
- Task: Task 24 redraft step (e), the service orchestration of the consume transaction —
  `contracts/deployment-receipt-journal-v3.md` §4 (`expected` derivation from retained
  records), §5 (admission, expiry precedence, observation between the writers, preseal,
  final-writer rechecks, one commit), §6 (admission matrix, error partition, replay). Builds on
  (d) the observer, (e1) the storage, (e2a) the acceptance writer. The route is (f).

## Frozen identities

```
47c81b2344f42d96f4e56455bb76544d472bb327d6bae4d3c3899cdeab41e2d6  app/deployment/prepare_service.py
724a505889b1635fec16ca84f44e13fbf18a4d8ddb6a3fe034f64dfea2751fb1  app/deployment/prepare_records.py
292bb92a2959544c49ed791f40b2499388f864159b7db52b933d4e36af515563  app/deployment/stage_observer.py
1b9b44a1ec76b3a00cb671b399717054682947837931b9ac5d22812e528d0010  app/tests/test_deployment_consume.py
b120e8f87703cfb33de775ed7510f3288ccfe880f41fd8280c9867246ad5877a  app/tests/test_deployment_acceptance.py
bc767770c629223173566fbec9cf08c052d536ef347b0a8e860494a90fdef972  specs/001-autonomous-release/contracts/deployment-receipt-journal-v3.md
```

## What was built

- `app/deployment/prepare_service.py`: `consume_receipt(authenticated_request, request_id,
  payload)` — `parse_consume`, `_admit` (the `consume` operation replays only
  `deployment-consume-v1` commands: an exact replay returns the frozen reply with no
  observation); first writer: authenticate, full journal, replay, `_consume_head`
  (receipt_pending2 head, matching digests and revision, a succeeded receipt, the global
  first-only guard), durable clock, expiry precedence (a due head commits `expired3` and the
  command is 409 without any socket), `records.expected_stage_identity`; outside the writer:
  `observe_stage_postcondition` (a mismatch is 409 conflict, unavailable/deadline/invalid are
  503 dependency_unavailable), `put_blob` preseal; final writer: authenticate, journal, replay,
  head, clock, expiry again, the expectation re-derived and required equal, the evidence
  re-parsed and its `expected` required equal, `records.accept_stage`, full verification, one
  commit. A failure after the preseal leaves only the orphan blob.
- `app/deployment/prepare_records.py`: `expected_stage_identity(domain, db, profile, item)` —
  the candidate bundle by the request anchor's candidate ref (ref equality required), exactly
  one `provenance` document, `parse_lineage`, `validate_descriptor_lineage` with the profile's
  instance id and the request's slot, the selected platform's embedded build identity through
  `parse_build_identity` (`digest`, `schema_set_digest`), the lineage's port contract version,
  and `contracts.slot` for identity/uid/gid; a candidate without a valid joined lineage is a
  conflict. `_load_installation` now re-derives the expectation through the same path and
  requires the evidence's `expected` to equal it (the (e2a) deferral closed).
- `app/deployment/stage_observer.py`: `_now()` reads `time.time_ns()` — the same clock source
  as the owner authority — so the observation time and the journal's `now` are one clock.

- `app/tests/test_deployment_acceptance.py` (part of this change set): because the verifier
  now re-derives the expectation from the candidate lineage, the (e2a) acceptance tests run on
  the lineage-joined candidate and their evidence names that lineage's identity digests (the
  synthetic digests can no longer verify); the module imports the consume module's fixture
  helpers, so the four modules and both test files land together.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (no defect in the transaction; nine scratch probes green). The
reviewer traced the first and final writers step by step against §5, confirmed the error
partition against §6 (`expected_revision:1` is 400 by the contract's own body pin), confirmed
the replay is served before any writer work and that the identity-differs case is refused by
the observer (`probe_mismatch`, both probes served), and confirmed that the embedded-identity
digest equals the worker's file digest because both sides parse through `parse_build_identity`.
Closures:

1. MUST — the acceptance-test adaptation was outside the declared change set and load-bearing
   → named above; the four modules and both test files are committed together, and the
   regression gate is re-run after the last edit.
2. SHOULD — the fault-injection test never proved the fault fired after the preseal → the
   blob count is asserted to be exactly one more (the orphan blob the contract allows).
3. SHOULD — untested admission rows → `probe_invalid`/`probe_deadline`/`probe_unavailable` are
   503 with no blob and no transition; a replay with a changed body and an import command id
   presented as a consume are 409 with no observation; a prepared head without a receipt is 409
   before any socket.
4. SHOULD — the seam statement was incomplete → every seam is enumerated in one place (the
   `StagedWorker` docstring) with what each one means this suite cannot claim.
5. NIT — the observer's `_now()` rounded differently from the owner clock → it renders
   `time.time_ns() // 1_000_000` through the shared `stamp`.
6. NIT — the contract §4 named `selected_platform(...)["build_identity"]`, a projection that
   has no identity → the contract now names the platforms entry selected by its measured
   platform, as the code does.
7. NIT — `candidate()` sat outside the mapping try → inside; any inner code is a conflict.
8. NIT — a dead import removed.

## Verification

- TDD: RED retained — `AttributeError` on the missing service method; then the fixture work:
  the staged worker must be installed after prepare/import (its seams would otherwise break the
  T-slot lease), must live on the source fixture's remapped pair root with fake ownership
  (`os.chown` replaced by ownership registration, the AF_UNIX alias, thread-keyed mountinfo),
  and its metadata tree must bypass the fixture's directory remap; the fixture reports real
  ownership for unregistered inodes. GREEN after those fixture corrections and one test slip
  (a closed connection reused).
- Tests (14): consume against the actual in-process `WorkerProbeService` commits accepted3
  (counts, the read body, the evidence's `expected` equal to the re-derived expectation, the
  requester boot id, an empty registry, exact replay without a second observation, fresh
  consume/cancel/import 409 afterwards, descriptors released); a worker whose identity file
  differs from the lineage is a 409 with nothing presealed; no listener is 503; a candidate
  without a lineage provenance is refused before any socket; wrong digest 409, wrong revision
  refused, unknown request 404, a due head expires to revision 3 and 409 without observation;
  a cancel between preseal and the final writer is caught by the recheck; a fault at each of
  eight authority writes (both anchors, both events, three index rows, the commit) leaves no
  partial acceptance and the head at receipt_pending.
- Covering (consume, acceptance, receipt import, v3 migration, stage observer, extension
  probe, prepare, receipt journal integrity): **208 passed, 6 failed** on the first run — the
  six were the (e2a) acceptance tests, whose fixture candidate carries a synthetic provenance
  while the verifier now re-derives the expectation from the lineage; they now run on the
  lineage-joined candidate with evidence naming that lineage's identity (36 passed). Ruff clean.
- Test honesty on this macOS host: the responder is the actual probe service through the same
  seams as the listener/observer tests plus the source fixture's fake ownership and path
  remapping; positive Linux authentication, real mounts, the real worker image and the
  container/socket runtime remain host gates, never claimed.
- After the closures: consume 21 and stage observer **48 passed**; Ruff clean.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No HTTP route (f), no reconcile/publication change, no replace/uninstall/retire arm, no
  qualification/binding/enable/dispatch; `staged ≠ verified`; the global first-only guard
  stands (at most one acceptance per journal); the live end-to-end run is a Docker/colima host
  gate; no GUI.
