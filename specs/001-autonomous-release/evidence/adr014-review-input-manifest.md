# ADR-014 independent-review input manifest

Frozen: `2026-09-08T20:10:05+0900` · Hash: SHA-256 of each file's raw bytes  
Status: **frozen review input, not a review verdict; T086 remains open**

## Scope and use

This manifest identifies the exact documentation bytes prepared for the independent post-ADR-014
T086 review. The reviewer must verify every digest before analysis and record the verdict separately
in `adr014-independent-review.md`. This manifest excludes itself and that future output, avoiding a
self-hash/review-output cycle. Any input edit invalidates this revision and requires a new immutable
successor manifest before review; do not overwrite this list and claim it covered changed bytes.

The input includes the framework identity, canonical Spec Kit artifacts/contracts, legal-readiness
wording, historical extension checkpoint and its corrective ledger. It deliberately does not treat
source code/tests as design completion: T087 owns implementation and staged R16 evidence, while T083
owns final two-clean-host V8 repetition. No product test, extension, image, deployment, effect,
license approval or publication is claimed by freezing these hashes.

## Frozen files

| Path | SHA-256 |
| --- | --- |
| `README.md` | `37e4a925a7aea4091aba2e6c0a77c6c2cc7b6dd2efaf05b19d5f15354537dd51` |
| `app/README.md` | `9f0688ad4698bd15d867cda71290cd751b32d71937e975d3dd1d80b85c90ae4d` |
| `.specify/memory/constitution.md` | `6709456b75a8b8d3494ae2f10526cf86e4fec3fcdd1212197fbe54aa000ef308` |
| `sdk/python/README.md` | `a7629633a7224e268b9eb8270dc3dfe9b1052a6dc6d0c48bac3b850a055c970f` |
| `examples/extensions/README.md` | `49c04dcfe4992a21410856e114e9922140bffa4a2a21ba12d5ddea6bd20d2b7c` |
| `specs/001-autonomous-release/spec.md` | `607e9de9b0efb9055d356f29904ff0e5049854305e93ce208d18d3138a25410d` |
| `specs/001-autonomous-release/plan.md` | `6bf6778520e8e89721078615aaa1a34921822ed9dba0fdc805242f1575ac19b2` |
| `specs/001-autonomous-release/decisions.md` | `85823681cb4457e80b2a4faec9c5b3b5080b29e2f7b80dd20cff084e7aa588df` |
| `specs/001-autonomous-release/research.md` | `077d80a077352f88f6f3be91481f6765bf882f4d3cd185225f8bb320e2350a26` |
| `specs/001-autonomous-release/provider-research.md` | `b754cc8cb237b12b122ee2bf5d02c2e7fc0c6e2d36ae46bd42775c6d573b5805` |
| `specs/001-autonomous-release/packaging-research.md` | `434d2c8b643eb6b49de34ad57fcae7a03bb4e1e70fc25ad3ab19e3c8c3487ae8` |
| `specs/001-autonomous-release/sandbox-research.md` | `4000900351390ded50de4cca1b9a4273a1c856e2f1d9fd02ac5752b5f86c1ce8` |
| `specs/001-autonomous-release/data-model.md` | `35723f0441869fea0729a3ead674a1306fb6143a41046b2d2da1af4b7defe839` |
| `specs/001-autonomous-release/quickstart.md` | `3f99d7af4a7fa8bc607ddb51ad1593ee42f9252ba8090b65f82348fa5ad70715` |
| `specs/001-autonomous-release/source-traceability.md` | `c1c08f55e9ec167aae93a965833070f69be38a7bc0aee067713c1282c8dcc162` |
| `specs/001-autonomous-release/tasks.md` | `88503194d89733e968a58101854aa310be6de38e8300eebeae4bc8a0e69a1bc0` |
| `specs/001-autonomous-release/progress.md` | `3abeb271f6834238cd921546f80e4f22d2322693cc2894bf6eb1ae148ae40222` |
| `specs/001-autonomous-release/contracts/api.md` | `006dffa7f6d24e9d959483be1f6b0876cc6384a600ef6503e549e94082209779` |
| `specs/001-autonomous-release/contracts/experience.md` | `2ca9c034a93f18a943dbb351e12d6c290ee69af7a54764adca129fb643dbc615` |
| `specs/001-autonomous-release/contracts/growth.md` | `0b579504cd37cbbd41d1218592643013663371d6fb4efe888237183f2be3e885` |
| `specs/001-autonomous-release/contracts/operations.md` | `4c188ef14ad359c5d31156dadd4fb89f4c52379e6bba505a5d42fd9fb13fbef5` |
| `specs/001-autonomous-release/contracts/runtime.md` | `70606e758f66941622d883cdf2307f4f7bf6e05a3c59cc6e7d05246cc07e1aad` |
| `specs/001-autonomous-release/contracts/verification.md` | `2944656b37e6f948c3ab520f822ac81923c5b514aff9967f899e05289feadaac` |
| `specs/001-autonomous-release/checklists/requirements.md` | `a565ae03af23b7b2ae2b9946dcead309fa16e086d1adf0ea24fd64d4e2bcd305` |
| `specs/001-autonomous-release/evidence/extension-spi-pure-contracts.md` | `a9932c77eec9beabd7dc92f78008f3a13eb9de77758207443a65ec7d0ef0076a` |
| `specs/001-autonomous-release/evidence/extension-framework-design-remediation.md` | `4433d0654ad842af7559ba990ff40cf1119db1348f63b7a67a8243c045502276` |
| `specs/001-autonomous-release/evidence/web-framework-design-review.md` | `056cc7100db755d2980ede08a016aa456cd9346881d86aedb716808055fd41d5` |

## Gate boundary

The reviewer must first report digest match/mismatch, then assess all six X01–X06 findings and the
secondary tagged-union, digest-direction, managed-runner-port, keyed-head, non-destructive replace,
mount, multi-platform and supply-chain distinctions. Only an independent no-P1/P2 result recorded in
the separate review file may support checking T086. T087, T078, T079, T081–T084, implementation,
runtime/effect evidence, legal open-source status and creator acceptance remain separately open.
