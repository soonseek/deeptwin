# Evidence — the merged working tree brought back to green (2026-09-22)

- Context: between 2026-09-19 and 2026-09-21 a parallel orchestration (`root` with
  sub-agents, tasks 27–51 under `.superpowers/sdd/resumption-plan/`; see
  `resumption-2026-09-19/20/21.md`) worked in this worktree on top of this loop's uncommitted
  ToolDefinition-gate slice, deliberately committing nothing and verifying by module subsets
  (Task47 final35: 1,341 passed; Task49 final20: 615 passed). Its Task51 had not started
  editing product files. No other session was running when this loop resumed.
- The whole tree had never been run as one suite. The first full run: **9,104 passed,
  95 failed, 82 errors** (1h11m). Every failure was classified alone before any change.

## Frozen identities (the files this reconciliation changed)

```
5ef9ec9e603e60f7d3a029980e0c8906320f1f989e39d0a86935a37c2e82c5ec  app/tests/test_provider_send_gateway.py
2509747e6c8959a25e04fc21e50529cf3eb32c94d83df7c4fdffc19836bc6194  app/tests/test_provider_semantic_vertical.py
ea5d1362f513bba82792259e9a54b9361a1766c5575853e7b94417990e757686  app/extensions/provider_conformance_service.py
34a4a26680dc5471c80bf13aa779aecd9efdd3a27ef716dc21da621c68597f29  app/services/owner_material_upload_lock.py
78055327e5b553a79c8a8b9f6eab52c13c30e4a0e0da6cf99c286a70573caf69  app/tests/test_runs_api.py
6d4b91902cfaa58579c6a4ab9b0a7f113d4605f772121159274a735d39ca1ce6  app/tests/test_works_api.py
37abef812afa1456f118976ffbcd7d18cde79be5ef255371319b83e47cf49216  app/tests/test_extension_attempt_transport.py
d34c791f86f1f190b2cebc4621c42700fc17ebc2e74fca666cc30df7c0b8a594  app/tests/test_provider_stage_connection_lifecycle.py
df952f9ffa6214e8ea0c80235d97e554fa66cebb38c27fce8fc1a269db4e7827  app/tests/test_extension_installation_domain.py
5d4d97384311c45aba9384e31f07c84234355af3d1bb3a1c0ca0bbdc947a9ed3  app/tests/test_installation_release_contracts.py
```

## Findings and closures (each reproduced, then fixed at its cause)

1. **Time bombs (81).** `test_provider_send_gateway.py` (79) and `test_provider_semantic_vertical.py`
   (2) used a fixed absolute deadline `2026-09-20T23:59:59.999Z`; from 09-21 every prepare
   answered "provider send deadline elapsed" — deterministic alone. The parallel orchestration's
   own Task51 plan warned against relying on that date. → a `future_deadline()` helper (now +
   1 hour, the wire's exact format); no fixed date remains in either file.
2. **Core import boundary (2 tests, 3 violations).** `provider_conformance_service.py` loaded
   `uuid` through `__import__` (dynamic loading is a violation); `owner_material_upload_lock.py`
   in the services layer imported `starlette.concurrency.run_in_threadpool` (a presentation
   dependency). → a plain `uuid4` import; `asyncio.to_thread` in the service.
3. **Route composition pins (2).** The parallel orchestration added `provider-conformance-v1`
   and `provider-installation-v1` (37 routes) and updated two pins but not `test_runs_api` and
   `test_works_api` (still 28) → 37.
4. **Detached private fields (6).** Task49 made `ExtensionConnection.close()` detach its socket,
   codec and generation before closing; four transport tests and two lifecycle tests still read
   `connection._socket.fileno()` / `._codec.closed` after the close → the objects are captured
   before the close (the tracked wrapper keeps the socket it saw at construction) and their own
   closed state is asserted.
5. **Schema export branch (1).** The `extension_installation` envelope branch became a `oneOf`
   (the extension anchor beside `provider-installation-verified-v1`); the test indexed
   `then.properties` → it selects the anchor's variant and pins the two variant names.
6. **Order-dependent setup errors (82).** Every `create_app` in five provider installation/
   conformance suites failed with "route factory failed" after ~230 earlier files, never
   alone. A scratch pytest plugin recorded the exception hidden by the composer's `from None`:
   `InstallationError("unavailable")` from the installation service's constructor identity
   chain (`type(release_source) is InstallationReleaseSource`). Cause:
   `test_installation_release_contracts.py::test_new_service_api_are_not_source_dependencies`
   reloaded four `installation_release_*` modules in-process under an import guard; a reload
   mints new class objects, so every module that had imported the old class before it (the
   service, imported early by the catalog) failed the identity check for the rest of the
   session. Reproduced with an early importer + the reload test + an errored file (1 error);
   → the guarded import check runs in a fresh interpreter (subprocess); the same triple passes.
   Recorded, not changed: `test_provider_sources.py` and `test_provider_source_init.py` also
   reload modules (`deployment.mounts`, the source initializer) — no harm observed in the full
   runs, a latent risk of the same shape.
7. Passed alone, failed only in the first full run, passed in the second: the extension
   handshake requester-id test, the conformance final-wall test and the provider service
   budget test — timing-sensitive under a 71-minute load; recorded, not chased.

## Verification

- Full run 2 (after 1–5, before 6): **9,201 passed, 0 failed, 82 errors** (1h11m), the errors
  revealed as above. Full run 3 (after 6): **9,280 passed, 3 failed, 0 errors** (1h22m). The
  three — the installation service's clock-floor check (`_now`: `now >= clock_floor_ms`), an
  owned-connection prepublication deadline case and the provider service's whole-dialogue
  budget case — are `TransportUncertain`/deadline shapes under the 82-minute load; all three
  pass alone (re-verified after the run, 5 passed with the parametrized case). Recorded as
  order/timing-dependent, not chased in this iteration; the tree is otherwise one green suite.
- Ruff: no new findings on the changed lines (the parallel orchestration's files carry their
  own pre-existing findings — BLE001, UP017 and the like — untouched).

## Boundaries kept

- Only tests and two non-behavioural code lines (an import, a thread-pool call) changed; no
  product behaviour, contract, schema or route changed; the parallel orchestration's accepted
  bytes are otherwise untouched (its manifests remain valid for every file it froze that this
  reconciliation did not edit). No model, tool or paid call.
