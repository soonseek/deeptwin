# T018-C — static self-hosted isolation-topology skeleton

Date: 2026-09-08  
Status: statically verified design checkpoint; **not runtime-qualified and T018 remains open**

## Product and evidence boundary

The target DeepTwin release is a **self-hostable, web-based, open-source multi-agent framework**;
the current repository has no approved project license. Its bundled browser
UI is the supported end-user product/control surface and the first-owner setup entrypoint.
`deploy/compose.yaml` is an inspectable external deployment/operator artifact; it is not a native
application, product launcher, ordinary work screen, or end-user CLI.

This checkpoint records only a candidate IPC/network/isolation skeleton. It does not claim that the
current server listens at the required container address, that any final service image exists, that
Docker can start the topology, or that either release profile is supported.

## Statically closed properties

- One data-mount-free edge is the only published service. `local` binds loopback and `portable`
  binds the operator-selected address with external read-only proxy configuration and TLS material.
  Compose cannot enforce their mutual exclusion, so the manifest states that exact-one validation
  remains a deployment gate. Because Compose can interpolate globally declared portable-resource
  variables before profile selection, T081 must also split validated profile descriptors/overrides
  or qualify one full-resource model before the local profile can be supported.
- Control has only the internal edge network. Provider, fetch and Codex have separate egress
  networks. Browser, document, speech, evaluation, runtime-extension and backup declare no network.
- Long-running services use distinct fixed non-root UID/GID identities, drop all capabilities,
  deny privilege escalation, use read-only roots and bounded CPU, memory, process, file-descriptor
  and `noexec,nosuid,nodev` scratch limits. Browser uses the exact locked seccomp input and never
  requests `--no-sandbox`, `SYS_ADMIN`, a Docker socket or an unconfined profile.
- Every IPC pair has one responder-owned setgid `02710` root, a distinct supplemental pair GID, a
  responder-owned `0660` socket contract and a 32-byte root/pair-readable `0640` secret that must be
  generated or overwritten each boot. Requesters mount their pair volume read-only; responders and
  the one-shot initializer are the only writers.
- `deeptwin-state`, `codex-auth` and `backup-output` are separate persistent volumes with `nocopy`.
  A networkless one-shot initializer owns only those roots. Control cannot mount Codex auth or
  backup output; Codex cannot mount work state; backup cannot mount work state or Codex auth.
- The portable edge alone receives the external pinned proxy configuration and operator TLS
  certificate/key surfaces. Backup alone receives a public recipient input and output volume; no
  private restore identity is declared at runtime.
- The manifest explicitly requires the future control listener `http://control:8080` and explicitly
  records that current `app.server` loopback behavior does not satisfy it.

## Verification

```text
python -m pytest -q deploy/tests/test_compose_topology.py \
  deploy/tests/test_worker_boundary.py
75 passed, 1 skipped, 21 subtests passed

python -m pytest -q deploy/tests
298 passed, 1 skipped, 369 subtests passed in 38.08s

python -m pytest -q app/tests
2255 passed, 1 skipped, 1 dependency deprecation warning in 73.54s

Ruff, Python compileall and git diff --check
PASS
```

The skipped worker-boundary case is the real Linux distinct-UID `SO_PEERCRED` path, which this
macOS development host cannot qualify. No Docker daemon, external network, paid model, live
provider account, user credential or publication action was used.

## Independent adversarial review

The first independent audit rejected the test oracle because it accepted dangerous mutations even
though the checked-in manifest itself was clean. The repaired oracle now rejects alternate
`volumes_from` mounts, an Engine API socket, host devices/user namespaces, non-loopback local
publishing, shared/external egress networks, swapped service images, effectively unbounded memory
and weakened restart policy. Exact top-level/service key allowlists also block unreviewed Compose
authority surfaces. All eleven reproduced bypasses now fail closed; the final audit found **no
remaining P1/P2 issue in this deliberately static scope**.

## Explicitly open work

The following remain mandatory empirical or implementation gates:

- T025's durable first-owner/session/Origin/CSRF authority and a control entrypoint that actually
  owns `/var/lib/deeptwin` and listens on the internal target;
- exact-one profile validation and digest verification for portable config/TLS before startup;
- final `@sha256` service image value validation, implementation of both initializer contracts,
  health/readiness ordering, crash/restart behavior and suitability of every declared tmpfs;
- real Linux UID/GID, mount, secret rotation and `SO_PEERCRED` qualification;
- non-root Chromium userns+sandbox runtime proof under the pinned seccomp policy;
- Codex device-auth lifecycle, provider/session credential vaults, backup archive streaming,
  atomic output, restore identity, restore verification and recovery/update behavior;
- amd64 and arm64 integrated runs, both deployment profiles and clean supported-host evidence.

Static shape tests cannot close any of those gates.

## SHA-256

```text
946ea5a1640be5b6536f3b06bc183a058fc8ceb1bdc1174c7f1cb1f4ba546daf  deploy/compose.yaml
8878c8683ef98daaaf9f296767581084d87969111e36d18a61bb70a8e3eff22a  deploy/security/browser-seccomp.json
020a31b4bd307c5e1087b8b20f9c9f995ba607226d0520a2f730d0f08a413eff  deploy/security/service-ids.json
5a9f34bc25b2d7a559e954f01078a9207bdd7c2f38311be6011b917a6c00fe0e  deploy/tests/test_compose_topology.py
```
