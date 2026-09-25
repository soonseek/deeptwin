# T076 — release qualification designs: v1 frozen, audited, v2 frozen (2026-09-25)

## What exists

- **release-v1** (commit 3508883, unchanged): `evals/deeptwin/qualification/release-v1/{qualification_design,independence_profile,FROZEN}.json`, `evals/deeptwin/effects/lens-effects-v1.json`.
- **release-v2** (this change): `evals/deeptwin/qualification/release-v2/{qualification_design,independence_profile,FROZEN}.json`, `evals/deeptwin/effects/lens-effects-v2.json`. The v2 manifest pins the v2 files, the v1 files and the v1 manifest, so neither version can be edited silently.
- Guard: `evals/deeptwin/tests/test_release_design_frozen.py` (4 tests) checks every hash in both manifests and the key v2 limits.

## Independent audit of v1 and what v2 changes

An independent review agent read v1 against Task.md, the spec (V3/V6, FR-006, SC-005) and the T035 calibration record. It found blocking gaps and smaller issues. v2 addresses them as follows.

| Audit finding (v1) | v2 response |
|---|---|
| The configuration identity was incomplete: lens refs, judge identity and prompt digest, dataset sha256, `max_proposed_chains`, deadlines and parser version were missing. | These are now `configuration_under_test.identity_fields`. They are fixed before the first dispatch; any change makes a new configuration. |
| Nothing stopped the sealed set being reused or a run being continued (T035 used `continue_from`). | `single_use`: the first dispatch marks the set observed. Exactly one run is allowed, with no continuation, merge or rerun. |
| Storage and readers of the sealed set were unspecified. | The set is stored outside the repo, recorded by path and sha256. Readers are listed before, during and after the run. |
| There was no required criterion coverage. | At least one required defect for each of Q1, Q2 and Q3, a valid Q4 alternative, and Q5 pairs. |
| A contract-breaking output could be treated as an invalid trial and not scored. | Such an output is a fail of that repetition. Invalid trials are only harness, evidence, isolation or judge failures. |
| Judge errors and run authority were not recorded. | Every judge verdict is logged beside the expectation. A run without a recorded authority and budget is not executed. |
| Reporting hid misses, false rejections and abstentions. | These are reported per class, with real denominators, joint critic–judge errors and cluster counts. |
| A pass could be read as meeting V3 error independence. | `claims_if_passed` states that V3 remains unmet. The profile's `v3_error_independence.status` is `unverified`, and it lists what is fixed now and what is not. |
| The judge-independence claim was unconditional. | `judge_separation.established: false`. Semantic items count only under a profile version where it is true. |
| The lens-effect design lacked the §8 comparison arms. | It adds `strong_existing_procedure`, `no_lens` and `general_multi_perspective`. `user_construct` is `not_runnable_data_needed`: no real user constructs exist and none are invented. It holds the other application points fixed, uses the same total budget, and fixes predictions in advance. |

## What is still not true

- No sealed release dataset has been authored. An author independent of the verifier's developer is needed, and none is available here.
- No independent judge exists yet, either human or another provider. v2 therefore cannot execute, and no release qualification or lens effect is claimed.
- V3 error independence is unverified.

T076 stays open until an independent audit of v2 is recorded as passing and the dataset preconditions are met.

## Audit 2 (of release-v2): AUDIT FAIL → release-v3

A second independent, read-only review confirmed several things:

- All pinned hashes match, and v1 is byte-identical to commit 3508883.
- No calibration data is admitted, no user alternatives are invented, and no universal thresholds are set.
- Contract errors are scored as fails, and a constant output cannot pass.

It then found 8 blocking problems. v2 is kept unchanged. **release-v3** (`evals/deeptwin/qualification/release-v3/`, `evals/deeptwin/effects/lens-effects-v3.json`, manifest `release-v3/FROZEN.json`, which pins v1, v2, both manifests and the product gate) answers them:

| # | v2 problem | v3 response |
|---|---|---|
| B1 | The frozen verifier (`verifiers/critic.py`) is hard-wired to the ten calibration cases, so every trial on a new set would be invalid. | A data-driven verifier is required. It loads sealed expectations (`sealed_expectation.schema.json`, which mirrors Expectation/EvidenceRule/judge items) only at verify time. Its version and sha256 go into the pre-dispatch manifest before sealing. The author writes the judge rubrics and a fixed-criteria text for the new materials. **The verifier is not implemented yet**, so v3 cannot execute until it exists. |
| B2 | The dataset and judge were part of the configuration identity, so a product critic could never match a qualification. | The fields are split into `critic_configuration`, with the one digest a pass binds to, and `run_identity` (dataset, expectations, judge, profile, harness, verifier, order, authority, stop). |
| B3 | The pinned profile can never be established, so v2 can never pass, yet the product gate whitelisted v2. | A successor profile is frozen and committed before sealing, names v3, and its path and sha256 go into the pre-dispatch manifest where the harness checks them. The gate now accepts only `q01-release-v3`. |
| B4 | It was undefined what a pass confers, and the outcome classes were misaligned. | `suite_outcome`: fail (any valid repetition failed) > incomplete > not_judged > pass. `suite_record.schema.json` includes the V3 status. A pass is a **scoped_pass**, not a qualification, while V3 is unverified. `critic_qualification.py` returns `scoped_pass` for it, and design approval needs `qualified`. |
| B5 | Unlimited attempts, and spent sets could be reused. | An `attempt_ledger` numbers every attempt per configuration digest across sets and versions, and claims cite attempt k with every prior verdict. `must_be_new` excludes every previously dispatched set. |
| B6 | Pre-dispatch commitments could be edited without trace. | `pre_dispatch_manifest.schema.json`. Its sha256 is committed (or externally timestamped) before the first dispatch. The harness refuses to run otherwise, and any later edit makes the attempt incomplete. |
| B7 | The effect design dropped the dataset rules. | The effect set follows the v3 dataset rules in full, is disjoint from every qualification and earlier effect set, and covers applies/abstains cases. |
| B8 | The baseline arms had no fixed content. | The `general_multi_perspective` text is frozen by digest before access, taken from a published checklist or written by a non-lens author; it is `text_not_yet_fixed` now. `strong_existing_procedure` is declared a duplicate of no_lens because no stronger procedure exists. |

The notes are handled as follows:

- **N1:** exclusions happen only before dispatch.
- **N2:** each verdict gets a post-verdict audit, and a defect found there voids the verdict to incomplete.
- **N3:** `joint_error` is labelled separately from `judge_disagreement`.
- **N4:** covered by the B8 fix.
- **N5:** the budget unit, cap and interleaving are defined.
- **N6:** the lens pack is treated as configuration, and the predictions include applicability and abstention.
- **N7:** the gate and older manifests are pinned, and the guard test covers v3.
- **N8:** the unmet quantitative-qualification decision is stated.

Guard: `evals/deeptwin/tests/test_release_design_frozen.py`, 7 tests, including the check that the product gate accepts exactly the v3 suite-record schema. A third independent audit of v3 is required before T076 can close.
