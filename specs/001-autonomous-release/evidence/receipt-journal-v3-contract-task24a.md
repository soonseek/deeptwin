# Evidence — Task 24 step (a): deployment receipt journal v3 contract

- Date: 2026-09-18
- Task: Task 24 (stage postcondition acceptance and installation head, T087 partial), redraft
  step (a) of the order recorded in `resumption-plan.md` "### Task 24" after the 2026-09-18
  rejection. Deliverable: `contracts/deployment-receipt-journal-v3.md` (specification only; no
  code, migration, observer, consumption or installation is implemented by it).
- Prerequisite satisfied: Task 25 (worker-private probe channel) is complete (810b2cd), so the
  contract can name an actual control-side observation of a staged service.

## Frozen identity

```
f30347d2b340bc6ce61a6c71d7cf1e6a2e469d2ad3dea7cfa3d98f6a81f32c59  specs/001-autonomous-release/contracts/deployment-receipt-journal-v3.md
```

## What the contract fixes

- Thirteen-statement v3 DDL (four changed: migrations `IN (1,2,3)`, lifecycle `accepted` at
  revision 3, commands `deployment-consume-v1` (200, revision 3), consumptions
  `lifecycle_revision IN (2,3)`; two new: installations with `UNIQUE(extension_id)` and
  `UNIQUE(extension_id,request_id)`, installation_heads with `revision=1` and a composite FK);
  C1/C2 preserved; `CHECKSUM_V3 = ff0931661b7958805f3113bad954110ca702ba3c0205e6dadc73651508a51457`
  computed from the literal statements (seven imported byte-identical from `DDL`/`DDL_V2`).
- Migration v2 → v3 by the v1 → v2 algorithm with the stated reliance on SQLite deferred-FK
  semantics for the populated child tables (proved by the reviewer on SQLite 3.53.1 and required
  of the migration tests, including the commit-without-restores refusal).
- Evidence blob `extension-stage-postcondition-v1` (two probes, connection identities, peer
  uid/gid, `expected`, `comparison:"equal"`), constructed only by the observer module; the
  `expected` tuple pinned to retained records through `records.candidate`, `parse_lineage`,
  `validate_descriptor_lineage` and `parse_build_identity` of the selected platform's embedded
  identity; the verifier re-derives it by the same path.
- Installation anchor `extension-installation-anchor-v1` (kind `extension_installation`, absent
  head → revision 1, `previous_record_digest:null`, evidence blob ref, consume command id), the
  explicit coexist ruling for `extension-installation-v1`, the `app/domain/extension_installation.py`
  validator and regenerated envelope/event-metadata exports.
- Consumption anchor v2 (`winning_lifecycle_revision:3`, `outcome:"succeeded"`, `effect_ref`),
  v1 dispatch unchanged; no K marker for success.
- Admission matrix (receipt_pending2 + consume → accepted3; unavailable 503; mismatch 409;
  accepted3 + any → 409; expiry precedence), the global first-only managed-kind guard stated as
  it exists in code (at most one accepted3 per journal while it stands), the consume route
  `deployment.requests.consume` with a frozen 200 body, `prepare-api-v3`, the
  `deployment.request_accepted` registration next to `extension.staged`, the ObjectRefs of both
  events, the `consume` admission/replay operation string, and the storage/records/lifecycle API
  additions for steps (c)–(f).
- Boundary statements kept verbatim: `staged ≠ verified`; no qualification/binding/enable/
  dispatch; no replace/uninstall/retire arm; one-writer atomicity; expiry precedence; the live
  end-to-end run is Docker/colima host authority reported as a gate; no GUI.

## Review (independent specification review) and closures

Verdict: ACCEPT WITH CHANGES. The reviewer recomputed C3 from the fenced statements, created the
thirteen tables with `foreign_keys=ON`, exercised the CHECK matrix (accepted2, rejected3,
consume@rev2, consume@201, installation@rev2, head@rev2 all refused) and proved the migration's
deferred-FK behaviour and rollback on a real SQLite. Findings, all folded in:

1. MUST — the managed-kind guard was written "for the extension" while the code and journal v2
   make it global → stated global, with its consequence (at most one accepted3/installation per
   journal; later prepare/import/consume 409; caps are structural) and the deferral of a
   per-extension guard to the replace/uninstall arms.
2. MUST — `expected` pointed at "retained lineage evidence" that no deployment-side code names →
   pinned to the exact path (`records.candidate` bundle → `provenance` support document →
   `parse_lineage` → `validate_descriptor_lineage` → `parse_build_identity` of the selected
   platform's embedded identity); a failing provenance/join denies 409 in the first writer.
3. SHOULD — the migration silently relied on populated children surviving the parent
   drop/recreate → the reliance and the required proofs are stated; "descending
   `lifecycle_revision`" for commands.
4. SHOULD — boot ids pinned to hex64 while the transport grammar is wider → stated, with
   `probe_invalid` for a session outside hex64.
5. SHOULD — `installation_digest` undefined and no `installation_id` in the replies → defined as
   the anchor envelope sha256; `installation_id` added to the 200 body and the GET object.
6. SHOULD — "installation" is not a locator kind → exact `ObjectRef(kind="extension_installation",
   …)` for the staged event; the accepted event keeps the request ObjectRef.
7. SHOULD — event-metadata schema export is byte-pinned to `EVENT_TYPES`; `_admit`/`_replay`
   need the `consume` operation string → both stated.
8. SHOULD — observer signature contradicted "one process boot ID"; `expected` untyped;
   correlation wording → boot id owned by the observer (no parameter), `ExpectedStageIdentity`
   frozen value, correlation to the probe request frame's `message_id`.
9. NIT — GET disposition derivation stated (from the accepted3 head; stored import reply frozen).
10. NIT — tightened DDL adopted (composite unique/FK between installations and heads); C3
    recomputed to `ff09…1457` and re-verified here from the fenced text.
11. NIT — `extension.staged` verified through `installations.event_id` and excluded from the ≤ 48
    deployment event universe.

## Verification

- C3 recomputed from the contract's fenced SQL plus the byte-identical imported statements
  (exact block extraction, thirteen tables created in an FK-on SQLite): equals the frozen value.
- No code changed in this step; the full regression of 810b2cd (5969 passed, 2 skipped) stands.
- Next: step (c) pure record/head/consumption-v2 codecs, absent-only, RED-first.

## Boundaries kept

- Specification only: no migration, observer, consume transaction, route, installation,
  qualification, binding, enable, dispatch, replace/uninstall/retire arm; no live container/
  socket/worker claim; no GUI.
