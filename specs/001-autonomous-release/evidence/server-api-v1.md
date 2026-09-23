# T016 authenticated server API v1 — offline implementation evidence

Verified 2026-09-08 in the authoritative worktree
`<repo>`. This is the completed server-delivery
slice of T016, not a claim that the whole feature or a release is complete. No provider,
tool, login, Keychain, external network, paid API, or user vault was accessed.

## Implemented boundary

`create_app` now installs or reopens one additive `DomainStore` root set in the existing
`intake.sqlite3`, then binds persistent permission, budget, runtime ledger, command journal and
public event journal components to that same vault. Existing work/file IDs and legacy routes are
unchanged. Reopening is idempotent. macOS's fixed OS-owned `/var -> /private/var` temporary-path
alias is normalized before the hardened domain path check. Before `Store` can create a directory,
database or legacy startup event, the server walks every existing ancestor with directory file
descriptors and `O_NOFOLLOW`; arbitrary caller-owned symlinks are rejected without creating the
missing tail or changing the symlink target. The database itself is pre-created only through the
retained final-directory descriptor; SQLite then opens it in existing-file (`mode=rw`) mode and
its reported `main` database inode is checked before any mutable PRAGMA, schema or event write.

The server-created `Store` retains duplicated directory and database descriptors through every
follow-up constructor and for the application lifespan. Each `Store._connection()` borrows its
own descriptor duplicates, checks both visible and SQLite-connected identities, and never falls
back to an unverified pathname after the retained authority is closed. `Requests` and Codex event
writes now use that connection boundary. `DomainStore` borrows and asserts the same retained
identity instead of treating a later pathname resolution as a second source of truth, and also
uses existing-file SQLite mode. Constructor failure and lifespan shutdown close both retained
descriptors. A repeated lifespan may reacquire them only when a no-follow walk reaches the exact
original directory/database inode pair with the required ownership and modes. Because shutdown
also closes the owned speech, speech-session, understanding and Codex services, a later sequential
lifespan constructs a fresh internally bound service set, refreshes the route closure and
`app.state` references together, and never reuses a closed worker facade.

Initialization does not bind a runtime principal, grant consent, reconcile/start a run, create a
budget session, obtain credentials, or dispatch a provider/tool. The trusted command registry is
fixed to the current `attempt.dispatch` envelope. The production default has no runtime context
resolver, so a valid command is rejected as `dependency_unavailable` before a command intent,
budget reservation, event, or process-local permit exists. An explicitly injected trusted
resolver must return the exact typed permission/attempt/owner/budget bindings; the route then
calls the real `RootCommandCoordinator`. A first pending result and its exact replay both return
HTTP 202, while the root transaction produces one receipt, event, reservation and post-commit
permit. Before invoking that resolver, the command route performs an authenticated read-only
lookup of the durable command journal. An identical same-session replay returns the original
receipt even when the resolver is now absent or failing; changed payload/actor/session bindings
still return conflict. A second exact lookup after resolver failure covers a concurrent commit
race: it waits behind the bounded in-process root-writer lock before consulting SQLite and cannot
mint another process-local permit.

Authenticated `GET /api/v1/events` returns only `PublicEventView` dictionaries plus a bound
cursor, gap/snapshot flag and snapshot link. Repeated `event_type` filters and limits are bounded;
unknown query fields, duplicate cursor/limit fields, unregistered event types, tampered cursors,
multiple `Last-Event-ID` headers, or simultaneous header/query cursors fail closed. The
path-filtered `/api/v1/events/{event_type}` surface makes durable command receipt links
resolvable. `/api/v1/events/stream` emits one bounded `text/event-stream` page with cursor IDs,
`no-store` and `nosniff`; gaps remain an explicit `snapshot_required` event rather than being
crossed silently.

The four documented public read surfaces also accept authenticated `HEAD`: JSON events, SSE,
path-filtered events and snapshot. They validate the same cursor/filter/snapshot reads, return
the authoritative event cursor (and event-page `snapshot_required`) in headers, emit no body,
and never invoke the runtime resolver or change command/event/budget/runtime journals. The ASGI
boundary strips body bytes from HEAD error responses as a final protocol guard.

`GET /api/v1/snapshot` authenticates before and after materialization. One hardened SQLite read
transaction reads the event tail cursor together with bounded public work, run and attempt state.
The projection exposes only IDs, revisions, file counts and registered phases. It validates these
values before release and omits work text, filenames, file bytes, runtime specs, vault/actor/policy
refs and private evidence refs. A snapshot cursor resumes the unfiltered event stream without
replaying events already reflected by that snapshot.

All `/api/v1` boundary and route errors use the fixed public shape
`{code,message,retryability,affected_refs,correlation_id}`. Unknown paths and wrong methods do not
fall back to framework `detail` bodies. Resolver, SQLite and internal exception messages are never
reflected, so canary secrets and host paths remain absent. Existing unversioned `/api/*` responses
retain their compatibility status/body behavior. A missing, malformed, revoked or expired v1
session is `401 unauthenticated`; `403 access_denied` is reserved for authenticated CSRF,
scope/consent and invalid same-origin transport failures.

## Failure-first and verification

The initial HTTP contract had seven tests and failed 7/7 because no shared component state or v1
route existed. The first implementation reached 3 passes / 4 failures and exposed an invalid
raw-ASGI header operation. A fresh independent audit then supplied four concrete defects. The
expanded focused suite reproduced them as 4 failures / 9 passes: target mutation through an
ancestor symlink, resolver-before-replay, invalid-session 403, and missing HEAD routes. After the
server corrections and HEAD gap-metadata follow-up, a second independent filesystem audit found
two initialization races. The first two-case regression reproduced mutation after an already
validated ancestor was replaced. A four-case refinement covered both an absent replacement DB and
a pre-existing user DB when the swap occurs at SQLite open. The next seven-case lifetime suite
failed 7/7 before implementation because the Store did not retain capabilities across downstream
constructors or lifespan cleanup. It now covers swaps at model-catalog, Requests and DomainStore
startup boundaries, both replacement states, constructor-failure cleanup, and clean lifespan
shutdown. A subsequent independent review reproduced one more failure: after a first clean
lifespan, the Store reopened but every closed service object was reused. Its one-case regression
failed before the service-set rebuild and now exercises live speech-session creation plus fresh
Codex/catalog/selection/speech/understanding bindings on a second lifespan. The final focused
command/result is:

```text
PYTHONDONTWRITEBYTECODE=1 \
/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python -m pytest -q \
  app/tests/test_server_api_v1.py
25 passed, 1 warning in 4.86s
```

The widened storage/domain compatibility check used this exact command:

```text
PYTHONDONTWRITEBYTECODE=1 \
/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python -m pytest -q \
  app/tests/test_storage.py \
  app/tests/test_domain_storage.py \
  app/tests/test_model_catalog.py \
  app/tests/test_model_selection.py \
  app/tests/test_speech_sessions.py \
  app/tests/test_understanding.py \
  app/tests/test_server.py
202 passed, 1 warning in 7.31s
```

The final exact ten-file transaction/server regression is:

```text
PYTHONDONTWRITEBYTECODE=1 \
/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python -m pytest -q \
  app/tests/test_server_api_v1.py \
  app/tests/test_server.py \
  app/tests/test_server_session_integration.py \
  app/tests/test_local_session.py \
  app/tests/test_public_events.py \
  app/tests/test_api_command_transaction.py \
  app/tests/test_runtime_budgets.py \
  app/tests/test_runtime_budget_dispatch.py \
  app/tests/test_runtime_ledger.py \
  app/tests/test_domain_permissions.py
300 passed, 1 warning in 51.34s
```

The first browser regression after wiring the hardened domain store produced 2 passes / 61
failures because Node-created macOS temp paths used the `/var` compatibility alias. The restricted
OS-alias normalization above closed that real integration defect. The exact browser command is:

```text
env CONTROL_PYTHON=/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python \
CONTROL_PLAYWRIGHT_MODULE=<node-runtime>/dependencies/node/node_modules/playwright/index.mjs \
PYTHONDONTWRITEBYTECODE=1 \
<node-runtime>/dependencies/node/bin/node \
  --test --test-concurrency=2 \
  app/tests/browser-codex-connection.test.mjs app/tests/browser-first-use.test.mjs \
  app/tests/browser-model-selection.test.mjs app/tests/browser-speech-input.test.mjs \
  app/tests/browser-state-review.test.mjs app/tests/browser-understanding.test.mjs
```

The first post-audit full run produced 63/63 passes in 128884.647834 ms. A second full run after
the final HEAD metadata hardening produced 62/63 passes in 137140.501375 ms: the unrelated
`work-specific model versions restore across work switching and reload without changing input
revisions` browser case observed `medium` once where it expected `low`. The exact isolated retry
then passed 1/1 in 3892.899334 ms:

```text
env CONTROL_PYTHON=/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python \
CONTROL_PLAYWRIGHT_MODULE=<node-runtime>/dependencies/node/node_modules/playwright/index.mjs \
PYTHONDONTWRITEBYTECODE=1 \
<node-runtime>/dependencies/node/bin/node \
  --test --test-name-pattern='work-specific model versions restore' \
  app/tests/browser-model-selection.test.mjs
```

After the sequential-lifespan service rebuild, the exact six-file command above passed **68/68**,
with no skip or failure, in **142858.209875 ms**. The previously observed work-switch case passed
in this final full run.

This sequence is recorded as a browser-suite stability observation, not hidden or converted into
a green final-full claim. The Python warning is the existing Starlette/AnyIO `BlockingPortal`
deprecation warning.

| File | SHA-256 |
|---|---|
| `app/server.py` | `fb6619651a982d773ed16aaacaa75eb5265b105676c4e05f2bbe08e6b56177e9` |
| `app/storage.py` | `6e938fa319e4e7520b3bcba1655c06a27c3fb01d1cb169d9c51745fff4e62fe5` |
| `app/requests.py` | `24fa41a93b6b0c08f4fad3559031a1c4f6e1aa6cc38ba2c1edfad8cc97b0fb6e` |
| `app/codex_connection.py` | `c8930e78f9e8a7445d38763c983249339df94e89592f72eeffd786aba5dfbaa7` |
| `app/api/routes.py` | `a448df305bb3e0587f9968ad45f6e581bc59a735832802f30b67642302c9f363` |
| `app/tests/test_server_api_v1.py` | `b30f738c0bca48befadac1a2312a315c8e8b4c54a9f7177e62ff2fe91970f3dc` |
| `app/api/transaction.py` | `55497d520ecdde1105bee5148b053e0647aa16a7520af71ffc6e855e5cd6d514` |
| `app/api/commands.py` | `f7c1512edbab66123dd5110127824bfd41442f6f50ea4be8fb4c57722cf1de71` |
| `app/api/views.py` | `cfc655fa5c52bf53a938ff422839ae10b9e4e87015ad40e3f855b450dd58d51b` |
| `app/api/session.py` | `dea47cdb69e220838292ad4cc79e969be232ea4358aa317be192e20cf1f43d4f` |
| `app/domain/store.py` | `8a39c4ab85713844aff6e90b410ccfc1f2975051d95d0230547f00c272b89f77` |
| `app/domain/permissions.py` | `3e1d631fad40dfdf61b7924ca69dbb497086ff1639a6fd83ad58e67c8aee79b9` |
| `app/runtime/budgets.py` | `6ab615d5491437ad92ba6c989e5e90e9f8b5c2b2de18c314ccf4e7dac1a8d6d6` |
| `app/runtime/ledger.py` | `e2ecc5988694d406fb8807196ff8d7abbc8fe68ae15f380637ce34e545714044` |

These hashes identify this reviewed working snapshot; they are not signatures.

## Honest limits

The SSE endpoint is a bounded resumable page, not a long-lived push/backpressure service. The
snapshot is a minimal recovery projection with a deliberate 10,000-item-per-class ceiling; it is
not yet the complete graph, artifact, approval or DeepTwin state view. Its item ceiling currently
returns an unavailable response rather than a paginated snapshot manifest.

The default server intentionally cannot resolve a dispatch context. A later trusted runtime
integration must supply reconciled attempts, live process-local principals/grants and a permit
consumer; this slice neither starts nor simulates those effects. The default compiler semantic
verifier rejects every projection until the reviewed compiler integration replaces it. Provider
acceptance, remote exactly-once behavior, tool execution, artifact sealing and terminal result
reconciliation are not proven here.

Finally, this evidence depends on the shared root transaction implementation. Its clock-floor
review fix and the combined 300-test regression are green. The earlier non-deterministic browser
observation above remains disclosed.

After the final service-set rebuild, a different agent performed the required fresh review without
editing implementation or evidence. It entered the same app three times; verified fresh route and
`app.state` bindings for Codex, catalog, selection, speech, speech sessions and understanding;
verified stable Store/Domain/API-v1 identity; and exercised initial, partial, late and re-entry
constructor failures plus a first-service close exception. It reported **CLEAR** with 25/25 focused,
300/300 exact integration, 202/202 storage/domain and 12/12 identity-targeted checks. Every later
task that edits these shared surfaces must still run the relevant regressions; this review does not
pre-approve future changes.
