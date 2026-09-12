# ADR-014 independent architecture review — revision 6

Date: 2026-09-08
Input: `adr014-review-input-manifest-r6.md`
Input-manifest SHA-256: `e8bb4c875a9714be9447d21fb37859fd1a193487a65e0350b7c94e6e9b7af0e3`
Verdict: **REJECT T086 closure**

## Findings

- P1: 0
- P2: 1
- P3: 0

### IR6-01 — isolated Markdown port row (P2)

In `contracts/extension-ports.md` §3.2, receipt-authority prose was inserted between the
`tool-port-v1` and `artifact-codec-port-v1` rows. Markdown therefore terminated the table before the
codec line, leaving a visually pipe-shaped but structurally isolated row. The semantic content was
otherwise unchanged, but a generator or reviewer could miss the codec contract.

Required remediation: keep the two rows consecutive, move the prose below the complete table, and
add an isolated-pipe/table-structure check that requires all eleven port rows to belong to their
contiguous header/separator table block.

T086 remains open. This verdict does not assess implementation, runtime qualification, distribution,
effectiveness, licensing or human acceptance and does not overwrite earlier review inputs/verdicts.
