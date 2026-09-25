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
