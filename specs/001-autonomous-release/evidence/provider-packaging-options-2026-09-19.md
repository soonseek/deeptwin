# Private provider worker packaging options — advisory

- Date: 2026-09-19
- Status: research advisory; no package, image, native measurement, qualification, or digest was
  produced
- Scope: Linux `amd64` and `arm64` packaging for the private no-network provider transformer
- Primary-source snapshot: official documentation available on 2026-09-19. The repository does
  not currently pin any of the packaging tools discussed below, so a later implementation must
  pin and verify the selected version rather than treating these moving docs as build inputs.

## Recommendation

**Correction:** the [standard-CPython OCI addendum](#addendum--standard-cpython-in-an-exact-oci-image)
supersedes the initial recommendation in this section. A locally rehashed one-folder manifest is
optional if a qualified external operator authenticates, verifies, and immutably launches the exact
final platform image under the closed conditions in that addendum.

Do **not** accept the current single-file `bin/worker` hash as proof of the Python worker's executed
closure. Prefer a PyInstaller **one-folder** bundle installed on the read-only image, plus a new
canonical, ordered closure manifest whose fixed paths, file sizes, modes, and SHA-256 values are
measured locally. Keep `/opt/deeptwin-extension/bin/worker` and its current argv, and keep the
16 MiB limit as a limit on that launcher executable only. Set a separate aggregate closure limit
from actual dual-architecture builds; do not invent one now.

This is the smallest robust correction because it avoids one-file runtime extraction, preserves the
existing entrypoint path, and makes imported Python modules, the bundled CPython runtime, and needed
non-system shared objects visible to the metadata reader. The exact platform OCI manifest/index
digest must remain the authority for the complete image, including the base runtime and system
libraries. Local entrypoint/closure measurements are supporting observations, not substitutes for
that digest.

No evaluated mechanism is currently proven to satisfy the existing stronger interpretation — “the
one measured file is at most 16 MiB and covers every executed Python/native dependency”:

- `zipapp` does not include the interpreter and cannot import native extension modules from the
  archive.
- PyInstaller and Nuitka one-file modes can embed application/runtime material, but both unpack
  support files before execution; neither has a repository-pinned builder nor an actual per-platform
  size result here. PyInstaller also deliberately relies on the target's `libc` on GNU/Linux.

Consequently the honest current result is **contract correction required before packaging
implementation**, not a completed package, an asserted 16 MiB fit, or a final image digest.

## Repository constraints and existing inputs

The [private worker contract](../contracts/private-provider-worker.md) fixes:

- `/opt/deeptwin-extension/bin/worker`, mode `0555`, nonempty and at most 16 MiB;
- separate identity and four provider-port schema files, with a 17,833,984-byte aggregate across
  those six measured files;
- Linux `amd64` and `arm64` identities;
- fresh hashing of the executable and schema files; and
- the requirement that every executed parser/helper be in the measured image/executable closure,
  explicitly rejecting a small launcher that imports unmeasured modules.

That file model is inherited from the tracked
[extension worker metadata contract](../contracts/extension-worker-metadata.md), whose reader hashes
and discards only `bin/worker` bytes and does not enumerate other image files. The tracked
[lineage value contract](../contracts/extension-lineage-values.md) separately models OCI index,
platform manifest, config, and ordered layer descriptors and states that parsing local structural
values is not image authentication or installation authority.

The current build inputs do not close this new package:

- [the lock README](../../../deploy/locks/README.md) defines separately verified per-platform
  wheelhouses installed with `--require-hashes --no-index`, but says these are inputs and not final
  service-image digests;
- [`service-roots.json`](../../../deploy/locks/service-roots.json) calls the existing profile
  `credentialed-provider-gateway`, includes the Anthropic/HTTP/PyNaCl/HTTP stacks, and still has
  `qualified_base: null`; the private transformer contract forbids importing the SDK, HTTP client,
  key store, or gateway adapter graph;
- [pyproject.toml](../../../pyproject.toml) declares the whole repository dependency set and
  `package = false`; it is not a frozen-worker recipe; and
- neither the project metadata nor deployment locks/manifests contain `PyInstaller`, `Nuitka`,
  `shiv`, or a dedicated private-transformer root set.

The existing provider lock therefore must remain byte-identical. A selected freezer, its own
transitive build inputs, the exact CPython/base inputs it consumes, and the smaller private-worker
runtime roots require a new additive lock/profile. Reusing the credentialed gateway closure would
both broaden the worker and contradict the contract's import boundary.

## Authority split

| Evidence | What it can honestly establish | What it cannot establish |
| --- | --- | --- |
| Local `bin/worker` size/hash | Exact bytes of that one fixed file at the time sampled | Imported files beside it, system loader/`libc`, the rest of the image, an OCI identity, or that the process was launched from an approved image |
| Proposed closure manifest plus fresh file measurement | Exact enumerated frozen-bundle files, including packaged Python modules/runtime and non-system `.so` files | Unlisted base-image/system files, kernel behavior, OCI provenance, native execution, or approval |
| Exact OCI index/platform manifest/config/layer descriptors, independently retrieved and verified | Content-addressed complete platform image graph; OCI descriptors carry media type, digest, and byte size, and an index selects platform manifests | Trust in an unauthenticated digest value, semantic correctness, successful staging, or live worker behavior |
| Build identity/input hashes | Declared source, recipe, and dependency inputs joined to produced bytes by a qualified build/verifier | Proof that a build ran merely because declarations parse |
| Unit/import-graph tests and fixture bundle reports | Code/build-recipe behavior and rejection of missing or forbidden entries | Native package size, ELF dependency resolution, image contents, or final OCI digests |

The OCI distinction is substantive: the official OCI image specification defines an image as a
manifest, optional index, configuration, and filesystem layers, and defines descriptors as
content-addressed references carrying digest and size. A platform entrypoint hash is not that graph.
See the [OCI Image Specification overview](https://github.com/opencontainers/image-spec/blob/main/spec.md)
and [OCI descriptor digest rules](https://github.com/opencontainers/image-spec/blob/main/descriptor.md).
Repository composition likewise requires exact `@sha256:` image references in
[`deploy/compose.yaml`](../../../deploy/compose.yaml); no such final provider-worker reference was
created by this research.

## Mechanism comparison

### 1. Standard-library `zipapp`: reject for this contract

Python's `zipapp` creates an executable ZIP containing `__main__.py`; an optional shebang names the
interpreter, and deflate compression can reduce archive size. It is “standalone” only on a machine
with the appropriate interpreter. The official documentation is explicit that a dependency with a
C extension cannot run from the ZIP and must be installed or shipped outside it. `zipimport`
likewise disallows `.so`/`.pyd` imports. See the CPython 3.12 documentation for
[`zipapp`](https://docs.python.org/3.12/library/zipapp.html) and
[`zipimport`](https://docs.python.org/3.12/library/zipimport.html).

This could produce a small `bin/worker`, but its hash would cover neither CPython/stdlib code loaded
from the image nor external native modules. It therefore fails the present measured-file model in
exactly the prohibited “small launcher plus mutable/unmeasured runtime” way. It becomes defensible
only if the contract adds those external runtime files to a measured closure manifest, at which
point a frozen one-folder bundle has the clearer inventory.

### 2. PyInstaller: best fit after the closure-manifest correction

PyInstaller recursively analyzes imports, collects Python modules, the active interpreter, and
binary dependencies, and can emit either a folder or one executable. Dynamic imports and data can
escape automatic analysis and must be declared through hidden imports, hooks, binaries, or data in
the spec. Its `Analysis` result explicitly separates scripts, pure modules, binaries, and data, which
is a useful basis for a fail-closed inventory. See official
[operating-mode documentation](https://pyinstaller.org/en/stable/operating-mode.html) and
[spec-file/Analysis documentation](https://pyinstaller.org/en/stable/spec-files.html).

Important limits:

- output is specific to the build operating system, Python version, and word size; Linux `amd64`
  and `arm64` therefore require separate native target builds and reports;
- one-file mode embeds the archive, but the bootloader creates a temporary directory and extracts
  Python/native support files before running them; a `noexec` temporary filesystem is incompatible
  unless the deployment supplies a deliberate executable extraction location;
- PyInstaller does not bundle GNU `libc`, so even one-file output is not a total Linux execution
  closure; the qualified base image must supply and attest that system boundary; and
- import analysis can miss dynamic imports, so a successful build alone is insufficient.

These are documented in PyInstaller's
[one-file execution description](https://pyinstaller.org/en/stable/operating-mode.html#how-the-one-file-program-works),
[runtime temporary-directory guidance](https://pyinstaller.org/en/stable/usage.html#defining-the-extraction-location),
and [GNU/Linux compatibility notes](https://pyinstaller.org/en/stable/usage.html#making-gnu-linux-apps-forward-compatible).
PyInstaller also provides `pyi-archive_viewer` for inspecting a produced archive, but that inspection
must be joined with the build's Analysis inventory and ELF dependency inspection rather than treated
as independent provenance; see the official
[archive inspection documentation](https://pyinstaller.org/en/stable/advanced-topics.html#using-pyi-archive-viewer).

**Assessment:** use one-folder mode, install the entire folder on the read-only image, and measure
its complete ordered inventory. Do not choose one-file merely to preserve the current schema: no
authorized native build has shown `<=16 MiB`, its extraction conflicts with a `noexec` temporary
policy, and its residual system-library boundary still belongs to the image.

### 3. Nuitka standalone/one-file: viable fallback, not the smallest input change

Nuitka can create standalone or one-file programs independent of an installed Python. Standalone
mode follows imports by default; dynamic imports and package data may still require explicit
inclusion, and the official docs warn that package-data handling may be incomplete. One-file mode is
standalone plus a self-extractor that unpacks to a temporary directory before running. Its compiler
and Python architectures must match. See the official
[Nuitka user manual requirements](https://nuitka.net/user-documentation/user-manual.html#requirements)
and [standalone/one-file use cases](https://nuitka.net/user-documentation/use-cases.html#standalone-program-distribution).

Nuitka could be revisited if measured PyInstaller bundles miss the final size or performance target,
but it introduces a C compiler/toolchain and Nuitka-specific build inputs and compiles the program
rather than only freezing it. The repository pins none of that today. It also does not remove the
need for per-architecture native builds, an explicit collected-file/dependency report, image-level
system-library evidence, or the closure-manifest correction. There is no evidence here that its
one-file output fits 16 MiB.

## Smallest contract correction

Revise provider BuildIdentity v2 and the fixed metadata reader before assigning the package builder:

1. Keep `entrypoint:{sha256,size_bytes}` and `/opt/deeptwin-extension/bin/worker`; interpret it only
   as the directly executed launcher and retain the existing 16 MiB per-file cap.
2. Add one fixed, root-owned, read-only canonical `worker-closure-v1` manifest leaf, itself named and
   hashed by the identity. It has a closed ordered list of fixed relative paths under the extension
   prefix with file kind, exact mode, size, and SHA-256, plus an aggregate size. No globs, caller
   paths, optional fallbacks, symlinks, hardlink aliases, or dynamically discovered additions.
3. Make fresh local metadata reads open and hash every manifest entry with the same descriptor,
   ownership, mount, currentness, and alias protections as the existing six files. Listener
   publication fails if any entry is absent, extra-to-the-frozen-inventory, replaced, or mismatched.
4. Populate the manifest from the freezer's explicit scripts/pure/binaries/data inventory and
   independently compare it with the installed image filesystem. Include bundled CPython, stdlib
   archives/modules, imported application modules, native extension modules, and copied non-system
   shared libraries. Do not list test-only modules or the network/credential SDK graph.
5. Give the manifest file count, individual and aggregate byte bounds, retained/transient FD bounds,
   and acquisition/read budgets derived from reviewed native `amd64` and `arm64` inventories and
   timings. A one-folder reader cannot silently inherit the present six-leaf 13-steady-FD,
   32-transient-FD, 500 ms model. Until those results exist, the schema cannot claim truthful final
   bounds.
6. State the residual boundary: the ELF loader, `libc`, other deliberately base-provided system
   libraries, and the kernel are covered by exact qualified per-platform image/base evidence and
   native inspection, not by the local closure-manifest claim.

If the controller instead insists on one measured file, it must separately authorize an executable,
bounded extraction filesystem and replace the 16 MiB cap with a bound justified by actual native
outputs. That is a larger security/runtime change and is not recommended.

## Work that can be implemented now

After approving the correction and choosing a freezer version, repository-local code can:

- add a dedicated private-transformer package profile without modifying the historical
  credentialed-provider gateway or tool-image pins;
- define a deterministic PyInstaller spec and offline build recipe that accepts only an explicitly
  verified per-platform wheelhouse/tool input set and performs no resolution or download;
- add an exact private-worker module/root allowlist and fail the build for forbidden gateway,
  network, credential, test, or unexpected dynamic-import entries;
- normalize and verify the freezer Analysis inventory, archive listing, installed-file closure
  manifest, ELF dependency report, and entrypoint/schema/identity assembly;
- make missing modules, unresolved shared objects, undeclared files, wrong architecture, cap
  overflow, or inventory drift hard failures; and
- test parsers, deterministic manifests, negative fixtures, and refusal paths without claiming a
  successful native package.

The new package profile must pin the selected freezer and every added build dependency explicitly.
That is an additive reviewed input decision, not permission to edit the existing provider lock or
to use the latest tool from the network.

## Work requiring separate authority and native evidence

The following remain operational gates and cannot be completed by source/unit work:

- provision the exact verified CPython, freezer, bootloader/compiler, wheelhouse, base-image, and
  native inspection inputs for each platform;
- run isolated native Linux `amd64` and `arm64` builds;
- measure actual launcher and aggregate sizes, inspect packaged imports and ELF dependencies, and
  exercise the no-network worker from the assembled read-only filesystem;
- verify the selected glibc floor and other base-provided libraries against the exact platform image;
- assemble and inspect the real OCI index, platform manifests, config, and layers, then record their
  actual digests and sizes;
- authenticate/approve the allowed image manifest, provision operator trust/keys, stage the image,
  and collect live postconditions.

No placeholder digest, test-success fixture, small launcher hash, source-tree import test, or local
build-input declaration may be promoted into those results.

## Initial decision path (superseded by the addendum)

1. Approve the closure-manifest correction and retain the 16 MiB cap only for the launcher.
2. Select and additively pin PyInstaller and its complete build inputs; keep existing locks intact.
3. Implement the offline one-folder recipe plus fail-closed inventory/manifest verifiers.
4. Commission native dual-architecture builds to determine real caps and close runtime/ELF checks.
5. Only after real image assembly and independent OCI verification, record the exact image
   index/platform digests and consider staging/qualification.

## Addendum — standard CPython in an exact OCI image

This addendum corrects the recommendation above. It was too strong to say that a local
multi-file closure manifest is required if “measured image/executable closure” permits the image
side of that disjunction. The existing metadata contract already says its six-file observation is
not image authentication, and the private worker contract calls actual image inclusion/native
measurement an external gate. Under a closed external authority chain, a standard CPython image
with a small measured launcher can satisfy the contract without PyInstaller, without a new freezer,
and without expanding the local reader's FD or 500 ms hashing budget.

The corrected preference is therefore conditional:

- **Prefer the standard-CPython image profile** if the final provider-worker OCI image is produced
  and inspected from exact inputs, selected by exact platform manifest digest from an authenticated
  allowed-image record, and started only by a qualified external stage operator with a read-only
  root and no import-path overlays.
- **Prefer the one-folder closure-manifest profile** only if the design requires the worker itself to
  remeasure its imported application/runtime files independently of the stage operator, or if a
  deliberately reduced frozen runtime is needed for attack-surface reasons.

Neither profile is qualified today. This addendum records a viable architecture and the authority
it requires; it does not turn the pinned base into a final DeepTwin worker image.

### Why the OCI profile can meet the closure requirement

The repository already pins an official Python `3.12.14-slim-bookworm` upstream image index and
separate `linux/amd64` and `linux/arm64` manifest/config/layer descriptors in
[`upstream-images.json`](../../../deploy/manifests/upstream-images.json). It also pins Python wheel
artifacts and offline `--require-hashes --no-index` installation inputs. Those are useful build
inputs, but not final-image authority:
[`service-roots.json`](../../../deploy/locks/service-roots.json) still says `qualified_base: null`,
the upstream-image record is `candidate_not_release_qualified`, its
[provenance result](upstream-image-provenance-results.json) explicitly is not signature verification
or a final-image SBOM, and final DeepTwin image indexes remain later T081 outputs.

OCI supplies the content boundary needed for the broader claim. An image manifest references the
configuration and ordered filesystem layers by content descriptor; the configuration records
execution parameters and rootfs layer hashes. A verified digest therefore commits to the selected
image graph, not only to a launcher. See the official
[OCI Image overview](https://github.com/opencontainers/image-spec/blob/main/spec.md),
[manifest format](https://github.com/opencontainers/image-spec/blob/main/manifest.md), and
[image configuration](https://github.com/opencontainers/image-spec/blob/main/config.md).

That integrity statement is sufficient only when joined to trust and runtime enforcement:

1. A qualified verifier inspects the actual final filesystem and binds the fixed launcher,
   application modules/data, CPython/stdlib, native extensions/shared libraries, interpreter
   configuration, dependency inventory, source/recipe inputs, and selected parent-image descriptors
   to the produced final platform manifest.
2. An authenticated allowed-image manifest (or equivalently reviewed signed authority) names the
   exact final index and both platform entries. A caller-supplied digest, a tag, or parsing lineage
   bytes is not trust.
3. Before creating or starting the container, the qualified external stage operator selects the
   host platform, independently retrieves and verifies descriptor media type, size, and digest for
   the index, selected manifest, config, and ordered layers, and requires equality with that
   authenticated authority.
4. The stage operator launches that digest with the fixed command, UID/GID, environment, working
   directory, `network_mode: none`, read-only root, and only the declared broker socket mount. It
   rejects overlay/bind/volume mounts at the Python prefix, application tree, extension prefix, or
   any other importable path, and rejects loader/import overrides such as `LD_PRELOAD`,
   `LD_LIBRARY_PATH`, and `PYTHON*`. OCI runtime `root.readonly` makes the root filesystem read-only,
   but additional `mounts` are a separate mechanism and therefore must be checked explicitly; see
   the official [OCI Runtime configuration](https://github.com/opencontainers/runtime-spec/blob/main/config.md#root).
5. Python starts through a fixed interpreter path in isolated mode, with no caller-controlled
   `PYTHON*` variables, user site, current/script directory, writable path, editable install, or
   unreviewed `.pth`/`sitecustomize` source in import resolution. CPython documents that `-I`
   excludes the current/script directory and user site and ignores all `PYTHON*` variables; the
   remaining system `site` behavior and every admitted path still require final-image inspection.
   See [CPython command-line isolated mode](https://docs.python.org/3.12/using/cmdline.html#cmdoption-I)
   and [module-search-path initialization](https://docs.python.org/3.12/library/sys_path_init.html).
6. The operator's signed receipt and an authenticated live worker postcondition join the launched
   image/platform/command/isolation facts back to the admitted descriptor. The worker does not gain
   a caller-supplied digest argument and does not mint image authority from its identify reply.

Under those conditions, the exact final image is the measured executed-code closure. The small
`bin/worker` hash is merely a fresh local observation of the selected entrypoint inside that image;
it is not promoted into proof of CPython or imported modules. The build-time file/import inventory
supports review, omission detection, and source-to-image linkage, but also is not authority by
itself. The authenticated exact OCI graph and qualified stage/runtime observation carry that role.

### Residual trust and attack surfaces

| Boundary | Standard CPython exact-image profile | Residual risk / required refusal |
| --- | --- | --- |
| Build inputs | Existing exact Python base descriptors and wheel artifacts avoid a new freezer dependency | They do not prove the final build ran, used only those inputs, or omitted gateway packages; a qualified final-image verifier must join inputs to output |
| Application/dependency inventory | Offline inventory can enumerate final application files, distributions, native extensions, linked libraries, `.pth`/customization files, and expected import paths | Static/module inventory does not prove which code a dynamic path executes or that code is safe; reject unexplained files/import paths and retain runtime canaries/code review |
| Registry/image bytes | Exact OCI descriptor verification detects byte substitution and commits to config plus ordered layers | A digest from an untrusted request authenticates nothing; require an authenticated allowed-image authority and verify retrieved bytes independently |
| Platform selection | Exact index plus selected platform manifest prevents accepting only a convenient architecture | Index equality alone is insufficient; reject missing, reordered, unknown, or mismatched `amd64`/`arm64` entries and verify config/layers |
| Stage operator/runtime | Trusted operator verifies authority before startup and fixes command, identity, network, root, and mounts | A compromised operator/container runtime can launch another rootfs, add an overlay, or falsify a receipt; qualification, narrow keys, actual postconditions, and host/runtime gates remain required |
| Python/native resolution | Fixed interpreter plus isolated mode, closed loader/import environment, and a reviewed immutable image deny environment/user/current-directory injection | System `site`, `.pth`, `sitecustomize`, namespace packages, dynamic imports, `LD_*` loader controls, and writable paths remain hazards unless explicitly absent or reviewed in the final image |
| Runtime filesystem | Read-only root and no import-path mounts prevent ordinary in-container mutation of image code | Read-only root alone does not forbid additional mounts; tmpfs/socket volumes must not become importable, and host/kernel/runtime compromise is outside this claim |
| Local six-file reader | Continues to detect replacement/drift of launcher, identity, provider schemas, extension prefix mounts, UID/GID, and platform with its existing caps | It does not detect mutation/substitution elsewhere in CPython or the image and must not report image qualification, import-closure verification, or OCI identity |
| Live process | Authenticated worker handshake links the running component to local build/schema values | It does not itself prove the container image digest; the controller must join it with the retained stage record/receipt and selected image lineage |

The image profile intentionally trusts more external machinery than a local closure manifest. In
exchange it avoids runtime extraction, freezer hooks, a new native/freezer toolchain, and a large
per-read local hash set. It also retains more of the normal CPython/base-image surface. A malicious
but digest-stable file in a trusted image remains malicious; content addressing supplies identity,
not semantic safety.

### Contract delta versus the one-folder manifest profile

| Contract area | Standard CPython exact-image profile | PyInstaller one-folder closure-manifest profile |
| --- | --- | --- |
| `bin/worker` and 16 MiB cap | Unchanged; explicitly a launcher-only local claim | Unchanged launcher cap, plus a new manifest for adjacent frozen files |
| BuildIdentity v2 | No per-import file list required; entrypoint remains one declared/measured file | Add a hashed closure-manifest leaf/role and aggregate/file-count bounds |
| Local metadata reader | Keep six leaves, 13 steady FDs, at most 32 transient FDs, and current acquisition/read budgets | Traverse and rehash the frozen bundle; derive new file-count, size, FD, and timing limits |
| Import/runtime closure authority | Authenticated exact final OCI platform graph plus qualified final-image inspection and stage enforcement | Local frozen-file manifest for application/runtime files, still joined to exact OCI/base evidence for system files |
| New build inputs | No freezer; use the already pinned Python base/wheel inputs and add only a private-worker root/layout/recipe record | Add and pin PyInstaller, bootloader/build dependencies, spec/hooks, and per-platform freezer outputs |
| Operator dependence | Strong: correctness depends on pre-start digest verification, no overlays/import mounts, fixed runtime config, and retained receipt | Still required for image/base identity and isolation, but local reader independently detects frozen-bundle file drift |
| Runtime/import surface | Normal inspected CPython image; potentially larger stdlib/base surface | Potentially smaller selected bundle, subject to hidden-import/hook completeness |

The exact-image profile therefore needs **less local metadata change** than the earlier recommendation,
but more explicit source/stage contract text. The following is the smallest defensible correction:

1. In the private worker packaging paragraph, define two separate claims: `entrypoint_measurement`
   covers only `bin/worker`; `executed_image_closure` covers the exact selected final OCI platform
   manifest/config/ordered layers after qualified inspection. State explicitly that neither claim
   substitutes for the other.
2. Preserve the no-argument local metadata factory and all present six-file/FD/deadline bounds.
   Do not add the OCI digest to the identify DTO unless it comes from a separately authenticated
   controller-side stage record; never accept it from worker argv/environment/request data.
3. In the future provider source/lineage contract, require the actual final image index and both
   complete platform entries, final-filesystem inventory digest, exact parent Python base entry,
   private-worker source/recipe/dependency-input digests, and the fixed command/import policy.
   These are absent until produced; no default or test digest is allowed.
4. In the stage-operator contract, require an authenticated allowed-image authority, independent OCI
   descriptor verification, exact host-platform selection, launch by digest, read-only root, closed
   mount list with no import-path overlays, fixed argv/env/cwd/UID/GID, isolated Python mode, no
   network, and an actual signed receipt. An opaque caller digest is rejected before any effect.
5. In admission/acceptance, join the operator's retained selected-image evidence to the subsequent
   authenticated live provider identity/build/schema observations. Local listener publication can
   remain a worker-readiness event only; it must not become image qualification or admission.
6. In the offline builder/verifier, generate and validate an exact application/dependency/image
   inventory and native import/ELF report for both platforms, but label it supporting build evidence.
   Only the resulting verified final-image descriptors, trusted stage receipt, and live join can
   authorize use.

With that wording, the standard locked-CPython OCI design is a defensible and likely smaller
architecture correction than the one-folder manifest. The manifest profile remains optional
defense in depth rather than a prerequisite. Actual final-image construction, inspection, signing,
operator qualification, native dual-platform execution, and digest production remain separately
authorized work.
