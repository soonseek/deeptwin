# ADR-014 independent-review input manifest — revision 3

Frozen: `2026-09-08T22:06:56+0900` · Hash: SHA-256 of each file's raw bytes
Status: **frozen revision-3 review input, not a verdict; T086 remains open**

## Supersession and scope

This immutable successor supersedes `adr014-review-input-manifest-r2.md` only as the input set for
the next ADR-014 review. It does not overwrite the frozen revision-1 or revision-2 manifests or their
rejected review history. Revision 1 was rejected on IR-01–05. Revision 2 was rejected on IR2-01–04;
the revision-3 consistency rescan additionally exposed and corrected the missing rollback-retention
release path inside IR2-01. A new independent reviewer must verify every digest below before analysis
and write a separate `adr014-independent-review-r3.md`.

This manifest excludes itself and every independent-review output, including the future revision-3
review file, so no self-hash or verdict-input cycle exists. Any input-byte change invalidates this
snapshot and requires an explicitly superseding manifest; these hashes must never be edited in place.
The input set includes both earlier frozen manifests as historical evidence.

The scope covers the self-hostable web-based open-source framework target, reusable server core,
bundled official browser control surface/reference client, external deployment boundary, semantic
extension ports, durable installation/qualification/binding/rollback-retention/retirement lifecycle,
extension-author SDK and HTTP/OpenAPI client, recursive reusable-core boundary and legal-readiness
wording. Hashing these documents implements no schema, route, package, extension, service, image or
test; qualifies no runtime effect or user experience; grants no license; and authorizes no
publication.

## Frozen files

| Path | SHA-256 |
| --- | --- |
| `README.md` | `37e4a925a7aea4091aba2e6c0a77c6c2cc7b6dd2efaf05b19d5f15354537dd51` |
| `app/README.md` | `9f0688ad4698bd15d867cda71290cd751b32d71937e975d3dd1d80b85c90ae4d` |
| `.specify/memory/constitution.md` | `6709456b75a8b8d3494ae2f10526cf86e4fec3fcdd1212197fbe54aa000ef308` |
| `sdk/python/README.md` | `ec1b88f8ff79787c607d5babd4ed33f5a2837271828c8f1f4b64ee0c361dc2f7` |
| `examples/extensions/README.md` | `49c04dcfe4992a21410856e114e9922140bffa4a2a21ba12d5ddea6bd20d2b7c` |
| `specs/001-autonomous-release/spec.md` | `4be8557072748066722d5fdde5c48b2436a5e7050fd366cd61934b8553163df3` |
| `specs/001-autonomous-release/plan.md` | `a21b6166553c0f76da40f5c1ae1f65a1116e0abda83aec29fa0027e40aadb0ee` |
| `specs/001-autonomous-release/decisions.md` | `7ec720eb0961f2f62915cc02ba8de750f14bcb8280a29d43ef95e7a130d64957` |
| `specs/001-autonomous-release/research.md` | `2403899f2a5a981e8b8e5335c89223dfd4a259b8e755637ba1498ad2c12a5303` |
| `specs/001-autonomous-release/provider-research.md` | `b754cc8cb237b12b122ee2bf5d02c2e7fc0c6e2d36ae46bd42775c6d573b5805` |
| `specs/001-autonomous-release/packaging-research.md` | `434d2c8b643eb6b49de34ad57fcae7a03bb4e1e70fc25ad3ab19e3c8c3487ae8` |
| `specs/001-autonomous-release/sandbox-research.md` | `4000900351390ded50de4cca1b9a4273a1c856e2f1d9fd02ac5752b5f86c1ce8` |
| `specs/001-autonomous-release/data-model.md` | `a1af136ee0a9fea1446d14f7d0573824ddaff23dd834e957d28ccc482c65d621` |
| `specs/001-autonomous-release/quickstart.md` | `c66811f17b3773bbe7df9c466c8b9495147607ed40b472687e81a575d62529c9` |
| `specs/001-autonomous-release/source-traceability.md` | `2a17ec054f9efd769804581fd6a4890fa52eb8dacabce1f08a94c63b47a96217` |
| `specs/001-autonomous-release/tasks.md` | `4d1e9ba936825b7f5f9305d923bbcd917114d746071f9b9e40c40ee5141aaf09` |
| `specs/001-autonomous-release/progress.md` | `aad269967cf12346d4e5ef0a84ab59abab9d6298a7064781e117ba91b7a27fcd` |
| `specs/001-autonomous-release/contracts/api.md` | `3391de569b4b9e27050c5789635308e185db5bbaa42e23911b3224de1f39b6a4` |
| `specs/001-autonomous-release/contracts/experience.md` | `a8a3ffaa2827224287d32d837c1d953154017203d6f457ff15990f675b8f5e5d` |
| `specs/001-autonomous-release/contracts/growth.md` | `0b579504cd37cbbd41d1218592643013663371d6fb4efe888237183f2be3e885` |
| `specs/001-autonomous-release/contracts/operations.md` | `1ad6d64395002059f49e2d9c1068aa03b4551b9eb9f126ede746c229bff37ac0` |
| `specs/001-autonomous-release/contracts/runtime.md` | `b1d0a07bdf9e0d5ba0a9fcc67ff5ffb25eb07b5de4119346c67a89897ccc3fea` |
| `specs/001-autonomous-release/contracts/extension-ports.md` | `3a5289c1cf90f89ba5779384f8e2cf2226d6f9cd22983997c7b0334ebb64caa9` |
| `specs/001-autonomous-release/contracts/verification.md` | `a8da7f30a9093e412a014b5bd0d55e519e23682f78b208ad1a21051801e8ad2e` |
| `specs/001-autonomous-release/checklists/requirements.md` | `2e5c0211761bc34c708e8cfd93f5a69665b3bce1b12c0aed90d1dd612f309e58` |
| `specs/001-autonomous-release/evidence/extension-spi-pure-contracts.md` | `1ee85c3a550c7e6949b391f86ad1a16fc7e8aaebe00b0a9c3d5f85b1c3c16c01` |
| `specs/001-autonomous-release/evidence/extension-framework-design-remediation.md` | `4bb79882b89259e7f93bf60e7c624d23739d1a88d8de538f155c6b4ac5e0f027` |
| `specs/001-autonomous-release/evidence/web-framework-design-review.md` | `7a2a6b8fdc20d95c4b2575193e8026a1ac82bd24bf22bafa2de760d22906f21a` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest.md` | `514e279f6b3db9672f31d373d78316a8470a98287d51d67f58c5101a6b6dd15f` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r2.md` | `ffeba2ba0014ce13065cb2ea0d6ebda28a1ceabdbdc3882b03e40d13ccbd70ae` |

## Required independent-review gates

The reviewer must report digest match/mismatch first, then independently decide all of the following:

1. X01–X06 remain closed without collapsing the reusable framework core into the bundled browser
   application or transferring deployment authority into the product.
2. IR-01 stable binding-slot and core capability-selector identity allows different same-port slots
   to coexist and confines competition, supersession, rollback and stale-head handling to one exact
   five-part key.
3. IR-02/IR2-01 define four exact deployment request/result arms with one precondition truth, exact
   request/result identity equality and acyclic existing-input→request→receipt→postcondition→record/
   head→consumption/event order. A→B→release every A rollback-retention→retire A must preserve B's
   binding/installation heads and dispatch, advance only A's retirement head and reject A rollback.
4. Immutable binding history is not rollback authority. Supersession/disable creates an exact
   target-binding-keyed `retained` head, rollback consumes it, and the closed owner release command/
   result/event preserves history/current heads while advancing only `retained→released`. Current,
   cross-slot, stale, repeated or mismatched release and released-target rollback fail closed.
5. Current uninstall is separately reachable: in a slot with no active-environment refs, B disable→
   release B retention→dependency zero→uninstall→exact tombstone→next-revision C stage/qualification/
   binding/dispatch succeeds without reviving A/B.
6. IR-03/IR2-02 mechanically derive 44 core-owned schema artifacts and evaluate all 208 operation×
   candidate-terminal pairs exactly once, emitting 127 allowed and rejecting 81. Every allowed
   non-success result, including cancelled codec, has `artifacts=[]`; successful empty/variable/
   exact-one ref, role, count and byte constraints cannot be widened by an extension.
7. IR-04 recursively scans `app/extensions/**` with all reusable-core roots and rejects direct or
   indirect API/static/server/FastAPI/Starlette/Jinja and resolvable dynamic-import bypasses.
8. IR-05/IR2-03 assigns T025 the durable common ServiceClient authority, frozen first-party router-
   composition seam and sole `app/server.py` call. T087 owns only the fixed extension route module/
   descriptor, extension-specific client methods and real-server parity without editing T025 files.
9. IR2-04 runs actual bearer client parity only over portable HTTPS. HTTP loopback sends no real
   bearer and proves route non-registration or pre-parser denial with a fixed non-secret canary and no
   cookie/plaintext fallback.
10. Executable extensions remain externally operator-staged digest-pinned OCI services; browser/core
    authority cannot download runtime code, control Docker/containers, create dynamic/host mounts or
    rebuild the core. Code-free definition import remains bounded and owner-authorized.
11. The extension-author SDK and HTTP/OpenAPI client are separate installable distributions, and the
    client parity process cannot import `app` while talking to the actual composed server.
12. The repository remains only an open-source target: no root project license currently grants
    redistribution, and T084 still requires explicit copyright-owner approval.

Only a new independent no-P1/P2 verdict in the separate revision-3 review file may support checking
T086. T087, T078, T079, T081–T084 and every implementation, runtime, effect, distribution and human-
acceptance gate remain independently open.
