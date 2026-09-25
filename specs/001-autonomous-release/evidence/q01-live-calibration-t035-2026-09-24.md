# Q01 initial live calibration of the critic (T035, 2026-09-24)

Status: **executed. The critic configuration does not qualify.** On the complete tuned run it
passes 6 of the 10 development boundary cases. Under the strict per-suite rule the suite
verdict is `fail`, score 0.0. No lens or critic qualification follows from this, so the
design arc's qualified-lens gate stays closed. T035 stays open, because no scoped
qualification record was issued (there was nothing to qualify). These are observed
development cases, and after the prompt change they are tuned cases too: none of them can
ever be release heldout.

## Frozen configuration

- **Plan:** `evals/deeptwin/qualification/calibration/run_plan.json`, pinned sha256
  `8793d002…`.
  - Critic: `claude-opus-5` through the owner's API connection, effort `medium`, 16k max
    tokens.
  - Judge: the same model, effort `medium`, 4k max tokens.
  - The 10 cases once each, at most 2 proposed chains, concurrency 1.
  - No retry and no model fallback.
  - Hard spend stop: USD 6.00 per run, at $5 / $25 per million tokens.
- **Independence profile:** `independence_profile.json`. The critic and judge share provider
  and model, so correlated errors are possible and **independence is not established**.

## Runs

| Run | What changed | Result | Calls | Est. USD |
| --- | --- | --- | --- | --- |
| 1 (`observed/run-1-results.json`) | none | 1 pass, 8 fail, 1 invalid (0 invalid under the fixed verifier) | 38 | 3.59 |
| 2 (`observed/run-2-results.json`) | critic prompt states two contract rules | 6 pass, 1 fail, **3 not run** (spend stop) | 70 | 5.54 |
| 2, continued (`observed/run-2-continued-results.json`) | only run 2's not-run cases, same plan and profile | complete: **6 pass, 4 fail** | 34 | 2.67 |

**Run 1.** Seven of the eight failures broke the output contract, from two rules the
critic's prompt never stated:
- It cited a section of `original-images`, an original without text availability and so with
  no citable sections. It also once named the criteria document by the wrong id.
- It answered `mitigate` or `avoid` to a **rejected** counterexample, where the contract
  requires `unresolved`.

These were found by replaying the saved raw outputs offline against the contract (free).
The eighth failure was c18, a real semantic miss.

The one `invalid` was a verifier bug. The verifier took the case key from how far a trial got,
so a counterexample case that stopped at review was judged as the plain case (or `invalid`
when none exists). It now keys a trial by its recorded frozen case (regression test added).
Re-verifying run 1's records without a judge made that trial an ordinary contract `fail`.

**Run 2.** The two rules were stated in the product critic prompt
(`design_criticism_live._CITATION_RULE`). Run 2 then used more stages per trial, because
passing trials go on to the later stages, so its spend stop left three cases unrun. A
continuation (`run(..., continue_from=…)`) accepts only the same pinned plan and profile.
It carried the seven verified trials over unchanged and ran only the three.

## The complete tuned result, by case

- **Pass (6):**
  - accepting normal candidates: c71, c24, c86, c09, c53
  - rejecting an unfounded counterexample: c71/ce-29
- **Fail (4):**
  - **c86/ce-17:** output contract.
  - **c71/ce-17 and c42/ce-43:** review Q2 left `unresolved` where the materials support a
    pass. The critic was too cautious about full hand-off, and it is a false non-pass.
  - **c18:** review Q1 `pass` where the attribution evidence is removed and the answer must be
    `unresolved`. This is overconfidence, the very failure Q6 guards. The judge independently
    marked the related item `not_supported`, but that is a shared-model agreement, not an
    independent check.

## What this does and does not show

- The critic's contract failures are mostly prompt-statable, and fixing them was cheap.
- The remaining failures are judgment calibration, in both directions (too cautious on Q2, too
  confident on Q6).
- No guarantee is claimed: one repetition, a shared critic/judge model, and development cases
  the developer has read.
- A qualification needs:
  - a sealed set not seen during tuning
  - an independence profile that separates critic and judge (for example, another provider or
    a human reviewer)
  - more than one repetition

Total spend on these three runs was **about $11.80** (session total so far: about $15.8 of the
$20 budget).

## Joint errors, abstention and valid alternatives (2026-09-25)

These counts were derived offline from the recorded complete tuned result (`observed/run-2-continued-results.json`) by `evals/deeptwin/qualification/calibration/analyze_observed.py`, guarded by `evals/deeptwin/tests/test_calibration_analysis.py`. They come only from the verifier's rule checks and judge items. No call was made, and no rate is inferred.

- **Abstention.**
  - The critic left 15 of 72 review findings `unresolved`, across the 9 trials that produced a valid review. 13 of these are on Q5–Q8, where the expectations allow it. 2 are on Q2 (c71/ce-17, c42/ce-43), where the materials support a decision; these are the two false non-passes above.
  - No counterexample proposal abstained: all 9 proposal stages proposed chains.
  - Of the three counterexample validity judgments, ce-29 was `rejected`, ce-17 `valid` and ce-43 `unresolved`. All three match the expectations.
- **Valid alternatives.** Both accept cases passed without a false rejection: c71, and c24, which is an alternative accepted on its substance.
- **Critic/judge joint errors.** The critic made 3 semantic errors (the 2 Q2 abstentions, and the c18 Q1 overconfidence).
  - Only c18 has a judge item on the same criterion, and there the judge disagreed with the critic (`not_supported`). So 0 joint errors were observed, out of 1 measurable item.
  - The two Q2 errors had no covering judge item, so for them joint error is **not measurable**. It is not "absent".
  - The judge marked 1 of 36 items `not_supported`, and that one flag was correct.
  - Critic and judge share a model (`independence_established: false`), so this agreement pattern is not evidence of independence. V3 is not addressed.

With this, T035's scope is met: the calibration and independence profile are frozen, the authorized live trials were executed, the result (6/10, suite `fail`) is recorded, and joint errors, abstention and valid alternatives are recorded with their denominators, with no guarantee invented. No critic or lens qualifies. All ten cases are observed/tuned development data and never release heldout. The release qualification belongs to T076 (frozen and audited) and T077 (execution).
