# DeepTwin framework architecture (draft)

Date: 2026-09-23 · Status: **draft for T084; describes the repository as it is, not a qualified
release**. Normative sources: `specs/001-autonomous-release/plan.md`, `decisions.md` (ADR-009…
ADR-014) and the contracts under `specs/001-autonomous-release/contracts/`. Where this page and a
contract disagree, the contract wins.

## 1. What DeepTwin is meant to be

A self-hostable, web-based multi-agent framework. The **browser UI is the only official end-user
product surface** and the first reference implementation of a reusable core. The core owns graph,
authority, artifact, evidence and growth contracts that are independent of the browser/API
adapter. Deployment tooling (Docker, Compose, Portainer) and server-internal workers are not
product surfaces; see [surface-boundaries.md](surface-boundaries.md).

The repository has **no project license yet**, so it is not a legally open-source release
([license-recommendation.md](license-recommendation.md)).

## 2. Repository map

| Path | Role | Status |
| --- | --- | --- |
| `app/static/` | Browser shell: `start.html`, `work.html`, `records.html`, `observe.html` and their `.mjs` modules | development preview |
| `app/api/` | Web boundary, owner session routes, frozen first-party route composition, route factories | partial (54 contributed `/api/v1` routes) |
| `app/api/route_contributions/` | Build-installed JSON route descriptors (one file per contribution) | 9 contributions |
| `app/services/` | Domain services (works, runs, artifacts, drafts/alternatives, exports, consents, approvals, owner auth, …) | partial |
| `app/domain/` | Domain store, refs, schemas, event envelopes, permissions | partial |
| `app/runtime/` | Graph compiler, LangGraph scheduling adapter, runtime ledger, budgets, gates, tool dispatcher, egress broker, worker coordinator | partial |
| `app/workers/` | Isolated-worker IPC (listener, broker, artifact stream), provider/credential gateway, extension worker, backup crypto | partial |
| `app/operations/` | Deployment-only init jobs, backup/restore, export manifest, retention, migrations | partial |
| `app/deployment/` | Deployment request/receipt contracts, rendering and publication | partial |
| `app/extensions/` | Core-owned extension port contracts, candidate registry, provider conformance/installation | partial (T087 open) |
| `schemas/v1`, `schemas/v2` | Exported JSON Schemas (domain envelopes, route contribution, origin profile, extension ports, deployment) | generated artifacts |
| `deploy/` | Compose skeleton, build-input locks, manifests, verifiers, canaries, bootstrap helper | candidate, not runtime-qualified |
| `sdk/python/deeptwin_ext/` | Historical extension-kit source checkpoint | **not** the installable SDK |
| `examples/extensions/` | Inert manifest examples | not runnable extensions |
| `control-prototype/`, `prototype/` | Synthetic control prototype and earlier prototype | not release evidence |
| `packaging/macos/` | Pre-ADR-009 native experiment | historical only, out of release scope |
| `specs/`, `docs/` | Specification, contracts, evidence, design notes | — |

## 3. Runtime topology (target)

The Compose skeleton (`deploy/compose.yaml`) declares the intended service split. Every image is an
unresolved `${…_IMAGE}` variable that must become an exact `@sha256:` reference produced by T081.

| Service | Network | Purpose |
| --- | --- | --- |
| `edge-local` / `edge-portable` | internal `edge-control` (+ publish) | exactly one edge profile: loopback HTTP or operator-TLS HTTPS |
| `control` | internal `edge-control` only | web control plane: API, session, domain store, runtime ledger |
| `provider` | `provider-egress` | credentialed provider gateway |
| `fetch` | `fetch-egress` | public-web fetch broker |
| `codex` | `codex-egress` | managed Codex runner |
| `browser`, `document`, `speech`, `evaluation`, `runtime-extension`, `backup` | `none` | isolated workers reached only over per-pair Unix sockets |
| `state-root-init`, `ipc-root-init` | `none` | one-shot init jobs |

Each control-plane/worker pair has its own IPC volume with fixed owners/modes, a per-boot secret
and Linux `SO_PEERCRED` checks (`app/workers/ipc_root.py`, `listener.py`, `broker.py`). The control
plane never mounts a Docker socket and does not start, stop or replace containers. The skeleton's
own `open_gates` list what is still missing (control entrypoint on `control:8080`, single edge
profile validation, final images, dual-platform runtime evidence, and more).

## 4. Request path in the control plane

1. **Web boundary** (`app/api/web_boundary.py`): exact scheme/Host/Origin against the deployment's
   `OriginProfile`, `Sec-Fetch-Site` check, rejection of `Forwarded`/`X-Forwarded-*`, raw-path
   hygiene, per-route body limits, security headers, CSRF verification for mutations.
2. **Owner session** (`app/api/session_routes.py`): `/`, `/health`, `/session`,
   `/session/bootstrap`, `/session/login`, `/session/logout` and the closed static asset
   catalogue (`app/api/assets.py`). These are unversioned by design.
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
  ledger-reconciled, idempotent node visits.
- `app/runtime/ledger.py` persists run/attempt/send-intent state; a committed send intent means only
  that a transfer may have started, so restart handling is conservative.
- `app/runtime/worker_coordinator.py` performs one-shot authenticated dispatch with an already
  authorized, already budgeted permit.
- `app/runtime/tools.py` and `app/runtime/egress.py` form the tool and network boundary
  ([security.md](security.md)).

## 6. Extension model (design; implementation open)

ADR-014 defines four trust tiers: `deployment_trusted` core adapters, `runtime_worker` extensions,
code-free `definition_package` lenses/evaluators, and the built-in `managed_provider_runner`. The
core owns 11 semantic ports (`schemas/v1/extensions/ports/<port>/{config,request,result,error}`,
44 schema artifacts). Executable third-party code runs only as an operator-staged OCI service.
Current code implements candidate registration, provider conformance/installation records and
parts of the tool path; T087 (the full framework, SDK and client) remains open. See
[extension-authoring.md](extension-authoring.md).

## 7. Two application factories

- `create_app` in `app/server.py` is the **supported** factory: exact deployment authority,
  `start.html` at `/`, only the frozen route contributions.
- `create_development_app` is a **development preview** (legacy `index.html` shell and
  unversioned `/api/works…` routes, loopback only). It is not a release surface and not a security
  boundary.

## 8. What is not yet built

No final service images, no qualified runtime topology, no run-start or provider-connection
screen, no model-backed understanding/design generation in the supported path, no GUI backup, no
installable SDK or HTTP client, no OpenAPI document (the supported factory sets
`openapi_url=None`), and no service-client bearer routes. Progress per task is tracked in
`specs/001-autonomous-release/tasks.md`.
