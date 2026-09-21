# Owned semantic worker connection contract

Adopted 2026-09-21 for Task49 implementation only.

The exact [reviewed R1 design](provider-semantic/owned-connection-design-r1.md)
is normative for the worker-only owned connection prerequisite. Its draft/pending
header is retained as provenance; this master adopts its requirements after the
independent R1 review passed spec and executable-design readiness with no findings.
It does not adopt any claim of completed behavior, native qualification, artifact
admission, installation, production activation or a complete browser journey.

Snapshot SHA256: `54f3c528543ef4e0d043e514535043b2223ce453136ad7651874c4e42935a914`.
Independent review SHA256: `a3350da7f1ddbc6023c4d2c976f6511fa0c4d982062e8738dcd3df9c5a623c0e`.
Review evidence: `.superpowers/sdd/resumption-plan/task-48-design-r1-review.md`.

The earlier semantic execution, installation, conformance and ADR-014 contracts
remain unchanged. This adds only the three specified owner-preserving entrypoints,
private adapter and finite behavioral proofs within the seven-file ownership set.
No product code may read this document or the scratch workspace as runtime policy.

Task49 implementation amendment: allow one additional test-only file,
`app/tests/test_provider_semantic_vertical.py`, for sanitized diagnostics on its
existing fresh-catalog assertion. All predicates, scenarios and budgets stay exact.
This supplements the seven-file R1 proposal without changing its product interfaces,
wire or acceptance criteria; it is not a claim that the observed transient is fixed.
