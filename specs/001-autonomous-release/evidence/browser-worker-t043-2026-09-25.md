# T043 slice — sandboxed Chromium worker, fetch service and typed IPC (2026-09-25)

Status: **worker, typed IPC and dispatch wiring landed; T043 stays open** (see "Open"
below). Builds on the pinned transport of evidence/egress-transport-t043-2026-09-23.md.

## Topology (existing ids, compose unchanged)

| pair | requester → responder | pair gid | what crosses it |
|---|---|---|---|
| `cp-browser` | control 20102 → browser 20105 | 21104 | one typed browser request, one bounded result |
| `cp-fetch` | control 20102 → fetch 20104 | 21102 | grant register / revoke (with the fetch service's own usage) |
| `browser-fetch` | browser 20105 → fetch 20104 | 21110 | one URL under a grant id, one bounded body |

Every pair uses the existing verified pair-root machinery (root-initialized generation,
HMAC readiness record, socket inode, SO_PEERCRED, boot-secret handshake, per-frame MACs),
one request per connection, both directions bounded. The browser (`network_mode: none`)
has no path out except `browser-fetch`; the fetch service is the only process that runs
the egress broker.

## What landed

- `app/runtime/egress.py`: `EgressBrokerError.code`, one of the closed `EGRESS_CODES`
  (`grant_denied`, `dns_denied`, `redirect_denied`, `too_large`, `timeout`,
  `fetch_failed`, `invalid_request`). An admission failure on a redirect hop is
  `redirect_denied`; `FetchResult.content_type` carries the final response's declared
  type. `egress_transport.py` sets codes on its refusals (a timed-out pinned connect is
  `timeout`). Existing messages are unchanged.
- `app/workers/fetch_channel.py`: the `cp-fetch`/`browser-fetch` profiles and grammar;
  `BrowserGrant` (navigation **sources** = https URL prefixes, **recipients** = hosts every
  request may reach, per-response/total byte limits, request count, redirect budget,
  lifetime; every source host is a recipient); `FetchControlClient` (register under a
  fresh 256-bit id, excluding the product's own hosts; revoke returns the service's own
  accounting); `BrowserFetchClient`. URLs with dot segments (literal or `%2e`) or encoded
  separators are refused, so a source prefix means exactly what it says.
- `app/workers/fetch_service.py` + `fetch_worker_main.py`: grants held in memory (bounded,
  monotonic expiry); each browser fetch runs `broker_fetch` with the pinned transport:
  navigation URL and final URL under the sources, every hop's host a recipient, every
  resolved address public (a private or mixed answer is `dns_denied`), per-response limit
  = min(per-response, remaining total). The answer carries only status, a sanitized
  content type, final URL, redirect count and body+digest — never `Set-Cookie` or other
  headers; the browser's request headers are never forwarded. Two listeners, one process.
- `app/adapters/browser.py` (worker only): headless Chromium over `--remote-debugging-pipe`
  (fds 3/4, stdlib only — no driver dependency, no DevTools port). One session = one fresh
  profile dir under the worker's 0700 profile root, removed on close. Every request is
  paused by the DevTools `Fetch` domain and answered by controlled fulfillment from the
  fetch service (GET only; a broker-followed redirect is replayed as a 302 and the
  re-request served from the same brokered result); scripts disabled, downloads denied,
  `--host-resolver-rules=MAP * ~NOTFOUND`, `--no-proxy-server`, never `--no-sandbox`.
  Positive sandbox probe before any content: every renderer must be under seccomp-BPF
  (`Seccomp: 2`) in a nested PID namespace, else `sandbox_unavailable`.
- `app/workers/browser_channel.py`: `cp-browser` profile, `BrowserControlConfiguration`
  (control) and `BrowserWorkerConfiguration` (worker) attachments, `BrowserRequest`
  (`navigate` | `read` bounded text | `screenshot` bounded viewport PNG, deadlines), and
  the frame-only `BrowserClient`: control pre-checks the URL against the grant, registers,
  runs, revokes, and refuses a result whose final URL leaves the sources, whose profile
  was not wiped, whose sandbox reading is not positive, whose output digest/PNG size
  differs, or whose body bytes/served requests differ from the fetch service's own
  accounting (`malformed_result`).
- `app/workers/browser_service.py` + `browser_worker_main.py`: the worker refuses to start
  when its network namespace has any interface but loopback (`network_present`) or its
  profile root is not a private 0700 dir it owns; stale sessions are removed at startup.
  Closed codes: `grant_denied`, `dns_denied`, `redirect_denied`, `too_large`, `timeout`,
  `render_failed`, `fetch_failed`, `sandbox_unavailable`, `invalid_request`.
- `app/runtime/browser_attempt_transport.py`: `BrowserAttemptTransport`
  (`CompiledToolTransport`) for `browser_navigate` / `browser_read` / `browser_screenshot`
  1.0.0, effect `read`. Built for one compiled node binding, one request whose operation
  is the bound tool's, one grant (URL under a source; product host never a recipient).
  ToolCall intent claimed with the send and settled from what control observed; a verified
  observation is sealed as an `artifact` (`browser-tool-output-v1`, output imported as a
  blob) and is the `succeeded` result; grant/DNS/redirect refusals are `denied`
  (`permission_denied`), timeout `timed_out`, other worker failures `failed`, all with
  final usage; no reachable worker is `definitely_not_sent`.
- `app/server.py`: `--browser-worker-config` (`deeptwin-browser-control-attachment-v1`) →
  `create_app(browser_worker=...)` → `app.state.browser_tools` = `BrowserToolset`, or
  `BrowserToolsUnavailable` (every build refuses `unavailable`) when not configured. No
  route added.

## Observed

`app/tests/test_browser_worker.py`: **31 passed** (three consecutive full runs of the
then-30 tests passed; the 31st, broker per-hop codes, added after). Root, Linux, local
headless Chromium 141 (`/opt/pw-browsers/chromium_headless_shell-1194`), no outbound
network — the fixture site is a loopback HTTPS server with a test CA made by `openssl`.

Real-process qualification (root-only, skips elsewhere): the unmodified fetch entrypoint
as 20104 (groups 21102/21110); the unmodified browser entrypoint via
`unshare --net -- setpriv --reuid=20105 --groups=21104,21110 --no-new-privs --inh-caps=-all`;
the requester as 20102; three root-initialized pair roots. Only substitutions: profile
relocation, and in the fetch child only the fixture resolver table, the test CA, the
fixture port and pinned-address → loopback translation for the fixture's public-looking
addresses (any other address refuses before a socket). Cases:

- `read` of the granted page: title from the document (the page's `<script>` did not run),
  rendered text, document digest = the fixture bytes' sha256, the granted image fetched,
  the other host's tracker refused; `sandbox` = seccomp filter + PID namespace, 2 renderers.
- redirect within the grant followed (final `/final`); `screenshot` 320×200 whose centre
  pixel decodes to (255, 0, 0) — actually rendered; digest verified.
- ungranted host: refused by control before any send (`sent=false`) and, with control's
  pre-check bypassed, by the fetch service (`grant_denied`).
- redirect to another host, to `https://127.0.0.1/`, to `https://[::1]/`: `redirect_denied`;
  redirect to a granted name resolving privately: `dns_denied`; a private name: `dns_denied`.
- DNS rebinding: first answer public (page loads), second answer 127.0.0.1 (its image
  refused, `denied ≥ 1`).
- iframe to an ungranted host refused; an `application/octet-stream` download refused
  (`render_failed`); a 3 MiB page over a 1 MiB grant `too_large`; a 6 s page under a 3 s
  deadline `timeout`.
- the fixture server never received a request for the ungranted host, never a `Cookie` or
  `Referer`; the profile root is empty after every session; logs carry only
  `event`/`class`/`outcome`/`pair`.
- a graph `writer` node bound to `browser_read` runs through the real dispatcher and
  `BrowserAttemptTransport` to the real worker; the sealed result's blob holds the page
  text, ToolCall `succeeded`.
- the worker's netns: not the host's, only `lo`; from inside it (nsenter, as 20105)
  connects to the fixture port, a public-looking and a private address all fail and the
  name does not resolve. A browser worker started without `unshare --net` exits 1
  (`network_present`). A foreign identity (20104) is refused on `cp-fetch` before any send.

In-thread tests (any platform): profiles equal `deploy/security/service-ids.json` and
compose; exact configuration objects; grant bounds; broker per-hop codes; the fetch
service's source/recipient/scheme/port/DNS/redirect/byte/request/expiry/product-origin
enforcement and header stripping; the client's refusal of contradicted results; dispatch
succeeded/denied/unreachable through the ledger; server attach/unavailable; Chromium argv
never contains a flag from `deploy/tests/browser_worker_canary.mjs`'s forbidden list;
import boundary: importing `app.server`, the transport and both channel modules loads no
`app.adapters.browser`, browser/fetch service or worker main, and only
`app/workers/browser_service.py` imports the driver.

Kept passing: `test_egress*.py`, `test_extension_*.py`, `test_document_*.py`,
`test_web_owner_integration.py`, `test_first_party.py` (1132 passed, 3 skipped), and
`test_core_import_boundary`, `test_client_conformance`, `test_tool_boundary`,
`test_run_artifact_previews`, `test_scheduler_attempt_dispatch`,
`deploy/tests/test_compose_topology`, `test_worker_boundary`, `test_worker_listener`.

## Open (why T043 stays unchecked)

- **Source/projection categories.** runtime.md §6 binds a grant to permitted recipients
  *and* allowed source/projection categories of the outbound request. This slice enforces
  URL-prefix navigation sources and recipient hosts; data-source tagging of URL/query
  content (DLP-style projection checks) is not implemented.
- **Grant authority.** The `BrowserGrant` is supplied code-side when the transport is
  built; it is not yet resolved from a persisted grant record / the compiled binding's
  `grant_ref`, and no production graph authority registers the browser ToolDefinitions
  (`ClaudeRunExecutor` compiles with `tool_definitions=[]`).
- **Packaging (T081/T089).** `deploy/locks/service-roots.json` declares the browser worker
  as Node 24 + `playwright-core` 1.63.0 + chromium-headless-shell 153; this worker needs a
  Python runtime (stdlib only, no new dependency) + chromium-headless-shell. The browser
  image and its lock must be reconciled; local qualification used Chromium 141.
- **Container qualification (T081/T079).** No Docker here: the compose seccomp profile
  (`deploy/security/browser-seccomp.json`), read-only root, tmpfs profile root, `init`,
  pids/memory limits and `network_mode: none` were not exercised; the netns came from
  `unshare --net`. Chromium's own sandbox (userns + seccomp-BPF) was positively probed.
- **Scripts.** JavaScript is always disabled; JS-rendered pages, WebSocket/ServiceWorker/
  popup qualification with scripts on, and interaction tools are out of this slice.
