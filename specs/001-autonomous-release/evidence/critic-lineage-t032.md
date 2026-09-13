# Evidence — T032: critic lineage exact-hash binding

- Date: 2026-09-13
- Task: T032 [US2] bind counterexample/validity/candidate-response exact
  hashes and parent provenance in app/critic_audit.py; reject forged
  cross-call evidence (B4).

## Frozen identities

```
aa677826f922d5ce61eac2e2e29b7ce25e07ceb584be016e446dd37c7435ea5d  app/critic_audit.py
2e51959b934d538b185ddc025f181464642893668148e7c00384cc65be131655  app/tests/test_critic_lineage.py
```

## What was built

- **Evidence registry** — a new `evidence` table in the audit journal;
  `register_result_evidence(request_id, items)` records the SHA-256 of
  each canonical evidence object a COMPLETED call produced (an
  uncompleted call has no result and registers nothing). These hashes are
  the only cross-call currency.
- **Lineage-bound reservation** — `reserve_with_lineage(call,
  parent_request_id, evidence_sha)` for the three downstream purposes:
  - the parent-purpose chain is fixed (proposal←review,
    validity←proposal, response←validity; a review has no parent);
  - the parent must exist, be `completed`, and bind the SAME run,
    candidate id and candidate version;
  - validity/response must present an evidence hash actually registered
    under that exact parent — a hash the parent never produced is forged
    cross-call evidence and refuses; a proposal binds its review by
    request only and refuses a superfluous hash;
  - lineage verification, budget check and reservation commit in ONE
    transaction; the stored call's details and the reserved event record
    the lineage parent (and hash).

## Verification (6 tests, TDD — methods absent first)

- The full review→proposal→validity→response chain reserves with real
  hashes (independently recomputed in the test).
- A never-produced hash, an unfinished parent, a cross-run parent, a
  cross-candidate parent, a wrong-purpose parent, a parentless review
  claim and a proposal carrying a superfluous hash all refuse.
- Evidence registration is bounded, requires an existing completed call
  and object payloads.
- One fixture fix (canonical JSON encoding); one own lint (RUF012) fixed
  by hoisting the purpose map; the file's pre-existing I001/TRY004 stay
  as-is per the standing precedent.
- Full regression **3340 passed, 2 skipped** (was 3334).
