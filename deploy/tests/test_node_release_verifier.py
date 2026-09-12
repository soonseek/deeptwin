from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from typing import Callable


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = REPOSITORY_ROOT / "deploy/locks/verify_node_release.py"
SPEC = importlib.util.spec_from_file_location("deeptwin_node_release_verifier", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

FINGERPRINT = "5BE8A3F6C8A5C01D106C0AD820B1A390B168D356"
SIGNATURE_TIME = "2026-08-26T14:25:36Z"
SIGNATURE_EPOCH = "1787754336"
VERSION = "24.20.0"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class NodeReleaseVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="deeptwin-node-release-test-")
        self.addCleanup(self.temporary.cleanup)
        self.temporary_root = Path(self.temporary.name).resolve()
        self.root = self.temporary_root / "repo"
        (self.root / "deploy/locks/nodejs").mkdir(parents=True)
        (self.root / "deploy/locks/licenses").mkdir(parents=True)
        (self.root / "deploy/manifests").mkdir(parents=True)
        self.inputs = self.temporary_root / "inputs"
        self.inputs.mkdir()
        self.license_bytes = b"fixture Node license\n"
        self.node_bytes = {
            "amd64": b"fixture-node-amd64\n",
            "arm64": b"fixture-node-arm64\n",
        }
        self.archive_paths = {
            architecture: self._write_archive(architecture)
            for architecture in ("amd64", "arm64")
        }
        self.keyring = self.root / "deploy/locks/nodejs/release-keys-fixture.kbx"
        self.keyring.write_bytes(b"fixture keyring")
        self.license_path = self.root / "deploy/locks/licenses/Node-24.20.0-LICENSE.txt"
        self.license_path.write_bytes(self.license_bytes)
        self.gpgv = self._write_fake_gpgv(success=True)
        self.gpgv_descriptor = VERIFIER.GpgvDescriptor(
            path=self.gpgv,
            version_line="gpgv (GnuPG) fixture-1.0",
            bytes=self.gpgv.stat().st_size,
            sha256=VERIFIER.sha256_file(self.gpgv),
        )
        self.manifest = self._build_manifest()
        self._write_manifest()

    def _archive_root(self, architecture: str) -> str:
        suffix = "x64" if architecture == "amd64" else "arm64"
        return f"node-v{VERSION}-linux-{suffix}"

    def _archive_path(self, architecture: str) -> Path:
        return self.inputs / f"{self._archive_root(architecture)}.tar.xz"

    def _tar_member(
        self,
        archive: tarfile.TarFile,
        name: str,
        value: bytes | None = None,
        *,
        mode: int = 0o644,
        member_type: bytes = tarfile.REGTYPE,
        linkname: str = "",
    ) -> None:
        info = tarfile.TarInfo(name)
        info.type = member_type
        info.mode = mode
        info.linkname = linkname
        payload = b"" if value is None else value
        info.size = len(payload) if member_type == tarfile.REGTYPE else 0
        archive.addfile(info, io.BytesIO(payload) if member_type == tarfile.REGTYPE else None)

    def _write_archive(
        self,
        architecture: str,
        *,
        extra: Callable[[tarfile.TarFile, str], None] | None = None,
        license_bytes: bytes | None = None,
        node_bytes: bytes | None = None,
    ) -> Path:
        path = self._archive_path(architecture)
        root = self._archive_root(architecture)
        with tarfile.open(path, "w:xz") as archive:
            self._tar_member(archive, root, member_type=tarfile.DIRTYPE, mode=0o755)
            self._tar_member(archive, f"{root}/bin", member_type=tarfile.DIRTYPE, mode=0o755)
            self._tar_member(
                archive,
                f"{root}/bin/node",
                self.node_bytes[architecture] if node_bytes is None else node_bytes,
                mode=0o755,
            )
            self._tar_member(
                archive,
                f"{root}/LICENSE",
                self.license_bytes if license_bytes is None else license_bytes,
            )
            self._tar_member(archive, f"{root}/lib", member_type=tarfile.DIRTYPE, mode=0o755)
            self._tar_member(archive, f"{root}/lib/npm-cli.js", b"fixture\n")
            self._tar_member(
                archive,
                f"{root}/bin/npm",
                member_type=tarfile.SYMTYPE,
                mode=0o777,
                linkname="../lib/npm-cli.js",
            )
            if extra is not None:
                extra(archive, root)
        return path

    def _write_fake_gpgv(self, *, success: bool, duplicate_validsig: bool = False) -> Path:
        path = self.temporary_root / (
            f"fake-gpgv-{'pass' if success else 'fail'}-{'duplicate' if duplicate_validsig else 'one'}"
        )
        valid = (
            f"[GNUPG:] VALIDSIG {FINGERPRINT} 2026-08-26 {SIGNATURE_EPOCH} "
            f"0 4 0 22 8 01 {FINGERPRINT}"
        )
        statuses = [
            "[GNUPG:] NEWSIG",
            f"[GNUPG:] GOODSIG 20B1A390B168D356 Fixture Signer",
            valid,
        ]
        if duplicate_validsig:
            statuses.append(valid)
        body = f"""#!{sys.executable}
import sys
if '--version' in sys.argv:
    print('gpgv (GnuPG) fixture-1.0')
    raise SystemExit(0)
print({chr(10).join(statuses)!r})
raise SystemExit({0 if success else 1})
"""
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
        return path

    def _signed_text(self, checksums: dict[str, str] | None = None) -> bytes:
        if checksums is None:
            checksums = {
                path.name: VERIFIER.sha256_file(path)
                for path in self.archive_paths.values()
            }
        rows = "\n".join(f"{value}  {name}" for name, value in sorted(checksums.items()))
        return (
            "-----BEGIN PGP SIGNED MESSAGE-----\n"
            "Hash: SHA256\n\n"
            f"{rows}\n"
            "-----BEGIN PGP SIGNATURE-----\n\n"
            "fixture\n"
            "-----END PGP SIGNATURE-----\n"
        ).encode("utf-8")

    def _build_manifest(self) -> dict:
        signed_path = self.root / "deploy/locks/nodejs/node-v24.20.0-SHASUMS256.txt.asc"
        signed_path.write_bytes(self._signed_text())
        platforms = []
        base_platforms = []
        for architecture in ("amd64", "arm64"):
            archive_path = self.archive_paths[architecture]
            suffix = "x64" if architecture == "amd64" else "arm64"
            platforms.append(
                {
                    "os": "linux",
                    "architecture": architecture,
                    "archive_url": f"https://nodejs.org/dist/v{VERSION}/{archive_path.name}",
                    "archive_bytes": archive_path.stat().st_size,
                    "archive_sha256": VERIFIER.sha256_file(archive_path),
                    "executable_path": f"node-v{VERSION}-linux-{suffix}/bin/node",
                    "executable_bytes": len(self.node_bytes[architecture]),
                    "executable_sha256": digest(self.node_bytes[architecture]),
                    "base_image_executable_sha256_match": True,
                }
            )
            base_platforms.append({"os": "linux", "architecture": architecture})
        return {
            "node": {
                "version": VERSION,
                "base_image": {"platforms": base_platforms},
                "official_release_provenance": {
                    "source_repository": "https://github.com/nodejs/node",
                    "source_tag": f"v{VERSION}",
                    "source_commit": "1" * 40,
                    "signed_checksums": {
                        "path": "deploy/locks/nodejs/node-v24.20.0-SHASUMS256.txt.asc",
                        "bytes": signed_path.stat().st_size,
                        "sha256": VERIFIER.sha256_file(signed_path),
                        "openpgp_verified": True,
                        "signer_fingerprint": FINGERPRINT,
                        "signature_time_utc": SIGNATURE_TIME,
                    },
                    "verification_keyring": {
                        "source_repository": "https://github.com/nodejs/release-keys",
                        "source_commit": "2" * 40,
                        "source_path": "gpg/pubring.kbx",
                        "path": "deploy/locks/nodejs/release-keys-fixture.kbx",
                        "bytes": self.keyring.stat().st_size,
                        "sha256": VERIFIER.sha256_file(self.keyring),
                    },
                    "platforms": platforms,
                    "license": {
                        "path": "deploy/locks/licenses/Node-24.20.0-LICENSE.txt",
                        "bytes": len(self.license_bytes),
                        "sha256": digest(self.license_bytes),
                        "identical_in_both_platform_archives": True,
                    },
                },
            }
        }

    def _write_manifest(self) -> None:
        (self.root / "deploy/manifests/browser-worker.json").write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )

    def _verify(self) -> dict:
        return VERIFIER.verify_node_release(
            self.manifest,
            repository_root=self.root,
            archive_paths=self.archive_paths,
            gpgv=self.gpgv_descriptor,
        )

    def _platform(self, architecture: str) -> dict:
        return next(
            item
            for item in self.manifest["node"]["official_release_provenance"]["platforms"]
            if item["architecture"] == architecture
        )

    def _refresh_signed_reference(self, checksums: dict[str, str] | None = None) -> None:
        reference = self.manifest["node"]["official_release_provenance"]["signed_checksums"]
        path = self.root / reference["path"]
        path.write_bytes(self._signed_text(checksums))
        reference["bytes"] = path.stat().st_size
        reference["sha256"] = VERIFIER.sha256_file(path)

    def _replace_archive(self, architecture: str, **kwargs) -> None:
        self.archive_paths[architecture] = self._write_archive(architecture, **kwargs)
        platform = self._platform(architecture)
        platform["archive_bytes"] = self.archive_paths[architecture].stat().st_size
        platform["archive_sha256"] = VERIFIER.sha256_file(self.archive_paths[architecture])
        self._refresh_signed_reference()

    def assert_failure(self, code: str, call=None) -> VERIFIER.NodeReleaseVerificationError:
        with self.assertRaises(VERIFIER.NodeReleaseVerificationError) as captured:
            (self._verify if call is None else call)()
        self.assertEqual(captured.exception.code, code)
        return captured.exception

    def test_exact_dual_platform_chain_passes_offline(self) -> None:
        result = self._verify()
        self.assertTrue(result["verified"])
        self.assertFalse(result["network_used"])
        self.assertEqual([item["platform"] for item in result["platforms"]], ["linux/amd64", "linux/arm64"])
        self.assertEqual(result["gpgv"]["sha256"], self.gpgv_descriptor.sha256)

    def test_release_version_is_exactly_pinned(self) -> None:
        self.manifest["node"]["version"] = "24.20.1"
        self.assert_failure("identity_mismatch")

    def test_repository_keyring_tamper_fails(self) -> None:
        self.keyring.write_bytes(self.keyring.read_bytes() + b"tamper")
        self.assert_failure("identity_mismatch")

    def test_repository_reference_cannot_escape_or_use_symlink(self) -> None:
        signed = self.manifest["node"]["official_release_provenance"]["signed_checksums"]
        signed["path"] = "../outside.asc"
        self.assert_failure("unsafe_repository_path")

    def test_gpgv_executable_hash_and_version_are_exact_inputs(self) -> None:
        wrong_hash = VERIFIER.GpgvDescriptor(
            path=self.gpgv,
            version_line=self.gpgv_descriptor.version_line,
            bytes=self.gpgv_descriptor.bytes,
            sha256="0" * 64,
        )
        self.assert_failure(
            "identity_mismatch",
            lambda: VERIFIER.verify_node_release(
                self.manifest,
                repository_root=self.root,
                archive_paths=self.archive_paths,
                gpgv=wrong_hash,
            ),
        )
        wrong_version = VERIFIER.GpgvDescriptor(
            path=self.gpgv,
            version_line="gpgv (GnuPG) wrong",
            bytes=self.gpgv_descriptor.bytes,
            sha256=self.gpgv_descriptor.sha256,
        )
        self.assert_failure(
            "identity_mismatch",
            lambda: VERIFIER.verify_node_release(
                self.manifest,
                repository_root=self.root,
                archive_paths=self.archive_paths,
                gpgv=wrong_version,
            ),
        )

    def test_nonzero_or_ambiguous_gpgv_result_fails(self) -> None:
        failed = self._write_fake_gpgv(success=False)
        failed_descriptor = VERIFIER.GpgvDescriptor(
            path=failed,
            version_line="gpgv (GnuPG) fixture-1.0",
            bytes=failed.stat().st_size,
            sha256=VERIFIER.sha256_file(failed),
        )
        self.assert_failure(
            "openpgp_verification_failed",
            lambda: VERIFIER.verify_node_release(
                self.manifest,
                repository_root=self.root,
                archive_paths=self.archive_paths,
                gpgv=failed_descriptor,
            ),
        )
        duplicate = self._write_fake_gpgv(success=True, duplicate_validsig=True)
        duplicate_descriptor = VERIFIER.GpgvDescriptor(
            path=duplicate,
            version_line="gpgv (GnuPG) fixture-1.0",
            bytes=duplicate.stat().st_size,
            sha256=VERIFIER.sha256_file(duplicate),
        )
        self.assert_failure(
            "ambiguous_openpgp_signature",
            lambda: VERIFIER.verify_node_release(
                self.manifest,
                repository_root=self.root,
                archive_paths=self.archive_paths,
                gpgv=duplicate_descriptor,
            ),
        )

    def test_signed_checksum_must_match_archive_manifest_hash(self) -> None:
        platform = self._platform("amd64")
        platform["archive_sha256"] = "0" * 64
        self.assert_failure("identity_mismatch")

    def test_duplicate_signed_checksum_is_rejected(self) -> None:
        signed = self.manifest["node"]["official_release_provenance"]["signed_checksums"]
        path = self.root / signed["path"]
        rows = self._signed_text().decode("utf-8").splitlines()
        rows.insert(4, rows[3])
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        signed["bytes"] = path.stat().st_size
        signed["sha256"] = VERIFIER.sha256_file(path)
        self.assert_failure("duplicate_signed_checksum")

    def test_signed_checksum_filename_cannot_traverse(self) -> None:
        checksums = {
            path.name: VERIFIER.sha256_file(path)
            for path in self.archive_paths.values()
        }
        checksums["../outside"] = "0" * 64
        self._refresh_signed_reference(checksums)
        self.assert_failure("invalid_signed_checksums")

    def test_archive_url_is_exact_not_equivalent(self) -> None:
        self._platform("amd64")["archive_url"] = (
            f"https://NODEJS.ORG/dist/v{VERSION}/node-v{VERSION}-linux-x64.tar.xz"
        )
        self.assert_failure("untrusted_archive_url")

    def test_missing_or_duplicate_platform_is_rejected(self) -> None:
        platforms = self.manifest["node"]["official_release_provenance"]["platforms"]
        platforms.pop()
        self.assert_failure("platform_coverage_mismatch")
        self.manifest = self._build_manifest()
        self.manifest["node"]["official_release_provenance"]["platforms"][1]["architecture"] = "amd64"
        self.assert_failure("duplicate_platform")

    def test_base_image_match_claim_must_be_true(self) -> None:
        self._platform("arm64")["base_image_executable_sha256_match"] = False
        self.assert_failure("identity_mismatch")

    def test_node_member_hash_is_checked_after_archive_authentication(self) -> None:
        self._replace_archive("amd64", node_bytes=b"different node bytes\n")
        self.assert_failure("identity_mismatch")

    def test_license_member_must_match_locked_repository_license(self) -> None:
        self._replace_archive("arm64", license_bytes=b"different license\n")
        self.assert_failure("identity_mismatch")

    def test_duplicate_member_is_rejected(self) -> None:
        def duplicate(archive, root):
            self._tar_member(archive, f"{root}/LICENSE", self.license_bytes)

        self._replace_archive("amd64", extra=duplicate)
        self.assert_failure("duplicate_archive_member")

    def test_path_traversal_and_second_root_are_rejected(self) -> None:
        def traversal(archive, root):
            self._tar_member(archive, f"{root}/../escape", b"bad")

        self._replace_archive("amd64", extra=traversal)
        self.assert_failure("unsafe_archive_member")

        self.manifest = self._build_manifest()
        def second_root(archive, root):
            self._tar_member(archive, "other-root/file", b"bad")

        self._replace_archive("arm64", extra=second_root)
        self.assert_failure("unsafe_archive_member")

    def test_unsafe_or_dangling_symlink_is_rejected(self) -> None:
        def escaping_link(archive, root):
            self._tar_member(
                archive,
                f"{root}/bin/escape",
                member_type=tarfile.SYMTYPE,
                mode=0o777,
                linkname="../../outside",
            )

        self._replace_archive("amd64", extra=escaping_link)
        self.assert_failure("unsafe_archive_link")

        self.manifest = self._build_manifest()
        def dangling_link(archive, root):
            self._tar_member(
                archive,
                f"{root}/bin/dangling",
                member_type=tarfile.SYMTYPE,
                mode=0o777,
                linkname="../missing",
            )

        self._replace_archive("arm64", extra=dangling_link)
        self.assert_failure("unsafe_archive_link")

    def test_special_archive_member_is_rejected(self) -> None:
        def fifo(archive, root):
            self._tar_member(archive, f"{root}/fifo", member_type=tarfile.FIFOTYPE)

        self._replace_archive("amd64", extra=fifo)
        self.assert_failure("unsafe_archive_member")

    def test_two_platforms_cannot_alias_one_archive_file(self) -> None:
        self.archive_paths["arm64"] = self.archive_paths["amd64"]
        self.assert_failure("duplicate_archive_input")

    def test_strict_json_loader_rejects_duplicate_keys_and_float(self) -> None:
        manifest_path = self.root / "deploy/manifests/browser-worker.json"
        manifest_path.write_text('{"node":{},"node":{}}', encoding="utf-8")
        with self.assertRaises(VERIFIER.NodeReleaseVerificationError) as captured:
            VERIFIER.load_json(manifest_path)
        self.assertEqual(captured.exception.code, "duplicate_json_key")
        manifest_path.write_text('{"node":{"version":1.5}}', encoding="utf-8")
        with self.assertRaises(VERIFIER.NodeReleaseVerificationError) as captured:
            VERIFIER.load_json(manifest_path)
        self.assertEqual(captured.exception.code, "invalid_json")


if __name__ == "__main__":
    unittest.main()
