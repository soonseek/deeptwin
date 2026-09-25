# T076: the data-driven release-v3 verifier (2026-09-25)

release-v3 (`evals/deeptwin/qualification/release-v3/qualification_design.json`) cannot run without a data-driven verifier. Its `verifier` block says the verifier must load the sealed expectations only at verify time and derive material checks and leak markers from the sealed set. It must also keep the outcome classes and the six boundary classes of `evals/deeptwin/verifiers/critic.py`, and it must not use that file's calibration expectations. This change builds that verifier. It also adds the harness side of the pre-dispatch freeze.

No frozen file was edited: nothing under `evals/deeptwin/qualification/` or `evals/deeptwin/effects/`, and not `app/services/critic_qualification.py`. The design's `verifier.state_at_freeze` still says "not yet implemented". That is correct for the frozen text. The verifier's version and sha256 go into each pre-dispatch manifest, as `FROZEN.json` `not_pinned_here` requires.

## What exists

- **`evals/deeptwin/verifiers/sealed_critic.py`** (`VERIFIER_VERSION = "q01-sealed-verifier-1"`).
  - `load_sealed_expectations(bytes | Path, expected_sha256)` checks the sha256 of the bytes before parsing and refuses a mismatch. It then parses strict JSON (a duplicate key or NaN is refused) and validates it against `sealed_expectation.schema.json`. Next it applies boundary-class rules to the authored data, not only to the labels:
    - accept: no criterion allows fail.
    - required defect: Q1, Q2 or Q3 is `{fail}` with an evidence rule.
    - rejected: the counterexample is rejected, the response is `{unresolved}`, and no criterion allows fail.
    - valid: the response is either `{fail}` or a subset of avoid/mitigate.
    - unresolved claim: both the counterexample and the response are unresolved.
    - insufficient: some criterion is `{unresolved}`.
    - Also checked: counterexample, validity and response are given together or not at all; judge selectors are valid; judge item ids are not duplicated.
    - Composition: at least 2 cases per class, a required defect for each of Q1, Q2 and Q3, and a Q5 pair. The verifier refuses a set that breaks composition by default. "A valid Q4 alternative" cannot be decided from the expectation data, so it stays a reviewer check.
    - The result is the shared `Expectation`, `EvidenceRule` and `Ref` structures.
  - `load_sealed_materials(files, manifest_sha256)` loads the sealed materials bundle. The bundle is a mapping of published path to bytes, in the harness environment layout (`environment/manifest.json` plus `environment/cases/<case id>.json`), together with the sha256 of the manifest bytes. Every listed file must match its sha256, unlisted files are refused, each case file must have the frozen-case shape, and each case id must follow the published case-id rule. `load_sealed_materials_dir` reads the same layout from a directory and refuses symlinks.
  - `check_binding` confirms that the expectations and the bundle list the same cases. For each case it confirms:
    - the authored counterexample matches;
    - the criteria are exactly Q1..Q8;
    - every evidence group cites something visible.

    It also refuses a bundle whose materials contain answer content: a boundary name, a case id, or a whole basis or rubric.
  - `answer_markers` are the boundary names, the case ids, each whole basis and rubric text, and basis/rubric fragments of 24 or more characters that do not occur in the agent-visible corpus. They are taken from the sealed set, never from `Task.md` or `critic.EXPECTED`.
  - `verify_trial(record, *, expectations, materials, judge, repetition, …)` follows the same order and classes as `critic.py`:
    1. Trial validity. Ledger re-derivation, journal coverage, lineage, the case key, access and leaks, and materials: the visible inputs, lens pack, authored counterexample and case sha256 are compared with the bundle. Any failure gives `invalid` with no score.
    2. An output-contract error gives `fail`.
    3. Rule checks.
    4. Semantic items, only through a `SemanticJudge`. With no judge, or a judge answer of `undetermined`, the result is `not_judged`. `not_supported` gives `fail`. A judge exception or unknown answer gives `invalid` (`judge_fault`).

    An invalid trial is still attributed to its case when the record names a sealed case. Each result carries the sha256 of the expectations and of the materials manifest.
  - `verify_suite(results, *, expectations, planned_repetitions, pre_dispatch_manifest_sha256, committed_manifest_sha256, judge_separation_established=False, stopped=False, manifest_bytes=None)` applies `acceptance.suite_outcome` in this order:
    1. **fail**: any valid repetition failed.
    2. **incomplete**: any of the following:
       - an invalid, missing, duplicated or unplanned repetition;
       - an unattributable result (another verifier, other expectations, or no case);
       - results verified against different materials;
       - a stopped run;
       - a recorded manifest sha256 that is missing or differs from the committed one.

       When `manifest_bytes` is given, the manifest is also re-checked in full: schema, digest, attempt, verifier identity, sealed expectations and dataset sha256, and case order.
    3. **not_judged**: a not_judged repetition, or judge separation not established. Separation defaults to not established.
    4. **pass**.

    `case_pass` is true only if every planned repetition is present exactly once and is a valid pass. The result reports counts per boundary class (pass, fail, not_judged, invalid, missing) and the causes of invalid results.
  - `build_suite_record(suite, *, manifest_bytes)` builds a record that validates against `suite_record.schema.json`. It takes the configuration digest (recomputed), the sealed set sha256, the attempt, the prior outcomes and the profile sha256 from the manifest. It re-checks the manifest, and a manifest that does not verify turns a would-be pass or not_judged into incomplete; a fail keeps precedence. `record_sha256` is the sha256 of the canonical JSON of the record without its `record_sha256` key. Canonical JSON here means `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`, UTF-8 encoded. `check_suite_record` re-verifies the schema and the hash.
  - `verifier_identity()` returns `{"version", "sha256"}`. The sha256 is taken over the canonical JSON of `{path: file sha256}` for `sealed_critic.py`, `q01_core.py` and `q01_release_manifest.py`. At this commit it is `63e29405ea62c71b979ca5aec039df617d5e3492bdf0215ef1a70a4b00776be9`. This is informational: it is fixed only when a pre-dispatch manifest records it.
- **`evals/deeptwin/q01_release_manifest.py`** is the pre-dispatch manifest check, shared by the harness and the verifier. `check_pre_dispatch_manifest(bytes | Path, *, committed_sha256, harness=None, verifier=None)`:
  - requires a committed sha256 and checks the file bytes against it;
  - parses strict JSON and validates it against `pre_dispatch_manifest.schema.json`;
  - recomputes `critic_configuration_digest` from `critic_configuration`, using canonical JSON with sorted keys, separators `(",", ":")`, UTF-8 and `ensure_ascii=False`;
  - checks that `attempt == len(prior_attempts) + 1` and that the prior attempts are numbered 1..k-1;
  - optionally checks the harness and verifier identities.
- **`evals/deeptwin/verifiers/q01_core.py`** holds the parts of `critic.py` that do not depend on data: the classes, `Ref`, `EvidenceRule`, `Expectation`, `JudgeItem`, `SemanticJudge`, `_Trial`, and the lineage, journal, completeness, rule and judge-item code. They were moved here unchanged so that the sealed verifier can reuse them without importing `critic.py`, which imports `q01_materials`. The only generalisation is that `_case_key` takes the case-id map, and the selector `("all_outputs",)` is accepted as well as `"all_outputs"`. `critic.py` re-exports every moved name and keeps `VERIFIER_VERSION = "q01-critic-verifier-1"`, because its behaviour is identical: all 130 pre-existing evals tests pass unchanged. Its file bytes did change; no hash pins that file.
- **Harness wiring** (`evals/deeptwin/harness/q01_harness.py`):
  - `PreDispatch(manifest_path, committed_sha256, harness=None)`, `pre_dispatch_errors(...)` and `run_release_trial(...)`. `run_release_trial` refuses to start without a `PreDispatch`.
  - `Q01Trial(..., pre_dispatch=...)` checks the manifest before any material read or dispatch. It also binds the trial to the manifest: the environment manifest it will read must hash to `sealed_dataset_sha256`, the case must be in `case_order`, and `max_proposed_chains` and the fixed `call_seconds`/`run_seconds` must match. If any check fails, the record is `invalid` / `pre_dispatch_manifest_unverified`, with no reads and no calls, and the verifier scores it as invalid.
  - The calibration path (`run_trial`) is unchanged: its records have no `pre_dispatch` key.
  - `q01_core.py` and `sealed_critic.py` were added to `CONTROL_PLANE_FILES`, and `sealed_critic.py` to the reader refusal probes.

## Tests

`evals/deeptwin/tests/test_sealed_critic_verifier.py` has 203 tests. They run on **synthetic development data written in the test by the test actor**, labelled as such in every basis and in the environment manifest. This data is not sealed, not independent and not reviewed. It is 13 cases over 7 candidates, with at least 2 per boundary class, a Q1/Q2/Q3 defect each, and a Q5 pair. Real harness trials are driven by a scripted critic. The tests cover:

- refusal of a sha256 mismatch before parsing, of schema violations, of each boundary-rule violation, of composition failures, and of duplicate JSON keys; the opt-out of composition;
- bundle refusal: wrong manifest sha256, unlisted file, altered file, missing file;
- binding refusal: an uncitable rule, a leaking bundle, mismatched cases;
- each of the 13 dev cases: `not_judged` without a judge and `pass` with a judge;
- a failing variant for each boundary class: false rejection; missed or unsourced defect; accepted or blamed rejection; fail versus handling; decided unresolved claim; decided insufficient evidence;
- an output-contract error as `fail`, including a response transition from a rejected counterexample;
- a judge answer of `undetermined` as `not_judged`, `not_supported` as `fail`, and a bad answer or exception as `invalid`;
- invalid trials attributed to their case and left unscored: a transport failure, tampering, forbidden access, a wrong record schema, a non-bundle input;
- a material mismatch and a basis leak detected from the sealed set, with the harness scan unaware of either;
- the full suite precedence table: all 128 combinations of fail, invalid, missing, not_judged, manifest mismatch, stopped and separation, checked against a transcription of the design text;
- `case_pass` semantics; a missing repetition; duplicated, unplanned, foreign and wrong-expectation results; mixed materials; fail taking precedence over incomplete;
- a manifest mismatch as incomplete;
- digest recomputation, including key order and non-ASCII text, and a digest mismatch;
- attempt against prior attempts; manifest schema errors; an uncommitted manifest;
- an end-to-end dev suite whose `build_suite_record` output validates against the schema, whose `record_sha256` recomputes independently, and which the product gate reads as `scoped_pass`, never qualified; manifests pinning other expectations or a bad digest give incomplete;
- harness refusal for each of seven manifest faults, with no read and no call, and dispatch with a manifest that verifies;
- AST and subprocess checks that `sealed_critic.py`, `q01_core.py` and `q01_release_manifest.py` import nothing from `q01_materials`, `critic.py`, `q01_cases` or the harness, and reference neither `EXPECTED` nor `Task.md`;
- verifier identity hashing.

Mutating the suite precedence (incomplete before fail) or turning off the leak check makes 62 of these tests fail.

Commands (no network, no provider, no live files):

```
env -u DEEPTWIN_LIVE_ANTHROPIC_API_KEY .venv/bin/python -m pytest -q -p no:cacheprovider evals/deeptwin/tests/test_sealed_critic_verifier.py
# 203 passed
env -u DEEPTWIN_LIVE_ANTHROPIC_API_KEY .venv/bin/python -m pytest -q -p no:cacheprovider evals/deeptwin/tests --ignore=evals/deeptwin/tests/test_q01_live_calibration.py
# 333 passed (130 pre-existing + 203 new)
```

## What remains (release-v3 still cannot execute)

- **No sealed set exists.** Release-v3 needs an independent named author and a separate reviewer, new materials outside the repository, and expectations sealed by sha256. None of these exist. The dev data in the test is the developer's own and can never count.
- **No independent judge.** `independence_profile.json` has `judge_separation.established: false`. `verify_suite` therefore defaults to `not_judged` for any would-be pass, and no successor profile exists.
- **V3 error independence is unverified.** Even a pass would be a `scoped_pass`, never a qualification.
- **Harness gaps for a real release run.** Still not implemented:
  - running cases in the manifest's `case_order` sequence at concurrency 1;
  - the USD hard stop and stop recording;
  - recording single use and spending the sealed set;
  - persisting the attempt ledger;
  - checking the successor profile's path and sha256, and the judge identity and prompt digest, before dispatch;
  - loading a sealed bundle from outside the repository. Today the bundle must be laid out as a task directory `environment/` next to the pinned `instruction.md`.

  The harness leak scan does not know the sealed answers; the verifier catches such leaks after the run.
- **The verifier's identity covers its three source files only.** The app modules it depends on (`app/critic_contract.py`, `app/critic_audit.py`, `app/services/design_criticism_live.py`) are covered by the harness code hashes, not by the verifier sha256.
- **Reporting is incomplete.** Per-item judge-versus-expectation disagreement listings, cluster counts, and spend and time per invalid trial are not produced. The suite result gives counts per class and invalid causes only.
- **No independent audit.** The verifier needs one before a pre-dispatch manifest fixes its version and sha256.
