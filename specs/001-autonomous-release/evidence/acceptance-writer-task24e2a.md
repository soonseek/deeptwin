# Evidence — Task 24 step (e2a): acceptance writer, accepted3 rules, events and v3 read

- Date: 2026-09-18
- Task: Task 24 redraft step (e), second half's first part (e2a): the one-writer body of the
  consume transaction and everything the journal needs to hold, verify and read an accepted3
  request — `contracts/deployment-receipt-journal-v3.md` §4 (records, bijections, evidence
  grammar), §5 (final-writer part), §6 (events, consume reply, read fields), §7 (API names).
  The service orchestration (admission, expiry precedence, `expected` derivation, the observer,
  presealing, final-writer rechecks, fault injection) is (e2b); the route is (f).

## Frozen identities

```
2953067ac16725408043a124b8c08911e8bee066eb294b09e034c2bed1738e56  app/deployment/prepare_records.py
c4fce2220ae83559d3d09881154908ceec6efd28809b3e91fbbd45913be2d1ba  app/deployment/prepare_lifecycle.py
c4b913a4cbe50abe20eca02f6a3069f6ec9af4a8de7c9659c0baa9ab8a397933  app/deployment/stage_observer.py
3271baae03e3a3ccf441c899386e6527078477aef38488e643f2cfb8a1552520  app/domain/events.py
c2e83e868dd8ab25362c2e5091cf5d1c43c44ba989bdc382f31af3f6e72a292c  schemas/v1/event-metadata.schema.json
d518b2a88e4da5fc24a317b0f7654fb46bed970c4fabfcb2c7a4e43ae8615518  app/tests/test_deployment_acceptance.py
d85869b2a0aefeff4ce0c103f2d52640ea91c031267d1132130c39f93d226ee3  specs/001-autonomous-release/contracts/deployment-receipt-journal-v3.md
```

## What was built

- `app/domain/events.py`: `deployment.request_accepted` registered next to the other deployment
  events (`revision=COUNT`); `schemas/v1/event-metadata.schema.json` regenerated (byte-pinned).
- `app/deployment/stage_observer.py`: `parse_stage_evidence(raw)` — the pure closed grammar of
  `extension-stage-postcondition-v1` (canonical bytes ≤ 8192, every field and nested shape
  exact, B32/hex64/Time/UInt32/Nonce/BrokerId grammars, exactly two probes with distinct
  challenges and four distinct ids, every reply's compared fields equal to `expected`, the peer
  equal to the slot, `comparison:"equal"`); it proves nothing about the request it names.
- `app/deployment/prepare_lifecycle.py`: `event_fields` for `accepted` (type
  `deployment.request_accepted`, status `succeeded`, error null, metadata `{revision:3}`, human
  actor; revision 3 required); `_append_transition` admits `receipt_pending → accepted`;
  `installation_summary`; `commit_acceptance_transition` (the frozen consume 200 reply with the
  installation summary and the `deployment-consume-v1` command at revision 3);
  `staged_event_fields`/`append_staged_event` (`extension.staged` with the installation
  ObjectRef, correlation = consume command, causation = acceptance event, metadata from the
  fixed stage arm's port contract, revision 1); `read_body` adds `installation` and derives
  `consumed_success` from the accepted head (the stored revision-2 import reply is unchanged);
  `verify` gains the accepted3 arm (receipt_pending2 → accepted3 with a succeeded receipt),
  the consume namespace with `parse_consume`, and the frozen consume reply equality.
- `app/deployment/prepare_records.py`: `accept_stage(domain, db, roots, profile, item, *, now,
  actor_ref, value, evidence, evidence_bytes)` — exact head and receipt, `expected_revision`
  2, matching digests, the global managed-kind guard, the evidence BlobRef against its bytes and
  the stored blob, the parsed evidence against the request/receipt (id, digests, retained bytes'
  SHA-256, service identity, platform); then, in this writer: the installation anchor
  (`_installation_anchor`, every field from the retained request and the receipt's Present
  result), the acceptance transition and event, the staged event, the consumption anchor v2
  (`effect_ref` = installation), the consumptions/installations/installation_heads rows.
  `_load_consumption` handles the v2 success shape; `_load_installation` re-verifies the anchor
  content, the evidence blob (re-parsed, consistent with the item), the head row, the
  command/consumption/time linkage and the `extension.staged` event byte for byte; the per-item
  rules are `accepted ⇔ installation ⇔ consumption at revision 3`, `rejected ⇔ consumed outbox`;
  the (e1) closure line is replaced by the loader; the deployment event universe includes the
  new type.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES. The reviewer traced every refusal to its raise site through the
real fixture, confirmed the exact edge/blob counts, the anchor/row/reply shapes, both events'
fields, the accepted3 verifier arm, the read bodies of every reachable state against
`prepare-api-v3`, and that the (e1) crafted-row window is closed by the per-item rule and the
`(request_id, 3)` foreign key. Closures, all RED-first:

1. MUST — neither the writer nor the verifier compared the evidence's `expected`/peer identity
   with the admitted slot (internally consistent evidence about uid/gid 7 was accepted) → both
   go through `_evidence_agrees`: `service_identity`, `uid`, `gid` and the channel id must equal
   `contracts.slot(profile.instance_id, row.slot_id)` (never the blob alone); the build/schema
   digests stay for the service's lineage join (e2b), which must also reach the verifier.
2. MUST — `observed_at` was unbounded (an observation in 2099 was accepted) → the writer
   requires receipt-import time ≤ `observed_at` ≤ `now`; the verifier requires it inside the
   receipt-import → acceptance window.
3. MUST — the writer body had no time precondition (an acceptance at the deadline produced a
   journal every later read refuses) → `history[1].transitioned_ms ≤ now < expires_ms` is a
   `conflict` precondition; tests at the deadline, one past it and far before the import.
4. SHOULD — the `consumption_revision` damage case was refused by the stale row hash → the
   row is re-hashed so the `lifecycle_revision` rule refuses; an `installed_ms` case reaching
   `_load_installation` added.
5. SHOULD — the `_append_transition` arm had no direct negative → refused from `prepared` and
   without a command on the real store.
6. NIT — the contract's §7 loader signature aligned with the implementation (`profile`,
   `head_rows`) and `accept_stage` named there.
7. NIT — the staged event's kind/tier come from the port contract constant → a comment names
   the request-time pin (`stage_for_candidate`) that makes it the admitted tuple.
8. NIT — the staged event's sequence is now required to be the acceptance event's + 1.
9. NIT — `accept_stage` re-parses `value` through `parse_consume` before trusting its shape.
- Not closed here: the verifier does not yet re-derive `build_identity_digest`/
  `port_schema_set_digest` from the candidate lineage (e2b adds the derivation to the service
  and to `_load_installation`).

## Verification

- TDD: RED retained — `AttributeError: module 'app.deployment.prepare_records' has no attribute
  'accept_stage'` ×17, `'parse_stage_evidence'` ×6, the unregistered event; GREEN after one
  implementation slip (two relative imports in the appended parser) and two test-side
  corrections (an Absent receipt result carries no service identity; a canonical B32 literal).
- Tests (27): the writer commits the installation anchor/head, the success consumption v2, both
  events and the frozen reply on the real store (`records.verify` and the read body validated
  against `prepare-api-v3`; the stored import reply keeps `pending_postconditions`; a second
  acceptance and a cancel of the accepted head are 409); ten evidence deviations (request id,
  receipt digest, request bytes digest, `comparison`, one probe, repeated challenge, service
  identity, peer, a differing reply, an extra field) are refused with the head untouched; a
  prepared, rejected or cancelled3 head is refused; four broken relationships (missing head,
  missing installation, a consumed outbox for a success, a consumption at revision 2) fail the
  verifier; the lifecycle admits `accepted` only at revision 3; the event registration and the
  regenerated export; the evidence grammar's closed cases.
- Covering (acceptance, receipt import, v3 and v2 migration, receipt journal integrity and
  reconciliation, prepare, domain schema exports, v3 contracts, v2 schema exports, stage
  observer): **212 passed**. Ruff clean on every changed file (`events.py` keeps exactly its
  pre-existing I001/F821 findings on untouched lines).
- After the closures: acceptance **36 passed**; Ruff clean.
- Full regression (`app/tests deploy/tests`, watchdog 1500 s): **6085 passed, 1 failed, 2 skipped**;
  the one failure was the pre-Task-22 artifact byte-pin meeting the regenerated
  `event-metadata.schema.json` (required by journal v3 §6) → the test names it as the second
  authorised regeneration (pinned to the live export by the domain export test); re-run green with
  its module and the export suite; no `app/` code changed after the full run. Adapted test hash:

  ```
  e032c000250195e4fcbde29037077c1884003b71816f73250cff5985242203ce  app/tests/test_extension_lineage_contracts.py
  ```
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No service `consume_receipt`, no observer wiring, no route, no `expected` derivation from the
  candidate lineage (e2b), no replace/uninstall/retire arm, no qualification/binding/enable/
  dispatch; `staged ≠ verified`; the evidence in these tests is built by the test in the
  contract's grammar, not observed; the live container/socket/worker run stays a host gate; no GUI.
