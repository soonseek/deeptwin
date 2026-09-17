# Evidence — owner decisions over an exact subject; design approval (T036, environments part)

- Date: 2026-09-17
- Scope: replace the caller-declared `{"actor_id", "authenticated": True,
  "evidence"}` approver of `record_design_approval` (app/services/environments.py,
  T036 "exact `DesignApproval`", FR-006/FR-008) with authoritative owner-session
  evidence, through a shared producer that later consumers (retention deletion,
  T069 follow-up) can reuse. T036 itself stays open: design_review /
  critic-lens pipeline work is untouched.
- Builds on: `run-approvals-human-gate.md`, `promotion-approvals-t065.md`.

## Frozen identities

```
17dfb1ae3a8bf01ee570062165d6ae6aace4758932486830c59c67be47727519  app/services/owner_decisions.py
f0d6877e395e1ee7609d90a2752418898c13160e5e098ae7697142d1f2b13430  app/services/environments.py
be31ec3756e31c49b94e6cdd12de8b9a5bd6bd79e3caa2ff1dfa28d5ae5190a5  app/tests/test_owner_decisions.py
c9a4de64fc9834f0f015d86e799bd5fbe60a84ecae0edfec16715efbe77e8cbb  app/tests/test_environments.py
2f46c84a589a714977cf772c917a5df5854b0ad859432d675396d04dc21272d7  app/tests/test_design_store.py
3d2bcce27c4d9d19709354d0fa5b01ab8348cb8d8b68099801dc07a72b848ae6  app/tests/test_design_audit_findings2.py
```

## What was built

- `app/services/owner_decisions.py` — `PersistentOwnerDecisions.record(request,
  payload)` / `resolve(ref)`, issuing `OwnerDecision(subject_kind, subject,
  subject_sha256, decision, command_id, approval_ref, actor_ref,
  decided_at_utc)`. The persistent owner session is re-authenticated inside
  the final writer (authentication precedes command parsing); one immutable
  `action_approval` per command (identity uuid5 over the command id; exact
  replay returns the same value, any other body under the same command
  conflicts) stores the closed subject kind (`design_approval` | `deletion`),
  the subject verbatim, its canonical SHA-256, the decision (`approve` |
  `reject`) and the `approval.decided` event sequence appended in the same
  transaction. A subject is plain JSON only: no dict shaped like a stored
  record reference or a blob reference, no `*_ref`/`*_refs` keys, no floats,
  bounded depth/size — the producer, never the store's reference scan, is
  what refuses it. The issued subject is a read-only copy. `resolve`
  re-validates content with the writer's grammar, the identity derived from
  the command, and that the named event is the `approval.decided` event whose
  correlation id is this very command.
- `app/services/environments.py` — `design_approval_subject(value)` derives
  the exact subject the human approves (environment id, design identity,
  verdict digest, candidate id/version, binding identities — identities as
  `(id, version, sha256)` fields, never references). `record_design_approval`
  takes `{environment, candidate, verdict, approval, model_bindings,
  tool_permissions, observation_contract}` and accepts only an issued
  `OwnerDecision` with kind `design_approval`, subject equal to the one it
  computes itself (dict equality AND digest equality — Python treats `1 ==
  True`, the digest does not) and decision `approve`; approver id, evidence
  and time come from it. A recorded reject approves nothing. Because
  `approval_sha` now includes the writer-issued evidence and stamp, one owner
  decision yields exactly one `DesignApproval` and one preparation, also
  across `restore_environment_state`.

## Review (independent, adversarial) and closures

Verdict on the first cut: REJECT (narrow). Closed RED-first:

1. Blob-reference-shaped dicts (`vault_id, purpose, sha256, size`) passed the
   subject check and were indexed by the store (a deletion subject would pin
   the blob it deletes) → refused by the producer; parametrised case.
2. Dead float branch (canonical JSON carries no floats) → removed; `1.5` is a
   refusal case. 3. Issued `subject` was a mutable dict → `MappingProxyType`
   over a deep copy; mutation raises. 4. `resolve` checked only the event
   type → also the envelope's correlation id; test writes an owner-authored
   record naming another command's decided event. 5. `design_approval_subject`
   accepted superset keys → exact set (plus `approval`).
- Tracked follow-up (review finding 2): `persist_design_approval`
  (app/services/design_store.py) encodes `approver_evidence_ref` as a tagged
  string, so a persisted approval can carry evidence from another vault; it
  should resolve the evidence through `PersistentOwnerDecisions` bound to the
  same store before persisting. Not closed here.
- `app/extensions/port_schema_generator.py:1848` reads `authenticated` off a
  trusted actor record for system/worker actors — not the caller-declared
  human-approval shape; outside this ruling.

## Verification

- TDD: `ModuleNotFoundError` / `ImportError` on the absent module and helper
  first, then GREEN; each closure RED first.
- Covering command (owner decisions, environments, design store, design
  audit findings 2, promotion approvals, run approvals): **86 passed, 1
  inherited warning, 23.07s**. Ruff check/format clean.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No route or GUI calls the producer yet (§6.3 "이 설계로 준비" screen is UI
  work); no model/tool/paid call; no publication; no license decision.
- `retention.py` `delete_items` still takes the caller-declared actor dict
  (T069 follow-up; the `deletion` subject kind is reserved for it).
