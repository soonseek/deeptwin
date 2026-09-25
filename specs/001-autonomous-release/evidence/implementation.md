# Implementation state (T075) — 2026-09-25

The requirement → task → test → evidence matrix is generated from the tracked files by
`specs/001-autonomous-release/tools/implementation_matrix.py` into
[implementation-matrix.md](implementation-matrix.md). Regenerate it after any change to
spec.md, tasks.md, tests or evidence. At this snapshot there are 44 requirements (FR-001–034,
SC-001–010) and 90 tasks: **52 done, 38 open**. 13 requirements have every citing task checked.
That is a bookkeeping state, not a field claim. 31 requirements have open tasks, and none is
uncited.

## Failed, invalid or missing evidence (never counted as passes)

| Area | State | Record |
| --- | --- | --- |
| Q01 critic calibration (T035) | executed live. The tuned result was **6/10, suite fail**, so nothing qualifies. Critic and judge share a model, so independence is not established. | q01-live-calibration-t035-2026-09-24.md |
| Release qualification (T076/T077) | the release-v1 and v2 designs are frozen, but **not executable**: there is no sealed set by an independent author, no independent judge, and V3 is unverified. | release-designs-t076-2026-09-25.md |
| Design approval (T036) | refused unless the critic is qualified. No release suite has passed, so no design is approvable in production. The design arc production path (T030/T038/T048) is blocked by this. | tasks.md T036 notes |
| Lens effect (FR-004/SC-005) | not measured. `user_construct` arm is `not_runnable_data_needed`. | lens-effects-v2.json |
| Growth E2E (T067) | G-06–G-13 and rollback pass with test-actor data. **G-14 and G-15 were not exercised.** | us6.md |
| Performance (T080) | command/event/log p95 measured on a single host. **STT was not measured**, because there is no real microphone. | performance.md |
| Container services (T018, T026, T043 worker, T070, T081, T083) | **blocked here**: the Docker daemon cannot be started in this environment. There are no images, no two-host tests and no isolation qualification. | tasks.md |
| Codex subscription runner (T088), Codex bridge in T042 | **no subscription available**. Not executed. | tasks.md |
| Live speech (T024) | there is no real microphone input, and none is simulated as real. | tasks.md |
| Signing/SBOM/provenance (T082) | depends on T081 images. Not produced. | tasks.md |
| License (T084) | Apache-2.0 has been approved and added. REUSE 3.3 is compliant for 1671 files. Still open: per-image notices, inbound-contribution policy (an owner decision), rights to text quoted in `docs/lenses/`, and the Compose gaps. | license-approval-apache-2.0-2026-09-24.md |

## Progress numerator, uncertainty and ETA (FR-034, SC-002)

The numerator used in status reports is the count of checked tasks in tasks.md. Each task
has equal weight, and the count is stable because it only moves when a task's checkbox is
changed with evidence. Partial slices never move it. The uncertainty is large and one-sided:
at least 20 of the 38 open tasks depend on container execution, qualification by independent
people, a Codex subscription or real hardware, and none of these exist in this environment.
There is therefore **no supported ETA** for those tasks. An ETA can only be given for work
whose blockers are inside this environment.

## Source hashes and supersession

The frozen release designs are pinned by `evals/deeptwin/qualification/release-v2/FROZEN.json`.
That manifest also pins v1, which is superseded by v2 but kept. Other pinned inputs (lens
bundle, calibration plan, independence profiles) keep their own manifests and guard tests.

## Full offline regression (2026-09-25, commit dbe3185)

The full offline Python regression passed on its first run, in two serial shards on Linux x86_64, run as root with the locked age runtime:

- Scope: every tracked `app/tests/test_*.py`, `evals/deeptwin/tests/test_*.py` and `deploy/tests/test_*.py` file, excluding live files (`_live_`, `live_calibration`).
- Result: **10,448 passed, 0 failed, 4 skipped**, plus 369 subtests passed.
- Wall time: about 45 and 57 minutes for the two shards.

An earlier regression run did not pass on its first attempt, for two reasons:

- 4-way sharding on 4 CPUs failed timing-sensitive provider tests under load.
- Running a snapshot under a root-only scratch directory blocked the tests that run children under other UIDs.

Neither affects this run. Browser (`*.test.mjs`) suites are run per change, as recorded in each task's evidence; they are not part of this Python regression.
