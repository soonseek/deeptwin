# US4/US5 growth contracts — independent adversarial audit and remediation

Date: 2026-09-13
Scope: app/services/{alternatives,diagnosis,inquiry}.py at b3babe3

## Audit

An independent adversarial audit subagent (probe scripts preserved in the
session scratchpad `growth-audit/`) returned **REJECT** — 3 P1, 4 P2, 3 P3, all
reproduced. Its core diagnosis: the modules validated shapes rigorously but did
not defend their own invariants against in-process construction or reference
recycling, while `lenses.py` already demonstrated the needed defense
(init-disabled factories, issuer capabilities, evidence binding).

## Remediation (all ten findings closed, per-finding regression tests in
app/tests/test_growth_audit_findings.py, 10 tests)

- **F1 (P1):** synthetic material laundered through `.inner` into the whole
  loop. `OwnAlternative` now carries issuance-time `synthetic` provenance and
  `record_difference` accepts only `is_accepted_alternative` (real, issued,
  non-synthetic); `SyntheticAlternative.is_user_learning_evidence` is a constant
  property, not a field.
- **F2 (P1):** every growth value type was forgeable via public constructors /
  `dataclasses.replace`. All of `OwnAlternative`, `SyntheticAlternative`,
  `Difference`, `Hypothesis`, `HypothesisSet`, `Inquiry`, `OpposingPrediction`
  are now `init=False` with issuer tokens; construction and evolution happen
  only through the module factories, `replace()` fails, and every consumer
  (`record_difference`, `propose_hypotheses`, `resolve`, `open_inquiry`,
  `observe_evidence`, `conclude_inquiry`) checks issuance.
- **F3 (P1):** version-bumped renames and pre-freeze records re-entered as
  fresh evidence. The inquiry's exclusion set now covers the difference's whole
  boundary closure (original/alternative artifacts plus the boundary's inputs
  and outputs) and every hypothesis support/counterevidence/confirmation ref,
  matched by sha256 or (kind, id) — a rename cannot dodge it.
- **F4 (P2):** excluded/abstained lens decisions opened inquiries; the lens
  gate now also requires `state == "proposed"`.
- **F5 (P2):** the boundary's own outputs/inputs passed as a "user-made"
  alternative; they are now rejected. (Residual, documented: a genuinely
  foreign artifact ref still passes — true user-authorship validation needs the
  actor/provenance systems.)
- **F6 (P2):** the compared artifacts confirmed their own hypotheses and
  duplicate basis refs multiplied. `_evidence_refs` now dedupes and rejects any
  ref matching the difference's excluded closure by sha or (kind, id).
- **F7 (P2):** SPLI route evidence was never bound to the actual difference;
  `open_inquiry` now requires the decision's evidence hashes to contain the
  exact original/alternative/difference digests and its `alternative_scope` to
  match the difference's coverage.
- **F8 (P3):** stamps were regex-plus-lexical only; both modules now parse the
  exact datetime, so month-13/hour-25 stamps fail.
- **F9 (P3):** locator type failures leaked `DomainContractError`; both
  `Selector` and `Observation` now fail with their module's typed error.
- **F10 (P3):** `[no_generalization, one-causal-family]` satisfied the
  competition rule; a lone causal family now fails even beside the null, while
  two causal families plus the null remain legitimate.

Invariants the audit could NOT break (held probes in its report): lone-causal
rejection within a family-duplicated batch, difference/own_alternative kinds as
basis, API-level transition discipline, cross-difference confusion, and
foreign-registry lens decisions (the one type already built with the defense).

```text
python -m pytest -q (four growth suites incl. audit findings)
30 passed
ruff check (four touched files)
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,117 passed, 2 skipped, 369 subtests passed, 1 known warning
```

Frozen identities after remediation (SHA-256):

```text
aab37dc6b67c61820bd9b2bedf6cfe854774f02518c762f9ebfe4bd8564854eb  app/services/alternatives.py
f6b257403af0cba1819c41a5395e74d28888dca10fcbd55efcf78cda8229c23d  app/services/diagnosis.py
db6ac7089afca888368caa4d4dc69bcf90da5ee16f0c06913538c2fe5364de14  app/services/inquiry.py
7d2d10e0826cd9992865335a7591d4d67348f3337757c95a1253239e40f04424  app/tests/test_growth_audit_findings.py
```

This remediation itself has not been independently re-audited.
