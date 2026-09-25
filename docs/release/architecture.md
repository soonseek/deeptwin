# DeepTwin framework architecture (draft)

Date: 2026-09-23 · Updated: 2026-09-25 · Status: **draft for T084; describes the repository as it
is, not a qualified release**. Normative sources: `specs/001-autonomous-release/plan.md`,
`decisions.md` (ADR-009… ADR-014) and the contracts under `specs/001-autonomous-release/contracts/`.
Where this page and a contract disagree, the contract wins.

## 1. What DeepTwin is meant to be

A self-hostable, web-based multi-agent framework. The **browser UI is the only official end-user
product surface** and the first reference implementation of a reusable core. The core owns graph,
authority, artifact, evidence and growth contracts that are independent of the browser/API
adapter. Deployment tooling (Docker, Compose, Portainer), the operator maintenance tools and the
server-internal workers are not product surfaces; see [surface-boundaries.md](surface-boundaries.md).

The repository is licensed under the **Apache License 2.0** (`LICENSE`, `NOTICE`), approved by
the owner on 2026-09-24 ([license-recommendation.md](license-recommendation.md)).

## 2. Repository map

| Path | Role | Status |
| --- | --- | --- |
| `app/static/` | Browser shell: `start.html`, `work.html`, `observe.html`, `versions.html`, `records.html`, `settings.html` and their `.mjs` modules (closed catalogue in `app/api/assets.py`) | development preview |
| `app/api/` | Web boundary, owner session routes, frozen first-party route composition, route factories | partial (128 contributed `/api/v1` routes) |
| `app/api/route_contributions/` | Build-installed JSON route descriptors (one file per contribution) | 25 contributions |
| `app/services/` | Domain services (works, source readings, work models, conversation, design workspace, runs, approvals, consents, artifacts, alternatives, hypotheses, versions/growth, exports, backups, retention, credentials, browser grants, owner auth, deployment control, …) | partial |
| `app/domain/` | Domain store, refs, schemas, event envelopes, permissions, extension-binding records | partial |
| `app/runtime/` | Graph compiler, LangGraph scheduling adapter, runtime ledger, budgets, gates, tool dispatcher, egress broker and pinned transport, worker coordinator and per-node attempt transports (provider, extension, browser) | partial |
| `app/workers/` | Isolated-worker IPC (pair roots, listener, broker, artifact stream) and the worker processes: credential gateway, document, backup-crypto, browser, fetch, extension worker | partial; no worker is wired into Compose |
| `app/operations/` | Deployment-only init jobs, backup/restore, export manifest, retention, migrations, and the stopped-control-plane operator tools (`deployment_control`, `updates`, `recovery`) | partial |
| `app/deployment/` | Deployment request/receipt contracts (including owner recovery and the v2 trust set), rendering and publication | partial |
| `app/extensions/` | Core-owned extension port contracts, candidate registry, provider conformance/installation, transport qualification, binding service | partial (T087 open) |
| `schemas/v1`, `schemas/v2` | Exported JSON Schemas (domain envelopes, route contribution, origin profile, extension ports, deployment, provider installation/conformance) | generated artifacts |
| `deploy/` | Compose skeleton, build-input locks, manifests, verifiers, canaries, bootstrap helper | candidate, not runtime-qualified |
| `sdk/python/deeptwin_ext/` | Historical extension-kit source checkpoint | **not** the installable SDK |
| `examples/extensions/` | Inert manifest examples | not runnable extensions |
| `evals/deeptwin/` | Q01 harness, verifiers, frozen calibration/qualification designs | offline; no qualified critic |
| `control-prototype/`, `prototype/` | Synthetic control prototype and earlier prototype | not release evidence |
| `packaging/macos/` | Pre-ADR-009 native experiment | historical only, out of release scope |
| `specs/`, `docs/` | Specification, contracts, evidence, design notes | — |

## 3. Runtime topology (target)

The Compose skeleton (`deploy/compose.yaml`) declares the intended service split. Every image is an
unresolved `${…_IMAGE}` variable that must become an exact `@sha256:` reference produced by T081.

| Service | Network | Purpose | Process in this repository |
| --- | --- | --- | --- |
| `edge-local` / `edge-portable` | internal `edge-control` (+ publish) | exactly one edge profile: loopback HTTP or operator-TLS HTTPS | no DeepTwin process (edge image from T081) |
| `control` | internal `edge-control` only | web control plane: API, session, domain store, runtime ledger | `python -m app.server` |
| `provider` | `provider-egress` | credentialed provider gateway | `app.workers.credential_gateway_main` |
| `fetch` | `fetch-egress` | public-web fetch broker | `app.workers.fetch_worker_main` |
| `codex` | `codex-egress` | managed Codex runner | not implemented (T088) |
| `browser` | `none` | sandboxed Chromium, reached only through `fetch` | `app.workers.browser_worker_main` |
| `document` | `none` | PDF/DOCX reading, previews, PDF secret scan | `app.workers.document_worker_main` |
| `backup` | `none` | age encryption/decryption | `app.workers.backup_crypto_main` |
| `speech`, `evaluation`, `runtime-extension` | `none` | isolated workers | not connected to the supported server |
| `state-root-init`, `ipc-root-init` | `none` | one-shot init jobs | declared with commands |

No worker service in the skeleton has a `command` yet; wiring the processes above into images,
mounts and attachment files is T081. Each control-plane/worker pair has its own IPC volume with
fixed owners/modes, a per-boot secret and Linux `SO_PEERCRED` checks (`app/workers/ipc_root.py`,
`listener.py`, `broker.py`; identities in `deploy/security/service-ids.json`). The control plane
never mounts a Docker socket and does not start, stop or replace containers. The skeleton's own
`open_gates` list what is still missing (control entrypoint on `control:8080`, single edge profile
validation, final images, dual-platform runtime evidence, and more).

The control plane attaches to each worker only through an operator-supplied attachment file
(`--credential-gateway-config`, `--document-worker-config`, `--backup-worker-config`,
`--browser-worker-config`); without one, the dependent feature reports itself unavailable. The
current `main()` also wires a direct-adapter Claude executor whose owner-entered key lives in the
control-plane process memory only; this is an owner-approved development profile, not the release
isolation boundary (see [security.md](security.md) §7).

## 4. Request path in the control plane

1. **Web boundary** (`app/api/web_boundary.py`): exact scheme/Host/Origin against the deployment's
   `OriginProfile`, `Sec-Fetch-Site` check, rejection of `Forwarded`/`X-Forwarded-*`, raw-path
   hygiene, per-route body limits, security headers, CSRF verification for mutations.
2. **Owner session** (`app/api/session_routes.py`): `/`, `/health`, `/session`,
   `/session/bootstrap`, `/session/login`, `/session/password`, `/session/revoke-others`,
   `/session/logout` and the closed static asset
   catalogue (`app/api/assets.py`). These are unversioned by design. After an owner recovery,
   `/health` adds `recovered: true`; during the restricted recovery start every authority method
   fails closed.
3. **Frozen route composition** (`app/api/router_composition.py`, `first_party_catalog.py`): each
   JSON descriptor is read with no-follow opens, validated against a closed schema, an allowlisted
   factory, allowed auth policies and scopes, and mounted once. Every current route uses the
   `browser_session` policy.
4. **Services → domain store / runtime ledger**: services perform authorization-aware commands;
   the store enforces integrity and purpose partitioning but is not itself an authorization API.

## 5. Execution core

- `app/runtime/graph.py` compiles an approved graph to fixed core handler keys only; it never
  imports a path or evaluates model-supplied code.
- `app/runtime/scheduler.py` maps a compiled graph onto a LangGraph `StateGraph` with
  ledger-reconciled, idempotent node visits. Human gates clear only on a recorded owner decision;
  execution-bound (v2) approvals are consumed per attempt of one execution and expire.
- `app/runtime/ledger.py` persists run/attempt/send-intent state; a committed send intent means only
  that a transfer may have started, so restart handling is conservative.
- `app/runtime/worker_coordinator.py` performs one-shot authenticated dispatch with an already
  authorized, already budgeted permit; `node_attempts.py` and the per-kind attempt transports
  route a node attempt to its worker.
- `app/runtime/tools.py` and `app/runtime/egress.py` form the tool and network boundary
  ([security.md](security.md)).
- Growth: paired comparisons replay past external effects only through an owner-approved tool
  effect boundary (recorded replay or an isolated sink), never by re-sending
  (`app/services/tool_effect_approvals.py`, `tool_effect_isolation.py`).

The supported product path today is narrower than this core: a work model can be drafted and
confirmed, but no production route yet produces a design request, and design approval is refused
because no qualified critic configuration exists (T036/T038/T077). Runs are not started from the
browser.

## 6. Extension model (design; implementation partial)

ADR-014 defines four trust tiers: `deployment_trusted` core adapters, `runtime_worker` extensions,
code-free `definition_package` lenses/evaluators, and the built-in `managed_provider_runner`. The
core owns 11 semantic ports (`schemas/v1/extensions/ports/<port>/{config,request,result,error}`,
44 schema artifacts). Executable third-party code runs only as an operator-staged OCI service.

Current code implements inert candidate registration and listing, provider installation records
(operator-staged revision 1, verified revision 2), provider conformance runs over fixed vectors,
the sealed provider-transport qualification, and owner bindings of the provider port with
compare-and-set heads, disable, rollback and rollback-retention release
(`app/extensions/binding_service.py`), shown on `Settings > Extensions`. Only `provider-port-v1` is
bindable: no other port has a durable qualification record. T087 (the full framework, SDK and
client) remains open. See [extension-authoring.md](extension-authoring.md).

## 7. Two application factories

- `create_app` in `app/server.py` is the **supported** factory: exact deployment authority,
  `start.html` at `/`, only the frozen route contributions, no OpenAPI or docs routes.
- `create_development_app` is a **development preview** (legacy `index.html` shell, unversioned
  `/api/works…` and `/api/speech…` routes, loopback only). It is not a release surface and not a
  security boundary.

## 8. What is not yet built

No final service images and no qualified runtime topology; no worker wired into Compose; no
run-start screen; no production design-request source or approvable design; no managed Codex
runner (T088) or microphone input (T024); provider sends through the credential gateway are not
used by runs; no installable SDK or HTTP client; no OpenAPI document (the supported factory sets
`openapi_url=None`); and no service-client bearer routes. Progress per task is tracked in
`specs/001-autonomous-release/tasks.md`.
