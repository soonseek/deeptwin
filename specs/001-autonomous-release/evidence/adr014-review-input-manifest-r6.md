# ADR-014 independent-review input manifest — revision 6

Frozen: `2026-09-08T23:26:18+0900` · Hash: SHA-256 of each file's raw bytes
Status: **frozen revision-6 review input, not a verdict; T086 remains open**

## Supersession and scope

This immutable successor supersedes revision 5 only as the next ADR-014 review input. It does not
rewrite revisions 1–5 or any rejection. Revision 5 was rejected with P1=0, P2=1, P3=0 because tool
success output duplicated the common effect receipt truth. Revision 6 makes successful `invoke_tool`
output exactly `{tool_call_ref,result_ref}`, forbids output-level receipt fields/aliases, and leaves
`ToolResultArtifactBindingV1` under `result_ref`. All r5 counts, lifecycle, T018 DAG, browser-framework
identity and legal-open-source boundary are unchanged.

This manifest excludes itself and every independent-review verdict, including the separately stored
r5 rejection, so no verdict participates in its own next review input. It includes the frozen r5
manifest only as immutable supersession history. Any byte change requires another explicitly
superseding manifest. No entry implements or qualifies a port, extension, worker or release, and the
absence of a root project license continues to keep T084/legal publication open.

## Frozen files

| Path | SHA-256 |
| --- | --- |
| `README.md` | `37e4a925a7aea4091aba2e6c0a77c6c2cc7b6dd2efaf05b19d5f15354537dd51` |
| `app/README.md` | `9f0688ad4698bd15d867cda71290cd751b32d71937e975d3dd1d80b85c90ae4d` |
| `.specify/memory/constitution.md` | `6709456b75a8b8d3494ae2f10526cf86e4fec3fcdd1212197fbe54aa000ef308` |
| `sdk/python/README.md` | `ec1b88f8ff79787c607d5babd4ed33f5a2837271828c8f1f4b64ee0c361dc2f7` |
| `examples/extensions/README.md` | `49c04dcfe4992a21410856e114e9922140bffa4a2a21ba12d5ddea6bd20d2b7c` |
| `specs/001-autonomous-release/spec.md` | `4b57c3fe6df786aa65d0459c82f74ffef0c33aa5afcc18cc52eaed41a7f350c1` |
| `specs/001-autonomous-release/plan.md` | `c193c1d7cb58ea8c4058cf7b3e7a063921e6c8ed6fe90cf1d393392b2d0d4839` |
| `specs/001-autonomous-release/decisions.md` | `960562f8ce6e647ee69587a08871a0c337f0547bc4d0f8e9c63d1001f9ad3b24` |
| `specs/001-autonomous-release/research.md` | `7e8f06340e4df1c4bab388fa752207eab9850f435e1d4bb657848a8f6d8d17c8` |
| `specs/001-autonomous-release/provider-research.md` | `b754cc8cb237b12b122ee2bf5d02c2e7fc0c6e2d36ae46bd42775c6d573b5805` |
| `specs/001-autonomous-release/packaging-research.md` | `434d2c8b643eb6b49de34ad57fcae7a03bb4e1e70fc25ad3ab19e3c8c3487ae8` |
| `specs/001-autonomous-release/sandbox-research.md` | `4000900351390ded50de4cca1b9a4273a1c856e2f1d9fd02ac5752b5f86c1ce8` |
| `specs/001-autonomous-release/data-model.md` | `38cdccbb038474b42117a7e588445f525b5a7321fc21c77af83ed371d3925789` |
| `specs/001-autonomous-release/quickstart.md` | `c66811f17b3773bbe7df9c466c8b9495147607ed40b472687e81a575d62529c9` |
| `specs/001-autonomous-release/source-traceability.md` | `dd14d0bd6aa5db915e710aca1315d45d3f4af569f361f143aeb97b805b5c51ce` |
| `specs/001-autonomous-release/tasks.md` | `e2b7c8b2ef74263a20784663c94672663c27690918a0de23f787965cd55495b0` |
| `specs/001-autonomous-release/progress.md` | `de01642fe3d1ab4bd93719d2bfece803a8c3532abfac5ab8610b197027831bcc` |
| `specs/001-autonomous-release/contracts/api.md` | `4dd9f0a5ab0531cef3e054dc4bb376e75e3ac5c8841ea74cd2195a229902ee5b` |
| `specs/001-autonomous-release/contracts/experience.md` | `9efb5a515d26ebb40c5b23b97a74869589e020653ae84f7fe9b382fb28110d73` |
| `specs/001-autonomous-release/contracts/growth.md` | `0b579504cd37cbbd41d1218592643013663371d6fb4efe888237183f2be3e885` |
| `specs/001-autonomous-release/contracts/operations.md` | `daeef0745de8c486f3b394e16deb6d54d87721ace9043ee070ccb139f997f057` |
| `specs/001-autonomous-release/contracts/runtime.md` | `d987878241d6259bd15186b12119f9af12e0ade74b23da24316d8fb3d1d2c82c` |
| `specs/001-autonomous-release/contracts/extension-ports.md` | `e126c2448e6ba01af286ee1799dfdfca6f8d5b1392a92eba4167d856c670c2fc` |
| `specs/001-autonomous-release/contracts/verification.md` | `3426a69d8e325382f6a95e8143a05cadd5023db6568b5f177054ed82d5649412` |
| `specs/001-autonomous-release/checklists/requirements.md` | `4176ef1ba118c1406317faf15e410a3c8907f6fdc942d82446c0bf634ca4f82e` |
| `specs/001-autonomous-release/evidence/extension-spi-pure-contracts.md` | `32ee33c4eb9d489e7d4655a15031e9fa64fa8c68ccb4727ce27e09ffe4e3e62e` |
| `specs/001-autonomous-release/evidence/extension-framework-design-remediation.md` | `588176f72d92295d1d725a6977a902f7bbb5ee86c1db3d014821faac35b0948e` |
| `specs/001-autonomous-release/evidence/web-framework-design-review.md` | `1098807e1b9962450273b0dfbac9a14dc4420d179ef2227cec192e5852d810e0` |
| `specs/001-autonomous-release/evidence/worker-dispatch-t018b2.md` | `6bc87a7e20174461c5265f7dd06115dbfeabc0bbcefb4de0bb7bad6aa81a85d2` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest.md` | `514e279f6b3db9672f31d373d78316a8470a98287d51d67f58c5101a6b6dd15f` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r2.md` | `ffeba2ba0014ce13065cb2ea0d6ebda28a1ceabdbdc3882b03e40d13ccbd70ae` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r3.md` | `990a2bbe4f128e60386b68e6c7774328e901d8cbedaf6f567bdc65a744803238` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r4.md` | `3d9eb8ea804dcd7f52300a7ffaafec5cc536f7fd46f21aafdc931f884fab1468` |
| `specs/001-autonomous-release/evidence/adr014-review-input-manifest-r5.md` | `2da9c4b1fc08200d80e222f82cc21367f61ac7d5ea0f6a0eaa61411862d3701f` |

## Required independent-review gates

The reviewer first verifies all 34 digests, then checks the complete prior ADR-014 gate set plus:

1. Successful `tool-port-v1.invoke_tool` output is exactly `{tool_call_ref,result_ref}`.
2. Output-level `effect_receipt_ref` or any alias is rejected even when it equals the common receipt;
   `result.effect.effect_receipt_ref` is the sole receipt truth for all terminals.
3. `ToolResultArtifactBindingV1` remains sealed under `result_ref`; removing the duplicate receipt
   neither removes artifact bindings nor changes their exact role/media/omissions/ref equality.
4. The 44 schema, 52-operation, 208/127/81 terminal and 11/41 request counts, durable lifecycle,
   T018-foundation/final DAG, browser framework and legal target boundaries remain unchanged.

Only a new independent revision-6 verdict with no P1/P2 contradiction can support closing T086.
Implementation, runtime, distribution, effect, legal and human-acceptance gates remain separate.
