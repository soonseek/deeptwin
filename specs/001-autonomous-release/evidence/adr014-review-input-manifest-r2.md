# ADR-014 independent-review input manifest — revision 2

Frozen: `2026-09-08T21:03:12+0900` · Hash: SHA-256 of each file's raw bytes
Status: **frozen revision-2 review input, not a verdict; T086 remains open**

## Supersession and scope

This immutable successor supersedes `adr014-review-input-manifest.md` only as the input set for the
next ADR-014 review. It does not overwrite or invalidate that frozen revision-1 history. The first
independent review rejected revision 1 on IR-01–05; the corrective ledger preserves that disposition.
A new independent reviewer must verify every digest below before analysis and write a separate
`adr014-independent-review-r2.md`. This manifest excludes itself and that future review output, so no
self-hash or review-output cycle exists. Any change to an input below invalidates this snapshot and
requires another explicitly superseding manifest rather than an in-place hash edit.

The input set covers the self-hostable web framework identity, bundled official browser control
surface, external deployment boundary, semantic extension ports, durable extension lifecycle,
extension-author SDK/HTTP client design, recursive reusable-core boundary and legal-readiness wording.
It also includes the frozen revision-1 manifest as historical evidence. Hashing documentation does
not implement a schema, route, client, extension, service, image or test; does not qualify a runtime
effect or user experience; and does not grant a license or authorize publication.

## Frozen files

| Path | SHA-256 |
| --- | --- |
| `README.md` | `37e4a925a7aea4091aba2e6c0a77c6c2cc7b6dd2efaf05b19d5f15354537dd51` |
| `app/README.md` | `9f0688ad4698bd15d867cda71290cd751b32d71937e975d3dd1d80b85c90ae4d` |
| `.specify/memory/constitution.md` | `6709456b75a8b8d3494ae2f10526cf86e4fec3fcdd1212197fbe54aa000ef308` |
| `sdk/python/README.md` | `ec1b88f8ff79787c607d5babd4ed33f5a2837271828c8f1f4b64ee0c361dc2f7` |
| `examples/extensions/README.md` | `49c04dcfe4992a21410856e114e9922140bffa4a2a21ba12d5ddea6bd20d2b7c` |
| `specs/001-autonomous-release/spec.md` | `ebb12587862556fee48d7632aabf38015a2e8d3124f4f5266c8946047f77ee22` |
| `specs/001-autonomous-release/plan.md` | `9c1060af8781974c9da345882d7b8ad9675e2d17ab4f04fb4feb9f3dad078b29` |
| `specs/001-autonomous-release/decisions.md` | `91d71436907b3f9c5b713e5833e1f773d79a20dd433c9424d6fb5ac576176833` |
| `specs/001-autonomous-release/research.md` | `7b00211deb7ef9223dce0a35f8677a62e4ac08b252fde6cb626a2de48b73606a` |
| `specs/001-autonomous-release/provider-research.md` | `b754cc8cb237b12b122ee2bf5d02c2e7fc0c6e2d36ae46bd42775c6d573b5805` |
| `specs/001-autonomous-release/packaging-research.md` | `434d2c8b643eb6b49de34ad57fcae7a03bb4e1e70fc25ad3ab19e3c8c3487ae8` |
| `specs/001-autonomous-release/sandbox-research.md` | `4000900351390ded50de4cca1b9a4273a1c856e2f1d9fd02ac5752b5f86c1ce8` |
| `specs/001-autonomous-release/data-model.md` | `2eca66faa36703c8eb80f93e4f51649376df60619816203a38d289f0270bc00e` |
| `specs/001-autonomous-release/quickstart.md` | `3f99d7af4a7fa8bc607ddb51ad1593ee42f9252ba8090b65f82348fa5ad70715` |
| `specs/001-autonomous-release/source-traceability.md` | `17da2daffcd2d250bb9bb2023f4c655d7e46ceb6e877582b7261c19d0be6c322` |
| `specs/001-autonomous-release/tasks.md` | `4fd107c461de8a4603970ca3de04c63911d4cd91eff3b028451ce02dbb468096` |
| `specs/001-autonomous-release/progress.md` | `e4a494f8a315ef0f4b5d87f77809ba1225c2e4c481f3a95b7ed3f9c94cfaf57c` |
| `specs/001-autonomous-release/contracts/api.md` | `da3492195e7a25c656a17630d54ccc3f905eebf70947a561405b51436804b894` |
| `specs/001-autonomous-release/contracts/experience.md` | `8b62504f94abeae246099db072132becbebfee97928d26ad489ac678082d8d2d` |
| `specs/001-autonomous-release/contracts/growth.md` | `0b579504cd37cbbd41d1218592643013663371d6fb4efe888237183f2be3e885` |
| `specs/001-autonomous-release/contracts/operations.md` | `c56acfa43c48e3644ee52297760c2cdb47468fb651c71159fe61091bda11bd36` |
| `specs/001-autonomous-release/contracts/runtime.md` | `0abd9fb9da8547c765be996c41c80e18f3d859e486b456f01c5c5277c125902c` |
| `specs/001-autonomous-release/contracts/extension-ports.md` | `657e045636cbc05e5b5de8fe5e41093153437a432fa133e6778c9d3b7bc0e240` |
| `specs/001-autonomous-release/contracts/verification.md` | `84f329891695dafe3a955ac2dc94c95f8c603a3f72da622a8198f98d96f8a490` |
| `specs/001-autonomous-release/checklists/requirements.md` | `d10d443d7d88f07e56495fdf0ca8364f307d18a27895524e7b5253c5500ec538` |
| `specs/001-autonomous-release/evidence/extension-spi-pure-contracts.md` | `83021d97e5f1394b58ee5b50c7cf4006794e94d568e1de3ab40b4fc24fd1b383` |
| `specs/001-autonomous-release/evidence/extension-framework-design-remediation.md` | `aef5eb4ea0127ff1654b6af094c0c19bf5c162f16954370c5ec2184e0bd811a4` |
| `specs/001-autonomous-release/evidence/web-framework-design-review.md` | `dafc982cd19304bb893f683c409d912904e5ac1242e9e3d6b48cf45387ef36af` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest.md` | `514e279f6b3db9672f31d373d78316a8470a98287d51d67f58c5101a6b6dd15f` |

## Required independent-review gates

The reviewer must report digest match/mismatch first, then independently decide all of the following:

1. X01–X06 are closed without collapsing the reusable core into the bundled browser application.
2. IR-01 binding-slot/capability-selector identity permits coexistence and confines competition,
   supersession, rollback and stale-head handling to the exact slot key.
3. IR-02 stage/replace/remove requests and results are separate closed arms; common extension
   `preconditions={}` leaves one arm-owned truth; old/new observations are equality-bound to request
   service/digest tuples; remove failure/unknown cannot substitute an unrelated service; and digest
   causality has no future reference or cycle.
4. IR-03 all eleven ports and 44 config/request/result/error artifacts are mechanically derivable
   from exact types, bounds, nested fields, operation arms, terminal/error/refinement and
   effect/idempotency/cancellation/artifact rules; the author SDK cannot author a core port.
5. IR-04 recursively scans `app/extensions/**` with all reusable-core roots and rejects direct or
   indirect API/static/server/FastAPI/Starlette/Jinja and dynamic-import bypasses.
6. IR-05 gives T025 exact ownership of durable common ServiceClient credentials, TLS bearer
   authentication, scopes/network/rate limits, route mounting/server registration and tests, while
   T087 owns only extension-specific routes/client methods and actual separate-process parity.
7. Executable code remains externally operator-staged as digest-pinned OCI services; product/browser
   authority cannot download code, control Docker/containers, create dynamic mounts or rebuild core.
8. The project is only an open-source target: no repository license currently grants redistribution,
   and T084 still requires explicit copyright-owner approval.

Only a new independent no-P1/P2 verdict in the separate review file may support checking T086.
T087, T078, T079, T081–T084 and every implementation, effect, runtime, distribution and human-
acceptance gate remain independently open.
