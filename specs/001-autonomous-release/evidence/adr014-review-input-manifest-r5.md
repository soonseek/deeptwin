# ADR-014 independent-review input manifest — revision 5

Frozen: `2026-09-08T23:12:00+0900` · Hash: SHA-256 of each file's raw bytes
Status: **frozen revision-5 review input, not a verdict; T086 remains open**

## Supersession and scope

This immutable successor supersedes revision 4 only as the next ADR-014 review input. It does not
rewrite revisions 1–4 or any rejection. The revision-4 review found no P1 but rejected three P2 gaps:
export-sink lacked a byte-bearing request path, result artifact metadata was not field-complete, and
terminal/result/error effect truth was contradictory. Revision 5 freezes the exact export snapshot/
prepared lists over bounded IPC, the 11/41 request split, closed result role/media/omissions/ref
metadata, and one exhaustive `result.effect` truth. It also clarifies T018-foundation versus
T018-final without creating a task or moving T083's two-clean-host responsibility.

This manifest excludes itself and every review verdict, so it has no self-hash or verdict-input
cycle. It includes the frozen r4 manifest only as immutable supersession history. Any input-byte
change requires a new explicitly superseding manifest. The T018-B2 evidence is included only to
support current-status wording; it does not close T018. No entry implements or qualifies a port,
schema, extension, worker, distribution or UI. The repository remains an open-source target without
a project license; T084 and copyright-owner approval remain mandatory before legal open-source
publication or redistribution is claimed.

## Frozen files

| Path | SHA-256 |
| --- | --- |
| `README.md` | `37e4a925a7aea4091aba2e6c0a77c6c2cc7b6dd2efaf05b19d5f15354537dd51` |
| `app/README.md` | `9f0688ad4698bd15d867cda71290cd751b32d71937e975d3dd1d80b85c90ae4d` |
| `.specify/memory/constitution.md` | `6709456b75a8b8d3494ae2f10526cf86e4fec3fcdd1212197fbe54aa000ef308` |
| `sdk/python/README.md` | `ec1b88f8ff79787c607d5babd4ed33f5a2837271828c8f1f4b64ee0c361dc2f7` |
| `examples/extensions/README.md` | `49c04dcfe4992a21410856e114e9922140bffa4a2a21ba12d5ddea6bd20d2b7c` |
| `specs/001-autonomous-release/spec.md` | `4b57c3fe6df786aa65d0459c82f74ffef0c33aa5afcc18cc52eaed41a7f350c1` |
| `specs/001-autonomous-release/plan.md` | `17b441459a2a7ce328351e6291d357c3e0d3d7ce182dc4bbcd440af1f028b60b` |
| `specs/001-autonomous-release/decisions.md` | `7c260b51c61707662a44df827ef09de62b2e77656afcc7cfb468f9a3c7a4a5b3` |
| `specs/001-autonomous-release/research.md` | `7e8f06340e4df1c4bab388fa752207eab9850f435e1d4bb657848a8f6d8d17c8` |
| `specs/001-autonomous-release/provider-research.md` | `b754cc8cb237b12b122ee2bf5d02c2e7fc0c6e2d36ae46bd42775c6d573b5805` |
| `specs/001-autonomous-release/packaging-research.md` | `434d2c8b643eb6b49de34ad57fcae7a03bb4e1e70fc25ad3ab19e3c8c3487ae8` |
| `specs/001-autonomous-release/sandbox-research.md` | `4000900351390ded50de4cca1b9a4273a1c856e2f1d9fd02ac5752b5f86c1ce8` |
| `specs/001-autonomous-release/data-model.md` | `6ad320c472cebb9d86621e5f5188b3b868bf6d1d85e4364ba30706986abbf4b0` |
| `specs/001-autonomous-release/quickstart.md` | `c66811f17b3773bbe7df9c466c8b9495147607ed40b472687e81a575d62529c9` |
| `specs/001-autonomous-release/source-traceability.md` | `a29766bfcd53093afc3d9df2da6d8eba8990ef12141a578ac3011d4e6840f8cf` |
| `specs/001-autonomous-release/tasks.md` | `8331f208ed542cbf4e842dbfcbad5314670e438a9c3b6a85ea69c0ad5e428d8c` |
| `specs/001-autonomous-release/progress.md` | `188529b128042b813510bc5a6394e43568b184e78bb2715a59dbe38c8d8dea5b` |
| `specs/001-autonomous-release/contracts/api.md` | `d55b58d0c289b662c47387d6f7d8ba7a17c29e02309917b4d5179c05fda2fb9f` |
| `specs/001-autonomous-release/contracts/experience.md` | `9efb5a515d26ebb40c5b23b97a74869589e020653ae84f7fe9b382fb28110d73` |
| `specs/001-autonomous-release/contracts/growth.md` | `0b579504cd37cbbd41d1218592643013663371d6fb4efe888237183f2be3e885` |
| `specs/001-autonomous-release/contracts/operations.md` | `4517aac426b0cc36f1cae40053f043468773ec946e057d324e761389af4df013` |
| `specs/001-autonomous-release/contracts/runtime.md` | `2dccfab85b2b6351cb9b7de86be092f8dfa5695188a52d65c7673de7fd666330` |
| `specs/001-autonomous-release/contracts/extension-ports.md` | `3f4d159e6389e986c81588b7a674fc5528a3f0b73d86fb37ff6b34543e838de9` |
| `specs/001-autonomous-release/contracts/verification.md` | `b7ecdc439cf3ba5dd055446950637fb1356902872e9f24d5c543b8d54e4a862e` |
| `specs/001-autonomous-release/checklists/requirements.md` | `bc9ad5e6e4ab3b9f87531dbcd513845b2965a4ad75b0456ba29bcddca773cfdb` |
| `specs/001-autonomous-release/evidence/extension-spi-pure-contracts.md` | `4621b6c0b78802d963d986de486fd27cc7616e551b89d2f00463abec1a7b3b7a` |
| `specs/001-autonomous-release/evidence/extension-framework-design-remediation.md` | `e684b16865cb70475fb5b8313e73de3f2825a04e939b98d3aaa29327f27731d6` |
| `specs/001-autonomous-release/evidence/web-framework-design-review.md` | `d24378e849cffc088438f0529f7d14f8516d137efb70ddd33847c35de4922018` |
| `specs/001-autonomous-release/evidence/worker-dispatch-t018b2.md` | `6bc87a7e20174461c5265f7dd06115dbfeabc0bbcefb4de0bb7bad6aa81a85d2` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest.md` | `514e279f6b3db9672f31d373d78316a8470a98287d51d67f58c5101a6b6dd15f` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r2.md` | `ffeba2ba0014ce13065cb2ea0d6ebda28a1ceabdbdc3882b03e40d13ccbd70ae` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r3.md` | `990a2bbe4f128e60386b68e6c7774328e901d8cbedaf6f567bdc65a744803238` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r4.md` | `3d9eb8ea804dcd7f52300a7ffaafec5cc536f7fd46f21aafdc931f884fab1468` |

## Required independent-review gates

The reviewer first verifies all 33 digests, then checks the complete prior ADR-014 gate set plus:

1. All 52 request operations occur once: 11 non-empty-capable and 41 exact-empty. Export prepare and
   transmit carry the exact snapshot/prepared 1–256 `export_payload` list and bytes only through the
   bounded broker stream; ref-only, shared-store/mount and changed-content paths fail.
2. Every result artifact has its exact operation role/media/omissions/ref/digest/size relation;
   codec target media and output omissions and core ToolDefinition output contracts cannot conflict.
3. `result.effect` is the sole truth. The generated terminal×effect-family table admits only the
   listed tuples, error has no duplicate effect state, succeeded external unknown/unconfirmed and
   failed unknown/committed/retryable combinations fail, and unknown is never auto-retried.
4. The 44 schema count and independent 208 candidate-terminal/127-allowed/81-rejected result matrix
   remain coherent, including cancelled codec `artifacts=[]`.
5. T018-foundation alone precedes semantic integrations; T018-final consumes their evidence later,
   T083 retains two-clean-host repetition, and the unchanged T018 checkbox does not create a cycle.
6. The exact five-field binding key, four deployment arms, durable lifecycle, router seam, HTTPS
   client, recursive reusable-core scan, official browser framework identity, external deployment
   authority and legal open-source-target boundary remain unchanged.

Only a new independent revision-5 verdict with no P1/P2 contradiction can support closing T086.
Implementation, runtime, distribution, effect, legal and human-acceptance gates remain separate.
