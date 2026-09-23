# Product and integration surface boundaries (draft)

Date: 2026-09-23 · Status: **draft for T084**. Sources: `README.md` ("제품 경계"),
`.specify/memory/constitution.md` principle II, ADR-009 and ADR-014 in
`specs/001-autonomous-release/decisions.md`, `contracts/api.md`, `contracts/operations.md` §2.2
and §8, `deploy/compose.yaml`.

T084 requires four surfaces to be documented and kept apart, plus three separately distributed
integration boundaries. "Not yet provided" means the thing is specified but does not exist in the
repository in usable form.

## Summary

| # | Surface | Who uses it | Is it the product? | Exists today |
| --- | --- | --- | --- | --- |
| 1 | Official browser product / control surface | instance owner (end user) | **yes, the only one** | development preview |
| 2 | External instance deployment / operator tooling | instance operator | no | Compose skeleton, bootstrap helper, locks and verifiers; not runnable |
| 3 | Server-owned internal CLI / worker implementation artifacts | the server itself | no | partially |
| 4 | Optional API / SDK integration | automation authors | no (optional) | browser-session API only; SDK/client not yet provided |
| A | Installable extension-author SDK | extension authors | no | not yet provided |
| B | Installable HTTP/OpenAPI client | automation authors | no | not yet provided |
| C | External operator OCI-extension staging | instance operator | no | specified; not yet provided end to end |

## 1. Official browser product / control surface

- The browser UI served by the instance is the **only** official end-user surface: owner setup and
  login, work intake, run observation, own alternatives, records, export, and (in future) settings
  and extensions.
- Current files: `app/static/start.html`, `work.html`, `records.html`, `observe.html` and their
  modules; served by the supported factory `create_app`. See
  [browser-user-guide.md](browser-user-guide.md).
- Out of scope by decision (ADR-009): native desktop wrappers, embedded WebViews, macOS app bundles
  or DMGs, product launchers and any end-user CLI journey. `packaging/macos/` is historical.
- The legacy `index.html` shell and `create_development_app` are a **development preview**, not a
  product surface.

## 2. External instance deployment / operator tooling

- Docker Engine, Docker Desktop, Compose and Portainer CE are **external deployment authorities**
  operated by the instance operator. They are not DeepTwin screens, and Portainer holds
  host-administrator power over Docker.
- DeepTwin artifacts for this surface: `deploy/compose.yaml` (skeleton,
  `candidate_not_runtime_qualified`), `deploy/bootstrap/index.html` (offline first-setup helper),
  `deploy/locks/` and `deploy/manifests/` (pinned build inputs), `deploy/security/` (recipes,
  seccomp) and `deploy/tests/` (verifiers and canaries).
- The product side of the boundary is the `deployment-prepare-v1` API: the product prepares an exact
  request and later verifies a signed receipt; it never performs the deployment.
- Operator commands never become an end-user requirement. See
  [operator-deployment-backup-guide.md](operator-deployment-backup-guide.md).

## 3. Server-owned internal CLI / worker implementation artifacts

These run inside the deployment on the server's behalf. Users never invoke them.

| Artifact | Role | State |
| --- | --- | --- |
| `python -m app.server` with `--data-dir … --expected-gid` | control-plane process entrypoint, fed by the deployment | implemented; container entrypoint on `control:8080` still an open gate |
| Init jobs (`state-root-init`, `ipc-root-init`, session/vault/backup-key/deployment-receipt root init) | one-shot deployment jobs | code in `app/operations/`, `app/workers/ipc_root.py`; only two declared in Compose |
| Isolated workers (provider gateway, fetch broker, browser, document, speech, evaluation, runtime-extension, backup) | typed, broker-mediated execution | partial; several not connected to the supported server |
| Managed Codex runner (Codex CLI inside the `codex` service) | server-owned provider runner | build inputs locked (`deploy/manifests/codex-0.153.4.json`); not qualified |
| age / age-keygen | backup encryption, reached only through `app/workers/backup_crypto.py` | implemented in-process; separate networkless service not yet provided |

The Codex CLI and other tools here are implementation means. Using DeepTwin never requires the user
to open a provider app or CLI.

## 4. Optional API / SDK integration

- Today the `/api/v1` routes accept only the owner's **browser session** (cookie + CSRF). They exist
  to serve the browser UI. See [api-compatibility.md](api-compatibility.md).
- Target: scoped `ServiceClient` bearer credentials created by the owner in the browser, usable
  only over the portable HTTPS profile, plus an OpenAPI document. **Not yet provided**: no
  service-client routes are mounted and OpenAPI is disabled.
- This surface is optional. Nothing in the ordinary user workflow depends on it, and it does not make
  a CLI part of that workflow.

## A. Installable extension-author SDK

- Target: a separately installable, independently versioned `deeptwin_ext` distribution for
  manifests, permitted refinements and read-only, digest-equal bindings to the core-owned
  `extension-ports-v1` schemas. It never authors or registers a core port.
- **Not yet provided.** `sdk/python/deeptwin_ext/` is a historical, dependency-free source checkpoint
  with no packaging metadata (its README says so).
- See [extension-authoring.md](extension-authoring.md).

## B. Installable HTTP/OpenAPI client

- Target: a separately installable `deeptwin_client` that imports no `app` module and proves parity
  with browser commands (same durable revisions, authority decisions, receipts and event order)
  against the real HTTPS server (T087, repeated on the final distribution in T083).
- **Not yet provided.**

## C. External operator OCI-extension staging boundary

- Executable third-party extensions run only as OCI services that the **operator** creates from an
  exact `ExtensionServiceDescriptor` (digest-pinned index and per-platform manifests, declared
  sockets and named volumes only) and confirms with a signed receipt.
- The product may register inert candidates (`/api/v1/extensions/candidates`), verify receipts,
  handshakes and qualification, and bind/disable/roll back already-qualified revisions. It never
  downloads code or images, uses a Docker socket, manages container lifecycle, adds host-path or
  post-start mounts, or rebuilds the core image.
- Third-party extensions and the private T087 conformance fixture are never baked into the core
  release lock.
- **State:** candidate registration exists; staging requests/receipts for extensions, qualification,
  binding and `Settings > Extensions` are not yet provided end to end.

## Licensing, NOTICE and source-offer closure per surface

T084 requires each distributable surface to carry its own licence, NOTICE and (where required)
source-offer closure. None of this exists yet, and **nothing may be published before the copyright
owner explicitly approves the repository licence**.

| Surface / distribution | What would ship | Closure status |
| --- | --- | --- |
| 1 + 3 (core images) | control plane, workers, browser assets, locked third-party components | inventory drafted ([third-party-notices.md](third-party-notices.md)); NOTICE/LICENSES/source offers not assembled; images do not exist |
| 2 (operator artifacts) | Compose file, bootstrap helper, verifiers | covered by the repository licence once chosen |
| A (SDK) | `deeptwin_ext` package | not yet provided; licence to follow the owner's decision |
| B (client) | `deeptwin_client` package | not yet provided; licence to follow the owner's decision |
| C (third-party extensions) | author-supplied images | each author's own licence, recorded as unverified metadata |

## Verification status

The boundary statements above are checked against the code only by reading it for this draft. The
automated checks that bear on them are limited to existing tests such as route-count and composition
tests and `deploy/tests/test_compose_topology.py`. Verification of the boundary on real hosts (T083)
has not been performed.
