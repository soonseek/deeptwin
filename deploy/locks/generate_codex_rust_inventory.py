#!/usr/bin/env python3
"""Generate the pinned Codex 0.153.4 Rust dependency input inventory.

This generator intentionally consumes Cargo's offline ``metadata`` and ``tree``
outputs instead of attempting to infer target selection from Cargo.toml files.
The caller is responsible for producing those inputs with Cargo 1.95.0 and the
commands recorded in the generated manifest.  The generator then binds every
reachable crates.io archive by byte count and Cargo.lock SHA-256, every precise
Git dependency to a separately hashed commit archive, the Codex source archive
and its effective release lock, and the non-Cargo rusty_v8 build artifacts.

It is a technical build/licensing input inventory.  It does not make a legal
redistribution determination and it does not turn unsigned source or V8 assets
into cryptographically attested inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import tarfile
import tomllib
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit


CODEX_VERSION = "0.153.4"
CODEX_TAG = "rust-v0.153.4"
CODEX_COMMIT = "3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
SOURCE_ARCHIVE = {
    "url": f"https://codeload.github.com/openai/codex/tar.gz/{CODEX_COMMIT}",
    "bytes": 13_330_433,
    "sha256": "bbbf66ffa30846f1e9bc3ae8a87a5aa0bb768efee8dbb94759dc9eb64bb4aa3a",
    "root": f"codex-{CODEX_COMMIT}",
    "commit_signature": "unsigned",
}
ORIGINAL_LOCK = {
    "bytes": 378_387,
    "sha256": "3494b8a78d0f643556a83a9cc184e912bcab9f4c5640288952f4223452ba5dc8",
}
EFFECTIVE_LOCK = {
    "bytes": 378_685,
    "sha256": "a2cb91dfb2e8112bc81d05158fa00b9698e2df8cc1ae0547b5dc5606a44904d3",
}

TARGETS = (
    ("linux/amd64", "x86_64-unknown-linux-musl"),
    ("linux/arm64", "aarch64-unknown-linux-musl"),
)
ROOTS = (
    ("codex", "codex-cli", "bin/codex", ""),
    (
        "code-mode-host",
        "codex-code-mode-host",
        "bin/codex-code-mode-host",
        "code-mode-host-",
    ),
    ("bwrap", "codex-bwrap", "codex-resources/bwrap", "bwrap-"),
)

GIT_ARCHIVE_EXPECTATIONS = {
    "git+https://github.com/openai-oss-forks/crossterm?rev=45fecb9508105988f42fe6ff0441783ed3717f92#45fecb9508105988f42fe6ff0441783ed3717f92": {
        "filename": "crossterm-45fecb9508105988f42fe6ff0441783ed3717f92.tar.gz",
        "bytes": 144_786,
        "sha256": "408decc2710285f01e6a154e2605891e1af297961fd4e6517dcbfb9491eb6c6f",
    },
    "git+https://github.com/helix-editor/nucleo.git?rev=4253de9faabb4e5c6d81d946a5e35a90f87347ee#4253de9faabb4e5c6d81d946a5e35a90f87347ee": {
        "filename": "nucleo-4253de9faabb4e5c6d81d946a5e35a90f87347ee.tar.gz",
        "bytes": 86_782,
        "sha256": "d1676ac33a82c5903ffede68ce73c9d924666aa8a102bb649a8fb926a7a61ce1",
    },
    "git+https://github.com/openai-oss-forks/tokio-tungstenite?rev=0e5b2d73aa18dd9f0a50ee9ff199d5aef7594186#0e5b2d73aa18dd9f0a50ee9ff199d5aef7594186": {
        "filename": "tokio-tungstenite-0e5b2d73aa18dd9f0a50ee9ff199d5aef7594186.tar.gz",
        "bytes": 33_055,
        "sha256": "a1d8bfedf41ea59d5ed375ebc280dad7099d0c3398e91406c51d485270196a3d",
    },
    "git+https://github.com/openai-oss-forks/tungstenite-rs?rev=4fffad30fe373adbdcffab9545e9e9bf4f2fc19f#4fffad30fe373adbdcffab9545e9e9bf4f2fc19f": {
        "filename": "tungstenite-rs-4fffad30fe373adbdcffab9545e9e9bf4f2fc19f.tar.gz",
        "bytes": 293_806,
        "sha256": "d85393467dd5843688059bb204a61b7450dce1166a2c8aab3c87478955ffce48",
    },
}

RUSTY_V8_VERSION = "150.4.0"
RUSTY_V8_TAG = f"rusty-v8-v{RUSTY_V8_VERSION}"
RUSTY_V8_TAG_COMMIT = "12b3e88028b983051913fb6bb95d7a11218bdceb"
RUSTY_V8_ASSETS = {
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

QUALIFICATION_LIMITS = (
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
)

LICENSE_BASENAME = re.compile(
    r"^(?:licen[cs]e|copying|notice|unlicense|copyright)(?:$|[._-])", re.I
)
TREE_PACKAGE = re.compile(r"^([^ ]+) v([^ ]+)(?: |$)")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_descriptor(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required regular file is absent: {path}")
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def require_descriptor(path: Path, expected: dict[str, Any], label: str) -> None:
    observed = file_descriptor(path)
    if observed != {"bytes": expected["bytes"], "sha256": expected["sha256"]}:
        raise ValueError(f"{label} size or digest changed: {observed}")


def load_json(path: Path) -> Any:
    def reject_duplicates(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=reject_duplicates)


def canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def safe_tar_members(path: Path) -> list[tarfile.TarInfo]:
    with tarfile.open(path, "r:*") as archive:
        members = archive.getmembers()
    for member in members:
        posix = PurePosixPath(member.name)
        if posix.is_absolute() or ".." in posix.parts:
            raise ValueError(f"unsafe archive member in {path}: {member.name}")
    return members


def tar_member_bytes(path: Path, member_name: str) -> bytes:
    with tarfile.open(path, "r:*") as archive:
        member = archive.getmember(member_name)
        if not member.isfile():
            raise ValueError(f"archive member is not a regular file: {member_name}")
        handle = archive.extractfile(member)
        if handle is None:
            raise ValueError(f"archive member cannot be read: {member_name}")
        return handle.read()


def scan_license_members(path: Path, *, strip_root: bool) -> list[dict[str, Any]]:
    members = safe_tar_members(path)
    result: list[dict[str, Any]] = []
    with tarfile.open(path, "r:*") as archive:
        for member in members:
            if not LICENSE_BASENAME.match(PurePosixPath(member.name).name):
                continue
            parts = PurePosixPath(member.name).parts
            relative = PurePosixPath(*parts[1:]).as_posix() if strip_root else member.name
            if member.issym():
                resolved = posixpath.normpath(
                    posixpath.join(posixpath.dirname(member.name), member.linkname)
                )
                root = parts[0] if strip_root else ""
                if (
                    PurePosixPath(member.linkname).is_absolute()
                    or resolved == ".."
                    or resolved.startswith("../")
                    or (root and resolved != root and not resolved.startswith(root + "/"))
                ):
                    raise ValueError(
                        f"license symlink escapes its archive: {member.name} -> "
                        f"{member.linkname}"
                    )
                result.append(
                    {
                        "path": relative,
                        "symlink_target": member.linkname,
                    }
                )
                continue
            if not member.isfile():
                raise ValueError(
                    f"license candidate is not a regular file: {member.name}"
                )
            handle = archive.extractfile(member)
            if handle is None:
                raise ValueError(f"license candidate cannot be read: {member.name}")
            content = handle.read()
            result.append(
                {
                    "path": relative,
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
    return sorted(result, key=lambda item: item["path"])


def load_lock(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        value = tomllib.load(handle)
    if value.get("version") != 4 or not isinstance(value.get("package"), list):
        raise ValueError(f"unexpected Cargo.lock schema: {path}")
    return value


def validate_lock_derivation(original_path: Path, effective_path: Path) -> int:
    require_descriptor(original_path, ORIGINAL_LOCK, "original Cargo.lock")
    require_descriptor(effective_path, EFFECTIVE_LOCK, "effective Cargo.lock")
    original = load_lock(original_path)["package"]
    effective = load_lock(effective_path)["package"]
    if len(original) != len(effective):
        raise ValueError("Cargo.lock package count changed")

    by_name_original: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_name_effective: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in original:
        by_name_original[record["name"]].append(record)
    for record in effective:
        by_name_effective[record["name"]].append(record)
    if set(by_name_original) != set(by_name_effective):
        raise ValueError("Cargo.lock package names changed")

    changes = 0
    for name in sorted(by_name_original):
        before = by_name_original[name]
        after = by_name_effective[name]
        if len(before) != len(after):
            raise ValueError(f"Cargo.lock multiplicity changed for {name}")
        for left, right in zip(before, after, strict=True):
            changed_keys = {
                key
                for key in set(left) | set(right)
                if left.get(key) != right.get(key)
            }
            if not changed_keys:
                continue
            if (
                changed_keys != {"version"}
                or left.get("source") is not None
                or right.get("source") is not None
                or left.get("version") != "0.0.0"
                or right.get("version") != CODEX_VERSION
            ):
                raise ValueError(
                    f"Cargo.lock has a non-workspace-version change for {name}: "
                    f"{changed_keys}"
                )
            changes += 1
    if changes != 149:
        raise ValueError(f"expected 149 workspace version rewrites, observed {changes}")
    return changes


def normalize_workspace_manifest(path: str) -> str:
    marker = "/codex-rs/"
    if marker not in path:
        raise ValueError(f"workspace manifest is outside codex-rs: {path}")
    return "codex-rs/" + path.split(marker, 1)[1]


def tree_keys(path: Path, expected_root: tuple[str, str]) -> set[tuple[str, str]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Cargo tree evidence is absent: {path}")
    result: set[tuple[str, str]] = set()
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"Cargo tree evidence is empty: {path}")
    first = TREE_PACKAGE.match(lines[0].removesuffix(" (*)"))
    if first is None or first.groups() != expected_root:
        raise ValueError(f"Cargo tree root changed: {path}")
    for line in lines:
        match = TREE_PACKAGE.match(line.removesuffix(" (*)"))
        if match is None:
            raise ValueError(f"unparseable Cargo tree package line: {line!r}")
        result.add(match.groups())
    return result


def package_source_kind(source: str | None) -> str:
    if source is None:
        return "workspace"
    if source.startswith("registry+"):
        return "registry"
    if source.startswith("git+"):
        return "git"
    raise ValueError(f"unsupported Cargo source: {source}")


def git_source_descriptor(source: str, archive_dir: Path) -> dict[str, Any]:
    expected = GIT_ARCHIVE_EXPECTATIONS.get(source)
    if expected is None:
        raise ValueError(f"unrecognized precise Git source: {source}")
    archive_path = archive_dir / expected["filename"]
    require_descriptor(archive_path, expected, f"Git source {source}")

    locator = source.removeprefix("git+")
    commit = locator.rsplit("#", 1)[1]
    parsed = urlsplit(locator.split("?", 1)[0])
    repository_path = parsed.path.removesuffix(".git").strip("/")
    source_id = f"git:{repository_path}@{commit}"
    return {
        "id": source_id,
        "kind": "git-commit-archive",
        "cargo_source": source,
        "commit": commit,
        "commit_signature": "not_established",
        "archive": {
            "url": f"https://codeload.github.com/{repository_path}/tar.gz/{commit}",
            "bytes": expected["bytes"],
            "sha256": expected["sha256"],
        },
        "license_files": scan_license_members(archive_path, strip_root=True),
    }


def source_file_ref(source_root: Path, relative: str) -> dict[str, Any]:
    descriptor = file_descriptor(source_root / relative)
    return {"path": relative, **descriptor}


def build_rusty_v8_inputs(asset_dir: Path) -> dict[str, Any]:
    base = f"https://github.com/openai/codex/releases/download/{RUSTY_V8_TAG}"
    platforms: list[dict[str, Any]] = []
    for platform, target in TARGETS:
        expected_assets = RUSTY_V8_ASSETS[target]
        assets: list[dict[str, Any]] = []
        for name in sorted(expected_assets):
            expected_bytes, expected_sha256 = expected_assets[name]
            path = asset_dir / name
            require_descriptor(
                path,
                {"bytes": expected_bytes, "sha256": expected_sha256},
                f"rusty_v8 {target} asset {name}",
            )
            role = (
                "static_archive"
                if name.startswith("librusty_v8")
                else "rust_binding"
                if name.startswith("src_binding")
                else "checksum_manifest"
            )
            assets.append(
                {
                    "role": role,
                    "name": name,
                    "url": f"{base}/{name}",
                    "bytes": expected_bytes,
                    "sha256": expected_sha256,
                }
            )

        checksum = next(item for item in assets if item["role"] == "checksum_manifest")
        checksum_text = (asset_dir / checksum["name"]).read_text(encoding="utf-8")
        expected_lines = [
            f"{item['sha256']}  {item['name']}"
            for item in assets
            if item["role"] in {"static_archive", "rust_binding"}
        ]
        if sorted(checksum_text.splitlines()) != sorted(expected_lines):
            raise ValueError(f"rusty_v8 checksum content changed for {target}")
        platforms.append({"platform": platform, "target": target, "assets": assets})

    return {
        "component": "rusty_v8",
        "crate": "v8@150.4.0",
        "release_tag": RUSTY_V8_TAG,
        "tag_commit": RUSTY_V8_TAG_COMMIT,
        "tag_commit_signature": "unsigned",
        "asset_signature_or_attestation": "not_provided",
        "release_asset_mutability": "github_release_assets_not_immutable",
        "platforms": platforms,
    }


def build_inventory(args: argparse.Namespace) -> dict[str, Any]:
    source_archive = args.source_archive.resolve()
    source_root = args.source_root.resolve()
    original_lock_path = args.original_lock.resolve()
    effective_lock_path = source_root / "codex-rs/Cargo.lock"
    require_descriptor(source_archive, SOURCE_ARCHIVE, "Codex source archive")
    lock_member = f"{SOURCE_ARCHIVE['root']}/codex-rs/Cargo.lock"
    archive_lock = tar_member_bytes(source_archive, lock_member)
    if (
        len(archive_lock) != ORIGINAL_LOCK["bytes"]
        or hashlib.sha256(archive_lock).hexdigest() != ORIGINAL_LOCK["sha256"]
        or archive_lock != original_lock_path.read_bytes()
    ):
        raise ValueError("source archive Cargo.lock does not match the original lock")
    changed_workspace_versions = validate_lock_derivation(
        original_lock_path, effective_lock_path
    )

    effective_lock = load_lock(effective_lock_path)
    lock_records = {
        (record["name"], record["version"], record.get("source")): record
        for record in effective_lock["package"]
    }
    if len(lock_records) != len(effective_lock["package"]):
        raise ValueError("Cargo.lock package identities are not unique")

    metadata_by_target: dict[str, dict[str, Any]] = {}
    package_by_target: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    memberships: dict[tuple[str, str, str | None], set[str]] = defaultdict(set)
    matrix_summaries: list[dict[str, Any]] = []
    for platform, target in TARGETS:
        metadata_path = args.metadata_dir / f"metadata-{target}.json"
        metadata = load_json(metadata_path)
        if metadata.get("version") != 1 or not isinstance(metadata.get("packages"), list):
            raise ValueError(f"unexpected Cargo metadata schema: {metadata_path}")
        package_map: dict[tuple[str, str], dict[str, Any]] = {}
        for package in metadata["packages"]:
            key = (package.get("name"), package.get("version"))
            if not all(isinstance(item, str) for item in key) or key in package_map:
                raise ValueError(f"Cargo metadata package identity is invalid: {key}")
            package_map[key] = package
        metadata_by_target[target] = metadata
        package_by_target[target] = package_map

        for root_id, package_name, _binary, prefix in ROOTS:
            path = args.metadata_dir / f"tree-{prefix}{target}.txt"
            keys = tree_keys(path, (package_name, CODEX_VERSION))
            for key in keys:
                package = package_map.get(key)
                if package is None:
                    raise ValueError(
                        f"Cargo tree package is missing from {target} metadata: {key}"
                    )
                source = package.get("source")
                memberships[(key[0], key[1], source)].add(f"{root_id}@{platform}")
            matrix_summaries.append(
                {
                    "root": root_id,
                    "platform": platform,
                    "target": target,
                    "package_count": len(keys),
                }
            )

    git_sources: dict[str, dict[str, Any]] = {}
    packages: list[dict[str, Any]] = []
    for identity in sorted(memberships, key=lambda item: (item[0], item[1], item[2] or "")):
        name, version, source = identity
        metadata_package = next(
            (
                package_by_target[target][(name, version)]
                for _platform, target in TARGETS
                if (name, version) in package_by_target[target]
                and package_by_target[target][(name, version)].get("source") == source
            ),
            None,
        )
        if metadata_package is None:
            raise ValueError(f"metadata package disappeared: {identity}")
        kind = package_source_kind(source)
        lock_record = lock_records.get(identity)
        if lock_record is None:
            raise ValueError(f"reachable package is absent from effective lock: {identity}")
        declared_license = metadata_package.get("license")
        if not isinstance(declared_license, str) or not declared_license.strip():
            raise ValueError(f"reachable package has no declared license: {identity}")

        record: dict[str, Any] = {
            "name": name,
            "version": version,
            "source_kind": kind,
            "source_ref": "codex-source",
            "declared_license": declared_license,
            "license_files": [],
            "memberships": sorted(memberships[identity]),
            "custom_build": any(
                "custom-build" in target_record.get("kind", [])
                for target_record in metadata_package.get("targets", [])
            ),
        }
        if metadata_package.get("links") is not None:
            record["native_links"] = metadata_package["links"]

        if kind == "workspace":
            record["manifest_path"] = normalize_workspace_manifest(
                metadata_package["manifest_path"]
            )
        elif kind == "registry":
            checksum = lock_record.get("checksum")
            if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
                raise ValueError(f"registry package checksum is absent: {identity}")
            archive_path = args.cargo_cache / f"{name}-{version}.crate"
            descriptor = file_descriptor(archive_path)
            if descriptor["sha256"] != checksum:
                raise ValueError(f"registry archive disagrees with Cargo.lock: {identity}")
            record["source_ref"] = "crates.io-index"
            record["archive"] = {
                "url": f"https://static.crates.io/crates/{name}/{name}-{version}.crate",
                **descriptor,
            }
            record["license_files"] = scan_license_members(
                archive_path, strip_root=True
            )
        else:
            assert isinstance(source, str)
            if source not in git_sources:
                descriptor = git_source_descriptor(source, args.git_archive_dir)
                git_sources[descriptor["id"]] = descriptor
            source_id = next(
                source_id
                for source_id, descriptor in git_sources.items()
                if descriptor["cargo_source"] == source
            )
            record["source_ref"] = source_id
        packages.append(record)

    packages.sort(key=lambda item: (item["name"], item["version"], item["source_ref"]))
    package_ids = {
        (item["name"], item["version"], item["source_ref"]): item
        for item in packages
    }
    if len(package_ids) != len(packages):
        raise ValueError("generated package identities are not unique")

    for summary in matrix_summaries:
        membership = f"{summary['root']}@{summary['platform']}"
        identifiers = sorted(
            f"{item['name']}@{item['version']}|{item['source_ref']}"
            for item in packages
            if membership in item["memberships"]
        )
        if len(identifiers) != summary["package_count"]:
            raise ValueError(f"membership count changed for {membership}")
        summary["package_set_sha256"] = canonical_digest(identifiers)

    source_files = [
        source_file_ref(source_root, relative)
        for relative in (
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
        )
    ]

    by_source = Counter(item["source_kind"] for item in packages)
    registry_without_files = sum(
        item["source_kind"] == "registry" and not item["license_files"]
        for item in packages
    )
    summary = {
        "package_count_union": len(packages),
        "package_counts_by_source": dict(sorted(by_source.items())),
        "declared_license_missing_count": sum(
            not item["declared_license"] for item in packages
        ),
        "registry_archive_count": by_source["registry"],
        "registry_archive_bytes": sum(
            item["archive"]["bytes"]
            for item in packages
            if item["source_kind"] == "registry"
        ),
        "registry_license_file_count": sum(
            len(item["license_files"])
            for item in packages
            if item["source_kind"] == "registry"
        ),
        "registry_packages_without_license_file_count": registry_without_files,
        "git_source_archive_count": len(git_sources),
        "native_links_package_count": sum("native_links" in item for item in packages),
        "custom_build_package_count": sum(item["custom_build"] for item in packages),
        "matrix": sorted(
            matrix_summaries, key=lambda item: (item["root"], item["platform"])
        ),
    }

    result: dict[str, Any] = {
        "schema_version": "deeptwin-codex-rust-dependency-inventory-v1",
        "status": "candidate_exact_input_inventory_not_release_qualified",
        "codex": {
            "version": CODEX_VERSION,
            "tag": CODEX_TAG,
            "source_commit": CODEX_COMMIT,
        },
        "source": {
            "id": "codex-source",
            "archive": SOURCE_ARCHIVE,
            "original_cargo_lock": {
                "path": "codex-rs/Cargo.lock",
                **ORIGINAL_LOCK,
            },
            "effective_release_cargo_lock": {
                "path": "codex-rs/Cargo.lock",
                **EFFECTIVE_LOCK,
                "derivation": "149 workspace-only version rewrites from 0.0.0 to 0.153.4; no package source, checksum, dependency or name changed",
                "workspace_version_rewrite_count": changed_workspace_versions,
            },
            "source_files": source_files,
        },
        "resolver": {
            "cargo_version": "1.95.0",
            "rustc_version": "1.95.0",
            "edges": ["normal", "build"],
            "excluded_edges": ["dev"],
            "network": "offline",
            "metadata_command": "cargo metadata --locked --offline --format-version 1 --filter-platform <target> --manifest-path codex-rs/cli/Cargo.toml",
            "tree_command": "cargo tree --locked --offline --target <target> --manifest-path codex-rs/<root>/Cargo.toml -p <package> -e normal,build --prefix none --format {p}",
        },
        "targets": [
            {"platform": platform, "target": target} for platform, target in TARGETS
        ],
        "roots": [
            {"id": root_id, "package": package, "package_member": binary}
            for root_id, package, binary, _prefix in ROOTS
        ],
        "git_sources": sorted(git_sources.values(), key=lambda item: item["id"]),
        "external_build_inputs": [build_rusty_v8_inputs(args.rusty_v8_dir)],
        "packages": packages,
        "summary": summary,
        "qualification_limits": list(QUALIFICATION_LIMITS),
        "release_gate": "not_satisfied",
    }
    digest_input = dict(result)
    result["inventory_digest"] = canonical_digest(digest_input)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--original-lock", type=Path, required=True)
    parser.add_argument("--cargo-cache", type=Path, required=True)
    parser.add_argument("--git-archive-dir", type=Path, required=True)
    parser.add_argument("--rusty-v8-dir", type=Path, required=True)
    parser.add_argument("--metadata-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_inventory(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {args.output}: {len(result['packages'])} packages, "
        f"digest {result['inventory_digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
