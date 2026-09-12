#!/usr/bin/env python3
"""Native, account-free qualification canary for the restricted age runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import tempfile
from typing import Any


BECH32_LOWER = "023456789acdefghjklmnpqrstuvwxyz"
BECH32_UPPER = BECH32_LOWER.upper()
NATIVE_RECIPIENT = re.compile(rf"^age1[{BECH32_LOWER}]{{58}}$")
NATIVE_IDENTITY = re.compile(rf"^AGE-SECRET-KEY-1[{BECH32_UPPER}]{{58}}$")
PLATFORM_MACHINE = {"linux/amd64": "x86_64", "linux/arm64": "aarch64"}


class CanaryFailure(RuntimeError):
    pass


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run(
    argv: list[str],
    *,
    env: dict[str, str],
    input_bytes: bytes = b"",
    pass_fds: tuple[int, ...] = (),
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        pass_fds=pass_fds,
        check=False,
        timeout=15,
    )


def require_success(result: subprocess.CompletedProcess[bytes], label: str) -> None:
    if result.returncode != 0:
        raise CanaryFailure(
            f"{label}: exit {result.returncode}, stderr SHA-256 {digest(result.stderr)}"
        )


def validate_recipient(value: str) -> None:
    if not NATIVE_RECIPIENT.fullmatch(value) or value.count("1") != 1:
        raise ValueError("recipient rejected before age: native X25519 only")


def validate_identity(value: bytes) -> None:
    try:
        text = value.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("identity rejected before age: ASCII native X25519 only") from error
    if text.endswith("\n"):
        text = text[:-1]
    if not NATIVE_IDENTITY.fullmatch(text) or text.count("1") != 1:
        raise ValueError("identity rejected before age: native X25519 only")


def extract_generated_identity(value: bytes) -> bytes:
    candidates = [line.strip() for line in value.splitlines() if line.startswith(b"AGE-SECRET-KEY-1")]
    if len(candidates) != 1:
        raise CanaryFailure("key generation: expected exactly one native secret-key line")
    validate_identity(candidates[0])
    return candidates[0]


def safe_encrypt(age: Path, recipient: str, plaintext: bytes, env: dict[str, str]) -> bytes:
    validate_recipient(recipient)
    result = run(
        [str(age), "--encrypt", "--recipient", recipient],
        env=env,
        input_bytes=plaintext,
    )
    require_success(result, "encrypt")
    if not result.stdout.startswith(b"age-encryption.org/v1\n"):
        raise CanaryFailure("encrypt: unexpected ciphertext format")
    return result.stdout


def safe_decrypt(age: Path, identity: bytes, ciphertext: bytes, env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    validate_identity(identity)
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, identity.rstrip(b"\n") + b"\n")
        os.close(write_fd)
        write_fd = -1
        return run(
            [str(age), "--decrypt", "--identity", f"/proc/self/fd/{read_fd}"],
            env=env,
            input_bytes=ciphertext,
            pass_fds=(read_fd,),
        )
    finally:
        if write_fd >= 0:
            os.close(write_fd)
        os.close(read_fd)


def make_sentinel(path: Path, marker: Path) -> None:
    path.write_text(
        "#!/usr/local/bin/python3\n"
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
        "raise SystemExit(97)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def assert_rejected(callback: Any, marker: Path, label: str) -> None:
    try:
        callback()
    except ValueError:
        pass
    else:
        raise CanaryFailure(f"{label}: restricted boundary accepted unsupported input")
    if marker.exists():
        raise CanaryFailure(f"{label}: PATH sentinel executed")


def check_network_none() -> dict[str, Any]:
    interfaces = sorted(path.name for path in Path("/sys/class/net").iterdir())
    if interfaces != ["lo"]:
        raise CanaryFailure(f"network namespace: expected loopback only, got {interfaces}")
    failure_name = ""
    try:
        with socket.create_connection(("198.51.100.1", 443), timeout=0.25):
            raise CanaryFailure("network namespace: external connection unexpectedly succeeded")
    except CanaryFailure:
        raise
    except OSError as error:
        failure_name = type(error).__name__
    return {"interfaces": interfaces, "external_connect": "denied", "failure": failure_name}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--platform", choices=sorted(PLATFORM_MACHINE), required=True)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    if platform.system() != "Linux" or platform.machine() != PLATFORM_MACHINE[args.platform]:
        parser.exit(1, "FAIL: canary must run natively inside the declared Linux platform\n")
    if os.geteuid() == 0:
        parser.exit(1, "FAIL: canary must run as a non-root runtime user\n")

    runtime_root = args.runtime_root.resolve()
    age = runtime_root / "age"
    keygen = runtime_root / "age-keygen"
    if not age.is_file() or not keygen.is_file() or age.is_symlink() or keygen.is_symlink():
        parser.exit(1, "FAIL: exact regular age and age-keygen paths are required\n")

    try:
        with tempfile.TemporaryDirectory(prefix="deeptwin-age-canary-") as temporary:
            work = Path(temporary)
            fakebin = work / "fakebin"
            fakebin.mkdir()
            home = work / "home"
            home.mkdir()
            markers = {
                name: work / f"{name}.executed"
                for name in ("age", "age-plugin-test", "curl", "wget", "ssh")
            }
            for name, marker in markers.items():
                make_sentinel(fakebin / name, marker)
            env = {
                "HOME": str(home),
                "PATH": f"{fakebin}:/usr/local/bin:/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "AGE_PLUGIN_PATH": str(fakebin),
            }

            network = check_network_none()
            version_results = {}
            for name, binary in (("age", age), ("age-keygen", keygen)):
                version = run([str(binary), "--version"], env=env)
                require_success(version, f"{name} version")
                observed = version.stdout.decode("ascii").strip()
                if observed != "v1.3.2":
                    raise CanaryFailure(f"{name}: unexpected version {observed!r}")
                version_results[name] = observed

            first = run([str(keygen)], env=env)
            second = run([str(keygen)], env=env)
            require_success(first, "first key generation")
            require_success(second, "second key generation")
            identity = extract_generated_identity(first.stdout)
            wrong_identity = extract_generated_identity(second.stdout)
            recipient_result = run([str(keygen), "--y"], env=env, input_bytes=identity + b"\n")
            require_success(recipient_result, "recipient derivation")
            recipient = recipient_result.stdout.decode("ascii").strip()
            validate_recipient(recipient)

            plaintext = "DeepTwin age native X25519 canary · 한국어\n".encode("utf-8") + bytes(range(32))
            ciphertext = safe_encrypt(age, recipient, plaintext, env)
            decrypted = safe_decrypt(age, identity, ciphertext, env)
            require_success(decrypted, "decrypt")
            if decrypted.stdout != plaintext:
                raise CanaryFailure("roundtrip: plaintext mismatch")

            wrong = safe_decrypt(age, wrong_identity, ciphertext, env)
            if wrong.returncode == 0 or wrong.stdout:
                raise CanaryFailure("wrong identity: authentication failure did not fail closed")

            tampered = bytearray(ciphertext)
            tampered[-1] ^= 1
            tamper_result = safe_decrypt(age, identity, bytes(tampered), env)
            if tamper_result.returncode == 0 or tamper_result.stdout:
                raise CanaryFailure("tamper: authentication failure did not fail closed")

            assert_rejected(
                lambda: safe_encrypt(age, "age1test10qdmzv9q", plaintext, env),
                markers["age-plugin-test"],
                "plugin recipient",
            )
            assert_rejected(
                lambda: safe_encrypt(age, "github:deeptwin-network-sentinel", plaintext, env),
                markers["curl"],
                "network recipient",
            )
            assert_rejected(
                lambda: safe_encrypt(age, "ssh-ed25519 AAAATEST", plaintext, env),
                markers["ssh"],
                "SSH recipient",
            )
            assert_rejected(
                lambda: safe_decrypt(age, b"AGE-PLUGIN-TEST-10Q32NLXM\n", ciphertext, env),
                markers["age-plugin-test"],
                "plugin identity",
            )

            raw_github = run(
                [str(age), "--encrypt", "--recipient", "github:deeptwin-network-sentinel"],
                env=env,
                input_bytes=plaintext,
            )
            if raw_github.returncode == 0 or raw_github.stdout:
                raise CanaryFailure("raw github recipient: age did not reject removed recipient type")
            if markers["age"].exists() or markers["curl"].exists() or markers["wget"].exists():
                raise CanaryFailure("absolute executable or network PATH sentinel executed")

            result = {
                "schema_version": "deeptwin-age-native-canary-v1",
                "status": "pass",
                "platform": args.platform,
                "uid": os.geteuid(),
                "versions": version_results,
                "network": network,
                "roundtrip": {
                    "algorithm": "native-X25519",
                    "plaintext_bytes": len(plaintext),
                    "plaintext_sha256": digest(plaintext),
                    "ciphertext_bytes": len(ciphertext),
                    "decrypted_sha256": digest(decrypted.stdout),
                },
                "negative_tests": {
                    "wrong_identity": {"exit_nonzero": True, "plaintext_bytes": len(wrong.stdout)},
                    "tamper": {"exit_nonzero": True, "plaintext_bytes": len(tamper_result.stdout)},
                    "plugin_recipient_pre_spawn_rejection": True,
                    "plugin_identity_pre_spawn_rejection": True,
                    "github_recipient_pre_spawn_rejection": True,
                    "ssh_recipient_pre_spawn_rejection": True,
                    "raw_github_recipient_removed_upstream": True,
                    "path_sentinels_executed": [],
                },
                "secret_transport": {
                    "identity_in_argv": False,
                    "identity_transport": "owned pipe descriptor via /proc/self/fd/N",
                    "secret_material_emitted": False,
                },
                "assurance_boundary": (
                    "The canary exercises a minimal restricted caller under a non-root, "
                    "network-none container. Production must make the same caller the sole "
                    "reachable entrypoint; the upstream age binary still contains plugin support."
                ),
            }
    except (CanaryFailure, OSError, subprocess.SubprocessError, UnicodeError, ValueError) as error:
        parser.exit(1, f"FAIL: {error}\n")

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_output is not None:
        args.json_output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
