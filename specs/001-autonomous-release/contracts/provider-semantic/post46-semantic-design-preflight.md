# Post46 semantic vertical — independent design preflight

2026-09-20. **NOT READY for executable promotion: three Important (P2) design findings.**
The finite offline semantic direction is sound. These findings concern usable query identity,
deadline propagation into real custody, and the exact credential binding join; they do not require
real C/native/release authority before conditional offline behavior can be implemented and tested.

## Review basis and boundaries

Read the complete requesting-code-review skill and code-reviewer template, both complete drafts,
the complete255-line source reference and readiness map. This is a draft review, not a HEAD diff.
Read-only `git rev-parse HEAD` confirmed `a2f85d578c47a0e59c1850ac1840cf8baceb0d96`.

| Reviewed artifact | Lines / SHA-256 |
| --- | --- |
| `post46-semantic-vertical-contract-draft.md` |234 / `3e5006d06f8aabab0478f0cbd0c4cffc263bc71ab782fab884ac013c2c940594`|
| `post46-semantic-wire-record-appendix-draft.md` |227 / `4276df4cb52704ff97c752ead14d1097151ffbe7aa0d226e64e3c962678e2a8d`|
| `post46-claude-api-source-reference.md` |255 / `62764974a8f702d386fb36848a105181c9f2f50bc1831d465d1ecd9a3a260f4b`|
| `post46-provider-readiness-map.md` |`4de7248a3f0eae1410ab45596a7c1b1b9ed2e5c5fa470c700be9c4cf0c06fdd5`|

Read Task46's brief, the installation master and ownership listing before product inspection.
Task46-owned domain schema/export interfaces were inspected only through
`installation-before/app/domain/schema_exports.py` and its stable envelope rules, not their
changing product versions. Relevant stable canonical ports/runtime, domain refs/schemas/store,
port validator, frozen turn, dispatcher/ledger/budget, artifact stream/CAS, gateway/vault/files/
journal and connection interfaces were inspected. No moving Task46 implementation was used.

Only this report was written. No product/canonical edits, helper, tests, imports executing product
code, dependency operation, network/native/root operation, keys, commit or push occurred. Official
API facts were checked against the supplied source reference; no fresh upstream observation is claimed.

## Strengths and confirmed compatibility

- The worker remains network/credential-free; separate authenticated core→worker and core→gateway
  dialogues, independently reconstructed proposal bytes, core-only output refs and sealed terminal
  records supply a behavior-bearing path. The existing unqualified resolver remains denied while
  the new path must traverse real encrypted custody, not a fake resolver (draft:124–140, 169–173).
- All five operation branches preserve canonical result/effect/artifact rules, including twelve
  allowed operation×terminal pairs and quarantined non-success output. Direct ordered Artifact
  refs agree with `port_schema_generator.py:2140–2156` and ports§§3.8–3.9.
- Successful text with provisional currency is compatible with the actual consumer:
  `node_attempts.py:187–213, 423–463`, `ledger.py:2514–2545, 2694–2701` and
  `budgets.py:1146–1178` admit succeeded with `usage_finality=provisional, usage=None` and retain
  the reservation. No new settlement branch or fabricated zero is needed.
- The new record ordering is acyclic as specified; catalog/compatibility-set parent projections
  do not hide graph edges because `domain/store.py:247–278` recursively indexes exact refs in
  content. Existing graph verification rehashes descendants/blobs and enforces caps
  (`store.py:627–651`). Retaining cap-based refusal rather than claiming every256-row input fits
  is correct. Task46's frozen export has the compatible256-parent bound
  (`installation-before/app/domain/schema_exports.py:83–91`).
- Availability versus capability/compatibility, dated text policy, nullable usage and complete
  pagination are separated. The selected narrow text codec can have genuine controlled-upstream
  positive paths without declaring unknown models eligible. Synthetic authority ownership and
  absent production registration are explicit; mandatory Codex subscription remains later work.

## Important findings

### F1 — A successful status observation permanently consumes its only semantic key (P2)

**Evidence:** appendix:65–69 assigns one immutable operation/request identity to each semantic key
for every operation and rejects a different request ID using that key. Yet appendix:171–175 and
draft:64–65, 205–206 require observing a live operation's changing state. Canonical
`extension-ports.md:141` hashes operation/purpose/grants/input but excludes request ID, deadline
and observation time; `port_schema_generator.py:1884–1899` implements that exact hash.
`extension-ports.md:283–290` also literally makes every request idempotent by this key.

**Concrete failure:** obtain a successful `status` whose output is `running`. After the original
model operation completes, another status with the same target, purpose, grants and binding has
the same key. Byte-identical retry returns the old running observation forever; a fresh request ID
conflicts. No field in the closed status input can express a fresh observation. The same issue
prevents a fresh post-restart status after an earlier successful live status. A single status call
in the current positive test would miss this defect.

**Distinction:** the draft's global uniqueness/index rule makes the failure concrete, but the
canonical all-operation idempotency wording is itself a query-usability gap. It is not valid to
fix this silently by ignoring the existing key or changing the canonical hash in implementation.

**Bounded fix:** obtain and record a narrowly scoped canonical amendment for fresh read
observations: a fresh request identity may take a fresh immutable observation, while the exact
same request ID and bytes replay its prior result and changed bytes under that ID conflict.
Explicitly enumerate the affected read operations and their admission/currentness rules.
Keep model/external-effect semantic-key deduplication, unknown-outcome no-resend and exact old
result identity unchanged. Then scope the command index accordingly. Do not manufacture a new
purpose/binding/grant just to vary the status key. Required future proof: running→terminal and
running→restart-unknown under fresh query IDs, old-query exact replay, and unchanged duplicate
model-step zero-send behavior.

### F2 — The promised single deadline does not reach the reused custody locks/journal (P2)

**Evidence:** draft:116, 135, 144 and appendix:189, 196–200 require one remaining deadline,
cancellable cleanup and reuse of existing vault exclusion. Actual `credential_vault.py:44–60`
waits up to5s for its RLock, then calls `credential_files.py:170–186`, which starts a separate5s
flock budget (`BUSY_SECONDS=5.0`, line11). `credential_journal.py:42–74` separately opens SQLite
with `timeout=5`/`busy_timeout=5000`, runs integrity/FK checks and validates the whole bounded
metadata set; its validation loops begin at87. None receives the exchange deadline/cancel latch.
The proposed owned-file table includes vault but neither credential_files nor credential_journal
(draft:188–193).

**Concrete failure:** a committed exchange with100ms remaining enters delivery while a legacy
custody operation holds the lifetime/mutation lock. It can remain in a5s wait before reaching the
draft's pre-write cancellation check; the separate waits can also stack. Moving this work to an
uncancellable helper thread still leaves the same-deadline join/cleanup promise unsatisfied.
This is an existing offline interface mismatch, not merely an unmeasured production DNS issue.

**Bounded fix:** define an optional shared absolute deadline/cancel-aware custody seam for this
new delivery path, including lifetime acquisition, flock acquisition, SQLite busy/progress handling
and bounded metadata-validation checkpoints. Keep every existing identity/integrity/FK/metadata
check; interrupted validation refuses delivery, never skips validation. Preserve historical default
behavior for old operations and the established lock order. Add the two narrow support files to
prospective ownership if this is the chosen implementation, or specify an equally concrete
in-scope implementation that bounds all these waits. Required future proof: contention at each
lock/SQLite boundary and cancellation during validation with a short remaining window, zero
upstream writes and no surviving thread/lease/lock. Normal encrypted positive delivery must still pass.

### F3 — No literal join connects the bound opaque handle to the selected custody record (P2)

**Evidence:** appendix:34–35 freezes a connection snapshot containing CM/CR and a config snapshot
containing the canonical config; prepare:162 and lease:194 carry CM/CR but no selected opaque
handle reference or explicit handle→connection→CM/CR rule. Draft:126–135 promises current
config/binding/credential joins without defining this particular equality. The existing config
validator only checks equality between the binding and config `credential_handle_refs`
(`port_schema_generator.py:1630–1633`); it does not join those refs to a connection/custody record.
Canonical `runtime.md:287–305` requires handle/provider/scope checks and opaque-handle dispatch.
The stable vault's `metadata(handle)` selects a latest stored version by record ID
(`credential_vault.py:317–323`), while `resolve_for_gateway` unconditionally denies (334–335);
neither supplies the missing canonical immutable-reference mapping. The legacy connection module
imports its different Keychain `CredentialRef` (`services/provider_connections.py:28–32`).

**Concrete gap:** a config/binding can agree on handleA while a separate well-formed connection
snapshot supplies valid stored CM/CR for credentialB. Correct custody hashing/decryption, matching
prepare/lease bytes and provider spelling still do not establish that bindingA authorized B.
The present prose does not define a deterministic check that rejects this swapped-valid-record case.
This is a missing contract edge in the conditional consumer, not a claim that production is active.

**Bounded fix:** choose one exact immutable opaque-handle projection/reference in the existing
record vocabulary and define its unique relationship to the connection revision, account/provider,
exact CM fingerprint and CR version/hash. Require the selected handle to be the authorized member
of config and binding handle refs; pin that same mapping into prepare/lease issuance and verify it
through delivery. A connection snapshot can serve this role only if the contract explicitly gives
it that mapping and equality rule. Do not add a second registry or implement a real authority issuer.
Future offline tests should store two real encrypted credentials, use synthetic scoped bindings,
then swap valid handles/connection revisions/CM/CR separately and require zero sends; the exact
selected handle must positively decrypt/send once. Keep real current-connection/binding issuance
as the later activation gate already declared by the draft.

## Declined to judge

- Actual native C, qualification/binding heads and permission/current-connection issuance: intentionally
  absent production authorities; synthetic sealed records may prove the same conditional consumer.
- Authentic compatibility, text-policy/reservation review, real pricing or currency settlement:
  separately authorized producers; this review only confirms honest provisional accounting.
- New worker/gateway release admission beyond Task46 cap1, scans, rights, signatures, native layout
  and clean-host fit: later real release/platform work, not required for offline behavioral proofs.
- Real DNS/TLS/socket interruption and supported-platform30s/4-input/4-output fit: measurements remain
  later gates; F2 instead identifies already-known software waits that must be bounded offline.
- Actual browser activation and the complete graph/lens/artifact journey: no production registration
  is proposed here. This finite consumer does not claim T018/T087/T090 or whole-product completion.
- Managed Codex subscription and optional Codex API execution: distinct mandatory later work,
  explicitly preserved; no Claude substitute or automatic billing/model fallback was assessed.
- Task46's changing implementation, acceptance, final generated exports and overlapping ownership:
  owned by its sole writer; reconcile accepted final bytes before dispatch.
- Test results and implementation correctness: no implementation or tests were authorized for this
  review. Listed vectors are required future evidence, not claimed passes.

## Assessment

**Ready for executable promotion: No, with the three finite fixes above.** F1 needs an explicit
canonical query-semantics ruling/amendment; F2 and F3 need literal consumer/interface closure and
their narrow ownership/proof updates. No Critical or additional Minor findings are raised.
After those changes receive bounded re-review and accepted46 scope reconciliation completes,
the selected offline implementation can proceed without first inventing C/native/release authority.
Production activation remains closed for the separately enumerated genuine gates.

---

## R1 — bounded correction re-review, 2026-09-20

**Design assessment: READY for the controller's exact scoped promotion decision. F1, F2 and F3
are addressed; no remaining or new Critical/Important/Minor finding in this correction scope.**
This does not itself promote canonical text, accept Task46, authorize implementation, or establish
production activation. The original172-line report above is preserved verbatim as historical review.

| R1 artifact | Lines / SHA-256 |
| --- | --- |
| `post46-semantic-vertical-contract-draft.md` |247 / `7177e9cd27e1813f6b42344437e73593ef0ba1537714acfbefe6fd76bd02c513`|
| `post46-semantic-wire-record-appendix-draft.md` |245 / `dcf68d94934aac3e0dc1078a9620f4cdb7c6c12c70682f32681c8ca19b410fd4`|
| `post46-read-observation-amendment-draft.md` |82 / `3599b84bbb08e5fdf93675f67dffb657d9cfcb48d2153c8904d231d5d97c4ebe`|

Read the entire82-line amendment and the changed record/replay/handle/wire/lease/budget,
ownership/proof and status sections of the two revised drafts. Rechecked the relevant unchanged
port-validator, DomainStore transaction/reference and custody Journal interfaces. This is bounded
re-review of F1–F3 and their introduced behavior, not a restart of the original design review.

### F1 disposition — addressed through an explicit scoped canonical amendment

The amendment:11–24 distinguishes the existing canonical rule from the proposed exception,
enumerates only this exact profile's capabilities/catalog/status, and pins both request bytes and
config_ref for UUID replay/conflict. Fresh read UUIDs can observe new state under fresh admission;
old UUIDs preserve exact observations and cannot dispatch again. The unchanged key still matches
`port_schema_generator.py:1885–1897`; model_step retains its unique semantic-key fence
(amendment:47–60; appendix:69–75). Profile selection comes from trusted composition, not an input
flag or arbitrary manifest claim. This closes the original status-freeze gap without covertly
changing established hash/schema bytes or generalizing other ports.

Cancel is separately constrained by an exact-target durable intent and owner mutex
(amendment:28–45). Terminal-first observation, one-way latch, at-most-one gateway control,
unchanged first reason, exact acknowledgement replay and intent-before-latch crash uncertainty
are specified. Intent refs point to the earlier target and first cancel operation; the latter only
points back to the target, so insertion remains acyclic and fits the real existing writer/unique
identity behavior (`domain/store.py:677–700`). A later fresh cancel can observe already_terminal
without creating another model effect. Required vectors cover state progression, restart, changed
same-ID config/body, target races and no second send (amendment:66–72; main:206,225).

The canonical promotion requirement is retained as an explicit controller action, not treated as
a new defect merely because the proposed amendment is still labelled DRAFT.

### F2 disposition — addressed by a shared budget through the actual custody stack

Appendix:213–219 supplies the formerly absent concrete seam: one immutable absolute deadline and
Event; sliced RLock/flock waits; timeout=0/busy_timeout=0 for the new Journal path; SQLite progress
interruption; bounded fixed-statement checked reads; per-row parsing/fingerprint checkpoints; and
checkpoints around root/file/crypto work and immediately before byte exposure/write. Busy refuses
instead of renewing a timeout or retrying a model send. Full schema/integrity/FK/binding/capacity/
metadata checks remain required, including unrelated sibling records. The8192-row read ceiling
matches the existing largest nonce set while preserving stricter cumulative/table limits
(`credential_journal.py:87–141`). Interrupted checks provide no partial authority.

The correction explicitly preserves budget=None historical defaults and forbids recover=True
on the new read-only delivery path. Main:194 and appendix:233 include both required support-file
edits. No journal/receipt schema changes or detached custody thread are prescribed; all owned
threads must unwind/join, and a cleanup overrun fails the controlled proof. Non-preemptible local
syscalls/crypto remain a candid platform-fit limitation, not an excuse to accept unbounded
software waits. Main:217 and appendix:241 now require real lock/SQLite contention, scan cancellation,
malformed-sibling refusal, legacy behavior and resource-release regressions. This closes F2 at
design level; actual timing and cleanup still require implementation evidence.

### F3 disposition — addressed by the sole immutable connection-snapshot handle

Appendix:34,53–55 makes the exact connection snapshot R the sole selected opaque handle and requires
both config and resolved binding handle arrays to equal `[connection_ref]`. Core rehashes the
record, checks current locator/account/provider/revision, fingerprints exact CM and joins CR
ID/version/hash. These checks add the missing edge beyond the existing binding/config-array
comparison (`port_schema_generator.py:1630–1633`) without inventing a credential-handle EntityRef
kind or a separate registry.

Authenticated prepare now carries selected_handle_ref/CP/CM/CR (appendix:168); the lease freezes
the same projection (201), and delivery checks exact CM/receipt/nonretirement/ciphertext (205–207).
Core owns same-store handle/binding resolution; gateway does not claim its partial CP projection
independently proves a DomainStore record or current binding. It preserves the authenticated core's
exact mapping through one-shot issuance and custody consumption, with no latest-version lookup.
Changing connection or credential requires a new matching handle/config/binding. Required real
two-ciphertext tests include coherent B under bindingA and individual prepare/lease/record swaps,
plus exact A positive delivery (main:207,216; appendix:241). This closes the conditional consumer
gap while leaving the genuine current-connection/binding issuer outside this tranche.

### R1 declined-to-judge gates and final assessment

All original declined activation gates remain: genuine C/native/permissions/current-connection,
text-scope/reservation/compatibility/accounting producers, authentic release admission/rights/
scan/keys/fit, real transport measurements, browser production integration and mandatory managed
Codex work. No new production authority follows from this re-review. Task46's moving implementation
and final overlapping exports remain uninspected; accepted46 scope reconciliation is still required.

No tests were run and no implementation correctness, timing pass or upstream compatibility is
claimed. Only this report was appended; no product/canonical/network/native/helper/commit action
occurred. No new breakage attributable to F1–F3 was found in the bounded design re-review.

**Ready for scoped design promotion: Yes.** Controller must explicitly adopt the exact read/cancel
amendment and reconcile accepted46 ownership before dispatch. Those remaining procedural gates do
not reopen the three now-addressed design findings or require real activation producers first.
