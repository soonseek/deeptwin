# Shared fixed provider source observation

Controller contract, 2026-09-19. Spec authority: ../spec.md; layout/bytes/policies are exactly
provider-source-production.md. This is Task36's shared READ-ONLY mechanism, reused unchanged by
Task37's runtime context. Independent scoped preflight precedes implementation.
File: app/deployment/_provider_source_files.py. No source discovery, publication, source admission,
journal, credential, network or arbitrary-path behavior. The initializer operations helper alone
owns staging/rename. Do not copy its observation/snapshot algorithms into either client.

## Exact internal interfaces

    _open_provider_bundle(
        root: Directory, *, context_sha256: str,
    ) -> _RetainedProviderBundle

    _RetainedProviderBundle.read_current() -> tuple[tuple[str, bytes], ...]
    _RetainedProviderBundle.recheck_current() -> None
    _RetainedProviderBundle._object_identities() -> tuple[
        FileIdentity, tuple[tuple[str, FileIdentity], ...]
    ]
    _RetainedProviderBundle.close() -> None

    _snapshot_provider_namespace(
        directory: Directory, *, namespace: str,
    ) -> _ProviderNamespaceSnapshot

`root` is borrowed, exact-type Directory with the one fixed provider-stage-sources path and
0:21201/0750 metadata; its caller retains/closes it. No path argument, root discovery or virgin-root
acceptance. Bundle owns only the documents Directory and18 regular-file FDs. It rechecks the borrowed
root and all names/signatures on every read; use-after-root-close fails. Opening/closing the bundle
must never close the borrowed root. No public constructor, alternate filename table, cap/policy
override, callback or prevalidated dictionary. Construction failures close all acquired children,
preserving the primary; lifecycle semantics remain the Task36 bounded checkpoint contract.

`_object_identities()` first checks currentness and returns only the documents identity followed by
the18 ordered `(filename, identity)` pairs. It is a private transfer/comparison aid, not an authority
record or exposed FD. The shared handle never accepts replacement identities or rebinds itself.
It only observes final documents/; the operations helper owns every staged-path transition.

`namespace` is exactly one of cancelled,requests,receipts,consumed. The helper selects the code-owned
policy from provider-source-production.md §4 and requires the Directory's exact corresponding fixed path/owner/group/mode. It
borrows the directory and opens no channel leaf. `_ProviderNamespaceSnapshot` is a frozen private
value with fields `directory_signature`, `entries` (sorted tuple of name/stat-signature pairs),
`final_count`, `stage_count`; no bytes or admission properties. Capture all entries before/after
unchanged _scan_namespace and require equality. The caller owns aggregate240 checks and comparison
timing. Task36 compares with its initial preflight baseline throughout initialization; Task37 takes
fresh per-operation before/after snapshots and permits safe changes between operations. Sharing the
mechanism does not conflate those different lifecycle policies.

### Cold read versus expected-byte verification

The former `_open_bundle(root, expected_files)` alone is not a sound bootstrap interface for Task37:
runtime does not yet know expected source bytes. Reading a directory and feeding those same bytes
back as "expected" would prove no pin or graph binding. Do not do that, and do not add a trust flag.

The shared reader starts from the independently supplied strict context_sha256 scalar. It opens
source-context.json first under its fixed cap, retains its FD and name/signature, and checks actual
bytes against that pin. It then opens only the other17 fixed filenames, assembles the exact ordered
tuple, calls Task35's validate_provider_source_bundle on those bytes, and repeats retained-root,
documents/leaf membership/signature/byte checks before returning. Full validation closes every
original/provider reference, including pins/context, without needing any caller expected tuple.
Subsequent reads must equal those original retained bytes and signatures; no refresh/rebase.

Task37 supplies the immutable startup pin, then performs its additional owner-profile/native and
actual-five-original-sources joins. No operator image or admitted request is used as a substitute.

Task36 supplies `digest(artifacts.context_bytes)` from its real retained-input rerender, NOT a hash
computed from target-root contents. Immediately require the shared reader's complete tuple equals
`artifacts.bundle_files` byte-for-byte. This preserves the initializer's stronger expected-output
test instead of reducing it to internal graph consistency. Perform both checks for an existing
owned static root and for the final published tree; no comparison uses a self-derived target oracle.

For virgin publication, retain the staged directory and leaf identities in _BundlePublication.
Give that private publication handle `_object_identities()` with the same return shape as the
reader: it derives identities from its still-owned directory/leaf FDs, not a caller-supplied tuple,
and must not re-open the obsolete staging pathname after rename.
After no-replace rename, root metadata finalization and original root-identity proof, open final
documents/ through the shared reader and compare `_object_identities()` with the still-retained
publication identities, then compare full bytes with renderer output. Only after both succeed may
the orchestrator transfer ownership to the final observation and close staging handles. Reopening
equal bytes at substituted inodes must fail. The shared reader does not perform rename, chmod,
chown, fsync, adoption of unverified caller identities or cleanup of filesystem remnants.

## Bounds, errors and tests

All18 fixed filenames/caps/order,524288-byte aggregate, root/document/leaf metadata and namespace
policies come from source-production.md. Policy selection is code-owned here, not duplicated in
initializer or runtime clients. Total caller-owned liveFD budget256 includes overlapping staged
and final handles during initializer transfer. Borrowed roots/namespaces are never closed.
Invalid exact types, hollow/forged/subclass handles, closed handles, badpins, changed bytes/names/
signatures or borrowed-root closure refuse with fixed DeploymentSourceError. Ordinary filesystem/
native unavailability retains the existing error-family distinctions. No reflective path/content
errors. No BaseException swallowing: preserve primary and attempt all owned closes as specified
by source-initialization.md. Returned bytes/identities/snapshots grant no operation authority.

Task36's test_provider_source_init.py covers actual independently pinned cold reads, wrong pin,
valid alternate internally-consistent bundle against the initializer's stronger expected output,
same-byte inode substitution, borrowed-root survival, partial leaf-acquisition cleanup, complete
final/stage snapshots and staged-to-final retained identity equality. Positive tests execute actual
I/O and complete bundle validation, not a mocked successful observer. Task37 adds startup ownership
and different within-call/between-call snapshot timing tests without duplicating this mechanism.

