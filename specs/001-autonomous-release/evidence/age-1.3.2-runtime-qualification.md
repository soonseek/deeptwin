# age 1.3.2 runtime qualification evidence

Date: 2026-09-08

Outcome: the exact upstream Linux archives, copied runtime members, embedded Go module/build information, source-equivalent license texts, and native X25519 behavior passed the new offline and dual-architecture checks. This advances the age blocker, but it does **not** yet qualify the product release: the production bridge and final image do not exist yet, and legal review remains open.

## What is now closed technically

The offline verifier accepted only the exact source archive and Linux archives already pinned in `age-1.3.2.json`. It rejected unsafe archive types, bound every copied member by size, mode and SHA-256, checked ELF architecture, and parsed Go's inline build information without trusting a host Go toolchain.

Both `age` executables embed the exact six declared third-party modules. Both `age-keygen` executables embed the exact linked subset of four. On both architectures the metadata reported Go 1.27.0, `CGO_ENABLED=0`, trimpath, Linux, the declared architecture, source commit `b74dce4cdbe35b5e5f66c06d9612b72f89028758`, and an unmodified VCS tree.

The staged runtime inventory was exactly:

```text
LICENSE
age
age-keygen
```

The verifier therefore excluded `age-inspect` and all four upstream plugin executables from the staged runtime. The raw `age` program still contains plugin client code; this is reachability denial, not physical feature removal.

## License-material closure

The new technical bundle maps the Go runtime, `filippo.io/age`, and the six embedded third-party Go modules to three exact license texts. Each external module's selected text is byte-identical to its member in the pinned age source archive. The Go runtime text is byte-identical to `go/LICENSE` in the official Go 1.27.0 source archive (35,080,395 bytes, SHA-256 `7002403d7cc44529ef6d26f69a44818263395ead7c16c05a5808ae047ebeb0e5`), whose size and digest matched go.dev release metadata. The module versions and sums are also matched against the build information embedded in both binaries.

This is a complete technical inventory input, not legal approval. A project legal reviewer must still approve the redistribution disposition and the final notice presentation.

## Native dual-platform canary

The canary ran successfully in both `linux/amd64` and `linux/arm64` containers. Both used the exact Python base index `python@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254`, UID/GID `65532:65532`, a read-only root filesystem, `--network none`, all Linux capabilities dropped, `no-new-privileges`, a 64-process limit, and a 128 MiB memory limit.

Both platforms passed all of the following:

- `age --version` and `age-keygen --version` returned exactly `v1.3.2`.
- A fresh native X25519 identity encrypted and decrypted a 79-byte binary/UTF-8 payload exactly.
- A different valid identity failed with nonzero exit and emitted zero plaintext bytes.
- A one-bit ciphertext mutation failed with nonzero exit and emitted zero plaintext bytes.
- Plugin recipient, plugin identity, SSH recipient and removed GitHub/network recipient forms were rejected by the restricted caller before spawning `age`.
- A direct raw-CLI GitHub recipient check was also rejected by upstream age without output.
- Leading-PATH sentinels for `age`, `age-plugin-test`, `curl`, `wget` and `ssh` were never executed.
- The namespace exposed only loopback; an external connection attempt failed.
- The secret identity never appeared in argv. It crossed the process boundary through an owned pipe referenced as `/proc/self/fd/N` and was never logged.

The complete machine-readable result, including carrier image IDs and log hashes, is in `age-1.3.2-native-results.json`. No account, credential, persistent user key, or live network was used. Every generated test key existed only inside the disposable container process and tmpfs.

## Honest test history

The first container packaging attempt tried to copy files into a container already marked read-only; Docker rejected the copy before execution. The first native canary then exposed two harness assumptions: the release prints `v1.3.2` rather than `1.3.2`, and `age-keygen` writes comments plus the key to stdout rather than a key-only stream. Those expectations were corrected, both architectures were rerun in fresh qualification executions, and both final containers exited `0`.

## Remaining release blockers

- Implement this restricted X25519-only boundary in production and ensure agents cannot reach the raw binary, supply arbitrary argv, or discover plugins through PATH.
- Put exact archive, Sigsum, license-source and dual-platform native checks into hermetic release CI. The successful native runs used verified local temp inputs.
- Obtain legal approval for age, the Go runtime and embedded-module notices.
- Build the real final runtime image and rerun inventory, non-root, read-only, seccomp, no-network and negative tests against that exact image.

Until those four items close, `age-1.3.2.json` should remain `candidate_not_release_qualified`.
