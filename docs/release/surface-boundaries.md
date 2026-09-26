# Product and integration surface boundaries (draft)

Date: 2026-09-23 · Updated: 2026-09-25 · Status: **draft for T084**. Sources: `README.md`
("제품 경계"), `.specify/memory/constitution.md` principle II, ADR-009 and ADR-014 in
`specs/001-autonomous-release/decisions.md`, `contracts/api.md`, `contracts/operations.md` §2.2
and §8, `deploy/compose.yaml`, `app/api/assets.py`, `app/api/route_contributions/*.json`.

T084 requires four surfaces to be documented and kept apart, plus three separately distributed
integration boundaries. "Not yet provided" means the thing is specified but does not exist in the
repository in usable form.

## Summary

| # | Surface | Who uses it | Is it the product? | Exists today |
| --- | --- | --- | --- | --- |
| 1 | Official browser product / control surface | instance owner (end user) | **yes, the only one** | development preview (six pages) |
| 2 | External instance deployment / operator tooling | instance operator | no | Compose skeleton, bootstrap helper, locks and verifiers, stopped-control-plane operator tools; not deployable |
| 3 | Server-owned internal CLI / worker implementation artifacts | the server itself | no | control plane and five worker processes; none wired into Compose |
| 4 | Optional API / SDK integration | automation authors | no (optional) | browser-session API only; SDK/client not yet provided |
| A | Installable extension-author SDK | extension authors | no | wheel/sdist build and install (2026-09-26); port-schema bindings not yet provided |
| B | Installable HTTP/OpenAPI client | automation authors | no | wheel/sdist build and install (2026-09-26); no bearer route to call, no parity |
| C | External operator OCI-extension staging | instance operator | no | provider-port path partially implemented; not provided end to end |

## 1. Official browser product / control surface

- The browser UI served by the instance is the **only** official end-user surface: owner setup,
  login and re-setup after an owner recovery; work intake, source readings, work model,
  conversation and design comparison; run observation, approvals, graph, artifacts and own
  alternatives; versions; records, export, backup/restore, retention, account, connections and
  run budgets; settings, browser grants and `Settings > Extensions`.
- Current files: `app/static/start.html`, `work.html`, `observe.html`, `versions.html`,
  `records.html`, `settings.html` and their modules, served from the closed catalogue in
  `app/api/assets.py` by the supported factory `create_app`. See
  [browser-user-guide.md](browser-user-guide.md).
- Where the product depends on the operator (owner recovery, web-release update), the browser only
  **reads** the state (`/health` `recovered`, `GET /api/v1/platform/update`); it has no control or
  file input that becomes deployment authority.
- Out of scope by decision (ADR-009): native desktop wrappers, embedded WebViews, macOS app bundles
  or DMGs, product launchers and any end-user CLI journey. `packaging/macos/` is historical.
- The legacy `index.html` shell and `create_development_app` are a **development preview**, not a
  product surface. The microphone input exists only there (T024 open).
- `app/tests/test_product_wording_t023.py` keeps every served asset free of wording that implies
  the browser's device, a native app or an install launcher is the host.

## 2. External instance deployment / operator tooling

- Docker Engine, Docker Desktop, Compose and Portainer CE are **external deployment authorities**
  operated by the instance operator. They are not DeepTwin screens, and Portainer holds
  host-administrator power over Docker.
- DeepTwin artifacts for this surface: `deploy/compose.yaml` (skeleton,
  `candidate_not_runtime_qualified`), `deploy/bootstrap/index.html` (offline first-setup helper),
  `deploy/locks/` and `deploy/manifests/` (pinned build inputs), `deploy/security/` (service
  identities, recipes, seccomp), `deploy/tests/` (verifiers and canaries), the one-shot init jobs
  and the stopped-control-plane operator tools in `app/operations/` (owner recovery, web-release
  update, update guidance and gate-backup restore).
- The product side of the boundary is the `deployment-prepare-v1` API (the product prepares an
  exact request and later verifies a signed receipt; it never performs the deployment) and the
  read-only `platform-update-v1` guidance. Owner-recovery and update receipts are accepted only by
  the operator tools, from operator-owned files outside the data directory and session root.
- Operator commands never become an end-user requirement and are described only in
  [operator-deployment-backup-guide.md](operator-deployment-backup-guide.md).

## 3. Server-owned internal CLI / worker implementation artifacts

These run inside the deployment on the server's behalf. Users never invoke them.

| Artifact | Role | State |
| --- | --- | --- |
| `python -m app.server` (required deployment inputs plus optional worker attachments) | control-plane process entrypoint, fed by the deployment | implemented; container entrypoint on `control:8080` still an open gate |
| Init jobs (`state-root-init`, `ipc-root-init`, session/vault/backup-key/deployment-receipt/provider-source/release-source root init) | one-shot deployment jobs | code in `app/operations/`, `app/workers/ipc_root.py`; only two declared in Compose |
| Credential gateway, document worker, backup-crypto worker, browser worker, fetch service (`app/workers/*_main.py`) | typed, pair-authenticated execution under fixed identities | implemented and tested on test-owned pair roots; no Compose `command`, image or mounts yet (T081) |
| Speech, evaluation and runtime-extension workers | isolated workers | not connected to the supported server |
| Managed Codex runner (Codex CLI inside the `codex` service) | server-owned provider runner | build inputs locked (`deploy/manifests/codex-0.153.4.json`); runner not implemented (T088) |
| age / age-keygen | backup encryption, reached only through the networkless backup-crypto worker | implemented; its Compose service has no image yet |

The Codex CLI and other tools here are implementation means. Using DeepTwin never requires the user
to open a provider app or CLI.

## 4. Optional API / SDK integration

- Today the 128 `/api/v1` routes accept only the owner's **browser session** (cookie + CSRF). They
  exist to serve the browser UI. See [api-compatibility.md](api-compatibility.md).
- Target: scoped `ServiceClient` bearer credentials created by the owner in the browser, usable
  only over the portable HTTPS profile, plus an OpenAPI document. **Not yet provided**: no
  service-client routes are mounted and OpenAPI is disabled.
- This surface is optional. Nothing in the ordinary user workflow depends on it, and it does not make
  a CLI part of that workflow.

## A. Installable extension-author SDK

- Target: a separately installable, independently versioned `deeptwin_ext` distribution for
  manifests, permitted refinements and read-only, digest-equal bindings to the core-owned
  `extension-ports-v1` schemas. It never authors or registers a core port.
- **Partly provided (2026-09-26).** `sdk/python/deeptwin_ext/` is now its own PEP 517 package root
  (`deeptwin-ext` 0.1.0, wheel and sdist, installed and tested in a fresh venv). It still ships only
  the historical manifest/worker-message helpers: no port-schema bindings or refinements yet.
- See [extension-authoring.md](extension-authoring.md).

## B. Installable HTTP/OpenAPI client

- Target: a separately installable `deeptwin_client` that imports no `app` module and proves parity
  with browser commands (same durable revisions, authority decisions, receipts and event order)
  against the real HTTPS server (T087, repeated on the final distribution in T083).
- **Partly provided (2026-09-26).** `sdk/python/deeptwin_client/` builds `deeptwin-client` 0.1.0
  (wheel and sdist). Installed in a fresh venv that cannot import `app`, it reaches the real
  TLS server's mounted routes, but no route admits a service-client bearer yet (T025), so there
  is no parity proof.

## C. External operator OCI-extension staging boundary

- Executable third-party extensions run only as OCI services that the **operator** creates from an
  exact `ExtensionServiceDescriptor` (digest-pinned index and per-platform manifests, declared
  sockets and named volumes only) and confirms with a signed receipt.
- The product may register and list inert candidates, prepare a provider staging request and
  import its signed receipt (`deployment-prepare-v1` provider requests), record the operator-staged
  installation as verified, run conformance, seal the provider-transport qualification, and bind,
  disable, roll back or release rollback retention of already-qualified revisions. It never
  downloads code or images, uses a Docker socket, manages container lifecycle, adds host-path or
  post-start mounts, or rebuilds the core image.
- Third-party extensions and the private T087 conformance fixture are never baked into the core
  release lock.
- **State:** the path above exists for `provider-port-v1` only and is exercised with synthetic,
  test-owned release trees; `Settings > Extensions` shows it and marks what the server does not
  supply. Other ports, qualification records for them, code-free definition import, uninstall/
  replace, and the dispatch path reading binding heads are not yet provided (T087).

## Licensing, NOTICE and source-offer closure per surface

The repository is Apache-2.0 (owner-approved 2026-09-24; `LICENSE`, `NOTICE`, `REUSE.toml`). T084
requires each distributable surface to carry its own licence, NOTICE and (where required)
source-offer closure. Nothing is published by this repository's automation; publication needs its
own authority.

| Surface / distribution | What would ship | Closure status |
| --- | --- | --- |
| 1 + 3 (core images) | control plane, workers, browser assets, locked third-party components | inventory drafted ([third-party-notices.md](third-party-notices.md)); per-image NOTICE/licence texts and source offers not assembled; images do not exist (T081/T082) |
| 2 (operator artifacts) | Compose file, bootstrap helper, verifiers, operator tools | Apache-2.0 via the repository licence; upstream files under `deploy/locks/licenses/` keep upstream terms |
| A (SDK) | `deeptwin_ext` package | package root and artifacts build; not released |
| B (client) | `deeptwin_client` package | package root and artifacts build; not released |
| C (third-party extensions) | author-supplied images | each author's own licence, recorded as unverified metadata |

## Verification status

The boundary statements above are checked against the code only by reading it for this draft. The
automated checks that bear on them are limited to existing tests such as route-count and composition
tests (`app/tests/test_router_composition.py`), the served-asset wording guard
(`test_product_wording_t023.py`), the update-tooling tests that refuse browser-uploaded receipts
(`test_update_recovery.py`) and `deploy/tests/test_compose_topology.py`. Verification of the
boundary on real hosts (T083) has not been performed.
