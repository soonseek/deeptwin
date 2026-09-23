# Additive domain storage review

2026-09-07 · bounded, read-only code/security/correctness review of T007/T008.

Reviewed `app/domain/store.py`, `app/tests/test_domain_storage.py`, the unchanged legacy
`app/storage.py`, [implementation evidence](domain-storage.md), [data-model §1.1/2](../data-model.md)
and [ADR-008](../decisions.md#adr-008--acyclic-immutable-record-bootstrap).
The initial implementation identity recorded in the handoff was
`4492d22e0979b25a42188d8f32a81d821fa55899f62663915500bbd86d639d2e`.
Root subsequently edited implementation/tests concurrently to address reported findings.
Line numbers below identify the initially reviewed implementation, not a frozen final patch.

This is independent review work by the existing assigned agent. It is not a new model,
fresh-model validation, live-provider evaluation or production-vault qualification.
Only temporary fixture databases/files were created for diagnosis; no actual user database
was accessed. This review agent changed only this report, not implementation or test files.

## Reproduced findings

All four findings were sent to root immediately after reproduction. Fix confirmation is
recorded separately below; a root-authored fix is not considered verified merely because
the original test suite was green.

| Finding | Initial location | Reproduction and consequence | Required correction |
| --- | --- | --- | --- |
| R1 — New record excluded from verification budget | `app/domain/store.py:473–477` | A fresh vault has four roots. Under `MAX_GRAPH_NODES=4`, an ordinary record's first `put` succeeds, but immediate `get` and repeated `put` raise `VerificationLimit`. Only pre-existing dependencies were counted before committing the new record. This can also occur at the real configured boundary. | Validate the completed graph including the new record before committing, with the same limits used for reads; preserve rollback on refusal. Do not raise the cap to hide the off-by-one behavior. |
| R2 — FIFO blocks before nonregular-file rejection | `app/domain/store.py:495–506` | Place a mode-0600 FIFO at a computed CAS digest in an owned temporary fixture directory. `put_blob` blocks at `os.open(O_RDONLY)` and only raises `UnsafePath` after a separate FIFO writer connects. During that wait the process-wide writer lock is held. | Open without waiting on a FIFO, e.g. `O_NONBLOCK`, then reject nonregular descriptors before reading. Retain no-follow, mode, size and hash checks. |
| R3 — Residual domain tables mistaken for an empty vault | `app/domain/store.py:327–333,370–373` | Create a vault/blob, then simulate partial corruption in the temporary database by deleting edges/records/vault with foreign-key checking off while retaining `domain_blobs`. `roots()` says `UninitializedVault`, and `initialize_vault()` installs a different genesis. `PRAGMA foreign_key_check` then reports a dangling `domain_blobs` vault reference. | An absent registry with any existing domain data must be corrupt/nonempty, including blob and relationship tables. Reject initialization instead of minting fresh roots over residual state. |
| R4 — Reader ceiling misreported as corrupt bytes | `app/domain/store.py:507–508` | Store `b'1234'` with `max_blob_bytes=4`; reopen the same legacy Store with a ceiling of 3. The new reader reports `CorruptBlob`, although the original reader returns unchanged valid bytes. | Distinguish an implementation verification ceiling from actual file-size/hash corruption, consistent with `VerificationLimit` for graph bounds. Do not turn a resource limit into a corrupt-data conclusion. |

R1/R4 require normal API inputs. R2/R3 require malformed or partially damaged fixture state;
they demonstrate failures in the claimed rejection/recovery behavior, not an external
attacker's ability to modify the protected directory. No CRITICAL/HIGH authorization bypass
was demonstrated within the documented internal-repository threat boundary.

The diagnostics used `<workspace>/.venv/bin/python`,
`TemporaryDirectory(prefix='deeptwin-storage-review-')`, and `Path(...).resolve()`.
The FIFO diagnostic connected a temporary writer to release its blocked reader and joined
the thread before fixture cleanup; it did not leave a blocked background worker.

## Supported behavior and legitimate deferrals

The implementation has a coherent separation between immutable record hashes and exact
blob-byte hashes. The normal API rejects bootstrap schemas; initialization uses locally
generated IDs and one SQLite transaction for registry, four roots and indexed links.
Exact same-version hash conflicts are rejected, and canonical bodies are rechecked against
both reference envelopes and stored edge/blob indexes.

The CAS path performs bounded writes and staged verification, then rename and directory
fsync before database registration. Exceptions propagate and the SQLite transaction rolls
back; complete orphan/staging files remain for explicit reconciliation. The tests exercise
pre-commit SQL failures, filesystem failures, directory-sync ordering, real bytes and legacy
row preservation. These support the bounded local implementation; simulated failures are
not evidence of hardware power-loss behavior or every possible crash point.

Database/vault ownership and modes, sidecar links, no-follow directory traversal, and exact
file checks improve the internal boundary. They do not make pathname-based SQLite opening
safe against a hostile same-user process; the implementation evidence correctly states that
limit. The original legacy Store constructor is unchanged and is not retroactively hardened.

Permission and integrity remain separate. `get`, `read_blob` and initialization are internal
methods, not authenticated user/model APIs. Blob purpose matching checks the requested
partition; it does not prove the actor may access that purpose. Transitive verification may
read linked bytes privately inside the repository. T009/T010 and the session/command layer
must therefore authorize the full required scope before invoking this interface. No public
route, human-approval bypass or dispatch-enable behavior was introduced by this slice.

At the time of this first review, legitimate unfinished work included legacy BLOB-to-CAS
migration/read switching, so T008 remained partial. The later closure section below reviews
that implementation. Multi-record command/event/budget transactions, explicit import/restore
policy, later migrations, and native filesystem/power-loss qualification remain separately
owned work. Graph node/depth, per-object and aggregate-byte bounds are implementation refusal
ceilings, not an end-to-end deadline or unlimited-history claim.

## Verification observations and closure

During concurrent root test-first edits, this reviewer ran:

```sh
<workspace>/.venv/bin/python -m pytest -q app/tests/test_domain_storage.py
```

That point-in-time run observed **50 passed, 2 failed**; the two failures were the newly added
FIFO rejection tests, agreeing with independent R2 reproduction. This was not a stable final
snapshot. The earlier 48-focused/1,555-app-test results are implementation-agent reports in
[domain-storage.md](domain-storage.md), not this reviewer's independently observed full run.

Closure status when the independent reviewer stopped: **R1–R4 reported; root
fixes/revalidation pending**. The agent then reached its account usage limit before the
requested closure rerun, so no independent post-fix pass is claimed.

## Root post-review disposition

Root retained each reproduced regression and made these bounded corrections:

- Insert then traverse the complete new record graph inside the same transaction, so a
  `VerificationLimit` rolls back the body and indexes before success is returned.
- Add `O_NONBLOCK` to the no-follow CAS read open, then reject nonregular descriptors using
  `fstat`; regular-file behavior and exact size/hash validation remain.
- Treat rows in any of the four domain data/relationship tables without a vault registry as
  corruption, and refuse fresh bootstrap over those rows.
- Separate actual stored-size mismatch (`CorruptBlob`) from a smaller current backend ceiling
  (`VerificationLimit`).

Observed in the exact fresh dependency environment after these changes: **57/57 storage
tests passed in 2.22s**, followed by **1,598/1,598 app tests in 12.59s** with the one existing
Starlette/AnyIO deprecation warning. This closes the four reproduced implementation defects;
it does not close the legitimate deferrals above or substitute for an unavailable independent
post-fix run.

## T008 legacy-CAS closure review

The T008 implementation adds ledger version 2, an indexed stable-ID mapping from legacy file
rows to registered CAS objects, bounded per-file/page migration, and a legacy read switch that
never uses the retained BLOB after a mapping is present. Failure-first tests cover exact v1→v2
upgrade, rollback, legacy ID/revision/event/byte preservation, seal and mapping-commit failures,
idempotent resume, mapping/metadata/timestamp tamper and no CAS-corruption fallback.

Implementation self-review first exposed and corrected wrong-work mapping acceptance, missing
aggregate byte ceilings, incomplete applied-schema checks, a residual v2 mapping being mistaken
for an empty vault, and verification-limit exception relabelling. A separate final read-only
review then reproduced these additional closure defects against temporary fixtures:

| Finding | Reproduction | Disposition |
|---|---|---|
| C1 — schema-object name bypass | Uppercase or arbitrary-named triggers/indexes attached to a governed table survived a lowercase `domain_*` name query. | Schema discovery now case-folds reserved names and includes all explicit triggers/indexes attached to governed domain tables. Four name/attachment regressions pass. |
| C2 — directory identity swap during SQLite open | A one-shot same-UID rename swapped vault directories inside `sqlite3.connect`; the old fd-only post-check accepted the replacement vault. | The visible path is re-resolved and compared with held directory/database identities immediately after connect and again before `BEGIN`. The exact swap regression is rejected. Repeated hostile same-UID races are still not represented as sandbox-proof. |
| C3 — non-BLOB integer materialization | SQLite INTEGER `1000000` in the declared BLOB column reached `bytes(1000000)`, allocating zeros before mismatch detection. | Both unmigrated read and migration require SQLite storage class `blob`, enforce length ceilings before selecting bytes, and then verify metadata length/hash. Spy regressions prove `bytes(integer)` is not reached. |
| C4 — purpose reclassification | Registering equal bytes in `diagnosis` allowed a mapping's purpose to be changed from its implemented `operational` source. | Migration-2 DDL now has `CHECK(purpose='operational')`; domain-link and legacy-read validation independently reject bypassed constraint tamper. |

The implemented repository transaction is complete for the T008 switch itself: CAS is sealed
and registered before one mapping commit, while any failure before that commit leaves legacy
read authority unchanged. The broader authenticated command transaction spanning permission,
domain records, budget reservation, dispatch intent/result and events is explicitly T014/T016.
It is not silently claimed here and does not make the narrower T008 storage migration partial.

The final read-only re-audit of the corrected snapshot observed **84/84 focused tests passed
in 6.62s** and **9/9 targeted closure regressions passed** (schema bypasses, both persistent
directory-swap windows, non-BLOB materialization, and purpose tamper). It found no remaining
T008 closure blocker. Repeatedly timed hostile same-UID swaps remain part of the explicitly
documented native-isolation limit rather than a claim made by this repository.
