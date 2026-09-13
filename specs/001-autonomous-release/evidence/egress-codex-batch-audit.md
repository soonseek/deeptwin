# Evidence — iter-55 adversarial audit: egress/lifecycle/lineage batch

- Date: 2026-09-13
- Scope: independent adversarial audit of the recent batch —
  app/runtime/egress.py (T043 broker), app/codex_rpc.py +
  app/codex_understanding.py (T031 lifecycle), app/critic_audit.py
  lineage (T032), app/tests/test_critic_lens_pipeline.py (T036).
  Auditor ran its own repro scripts; every REJECT below was closed
  RED-first (the finding's repro became a failing regression test in
  app/tests/test_egress_codex_audit_findings.py, 22 tests).

## Frozen identities

```
dfa89ebc4462eecfd01b898b118dc3b7c7fda096856f472b04e343d0fbb0beee  app/runtime/egress.py
b23c6c008e7e9fe98d00a40dcad819855486b76106eb908058c35ae3dec07eb1  app/codex_rpc.py
11f02ef7abefa93d8affa65da044e595086d99e57982b02c3fc7657967884f29  app/codex_understanding.py
ab88fbb6aa5df53678cd3e1cbe23b98126fe52c2c4606ae83883723c6495f7ca  app/critic_audit.py
a8b1a2edcb140925c330ed0c4863e2fb675cd4ccfc583835559782c3546653d2  app/critic_trial.py
b3e270d9af13d5dbb69577827172f82d3c0023e80433ee9ccf01eeb19de6c82c  app/tests/test_egress_codex_audit_findings.py
```

## Findings and dispositions

- **F1 HIGH REJECT → fixed** — urlsplit strips `\t\r\n`/leading space,
  so a policy-clean parse handed the transport a raw URL carrying
  request-line/Host injection (`.../a\r\nHost: evil...` was ACCEPTED;
  port `4\t43` admitted). Fix: `_admit_url` refuses every character
  ≤ 0x20 and DEL outright — a legal URL percent-encodes them.
- **F2 HIGH REJECT → fixed** — header names were blocklist-matched
  verbatim, letting `"Authorization "`/`"AUTHORIZATION\t"` and CRLF in
  values smuggle credential headers. Fix: names must be RFC 7230
  tokens; values refuse control characters; blocklist matches after
  that.
- **F3 MEDIUM REJECT → fixed** — redirect-hop bodies were discarded
  unchecked (a 10MB 302 body was accepted). Fix: every hop's body is
  bounded before redirect handling; the post-materialization nature of
  the check is now documented (streaming enforcement belongs to the
  transport).
- **F4 LOW → fixed** — `Location` lookup was case-sensitive
  (fail-closed interop bug); now case-insensitive.
- **F5 LOW → fixed** — transport status was vouched for unvalidated;
  now must be an int in 100..599.
- **F7 MEDIUM REJECT → fixed** — a second `close()` (the NORMAL error
  flow: start-failure closes, then generate's finally closes again)
  overwrote `termination_confirmed` False→True. Fix: a redundant close
  never upgrades a recorded verdict.
- **F8 LOW → fixed** — no deadline gate stood between `thread/start`
  and `turn/start`; a slow thread-start let the prompt transfer past
  the lifecycle deadline. Fix: deadline check right before
  `turn/start` (cancel semantics there unchanged).
- **F10 MEDIUM REJECT → fixed** — plain `Ledger.reserve()` admitted
  lineage-requiring purposes parentless, and the production runner
  (critic_trial) used it for every call — the whole B4 chain was
  opt-in. Fix: `reserve()` refuses purposes in `_PARENT_PURPOSES`;
  `OfflineRunner.run(..., lineage=(parent_request_id, evidence_sha))`
  routes chained purposes through `reserve_with_lineage` and refuses a
  lineage argument on unchained ones; the trial roundtrip tests seed
  the real completed parent chain (`seeded_lineage`).
- **F6/F9/F11 ACCEPT-WITH-NOTE (documented, unchanged)** — NAT64
  `64:ff9b::/96` passes `is_global` (consistent with the single
  authoritative check; NAT64 hosts are outside the deployment model);
  cancel with an already-expired deadline surfaces as `timeout` with a
  best-effort interrupt; evidence registration is caller-honesty by
  documented design ("hashes detect accidental corruption, not
  adversarial storage modification").
- **CLEAN** — issued-value forgery, IP checks (IPv4-mapped, zone-id,
  int/object resolver returns), redirect revalidation/downgrade/hop
  bounds, `_CancelledBeforeTransfer` ordering, restart-gate placement,
  all lineage forgeries (cross-call/case/cross-db/version/dup), and the
  lens-pipeline isolation assertions (backed by `extra="forbid"`
  contracts — smuggled keys are stripped).

## Verification

- RED: 22/22 findings tests failed against the pre-fix code; GREEN
  after the fixes with no test weakened.
- Affected suites: 306 passed (trial/audit/lineage/egress/lifecycle/
  findings). New lint findings: none (the 12 remaining are verified
  HEAD pre-existing). Full regression **3397 passed, 2 skipped**
  (was 3375).
