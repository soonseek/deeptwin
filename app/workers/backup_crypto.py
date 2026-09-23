"""The backup-crypto worker's only caller of age (T070; operations.md §5.2).

The worker image carries exactly the verified age 1.3.2 `age`/`age-keygen`
(deploy/manifests/age-1.3.2.json) and no shell. This module is the code-owned
entrypoint: it accepts only native X25519 recipients and identities (checked
before any spawn — SSH, scrypt passphrases, plugins, tags and GitHub-style
recipients never reach age), builds a fixed argv, hands a secret identity to
age only through an owned pipe descriptor (never argv, a file or the
environment), runs with an empty environment (no PATH, so no `age-plugin-*`
can be found; no HOME) and a bound wall time, and never emits secret material
in results or errors. The binaries are verified against the locked member
digests before each use. The worker runs network-none; this module does not
open sockets. The canary (deploy/tests/age_runtime_canary.py) qualifies the
same caller shape non-root in a network-none namespace.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

AGE_VERSION = "v1.3.2"
PROFILE = "age-x25519-v1"
# the locked members of age-v1.3.2-linux-{amd64,arm64}.tar.gz (deploy/manifests/age-1.3.2.json)
LOCKED_MEMBERS = {
    "x86_64": {
        "age": "eb7dd1b518f0a307c99cd97782623c5321da049154b04acd2d98d21aa7bc9b2c",
        "age-keygen": "0a0009db842259d6717f7eeb30acb6b90d2a2eb924c6acd0a0db0ca1f1537899",
    },
    "aarch64": {
        "age": "41b072352f4561018949623c674d16ef704019b9108a9bbdbd21292efebfc94f",
        "age-keygen": "00b549cebf68302893fc489830f37e706712689ca877f84d85439d700d2997c7",
    },
}
_BECH32_LOWER = "023456789acdefghjklmnpqrstuvwxyz"
RECIPIENT = re.compile(rf"age1[{_BECH32_LOWER}]{{58}}\Z")
IDENTITY = re.compile(rf"AGE-SECRET-KEY-1[{_BECH32_LOWER.upper()}]{{58}}\Z")
CIPHERTEXT_HEADER = b"age-encryption.org/v1\n"
MAX_PLAINTEXT_BYTES = 1 << 31
_TIMEOUT_SECONDS = 600


class BackupCryptoError(RuntimeError):
    """Closed failure; never carries secret material or tool output."""


def require_recipient(value) -> str:
    if type(value) is not str or RECIPIENT.fullmatch(value) is None or value.count("1") != 1:
        raise BackupCryptoError("recipient refused before age: native X25519 only")
    return value


def require_identity(value) -> bytes:
    if type(value) is not bytes:
        raise BackupCryptoError("identity refused before age: exact bytes required")
    text = value[:-1] if value.endswith(b"\n") else value
    try:
        decoded = text.decode("ascii")
    except UnicodeDecodeError:
        raise BackupCryptoError("identity refused before age: native X25519 only") from None
    if IDENTITY.fullmatch(decoded) is None or decoded.count("1") != 1:
        raise BackupCryptoError("identity refused before age: native X25519 only")
    return text + b"\n"


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


@dataclass(frozen=True, slots=True)
class AgeRuntime:
    """The verified age binaries of this worker image."""

    root: Path

    @classmethod
    def open(cls, root, *, machine=None) -> AgeRuntime:
        root = Path(root)
        machine = machine or os.uname().machine
        expected = LOCKED_MEMBERS.get(machine)
        if expected is None:
            raise BackupCryptoError("no locked age build for this platform")
        for name, digest in expected.items():
            path = root / name
            if path.is_symlink() or not path.is_file():
                raise BackupCryptoError("the locked age binaries are not installed")
            observed = _digest(path)
            if observed != digest:
                raise BackupCryptoError("an age binary differs from its locked digest")
        runtime = cls(root)
        for name in ("age", "age-keygen"):
            result = runtime._run([name, "--version"])
            if result.stdout.strip() != AGE_VERSION.encode():
                raise BackupCryptoError("an age binary reports another version")
        return runtime

    def _run(self, argv, *, stdin=b"", pass_fds=(), stdout=None):
        binary = self.root / argv[0]
        try:
            return subprocess.run(
                [str(binary), *argv[1:]], input=stdin, stdout=stdout or subprocess.PIPE,
                stderr=subprocess.DEVNULL, env={}, pass_fds=tuple(pass_fds), close_fds=True,
                check=True, timeout=_TIMEOUT_SECONDS,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            raise BackupCryptoError(f"age {argv[1]} failed") from None

    def generate(self) -> tuple[bytes, str]:
        """A fresh native identity and its recipient; the secret stays in memory."""

        output = self._run(["age-keygen"]).stdout
        lines = [line for line in output.splitlines() if line.startswith(b"AGE-SECRET-KEY-1")]
        if len(lines) != 1:
            raise BackupCryptoError("age-keygen produced no single native identity")
        identity = require_identity(lines[0])
        return identity, self.recipient_of(identity)

    def recipient_of(self, identity: bytes) -> str:
        identity = require_identity(identity)
        with _SecretPipe(identity) as fd:
            output = self._run(["age-keygen", "-y", f"/proc/self/fd/{fd}"], pass_fds=(fd,)).stdout
        return require_recipient(output.decode("ascii").strip())

    def encrypt(self, plaintext: bytes, recipient: str) -> bytes:
        recipient = require_recipient(recipient)
        if type(plaintext) is not bytes or len(plaintext) > MAX_PLAINTEXT_BYTES:
            raise BackupCryptoError("the plaintext is out of bounds")
        ciphertext = self._run(["age", "--encrypt", "--recipient", recipient], stdin=plaintext).stdout
        if not ciphertext.startswith(CIPHERTEXT_HEADER):
            raise BackupCryptoError("age produced an unexpected ciphertext format")
        return ciphertext

    def decrypt(self, ciphertext: bytes, identity: bytes) -> bytes:
        """The full authenticated plaintext, or a closed failure (never partial)."""

        identity = require_identity(identity)
        if type(ciphertext) is not bytes or not ciphertext.startswith(CIPHERTEXT_HEADER):
            raise BackupCryptoError("the input is not a native age ciphertext")
        with _SecretPipe(identity) as fd:
            return self._run(["age", "--decrypt", "--identity", f"/proc/self/fd/{fd}"],
                             stdin=ciphertext, pass_fds=(fd,)).stdout


class _SecretPipe:
    """An owned pipe whose read end hands one identity to one child."""

    def __init__(self, secret: bytes):
        self._secret = secret
        self._read = self._write = -1

    def __enter__(self) -> int:
        self._read, self._write = os.pipe()
        try:
            os.write(self._write, self._secret)
        finally:
            os.close(self._write)
            self._write = -1
        return self._read

    def __exit__(self, *_exc):
        if self._read >= 0:
            os.close(self._read)
            self._read = -1


__all__ = [
    "AGE_VERSION",
    "PROFILE",
    "AgeRuntime",
    "BackupCryptoError",
    "require_identity",
    "require_recipient",
]
