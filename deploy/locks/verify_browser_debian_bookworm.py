#!/usr/bin/env python3
"""Fail-closed structural and byte verifier for the pinned Debian browser closure.

This verifier does not qualify native Chromium behavior. A successful result means only
that the manifest, evidence sidecar, pinned metadata, and optional .deb inputs are
content-consistent. Dual-architecture ldd/sandbox/render tests remain separate gates.
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, re, shutil, subprocess, sys

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SNAPSHOT_RE = re.compile(r"^https://snapshot\.debian\.org/archive/(debian|debian-security)/([0-9]{8}T[0-9]{6}Z)(?:/|$)")

def fail(message: str) -> None:
    raise ValueError(message)

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

def check_descriptor(item: dict, label: str) -> None:
    if not isinstance(item.get("bytes"), int) or item["bytes"] <= 0:
        fail(f"{label}: invalid byte count")
    if not SHA256_RE.fullmatch(item.get("sha256", "")):
        fail(f"{label}: invalid SHA-256")

def check_file(path: pathlib.Path, desc: dict, label: str) -> None:
    data = path.read_bytes()
    if len(data) != desc["bytes"] or digest(data) != desc["sha256"]:
        fail(f"{label}: byte/hash mismatch at {path}")

def parse_release_sha256(text: str) -> dict[str, tuple[str, int]]:
    output: dict[str, tuple[str, int]] = {}
    active = False
    for line in text.splitlines():
        if line == "SHA256:":
            active = True
            continue
        if active and line and not line.startswith(" "):
            break
        if active:
            fields = line.split()
            if len(fields) == 3:
                output[fields[2]] = (fields[0], int(fields[1]))
    return output

def verify_metadata(manifest: dict, root: pathlib.Path, keyring: pathlib.Path) -> None:
    gpgv = shutil.which("gpgv")
    if not gpgv:
        fail("gpgv is required for metadata verification")
    if not keyring.is_file():
        fail("pinned Debian archive keyring is missing")
    for suite, repo in manifest["snapshot"]["repositories"].items():
        local = {
            "inrelease": root / f"{suite}.InRelease",
            "release": root / f"{suite}.Release",
            "release_gpg": root / f"{suite}.Release.gpg",
            "sources": root / f"{suite}-Sources.xz",
        }
        check_file(local["inrelease"], repo["inrelease"], f"{suite} InRelease")
        check_file(local["release"], repo["release"], f"{suite} Release")
        check_file(local["release_gpg"], repo["release_gpg"], f"{suite} Release.gpg")
        subprocess.run([gpgv, "--keyring", str(keyring), str(local["inrelease"])], check=True)
        subprocess.run([gpgv, "--keyring", str(keyring), str(local["release_gpg"]), str(local["release"])], check=True)
        checksums = parse_release_sha256(local["release"].read_text(encoding="utf-8"))
        expected = repo["sources_index"]
        path = "main/source/Sources.xz"
        if checksums.get(path) != (expected["sha256"], expected["bytes"]):
            fail(f"{suite}: Release does not authenticate {path}")
        check_file(local["sources"], expected, f"{suite} Sources.xz")
        for arch, expected in repo["binary_indexes"].items():
            path = f"main/binary-{arch}/Packages.xz"
            if checksums.get(path) != (expected["sha256"], expected["bytes"]):
                fail(f"{suite}: Release does not authenticate {path}")
            check_file(root / f"{suite}-{arch}-Packages.xz", expected, f"{suite} {arch} Packages.xz")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=pathlib.Path)
    parser.add_argument("--source-evidence", type=pathlib.Path)
    parser.add_argument("--audit-input", type=pathlib.Path)
    parser.add_argument("--artifacts-root", type=pathlib.Path, help="contains amd64/ and arm64/ .deb files")
    parser.add_argument("--metadata-root", type=pathlib.Path)
    parser.add_argument("--debian-keyring", type=pathlib.Path)
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    if (b"/private" + b"/tmp") in raw:
        fail("publishable manifest contains an ephemeral path")
    manifest = json.loads(raw)
    if manifest.get("schema_version") != "deeptwin-browser-debian-bookworm-lock-v1":
        fail("unsupported manifest schema")
    if manifest.get("status") != "candidate_blocked_not_release_qualified":
        fail("manifest must stay blocked until native/signature gates close")
    snapshot_id = manifest["snapshot"]["id"]
    if snapshot_id != "20260907T000000Z":
        fail("unexpected snapshot id")
    if manifest["snapshot"].get("openpgp_status") != "verified_both_platforms":
        fail("snapshot OpenPGP verification is not recorded for both platforms")
    openpgp = manifest["snapshot"].get("openpgp_verification", {})
    required_true = (
        "all_inrelease_signatures_verified",
        "all_detached_release_signatures_verified",
        "release_to_packages_and_sources_sha256_linkage_verified",
        "exact_delta_artifact_sets_verified",
    )
    if openpgp.get("network_during_verification") is not False or any(
        openpgp.get(key) is not True for key in required_true
    ):
        fail("incomplete or network-dependent OpenPGP verification record")
    keyring = openpgp.get("debian_archive_keyring", {})
    if (
        keyring.get("package") != "debian-archive-keyring"
        or keyring.get("version") != "2023.3+deb12u2"
        or keyring.get("bytes") != 55918
        or keyring.get("sha256")
        != "506b815cbb32d9b6066b4a2aa524071e071761e7e7f68c3ac74f3061ba852017"
    ):
        fail("unexpected Debian archive keyring evidence")
    expected_gpgv = {
        "amd64": "e82416f3ae002b63c0731f311519c55fc9e7d3c8bdadbd64239833298f09a2cf",
        "arm64": "26999f2766739b3df31c6c355856440bbd7377a5a19ebcf3f6cfe4cfb3c42f69",
    }
    if set(openpgp.get("platforms", {})) != set(expected_gpgv):
        fail("OpenPGP verifier platform set mismatch")
    for arch, expected_digest in expected_gpgv.items():
        result = openpgp["platforms"][arch]
        if (
            result.get("gpgv_package_version") != "2.2.40-1.1+deb12u2"
            or result.get("gpgv_binary_sha256") != expected_digest
            or result.get("exit_code") != 0
        ):
            fail(f"{arch}: unexpected gpgv verification evidence")
    for suite, repo in manifest["snapshot"]["repositories"].items():
        match = SNAPSHOT_RE.match(repo["base_url"])
        if not match or match.group(2) != snapshot_id:
            fail(f"{suite}: non-pinned or non-Debian snapshot URL")
        for key in ("inrelease", "release", "release_gpg", "sources_index"):
            check_descriptor(repo[key], f"{suite} {key}")
            if not repo[key]["url"].startswith(repo["base_url"] + "/"):
                fail(f"{suite} {key}: URL escapes the pinned snapshot")
        for arch, desc in repo["binary_indexes"].items():
            check_descriptor(desc, f"{suite} {arch} index")
            if arch not in ("amd64", "arm64") or not desc["url"].startswith(repo["base_url"] + "/"):
                fail(f"{suite}: invalid binary index")
    roots = manifest["roots"]
    if len(roots["playwright_debian12_chromium"]) != 21 or len(roots["rendering_fonts"]) != 10:
        fail("unexpected Playwright/font root count")
    if roots["excluded"] != ["xvfb"] or "xvfb" in roots["playwright_debian12_chromium"] + roots["rendering_fonts"]:
        fail("xvfb must remain excluded for headless-shell")
    if roots["elf_base_assertions"] != ["libudev1"]:
        fail("ELF-proven libudev1 base assertion missing")
    closure = manifest["closure"]
    packages = closure["packages"]
    if len(packages) != closure["package_count"] or closure["package_count"] != 105:
        fail("unexpected closure package count")
    if digest(canonical(packages)) != closure["packages_sha256"]:
        fail("closure package digest mismatch")
    versions = {p["name"]: p["version"] for p in packages}
    if len(versions) != len(packages):
        fail("duplicate closure package")
    source_keys = {p["source"] for p in packages}
    entrypoints = set(roots["playwright_debian12_chromium"] + roots["rendering_fonts"] + roots["elf_base_assertions"])
    if not entrypoints <= versions.keys():
        fail("root missing from closure")
    for arch, platform in manifest["platforms"].items():
        if arch not in ("amd64", "arm64"):
            fail("unexpected platform")
        graph = platform["dependency_graph"]
        edges = graph["edges"]
        if len(edges) != graph["edge_count"] or digest(canonical(edges)) != graph["edges_sha256"]:
            fail(f"{arch}: dependency graph digest/count mismatch")
        adjacency = {name: set() for name in versions}
        for parent, dependency, constraint in edges:
            if parent not in versions or dependency not in versions or not constraint:
                fail(f"{arch}: malformed dependency edge")
            adjacency[parent].add(dependency)
        reachable = set(entrypoints)
        queue = list(entrypoints)
        while queue:
            for dependency in adjacency[queue.pop()]:
                if dependency not in reachable:
                    reachable.add(dependency); queue.append(dependency)
        if reachable != set(versions):
            fail(f"{arch}: closure has unreachable/missing nodes: {sorted(set(versions) ^ reachable)}")
        base = platform["base_dpkg_inventory"]
        if base["installed_count"] != 88 or not SHA256_RE.fullmatch(base["status_sha256"]):
            fail(f"{arch}: base dpkg inventory evidence invalid")
        base_names = {p["name"] for p in base["closure_packages_satisfied"]}
        delta = platform["install_delta"]
        delta_names = {p["name"] for p in delta["packages"]}
        if len(base_names) != 32 or len(delta_names) != delta["package_count"] or delta["package_count"] != 73:
            fail(f"{arch}: base/delta count mismatch")
        if base_names & delta_names or base_names | delta_names != set(versions):
            fail(f"{arch}: base and delta do not partition closure")
        if sum(p["bytes"] for p in delta["packages"]) != delta["total_bytes"]:
            fail(f"{arch}: delta byte total mismatch")
        expected_debs = {pathlib.PurePosixPath(p["filename"]).name for p in delta["packages"]}
        if args.artifacts_root:
            actual_debs = {p.name for p in (args.artifacts_root / arch).glob("*.deb")}
            if actual_debs != expected_debs:
                fail(f"{arch}: artifact directory has missing or extra .debs: {sorted(actual_debs ^ expected_debs)}")
        for p in delta["packages"]:
            check_descriptor(p, f"{arch} {p['name']}")
            if versions.get(p["name"]) != p["version"]:
                fail(f"{arch} {p['name']}: version mismatch")
            if pathlib.PurePosixPath(p["url"]).name != pathlib.PurePosixPath(p["filename"]).name:
                fail(f"{arch} {p['name']}: URL/filename mismatch")
            match = SNAPSHOT_RE.match(p["url"])
            if not match or match.group(2) != snapshot_id:
                fail(f"{arch} {p['name']}: URL escapes snapshot")
            if args.artifacts_root:
                check_file(args.artifacts_root / arch / pathlib.PurePosixPath(p["filename"]).name, p, f"{arch} {p['name']}")
    side_desc = manifest["source_license_evidence"]
    evidence_path = args.source_evidence or args.manifest.parent / pathlib.PurePosixPath(side_desc["path"]).name
    check_file(evidence_path, side_desc, "source/license evidence")
    evidence_raw = evidence_path.read_bytes()
    if (b"/private" + b"/tmp") in evidence_raw:
        fail("publishable source evidence contains an ephemeral path")
    evidence = json.loads(evidence_raw)
    if evidence["snapshot_id"] != snapshot_id or evidence["binary_count"] != 105 or evidence["source_package_count"] != 85:
        fail("source/license evidence summary mismatch")
    binary_names = {b["name"] for b in evidence["binaries"]}
    if binary_names != set(versions):
        fail("source/license evidence does not cover closure")
    evidence_sources = {f"{s['name']}={s['version']}" for s in evidence["sources"]}
    if evidence_sources != source_keys:
        fail("source package evidence does not cover closure")
    for source in evidence["sources"]:
        if not source["found_in_index"] or not source["files"]:
            fail(f"source evidence incomplete: {source['name']}")
        for f in source["files"]:
            check_descriptor(f, f"source {source['name']} {f['filename']}")
            match = SNAPSHOT_RE.match(f["url"])
            if not match or match.group(2) != snapshot_id:
                fail(f"source {source['name']}: URL escapes snapshot")
    for binary in evidence["binaries"]:
        ce = binary["copyright_evidence"]
        if ce["kind"] == "file":
            check_descriptor(ce, f"copyright {binary['name']}")
        elif not (binary["name"] == "libgcc-s1" and ce["kind"] == "directory_symlink" and ce["resolved_in_package"] == "gcc-12-base"):
            fail(f"unresolved copyright evidence: {binary['name']}")
    audit = manifest["research_input"]
    if audit["embedded"] is not False or audit["sha256"] != "c1757a2b08e699b3be4e37134f4dec37985953b79d68f7f242188354af7090b8":
        fail("unexpected research input descriptor")
    if args.audit_input:
        check_file(args.audit_input, audit, "research input")
    if bool(args.metadata_root) != bool(args.debian_keyring):
        fail("--metadata-root and --debian-keyring must be supplied together")
    if args.metadata_root:
        verify_metadata(manifest, args.metadata_root, args.debian_keyring)
    print("browser Debian closure: structural/selected byte checks passed; native release gates remain")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
