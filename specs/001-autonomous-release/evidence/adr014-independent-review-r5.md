# ADR-014 independent architecture review — revision 5

Date: 2026-09-08
Input: `adr014-review-input-manifest-r5.md`
Input-manifest SHA-256: `2da9c4b1fc08200d80e222f82cc21367f61ac7d5ea0f6a0eaa61411862d3701f`
Verdict: **REJECT T086 closure**

## Findings

- P1: 0
- P2: 1
- P3: 0

### IR5-01 — duplicated tool effect receipt truth (P2)

The common `result.effect.effect_receipt_ref` was defined as the sole receipt truth, while successful
`tool-port-v1.invoke_tool` output independently allowed nullable `effect_receipt_ref` without an
equality constraint. Two conflicting receipts could therefore validate.

Required remediation: remove the output-level field so invoke success is exactly
`{tool_call_ref,result_ref}`, keep the common effect receipt as the only truth, reject the removed
field and aliases explicitly, and preserve `ToolResultArtifactBindingV1` semantics under `result_ref`.

T086 remains open. This verdict does not assess implementation, runtime qualification, distribution,
effectiveness, licensing or human acceptance and does not overwrite earlier review inputs/verdicts.
