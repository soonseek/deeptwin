#!/usr/bin/env python3
"""Offline verifier for the pinned age 1.3.2 release and runtime subset.

This verifier deliberately does not download anything. Release CI must supply the
two upstream archives and source archive out of band, after which this program
binds archive bytes, copied members, embedded Go build information, the staged
runtime inventory, and the repository's license bundle into one check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import tarfile
from typing import Any


BUILDINFO_MAGIC = b"\xff Go buildinf:"
PLATFORM_ARCH = {"linux/amd64": "amd64", "linux/arm64": "arm64"}
ELF_MACHINE = {"amd64": 62, "arm64": 183}
EXPECTED_COPIED = {"age/age", "age/age-keygen", "age/LICENSE"}
EXPECTED_FORBIDDEN = {
    "age/age-inspect",
    "age/age-plugin-batchpass",
    "age/age-plugin-pq",
    "age/age-plugin-tag",
    "age/age-plugin-tagpq",
}
EXPECTED_RUNTIME_PROFILE = {
    "guarantee": "reachability_denial_not_physical_feature_removal",
    "network": "none",
    "shell": False,
    "caller_argv": False,
    "allowed_recipient": "native_x25519_age1_only",
    "allowed_identity": "native_x25519_AGE-SECRET-KEY-1_only",
    "secret_transport": "owned_descriptor",
    "negative_tests_completed": True,
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON root must be an object")
    return value


def require_file(path: Path, *, size: int, digest: str, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label}: regular file required")
    observed_size = path.stat().st_size
    if observed_size != size:
        raise ValueError(f"{label}: byte count changed ({observed_size} != {size})")
    observed_digest = sha256_file(path)
    if observed_digest != digest:
        raise ValueError(f"{label}: SHA-256 changed ({observed_digest})")


def read_uvarint(blob: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(10):
        if offset >= len(blob):
            raise ValueError("Go build info: truncated varint")
        byte = blob[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise ValueError("Go build info: oversized varint")


def parse_go_buildinfo(blob: bytes) -> dict[str, Any]:
    offset = blob.find(BUILDINFO_MAGIC)
    if offset < 0 or offset + 32 > len(blob):
        raise ValueError("Go build info: header absent or truncated")
    pointer_size = blob[offset + 14]
    flags = blob[offset + 15]
    if pointer_size not in {4, 8} or flags & 2 == 0:
        raise ValueError("Go build info: unsupported non-inline encoding")

    cursor = offset + 32
    go_length, cursor = read_uvarint(blob, cursor)
    go_version = blob[cursor : cursor + go_length].decode("utf-8")
    cursor += go_length
    module_length, cursor = read_uvarint(blob, cursor)
    framed = blob[cursor : cursor + module_length]
    if len(framed) != module_length or module_length < 32:
        raise ValueError("Go build info: module payload truncated")
    module_text = framed[16:-16].decode("utf-8")

    program_path: str | None = None
    main_module: tuple[str, str, str] | None = None
    dependencies: list[tuple[str, str, str]] = []
    build: dict[str, str] = {}
    for line in module_text.splitlines():
        fields = line.split("\t")
        if fields[0] == "path" and len(fields) == 2:
            program_path = fields[1]
        elif fields[0] == "mod" and len(fields) == 4:
            main_module = (fields[1], fields[2], fields[3])
        elif fields[0] == "dep" and len(fields) == 4:
            dependencies.append((fields[1], fields[2], fields[3]))
        elif fields[0] == "build" and len(fields) == 2 and "=" in fields[1]:
            key, value = fields[1].split("=", 1)
            if key in build:
                raise ValueError(f"Go build info: duplicate build field {key}")
            build[key] = value
        elif fields[0] == "=>":
            raise ValueError("Go build info: module replacement is not permitted")
        elif fields[0] not in {"build"}:
            raise ValueError(f"Go build info: unsupported line {line!r}")
    if program_path is None or main_module is None:
        raise ValueError("Go build info: missing program or main module")
    return {
        "go_version": go_version,
        "path": program_path,
        "main": main_module,
        "dependencies": dependencies,
        "build": build,
    }


def verify_elf(blob: bytes, architecture: str, label: str) -> None:
    if len(blob) < 20 or blob[:4] != b"\x7fELF":
        raise ValueError(f"{label}: ELF header missing")
    if blob[4] != 2 or blob[5] != 1:
        raise ValueError(f"{label}: expected 64-bit little-endian ELF")
    machine = int.from_bytes(blob[18:20], "little")
    if machine != ELF_MACHINE[architecture]:
        raise ValueError(f"{label}: wrong ELF machine {machine}")


def expected_modules(
    licenses: dict[str, Any], executable: str
) -> tuple[tuple[str, str, str], set[tuple[str, str, str]]]:
    components = licenses.get("components", [])
    by_module = {item["module"]: item for item in components}
    if len(by_module) != len(components) or "filippo.io/age" not in by_module:
        raise ValueError("license bundle: unique main and dependency modules required")
    module_sets = licenses.get("executable_module_sets", {})
    if set(module_sets) != {"age", "age-keygen"} or executable not in module_sets:
        raise ValueError("license bundle: exact executable module sets required")
    main = by_module["filippo.io/age"]
    wanted_names = set(module_sets[executable])
    dependencies = {
        (item["module"], item["version"], item["module_sum"])
        for item in components
        if item["module"] in wanted_names
    }
    if {item[0] for item in dependencies} != wanted_names:
        raise ValueError(f"{executable}: executable module set has unknown entries")
    return (main["module"], main["version"], ""), dependencies


def verify_binary_buildinfo(
    blob: bytes,
    *,
    executable: str,
    architecture: str,
    source_commit: str,
    licenses: dict[str, Any],
) -> dict[str, Any]:
    verify_elf(blob, architecture, executable)
    info = parse_go_buildinfo(blob)
    wanted_main, wanted_dependencies = expected_modules(licenses, executable)
    if info["go_version"] != licenses["go_version"]:
        raise ValueError(f"{executable}: Go version changed")
    if info["path"] != f"filippo.io/age/cmd/{executable}":
        raise ValueError(f"{executable}: unexpected Go program path")
    if info["main"] != wanted_main:
        raise ValueError(f"{executable}: main module changed")
    if set(info["dependencies"]) != wanted_dependencies or len(info["dependencies"]) != len(wanted_dependencies):
        raise ValueError(f"{executable}: embedded Go dependency closure changed")
    required_build = {
        "-buildmode": "exe",
        "-compiler": "gc",
        "-trimpath": "true",
        "CGO_ENABLED": "0",
        "GOOS": "linux",
        "GOARCH": architecture,
        "vcs": "git",
        "vcs.revision": source_commit,
        "vcs.modified": "false",
    }
    for key, value in required_build.items():
        if info["build"].get(key) != value:
            raise ValueError(f"{executable}: Go build field {key} changed")
    return {
        "sha256": sha256_bytes(blob),
        "go_version": info["go_version"],
        "goarch": architecture,
        "cgo_enabled": False,
        "dependency_count": len(info["dependencies"]),
    }


def verify_tar_safety(archive: tarfile.TarFile, label: str) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or member.name in members:
            raise ValueError(f"{label}: unsafe or duplicate member {member.name!r}")
        if not (member.isdir() or member.isfile()):
            raise ValueError(f"{label}: links and special members are forbidden")
        members[member.name] = member
    return members


def member_bytes(archive: tarfile.TarFile, member: tarfile.TarInfo, label: str) -> bytes:
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"{label}: member has no bytes")
    value = stream.read()
    if len(value) != member.size:
        raise ValueError(f"{label}: truncated member")
    return value


def verify_platform_archive(
    manifest: dict[str, Any],
    licenses: dict[str, Any],
    declaration: dict[str, Any],
    archive_path: Path,
    proof_path: Path,
) -> dict[str, Any]:
    platform = declaration["platform"]
    architecture = PLATFORM_ARCH[platform]
    require_file(
        archive_path,
        size=declaration["bytes"],
        digest=declaration["sha256"],
        label=f"{platform} archive",
    )
    proof = declaration["sigsum_proof"]
    require_file(
        proof_path,
        size=proof["bytes"],
        digest=proof["sha256"],
        label=f"{platform} Sigsum proof",
    )
    if proof.get("verified") is not True or proof.get("exit_code") != 0:
        raise ValueError(f"{platform}: successful prior Sigsum verification required")
    copied = {item["path"]: item for item in declaration["copied_members"]}
    forbidden = set(manifest["forbidden_archive_members_in_final_image"])
    if set(copied) != EXPECTED_COPIED or forbidden != EXPECTED_FORBIDDEN:
        raise ValueError(f"{platform}: runtime copy/deny inventory policy changed")
    exact_members = {"age"} | set(copied) | forbidden
    with tarfile.open(archive_path, "r:gz") as archive:
        members = verify_tar_safety(archive, f"{platform} archive")
        if set(members) != exact_members:
            raise ValueError(f"{platform} archive: member inventory changed")
        binary_results: dict[str, Any] = {}
        for path, expected in copied.items():
            member = members[path]
            if not member.isfile() or member.size != expected["bytes"]:
                raise ValueError(f"{platform} archive:{path}: size or type changed")
            if stat.S_IMODE(member.mode) != int(expected["mode"], 8):
                raise ValueError(f"{platform} archive:{path}: mode changed")
            blob = member_bytes(archive, member, f"{platform} archive:{path}")
            if sha256_bytes(blob) != expected["sha256"]:
                raise ValueError(f"{platform} archive:{path}: digest changed")
            name = PurePosixPath(path).name
            if name in {"age", "age-keygen"}:
                binary_results[name] = verify_binary_buildinfo(
                    blob,
                    executable=name,
                    architecture=architecture,
                    source_commit=manifest["source_commit"],
                    licenses=licenses,
                )
        release_license = licenses["release_archive_license"]
        if copied[release_license["member"]]["sha256"] != release_license["sha256"]:
            raise ValueError(f"{platform}: release license declarations disagree")
    return {
        "platform": platform,
        "archive_sha256": declaration["sha256"],
        "sigsum_proof_sha256": proof["sha256"],
        "archive_member_count": len(exact_members) - 1,
        "copied_member_count": len(copied),
        "forbidden_member_count": len(forbidden),
        "binaries": binary_results,
    }


def verify_license_bundle(
    repository_root: Path,
    manifest: dict[str, Any],
    licenses: dict[str, Any],
    source_archive: Path,
    go_source_archive: Path,
) -> dict[str, Any]:
    source = manifest["source"]
    require_file(source_archive, size=source["bytes"], digest=source["sha256"], label="source archive")
    if licenses["source_archive_sha256"] != source["sha256"]:
        raise ValueError("license bundle: source archive binding changed")

    declared_files = {item["path"]: item for item in licenses["license_files"]}
    if len(declared_files) != len(licenses["license_files"]):
        raise ValueError("license bundle: duplicate file declaration")
    for path, expected in declared_files.items():
        require_file(
            repository_root / path,
            size=expected["bytes"],
            digest=expected["sha256"],
            label=f"license bundle:{path}",
        )

    go_source = licenses["go_source"]
    require_file(
        go_source_archive,
        size=go_source["bytes"],
        digest=go_source["sha256"],
        label="Go source archive",
    )
    with tarfile.open(go_source_archive, "r:gz") as archive:
        members = verify_tar_safety(archive, "Go source archive")
        member = members.get(go_source["license_member"])
        if member is None or not member.isfile():
            raise ValueError("Go source archive: exact license member absent")
        go_license = member_bytes(archive, member, "Go source license")
        if len(go_license) != go_source["license_bytes"] or sha256_bytes(go_license) != go_source["license_sha256"]:
            raise ValueError("Go source archive: license bytes changed")
        go_component = next(
            item for item in licenses["components"] if item["module"] == "go-runtime-and-standard-library"
        )
        if go_license != (repository_root / go_component["license_file"]).read_bytes():
            raise ValueError("Go runtime license bundle differs from exact Go source")

    with tarfile.open(source_archive, "r:gz") as archive:
        members = verify_tar_safety(archive, "source archive")
        for component in licenses["components"]:
            source_member = component["source_license_member"]
            license_path = component["license_file"]
            if license_path not in declared_files:
                raise ValueError(f"license bundle:{component['module']}: undeclared license file")
            if source_member is None:
                if component["module"] != "go-runtime-and-standard-library":
                    raise ValueError(f"license bundle:{component['module']}: source member required")
                continue
            member = members.get(source_member)
            if member is None or not member.isfile():
                raise ValueError(f"license bundle:{component['module']}: source license absent")
            source_bytes = member_bytes(archive, member, source_member)
            bundled_bytes = (repository_root / license_path).read_bytes()
            if source_bytes != bundled_bytes:
                raise ValueError(f"license bundle:{component['module']}: license bytes differ from source")

    components = licenses["components"]
    if len({item["module"] for item in components}) != len(components):
        raise ValueError("license bundle: duplicate component declaration")
    manifest_modules = {
        (item["name"], item["version"], item["license_sha256"])
        for item in manifest["embedded_modules"]
    }
    bundle_modules = {
        (
            item["module"],
            item["version"],
            declared_files[item["license_file"]]["sha256"],
        )
        for item in components
        if item["module"] != "go-runtime-and-standard-library"
    }
    if manifest_modules != bundle_modules:
        raise ValueError("license bundle: age manifest and component closure disagree")
    return {
        "component_count": len(licenses["components"]),
        "unique_license_file_count": len(declared_files),
        "source_archive_sha256": source["sha256"],
        "go_source_archive_sha256": go_source["sha256"],
    }


def verify_runtime_root(
    declaration: dict[str, Any], runtime_root: Path
) -> dict[str, Any]:
    expected = {PurePosixPath(item["path"]).name: item for item in declaration["copied_members"]}
    if not runtime_root.is_dir() or runtime_root.is_symlink():
        raise ValueError(f"{declaration['platform']} runtime root: directory required")
    observed = {path.name for path in runtime_root.iterdir()}
    if observed != set(expected):
        raise ValueError(
            f"{declaration['platform']} runtime root: exact inventory changed; "
            f"expected={sorted(expected)}, observed={sorted(observed)}"
        )
    for name, item in expected.items():
        path = runtime_root / name
        require_file(path, size=item["bytes"], digest=item["sha256"], label=f"runtime:{name}")
        if stat.S_IMODE(path.stat().st_mode) != int(item["mode"], 8):
            raise ValueError(f"runtime:{name}: mode changed")
    return {"platform": declaration["platform"], "inventory": sorted(observed)}


def verify(
    *,
    repository_root: Path,
    manifest_path: Path,
    license_manifest_path: Path,
    source_archive: Path,
    go_source_archive: Path,
    archives: dict[str, Path],
    proofs: dict[str, Path],
    runtime_roots: dict[str, Path] | None = None,
) -> dict[str, Any]:
    manifest = load_object(manifest_path)
    licenses = load_object(license_manifest_path)
    if manifest.get("tool") != "age" or manifest.get("version") != "1.3.2":
        raise ValueError("age manifest: exact age 1.3.2 declaration required")
    if licenses.get("tool") != "age" or licenses.get("version") != manifest["version"]:
        raise ValueError("license bundle: tool/version mismatch")
    if set(archives) != set(PLATFORM_ARCH):
        raise ValueError("archives: exact linux/amd64 and linux/arm64 inputs required")
    if set(proofs) != set(PLATFORM_ARCH):
        raise ValueError("proofs: exact linux/amd64 and linux/arm64 inputs required")
    declarations = {item["platform"]: item for item in manifest["platform_archives"]}
    if set(declarations) != set(PLATFORM_ARCH):
        raise ValueError("age manifest: exact dual-platform declarations required")
    if manifest.get("runtime_profile") != EXPECTED_RUNTIME_PROFILE:
        raise ValueError("age manifest: restricted runtime profile changed")
    if manifest.get("sigsum_policy", {}).get("offline_verification_completed") is not True:
        raise ValueError("age manifest: completed prior Sigsum verification required")

    license_result = verify_license_bundle(
        repository_root,
        manifest,
        licenses,
        source_archive,
        go_source_archive,
    )
    platform_results = [
        verify_platform_archive(
            manifest,
            licenses,
            declarations[platform],
            archives[platform],
            proofs[platform],
        )
        for platform in sorted(PLATFORM_ARCH)
    ]
    runtime_results: list[dict[str, Any]] = []
    if runtime_roots is not None:
        if set(runtime_roots) != set(PLATFORM_ARCH):
            raise ValueError("runtime roots: exact dual-platform roots required")
        runtime_results = [
            verify_runtime_root(declarations[platform], runtime_roots[platform])
            for platform in sorted(PLATFORM_ARCH)
        ]
    return {
        "schema_version": "deeptwin-age-offline-verification-v1",
        "status": "pass",
        "tool": "age",
        "version": manifest["version"],
        "license_bundle": license_result,
        "platforms": platform_results,
        "runtime_roots": runtime_results,
        "assurance_boundary": (
            "Offline byte, archive, ELF, embedded Go-module/build-field, staged-inventory, "
            "and license-source equivalence checks. Native behavior is a separate canary."
        ),
    }


def parse_mapping(values: list[str], label: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        platform, separator, path = value.partition("=")
        if not separator or platform not in PLATFORM_ARCH or platform in result or not path:
            raise ValueError(f"{label}: expected unique PLATFORM=PATH for both supported platforms")
        result[platform] = Path(path).resolve()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--license-manifest", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--go-source-archive", type=Path, required=True)
    parser.add_argument("--archive", action="append", default=[], metavar="PLATFORM=PATH")
    parser.add_argument("--proof", action="append", default=[], metavar="PLATFORM=PATH")
    parser.add_argument("--runtime-root", action="append", default=[], metavar="PLATFORM=PATH")
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    try:
        result = verify(
            repository_root=args.repository_root.resolve(),
            manifest_path=args.manifest.resolve(),
            license_manifest_path=args.license_manifest.resolve(),
            source_archive=args.source_archive.resolve(),
            go_source_archive=args.go_source_archive.resolve(),
            archives=parse_mapping(args.archive, "archive"),
            proofs=parse_mapping(args.proof, "proof"),
            runtime_roots=parse_mapping(args.runtime_root, "runtime root") if args.runtime_root else None,
        )
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as error:
        parser.exit(1, f"FAIL: {error}\n")
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_output is not None:
        args.json_output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
