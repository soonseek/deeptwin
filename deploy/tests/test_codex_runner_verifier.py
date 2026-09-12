from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import lzma
import os
import sys
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = REPOSITORY_ROOT / "deploy" / "locks" / "verify_codex_runner.py"
SPEC = importlib.util.spec_from_file_location("deeptwin_codex_runner_verifier", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_events() -> list[dict[str, object]]:
    return [
        {"type": "thread.started", "thread_id": "thread-1"},
        {
            "type": "item.completed",
            "item": {"id": "warning-1", "type": "error", "message": "warning"},
        },
        {"type": "turn.started"},
        {
            "type": "item.started",
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": "true",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
        {
            "type": "item.updated",
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": "true",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": "true",
                "aggregated_output": "",
                "exit_code": 0,
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {"id": "message-1", "type": "agent_message", "text": "done"},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 2,
                "cache_write_input_tokens": 0,
                "output_tokens": 4,
                "reasoning_output_tokens": 1,
            },
        },
    ]


def encode_events(events: list[dict[str, object]]) -> bytes:
    return b"".join(
        json.dumps(event, separators=(",", ":")).encode("utf-8") + b"\n"
        for event in events
    )


FAKE_CLI = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

args = sys.argv[1:]
home = Path(os.environ["CODEX_HOME"])
auth = home / "auth.json"

if args == ["--version"]:
    print("deeptwin-offline-codex-fixture 1")
    raise SystemExit(0)
if args == ["login", "status"]:
    print("Logged in" if auth.exists() else "Not logged in")
    raise SystemExit(0 if auth.exists() else 1)
if args == ["login", "--device-auth"]:
    if os.environ.get("DEEPTWIN_OFFLINE_FIXTURE") != "1":
        raise SystemExit(81)
    descriptor = os.open(auth, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(descriptor, b"offline-fixture-not-a-credential")
    os.close(descriptor)
    os.chmod(auth, 0o600)
    print("fixture login complete")
    raise SystemExit(0)
if args == ["logout"]:
    auth.unlink(missing_ok=True)
    print("fixture logout complete")
    raise SystemExit(0)
if not args or args[0] != "exec":
    raise SystemExit(82)

required = [
    "--ignore-user-config", "--ignore-rules", "--strict-config", "--ephemeral",
    "--model", "fixture-model", "--sandbox", "read-only", "--color", "never",
    "--json", "--skip-git-repo-check", "--cd", "-"
]
for value in required:
    if value not in args:
        raise SystemExit(83)
if 'approval_policy="never"' not in args:
    raise SystemExit(84)
if os.environ["HOME"] != os.environ["CODEX_HOME"]:
    raise SystemExit(85)
if "OPENAI_API_KEY" in os.environ or "CODEX_API_KEY" in os.environ:
    raise SystemExit(86)
if sys.stdin.read() != "offline fixture prompt":
    raise SystemExit(87)

def emit(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)

emit({"type": "thread.started", "thread_id": "fixture-thread"})
emit({"type": "turn.started"})
scenario = os.environ.get("DEEPTWIN_FIXTURE_SCENARIO", "success")
if scenario == "hang":
    marker = os.environ["DEEPTWIN_CANCEL_MARKER"]
    child = '''
import pathlib
import signal
import sys
import time
def stop(signum, frame):
    pathlib.Path(sys.argv[1]).write_text(signal.Signals(signum).name, encoding="utf-8")
    raise SystemExit(0)
signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
while True:
    time.sleep(1)
'''
    subprocess.Popen([sys.executable, "-c", child, marker])
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        raise SystemExit(130)
if scenario == "flood":
    sys.stdout.write("x" * 131072)
    sys.stdout.flush()
    time.sleep(1)
    raise SystemExit(0)
emit({"type": "item.completed", "item": {"id": "message-1", "type": "agent_message", "text": "ok"}})
emit({"type": "turn.completed", "usage": {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 0}})
"""


class MinimalRunnerFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.assets = root / "assets"
        self.assets.mkdir(mode=0o700)
        self.marker = root / "cosign-calls"
        self.cosign = root / "cosign-linux-amd64"
        self.cosign.write_text(
            "#!/usr/bin/env python3\n"
            "from hashlib import sha256\n"
            "from pathlib import Path\n"
            "import sys\n"
            "args=sys.argv[1:]\n"
            f"identity={VERIFIER.CERTIFICATE_IDENTITY!r}\n"
            f"issuer={VERIFIER.CERTIFICATE_ISSUER!r}\n"
            f"marker=Path({str(self.marker)!r})\n"
            "valid=(len(args)==9 and args[0:3]==['verify-blob','--offline','--bundle'] "
            "and args[4:6]==['--certificate-identity',identity] "
            "and args[6:8]==['--certificate-oidc-issuer',issuer])\n"
            "if valid:\n"
            " subject=Path(args[8]).read_bytes()\n"
            " bundle=Path(args[3]).read_bytes()\n"
            " valid=(bundle == b'bundle:' + sha256(subject).hexdigest().encode('ascii'))\n"
            "if valid:\n"
            " with marker.open('ab') as stream: stream.write(b'call\\n')\n"
            "raise SystemExit(0 if valid else 91)\n",
            encoding="utf-8",
        )
        self.cosign.chmod(0o755)
        cosign_release_prefix = (
            "https://github.com/sigstore/cosign/releases/download/v3.1.2/"
        )
        fixture_digest = digest(b"fixture-declaration")
        self.expected_cosign_bootstrap: dict[str, object] = {
            "name": "cosign",
            "version": "3.1.2",
            "certificate_identity": (
                "keyless@projectsigstore.iam.gserviceaccount.com"
            ),
            "certificate_oidc_issuer": "https://accounts.google.com",
            "checksum_manifest": {
                "url": f"{cosign_release_prefix}cosign_checksums.txt",
                "filename": "cosign_checksums.txt",
                "bytes": 1,
                "sha256": fixture_digest,
                "sigstore_bundle": {
                    "url": (
                        f"{cosign_release_prefix}"
                        "cosign_checksums.txt.sigstore.json"
                    ),
                    "filename": "cosign_checksums.txt.sigstore.json",
                    "bytes": 1,
                    "sha256": fixture_digest,
                    "verified": True,
                },
                "signature_chain_verified": True,
            },
            "release_build_verifiers": [
                {
                    "platform": "linux/amd64",
                    "executable": {
                        "url": f"{cosign_release_prefix}cosign-linux-amd64",
                        "filename": "cosign-linux-amd64",
                        "bytes": self.cosign.stat().st_size,
                        "sha256": digest(self.cosign.read_bytes()),
                        "mode": "0755",
                    },
                    "sigstore_bundle": {
                        "url": (
                            f"{cosign_release_prefix}"
                            "cosign-linux-amd64.sigstore.json"
                        ),
                        "filename": "cosign-linux-amd64.sigstore.json",
                        "bytes": 1,
                        "sha256": fixture_digest,
                        "verified": True,
                    },
                    "checksum_manifest_match": True,
                    "signature_chain_verified": True,
                },
                {
                    "platform": "linux/arm64",
                    "executable": {
                        "url": f"{cosign_release_prefix}cosign-linux-arm64",
                        "filename": "cosign-linux-arm64",
                        "bytes": 1,
                        "sha256": fixture_digest,
                        "mode": "0755",
                    },
                    "sigstore_bundle": {
                        "url": (
                            f"{cosign_release_prefix}"
                            "cosign-linux-arm64.sigstore.json"
                        ),
                        "filename": "cosign-linux-arm64.sigstore.json",
                        "bytes": 1,
                        "sha256": fixture_digest,
                        "verified": True,
                    },
                    "checksum_manifest_match": True,
                    "signature_chain_verified": True,
                },
            ],
            "audit_observations": [
                {
                    "label": "darwin-arm64-audit-only",
                    "platform": "darwin/arm64",
                    "eligible_for_release_build": False,
                    "executable": {
                        "url": f"{cosign_release_prefix}cosign-darwin-arm64",
                        "filename": "cosign-darwin-arm64",
                        "bytes": 1,
                        "sha256": fixture_digest,
                        "mode": "0755",
                    },
                    "sigstore_bundle": {
                        "url": (
                            f"{cosign_release_prefix}"
                            "cosign-darwin-arm64.sigstore.json"
                        ),
                        "filename": "cosign-darwin-arm64.sigstore.json",
                        "bytes": 1,
                        "sha256": fixture_digest,
                        "verified": True,
                    },
                    "checksum_manifest_match": True,
                    "signature_chain_verified": True,
                }
            ],
        }
        self.manifest_value: dict[str, object] = {
            "schema_version": VERIFIER.RUNNER_SCHEMA,
            "status": "candidate_not_release_qualified",
            "version": "0.153.4",
            "tag": "rust-v0.153.4",
            "source_commit": "3" * 40,
            "target_platforms": list(VERIFIER.PLATFORMS),
            "signature_policy": {
                "offline": True,
                "subject_scope": "extracted executable only",
                "certificate_identity": VERIFIER.CERTIFICATE_IDENTITY,
                "certificate_oidc_issuer": VERIFIER.CERTIFICATE_ISSUER,
                "verifier_bootstrap": copy.deepcopy(self.expected_cosign_bootstrap),
            },
            "runtime_layout": {
                "install_root": VERIFIER.INSTALL_ROOT,
                "codex_path": VERIFIER.INSTALL_PATHS["codex"],
                "code_mode_host_path": VERIFIER.INSTALL_PATHS["codex-code-mode-host"],
                "bubblewrap_path": VERIFIER.INSTALL_PATHS["bubblewrap"],
                "bash_path": "/bin/bash",
                "path_env": VERIFIER.FIXED_PATH_ENV,
                "required_internal_sandbox_profiles": ["read-only", "workspace-write"],
                "codex_home_policy": "isolated_per_run",
            },
            "platform_inputs": [],
            "omitted_components": list(VERIFIER.OMITTED_COMPONENTS),
            "runtime_mutation_policy": {
                "browser_download_at_runtime": False,
                "model_download_at_runtime": False,
                "package_install_at_runtime": False,
                "package_resolution_at_runtime": False,
                "tool_download_at_runtime": False,
            },
            "build_input_gate": "satisfied",
            "build_input_blockers": [],
            "release_gate": "not_satisfied",
            "downstream_release_blockers": [
                copy.deepcopy(item)
                for item in VERIFIER.EXPECTED_DOWNSTREAM_RELEASE_BLOCKERS
            ],
        }
        self.source_inputs: list[dict[str, object]] = []
        for source_index, filename in enumerate(
            item["filename"] for item in VERIFIER.BASH_SOURCE_INPUTS
        ):
            source_data = f"source:{filename}".encode("ascii")
            source_path = self.assets / filename
            source_path.write_bytes(source_data)
            source_path.chmod(0o644)
            self.source_inputs.append({
                "filename": filename,
                "url": (
                    "https://snapshot.debian.org/file/"
                    f"{source_index + 1:040x}"
                ),
                "bytes": len(source_data),
                "sha256": digest(source_data),
            })

        platform_inputs = self.manifest_value["platform_inputs"]
        assert isinstance(platform_inputs, list)
        for platform_index, platform in enumerate(VERIFIER.PLATFORMS):
            architecture = platform.rsplit("/", 1)[-1]
            bash_data = f"bookworm-bash:{platform}".encode("ascii")
            license_data = b"fixture Bash license"
            bash_filename = f"bash_5.2.15-2+b13_{architecture}.deb"
            bash_path = self.assets / bash_filename
            self._write_deb(
                bash_path,
                bash_data=bash_data,
                license_data=license_data,
            )
            components = []
            for component in VERIFIER.COMPONENTS:
                member = VERIFIER.COMPONENT_MEMBERS[(platform, component)]
                component_data = f"binary:{platform}:{component}".encode("ascii")
                archive_filename = f"{member}.tar.gz"
                archive_path = self.assets / archive_filename
                self._write_archive(archive_path, member, component_data)
                bundle_filename = f"{member}.sigstore"
                bundle_data = b"bundle:" + digest(component_data).encode("ascii")
                bundle_path = self.assets / bundle_filename
                bundle_path.write_bytes(bundle_data)
                bundle_path.chmod(0o644)
                components.append({
                    "name": component,
                    "archive": {
                        "url": f"{VERIFIER.OPENAI_RELEASE_PREFIX}{archive_filename}",
                        "filename": archive_filename,
                        "bytes": archive_path.stat().st_size,
                        "sha256": digest(archive_path.read_bytes()),
                        "member_path": member,
                    },
                    "executable": {
                        "installed_path": VERIFIER.INSTALL_PATHS[component],
                        "bytes": len(component_data),
                        "sha256": digest(component_data),
                        "mode": "0755",
                    },
                    "sigstore_bundle": {
                        "url": f"{VERIFIER.OPENAI_RELEASE_PREFIX}{bundle_filename}",
                        "filename": bundle_filename,
                        "bytes": len(bundle_data),
                        "sha256": digest(bundle_data),
                        "verified": True,
                    },
                    "signature_scope": "extracted executable only",
                })
            runtime_image = {
                "distribution": "debian",
                "suite": "bookworm",
                "repository": "docker.io/library/debian",
                "tag": "bookworm-20260824-slim",
                "created_at": "2026-08-24T00:00:00Z",
                "snapshot": "20260824T000000Z",
                "source_repository": (
                    "https://github.com/debuerreotype/docker-debian-artifacts.git"
                ),
                "source_revision": f"{platform_index + 1:040x}",
                "index": copy.deepcopy(VERIFIER.BOOKWORM_INDEX),
                "manifest": {
                    "media_type": VERIFIER.OCI_MANIFEST_MEDIA_TYPE,
                    "digest": "sha256:" + str(platform_index + 2) * 64,
                    "bytes": 1000 + platform_index,
                },
                "config": {
                    "media_type": VERIFIER.OCI_CONFIG_MEDIA_TYPE,
                    "digest": "sha256:" + str(platform_index + 4) * 64,
                    "bytes": 400 + platform_index,
                },
                "layers": [{
                    "position": 1,
                    "media_type": VERIFIER.OCI_LAYER_MEDIA_TYPE,
                    "digest": "sha256:" + str(platform_index + 6) * 64,
                    "bytes": 2000 + platform_index,
                }],
                "bash": {
                    "package": "bash",
                    "package_version": "5.2.15-2+b13",
                    "source_package": "bash",
                    "source_version": "5.2.15-2",
                    "installed_path": "/bin/bash",
                    "mode": "0755",
                    "binary_package": {
                        "filename": bash_filename,
                        "url": (
                            "https://snapshot.debian.org/file/"
                            f"{platform_index + 10:040x}"
                        ),
                        "bytes": bash_path.stat().st_size,
                        "sha256": digest(bash_path.read_bytes()),
                    },
                    "package_member": {
                        "path": "bin/bash",
                        "installed_path": "/bin/bash",
                        "bytes": len(bash_data),
                        "sha256": digest(bash_data),
                        "mode": "0755",
                    },
                    "license_member": {
                        "path": "usr/share/doc/bash/copyright",
                        "bytes": len(license_data),
                        "sha256": digest(license_data),
                    },
                    "source_inputs": copy.deepcopy(self.source_inputs),
                },
            }
            platform_inputs.append({
                "platform": platform,
                "target": VERIFIER.PLATFORM_TARGETS[platform],
                "components": components,
                "runtime_image": runtime_image,
            })
        self.expected_runtime_inputs = {
            record["platform"]: copy.deepcopy(record["runtime_image"])
            for record in platform_inputs
        }
        self.manifest = root / "manifest.json"
        self.save()

    @staticmethod
    def _write_archive(
        path: Path,
        member: str,
        data: bytes,
        *,
        member_mode: int = 0o755,
        extra_kind: str | None = None,
    ) -> None:
        with tarfile.open(path, "w:gz") as archive:
            info = tarfile.TarInfo(member)
            info.mode = member_mode
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
            if extra_kind == "file":
                extra = tarfile.TarInfo("unexpected")
                extra.mode = 0o755
                extra.size = 1
                archive.addfile(extra, io.BytesIO(b"x"))
            elif extra_kind == "symlink":
                extra = tarfile.TarInfo("unexpected")
                extra.type = tarfile.SYMTYPE
                extra.linkname = "../../etc/passwd"
                archive.addfile(extra)
            elif extra_kind == "hardlink":
                extra = tarfile.TarInfo("unexpected")
                extra.type = tarfile.LNKTYPE
                extra.linkname = member
                archive.addfile(extra)
        path.chmod(0o644)

    @staticmethod
    def _tar_xz(
        members: list[tuple[str, bytes | None, int, bytes | None]],
        *,
        trailing_tar_data: bytes = b"",
        trailing_xz_data: bytes = b"",
    ) -> bytes:
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w") as archive:
            for name, data, mode, link_type in members:
                info = tarfile.TarInfo(name)
                info.mode = mode
                if link_type == b"symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = "bash" if name == "bin/rbash" else "../../etc/passwd"
                    archive.addfile(info)
                elif link_type == b"hardlink":
                    info.type = tarfile.LNKTYPE
                    info.linkname = "bin/bash"
                    archive.addfile(info)
                elif link_type == b"device":
                    info.type = tarfile.CHRTYPE
                    info.devmajor = 1
                    info.devminor = 3
                    archive.addfile(info)
                else:
                    assert data is not None
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
        compressed = lzma.compress(raw.getvalue() + trailing_tar_data, format=lzma.FORMAT_XZ)
        return compressed + trailing_xz_data

    @staticmethod
    def _ar_bytes(
        members: list[tuple[str, bytes]],
        *,
        trailing: bytes = b"",
        member_mode: int = 0o100644,
    ) -> bytes:
        result = bytearray(b"!<arch>\n")
        for name, data in members:
            header = (
                f"{name:<16}{0:<12}{0:<6}{0:<6}{member_mode:<8o}{len(data):<10}`\n"
            ).encode("ascii")
            assert len(header) == 60
            result.extend(header)
            result.extend(data)
            if len(data) % 2:
                result.extend(b"\n")
        result.extend(trailing)
        return bytes(result)

    @classmethod
    def _write_deb(
        cls,
        path: Path,
        *,
        bash_data: bytes,
        license_data: bytes,
        extra_kind: str | None = None,
        trailing_tar_data: bytes = b"",
        trailing_xz_data: bytes = b"",
        trailing_ar_data: bytes = b"",
        bash_mode: int = 0o755,
        license_mode: int = 0o644,
        ar_mode: int = 0o100644,
    ) -> None:
        control = cls._tar_xz([("control", b"Package: bash\n", 0o644, None)])
        data_members: list[tuple[str, bytes | None, int, bytes | None]] = [
            ("bin/bash", bash_data, bash_mode, None),
            ("usr/share/doc/bash/copyright", license_data, license_mode, None),
            ("bin/rbash", None, 0o777, b"symlink"),
        ]
        if extra_kind == "traversal":
            data_members.append(("../escape", b"escape", 0o644, None))
        elif extra_kind == "symlink":
            data_members.append(("unexpected-link", None, 0o777, b"symlink"))
        elif extra_kind == "hardlink":
            data_members.append(("unexpected-hardlink", None, 0o644, b"hardlink"))
        elif extra_kind == "device":
            data_members.append(("unexpected-device", None, 0o600, b"device"))
        elif extra_kind == "duplicate":
            data_members.append(("bin/bash", b"duplicate", 0o755, None))
        data_archive = cls._tar_xz(
            data_members,
            trailing_tar_data=trailing_tar_data,
            trailing_xz_data=trailing_xz_data,
        )
        ar_members = [
            ("debian-binary", b"2.0\n"),
            ("control.tar.xz", control),
            ("data.tar.xz", data_archive),
        ]
        if extra_kind == "duplicate-ar":
            ar_members.append(("data.tar.xz", data_archive))
        path.write_bytes(
            cls._ar_bytes(
                ar_members, trailing=trailing_ar_data, member_mode=ar_mode
            )
        )
        path.chmod(0o644)

    def save(self) -> None:
        self.manifest.write_text(
            json.dumps(self.manifest_value, sort_keys=True), encoding="utf-8"
        )

    def platform(self, platform: str = "linux/amd64") -> dict[str, object]:
        records = self.manifest_value["platform_inputs"]
        assert isinstance(records, list)
        return next(record for record in records if record["platform"] == platform)

    def component(
        self, platform: str = "linux/amd64", component: str = "codex"
    ) -> dict[str, object]:
        record = self.platform(platform)
        components = record["components"]
        assert isinstance(components, list)
        return next(item for item in components if item["name"] == component)

    def rewrite_archive(
        self,
        *,
        platform: str = "linux/amd64",
        component: str = "codex",
        member_mode: int = 0o755,
        extra_kind: str | None = None,
    ) -> None:
        declaration = self.component(platform, component)
        archive = declaration["archive"]
        executable = declaration["executable"]
        assert isinstance(archive, dict) and isinstance(executable, dict)
        data = f"binary:{platform}:{component}".encode("ascii")
        path = self.assets / archive["filename"]
        self._write_archive(
            path, archive["member_path"], data,
            member_mode=member_mode, extra_kind=extra_kind,
        )
        archive["bytes"] = path.stat().st_size
        archive["sha256"] = digest(path.read_bytes())
        self.save()

    def rewrite_deb(
        self,
        *,
        platform: str = "linux/amd64",
        bash_data: bytes | None = None,
        license_data: bytes | None = None,
        extra_kind: str | None = None,
        trailing_tar_data: bytes = b"",
        trailing_xz_data: bytes = b"",
        trailing_ar_data: bytes = b"",
        bash_mode: int = 0o755,
        license_mode: int = 0o644,
        ar_mode: int = 0o100644,
        relock_package: bool = True,
    ) -> None:
        runtime = self.platform(platform)["runtime_image"]
        assert isinstance(runtime, dict)
        bash = runtime["bash"]
        assert isinstance(bash, dict)
        binary_package = bash["binary_package"]
        assert isinstance(binary_package, dict)
        path = self.assets / binary_package["filename"]
        if bash_data is None:
            bash_data = f"bookworm-bash:{platform}".encode("ascii")
        if license_data is None:
            license_data = b"fixture Bash license"
        self._write_deb(
            path,
            bash_data=bash_data,
            license_data=license_data,
            extra_kind=extra_kind,
            trailing_tar_data=trailing_tar_data,
            trailing_xz_data=trailing_xz_data,
            trailing_ar_data=trailing_ar_data,
            bash_mode=bash_mode,
            license_mode=license_mode,
            ar_mode=ar_mode,
        )
        if relock_package:
            binary_package["bytes"] = path.stat().st_size
            binary_package["sha256"] = digest(path.read_bytes())
            expected_package = self.expected_runtime_inputs[platform]["bash"]["binary_package"]
            expected_package["bytes"] = binary_package["bytes"]
            expected_package["sha256"] = binary_package["sha256"]
        self.save()

    def verify(
        self, *, locked: bool = False, allow_audit_verifier: bool = False
    ) -> dict[str, object]:
        with (
            mock.patch.object(
                VERIFIER, "CODEX_RUNTIME_INPUTS", self.expected_runtime_inputs
            ),
            mock.patch.object(
                VERIFIER, "COSIGN_BOOTSTRAP_POLICY", self.expected_cosign_bootstrap
            ),
        ):
            return VERIFIER.verify_minimal_runner(
                self.manifest,
                self.assets,
                self.cosign,
                locked=locked,
                allow_audit_verifier=allow_audit_verifier,
            )


class CodexMinimalRunnerVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="deeptwin-codex-v3-test-")
        self.addCleanup(self.temporary.cleanup)
        self.fixture = MinimalRunnerFixture(Path(self.temporary.name))

    def test_exact_two_platform_minimal_runner_passes_six_independent_signatures(self) -> None:
        report = self.fixture.verify()
        self.assertEqual(report["schema_version"], VERIFIER.RUNNER_SCHEMA)
        self.assertEqual(report["platform_count"], 2)
        self.assertEqual(report["component_count"], 6)
        self.assertEqual(report["omitted_components"], list(VERIFIER.OMITTED_COMPONENTS))
        self.assertEqual(self.fixture.marker.read_text(encoding="utf-8").splitlines(),
                         ["call"] * 6)
        self.assertEqual(len(report["bash_source_inputs"]), 3)
        self.assertEqual(
            [item["filename"] for item in report["bash_source_inputs"]],
            [item["filename"] for item in VERIFIER.BASH_SOURCE_INPUTS],
        )
        self.assertEqual(
            report["verified_input_file_count"],
            VERIFIER.EXPECTED_MINIMAL_RUNNER_INPUT_FILE_COUNT,
        )
        self.assertEqual(
            [item["filename"] for item in report["verified_input_files"]],
            sorted(entry.name for entry in self.fixture.assets.iterdir()),
        )
        self.assertEqual(
            sum(
                component["sigstore_verified"] is True
                for platform in report["platforms"]
                for component in platform["components"]
            ),
            6,
        )
        self.assertEqual(report["build_input_gate"], "satisfied")
        self.assertEqual(report["release_gate"], "not_satisfied")
        self.assertEqual(
            report["cosign"]["selected_verifier_platform"], "linux/amd64"
        )
        self.assertEqual(report["cosign"]["selection_mode"], "release-build")

    def test_locked_gate_rejects_build_gaps_but_allows_downstream_gaps(self) -> None:
        self.fixture.manifest_value["build_input_gate"] = "not_satisfied"
        self.fixture.manifest_value["build_input_blockers"] = [{
            "blocker_id": "fixture-missing-exact-input",
            "owner_task": "T089",
            "gate_id": "t089-artifact-source-size-digest",
            "summary": "A fixture exact input remains absent.",
        }]
        self.fixture.save()
        with self.assertRaisesRegex(
            VERIFIER.VerificationError, "locked build input.*build blockers"
        ):
            self.fixture.verify(locked=True)

        self.fixture.manifest_value["build_input_gate"] = "satisfied"
        self.fixture.manifest_value["build_input_blockers"] = []
        self.fixture.save()
        report = self.fixture.verify(locked=True)
        self.assertEqual(report["build_input_gate"], "satisfied")
        self.assertEqual(report["release_gate"], "not_satisfied")
        self.assertEqual(
            report["downstream_release_blocker_count"],
            len(VERIFIER.EXPECTED_DOWNSTREAM_RELEASE_BLOCKERS),
        )

    def test_gate_state_depends_on_the_correct_structured_blocker_class(self) -> None:
        self.fixture.manifest_value["build_input_gate"] = "not_satisfied"
        self.fixture.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "build_input_gate"):
            self.fixture.verify()

        replacement = MinimalRunnerFixture(Path(self.temporary.name) / "release-gate")
        replacement.manifest_value["release_gate"] = "satisfied"
        replacement.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "release_gate"):
            replacement.verify()

    def test_blocker_ids_owners_gates_summaries_and_order_are_fail_closed(self) -> None:
        mutations = (
            ("blocker_id", "unknown-build-gap"),
            ("owner_task", "T084"),
            ("gate_id", "t084-wrong-gate"),
            ("summary", "changed but plausible summary"),
        )
        for index, (field, value) in enumerate(mutations):
            with self.subTest(field=field):
                fixture = MinimalRunnerFixture(
                    Path(self.temporary.name) / f"bad-blocker-{index}"
                )
                blockers = fixture.manifest_value["downstream_release_blockers"]
                assert isinstance(blockers, list)
                blockers[0][field] = value
                fixture.save()
                with self.assertRaisesRegex(
                    VERIFIER.VerificationError, "downstream_release_blockers"
                ):
                    fixture.verify()

        duplicate = MinimalRunnerFixture(Path(self.temporary.name) / "duplicate-blocker")
        blockers = duplicate.manifest_value["downstream_release_blockers"]
        assert isinstance(blockers, list)
        blockers.append(copy.deepcopy(blockers[0]))
        duplicate.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "canonical.*subset|duplicate"):
            duplicate.verify()

    def test_linux_release_build_cosign_coverage_is_mandatory_and_unique(self) -> None:
        for index, replacement_records in enumerate((
            lambda records, audit: [copy.deepcopy(audit[0])],
            lambda records, audit: [copy.deepcopy(records[0])],
            lambda records, audit: [copy.deepcopy(records[0]), copy.deepcopy(records[0])],
        )):
            with self.subTest(case=index):
                fixture = MinimalRunnerFixture(
                    Path(self.temporary.name) / f"bad-cosign-coverage-{index}"
                )
                policy = fixture.manifest_value["signature_policy"]
                assert isinstance(policy, dict)
                bootstrap = policy["verifier_bootstrap"]
                records = bootstrap["release_build_verifiers"]
                audit = bootstrap["audit_observations"]
                bootstrap["release_build_verifiers"] = replacement_records(records, audit)
                fixture.save()
                with self.assertRaisesRegex(
                    VERIFIER.VerificationError,
                    "release-build verifiers|Linux verifier platforms|release build",
                ):
                    fixture.verify()

    def test_cosign_bootstrap_chain_and_darwin_audit_boundary_are_pinned(self) -> None:
        cases = (
            ("checksum-chain", lambda value: value["checksum_manifest"].update(
                {"signature_chain_verified": False}
            )),
            ("linux-chain", lambda value: value["release_build_verifiers"][0].update(
                {"signature_chain_verified": False}
            )),
            ("darwin-eligible", lambda value: value["audit_observations"][0].update(
                {"eligible_for_release_build": True}
            )),
            ("bootstrap-identity", lambda value: value.update(
                {"certificate_identity": "attacker@example.invalid"}
            )),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                fixture = MinimalRunnerFixture(Path(self.temporary.name) / name)
                policy = fixture.manifest_value["signature_policy"]
                assert isinstance(policy, dict)
                bootstrap = policy["verifier_bootstrap"]
                mutate(bootstrap)
                fixture.save()
                with self.assertRaisesRegex(
                    VERIFIER.VerificationError, "Cosign|cosign|signature|audit"
                ):
                    fixture.verify()

    def test_darwin_audit_executable_cannot_be_selected_by_cosign_argument(self) -> None:
        darwin = self.fixture.root / "cosign-darwin-arm64"
        darwin.write_bytes(self.fixture.cosign.read_bytes())
        darwin.chmod(0o755)
        with (
            mock.patch.object(
                VERIFIER, "CODEX_RUNTIME_INPUTS", self.fixture.expected_runtime_inputs
            ),
            mock.patch.object(
                VERIFIER,
                "COSIGN_BOOTSTRAP_POLICY",
                self.fixture.expected_cosign_bootstrap,
            ),
            self.assertRaisesRegex(
                VERIFIER.VerificationError, "Linux release-build verifier"
            ),
        ):
            VERIFIER.verify_minimal_runner(
                self.fixture.manifest,
                self.fixture.assets,
                darwin,
                locked=True,
            )

    def test_darwin_audit_verifier_requires_explicit_selection(self) -> None:
        darwin = self.fixture.root / "cosign-darwin-arm64"
        darwin.write_bytes(self.fixture.cosign.read_bytes())
        darwin.chmod(0o755)
        audit = self.fixture.expected_cosign_bootstrap["audit_observations"][0]
        audit["executable"]["bytes"] = darwin.stat().st_size
        audit["executable"]["sha256"] = digest(darwin.read_bytes())
        signature = self.fixture.manifest_value["signature_policy"]
        signature["verifier_bootstrap"] = copy.deepcopy(
            self.fixture.expected_cosign_bootstrap
        )
        self.fixture.cosign = darwin
        self.fixture.save()

        report = self.fixture.verify(locked=True, allow_audit_verifier=True)
        self.assertEqual(
            report["cosign"]["selected_verifier_platform"], "darwin/arm64"
        )
        self.assertEqual(report["cosign"]["selection_mode"], "audit-only")

    def test_repository_manifest_pins_exact_official_cosign_evidence(self) -> None:
        value = json.loads(
            (REPOSITORY_ROOT / "deploy" / "manifests" / "codex-0.153.4.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(
            value["signature_policy"]["verifier_bootstrap"],
            VERIFIER.COSIGN_BOOTSTRAP_POLICY,
        )
        self.assertEqual(
            [item["platform"] for item in VERIFIER.COSIGN_BOOTSTRAP_POLICY[
                "release_build_verifiers"
            ]],
            ["linux/amd64", "linux/arm64"],
        )
        self.assertFalse(
            VERIFIER.COSIGN_BOOTSTRAP_POLICY["audit_observations"][0][
                "eligible_for_release_build"
            ]
        )
        self.assertEqual(value["schema_version"], VERIFIER.RUNNER_SCHEMA)
        self.assertEqual(value["build_input_gate"], "satisfied")
        self.assertEqual(value["build_input_blockers"], [])
        self.assertEqual(value["release_gate"], "not_satisfied")
        self.assertEqual(
            value["downstream_release_blockers"],
            list(VERIFIER.EXPECTED_DOWNSTREAM_RELEASE_BLOCKERS),
        )

    def test_repository_manifest_uses_the_independent_exact_runtime_constants(self) -> None:
        value = json.loads(
            (REPOSITORY_ROOT / "deploy" / "manifests" / "codex-0.153.4.json")
            .read_text(encoding="utf-8")
        )
        actual = {
            record["platform"]: record["runtime_image"]
            for record in value["platform_inputs"]
        }
        self.assertEqual(actual, VERIFIER.CODEX_RUNTIME_INPUTS)

        aggregate_path = (
            REPOSITORY_ROOT / "deploy" / "locks" / "verify_build_inputs.py"
        )
        aggregate_spec = importlib.util.spec_from_file_location(
            "deeptwin_build_input_verifier_for_runner_test", aggregate_path
        )
        assert aggregate_spec is not None and aggregate_spec.loader is not None
        aggregate = importlib.util.module_from_spec(aggregate_spec)
        aggregate_spec.loader.exec_module(aggregate)
        self.assertEqual(
            VERIFIER.CODEX_RUNTIME_INPUTS, aggregate.CODEX_RUNTIME_INPUTS
        )

    def test_manifest_is_closed_and_has_no_parent_digest_or_sidecar_proposal(self) -> None:
        self.fixture.manifest_value["parent_manifest"] = {"sha256": "0" * 64}
        self.fixture.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "exact fields"):
            self.fixture.verify()

    def test_both_platforms_and_targets_are_mandatory_and_ordered(self) -> None:
        records = self.fixture.manifest_value["platform_inputs"]
        assert isinstance(records, list)
        records.pop()
        self.fixture.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "exactly two"):
            self.fixture.verify()

        replacement = MinimalRunnerFixture(Path(self.temporary.name) / "wrong-target")
        replacement.platform()["target"] = "x86_64-unknown-linux-gnu"
        replacement.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "platform/target"):
            replacement.verify()

    def test_fixed_sibling_layout_and_bash_are_mandatory(self) -> None:
        layout = self.fixture.manifest_value["runtime_layout"]
        assert isinstance(layout, dict)
        layout["code_mode_host_path"] = "/tmp/codex-code-mode-host"
        self.fixture.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "fixed sibling layout"):
            self.fixture.verify()

    def test_missing_or_relabelled_component_fails_closed(self) -> None:
        components = self.fixture.platform()["components"]
        assert isinstance(components, list)
        components[0]["name"] = "ripgrep"
        self.fixture.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "component ordering"):
            self.fixture.verify()

    def test_obsolete_artifact_is_not_an_optional_directory_extra(self) -> None:
        obsolete = self.fixture.assets / "codex-package-x86_64-unknown-linux-musl.tar.gz"
        obsolete.write_bytes(b"obsolete")
        obsolete.chmod(0o644)
        with self.assertRaisesRegex(VERIFIER.VerificationError, "undeclared files"):
            self.fixture.verify()

    def test_omission_list_cannot_silently_reintroduce_rg_or_zsh(self) -> None:
        omitted = self.fixture.manifest_value["omitted_components"]
        assert isinstance(omitted, list)
        omitted.remove("ripgrep")
        self.fixture.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "explicitly omitted"):
            self.fixture.verify()

    def test_archive_extra_file_symlink_hardlink_and_write_mode_are_rejected(self) -> None:
        for extra_kind, member_mode in (
            ("file", 0o755), ("symlink", 0o755), ("hardlink", 0o755), (None, 0o777),
        ):
            with (
                self.subTest(extra_kind=extra_kind, member_mode=oct(member_mode)),
                tempfile.TemporaryDirectory(prefix="deeptwin-codex-archive-case-") as raw,
            ):
                fixture = MinimalRunnerFixture(Path(raw))
                fixture.rewrite_archive(extra_kind=extra_kind, member_mode=member_mode)
                with self.assertRaises(VERIFIER.VerificationError):
                    fixture.verify()

    def test_archive_and_executable_digests_are_both_authoritative(self) -> None:
        declaration = self.fixture.component()
        archive = declaration["archive"]
        assert isinstance(archive, dict)
        archive["sha256"] = "0" * 64
        self.fixture.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "exact bytes changed"):
            self.fixture.verify()

        replacement = MinimalRunnerFixture(Path(self.temporary.name) / "wrong-executable")
        executable = replacement.component()["executable"]
        assert isinstance(executable, dict)
        executable["sha256"] = "0" * 64
        replacement.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "executable digest"):
            replacement.verify()

    def test_wrong_bundle_bytes_fail_actual_offline_signature_check(self) -> None:
        declaration = self.fixture.component()
        bundle = declaration["sigstore_bundle"]
        assert isinstance(bundle, dict)
        path = self.fixture.assets / bundle["filename"]
        path.write_bytes(b"bundle:validly-locked-but-wrong-subject")
        path.chmod(0o644)
        bundle["bytes"] = path.stat().st_size
        bundle["sha256"] = digest(path.read_bytes())
        self.fixture.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "Sigstore verification failed"):
            self.fixture.verify()

    def test_bundle_declaration_and_certificate_policy_fail_closed(self) -> None:
        bundle = self.fixture.component()["sigstore_bundle"]
        assert isinstance(bundle, dict)
        bundle["verified"] = False
        self.fixture.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "verification-bound"):
            self.fixture.verify()

        replacement = MinimalRunnerFixture(Path(self.temporary.name) / "wrong-identity")
        policy = replacement.manifest_value["signature_policy"]
        assert isinstance(policy, dict)
        policy["certificate_identity"] = "https://example.invalid/attacker"
        replacement.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "release policy"):
            replacement.verify()

    def test_cosign_hash_is_checked_before_any_signature_process(self) -> None:
        policy = self.fixture.manifest_value["signature_policy"]
        assert isinstance(policy, dict)
        bootstrap = policy["verifier_bootstrap"]
        assert isinstance(bootstrap, dict)
        verifier = bootstrap["release_build_verifiers"][0]["executable"]
        verifier["sha256"] = "0" * 64
        fixture_verifier = self.fixture.expected_cosign_bootstrap[
            "release_build_verifiers"
        ][0]["executable"]
        fixture_verifier["sha256"] = "0" * 64
        self.fixture.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "exact bytes changed"):
            self.fixture.verify()
        self.assertFalse(self.fixture.marker.exists())

    def test_bookworm_deb_bytes_mode_and_origin_are_verified(self) -> None:
        runtime = self.fixture.platform()["runtime_image"]
        assert isinstance(runtime, dict)
        bash = runtime["bash"]
        assert isinstance(bash, dict)
        package = bash["binary_package"]
        assert isinstance(package, dict)
        bash_path = self.fixture.assets / package["filename"]
        with bash_path.open("ab") as stream:
            stream.write(b"tampered-deb")
        with self.assertRaisesRegex(VERIFIER.VerificationError, "exact bytes changed"):
            self.fixture.verify()

        replacement = MinimalRunnerFixture(Path(self.temporary.name) / "wrong-suite")
        replacement.platform()["runtime_image"]["suite"] = "bullseye"
        replacement.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "pinned Debian Bookworm"):
            replacement.verify()

        mode = MinimalRunnerFixture(Path(self.temporary.name) / "wrong-bash-mode")
        runtime = mode.platform()["runtime_image"]
        assert isinstance(runtime, dict)
        bash = runtime["bash"]
        assert isinstance(bash, dict)
        package = bash["binary_package"]
        assert isinstance(package, dict)
        (mode.assets / package["filename"]).chmod(0o600)
        with self.assertRaisesRegex(VERIFIER.VerificationError, "file mode"):
            mode.verify()

    def test_runtime_oci_closure_and_snapshot_urls_are_exact(self) -> None:
        runtime = self.fixture.platform()["runtime_image"]
        assert isinstance(runtime, dict)
        manifest = runtime["manifest"]
        assert isinstance(manifest, dict)
        manifest["digest"] = "sha256:" + "a" * 64
        self.fixture.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "exact pinned Bookworm"):
            self.fixture.verify()

        malformed = MinimalRunnerFixture(Path(self.temporary.name) / "malformed-oci")
        runtime = malformed.platform()["runtime_image"]
        assert isinstance(runtime, dict)
        layer = runtime["layers"][0]
        layer["digest"] = "sha256:not-a-digest"
        malformed.expected_runtime_inputs["linux/amd64"]["layers"][0]["digest"] = (
            "sha256:not-a-digest"
        )
        malformed.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "OCI SHA-256"):
            malformed.verify()

        wrong_url = MinimalRunnerFixture(Path(self.temporary.name) / "wrong-snapshot")
        runtime = wrong_url.platform()["runtime_image"]
        assert isinstance(runtime, dict)
        package = runtime["bash"]["binary_package"]
        package["url"] = "https://snapshot.debian.org/archive/not-content-addressed"
        wrong_url.expected_runtime_inputs["linux/amd64"]["bash"]["binary_package"][
            "url"
        ] = package["url"]
        wrong_url.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "snapshot URL"):
            wrong_url.verify()

    def test_bash_package_and_license_member_bytes_are_verified(self) -> None:
        original_length = len(b"bookworm-bash:linux/amd64")
        self.fixture.rewrite_deb(bash_data=b"x" * original_length)
        with self.assertRaisesRegex(VERIFIER.VerificationError, "package_member digest"):
            self.fixture.verify()

        replacement = MinimalRunnerFixture(Path(self.temporary.name) / "license-member")
        replacement.rewrite_deb(license_data=b"different license")
        with self.assertRaisesRegex(VERIFIER.VerificationError, "license_member"):
            replacement.verify()

    def test_common_bash_sources_are_verified_once_and_must_match(self) -> None:
        source = self.fixture.source_inputs[0]
        source_path = self.fixture.assets / source["filename"]
        source_path.write_bytes(b"tampered source")
        with self.assertRaisesRegex(VERIFIER.VerificationError, "exact bytes changed"):
            self.fixture.verify()

        replacement = MinimalRunnerFixture(Path(self.temporary.name) / "divergent-source")
        runtime = replacement.platform("linux/arm64")["runtime_image"]
        assert isinstance(runtime, dict)
        source_inputs = runtime["bash"]["source_inputs"]
        source_inputs[0]["sha256"] = "f" * 64
        replacement.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "identical across"):
            replacement.verify()

    def test_deb_tar_traversal_links_devices_duplicates_and_garbage_fail_closed(self) -> None:
        cases = (
            ({"extra_kind": "traversal"}, "unsafe archive member"),
            ({"extra_kind": "symlink"}, "unpinned symlink"),
            ({"extra_kind": "hardlink"}, "hard links"),
            ({"extra_kind": "device"}, "special tar member"),
            ({"extra_kind": "duplicate"}, "duplicate tar member"),
            ({"trailing_tar_data": b"garbage"}, "block aligned|trailing data"),
            ({"trailing_xz_data": b"garbage"}, "trailing data after xz"),
            ({"trailing_ar_data": b"garbage"}, "trailing garbage"),
            ({"extra_kind": "duplicate-ar"}, "duplicate ar member"),
            ({"bash_mode": 0o777}, "unsafe tar member mode"),
            ({"license_mode": 0o666}, "unsafe tar member mode"),
            ({"ar_mode": 0o100666}, "unexpected ar ownership or mode"),
        )
        for index, (arguments, message) in enumerate(cases):
            with self.subTest(arguments=arguments):
                fixture = MinimalRunnerFixture(
                    Path(self.temporary.name) / f"malicious-deb-{index}"
                )
                fixture.rewrite_deb(**arguments)
                with self.assertRaisesRegex(VERIFIER.VerificationError, message):
                    fixture.verify()

    def test_deb_package_member_cannot_be_replaced_by_the_permitted_symlink(self) -> None:
        runtime = self.fixture.platform()["runtime_image"]
        assert isinstance(runtime, dict)
        package_member = runtime["bash"]["package_member"]
        package_member["path"] = "bin/rbash"
        package_member["bytes"] = 1
        package_member["sha256"] = digest(b"x")
        expected = self.fixture.expected_runtime_inputs["linux/amd64"]["bash"][
            "package_member"
        ]
        expected.update(copy.deepcopy(package_member))
        self.fixture.save()
        with self.assertRaisesRegex(
            VERIFIER.VerificationError, "package member path or mode"
        ):
            self.fixture.verify()

    def test_runtime_download_and_install_mutation_cannot_be_enabled(self) -> None:
        policy = self.fixture.manifest_value["runtime_mutation_policy"]
        assert isinstance(policy, dict)
        policy["tool_download_at_runtime"] = True
        self.fixture.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "mutation"):
            self.fixture.verify()

    def test_manifest_and_declared_artifact_sizes_are_bounded_before_use(self) -> None:
        archive = self.fixture.component()["archive"]
        assert isinstance(archive, dict)
        archive["bytes"] = VERIFIER.MAX_ARCHIVE_BYTES + 1
        self.fixture.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "bounded maximum"):
            self.fixture.verify()

        replacement = MinimalRunnerFixture(Path(self.temporary.name) / "huge-manifest")
        with replacement.manifest.open("ab") as stream:
            stream.write(b" " * (VERIFIER.MAX_MANIFEST_BYTES + 1))
        with self.assertRaisesRegex(VERIFIER.VerificationError, "byte limit"):
            replacement.verify()

    def test_standalone_components_are_pinned_to_the_openai_release_origin(self) -> None:
        archive = self.fixture.component()["archive"]
        assert isinstance(archive, dict)
        archive["url"] = f"https://mirror.invalid/{archive['filename']}"
        self.fixture.save()
        with self.assertRaisesRegex(VERIFIER.VerificationError, "pinned OpenAI release"):
            self.fixture.verify()

    def test_retired_v1_entrypoints_are_explicit_fail_closed_stubs(self) -> None:
        for entrypoint in (
            VERIFIER.verify_package_archive,
            VERIFIER.verify_signed_sidecar,
            VERIFIER.verify_imported_sidecar,
        ):
            with (
                self.subTest(entrypoint=entrypoint.__name__),
                self.assertRaisesRegex(VERIFIER.VerificationError, "retired"),
            ):
                entrypoint(Path("/does/not/exist"))

    def test_cli_exposes_only_minimal_runner_and_jsonl_commands(self) -> None:
        parser = VERIFIER.build_parser()
        subparsers = next(
            action for action in parser._actions
            if isinstance(action, VERIFIER.argparse._SubParsersAction)
        )
        self.assertEqual(set(subparsers.choices), {"minimal-runner", "jsonl"})
        runner = subparsers.choices["minimal-runner"]
        self.assertIn("--locked", {option for action in runner._actions
                                    for option in action.option_strings})


class CodexJsonlVerifierTests(unittest.TestCase):
    def test_complete_stream_passes(self) -> None:
        report = VERIFIER.validate_jsonl_bytes(encode_events(valid_events()))
        self.assertEqual(report["terminal_event"], "turn.completed")
        self.assertEqual(report["unfinished_item_count"], 0)

    def test_incomplete_cancel_prefix_is_distinct_from_completion(self) -> None:
        report = VERIFIER.validate_jsonl_bytes(
            encode_events(valid_events()[:3]), require_terminal=False
        )
        self.assertIsNone(report["terminal_event"])
        with self.assertRaisesRegex(VERIFIER.VerificationError, "lacks one terminal"):
            VERIFIER.validate_jsonl_bytes(encode_events(valid_events()[:3]))

    def test_duplicate_json_key_is_rejected(self) -> None:
        stream = (
            b'{"type":"thread.started","thread_id":"one","thread_id":"two"}\n'
            b'{"type":"turn.started"}\n'
            b'{"type":"turn.failed","error":{"message":"failed"}}\n'
        )
        with self.assertRaisesRegex(VERIFIER.VerificationError, "duplicate JSON object key"):
            VERIFIER.validate_jsonl_bytes(stream)

    def test_nonfinite_and_unbounded_numbers_are_rejected(self) -> None:
        nonfinite = (
            b'{"type":"thread.started","thread_id":"one","value":NaN}\n'
            b'{"type":"turn.started"}\n'
            b'{"type":"turn.failed","error":{"message":"failed"}}\n'
        )
        with self.assertRaisesRegex(VERIFIER.VerificationError, "non-finite"):
            VERIFIER.validate_jsonl_bytes(nonfinite)
        huge = (
            b'{"type":"thread.started","thread_id":"one","value":'
            + b"9" * 1024
            + b'}\n{"type":"turn.started"}\n'
            b'{"type":"turn.failed","error":{"message":"failed"}}\n'
        )
        with self.assertRaisesRegex(VERIFIER.VerificationError, "128 digits"):
            VERIFIER.validate_jsonl_bytes(huge)

    def test_event_after_terminal_is_rejected(self) -> None:
        events = valid_events()
        events.append({"type": "error", "message": "late"})
        with self.assertRaisesRegex(VERIFIER.VerificationError, "terminal event must be"):
            VERIFIER.validate_jsonl_bytes(encode_events(events))

    def test_unterminated_final_line_is_rejected(self) -> None:
        with self.assertRaisesRegex(VERIFIER.VerificationError, "newline boundary"):
            VERIFIER.validate_jsonl_bytes(encode_events(valid_events()).rstrip(b"\n"))

    def test_crlf_is_rejected_as_a_wire_format_change(self) -> None:
        with self.assertRaisesRegex(VERIFIER.VerificationError, "LF delimiters only"):
            VERIFIER.validate_jsonl_bytes(encode_events(valid_events()).replace(b"\n", b"\r\n"))

    def test_terminal_event_cannot_leave_an_item_active(self) -> None:
        events = valid_events()
        del events[5]
        with self.assertRaisesRegex(VERIFIER.VerificationError, "unfinished items"):
            VERIFIER.validate_jsonl_bytes(encode_events(events))

    def test_updated_item_requires_started_item(self) -> None:
        events = valid_events()
        events[3] = events[4]
        del events[4]
        with self.assertRaisesRegex(VERIFIER.VerificationError, "without item.started"):
            VERIFIER.validate_jsonl_bytes(encode_events(events))

    def test_item_type_cannot_change_for_one_id(self) -> None:
        events = valid_events()
        events[4]["item"]["type"] = "reasoning"
        with self.assertRaisesRegex(VERIFIER.VerificationError, "item type changed"):
            VERIFIER.validate_jsonl_bytes(encode_events(events))

    def test_json_depth_and_line_limits_are_enforced(self) -> None:
        nested: object = "leaf"
        for _ in range(40):
            nested = [nested]
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            {"type": "turn.started", "nested": nested},
            {"type": "turn.failed", "error": {"message": "failed"}},
        ]
        with self.assertRaisesRegex(VERIFIER.VerificationError, "nesting exceeds"):
            VERIFIER.validate_jsonl_bytes(encode_events(events))


class CodexRunnerLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="deeptwin-codex-runner-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixture = self.root / "fake_codex_runner.py"
        self.fixture.write_text(textwrap.dedent(FAKE_CLI), encoding="utf-8")
        self.fixture.chmod(0o755)
        self.cli = [sys.executable, str(self.fixture)]

    def test_offline_auth_lifecycle_never_reads_credential_bytes(self) -> None:
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-leak"}):
            report = VERIFIER.exercise_offline_auth_fixture(
                self.cli,
                fixture_sha256=digest(self.fixture.read_bytes()),
                base_directory=self.root / "lifecycle",
            )
        self.assertTrue(report["fixture_marker_verified"])
        self.assertFalse(report["credential_bytes_observed"])
        self.assertEqual(report["jsonl_run"]["outcome"], "completed")

    def test_auth_exercise_refuses_unmarked_executable_before_login(self) -> None:
        touched = self.root / "login-was-called"
        impostor = self.root / "impostor.py"
        impostor.write_text(
            "import pathlib,sys\n"
            f"p=pathlib.Path({str(touched)!r})\n"
            "print('codex-cli 0.153.4') if sys.argv[1:]==['--version'] else p.write_text('bad')\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(VERIFIER.VerificationError, "refusing auth exercise"):
            VERIFIER.exercise_offline_auth_fixture(
                [sys.executable, str(impostor)],
                fixture_sha256=digest(impostor.read_bytes()),
                base_directory=self.root / "refusal",
            )
        self.assertFalse(touched.exists())

    def test_auth_fixture_hash_is_checked_before_execution(self) -> None:
        touched = self.root / "fixture-ran"
        candidate = self.root / "candidate.py"
        candidate.write_text(
            f"import pathlib\npathlib.Path({str(touched)!r}).write_text('ran')\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(VERIFIER.VerificationError, "hash changed"):
            VERIFIER.exercise_offline_auth_fixture(
                [sys.executable, str(candidate)],
                fixture_sha256="0" * 64,
                base_directory=self.root / "hash-refusal",
            )
        self.assertFalse(touched.exists())

    def test_cancel_signals_the_owned_process_group(self) -> None:
        base = self.root / "cancel"
        home = VERIFIER.prepare_isolated_codex_home(base)
        workspace = base / "workspace"
        workspace.mkdir(mode=0o700)
        marker = base / "child-signal"
        report = VERIFIER.run_codex_jsonl(
            self.cli,
            prompt="offline fixture prompt",
            model="fixture-model",
            workspace=workspace,
            codex_home=home,
            timeout_seconds=3,
            cancel_after_seconds=0.3,
            signal_grace_seconds=0.5,
            extra_environment={
                "DEEPTWIN_OFFLINE_FIXTURE": "1",
                "DEEPTWIN_FIXTURE_SCENARIO": "hang",
                "DEEPTWIN_CANCEL_MARKER": str(marker),
            },
        )
        self.assertEqual(report["outcome"], "cancelled")
        self.assertEqual(report["signals_sent"][0], "SIGINT")
        self.assertEqual(marker.read_text(encoding="utf-8"), "SIGINT")
        self.assertIsNone(report["protocol"]["terminal_event"])

    def test_stdout_flood_is_capped_and_killed(self) -> None:
        base = self.root / "flood"
        home = VERIFIER.prepare_isolated_codex_home(base)
        workspace = base / "workspace"
        workspace.mkdir(mode=0o700)
        report = VERIFIER.run_codex_jsonl(
            self.cli,
            prompt="offline fixture prompt",
            model="fixture-model",
            workspace=workspace,
            codex_home=home,
            timeout_seconds=3,
            signal_grace_seconds=0.2,
            stdout_limit=4096,
            extra_environment={
                "DEEPTWIN_OFFLINE_FIXTURE": "1",
                "DEEPTWIN_FIXTURE_SCENARIO": "flood",
            },
        )
        self.assertEqual(report["outcome"], "output_limit_exceeded")
        self.assertGreater(report["stdout"]["bytes_seen"], 4096)
        self.assertEqual(report["stdout"]["bytes_retained"], 4096)

    def test_sensitive_environment_override_is_rejected(self) -> None:
        base = self.root / "environment"
        home = VERIFIER.prepare_isolated_codex_home(base)
        with self.assertRaisesRegex(VERIFIER.VerificationError, "sensitive"):
            VERIFIER.isolated_environment(
                home, extra={"DEEPTWIN_API_KEY": "forbidden"}
            )

    def test_default_runner_environment_uses_the_pinned_path_and_bash(self) -> None:
        home = VERIFIER.prepare_isolated_codex_home(self.root / "fixed-environment")
        environment = VERIFIER.isolated_environment(home)
        self.assertEqual(environment["PATH"], VERIFIER.FIXED_PATH_ENV)
        self.assertEqual(environment["SHELL"], "/bin/bash")

    def test_codex_home_symlink_is_rejected(self) -> None:
        base = self.root / "linked-home"
        real = base / "real"
        real.mkdir(parents=True, mode=0o700)
        linked = base / "linked"
        linked.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(VERIFIER.VerificationError, "non-symlink"):
            VERIFIER.isolated_environment(linked)

    def test_nonreading_stdin_cannot_block_the_deadline_loop(self) -> None:
        sleeper = self.root / "nonreader.py"
        sleeper.write_text(
            "import signal,time\n"
            "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "time.sleep(10)\n",
            encoding="utf-8",
        )
        result = VERIFIER.run_bounded_process(
            [sys.executable, str(sleeper)],
            cwd=self.root,
            environment={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            stdin_data=b"x" * (64 * 1024),
            timeout_seconds=0.2,
            signal_grace_seconds=0.1,
        )
        self.assertEqual(result.stop_reason, "deadline_exceeded")
        self.assertLess(result.elapsed_seconds, 1.5)

    def test_detached_descendant_pipe_has_a_hard_drain_cutoff(self) -> None:
        escaper = self.root / "escaper.py"
        escaper.write_text(
            "import subprocess,sys\n"
            "subprocess.Popen([sys.executable,'-c','import time;time.sleep(2)'], "
            "start_new_session=True)\n",
            encoding="utf-8",
        )
        result = VERIFIER.run_bounded_process(
            [sys.executable, str(escaper)],
            cwd=self.root,
            environment={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            timeout_seconds=0.2,
            signal_grace_seconds=0.1,
        )
        self.assertEqual(result.stop_reason, "deadline_exceeded")
        self.assertLess(result.elapsed_seconds, 1.5)

    def test_auth_symlink_is_rejected_without_following_it(self) -> None:
        base = self.root / "symlink"
        home = VERIFIER.prepare_isolated_codex_home(base)
        outside = base / "outside"
        outside.write_text("not-a-credential", encoding="utf-8")
        (home / "auth.json").symlink_to(outside)
        with self.assertRaisesRegex(VERIFIER.VerificationError, "non-symlink"):
            VERIFIER.credential_file_state(home)


if __name__ == "__main__":
    unittest.main()
