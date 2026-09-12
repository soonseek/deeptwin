# ADR-014 independent-review input manifest — revision 7

Frozen: `2026-09-08T23:34:31+0900` · Hash: SHA-256 of each file's raw bytes
Status: **frozen revision-7 review input, not a verdict; T086 remains open**

## Supersession and scope

This immutable successor supersedes revision 6 only as the next ADR-014 review input. It does not
rewrite revisions 1–6 or any rejection. Revision 6 was rejected with P1=0, P2=1, P3=0 because prose
split the §3.2 Markdown table and isolated the artifact-codec row. Revision 7 moves the unchanged
prose below the consecutive tool/codec rows and adds an exact eleven-row/zero-isolated-row structure
guard. It changes no operation, schema, request profile, effect, lifecycle, dependency or count.

This manifest excludes itself and every independent-review verdict, including the separately stored
r6 rejection. It includes the frozen r6 manifest only as immutable supersession history. Any byte
change requires another explicitly superseding manifest. No entry implements or qualifies a port,
extension, worker or release; T086 and the no-root-license/T084 legal gate remain open.

## Frozen files

| Path | SHA-256 |
| --- | --- |
| `README.md` | `37e4a925a7aea4091aba2e6c0a77c6c2cc7b6dd2efaf05b19d5f15354537dd51` |
| `app/README.md` | `9f0688ad4698bd15d867cda71290cd751b32d71937e975d3dd1d80b85c90ae4d` |
| `.specify/memory/constitution.md` | `6709456b75a8b8d3494ae2f10526cf86e4fec3fcdd1212197fbe54aa000ef308` |
| `sdk/python/README.md` | `ec1b88f8ff79787c607d5babd4ed33f5a2837271828c8f1f4b64ee0c361dc2f7` |
| `examples/extensions/README.md` | `49c04dcfe4992a21410856e114e9922140bffa4a2a21ba12d5ddea6bd20d2b7c` |
| `specs/001-autonomous-release/spec.md` | `4b57c3fe6df786aa65d0459c82f74ffef0c33aa5afcc18cc52eaed41a7f350c1` |
| `specs/001-autonomous-release/plan.md` | `c98637620c048baef459276ba9d3118c7dd1717a1eb3b33b9f1ab5aeffd792f0` |
| `specs/001-autonomous-release/decisions.md` | `78b3c5d465b33cc27588aa04990fb27e8fe61ebcf129a5557c56183f59ea39e8` |
| `specs/001-autonomous-release/research.md` | `7e8f06340e4df1c4bab388fa752207eab9850f435e1d4bb657848a8f6d8d17c8` |
| `specs/001-autonomous-release/provider-research.md` | `b754cc8cb237b12b122ee2bf5d02c2e7fc0c6e2d36ae46bd42775c6d573b5805` |
| `specs/001-autonomous-release/packaging-research.md` | `434d2c8b643eb6b49de34ad57fcae7a03bb4e1e70fc25ad3ab19e3c8c3487ae8` |
| `specs/001-autonomous-release/sandbox-research.md` | `4000900351390ded50de4cca1b9a4273a1c856e2f1d9fd02ac5752b5f86c1ce8` |
| `specs/001-autonomous-release/data-model.md` | `38cdccbb038474b42117a7e588445f525b5a7321fc21c77af83ed371d3925789` |
| `specs/001-autonomous-release/quickstart.md` | `c66811f17b3773bbe7df9c466c8b9495147607ed40b472687e81a575d62529c9` |
| `specs/001-autonomous-release/source-traceability.md` | `e172c0c4cad941583eb895764ac88e76061130c73c093c6a1f77a358364e33e7` |
| `specs/001-autonomous-release/tasks.md` | `175f375c037b06ac1219b98d05be36130eb1eb3fa51a250ea338eced41524d48` |
| `specs/001-autonomous-release/progress.md` | `83e316730fa14d94b6d84243b63a396088579eedb3ba5d86f83ff63decfd3c9a` |
| `specs/001-autonomous-release/contracts/api.md` | `4dd9f0a5ab0531cef3e054dc4bb376e75e3ac5c8841ea74cd2195a229902ee5b` |
| `specs/001-autonomous-release/contracts/experience.md` | `9efb5a515d26ebb40c5b23b97a74869589e020653ae84f7fe9b382fb28110d73` |
| `specs/001-autonomous-release/contracts/growth.md` | `0b579504cd37cbbd41d1218592643013663371d6fb4efe888237183f2be3e885` |
| `specs/001-autonomous-release/contracts/operations.md` | `daeef0745de8c486f3b394e16deb6d54d87721ace9043ee070ccb139f997f057` |
| `specs/001-autonomous-release/contracts/runtime.md` | `d987878241d6259bd15186b12119f9af12e0ade74b23da24316d8fb3d1d2c82c` |
| `specs/001-autonomous-release/contracts/extension-ports.md` | `f6be99eacbe21fbd06219d96529399d6bfb00d014e746ee82c331ea1605fe538` |
| `specs/001-autonomous-release/contracts/verification.md` | `3426a69d8e325382f6a95e8143a05cadd5023db6568b5f177054ed82d5649412` |
| `specs/001-autonomous-release/checklists/requirements.md` | `5871f0000681a4ab6eb1085baf2de0fba033860b1524debe58e8df3865ab2c10` |
| `specs/001-autonomous-release/evidence/extension-spi-pure-contracts.md` | `32ee33c4eb9d489e7d4655a15031e9fa64fa8c68ccb4727ce27e09ffe4e3e62e` |
| `specs/001-autonomous-release/evidence/extension-framework-design-remediation.md` | `311eacc2fc52a45f2d6291b0bfa6f2df90e27aaa80f8ce5a3c13c0c5c15cee9e` |
| `specs/001-autonomous-release/evidence/web-framework-design-review.md` | `571f940a48d0db67ba12ed7e68bc88fbefafcbaeaedb4e4867aa9055544439f1` |
| `specs/001-autonomous-release/evidence/worker-dispatch-t018b2.md` | `6bc87a7e20174461c5265f7dd06115dbfeabc0bbcefb4de0bb7bad6aa81a85d2` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest.md` | `514e279f6b3db9672f31d373d78316a8470a98287d51d67f58c5101a6b6dd15f` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r2.md` | `ffeba2ba0014ce13065cb2ea0d6ebda28a1ceabdbdc3882b03e40d13ccbd70ae` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r3.md` | `990a2bbe4f128e60386b68e6c7774328e901d8cbedaf6f567bdc65a744803238` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r4.md` | `3d9eb8ea804dcd7f52300a7ffaafec5cc536f7fd46f21aafdc931f884fab1468` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r5.md` | `2da9c4b1fc08200d80e222f82cc21367f61ac7d5ea0f6a0eaa61411862d3701f` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r6.md` | `e8bb4c875a9714be9447d21fb37859fd1a193487a65e0350b7c94e6e9b7af0e3` |

## Required independent-review gates

The reviewer first verifies all 35 digests, then checks the complete prior ADR-014 gate set plus:

1. Exactly eleven normative `*-port-v1` rows occur inside contiguous pipe tables opened by an
   immediately adjacent `Port` header and separator; isolated row count is zero.
2. Tool and artifact-codec remain consecutive rows under §3.2 and the unchanged receipt prose follows
   the completed table. Inserting prose between the rows makes the structure check fail.
3. The 11 ports, 44 schemas, 52 operations, 208 candidates, 127 allowed, 81 rejected and 11/41 request
   split are unchanged, as are every schema/profile/effect/lifecycle/DAG/legal semantic rule.

Only a new independent revision-7 verdict with no P1/P2 contradiction can support closing T086.
Implementation, runtime, distribution, effect, legal and human-acceptance gates remain separate.
