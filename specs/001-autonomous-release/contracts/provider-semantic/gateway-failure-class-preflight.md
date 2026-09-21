# Task47 gateway failure-class amendment — independent design preflight

2026-09-20. Same independent reviewer; narrowly scoped interface review, **not formal R2 code review**.

## Verdict

**READY for explicit controller adoption of the reviewed proposal.** Blocking findings: **0**. No Critical or Important design finding remains in this frozen version. This verdict grants no implementation authority by itself and does not accept any Task47 implementation or proof result.

Reviewed proposal: `.superpowers/sdd/resumption-plan/task-47-gateway-failure-class-amendment.md`, SHA-256 `cdab83d07f32a488e500523f77753912c6a9efa973c276b59d48ff2615d78292` (117 lines). The controller's cancellation-precedence correction is included in this exact version; an earlier wording is not the reviewed/adoptable artifact.

## Scope and method

Read the entire frozen proposal and accepted master. Compared the exact durable response grammar in literal appendix §2, closed send-result/stream grammar in §7, effect/cancellation rules in §8, custody/deadline/cleanup requirements in §9, and canonical result/error rules in §10. Read both existing adopted corrections and the incorporated read-observation/cancellation amendment. The initially truncated combined appendix read was supplemented with complete reads of the relevant sections; this verdict does not rely on the omitted unrelated sections of that output.

Read-only hashes verified during this preflight:

| Authority | SHA-256 |
| --- | --- |
| Accepted master `contracts/provider-semantic-execution.md` | `120ab6299bc36993c3a8b6c3ab848eabbf59001456658efcf1c7f366dde65361` |
| Literal appendix | `dcf68d94934aac3e0dc1078a9620f4cdb7c6c12c70682f32681c8ca19b410fd4` |
| Read/cancel amendment | `3599b84bbb08e5fdf93675f67dffb657d9cfcb48d2153c8904d231d5d97c4ebe` |
| Gateway request-identity correction | `3458cadbcd89b1d6fe4875146c3f96a0bc2e044adb5e95c140eb47c6b6e904c8` |
| Reservation currency correction | `abc13f808136b18b2c0d9eb4a81821861d04ecbb02410006e977f34f7de70632` |

No moving R2 product code was inspected. No tests, imports, suites, helpers, subagents, dependency operations, native/live requests, credentials, commits, index changes or product edits were performed. The only written output is this review.

## Interface assessment

1. **The conflict and correction are real and bounded.** Appendix §7's original closed result has no field that distinguishes a gateway-local custody refusal, capacity failure or unavailable dependency. HTTP status cannot legitimately encode those causes, and the cancellation latch/phase cannot encode them either. Proposal lines 16–30 add one required nullable finite field to that result and the new private response record only. The eight values cover the selected local categories without adding arbitrary diagnostics, a second error object, upstream status reinterpretation or authority. Durable copying preserves the observed category for later checking instead of requiring reconstruction from exception text.

2. **Classification does not override effect evidence.** Lines 39–65 keep cause, wire completeness, actual send phase and cancellation latch separate. Complete HTTP exchanges, including non-2xx, have a null local failure class. Non-null local failures cannot masquerade as wire-complete success. A known pre-send refusal is `not_sent` and cannot carry upstream status/raw-response evidence. Conversely, valid partial upstream evidence is not erased merely because a local failure follows. `terminal_observed` alone does not authorize semantic success. These constraints remain compatible with independent normalization and the existing terminal/effect cross-product.

3. **Canonical precedence now preserves cancellation.** Lines 73–79 retain external-effect-unknown for non-cancellation model failures after possible write, but explicitly preserve the original observed-cancellation branch: cancelled status/error, unknown effect, null effect receipt and unconfirmed remote outcome. A fully verified success remains governed by the original acceptance race. This agrees with appendix §§8/10 and adopted read/cancel §3; a cancellation acknowledgement still cannot establish remote rollback, zero cost or permission to resend. Lines 80–88 preserve known-unsent local errors and read-only catalog outcomes separately from model-spend uncertainty.

4. **No-wire and expired-deadline handling remain implementable without fabricated evidence.** Lines 25–27 and 86–96 allow core to report its own observed failure when no trustworthy gateway result exists. Before a usable prepare/READY/exchange identity, the gateway need not manufacture an exchange ID or send an out-of-phase result. Missing results after a possible send cannot establish `not_sent`. Lines 90–96 explicitly forbid extending the original deadline or inventing successful cleanup; appendix §9's full unwinding, lock release and no-detached-thread obligations therefore remain binding.

5. **Secret and authority boundaries are preserved.** Lines 39–44 require deliberate typed/stage-local classification and prohibit exception-message matching, secret material, paths, snippets and arbitrary error objects. Actual raw response bytes continue through authenticated bounded streams into private evidence, not the enum or a synthesized exception body. Identity, correlation, sequence, response-descriptor checks and one-shot consumption remain mandatory. Neither the gateway nor worker gains DomainStore resolution, policy production, retry or settlement authority.

6. **Compatibility is appropriately limited to the unactivated profile.** Required-field omission is rejected, not silently treated as null. This is a coordinated change to the new dialogue/private response variant, not a backwards-compatible claim for already published records. The master must explicitly adopt the correction before implementation authority follows. The first accepted correction's statement that result fields stay unchanged describes that correction's own scope; it does not make a subsequent explicit one-field correction inconsistent. Its required semantic request UUID, prepare digest and local lease pins are untouched. The currency correction, canonical port schemas/idempotency bytes, old private protocols and existing record variants are likewise unaffected.

## Required proof interpretation and remaining nonclaims

The proposal's five proof groups are suitable bounded obligations; none has been executed or accepted here. Formal implementation review must verify actual authenticated receivers and durable rehydration, not just an enum helper or synthetic pass map. In particular:

- Exercise permitted delivered categories through real local failure branches and reject missing fields, unknown values, invalid types other than the expressly allowed null, and incoherent complete/refused/cancel/phase combinations.
- Keep proof §4.1 subordinate to §§2–3's original-deadline and no-wire rules. An actual deadline exhausted before result delivery must use the prescribed no-result/core-local path; it cannot gain a result-transfer grace period merely to demonstrate a delivered `deadline_exceeded` enum. Core must not persist an invented gateway cause. This is a qualification already required by the proposal, not a waiver of deadline proof.
- Distinguish complete HTTP rejection from local custody denial, preserve deliverable bounded partial bytes/status, and prevent partial evidence or a local failure marker from becoming successful semantic output.
- Cover known-unsent, possibly-sent non-cancellation, observed cancellation, genuine success race, failed read-only catalog and malformed/missing-result outcomes; retain immutable same-UUID history, no resend, held provisional reservation and exact private-record joins.
- Retain the original custody-currentness, cancellation-during-stream, cleanup and thread-lifetime proof. A classification field cannot remedy or excuse an unbounded operation or falsely reported gateway closure.

Actual validator/schema parity, error-branch classification, encrypted custody, transport behavior, resource cleanup, end-to-end accounting and regression status remain unverified by this design-only review. Earlier formal R1 findings remain open or closed only under their own evidence and subsequent formal review; this preflight closes none of them.
