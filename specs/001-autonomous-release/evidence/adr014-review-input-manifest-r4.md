# ADR-014 independent-review input manifest — revision 4

Frozen: `2026-09-08T22:42:42+0900` · Hash: SHA-256 of each file's raw bytes
Status: **frozen revision-4 review input, not a verdict; T086 remains open**

## Supersession and scope

This immutable successor supersedes revision 3 only as the next ADR-014 review input. It does not
rewrite revisions 1–3 or any rejection. The revision-3 review found no P1 but rejected two P2 gaps:
the field-complete config used a four-field binding key while the canonical head key had five, and
the generic request artifact array left all 52 operations unconstrained. Revision 4 freezes one exact
five-field `BindingSlotKeyV1`+digest everywhere and a separate exhaustive request artifact-input
matrix: nine operations use core-owned frozen/tool/codec/storage profiles and 43 require `[]`.

This manifest excludes itself and every review verdict, so it has no self-hash or verdict-input
cycle. Any input-byte change requires a new explicitly superseding manifest. The T018-B2 evidence is
included only to support the corrected current-status wording in tasks/progress; it does not close
T018. No entry implements or qualifies a port, schema, extension, worker, distribution or UI. The
repository remains an open-source target without a project license; T084 and copyright-owner
approval remain mandatory before legal open-source publication/redistribution is claimed.

## Frozen files

| Path | SHA-256 |
| --- | --- |
| `README.md` | `37e4a925a7aea4091aba2e6c0a77c6c2cc7b6dd2efaf05b19d5f15354537dd51` |
| `app/README.md` | `9f0688ad4698bd15d867cda71290cd751b32d71937e975d3dd1d80b85c90ae4d` |
| `.specify/memory/constitution.md` | `6709456b75a8b8d3494ae2f10526cf86e4fec3fcdd1212197fbe54aa000ef308` |
| `sdk/python/README.md` | `ec1b88f8ff79787c607d5babd4ed33f5a2837271828c8f1f4b64ee0c361dc2f7` |
| `examples/extensions/README.md` | `49c04dcfe4992a21410856e114e9922140bffa4a2a21ba12d5ddea6bd20d2b7c` |
| `specs/001-autonomous-release/spec.md` | `c1721d79f0a636f3e051443d23bb492bb30bee81526c0754acd67f6b55908ca8` |
| `specs/001-autonomous-release/plan.md` | `fa51a4677a948e4b740d42de7e3e60b74352c2e88e0f21ee3062303c0d43f735` |
| `specs/001-autonomous-release/decisions.md` | `69c5beea896a39db85ae00ff6653092f0e9ebb38134ce9bb51ecf035237aebf4` |
| `specs/001-autonomous-release/research.md` | `4c7892066e34853f78781b7d8674c4eec4a80f1e3916ae3b5d68c558dac69e38` |
| `specs/001-autonomous-release/provider-research.md` | `b754cc8cb237b12b122ee2bf5d02c2e7fc0c6e2d36ae46bd42775c6d573b5805` |
| `specs/001-autonomous-release/packaging-research.md` | `434d2c8b643eb6b49de34ad57fcae7a03bb4e1e70fc25ad3ab19e3c8c3487ae8` |
| `specs/001-autonomous-release/sandbox-research.md` | `4000900351390ded50de4cca1b9a4273a1c856e2f1d9fd02ac5752b5f86c1ce8` |
| `specs/001-autonomous-release/data-model.md` | `a233c853af8d4154b9ff5bd84319cd307c7ca3f849fd01e8cd4b10e5826a1642` |
| `specs/001-autonomous-release/quickstart.md` | `c66811f17b3773bbe7df9c466c8b9495147607ed40b472687e81a575d62529c9` |
| `specs/001-autonomous-release/source-traceability.md` | `e445e68083919bbfdf8b026d007c8fa29495abaa259d1013fd8f712315b3c025` |
| `specs/001-autonomous-release/tasks.md` | `08945dc0fa9a58af45a0b7939d46981edf358c057704e7c5100091cee7ab4a04` |
| `specs/001-autonomous-release/progress.md` | `3761051c9b533d332add4405b1a3a42498df71de5528e8171dc3d1f793b58436` |
| `specs/001-autonomous-release/contracts/api.md` | `54dd703cfebdc92af9644dbe3aef7bc16a7be49b4ba138c93a78b5aa33f45d59` |
| `specs/001-autonomous-release/contracts/experience.md` | `9efb5a515d26ebb40c5b23b97a74869589e020653ae84f7fe9b382fb28110d73` |
| `specs/001-autonomous-release/contracts/growth.md` | `0b579504cd37cbbd41d1218592643013663371d6fb4efe888237183f2be3e885` |
| `specs/001-autonomous-release/contracts/operations.md` | `30698217654353b3acf397a16db3c043dbb8ad63f42787882868ae94cb96a557` |
| `specs/001-autonomous-release/contracts/runtime.md` | `36b47129a345f4dee1d278c5ee98ab44b226af47321d6fb47b09cc44ca50c7ed` |
| `specs/001-autonomous-release/contracts/extension-ports.md` | `77a28e153751cddcbefabd2e55bcd5e527a60a8d189280822707aafef9b590d2` |
| `specs/001-autonomous-release/contracts/verification.md` | `06229e7de514a7c35b051b4c95b55d4c2030b81e74a4c567259ea6770be07de5` |
| `specs/001-autonomous-release/checklists/requirements.md` | `a101551d6c8ae288095e7fb8de5f286e54685e9e5dc36aa4252b6b16eb8e22cf` |
| `specs/001-autonomous-release/evidence/extension-spi-pure-contracts.md` | `17d685c6bfedcf3a4568e8de771f103f1d18e7ad1181dac7b1e8df8567be255c` |
| `specs/001-autonomous-release/evidence/extension-framework-design-remediation.md` | `84f221c09167b8f3f8e80aa17d81544f074575ac7e22f0db77d322ffd7740d9e` |
| `specs/001-autonomous-release/evidence/web-framework-design-review.md` | `1556be58ef127f868e7e8a8d0a3608ac8c9298cb3fe48c158cd00a82c2e97923` |
| `specs/001-autonomous-release/evidence/worker-dispatch-t018b2.md` | `6bc87a7e20174461c5265f7dd06115dbfeabc0bbcefb4de0bb7bad6aa81a85d2` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest.md` | `514e279f6b3db9672f31d373d78316a8470a98287d51d67f58c5101a6b6dd15f` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r2.md` | `ffeba2ba0014ce13065cb2ea0d6ebda28a1ceabdbdc3882b03e40d13ccbd70ae` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r3.md` | `990a2bbe4f128e60386b68e6c7774328e901d8cbedaf6f567bdc65a744803238` |

## Required independent-review gates

The reviewer first verifies every digest, then checks the complete prior ADR-014 gate set plus:

1. `BindingSlotKeyV1` is exactly five fields everywhere, includes `port_contract_version`, and has
   one canonical digest; config sibling/nested version, resolved binding/head, command/result/event/
   retention and UI all preserve equality. Four-field, wrong-digest and cross-version mutations fail.
2. All 52 request operations are enumerated once: nine non-empty-capable and 43 exact-empty. Every
   profile fixes allowed/required count, role, media, selector, byte and source/ref relation; extra,
   missing, hidden/conflicting and frozen-list mismatches fail before dispatch.
3. Codec and storage use the common input array as sole source/value authority; ToolDefinition owns
   the closed input contract and explicit fetch/browser/multimodal/document profiles; extensions and
   arguments cannot add another artifact ref or widen it.
4. The 44 schema count and independent 208 candidate-terminal/127-allowed/81-rejected result matrix
   remain coherent, including cancelled codec `artifacts=[]`.
5. T018-B2 closes only its bounded HTTP→coordinator/observation checkpoint. Linux/service/worker/
   artifact-streaming/graph/Chromium/two-clean-profile work keeps T018 open.
6. The official browser control surface, reusable framework core, external deployment authority,
   separate SDK/client and legal open-source target boundaries remain unchanged.

Only a new independent revision-4 verdict with no P1/P2 contradiction can support closing T086.
Implementation, runtime, distribution, effect, legal and human-acceptance gates remain separate.
