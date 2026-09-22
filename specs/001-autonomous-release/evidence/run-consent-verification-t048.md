# Evidence — the run route verifies its consent, one consent per run (T048)

- Date: 2026-09-22
- Task: the Continuation's next step after the consent record (`run-consent-record-t048.md`):
  `POST /api/v1/runs` resolved its `consent_ref` by identity only; every route test fabricated a
  `{"fixture": "run_consent"}` row. experience.md §6.3 ("the server verifies each effect, version
  and scope independently"; `업무 시작` fixes this run's inputs and usage), data-model.md §3
  ("`RunConsent` authorizes a specific execution or bounded policy"), api.md ("403
  scope/consent"), runtime.md ("verify current consent … before dispatch" — the expiry/revocation
  half stays open).

## Frozen identities

```
a0fb1e2b4a2c6825eaee324e9d0a47017c85c3280bf2dc6c640374fe64ca0fa0  app/services/runs.py
850e03c36f4eb4184b64cd0ed5a7b5ec8f165490f4223f1ac9b44ec6eee5d316  app/services/run_consents.py
9e68240503d32dc1578732d98256946d37a3810a069d32349cbc0951d47453ac  app/tests/test_run_consents.py
4084f14b19b297c3467b7334058aae615663f88f69b4eccc698fe4cfa3c0d7ac  app/tests/test_runs_api.py
f54edf94b30c49653a302bbe7b63b3b0605e851d4f78b70fe985276f7f47a518  app/tests/test_works_api.py
```

(The `runs.py`, `test_runs_api.py` and `test_works_api.py` identities frozen in earlier slices are
superseded.)

## What was built

- `app/services/run_consents.py`: the read discipline is the module-level `resolve_consent`
  (the owner's human actor, the identity derived from the content's command, the exact content
  grammar, the `approval.decided` event the row names); the service's reads use it.
- `app/services/runs.py`: `_seal` calls `_consented` inside the writer transaction, after the
  five input records resolve and before the manifest is sealed — the consent must resolve
  under the whole discipline (a fixture or foreign row is no consent) and its four references
  must equal the command's `graph_ref`, `work_revision_ref`, `environment_ref` and
  `budget_policy_ref` exactly (kind, id, version, digest), else `access_denied` (403); and a
  manifest another command already sealed under this consent has spent it — a `conflict`
  (409), never a second run (one consent, one specific execution). Nothing is sealed or
  emitted on a refusal. A replay of a sealed command reuses its manifest (the consent is one of
  the bound inputs: any other consent under the same command is a conflict) and does not
  re-verify — there is no expiry or revocation yet (recorded open in the module docstrings).
- Tests: the run and works route fixtures seal real consents through the consent route
  (`consent_for`); the cancel test's replay replays the create body it sent.

## Review (independent, adversarial) and closures

- **ACCEPT WITH CHANGES** (1 MUST, 3 SHOULD, 2 NIT), folded in RED-first. MUST — the consent
  module's deferred list still named this verification as the next slice → rewritten (expiry
  and revocation, so `resume`/`recover` and sealed replays do not re-verify; the run mode; the
  environment ⇄ graph coherence). SHOULD — one consent started unbounded runs (a second command
  under the same consent: 201, a second budget session) → one consent, one execution: a manifest
  of another command naming the consent is a `conflict` (pinned RED first, with a fresh consent
  over the same inputs starting a fresh run); the pins added — an environment or budget
  mismatch → 403, the sealed manifest's `consent_ref` is the verified consent, the same command
  under another consent after sealing → 409 (a replay input, not a fresh verification); the
  double load of the consent record left as is (one transaction, immutable rows). NIT — the
  run service docstring names the verification; the lazy import is commented (the consent
  module imports this module's readers at import time; fresh-interpreter import orders probed
  by the reviewer: all fine).
- Reviewed and accepted: the ordering (absent consent or input → 404 from the record loads;
  a non-evidence row or a mismatch → 403; the consent before the graph/policy parse; 404 vs 403
  discloses only a row's existence to the single authenticated owner); the ledger `RunSpec`
  disclaims authorization, so the service is the layer.

## Verification

- TDD: RED retained (a run started under a consent over another graph), GREEN after
  `_consented`; the single-use rule RED (201) → GREEN (409).
- Tests: `test_run_consents.py` **8**, runs + works routes **58** together; the wider route,
  approvals, decisions, transaction and owner-integration neighbours **192**. Ruff: clean on
  the changed files.
- Full regression on the frozen identities above: **9,348 passed, 2 failed, 2 skipped** (Linux-only),
  369 subtests, 1h23m. The two failures — `test_provider_conformance_lifecycle.py::…monotonic_deadline
  …[preseal]` (`socket_peak` under a provider service error) and
  `test_provider_receipt_sources.py::…240_opaque_entries…` (`deployment_source_invalid`) — are the
  parallel orchestration's provider suites, touch nothing of this unit, and passed alone three
  times each after the run (66–76 s and 6 s). Recorded under the merged-tree reconciliation's
  disposition (order/timing-dependent under the 80-minute load); the recurrence of this class
  across the last three full runs (a different case each time) is noted for a dedicated
  chase-at-cause slice. The five identities above were unchanged across the run.

## Boundaries kept

- No expiry, revocation or dispatch-time re-verification; no `environment` producer; no page
  change; the ledger unchanged; no model, tool or paid call.
