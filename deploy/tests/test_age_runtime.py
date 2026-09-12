from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, relative_path: str):
    path = REPOSITORY_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = load_module("deeptwin_age_runtime_verifier", "deploy/locks/verify_age_runtime.py")
CANARY = load_module("deeptwin_age_runtime_canary", "deploy/tests/age_runtime_canary.py")


def uvarint(value: int) -> bytes:
    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


class AgeRuntimeVerifierTests(unittest.TestCase):
    def test_inline_go_buildinfo_is_parsed_without_host_go_toolchain(self) -> None:
        module_text = (
            "path\tfilippo.io/age/cmd/age\n"
            "mod\tfilippo.io/age\tv1.3.2\t\n"
            "dep\tgolang.org/x/sys\tv0.47.0\th1:test=\n"
            "build\tCGO_ENABLED=0\n"
            "build\tGOARCH=amd64\n"
        ).encode("utf-8")
        framed = b"0" * 16 + module_text + b"1" * 16
        header = VERIFIER.BUILDINFO_MAGIC + bytes((8, 2)) + bytes(16)
        blob = header + uvarint(len(b"go1.27.0")) + b"go1.27.0" + uvarint(len(framed)) + framed
        parsed = VERIFIER.parse_go_buildinfo(blob)
        self.assertEqual(parsed["go_version"], "go1.27.0")
        self.assertEqual(parsed["path"], "filippo.io/age/cmd/age")
        self.assertEqual(parsed["dependencies"], [("golang.org/x/sys", "v0.47.0", "h1:test=")])
        self.assertEqual(parsed["build"]["CGO_ENABLED"], "0")

    def test_runtime_inventory_rejects_an_extra_plugin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deeptwin-age-inventory-") as temporary:
            root = Path(temporary)
            declarations = []
            for name, mode, value in (
                ("age", "0755", b"age"),
                ("age-keygen", "0755", b"keygen"),
                ("LICENSE", "0644", b"license"),
            ):
                path = root / name
                path.write_bytes(value)
                path.chmod(int(mode, 8))
                declarations.append(
                    {
                        "path": f"age/{name}",
                        "mode": mode,
                        "bytes": len(value),
                        "sha256": hashlib.sha256(value).hexdigest(),
                    }
                )
            declaration = {"platform": "linux/amd64", "copied_members": declarations}
            VERIFIER.verify_runtime_root(declaration, root)
            plugin = root / "age-plugin-test"
            plugin.write_bytes(b"plugin")
            plugin.chmod(0o755)
            with self.assertRaisesRegex(ValueError, "exact inventory changed"):
                VERIFIER.verify_runtime_root(declaration, root)

    def test_archive_safety_rejects_links(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".tar") as temporary:
            with tarfile.open(temporary.name, "w") as archive:
                item = tarfile.TarInfo("age/age")
                item.size = 3
                item.mode = 0o755
                archive.addfile(item, io.BytesIO(b"age"))
                link = tarfile.TarInfo("age/age-plugin-test")
                link.type = tarfile.SYMTYPE
                link.linkname = "/tmp/sentinel"
                archive.addfile(link)
            with tarfile.open(temporary.name, "r") as archive:
                with self.assertRaisesRegex(ValueError, "links and special members"):
                    VERIFIER.verify_tar_safety(archive, "fixture")

    def test_archive_safety_rejects_parent_traversal(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".tar") as temporary:
            with tarfile.open(temporary.name, "w") as archive:
                item = tarfile.TarInfo("../age")
                item.size = 3
                item.mode = stat.S_IFREG | 0o755
                archive.addfile(item, io.BytesIO(b"age"))
            with tarfile.open(temporary.name, "r") as archive:
                with self.assertRaisesRegex(ValueError, "unsafe or duplicate"):
                    VERIFIER.verify_tar_safety(archive, "fixture")


class AgeRestrictedCallerTests(unittest.TestCase):
    def test_native_shapes_are_accepted(self) -> None:
        CANARY.validate_recipient("age1" + "a" * 58)
        CANARY.validate_identity(("AGE-SECRET-KEY-1" + "A" * 58).encode("ascii"))

    def test_plugin_hybrid_ssh_and_network_recipients_are_rejected_pre_spawn(self) -> None:
        for recipient in (
            "age1test10qdmzv9q",
            "age1pq1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq",
            "ssh-ed25519 AAAATEST",
            "github:octocat",
        ):
            with self.subTest(recipient=recipient):
                with self.assertRaisesRegex(ValueError, "native X25519 only"):
                    CANARY.validate_recipient(recipient)

    def test_plugin_identity_is_rejected_pre_spawn(self) -> None:
        with self.assertRaisesRegex(ValueError, "native X25519 only"):
            CANARY.validate_identity(b"AGE-PLUGIN-TEST-10Q32NLXM")


if __name__ == "__main__":
    unittest.main()
