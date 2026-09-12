#!/usr/bin/env python3
"""Fail-closed verifier for the Codex 0.153.4 Rust input inventory.

The default check is repository-local and network-free.  Optional artifact
directories let a release operator recheck the exact source, crates.io, Git and
rusty_v8 bytes used to generate the inventory.  Passing this verifier means the
technical inventory is internally and byte-level consistent; it is not legal
approval, binary reproducibility, or cryptographic provenance for unsigned and
unattested upstream inputs.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import tomllib
from typing import Any


EXPECTED_INVENTORY_DIGEST = (
    "a09a94f6099c7f003555d4a1b43da996098c11d2c26a7cefb75062c2799b0d47"
)
CODEX_COMMIT = "3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
SOURCE_ARCHIVE = {
    "url": f"https://codeload.github.com/openai/codex/tar.gz/{CODEX_COMMIT}",
    "bytes": 13_330_433,
    "sha256": "bbbf66ffa30846f1e9bc3ae8a87a5aa0bb768efee8dbb94759dc9eb64bb4aa3a",
    "root": f"codex-{CODEX_COMMIT}",
    "commit_signature": "unsigned",
}
ORIGINAL_LOCK = {
    "path": "codex-rs/Cargo.lock",
    "bytes": 378_387,
    "sha256": "3494b8a78d0f643556a83a9cc184e912bcab9f4c5640288952f4223452ba5dc8",
}
EFFECTIVE_LOCK = {
    "path": "codex-rs/Cargo.lock",
    "bytes": 378_685,
    "sha256": "a2cb91dfb2e8112bc81d05158fa00b9698e2df8cc1ae0547b5dc5606a44904d3",
    "derivation": "149 workspace-only version rewrites from 0.0.0 to 0.153.4; no package source, checksum, dependency or name changed",
    "workspace_version_rewrite_count": 149,
}
ALLOWED_MEMBERSHIPS = {
    f"{root}@{platform}"
    for root in ("codex", "code-mode-host", "bwrap")
    for platform in ("linux/amd64", "linux/arm64")
}
EXPECTED_MATRIX = {
    ("bwrap", "linux/amd64"): (
        "x86_64-unknown-linux-musl",
        6,
        "aa178f15381552e99dcf62edbee42eee2ab1846d53e01f06cd6f12015765e87c",
    ),
    ("bwrap", "linux/arm64"): (
        "aarch64-unknown-linux-musl",
        6,
        "aa178f15381552e99dcf62edbee42eee2ab1846d53e01f06cd6f12015765e87c",
    ),
    ("code-mode-host", "linux/amd64"): (
        "x86_64-unknown-linux-musl",
        537,
        "fc23b7bf9b47fb570a2b55a5607ae6e5e00b596dddb3e8b49e6a7b8dabfe520b",
    ),
    ("code-mode-host", "linux/arm64"): (
        "aarch64-unknown-linux-musl",
        537,
        "fc23b7bf9b47fb570a2b55a5607ae6e5e00b596dddb3e8b49e6a7b8dabfe520b",
    ),
    ("codex", "linux/amd64"): (
        "x86_64-unknown-linux-musl",
        1_016,
        "e8223b94a3b2d51f1c7673f9ffcde10d7229880e21da983669c67d92906a1598",
    ),
    ("codex", "linux/arm64"): (
        "aarch64-unknown-linux-musl",
        1_014,
        "e437ec088247a90dfe7f44ba1160704d269a17e8ddba64db2e5a12d92dd4c503",
    ),
}
EXPECTED_GIT_ARCHIVES = {
    "git:openai-oss-forks/crossterm@45fecb9508105988f42fe6ff0441783ed3717f92": (
        "crossterm-45fecb9508105988f42fe6ff0441783ed3717f92.tar.gz",
        144_786,
        "408decc2710285f01e6a154e2605891e1af297961fd4e6517dcbfb9491eb6c6f",
    ),
    "git:helix-editor/nucleo@4253de9faabb4e5c6d81d946a5e35a90f87347ee": (
        "nucleo-4253de9faabb4e5c6d81d946a5e35a90f87347ee.tar.gz",
        86_782,
        "d1676ac33a82c5903ffede68ce73c9d924666aa8a102bb649a8fb926a7a61ce1",
    ),
    "git:openai-oss-forks/tokio-tungstenite@0e5b2d73aa18dd9f0a50ee9ff199d5aef7594186": (
        "tokio-tungstenite-0e5b2d73aa18dd9f0a50ee9ff199d5aef7594186.tar.gz",
        33_055,
        "a1d8bfedf41ea59d5ed375ebc280dad7099d0c3398e91406c51d485270196a3d",
    ),
    "git:openai-oss-forks/tungstenite-rs@4fffad30fe373adbdcffab9545e9e9bf4f2fc19f": (
        "tungstenite-rs-4fffad30fe373adbdcffab9545e9e9bf4f2fc19f.tar.gz",
        293_806,
        "d85393467dd5843688059bb204a61b7450dce1166a2c8aab3c87478955ffce48",
    ),
}
EXPECTED_V8_ASSETS = {
    "x86_64-unknown-linux-musl": {
        "librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-musl.a.gz": (
            29_557_041,
            "d06e08bcbf45a90cfeac8a4d322c7288775cb5e3609ca703ea312b155174e46a",
        ),
        "src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-musl.rs": (
            39_884,
            "7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506",
        ),
        "rusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-musl.sha256": (
            264,
            "9bd5beb3a7bfa4f95bc887476ec3e4d564254c1815efe63296740e09bcc8665b",
        ),
    },
    "aarch64-unknown-linux-musl": {
        "librusty_v8_ptrcomp_sandbox_release_aarch64-unknown-linux-musl.a.gz": (
            28_897_449,
            "d258efd9c17b67077013f110302ff148fd11428cc4804fcb5c9ad05e3e634cb4",
        ),
        "src_binding_ptrcomp_sandbox_release_aarch64-unknown-linux-musl.rs": (
            39_884,
            "7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506",
        ),
        "rusty_v8_ptrcomp_sandbox_release_aarch64-unknown-linux-musl.sha256": (
            266,
            "9c40a51e4d5fcedaec527757b8660115b2a10ca3e2ddacadc3075924ad005b66",
        ),
    },
}

EXPECTED_QUALIFICATION_LIMITS = [
    (
        "The inventory binds Cargo normal/build membership for the three Rust "
        "roots selected by ADR-013's minimal standalone Codex runner on "
        "linux/amd64 and linux/arm64. This closes T089 enumeration; bit-for-bit "
        "reproduction of separately signed outputs remains T082 packaged "
        "provenance work."
    ),
    (
        "All 1,047 reachable packages declare a license expression, but 73 "
        "registry archives have no in-archive "
        "LICENSE/COPYING/NOTICE/UNLICENSE/COPYRIGHT candidate; final notice-text "
        "selection, transitive notices and source offers, publishable LICENSES "
        "and redistribution/legal/publication approval remain T084 work."
    ),
    (
        "The pinned Codex and rusty_v8 commits are unsigned and the exact V8 "
        "assets are checksum-bound on a mutable release without an observed "
        "artifact attestation. This exact-input risk remains T079 integrated "
        "security qualification and does not reopen T089."
    ),
    (
        "Per-final-image SBOMs, source-to-binary provenance and any authorized "
        "signing are T082 outputs, not products of this T089 input inventory."
    ),
]

HEX64 = re.compile(r"^[0-9a-f]{64}$")


class VerificationError(ValueError):
    pass


def load_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise VerificationError(f"required regular JSON file is absent: {path}")

    def reject_duplicates(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise VerificationError(f"duplicate JSON key {key!r}: {path}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=reject_duplicates)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def require_regular(path: Path, *, size: int, digest: str, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise VerificationError(f"{label} is absent or not a regular file: {path}")
    if path.stat().st_size != size or sha256_file(path) != digest:
        raise VerificationError(f"{label} size or SHA-256 changed: {path}")


def load_lock(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise VerificationError(f"Cargo.lock is absent or not regular: {path}")
    with path.open("rb") as handle:
        value = tomllib.load(handle)
    if value.get("version") != 4 or not isinstance(value.get("package"), list):
        raise VerificationError(f"unexpected Cargo.lock schema: {path}")
    return value["package"]


def verify_lock_derivation(original_path: Path, effective_path: Path) -> dict[tuple[str, str, str | None], dict[str, Any]]:
    require_regular(
        original_path,
        size=ORIGINAL_LOCK["bytes"],
        digest=ORIGINAL_LOCK["sha256"],
        label="original Cargo.lock",
    )
    require_regular(
        effective_path,
        size=EFFECTIVE_LOCK["bytes"],
        digest=EFFECTIVE_LOCK["sha256"],
        label="effective Cargo.lock",
    )
    original = load_lock(original_path)
    effective = load_lock(effective_path)
    if len(original) != 1_381 or len(effective) != 1_381:
        raise VerificationError("Cargo.lock must retain exactly 1,381 packages")

    left: dict[str, list[dict[str, Any]]] = defaultdict(list)
    right: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in original:
        left[record["name"]].append(record)
    for record in effective:
        right[record["name"]].append(record)
    if set(left) != set(right):
        raise VerificationError("Cargo.lock package names changed")
    changes = 0
    for name in sorted(left):
        if len(left[name]) != len(right[name]):
            raise VerificationError(f"Cargo.lock package multiplicity changed: {name}")
        for before, after in zip(left[name], right[name], strict=True):
            changed = {
                key
                for key in set(before) | set(after)
                if before.get(key) != after.get(key)
            }
            if not changed:
                continue
            if (
                changed != {"version"}
                or before.get("version") != "0.0.0"
                or after.get("version") != "0.153.4"
                or before.get("source") is not None
                or after.get("source") is not None
            ):
                raise VerificationError(
                    f"Cargo.lock has a non-workspace-version change: {name} {changed}"
                )
            changes += 1
    if changes != 149:
        raise VerificationError(
            f"Cargo.lock workspace version rewrite count changed: {changes}"
        )
    indexed = {
        (record["name"], record["version"], record.get("source")): record
        for record in effective
    }
    if len(indexed) != len(effective):
        raise VerificationError("effective Cargo.lock identities are not unique")
    return indexed


def verify_license_files(value: Any, *, symlinks_allowed: bool) -> None:
    if not isinstance(value, list):
        raise VerificationError("license_files must be a list")
    paths: list[str] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise VerificationError("license file entry is malformed")
        path = PurePosixPath(item["path"])
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise VerificationError(f"unsafe license file path: {item['path']}")
        paths.append(item["path"])
        if set(item) == {"path", "bytes", "sha256"}:
            if (
                type(item["bytes"]) is not int
                or item["bytes"] < 0
                or not isinstance(item["sha256"], str)
                or HEX64.fullmatch(item["sha256"]) is None
            ):
                raise VerificationError(f"invalid license file descriptor: {item}")
        elif set(item) == {"path", "symlink_target"} and symlinks_allowed:
            if not isinstance(item["symlink_target"], str):
                raise VerificationError("license symlink target is malformed")
        else:
            raise VerificationError(f"license file claim inventory changed: {item}")
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise VerificationError("license file paths must be unique and sorted")


def verify_source_archive(path: Path, source: dict[str, Any]) -> None:
    require_regular(
        path,
        size=SOURCE_ARCHIVE["bytes"],
        digest=SOURCE_ARCHIVE["sha256"],
        label="Codex source archive",
    )
    expected_files = {
        item["path"]: {"bytes": item["bytes"], "sha256": item["sha256"]}
        for item in source["source_files"]
    }
    expected_files["codex-rs/Cargo.lock"] = {
        "bytes": ORIGINAL_LOCK["bytes"],
        "sha256": ORIGINAL_LOCK["sha256"],
    }
    with tarfile.open(path, "r:gz") as archive:
        members = {member.name: member for member in archive.getmembers()}
        for member in members.values():
            parsed = PurePosixPath(member.name)
            if parsed.is_absolute() or ".." in parsed.parts:
                raise VerificationError(f"unsafe source archive member: {member.name}")
        for relative, expected in expected_files.items():
            name = f"{SOURCE_ARCHIVE['root']}/{relative}"
            member = members.get(name)
            if member is None or not member.isfile():
                raise VerificationError(f"source archive member is absent: {relative}")
            handle = archive.extractfile(member)
            if handle is None:
                raise VerificationError(f"source archive member cannot be read: {relative}")
            content = handle.read()
            if (
                len(content) != expected["bytes"]
                or hashlib.sha256(content).hexdigest() != expected["sha256"]
            ):
                raise VerificationError(f"source archive member changed: {relative}")


def verify_inventory(
    root: Path,
    *,
    inventory_path: Path | None = None,
    enforce_expected_digest: bool = True,
    source_archive: Path | None = None,
    cargo_cache: Path | None = None,
    git_archive_dir: Path | None = None,
    rusty_v8_dir: Path | None = None,
) -> dict[str, Any]:
    inventory_path = inventory_path or (
        root / "deploy/manifests/codex-0.153.4-rust-dependencies.json"
    )
    value = load_json(inventory_path)
    expected_keys = {
        "schema_version",
        "status",
        "codex",
        "source",
        "resolver",
        "targets",
        "roots",
        "git_sources",
        "external_build_inputs",
        "packages",
        "summary",
        "qualification_limits",
        "release_gate",
        "inventory_digest",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise VerificationError("Codex Rust inventory root claim set changed")
    if (
        value["schema_version"] != "deeptwin-codex-rust-dependency-inventory-v1"
        or value["status"] != "candidate_exact_input_inventory_not_release_qualified"
        or value["release_gate"] != "not_satisfied"
        or value["codex"]
        != {
            "version": "0.153.4",
            "tag": "rust-v0.153.4",
            "source_commit": CODEX_COMMIT,
        }
    ):
        raise VerificationError("Codex Rust inventory identity or non-release status changed")
    digest_input = dict(value)
    observed_digest = digest_input.pop("inventory_digest")
    calculated_digest = canonical_digest(digest_input)
    if observed_digest != calculated_digest:
        raise VerificationError("Codex Rust inventory self-digest changed")
    if enforce_expected_digest and calculated_digest != EXPECTED_INVENTORY_DIGEST:
        raise VerificationError("Codex Rust pinned semantic inventory changed")

    source = value["source"]
    if (
        not isinstance(source, dict)
        or set(source)
        != {
            "id",
            "archive",
            "original_cargo_lock",
            "effective_release_cargo_lock",
            "source_files",
        }
        or source["id"] != "codex-source"
        or source["archive"] != SOURCE_ARCHIVE
        or source["original_cargo_lock"] != ORIGINAL_LOCK
        or source["effective_release_cargo_lock"] != EFFECTIVE_LOCK
    ):
        raise VerificationError("Codex source or Cargo.lock binding changed")
    source_files = source["source_files"]
    expected_source_paths = {
        "LICENSE",
        "NOTICE",
        "codex-rs/Cargo.toml",
        "codex-rs/cli/Cargo.toml",
        "codex-rs/code-mode-host/Cargo.toml",
        "codex-rs/bwrap/Cargo.toml",
        "codex-rs/rust-toolchain.toml",
        "codex-rs/vendor/bubblewrap/COPYING",
        ".github/workflows/rust-release.yml",
        ".github/actions/setup-rusty-v8/action.yml",
    }
    if (
        not isinstance(source_files, list)
        or {item.get("path") for item in source_files if isinstance(item, dict)}
        != expected_source_paths
        or any(
            set(item) != {"path", "bytes", "sha256"}
            or type(item["bytes"]) is not int
            or item["bytes"] <= 0
            or not isinstance(item["sha256"], str)
            or HEX64.fullmatch(item["sha256"]) is None
            for item in source_files
        )
    ):
        raise VerificationError("Codex selected source-file inventory changed")

    resolver = value["resolver"]
    if (
        not isinstance(resolver, dict)
        or resolver.get("cargo_version") != "1.95.0"
        or resolver.get("rustc_version") != "1.95.0"
        or resolver.get("edges") != ["normal", "build"]
        or resolver.get("excluded_edges") != ["dev"]
        or resolver.get("network") != "offline"
        or set(resolver)
        != {
            "cargo_version",
            "rustc_version",
            "edges",
            "excluded_edges",
            "network",
            "metadata_command",
            "tree_command",
        }
    ):
        raise VerificationError("Cargo resolver scope changed")
    if value["targets"] != [
        {"platform": "linux/amd64", "target": "x86_64-unknown-linux-musl"},
        {"platform": "linux/arm64", "target": "aarch64-unknown-linux-musl"},
    ]:
        raise VerificationError("Codex Rust target set changed")
    if value["roots"] != [
        {"id": "codex", "package": "codex-cli", "package_member": "bin/codex"},
        {
            "id": "code-mode-host",
            "package": "codex-code-mode-host",
            "package_member": "bin/codex-code-mode-host",
        },
        {
            "id": "bwrap",
            "package": "codex-bwrap",
            "package_member": "codex-resources/bwrap",
        },
    ]:
        raise VerificationError("Codex Rust root set changed")

    original_lock_path = root / "deploy/locks/codex-0.153.4/Cargo.lock.source"
    effective_lock_path = root / "deploy/locks/codex-0.153.4/Cargo.lock.effective"
    lock_records = verify_lock_derivation(original_lock_path, effective_lock_path)

    git_sources = value["git_sources"]
    if not isinstance(git_sources, list) or len(git_sources) != 4:
        raise VerificationError("exact four Git source archives are required")
    git_by_id: dict[str, dict[str, Any]] = {}
    for item in git_sources:
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "id",
                "kind",
                "cargo_source",
                "commit",
                "commit_signature",
                "archive",
                "license_files",
            }
            or item.get("kind") != "git-commit-archive"
            or item.get("commit_signature") != "not_established"
            or not isinstance(item.get("id"), str)
            or item["id"] in git_by_id
        ):
            raise VerificationError("Git source claim inventory changed")
        expected = EXPECTED_GIT_ARCHIVES.get(item["id"])
        if expected is None:
            raise VerificationError(f"unexpected Git source: {item['id']}")
        filename, expected_bytes, expected_sha = expected
        if (
            item["commit"] not in item["id"]
            or not item["cargo_source"].endswith("#" + item["commit"])
            or item["archive"].get("bytes") != expected_bytes
            or item["archive"].get("sha256") != expected_sha
            or not item["archive"].get("url", "").endswith("/" + item["commit"])
        ):
            raise VerificationError(f"Git source archive binding changed: {item['id']}")
        verify_license_files(item["license_files"], symlinks_allowed=True)
        if git_archive_dir is not None:
            require_regular(
                git_archive_dir / filename,
                size=expected_bytes,
                digest=expected_sha,
                label=f"Git archive {item['id']}",
            )
        git_by_id[item["id"]] = item
    if set(git_by_id) != set(EXPECTED_GIT_ARCHIVES):
        raise VerificationError("Git source set changed")

    packages = value["packages"]
    if not isinstance(packages, list) or len(packages) != 1_047:
        raise VerificationError("exact 1,047-package union is required")
    package_sort: list[tuple[str, str, str]] = []
    membership_identifiers: dict[str, list[str]] = defaultdict(list)
    source_counts: Counter[str] = Counter()
    registry_bytes = 0
    registry_license_files = 0
    registry_without_license_files = 0
    native_links_count = 0
    custom_build_count = 0
    for package in packages:
        if not isinstance(package, dict):
            raise VerificationError("package entry is not an object")
        common = {
            "name",
            "version",
            "source_kind",
            "source_ref",
            "declared_license",
            "license_files",
            "memberships",
            "custom_build",
        }
        allowed = set(common)
        kind = package.get("source_kind")
        if kind == "registry":
            allowed.add("archive")
        elif kind == "workspace":
            allowed.add("manifest_path")
        elif kind != "git":
            raise VerificationError(f"unsupported package source kind: {kind}")
        if "native_links" in package:
            allowed.add("native_links")
        if set(package) != allowed:
            raise VerificationError(f"package claim inventory changed: {package.get('name')}")
        if not all(
            isinstance(package.get(key), str) and package[key]
            for key in ("name", "version", "source_ref", "declared_license")
        ) or type(package["custom_build"]) is not bool:
            raise VerificationError("package scalar field is malformed")
        memberships = package["memberships"]
        if (
            not isinstance(memberships, list)
            or memberships != sorted(memberships)
            or len(memberships) != len(set(memberships))
            or not memberships
            or not set(memberships).issubset(ALLOWED_MEMBERSHIPS)
        ):
            raise VerificationError(f"package memberships changed: {package['name']}")
        verify_license_files(package["license_files"], symlinks_allowed=False)
        source_counts[kind] += 1
        custom_build_count += package["custom_build"]
        native_links_count += "native_links" in package

        if kind == "registry":
            if package["source_ref"] != "crates.io-index":
                raise VerificationError("registry source reference changed")
            archive = package["archive"]
            if (
                not isinstance(archive, dict)
                or set(archive) != {"url", "bytes", "sha256"}
                or archive["url"]
                != f"https://static.crates.io/crates/{package['name']}/{package['name']}-{package['version']}.crate"
                or type(archive["bytes"]) is not int
                or archive["bytes"] <= 0
                or not isinstance(archive["sha256"], str)
                or HEX64.fullmatch(archive["sha256"]) is None
            ):
                raise VerificationError(f"registry archive malformed: {package['name']}")
            cargo_source = "registry+https://github.com/rust-lang/crates.io-index"
            lock = lock_records.get((package["name"], package["version"], cargo_source))
            if lock is None or lock.get("checksum") != archive["sha256"]:
                raise VerificationError(
                    f"registry archive disagrees with Cargo.lock: {package['name']}"
                )
            registry_bytes += archive["bytes"]
            registry_license_files += len(package["license_files"])
            registry_without_license_files += not package["license_files"]
            if cargo_cache is not None:
                require_regular(
                    cargo_cache / f"{package['name']}-{package['version']}.crate",
                    size=archive["bytes"],
                    digest=archive["sha256"],
                    label=f"crates.io archive {package['name']}@{package['version']}",
                )
        elif kind == "workspace":
            if (
                package["source_ref"] != "codex-source"
                or not package["manifest_path"].startswith("codex-rs/")
                or PurePosixPath(package["manifest_path"]).is_absolute()
                or ".." in PurePosixPath(package["manifest_path"]).parts
                or lock_records.get((package["name"], package["version"], None)) is None
            ):
                raise VerificationError(f"workspace source binding changed: {package['name']}")
        else:
            git = git_by_id.get(package["source_ref"])
            if git is None or lock_records.get(
                (package["name"], package["version"], git["cargo_source"])
            ) is None:
                raise VerificationError(f"Git package binding changed: {package['name']}")

        identity = (package["name"], package["version"], package["source_ref"])
        package_sort.append(identity)
        display = f"{package['name']}@{package['version']}|{package['source_ref']}"
        for membership in memberships:
            membership_identifiers[membership].append(display)

    if package_sort != sorted(package_sort) or len(package_sort) != len(set(package_sort)):
        raise VerificationError("package identities must be unique and sorted")
    if source_counts != Counter({"registry": 908, "workspace": 134, "git": 5}):
        raise VerificationError(f"package source counts changed: {source_counts}")

    summary = value["summary"]
    if not isinstance(summary, dict) or set(summary) != {
        "package_count_union",
        "package_counts_by_source",
        "declared_license_missing_count",
        "registry_archive_count",
        "registry_archive_bytes",
        "registry_license_file_count",
        "registry_packages_without_license_file_count",
        "git_source_archive_count",
        "native_links_package_count",
        "custom_build_package_count",
        "matrix",
    }:
        raise VerificationError("summary claim inventory changed")
    expected_summary_scalars = {
        "package_count_union": 1_047,
        "package_counts_by_source": {"git": 5, "registry": 908, "workspace": 134},
        "declared_license_missing_count": 0,
        "registry_archive_count": 908,
        "registry_archive_bytes": registry_bytes,
        "registry_license_file_count": registry_license_files,
        "registry_packages_without_license_file_count": registry_without_license_files,
        "git_source_archive_count": 4,
        "native_links_package_count": native_links_count,
        "custom_build_package_count": custom_build_count,
    }
    for key, expected in expected_summary_scalars.items():
        if summary[key] != expected:
            raise VerificationError(f"summary field changed: {key}")
    if (
        registry_bytes != 184_071_517
        or registry_license_files != 1_465
        or registry_without_license_files != 73
        or native_links_count != 14
        or custom_build_count != 98
    ):
        raise VerificationError("derived Cargo artifact or license counts changed")

    matrix = summary["matrix"]
    if not isinstance(matrix, list) or len(matrix) != 6:
        raise VerificationError("exact six root-platform summaries are required")
    observed_matrix: dict[tuple[str, str], dict[str, Any]] = {}
    for item in matrix:
        if not isinstance(item, dict) or set(item) != {
            "root",
            "platform",
            "target",
            "package_count",
            "package_set_sha256",
        }:
            raise VerificationError("matrix summary entry is malformed")
        key = (item["root"], item["platform"])
        if key in observed_matrix:
            raise VerificationError("duplicate matrix summary")
        observed_matrix[key] = item
    if set(observed_matrix) != set(EXPECTED_MATRIX):
        raise VerificationError("root-platform matrix changed")
    for key, (target, count, digest) in EXPECTED_MATRIX.items():
        item = observed_matrix[key]
        membership = f"{key[0]}@{key[1]}"
        identifiers = sorted(membership_identifiers[membership])
        if (
            item["target"] != target
            or item["package_count"] != count
            or len(identifiers) != count
            or item["package_set_sha256"] != digest
            or canonical_digest(identifiers) != digest
        ):
            raise VerificationError(f"root-platform package set changed: {membership}")

    external = value["external_build_inputs"]
    if not isinstance(external, list) or len(external) != 1:
        raise VerificationError("exact rusty_v8 external input is required")
    v8 = external[0]
    if (
        not isinstance(v8, dict)
        or set(v8)
        != {
            "component",
            "crate",
            "release_tag",
            "tag_commit",
            "tag_commit_signature",
            "asset_signature_or_attestation",
            "release_asset_mutability",
            "platforms",
        }
        or v8["component"] != "rusty_v8"
        or v8["crate"] != "v8@150.4.0"
        or v8["release_tag"] != "rusty-v8-v150.4.0"
        or v8["tag_commit"] != "12b3e88028b983051913fb6bb95d7a11218bdceb"
        or v8["tag_commit_signature"] != "unsigned"
        or v8["asset_signature_or_attestation"] != "not_provided"
        or v8["release_asset_mutability"] != "github_release_assets_not_immutable"
    ):
        raise VerificationError("rusty_v8 provenance boundary changed")
    v8_platforms = v8["platforms"]
    if not isinstance(v8_platforms, list) or len(v8_platforms) != 2:
        raise VerificationError("rusty_v8 dual-platform input set changed")
    observed_v8: set[str] = set()
    for platform_record in v8_platforms:
        if not isinstance(platform_record, dict) or set(platform_record) != {
            "platform",
            "target",
            "assets",
        }:
            raise VerificationError("rusty_v8 platform record is malformed")
        target = platform_record["target"]
        expected_assets = EXPECTED_V8_ASSETS.get(target)
        if expected_assets is None or target in observed_v8:
            raise VerificationError(f"unexpected rusty_v8 target: {target}")
        expected_platform = (
            "linux/amd64" if target.startswith("x86_64") else "linux/arm64"
        )
        if platform_record["platform"] != expected_platform:
            raise VerificationError("rusty_v8 platform mapping changed")
        assets = platform_record["assets"]
        if not isinstance(assets, list) or len(assets) != 3:
            raise VerificationError("rusty_v8 exact three-asset set is required")
        by_name = {item.get("name"): item for item in assets if isinstance(item, dict)}
        if len(by_name) != 3 or set(by_name) != set(expected_assets):
            raise VerificationError("rusty_v8 asset names changed")
        for name, (size, digest) in expected_assets.items():
            item = by_name[name]
            expected_role = (
                "static_archive"
                if name.startswith("librusty_v8")
                else "rust_binding"
                if name.startswith("src_binding")
                else "checksum_manifest"
            )
            if (
                set(item) != {"role", "name", "url", "bytes", "sha256"}
                or item["role"] != expected_role
                or item["bytes"] != size
                or item["sha256"] != digest
                or not item["url"].endswith("/" + name)
            ):
                raise VerificationError(f"rusty_v8 asset binding changed: {name}")
            if rusty_v8_dir is not None:
                require_regular(
                    rusty_v8_dir / name,
                    size=size,
                    digest=digest,
                    label=f"rusty_v8 asset {name}",
                )
        observed_v8.add(target)
    if observed_v8 != set(EXPECTED_V8_ASSETS):
        raise VerificationError("rusty_v8 target set changed")

    limits = value["qualification_limits"]
    if limits != EXPECTED_QUALIFICATION_LIMITS:
        raise VerificationError("qualification limits no longer preserve open gaps")

    if source_archive is not None:
        verify_source_archive(source_archive, source)
    return {
        "inventory_digest": calculated_digest,
        "package_count": len(packages),
        "registry_archive_count": source_counts["registry"],
        "registry_archive_bytes": registry_bytes,
        "git_source_count": len(git_sources),
        "rusty_v8_asset_count": sum(
            len(item["assets"]) for item in v8_platforms
        ),
        "release_gate": value["release_gate"],
    }


def parse_args() -> argparse.Namespace:
    default_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--source-archive", type=Path)
    parser.add_argument("--cargo-cache", type=Path)
    parser.add_argument("--git-archive-dir", type=Path)
    parser.add_argument("--rusty-v8-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = verify_inventory(
            args.root.resolve(),
            inventory_path=args.inventory.resolve() if args.inventory else None,
            source_archive=(
                args.source_archive.resolve() if args.source_archive else None
            ),
            cargo_cache=args.cargo_cache.resolve() if args.cargo_cache else None,
            git_archive_dir=(
                args.git_archive_dir.resolve() if args.git_archive_dir else None
            ),
            rusty_v8_dir=args.rusty_v8_dir.resolve() if args.rusty_v8_dir else None,
        )
    except (OSError, ValueError, tarfile.TarError, tomllib.TOMLDecodeError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(
        "PASS: Codex Rust candidate inventory is exact and remains non-release: "
        f"{result['package_count']} packages, "
        f"{result['registry_archive_bytes']} registry bytes, "
        f"digest {result['inventory_digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
