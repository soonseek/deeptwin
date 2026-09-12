# ADR-014 independent architecture review — revision 7

Date: 2026-09-08  
Disposition: **ACCEPT for T086 design closure**  
Severity count: **P1 0 · P2 0 · P3 1 (nonblocking)**

## Frozen input

The independent reviewer evaluated only the bytes named by
`adr014-review-input-manifest-r7.md`.

- manifest SHA-256:
  `57c80f1cec6bf674d91f0cd3da802f93fbca1386574558e546ad39c90676f08f`
- manifest entries: 35
- entry verification: 35/35 current raw-byte hashes matched at the start and end of review
- review behavior: read-only; the reviewer changed no workspace file

The manifest excludes this verdict. Revisions 1–6 and their rejected verdicts remain immutable
history. A later status-only checkbox or progress edit does not retroactively become a reviewed
semantic input; any semantic contract change requires a new revision and independent review.

## Verdict

No P1 or P2 design contradiction remains in revision 7. T086 may close after this separate verdict
is recorded and status-only bookkeeping is applied. This verdict closes only the all-design
architecture gate. It does not close T018, T025, T087, implementation, runtime isolation,
distribution, effect, legal-license, publication, or human-acceptance gates.

## Independently verified results

- The normative extension contract has 11 valid port rows and zero isolated Markdown pipe rows.
  `tool-port-v1` and `artifact-codec-port-v1` are consecutive rows; receipt prose follows the table.
- The tool `invoke_tool` successful output is exactly `{tool_call_ref,result_ref}`. An output-level
  `effect_receipt_ref` or alias is forbidden, while `result.effect.effect_receipt_ref` is the sole
  effect-receipt truth. `ToolResultArtifactBindingV1` remains beneath `result_ref`.
- The closed counts remain coherent: 11 ports, 44 schemas, 52 operations, 208 candidate terminal
  pairs, 127 allowed pairs, 81 rejected pairs, and 11 non-empty-capable versus 41 exact-empty
  request artifact-input profiles.
- Export `prepare` and `transmit` repeat the exact snapshot/prepared 1–256 `export_payload` bindings
  and obtain bytes only through the bounded digest/chunk/receiver-credit broker stream.
- Result artifact role/media/omissions/ref/digest/size relations and the single result-effect
  terminal/family/retry truth remain closed.
- The exact five-field `BindingSlotKeyV1`, four deployment arms, durable qualification/binding/
  rollback-retention/retirement lifecycle, and digest causality remain coherent.
- `T018-foundation -> semantic integration -> T018-final` is non-circular. T083 retains ownership of
  the two-clean-host repetition.
- T025 router/TLS/loopback ownership, recursive `app/extensions/**` core-boundary inspection,
  official browser-framework identity, external deployment authority, and the legal open-source
  target/current distinction remain intact.
- T018-B2's ten recorded source hashes matched current bytes and T018 correctly remains open.

Final mechanical observations:

```text
manifest entries: 35/35 OK
valid_port_rows: 11
isolated_pipe_rows: 0
listed_vs_table_diff: 0
task declarations: 90
duplicate or missing T001-T090: 0
T018-B2 source hashes: 10/10 OK
root LICENSE: absent
.specify/extensions.yml: absent before and after review
```

## Nonblocking P3

The frozen `progress.md` still used the phrase “both rejected ADR-014 reviews” in one historical
status line even though revisions 1–6 were rejected. This is a status-history wording defect, not a
design contradiction. Post-verdict bookkeeping must change it to an exact six-review description.

## Post-verdict bookkeeping boundary

T086/checklist/progress/current-status fields may now be updated without changing the accepted
architecture. Those edits must be identified as post-verdict bookkeeping and must not alter any
schema, authority, lifecycle, effect, artifact, deployment, routing, security, or product-identity
meaning. T075 remains responsible for the later implementation-era release-input manifest.

Applied post-verdict bookkeeping changed current-status prose only in the following accepted-input
documents; their resulting SHA-256 values are recorded so this transition is auditable:

| File | Post-verdict SHA-256 |
| --- | --- |
| `spec.md` | `d581f3921b24e13435e68e7e5201528ff92481b392788fff71849e6baec701c8` |
| `plan.md` | `10824ec8cf23f419609b140f7d49dfbda3fbeb26f9a6f946a15134532caecda7` |
| `decisions.md` | `dfeca8ae43df00912caa16e54dfb55466dade0f00d86b601cb49b10463494de7` |
| `source-traceability.md` | `c1c0b4d1d8d220ae01018cacf5c74f2378ce31638647c213bffd85098e5148af` |
| `tasks.md` | `db09bf7a7bcc913f8955e3496cdb7bda178fdfeeb54f4a83094277f9eab8ba85` |
| `progress.md` | `008df4139f008a04afd8a8f859b037bdd8b58c33bd645820c7b9e48f60ec2059` |
| `checklists/requirements.md` | `954ab5248a4f7465d25a367e62adddbc1bf493c6899cad82f72e5e4c0a6679cc` |
| `evidence/web-framework-design-review.md` | `52144648a0bd2e98b00f3933d37e1a9441ced6eab8c66d6f5fa5837a0153016d` |
| `evidence/extension-framework-design-remediation.md` | `32adb9242623552ef6e342faca48ceae6451ca16a3e09e44b1d4b7217c27df7e` |

The post-bookkeeping Spec Kit analysis found 34 functional requirements, 10 success criteria,
90 task declarations, 90 unique task IDs, complete FR/SC task-or-verification coverage, no unresolved
placeholder/conflict marker and a clean `git diff --check`. Twenty-four tasks are now evidenced
complete and 66 remain open. The weighted delivery estimate is 36.5% (user-facing: roughly 35%).
