# Repository license approval: Apache-2.0 (2026-09-24)

Status: **approved and applied.** T084 stays open for its other parts.

## The decision

On 2026-09-24 the owner stated in the working session: "라이선스 Apache-2.0으로 확정" ("the
license is confirmed as Apache-2.0"). This names one license explicitly, as
[license-recommendation.md](../../../docs/release/license-recommendation.md) required, and it is
that page's recommended default. An earlier "approve everything else" without a named license was
not treated as this approval, and no license file was added on it.

## What was applied

- `LICENSE` and `LICENSES/Apache-2.0.txt`: the canonical Apache License 2.0 text from
  apache.org, sha256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`.
- `NOTICE`: "Copyright 2026 The DeepTwin Authors". It points to the third-party inventory for
  bundled components.
- `pyproject.toml`: `license = "Apache-2.0"`, `license-files = ["LICENSE", "NOTICE"]` (PEP 639).
- The license-status statements in `docs/release/` (architecture, contributing, extension
  authoring, source-license inventory, third-party notices, license recommendation).

## Still open

- **Copyright holder name.** "The DeepTwin Authors" is a neutral placeholder; the owner may
  replace it with a person or organization (recommendation §4.1).
- SPDX headers in source files.
- Per-image third-party NOTICE, license texts and source offers (T081/T082).
- The inbound-contribution mechanism (DCO or CLA, §4.2) and the trademark policy (§4.3).
- The example extension manifests' own license declarations (§4.5).
- Publication, which needs its own authority. Nothing was published, tagged or uploaded.
