# Fixed extension worker metadata source

2026-09-16 · ordinary-tool fixed-image profile · local measurement, not installation authority.
Authority: extension-lineage-values.md, extension-candidates.md isolation baseline, ADR-014.
This contract narrows the first fixed-image reader, not general OCI validity or all extensions.
It introduces no user approval, privileged job, writable metadata volume or execution shortcut.

## 1. Public API and limits of the result

New module `app/workers/extension_metadata.py` exports:

```python
open_worker_metadata_source() -> WorkerMetadataSource
WorkerMetadataSource.read_current(*, deadline: broker.Deadline) -> WorkerMetadataReading
WorkerMetadataSource.close() -> None
WorkerMetadataSource.closed -> bool
```

`WorkerMetadataReading` is a frozen observational dataclass with exactly `build_identity:
BuildIdentity`, `platform: str`, `uid: int`, `gid: int`. It contains actual locally sampled values;
it is not a trusted capability, successful installation, qualification or evidence of a rebuild.
Identity input hashes remain declarations. Kernel architecture does not prove unemulated execution.

The factory takes no path, pin, bytes, expected values, environment, config or callback arguments.
Direct source construction is rejected; no public FD/path/property setter, clone, copy, pickle,
deserialization or successful-proof constructor. Source supports context manager cleanup and
idempotent close. Its private resources belong only to this source, never its caller's descriptors.
A future worker owns the source from startup through handler shutdown; handlers only borrow it.
This slice does not add that startup/handler, a readiness signal, an HTTP route or a control observer.

One nonblocking internal lock serializes reads and close; overlap raises busy, never closes or
seeks a descriptor being used. Repeated close after closure succeeds. Context-manager exit closes
the source; no destructor-only lifetime. Close must attempt all owned descriptors despite one
close error and must not replace an already propagating exception. Acquisition unwinds on every
BaseException. Unexpected BaseExceptions during a read close/poison the source, then propagate;
known errors are sanitized as below. No production clock/path/ownership test mode.

## 2. Closed errors

`WorkerMetadataError` has subclasses with fixed message/code strings, no dynamic message args:

| Class | Message and code |
| --- | --- |
| WorkerMetadataUnavailable | worker_metadata_unavailable |
| WorkerMetadataInvalid | worker_metadata_invalid |
| WorkerMetadataUnsupportedPlatform | worker_metadata_unsupported_platform |
| WorkerMetadataClosed | worker_metadata_closed |
| WorkerMetadataBusy | worker_metadata_busy |
| WorkerMetadataDeadline | worker_metadata_deadline |

OSError becomes unavailable; invalid bytes/metadata/mount/process invariants become invalid.
Unsupported startup OS/architecture uses unsupported-platform; drift after opening is invalid.
Wrong deadline type is invalid. No input, path, digest, raw OSError or chained cause is exposed.
An integrity/currentness or unavailable failure closes/poisons an open source. Busy, deadline and
invalid caller deadline alone do not poison it; every next read still performs all fresh checks.
Reads after closure fail closed. Operational errors never return a partial successful reading.

## 3. Fixed paths, ownership and bounds

The measured leaves are exactly:

| Path under /opt/deeptwin-extension | Owner | Exact mode | Nonempty byte cap |
| --- | --- | --- | ---: |
| bin/worker | 0:0 | 0555 | 16777216 |
| identity/build-identity-v1.json | 0:0 | 0444 | 8192 |
| ports/tool-port-v1/config.schema.json | 0:0 | 0444 | 262144 |
| ports/tool-port-v1/request.schema.json | 0:0 | 0444 | 262144 |
| ports/tool-port-v1/result.schema.json | 0:0 | 0444 | 262144 |
| ports/tool-port-v1/error.schema.json | 0:0 | 0444 | 262144 |

Retain seven unique directory descriptors: `/`, `/opt`, the extension prefix, and its `bin`,
`identity`, `ports`, `ports/tool-port-v1`. Each is a root0:0/0755 directory, opened componentwise
with DIRECTORY/CLOEXEC/NOFOLLOW. Retain six RO/CLOEXEC/NOFOLLOW/NONBLOCK file descriptors.
Stat names without following links before open and compare again after open. Leaves must be
regular/single-link. Reject symlinks, file inode aliases, repeated directory inodes and directory/
file aliases. Track device+inode pairs, not inode alone. No enumeration of unrelated image files.

File signature includes device/inode/uid/gid/mode/nlink/size/mtime_ns/ctime_ns. Directory identity
includes device/inode/uid/gid/mode/type; unrelated directory content changes alone are not tampering.
Steady retained FDs13; source-owned transient FD count≤32. Individual read chunks≤65536B. Total
six-file byte cap17833984; schema aggregate≤1048576. Stream/hash and discard executable chunks;
retain only bounded identity/schema bytes and baseline signatures/digests, never return worker bytes.

## 4. Actual process and mount observations

Sample actual `os.uname()`: Linux only, x86_64→linux/amd64, aarch64 or arm64→linux/arm64. Real and
effective UID/GID must match, be exact nonzero integers≤4294967295. Record actual UID/GID; slot
comparison is a later listener/control responsibility. No expected request value supplies them.

Read actual `/proc/self/mountinfo` using existing bounded parsing (≤1048576B,≤4096 records).
`/` must be read-only; all seven directories and six leaves must belong to the same root mount
and device. No mount at/below the extension prefix and no intervening mount at `/opt`. An unrelated
mount under `/opt/another-product` is not itself a rejection. Reject a visible other same-device
mount whose backing root overlaps the extension prefix's root-mount backing path in either
direction. Do not count the root mount itself as an alias. Compare relevant normalized records,
not unrelated mount order. Hidden host aliases, actual container settings and image inclusion are
external facts, not claims made by this namespace observation.

Reuse `deployment.mounts` read/parse/containing/backing/device helpers where compatible; do not
use `verify_boundaries`, which requires independent mountpoints. Reuse `deployment.files` low-
level signature/check/cleanup helpers where compatible, not its caller-pinned single-file source
or directory opener that discards ancestors. Existing absence-only IPC leases are not image leases.

## 5. Acquisition and every fresh read

Factory uses a private `broker.Deadline.after_ms(1000)`, opens the exact hierarchy and measures it.
Each read requires exact `broker.Deadline`, uses its `.bounded(500)`, checks before/after every
chunk and at the final fence. Timeout is scheduling, not caller authority; regular-file syscalls
cannot be preempted by Python checks. Never claim a hard wall-clock guarantee or hold a domain
writer while reading. Later network observers must reject late replies independently.

For acquisition and reads: sample process/mount state; validate fixed paths and held FDs; read
all six complete bounded files; parse actual identity with `parse_build_identity`; hash actual
worker size/bytes against its entrypoint; use `validate_schema_bytes` on four actual role-ordered
schema bytes. Identity platform must equal measured platform. No regeneration of schema JSON.
Only the external verifier/control later compares these schemas with the qualified core schema set.

Every read reopens the fixed chain from actual `/`, comparing all named directories with retained
identities and all named leaves with retained signatures. Compare held FDs too. Require all full
bytes/digests equal their acquisition baseline and rerun pure validations. After all reads, recheck
names/FDs/mount/process state before returning. Close all transient descriptors on every path.
Reject byte-identical replacement, unlink, chmod, growth/truncation, in-place changes, ancestor
replacement, mount or effective-ID/platform drift. This final check is a finite observation,
not atomicity with container changes or continuous liveness. An error requires restart, not repair.

## 6. Verification and integration gate

New `app/tests/test_extension_worker_metadata.py` uses actual temporary directories, bytes and
descriptors. Test-only monkeypatches may redirect fixed root constants and sample ownership,
process and mount facts; they must retain actual file type, names, inode, size, mode and contents
for filesystem behavior tests. Label this simulated Linux evidence, not actual kernel/OCI proof.
No real root directories, mounts, user files, credentials or worker processes are modified.

Tests cover valid observation and stable repeated reads; exact FD accounting/cleanup; cap edges;
actual identity/schema/executable mismatches; replacement/content/mode/name/ancestor mutation;
symlink/hardlink/FIFO/directory rejection without blocking; mount alias/drift/irrelevant order;
process drift; deadlines; concurrent busy/close; partial-acquisition errors, BaseException cleanup,
close failures and noncopyable handles. Test real shipped four schema bytes including >64KiB
result schema. Unpatched non-Linux factory fails unsupported-platform before path access.
Conditional host tests report their platform limitation explicitly, never simulate Linux success.

Real Linux nonroot access, image/mount behavior, both native architectures, freshness latency,
actual image authentication and inclusion, startup/private probe/peer/HMAC composition, populated
endpoint fence and atomic installation remain separate gates. This reader cannot satisfy them.
