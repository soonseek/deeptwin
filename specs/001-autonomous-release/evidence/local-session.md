# T015/T016 authenticated local API slice — offline implementation evidence

> **ADR-009 이후의 용도:** 이 문서의 `launcher-minted` loopback bootstrap은 출시할 웹
> 제품의 로그인·최초 소유자 계약이 아니라, 이전 로컬 개발 슬라이스의 제한된 역사적 시험 증거다.
> 네이티브 런처는 현재 제품 경계가 아니며 T025/ADR-010–012의 브라우저 최초 설정·세션·
> 복구 계약을 이 기록으로 통과시킬 수 없다.

2026-09-07 · authoritative worktree:
`/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure`.

Status: T015 is complete after isolated contracts and real HTTP/browser integration. The
latest focused run has 52 Python tests and the complete existing browser set has 63 tests.
T016 remains open only for the shared command/domain/budget/runtime transaction and public
SSE/snapshot route delivery. No provider, paid API, credential, user vault or external
network service was used.

## Implemented boundary

`app/api/session.py` accepts only canonical configured IPv4 loopback/`localhost` authorities.
Bootstrap session creation is a same-origin POST using a launcher-minted CSPRNG capability
with a maximum 60-second life, a bounded rolling attempt count and a bounded number of live
capabilities. It atomically marks the capability consumed before returning a short-lived
HttpOnly/SameSite=Strict session cookie and separate CSRF token. Reloaded or additional tabs
receive distinct tokens in an eight-entry FIFO so one page cannot silently disable another;
the oldest token is evicted when the bound is exceeded. A replay—including one after the launch-code expiry
while its session remains live—revokes that session. Session validation binds exact Host,
HTTP Origin, `Sec-Fetch-Site: same-origin`, cookie identity and CSRF on mutations. GET/HEAD
requires a live session but no mutation CSRF. The raw ASGI-header parser rejects duplicate
or non-ASCII Host/Origin/fetch-site/Cookie/CSRF fields rather than choosing a last value.

`app/api/commands.py` freezes trusted command definitions and accepts exact canonical
`command-v1` envelopes only. Command type, target kind, required revision/hash and typed
arguments are validated; arbitrary command kinds and extra fields do not acquire authority.
The SQLite journal keys receipts by exact `(vault_id, command_id)`, commits an `executing`
intent before the handler, and looks up duplicates before any handler call. An identical
completed request returns its stored result across reopen; changed payload/session/actor
conflicts. Concurrent or crash-uncertain requests do not run again and remain
`outcome_unknown`; raw handler exceptions are not persisted.

`app/api/views.py` stores the full typed EventEnvelope but derives `PublicEventView` from an
explicit allowlist. Actor, vault, policy and `private_evidence_refs` never enter the public
view. Event-specific metadata is revalidated again during SSE rendering so mutation of a
returned Python dictionary cannot create a private side channel. Per-vault SQLite sequences
are monotonic. Opaque cursor locators bind vault, stream UUID, generation, sequence and the
normalized event-type filter. Pages scan bounded rows, reject cursor tampering/cross-binding,
and return `snapshot_required` plus a coarse explicit gap for both declared generations and
physical sequence holes instead of crossing or hiding them.

`app/server.py` now exchanges the launcher capability only at
`POST /api/session/bootstrap`, authenticates every other `/api/*` route, rotates/adds a page
token through authenticated `GET /api/session/csrf`, and never includes a bootstrap or CSRF
secret in the public static shell or ordinary bootstrap payload. The launcher URL carries the
short-lived capability in a fragment, which is stripped after exchange and is not sent in the
HTTP request target. Exact Host, Origin, Fetch Metadata, body-size and duplicate-header checks
run before route handlers. The real frontend successfully traverses this boundary; Playwright
state probes explicitly add Fetch Metadata only to its non-renderer request client instead of
overriding Chromium-owned headers.

## Failure-first and actual verification

The first focused run stopped with **2 collection errors** because the three API modules did
not exist. The initial implementation then produced **29 passing session/command cases and
14 public-event failures/errors**, exposing an incorrect six-column stream insert. After that
fix, 43 tests passed. Three further failure-first canaries separately reproduced and closed:

- replay after launch-code expiry did not revoke the issued live session;
- no raw-header singleton parser existed, leaving duplicate-header handling to integration;
- mutating a returned public metadata dictionary could be serialized into SSE without a
  second allowlist check.

The latest focused result in the exact fresh dependency environment is:

```text
52 passed, 1 warning in 0.29s
```

The browser security and regression set produced:

```text
63 passed, 0 failed in 123.28s
```

The Python warning is the existing Starlette/AnyIO `BlockingPortal` deprecation warning.
Browser regressions include one-use entry, replay rejection, multi-tab model conflicts,
reloads, Korean IME, files, speech, delayed/aborted requests and understanding recovery.

Current source identity:

| File | SHA-256 |
|---|---|
| `app/api/__init__.py` | `b85c417f1e74007da7869ff53c2a43a59b0e5feb251c17e07d0e887154083b2f` |
| `app/api/session.py` | `dea47cdb69e220838292ad4cc79e969be232ea4358aa317be192e20cf1f43d4f` |
| `app/api/commands.py` | `60cfbad2635a95f8605865792cae8fa437f14394663f897f76828f232470ee7e` |
| `app/api/views.py` | `aa6028a34fd1f5aca081353783eae47c576b1cbe78741c0142a809c004596247` |
| `app/server.py` | `9023a66aaf68c2f81c9224932ba6c3bf6b825378e7eb59f7bd3ae727f6eb8b94` |
| `app/tests/test_local_session.py` | `4a3dea17f38a055c9a588a91cfff392f159a01a5193c8aee98365f0917edae8e` |
| `app/tests/test_public_events.py` | `e31d0d6587c346525f6c34c5c891fbf23ddc59c3f1ec2ee886fb0626d9ac905f` |
| `app/tests/test_server_session_integration.py` | `f8f2e66c9f2fd28ea8674ca7fed186ffe9dd4ce97464b0d29d38b3a3dcefbd0e` |
| `app/tests/helpers/local-session.mjs` | `f9bc620d0c9d211ed87a5a3417f1fcb9c8e1c56de60099dc1ed64b4024065b9e` |

These are final focused-slice content identities, not release signatures.

## Open integration limits

The existing application routes now use the authenticated boundary, so the prior legacy
unauthenticated bootstrap gap is closed. `Last-Event-ID`, snapshot links and actual bounded
SSE delivery are still server work; the tested encoder/cursor is not itself a live stream.

`CommandJournal` uses a durable write-ahead receipt but cannot make an arbitrary handler's
domain mutation, budget reservation, runtime dispatch intent, event and result one SQLite
transaction from this isolated module. A crash therefore fails closed as unknown instead of
rerunning, but can leave local state committed without a completed result receipt. Actual
`expected_revision`/target-hash comparison and permission/grant evaluation must run inside the
root-owned command handler and its shared transaction. Event append likewise is not yet atomic
with those changes or the execution ledger.

The event journal has a bounded resumable page/SSE encoder, not an authoritative snapshot
builder, backpressure loop, retention migration or legacy-event converter. The migration
digests are local to these API tables rather than one reviewed domain/runtime schema ledger.
Sessions are intentionally process-local and expire/revoke on restart; native relaunch and
draft recovery must establish a new session without redispatch. This is a local same-OS-user
boundary, not a proof against another process already controlling that OS account.
