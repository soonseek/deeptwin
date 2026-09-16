# Deployment receipt verification dependency candidate v1

This contract defines the additive control-plane dependency declaration needed by the public-only
receipt verifier. It does not change the frozen T089 input family, install a package, build an
image, authorize signing or qualify a deployment. The wire boundary remains deployment-receipts.md.
The candidate is deliberately separate from final T081 image inclusion and T084 publication gates.

## 1. Fixed deliverables and authority

Create exactly these build-input artifacts and their read-only verifier/test:

- deploy/locks/requirements-control-plane-receipt-v1-linux.lock
- deploy/manifests/python-wheel-artifacts-receipt-v1.addendum.json
- deploy/locks/verify_receipt_dependency_candidate.py
- deploy/tests/test_receipt_dependency_candidate.py

The complete candidate lock is a usable dependency input, not an overlay passed by itself to pip.
It preserves every frozen control dependency/version/hash and adds only pynacl==1.6.2. That is
18 distinct packages; cffi==2.0.0 and pycparser==2.23 are already in the17-package base closure.
No provider-profile inheritance, unpinned transitive resolution, optional automatic fallback or
replacement of unrelated dependency versions. Initial targets remain CPython3.12.14 Linux amd64/
arm64 and glibc floor2.28. The two architectures have separate selected wheelhouses.

The new declaration is inert metadata even after local verification. A caller-constructed result,
hash-matching wheel record or provider image dependency is not a qualified control image. The
general development requirement and verified local installation belong to the following codec
implementation step, not this metadata-only artifact step. No download/install is required here.

## 2. Immutable historical base inputs

The verifier has the following four exact code-owned relative paths, byte lengths and SHA256 pins.
The addendum repeats them for readable lineage; those repeated claims never select alternative
files or replace the verifier's fixed expected pins. Preserve bytes, including final newlines.

| path | bytes | SHA256 |
| --- | ---: | --- |
| deploy/locks/service-roots.json |3714|5feea78f28397217f2afdc1f51b41a3a3be916b4a0f3dd59f9b078f349e9150f|
| deploy/locks/requirements-control-plane-linux.lock |2077|66ced7fca949d303db10df2802f7b3a8b533d1dc7175d1edf30fe7f2a36fcb47|
| deploy/manifests/python-wheel-artifacts.json |201104|8d14cbc3b0acd9bc35773b3658c620409ef5e2ad3f9101b35395a740d4a85029|
| deploy/manifests/build-input-lock.json |27290|212eb478026a2e38b40d882c2525fcee6a3945ed258dbb0d89b615489e62e0bd|

Do not modify these files, the other historical service locks, their generators/verifiers,
EXPECTED_FILES, earlier evidence, or superseded native/macOS dependency inputs. Do not regenerate
the unversioned aggregate. A future complete release-input baseline gets separate versioned paths
and fresh aggregate qualification; this addendum does not silently join historical membership.

## 3. Exact addendum document

UTF8 JSON root object, at most65536bytes, depth16, total4000items, each string≤4096UTF8bytes and
integer in0..2^63-1 excluding booleans. No BOM, duplicate keys, nonfinite/float numbers, unknown
fields, surrogate text or trailing non-whitespace. Pretty JSON with terminal newline is allowed:
this is build metadata, not an ADR008 signed protocol. No alternate JSON canonicalizer is needed.

Exactly these ten fields:

```text
{
 schema_version:"deeptwin-control-receipt-dependency-candidate-v1",
 status:"candidate_not_release_qualified",
 service:"control-plane",
 consumers:["control-plane"],
 runtime:BaseRuntime,
 target_platforms:[{os:"linux",architecture:"amd64"},{os:"linux",architecture:"arm64"}],
 base_inputs:[{path:FixedPath,sha256:LowerHex64,size_bytes:FixedSize}, ... four sorted by path],
 added_direct_roots:["pynacl==1.6.2"],
 service_lock:{path:"deploy/locks/requirements-control-plane-receipt-v1-linux.lock",
               sha256:LowerHex64,size_bytes:PositiveInteger,package_count:18},
 artifacts:[Amd64PyNaClWheel,Arm64PyNaClWheel]
}
```

BaseRuntime is exactly the existing wheel manifest's runtime object:
`{implementation:"CPython",python_version:"3.12.14",abi:"cp312",glibc_floor:"2.28"}`.
The service_lock digest and size bind the actual new complete lock bytes. The addendum has no
self-digest. Future image provenance must independently pin the complete addendum's bytes.

Each artifact is an exact copy of the matching pinned base wheel record, with only usage replaced
by `[{service:"control-plane",os:"linux",architecture:MatchingArchitecture}]`. Preserve all other
name/version/filename/sha256/size_bytes/requires_python/license/source/wheel fields recursively.
Do not copy the old provider usage into this addendum or rewrite it in the original base manifest.
The two records are ordered amd64, arm64; duplicates and extra records are invalid. Full copies
retain original embedded PyNaCl/libsodium license-resource and package-source evidence without
inventing a second dependency resolver or claiming legal release clearance.

| architecture | selected filename | bytes | SHA256 |
| --- | --- | ---: | --- |
| amd64 |pynacl-1.6.2-cp38-abi3-manylinux_2_26_x86_64.manylinux_2_28_x86_64.whl|1437614|8a66d6fb6ae7661c58995f9c6435bda2b1e68b54b598a6a10247bfcdadac996c|
| arm64 |pynacl-1.6.2-cp38-abi3-manylinux_2_26_aarch64.manylinux_2_28_aarch64.whl|835085|46065496ab748469cdd999246d17e301b2c24ae2fdf739132e580a0e94c94a87|

These hashes are present in the pinned historical artifact inventory and were separately checked
against official PyPI release metadata. This step does not newly download or rehash wheel bytes.
The primary-source findings and API/RFC references are retained in
`.superpowers/sdd/resumption-plan/receipt-crypto-primary-sources.md`.

## 4. Read-only verifier

`verify_candidate(root: Path) -> dict` accepts a local repository/temporary fixture root, never a
runtime deployment source or receipt authority. It returns exactly
`{schema_version:"deeptwin-control-receipt-dependency-candidate-v1",
status:"candidate_not_release_qualified",service:"control-plane",package_count:18,
target_platforms:["linux/amd64","linux/arm64"],lock_sha256:LowerHex64,
addendum_sha256:LowerHex64}`. Returned data is freshly derived, inert metadata, not a capability.

Use the existing `verify_build_inputs.parse_lock` for the deliberately small exact-pin/hash lock
grammar, and its strict JSON helpers where compatible. The new layer enforces its own narrower
document limits, exact keys and relationships. No edits to the existing verifier. Add a small
private bounded read helper only where current helpers lack the needed byte/type preflight;
do not implement a second package resolver. All six input paths are code-owned descendants of
root, checked as regular non-symlink files before bounded read. Manifest path fields are equality
checks, never path inputs. This build-tool check does not promise a retained-FD runtime lease or
protection from arbitrary concurrent hostile modification of the checkout.

Check sequence:

1. Read actual four base files with their exact maximum sizes, compare length/SHA256 to fixed pins
   before parsing their metadata. Missing/symlinked/mutated inputs fail. Do not accept self-consistent
   replacement base documents whose hashes merely match a changed addendum.
2. Read actual new addendum≤65536bytes and complete lock≤16384bytes; enforce regular file/UTF8 and
   strict document bounds. Validate exact10field addendum shape and every nested fixed structure.
   Size/hash of actual lock must equal service_lock; base_inputs exactly equals the fixed four refs.
3. Parse base and candidate locks. Candidate package names are exactly base names plus pynacl;
   all17 base entries preserve exact versions and complete hash sets. PyNaCl has version1.6.2 and
   exactly the two hashes above, with no unused/extra hashes. Candidate direct roots are the four
   fixed base control roots plus the one added root, each present at the exact pin.
4. Select base records by actual control-plane usages for each architecture and add that platform's
   validated PyNaCl record. Exactly one record per package/platform, matching wheel platform or
   universal wheel, correct name/version and hash present in the candidate lock. Combined selected
   hashes across both architectures must equal every package's complete lock hash set. Reject
   duplicate/missing/extra/wrong-architecture/wrong-service selections. No inference from provider
   usage or filename substring alone; compare complete pinned records and explicit platform data.
5. Return the exact inert metadata summary. No writes, network, package import, image lookup,
   signing-key access, install, build, cleanup or modification of aggregate membership.

Candidate validation failures use `ReceiptDependencyError(ValueError)` with fixed safe code/text
`receipt_dependency_candidate_invalid`. Do not echo mutated content, arbitrary paths or raw parser
exceptions. Programming errors must not be silently converted to a passing candidate. An optional
`main()->int` has no user arguments and verifies its own repository root; success prints only the
summary JSON, failure prints the fixed code and returns1. This is an internal developer/CI tool,
not a CLI workflow required of framework users. Do not add an application import of deploy tools.

The existing whole aggregate check is a separate acceptance command, not reimplemented or invoked
inside each candidate validation. Passing candidate verification does not state that unrelated
historical inputs still pass; capture the existing aggregate result explicitly at final freeze.

## 5. RED/GREEN and freeze acceptance

Use actual temporary files for mutated candidate fixtures; no mocked hash-positive checker.
Snapshot the four fixed historical inputs, active compose/service IDs and old source contract
hashes before implementation. The following executable cases must initially fail when the new
verifier is absent or deliberately incomplete, then pass against the actual implementation:

- Actual repository candidate has18packages and both architecture closures; returned digests
  equal actual bytes. Existing aggregate remains accepted independently with no candidate member.
- Mutate each of the four base files and recompute its addendum ref: fixed expected pins still
  reject. Missing/nonregular/symlinked files, candidate length overflow and changed lock bytes fail.
- Addendum unknown/duplicate/BOM/float/bool integer/oversized depth/string/items/invalidUTF8 inputs,
  incorrect status/service/runtime/targets/base order/count/path and lock digest/size all fail.
- Provider substitution, missing/duplicate platform, swapped wheel platform, amended source/license/
  size/tag fields and extra wheel fail despite a locally rehashed addendum. Unknown paths are
  rejected without reading their target. Artifact source URLs never trigger a request.
- Candidate missing or changed base pin/hash, second added dependency, unused/duplicate PyNaCl hash,
  malformed requirement syntax, unsorted/noncanonical name, duplicate package and unpinned input fail.
- Per-platform missing/duplicate record, wrong version/architecture/service and unused lock hash
  are rejected. Check fixed TypeError/ValueError normalization without exposing input canaries.
- Byte-for-byte historical snapshots unchanged after all tests. No old generator/verifier or
  historical image/input claims edited; candidate files remain separate content-bound artifacts.

After focused tests, run the candidate plus existing build-input/aggregate test families once,
record exact command/counts/limits and source hashes, then independent scoped spec/quality review.
This does not require downloading all historical wheels or re-running platform qualification.

## 6. Following codec and image steps

The codec implementation may add direct `PyNaCl==1.6.2` to app/requirements.txt and install only its
hash-verified compatible development wheel after confirming the existing CFFI closure. Record
actual artifact hash, installed version/import and RFC8032 public-vector results. No existing
development package replacement or opaque dependency solving. Local success is not Linux evidence.

Before release, the actual control-plane image builder must select the complete candidate lock,
build an exact verified per-platform wheelhouse, perform offline require-hashes installation and
public verification canaries, and retain SBOM/license/provenance with actual final image digests.
Only then can the external deployment configuration select that exact CONTROL_IMAGE. If a complete
new release-input family is necessary, version its aggregate as well; never overwrite v1 history.
The separate external signing job requires its own key custody, dependency/image and observation
qualification. None are supplied by this public verifier dependency declaration.
