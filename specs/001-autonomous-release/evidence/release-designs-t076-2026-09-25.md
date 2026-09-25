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

## Audit 3 (of release-v3): AUDIT FAIL → release-v4

A third independent, read-only audit of release-v3 and its data-driven verifier found three blocking problems (BF1–BF3) and several non-blocking ones. release-v1, v2 and v3 and `lens-effects-v1..v3.json` are unchanged (byte-identical to their freezes). Because v3's `FROZEN.json` pins the product gate, changing the gate made a new design version: **release-v4** (`evals/deeptwin/qualification/release-v4/`, `evals/deeptwin/effects/lens-effects-v4.json`, manifest `release-v4/FROZEN.json`). That manifest pins v1–v4, every earlier manifest, the gate (`app/services/critic_qualification.py`), the verifier modules (`sealed_critic.py`, `q01_core.py`, `q01_release_manifest.py`, `app/critic_contract.py`, `app/critic_audit.py`) and the harness (`q01_harness.py`). v3's manifest still records the gate as it was when v3 was frozen. Its guard test now checks that hash against `git show bd6a976:app/services/critic_qualification.py` rather than against the working tree, and a comment explains why.

| Finding | release-v4 response |
|---|---|
| BF1: `build_suite_record` took the V3 status from the caller, and the gate trusted a record's V3 field and `record_sha256`, so a forged "verified" record reached `qualified`. | The verifier derives V3 from the design and the pinned profile, never from the caller. It is always `unverified`, because v4 has no generation path (`V3_VERIFYING_DESIGN_IDS` is empty), and the v4 suite-record schema allows only `unverified`. The gate reads only `q01-release-v4` records. It recomputes `record_sha256` (canonical JSON, UTF-8, record without the key) and refuses a mismatch. It caps every record of a design that cannot verify V3 at `scoped_pass` (`design_cannot_verify_v3`). `qualified` is reachable only from a design in the gate's `V3_VERIFYING_DESIGN_IDS`, and that set is empty. The design-approval tests use a test-only design id that the gate admits only through a module hook marked TEST-ACTOR (`_TEST_ACTOR_V3_DESIGN_IDS`, set only inside `actor_v3_design()` in `app/tests/test_environments.py`). A test asserts that the production path never yields `qualified`. |
| BF1 (approval binding): design approval should bind the qualification's configuration digest to the critic that produced the verdict. | **Open.** Criticism verdicts do not carry a critic configuration digest yet. This is stated in the gate docstring and the v4 design (`acceptance.open`), and it is required before any V3-verifying design is admitted. |
| BF2: acceptance could be met with a caller-chosen repetition count, one trial reused for several repetitions, hand-built results, a manifest check that could be skipped, or a composition opt-out. The suite was not bound to the manifest. | Repetitions are fixed at 3 (`REPETITIONS_PER_CASE`, no parameter). Each `verify_trial` result carries the trial id, the trial record sha256, the ledger head, the manifest sha256, the configuration digest, the judge identity and prompt digest, and its own `result_sha256`, and it is registered as issued. `verify_suite` refuses results that were not issued or were altered since. It also refuses one trial used for more than one slot, and results from another manifest, configuration or judge. `load_release_run` always re-checks the full manifest, so there is no hash-only path. The suite is incomplete unless the manifest pins these exact expectations, materials and case order. `SealedExpectations.composition_checked` is recorded and required for a pass. Judge separation comes only from the pinned profile bytes: the sha256 must match, the profile must name `q01-release-v4`, and its judge must equal `run_identity`. `build_suite_record` accepts only an issued suite and the same run, and re-checks the bindings. |
| BF3: the lens pack was read from the sealed bundle as dataset material, and the lens-effect run had no per-arm configuration, order or attempts. | The lens pack is critic configuration. `lens_refs_and_digests` = {pack id, version, sha256, per-rule digests}, and the harness receives the pack through `PreDispatch.lens_pack`. The verifier and the harness refuse a sealed case that carries a lens pack. The harness checks the pack actually sent at every proposal call, and the verifier re-checks it from the ledger. `lens-effects-v4.json` plus manifest schema v2 define `lens_effect`: per-arm configurations and digests (arms may differ only in their lens set), per-arm attempt entries, the arm × case order (every pair exactly once), and non-null text digests for `general_multi_perspective` and the lens arms before dispatch. `single_use` means one sealed effect set and one run covering all arms. |
| Non-blocking: harness identity was optional. | `PreDispatch.harness` and `lens_pack` are mandatory for release trials. The harness also compares the given identity with `harness_identity()` of the running code. |
| Non-blocking: configuration fields were not checked at dispatch. | Checked before any read: contract and parser version, `critic_prompt_digest` (instruction, renderer and profiles), chains, both deadlines and lens digests. Provider, mode, model and effort are checked against each call's frozen selection. `max_tokens` cannot be observed offline and is recorded as unchecked in each trial record. |
| Non-blocking: deadlines were optional. | The v2 schema requires `call_seconds` and `run_seconds`. |
| Non-blocking: no attestations. | The v2 schema requires author, reviewer and sealing attestations. The manifest check refuses an author who is also the reviewer, and a judge who is the author or the reviewer. |
| Non-blocking: the verifier identity omitted the product contract and audit code. | `VERIFIER_FILES` now include `app/critic_contract.py` and `app/critic_audit.py` (`q01-sealed-verifier-2`). |
| Non-blocking: v3 said the verifier did not exist. | v4 `verifier.state_at_freeze` records `exists: true`, the version, the file-set sha256 and every file hash. `harness_at_freeze` records the harness identity. |
| Non-blocking: it was implicit that the effect design does not measure the §8 joint-error change. | `lens-effects-v4.json` `not_measured.joint_error_change` states it explicitly: there is no generation path. |

Probe tests (every one now fails as it should):

- In `evals/deeptwin/tests/test_sealed_critic_verifier.py`:
  - a forged "verified" V3 status is capped and a caller V3 argument is refused;
  - a forged `record_sha256` is refused;
  - one trial reused for 3 repetitions is incomplete (`trial_reused`);
  - `planned_repetitions=1` and one repetition per case are refused or incomplete;
  - hand-built or altered results are refused;
  - a manifest for another expectation set, dataset or case order gives incomplete;
  - a composition opt-out gives incomplete;
  - a caller-supplied judge flag is a `TypeError`, and the profile's sha, design id, judge and V3 claims are all checked;
  - a lens pack in the bundle is refused;
  - a lens pack at a call that does not match the configuration is invalid in both the harness and the verifier.
- In `app/tests/test_environments.py`: the gate probes.
- In `test_release_design_frozen.py`: the v4 guards.

Verification: the evals tests (excluding live) and the listed app tests pass; the counts are in the commit report. All data is test-actor synthetic data. Nothing was dispatched to a provider.

Still not true:

- No sealed set, author, reviewer or independent judge exists.
- V3 cannot be verified under v4.
- Verdict-to-configuration binding in approval is open.
- No multi-arm effect dispatcher exists, so lens-effects-v4 cannot execute.
- Issued results are recognised only within the verifying process.

T076 stays open until an independent audit of release-v4 passes.
