#!/usr/bin/env python3
"""Strict offline verifier for DeepTwin's T089 aggregate build-input lock.

This verifier deliberately distinguishes a locked set of build inputs from a releasable
DeepTwin distribution.  Final service images, deployment receipts and clean-host evidence
belong to T081-T084 and are forbidden here.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import stat
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

MAX_BODY_BYTES = 1_048_576
MAX_DEPTH = 32
MAX_ITEMS = 10_000
MAX_STRING_BYTES = 65_536
MAX_INTEGER = (1 << 63) - 1
CODEX_RUST_CHILD_MAX_TOTAL_ITEMS = 50_000
CODEX_PROVENANCE_RECEIPT_MAX_TOTAL_ITEMS = 5_000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
UTC_SECOND = re.compile(r"^20[0-9]{2}-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z$")
PLATFORMS = ["linux/amd64", "linux/arm64"]
CODEX_PROVENANCE_RECEIPT_PATH = (
    "specs/001-autonomous-release/evidence/"
    "codex-0.153.4-provenance-receipt.json"
)
CODEX_PROVENANCE_RECEIPT_SCHEMA = "deeptwin-codex-provenance-receipt-v3"
EXPECTED_CODEX_VERIFIED_INPUT_FILE_COUNT = 17
CODEX_PROVENANCE_RECEIPT_LIMITS = (
    (
        "The selected manifest-pinned Cosign executable was hash-verified before "
        "checking all six Linux executable bundles; the receipt records whether "
        "that verifier was a native Linux release-build artifact or the locked "
        "Darwin audit artifact."
    ),
    (
        "The receipt records an exact artifact-backed verifier replay result and "
        "content bindings. Because the checked-in JSON is not an authenticated "
        "attestation, it does not prove which process or person created it. Hermetic "
        "release-CI repetition remains downstream T082 work."
    ),
    (
        "The receipt does not prove source-to-binary reproducibility, runtime "
        "isolation, legal approval, or release qualification."
    ),
)
CODEX_PROVENANCE_RECORDED_LIMITS = (
    *CODEX_PROVENANCE_RECEIPT_LIMITS,
    (
        "This checked-in record transcribes prior audit observations, but no complete "
        "artifact directory plus locked Linux verifier report is retained with it. It "
        "is not an artifact-backed PASS and cannot satisfy the T089 provenance gate."
    ),
)
EXPECTED_BUILD_GATES = [
    "aggregate-integrity",
    "architecture-coverage",
    "artifact-source-size-digest",
    "license-provenance-inputs",
    "offline-runtime-mutation-denial",
    "provenance-receipt-capture",
    "tool-distribution-closure",
]
EXPECTED_BUILD_GATE_SUMMARIES = {
    "aggregate-integrity": "All aggregate references and the set digest are exact.",
    "architecture-coverage": "Every build input covers Linux amd64 and arm64.",
    "artifact-source-size-digest": "Artifact sources, sizes, and digests are exact.",
    "license-provenance-inputs": "Recorded license and provenance inputs are exact.",
    "offline-runtime-mutation-denial": "Runtime download and install paths are disabled.",
    "provenance-receipt-capture": (
        "An exact artifact-backed Codex verifier replay receipt is content-bound."
    ),
    "tool-distribution-closure": "Managed tool distribution inputs are exact.",
}
EXPECTED_DOWNSTREAM_TASKS = [
    "T018",
    "T025",
    "T079",
    "T081",
    "T082",
    "T083",
    "T084",
    "T088",
]
CANDIDATE_BUILD_GATE_STATUSES = {
    "aggregate-integrity": "pass",
    "architecture-coverage": "pass",
    "artifact-source-size-digest": "pass",
    "license-provenance-inputs": "pass",
    "offline-runtime-mutation-denial": "pass",
    "provenance-receipt-capture": "open",
    "tool-distribution-closure": "pass",
}
EXPECTED_GLIBC_FLOORS = {
    "browser_debian_runtime": "2.36",
    "codex_runner_bookworm": "2.36",
    "python_wheel_floor": "2.28",
}
EXPECTED_RUNTIME_ABIS = [
    {"abi": "cp312", "runtime": "CPython", "version": "3.12.14"},
    {
        "abi": "musl-static-artifacts+glibc-shell",
        "runtime": "Codex managed runner",
        "version": "glibc-2.36",
    },
    {"abi": "no-native-addons", "runtime": "Node.js", "version": "24.20.0"},
]

EXPECTED_MANIFESTS: dict[str, tuple[str, str, str]] = {
    "age_runtime_licenses": (
        "deploy/manifests/age-1.3.2-runtime-licenses.json",
        "deeptwin-static-go-license-bundle-v1",
        "age embedded-module and Go license inputs",
    ),
    "age_tool": (
        "deploy/manifests/age-1.3.2.json",
        "deeptwin-tool-build-input-v1",
        "age Linux binary and Sigsum inputs",
    ),
    "browser_debian_runtime": (
        "deploy/manifests/browser-debian-bookworm.json",
        "deeptwin-browser-debian-bookworm-lock-v1",
        "Chromium Debian runtime closure",
    ),
    "browser_debian_sources": (
        "deploy/manifests/browser-debian-bookworm.sources.json",
        "deeptwin-debian-source-license-evidence-v1",
        "Chromium Debian source and notice inputs",
    ),
    "browser_worker": (
        "deploy/manifests/browser-worker.json",
        "deeptwin-browser-build-input-v1",
        "Node Playwright and Chromium inputs",
    ),
    "codex_managed_runner": (
        "deploy/manifests/codex-0.153.4.json",
        "deeptwin-managed-runner-build-input-v3",
        "server-owned Codex managed-runner inputs",
    ),
    "codex_rust_dependencies": (
        "deploy/manifests/codex-0.153.4-rust-dependencies.json",
        "deeptwin-codex-rust-dependency-inventory-v1",
        "Codex Rust transitive dependency and license inputs",
    ),
    "python_wheel_artifacts": (
        "deploy/manifests/python-wheel-artifacts.json",
        "deeptwin-python-wheel-artifacts-v1",
        "per-service Python wheel closure",
    ),
    "service_python_roots": (
        "deploy/locks/service-roots.json",
        "deeptwin-service-python-roots-v1",
        "isolated service dependency roots",
    ),
    "speech_model": (
        "deploy/manifests/speech-model.json",
        "deeptwin-model-lock-v1",
        "offline speech model bytes",
    ),
    "upstream_images": (
        "deploy/manifests/upstream-images.json",
        "deeptwin-upstream-image-locks-v1",
        "third-party multi-architecture image inputs",
    ),
}

# The exact non-manifest leaf inventory is frozen with the aggregate.  Adding or removing a
# build-affecting verifier, policy, lock, test, result or notice requires an intentional schema
# edit and a new aggregate digest; directory discovery can therefore never silently shrink it.
EXPECTED_FILES: dict[str, str] = {
    "deploy/locks/browser-worker-seccomp.json": "browser sandbox policy",
    "deploy/locks/build_downstream_faster_whisper.py": "derived speech wheel builder",
    "deploy/locks/capture_codex_provenance_receipt.py": (
        "artifact-backed Codex provenance receipt capture tool"
    ),
    "deploy/locks/codex-0.153.4/Cargo.lock.effective": "Codex derived release Cargo lock",
    "deploy/locks/codex-0.153.4/Cargo.lock.source": "Codex source Cargo lock",
    "deploy/locks/generate_codex_rust_inventory.py": "Codex Rust inventory generator",
    "deploy/locks/licenses/CTranslate2-4.8.2-MIT.txt": "Python source license input",
    "deploy/locks/licenses/LangSmith-0.12.2-MIT.txt": "Python source license input",
    "deploy/locks/licenses/Node-24.20.0-LICENSE.txt": "Node distribution license input",
    "deploy/locks/licenses/OpenAI-Whisper-MIT.txt": "speech source license input",
    "deploy/locks/licenses/Silero-MIT.txt": "excluded upstream notice input",
    "deploy/locks/licenses/age-1.3.2/filippo.io-age-BSD-3-Clause.txt": "age module license input",
    "deploy/locks/licenses/age-1.3.2/filippo.io-edwards25519-BSD-3-Clause.txt": "age module license input",
    "deploy/locks/licenses/age-1.3.2/go-authors-BSD-3-Clause.txt": "Go runtime license input",
    "deploy/locks/licenses/sqlite-vec-0.1.9-Apache-2.0.txt": "Python source license input",
    "deploy/locks/licenses/sqlite-vec-0.1.9-MIT.txt": "Python source license input",
    "deploy/locks/licenses/tokenizers-0.22.1-Apache-2.0.txt": "Python source license input",
    "deploy/locks/moby-default-seccomp-61eaf326.json": "pinned sandbox policy base",
    "deploy/locks/nodejs/node-v24.20.0-SHASUMS256.txt.asc": "Node signed checksum input",
    "deploy/locks/nodejs/release-keys-5b7f55f4a7e35d1176d27a6b81b0c3c3b794216b.kbx": "Node verification keyring input",
    "deploy/locks/requirements-control-plane-linux.lock": "Python service lock",
    "deploy/locks/requirements-document-linux.lock": "Python service lock",
    "deploy/locks/requirements-provider-linux.lock": "Python service lock",
    "deploy/locks/requirements-runtime-linux.lock": "Python service lock",
    "deploy/locks/requirements-speech-linux.lock": "Python service lock",
    "deploy/locks/verify_age_runtime.py": "offline age verifier",
    "deploy/locks/verify_browser_debian_bookworm.py": "offline Debian closure verifier",
    "deploy/locks/verify_browser_runtime.mjs": "offline browser runtime verifier",
    "deploy/locks/verify_build_input_lock.py": "aggregate lock verifier",
    "deploy/locks/verify_build_inputs.py": "component lock verifier",
    "deploy/locks/verify_codex_runner.py": "offline Codex runner verifier",
    "deploy/locks/verify_codex_rust_inventory.py": "Codex Rust inventory verifier",
    "deploy/locks/verify_downstream_faster_whisper.py": "derived speech wheel verifier",
    "deploy/locks/verify_node_release.py": "offline Node release verifier",
    "deploy/locks/verify_playwright_provenance.mjs": "offline Playwright provenance verifier",
    "deploy/locks/generate_build_input_lock.py": "aggregate lock generator",
    "deploy/tests/age_runtime_canary.py": "age dual-platform runtime canary",
    "deploy/tests/browser_worker_canary.mjs": "browser sandbox and artifact canary",
    "deploy/tests/test_age_runtime.py": "age verifier adversarial tests",
    "deploy/tests/test_build_input_lock_verifier.py": "aggregate verifier adversarial tests",
    "deploy/tests/test_build_input_verifier.py": "component verifier adversarial tests",
    "deploy/tests/test_codex_runner_verifier.py": "Codex runner adversarial tests",
    "deploy/tests/test_codex_rust_inventory_verifier.py": "Codex Rust inventory adversarial tests",
    "deploy/tests/test_node_release_verifier.py": "Node provenance adversarial tests",
    "deploy/tests/test_playwright_provenance_verifier.mjs": "Playwright provenance adversarial tests",
    "specs/001-autonomous-release/evidence/age-1.3.2-native-results.json": "age native result evidence",
    "specs/001-autonomous-release/evidence/age-1.3.2-runtime-qualification.md": "age runtime evidence",
    "specs/001-autonomous-release/evidence/codex-0.153.4-rust-dependency-inventory.md": "Codex Rust dependency inventory evidence",
    CODEX_PROVENANCE_RECEIPT_PATH: "Codex provenance result evidence",
    "specs/001-autonomous-release/evidence/codex-minimal-runner-decision.proposal.md": "Codex ADR-013 minimal-runner decision evidence",
    "specs/001-autonomous-release/evidence/node-24.20.0-release-results.json": "Node release result evidence",
    "specs/001-autonomous-release/evidence/playwright-1.63.0-provenance-results.json": "Playwright provenance result evidence",
    "specs/001-autonomous-release/evidence/upstream-image-provenance-results.json": "upstream image provenance result evidence",
}

FORBIDDEN_T081_FIELDS = {
    "release_id",
    "source_commit",
    "compose_digest",
    "data_schema_version",
    "server_architectures",
    "container_runtimes",
    "tested_host_profiles",
    "tested_browsers",
    "required_capabilities",
    "image_locks",
    "edge_profile",
    "deployment_evidence_refs",
}

EXPECTED_ROOT_KEYS = {
    "schema_version",
    "scope",
    "status",
    "generated_at",
    "digest_profile",
    "digest_algorithm",
    "resolver_versions",
    "runtime_abis",
    "glibc_floor",
    "target_platforms",
    "runtime_mutation_policy",
    "manifest_refs",
    "file_refs",
    "artifacts",
    "upstream_image_locks",
    "model_component_locks",
    "license_provenance_refs",
    "verification_refs",
    "gates",
    "build_input_lock_set_digest",
}

EXPECTED_CHILD_ROOT_KEYS: dict[str, set[str]] = {
    "age_runtime_licenses": {
        "assurance_boundary", "components", "executable_module_sets", "go_source",
        "go_version", "license_files", "release_archive_license", "schema_version",
        "source_archive_sha256", "status", "tool", "version",
    },
    "age_tool": {
        "embedded_modules", "forbidden_archive_members_in_final_image", "github_attestation",
        "native_runtime_canary", "offline_runtime_verifier", "platform_archives",
        "release_blockers", "runtime_license_bundle", "runtime_profile", "schema_version",
        "sigsum_policy", "source", "source_commit", "status", "tag", "tool", "version",
    },
    "browser_debian_runtime": {
        "closure", "platforms", "required_release_gates", "research_input", "roots",
        "runtime_verifier", "schema_version", "snapshot", "source_license_evidence",
        "status", "upstream_inputs",
    },
    "browser_debian_sources": {
        "binaries", "binary_count", "notice", "schema_version", "snapshot_id",
        "source_package_count", "sources",
    },
    "browser_worker": {
        "chromium_headless_shell", "debian12_runtime_roots", "debian_runtime_lock", "node",
        "playwright_core", "release_blockers", "rendering_font_roots", "runtime_security",
        "schema_version", "status", "worker_runtime",
    },
    "codex_managed_runner": {
        "build_input_blockers", "build_input_gate", "downstream_release_blockers",
        "omitted_components", "platform_inputs", "release_gate", "runtime_layout",
        "runtime_mutation_policy", "schema_version", "signature_policy", "source_commit",
        "status", "tag", "target_platforms", "version",
    },
    "codex_rust_dependencies": {
        "codex", "external_build_inputs", "git_sources", "inventory_digest",
        "packages", "qualification_limits", "release_gate", "resolver", "roots",
        "schema_version", "source", "status", "summary", "targets",
    },
    "python_wheel_artifacts": {
        "artifacts", "legal_gate", "runtime", "schema_version", "service_locks",
        "service_profile_semantics", "status", "target_platforms",
    },
    "service_python_roots": {
        "derived_build_inputs", "excluded_from_web_release", "non_python_services", "notes",
        "python", "schema_version", "services", "status", "target_platforms",
    },
    "speech_model": {
        "allow_extra_files", "allow_symlinks", "download_at_runtime", "files",
        "license_declared_by_model_card", "license_inputs", "model_id",
        "provenance_limitations", "revision", "schema_version", "source_base", "status",
        "verification",
    },
    "upstream_images": {
        "descriptor_rule", "images", "provenance_verification", "release_blockers",
        "schema_version", "status",
    },
}

EXPECTED_CHILD_STATUSES: dict[str, str] = {
    "age_runtime_licenses": "candidate_technical_inventory_not_legal_approval",
    "age_tool": "candidate_not_release_qualified",
    "browser_debian_runtime": "candidate_blocked_not_release_qualified",
    "browser_worker": "candidate_not_release_qualified",
    "codex_managed_runner": "candidate_not_release_qualified",
    "codex_rust_dependencies": "candidate_exact_input_inventory_not_release_qualified",
    "python_wheel_artifacts": "candidate_not_release_qualified",
    "service_python_roots": "candidate_not_release_qualified",
    "speech_model": "bytes_verified_not_runtime_qualified",
    "upstream_images": "candidate_not_release_qualified",
}

EXPECTED_CHILD_MAX_TOTAL_ITEMS = {
    "codex_rust_dependencies": CODEX_RUST_CHILD_MAX_TOTAL_ITEMS,
}

EXPECTED_CODEX_RUST_DEPENDENCY_INVENTORY = {
    "path": "deploy/manifests/codex-0.153.4-rust-dependencies.json",
    "schema_version": "deeptwin-codex-rust-dependency-inventory-v1",
    "bytes": 857379,
    "sha256": "9d67a5dda134bcdaab8bc62cc2b0fdbb7d2adb3c94062b0a12ea14d09b71b644",
    "inventory_digest": "a09a94f6099c7f003555d4a1b43da996098c11d2c26a7cefb75062c2799b0d47",
    "status": "candidate_exact_input_inventory_not_release_qualified",
    "release_gate": "not_satisfied",
    "evidence": {
        "path": "specs/001-autonomous-release/evidence/codex-0.153.4-rust-dependency-inventory.md",
        "bytes": 11254,
        "sha256": "5aeb4354cacda1e6ced6187ece19cef9fe28f310e09c12a9d0aff6faefaef0ce",
    },
}
CODEX_COMPONENTS = ["codex", "codex-code-mode-host", "bubblewrap"]
CODEX_OMITTED_COMPONENTS = [
    "codex-package.json",
    "full-package-tar",
    "ripgrep",
    "zsh",
]
CODEX_PLATFORM_TARGETS = {
    "linux/amd64": "x86_64-unknown-linux-musl",
    "linux/arm64": "aarch64-unknown-linux-musl",
}
CODEX_RELEASE_BASE = (
    "https://github.com/openai/codex/releases/download/rust-v0.153.4/"
)
CODEX_SIGNATURE_IDENTITY = (
    "https://github.com/openai/codex/.github/workflows/"
    "rust-release.yml@refs/tags/rust-v0.153.4"
)
CODEX_SIGNATURE_ISSUER = "https://token.actions.githubusercontent.com"
CODEX_RUNTIME_LAYOUT = {
    "install_root": "/opt/deeptwin/codex",
    "codex_path": "/opt/deeptwin/codex/bin/codex",
    "code_mode_host_path": "/opt/deeptwin/codex/bin/codex-code-mode-host",
    "bubblewrap_path": "/opt/deeptwin/codex/bin/bwrap",
    "bash_path": "/bin/bash",
    "path_env": "/opt/deeptwin/codex/bin:/usr/bin:/bin",
    "required_internal_sandbox_profiles": ["read-only", "workspace-write"],
    "codex_home_policy": "isolated_per_run",
}
CODEX_RUNTIME_MUTATION_POLICY = {
    "browser_download_at_runtime": False,
    "model_download_at_runtime": False,
    "package_install_at_runtime": False,
    "package_resolution_at_runtime": False,
    "tool_download_at_runtime": False,
}
EXPECTED_CODEX_BUILD_INPUT_BLOCKERS: list[dict[str, str]] = []
EXPECTED_CODEX_DOWNSTREAM_RELEASE_BLOCKERS = [
    {
        "blocker_id": "codex-runner-worker-isolation",
        "owner_task": "T018",
        "gate_id": "t018-managed-runner-worker-isolation",
        "summary": "Managed-runner worker and IPC isolation remain unqualified.",
    },
    {
        "blocker_id": "codex-provider-authority-recovery",
        "owner_task": "T025",
        "gate_id": "t025-provider-authority-recovery",
        "summary": "Provider authorization, secret custody, and restart recovery remain open.",
    },
    {
        "blocker_id": "codex-security-provenance-qualification",
        "owner_task": "T079",
        "gate_id": "t079-integrated-security-qualification",
        "summary": "Integrated isolation and unsigned upstream provenance risk remain unqualified.",
    },
    {
        "blocker_id": "codex-final-image-runtime-canaries",
        "owner_task": "T081",
        "gate_id": "t081-final-image-runtime-canaries",
        "summary": "Final dual-platform runner images and sandbox canaries remain open.",
    },
    {
        "blocker_id": "codex-packaged-provenance-sbom",
        "owner_task": "T082",
        "gate_id": "t082-packaged-provenance-sbom",
        "summary": "Packaged SBOM, source-to-binary linkage, and authorized signing remain open.",
    },
    {
        "blocker_id": "codex-redistribution-publication-approval",
        "owner_task": "T084",
        "gate_id": "t084-redistribution-publication-approval",
        "summary": "Third-party notices, redistribution, legal, and publication approval remain open.",
    },
    {
        "blocker_id": "codex-native-subscription-qualification",
        "owner_task": "T088",
        "gate_id": "t088-native-subscription-qualification",
        "summary": "Native dual-platform and authorized subscription-runner qualification remain open.",
    },
]
AGGREGATE_ONLY_DOWNSTREAM_BLOCKERS = [
    {
        "blocker_id": "aggregate-fresh-host-deployment-qualification",
        "owner_task": "T083",
        "gate_id": "t083-fresh-host-deployment-qualification",
        "summary": "Two-host deployment and browser-smoke qualification remain open.",
    }
]

CHILD_FORBIDDEN_DISTRIBUTION_FIELDS = FORBIDDEN_T081_FIELDS - {"source_commit"}
DEFAULT_ALLOWED_RUNTIME_ABSOLUTE_VALUES = {
    "/usr/share/keyrings/debian-archive-keyring.gpg",
}
CODEX_ALLOWED_RUNTIME_ABSOLUTE_VALUES = {
    "/opt/deeptwin/codex",
    "/opt/deeptwin/codex/bin/codex",
    "/opt/deeptwin/codex/bin/codex-code-mode-host",
    "/opt/deeptwin/codex/bin/bwrap",
    "/bin/bash",
    "/opt/deeptwin/codex/bin:/usr/bin:/bin",
}


class LockVerificationError(ValueError):
    """Raised when an aggregate lock is not exact and fail-closed."""


def fail(message: str) -> NoReturn:
    raise LockVerificationError(message)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_float(_: str) -> NoReturn:
    fail("floating-point JSON values are forbidden")


def _reject_constant(value: str) -> NoReturn:
    fail(f"non-finite JSON value is forbidden: {value}")


def _validate_scalar_tree(value: Any, *, depth: int = 0) -> int:
    if depth > MAX_DEPTH:
        fail("JSON nesting exceeds depth 32")
    if value is None or type(value) is bool:
        return 1
    if type(value) is int:
        if value < -MAX_INTEGER or value > MAX_INTEGER:
            fail("JSON integer exceeds signed 63-bit domain")
        return 1
    if type(value) is str:
        if len(value.encode("utf-8", "surrogatepass")) > MAX_STRING_BYTES:
            fail("JSON string exceeds 64 KiB")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            fail("unpaired Unicode surrogate is forbidden")
        return 1
    if type(value) is list:
        if len(value) > MAX_ITEMS:
            fail("JSON array exceeds 10000 items")
        return 1 + sum(_validate_scalar_tree(item, depth=depth + 1) for item in value)
    if type(value) is dict:
        if len(value) > MAX_ITEMS:
            fail("JSON object exceeds 10000 members")
        count = 1
        for key, item in value.items():
            if type(key) is not str:
                fail("JSON object keys must be strings")
            count += _validate_scalar_tree(key, depth=depth + 1)
            count += _validate_scalar_tree(item, depth=depth + 1)
        return count
    fail(f"unsupported canonical JSON value: {type(value).__name__}")


def load_strict_json(
    path: Path, *, max_total_items: int = MAX_ITEMS
) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > MAX_BODY_BYTES:
        fail(f"{path}: JSON body exceeds 1 MiB")
    if raw.startswith(b"\xef\xbb\xbf"):
        fail(f"{path}: UTF-8 BOM is forbidden")
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except UnicodeDecodeError as exc:
        fail(f"{path}: invalid UTF-8: {exc}")
    except json.JSONDecodeError as exc:
        fail(f"{path}: invalid JSON: {exc}")
    if type(value) is not dict:
        fail(f"{path}: JSON root must be an object")
    if _validate_scalar_tree(value) > max_total_items:
        fail(f"{path}: JSON tree exceeds {max_total_items} total items")
    return value


def canonical_bytes(value: Any) -> bytes:
    if _validate_scalar_tree(value) > MAX_ITEMS:
        fail("canonical JSON tree exceeds 10000 total items")
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > MAX_BODY_BYTES:
        fail("canonical JSON body exceeds 1 MiB")
    return encoded


def _json_exactly_equal(actual: Any, expected: Any) -> bool:
    """Compare JSON values without Python's bool/int equality coercion."""

    return canonical_bytes(actual) == canonical_bytes(expected)


def seal_manifest(value: dict[str, Any]) -> dict[str, Any]:
    if "build_input_lock_set_digest" in value:
        value = dict(value)
        value.pop("build_input_lock_set_digest")
    digest = hashlib.sha256(canonical_bytes(value)).hexdigest()
    return {**value, "build_input_lock_set_digest": digest}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_relative_path(root: Path, relative: Any, label: str) -> Path:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        fail(f"{label}: normalized repository-relative path required")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        fail(f"{label}: path escape or noncanonical segment")
    if pure.as_posix() != relative:
        fail(f"{label}: noncanonical path")
    candidate = root.joinpath(*pure.parts)
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            fail(f"{label}: symlink is forbidden")
    try:
        metadata = candidate.stat()
    except FileNotFoundError:
        fail(f"{label}: referenced file is missing")
    if not stat.S_ISREG(metadata.st_mode):
        fail(f"{label}: referenced path is not a regular file")
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except ValueError:
        fail(f"{label}: resolved path escapes repository root")
    return candidate


def _require_sha256(value: Any, label: str) -> str:
    if type(value) is not str or not HEX64.fullmatch(value):
        fail(f"{label}: full lowercase SHA-256 required")
    return value


def _verify_ref(
    root: Path,
    reference: Any,
    expected_path: str,
    expected_role: str,
    *,
    schema: str | None = None,
    max_total_items: int = MAX_ITEMS,
) -> dict[str, Any]:
    expected_keys = {"path", "bytes", "sha256", "role"}
    if schema is not None:
        expected_keys.update({"id", "schema_version"})
    if type(reference) is not dict or set(reference) != expected_keys:
        fail(f"{expected_path}: reference shape changed")
    if reference["path"] != expected_path or reference["role"] != expected_role:
        fail(f"{expected_path}: reference identity changed")
    path = _validate_relative_path(root, reference["path"], expected_path)
    if type(reference["bytes"]) is not int or type(reference["bytes"]) is bool or reference["bytes"] <= 0:
        fail(f"{expected_path}: positive exact byte count required")
    if path.stat().st_size != reference["bytes"]:
        fail(f"{expected_path}: referenced byte count changed")
    if sha256_file(path) != _require_sha256(reference["sha256"], f"{expected_path}.sha256"):
        fail(f"{expected_path}: referenced bytes changed")
    value = (
        load_strict_json(path, max_total_items=max_total_items)
        if schema is not None
        else {}
    )
    if schema is not None:
        if reference["schema_version"] != schema or value.get("schema_version") != schema:
            fail(f"{expected_path}: schema version changed")
    return value


def _index_refs(values: Any, label: str, key: str) -> dict[str, dict[str, Any]]:
    if type(values) is not list:
        fail(f"{label}: array required")
    identities: list[str] = []
    result: dict[str, dict[str, Any]] = {}
    for item in values:
        if type(item) is not dict or type(item.get(key)) is not str:
            fail(f"{label}: every reference requires {key}")
        identity = item[key]
        if identity in result:
            fail(f"{label}: duplicate {key} {identity}")
        identities.append(identity)
        result[identity] = item
    if identities != sorted(identities):
        fail(f"{label}: references must be canonically sorted")
    return result


def _verify_codex_component(
    component: Any,
    *,
    platform: str,
    target: str,
    expected_name: str,
) -> None:
    label = f"Codex {platform} {expected_name}"
    if type(component) is not dict or set(component) != {
        "name", "archive", "executable", "sigstore_bundle", "signature_scope"
    }:
        fail(f"{label}: standalone component shape changed")
    if component["name"] != expected_name:
        fail(f"{label}: component ordering or identity changed")
    if component["signature_scope"] != "extracted executable only":
        fail(f"{label}: signature must remain executable-scoped")

    asset_prefix = "bwrap" if expected_name == "bubblewrap" else expected_name
    asset_name = f"{asset_prefix}-{target}"
    archive = component["archive"]
    if type(archive) is not dict or set(archive) != {
        "url", "filename", "bytes", "sha256", "member_path"
    }:
        fail(f"{label}: standalone archive shape changed")
    if (
        archive["url"] != f"{CODEX_RELEASE_BASE}{asset_name}.tar.gz"
        or archive["filename"] != f"{asset_name}.tar.gz"
        or archive["member_path"] != asset_name
    ):
        fail(f"{label}: standalone archive identity changed")
    if (
        type(archive["bytes"]) is not int
        or archive["bytes"] <= 0
        or archive["bytes"] > MAX_INTEGER
    ):
        fail(f"{label}: standalone archive requires a bounded positive byte count")
    _require_sha256(archive["sha256"], f"{label}.archive.sha256")

    executable = component["executable"]
    if type(executable) is not dict or set(executable) != {
        "installed_path", "bytes", "sha256", "mode"
    }:
        fail(f"{label}: executable shape changed")
    installed_paths = {
        "codex": CODEX_RUNTIME_LAYOUT["codex_path"],
        "codex-code-mode-host": CODEX_RUNTIME_LAYOUT["code_mode_host_path"],
        "bubblewrap": CODEX_RUNTIME_LAYOUT["bubblewrap_path"],
    }
    if (
        executable["installed_path"] != installed_paths[expected_name]
        or executable["mode"] != "0755"
        or type(executable["bytes"]) is not int
        or executable["bytes"] <= 0
        or executable["bytes"] > MAX_INTEGER
    ):
        fail(f"{label}: executable placement, mode, or size changed")
    _require_sha256(executable["sha256"], f"{label}.executable.sha256")

    bundle = component["sigstore_bundle"]
    if type(bundle) is not dict or set(bundle) != {
        "url", "filename", "bytes", "sha256", "verified"
    }:
        fail(f"{label}: Sigstore bundle shape changed")
    if (
        bundle["url"] != f"{CODEX_RELEASE_BASE}{asset_name}.sigstore"
        or bundle["filename"] != f"{asset_name}.sigstore"
        or bundle["verified"] is not True
        or type(bundle["bytes"]) is not int
        or bundle["bytes"] <= 0
        or bundle["bytes"] > MAX_INTEGER
    ):
        fail(f"{label}: independently verified Sigstore bundle changed")
    _require_sha256(bundle["sha256"], f"{label}.sigstore_bundle.sha256")


def _require_positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0 or value > MAX_INTEGER:
        fail(f"{label}: bounded positive integer required")
    return value


def _require_prefixed_sha256(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or not value.startswith("sha256:")
        or not HEX64.fullmatch(value.removeprefix("sha256:"))
    ):
        fail(f"{label}: full lowercase sha256 descriptor digest required")
    return value


def _verify_oci_descriptor(
    value: Any,
    *,
    label: str,
    media_type: str,
    position: int | None = None,
) -> None:
    expected_keys = {"media_type", "digest", "bytes"}
    if position is not None:
        expected_keys.add("position")
    if type(value) is not dict or set(value) != expected_keys:
        fail(f"{label}: OCI descriptor shape changed")
    if value["media_type"] != media_type:
        fail(f"{label}: OCI media type changed")
    if position is not None and value["position"] != position:
        fail(f"{label}: OCI layer position changed")
    _require_prefixed_sha256(value["digest"], f"{label}.digest")
    _require_positive_int(value["bytes"], f"{label}.bytes")


def _verify_debian_artifact(value: Any, *, label: str, filename: str) -> None:
    if type(value) is not dict or set(value) != {"filename", "url", "bytes", "sha256"}:
        fail(f"{label}: Debian artifact shape changed")
    if value["filename"] != filename:
        fail(f"{label}: Debian artifact filename changed")
    if (
        type(value["url"]) is not str
        or not re.fullmatch(r"https://snapshot\.debian\.org/file/[0-9a-f]{40}", value["url"])
    ):
        fail(f"{label}: exact Debian snapshot content URL required")
    _require_positive_int(value["bytes"], f"{label}.bytes")
    _require_sha256(value["sha256"], f"{label}.sha256")


def _verify_codex_runtime_image(runtime_image: Any, *, platform: str) -> None:
    """Validate the bounded ADR-013 OCI and Debian Bash source closure."""

    label = f"Codex {platform} runtime_image"
    expected_keys = {
        "distribution", "suite", "repository", "tag", "created_at", "snapshot",
        "source_repository", "source_revision", "index", "manifest", "config",
        "layers", "bash",
    }
    if type(runtime_image) is not dict or set(runtime_image) != expected_keys:
        fail(f"{label}: Bookworm runtime shape changed")
    expected_source_revisions = {
        "linux/amd64": "bae6d64d90b4068b09ff9d8b564c2773ef5d8d83",
        "linux/arm64": "f73bd086e8d0e5e1c8b838ccc442bf24eb3ea205",
    }
    identity = {
        "distribution": "debian",
        "suite": "bookworm",
        "repository": "docker.io/library/debian",
        "tag": "bookworm-20260824-slim",
        "created_at": "2026-08-24T00:00:00Z",
        "snapshot": "20260824T000000Z",
        "source_repository": "https://github.com/debuerreotype/docker-debian-artifacts.git",
        "source_revision": expected_source_revisions[platform],
    }
    if any(runtime_image[key] != value for key, value in identity.items()):
        fail(f"{label}: date-pinned Docker Official Image identity changed")
    if not HEX40.fullmatch(runtime_image["source_revision"]):
        fail(f"{label}: full lowercase source revision required")

    _verify_oci_descriptor(
        runtime_image["index"],
        label=f"{label}.index",
        media_type="application/vnd.oci.image.index.v1+json",
    )
    _verify_oci_descriptor(
        runtime_image["manifest"],
        label=f"{label}.manifest",
        media_type="application/vnd.oci.image.manifest.v1+json",
    )
    _verify_oci_descriptor(
        runtime_image["config"],
        label=f"{label}.config",
        media_type="application/vnd.oci.image.config.v1+json",
    )
    layers = runtime_image["layers"]
    if type(layers) is not list or len(layers) != 1:
        fail(f"{label}: exact single-layer runtime image required")
    _verify_oci_descriptor(
        layers[0],
        label=f"{label}.layers[0]",
        media_type="application/vnd.oci.image.layer.v1.tar+gzip",
        position=1,
    )

    bash = runtime_image["bash"]
    if type(bash) is not dict or set(bash) != {
        "package", "package_version", "source_package", "source_version",
        "installed_path", "mode", "binary_package", "package_member",
        "license_member", "source_inputs",
    }:
        fail(f"{label}: Bash closure shape changed")
    if (
        bash["package"] != "bash"
        or bash["package_version"] != "5.2.15-2+b13"
        or bash["source_package"] != "bash"
        or bash["source_version"] != "5.2.15-2"
        or bash["installed_path"] != "/bin/bash"
        or bash["mode"] != "0755"
    ):
        fail(f"{label}: Bash package/source/member identity changed")
    architecture = "amd64" if platform == "linux/amd64" else "arm64"
    _verify_debian_artifact(
        bash["binary_package"],
        label=f"{label}.bash.binary_package",
        filename=f"bash_5.2.15-2+b13_{architecture}.deb",
    )
    package_member = bash["package_member"]
    if type(package_member) is not dict or set(package_member) != {
        "path", "installed_path", "bytes", "sha256", "mode"
    }:
        fail(f"{label}: Bash executable member shape changed")
    if (
        package_member["path"] != "bin/bash"
        or package_member["installed_path"] != "/bin/bash"
        or package_member["mode"] != "0755"
    ):
        fail(f"{label}: Bash executable member identity changed")
    _require_positive_int(package_member["bytes"], f"{label}.bash.package_member.bytes")
    _require_sha256(package_member["sha256"], f"{label}.bash.package_member.sha256")

    license_member = bash["license_member"]
    if type(license_member) is not dict or set(license_member) != {
        "path", "bytes", "sha256"
    }:
        fail(f"{label}: Bash license member shape changed")
    if license_member["path"] != "usr/share/doc/bash/copyright":
        fail(f"{label}: Bash license member identity changed")
    _require_positive_int(license_member["bytes"], f"{label}.bash.license_member.bytes")
    _require_sha256(license_member["sha256"], f"{label}.bash.license_member.sha256")

    source_inputs = bash["source_inputs"]
    source_filenames = [
        "bash_5.2.15-2.dsc",
        "bash_5.2.15.orig.tar.gz",
        "bash_5.2.15-2.debian.tar.xz",
    ]
    if type(source_inputs) is not list or len(source_inputs) != len(source_filenames):
        fail(f"{label}: exact Bash source input set required")
    for source_input, filename in zip(source_inputs, source_filenames, strict=True):
        _verify_debian_artifact(
            source_input,
            label=f"{label}.bash.source_inputs[{filename}]",
            filename=filename,
        )


def _expected_codex_signature_policy(root: Path) -> dict[str, Any]:
    """Reuse the exact verifier-bootstrap lock owned by the child verifier."""

    verifier_path = _validate_relative_path(
        root,
        "deploy/locks/verify_codex_runner.py",
        "Codex managed-runner verifier",
    )
    spec = importlib.util.spec_from_file_location(
        "deeptwin_codex_runner_policy_for_aggregate", verifier_path
    )
    if spec is None or spec.loader is None:
        fail("Codex managed-runner verifier could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    bootstrap = getattr(module, "COSIGN_BOOTSTRAP_POLICY", None)
    if type(bootstrap) is not dict:
        fail("Codex verifier bootstrap policy is unavailable")
    return {
        "offline": True,
        "subject_scope": "extracted executable only",
        "certificate_identity": CODEX_SIGNATURE_IDENTITY,
        "certificate_oidc_issuer": CODEX_SIGNATURE_ISSUER,
        "verifier_bootstrap": bootstrap,
    }


def _verify_codex_blocker_records(
    value: Any,
    *,
    label: str,
    expected: list[dict[str, str]],
    owner: str | None,
) -> list[dict[str, str]]:
    if type(value) is not list or len(value) > 64:
        fail(f"Codex {label} must be a bounded structured list")
    blocker_ids: list[str] = []
    gate_ids: list[str] = []
    for record in value:
        if type(record) is not dict or set(record) != {
            "blocker_id", "owner_task", "gate_id", "summary"
        }:
            fail(f"Codex {label} must use exact structured blocker records")
        if any(type(record[key]) is not str for key in record):
            fail(f"Codex {label} fields must be strings")
        if any(
            re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", record[key]) is None
            for key in ("blocker_id", "gate_id")
        ):
            fail(f"Codex {label} IDs must be stable kebab-case identifiers")
        if (
            not record["summary"]
            or len(record["summary"].encode("utf-8")) > 256
            or "\n" in record["summary"]
        ):
            fail(f"Codex {label} summary must be concise and bounded")
        if owner is not None and record["owner_task"] != owner:
            fail(f"Codex {label} blocker ownership changed")
        if record["blocker_id"] in blocker_ids or record["gate_id"] in gate_ids:
            fail(f"Codex {label} contains duplicate blocker or gate IDs")
        blocker_ids.append(record["blocker_id"])
        gate_ids.append(record["gate_id"])
    if not _json_exactly_equal(value, expected):
        fail(f"Codex {label} inventory, ownership, or canonical order changed")
    return value


def _aggregate_downstream_gate_records(
    codex: dict[str, Any],
) -> list[dict[str, Any]]:
    """Map child blockers one-for-one and add T083's aggregate-only gate."""

    blockers = [
        *codex["downstream_release_blockers"],
        *AGGREGATE_ONLY_DOWNSTREAM_BLOCKERS,
    ]
    by_owner: dict[str, dict[str, str]] = {}
    for blocker in blockers:
        owner = blocker["owner_task"]
        if owner in by_owner:
            fail(f"aggregate downstream gate has duplicate owner {owner}")
        by_owner[owner] = blocker
    if set(by_owner) != set(EXPECTED_DOWNSTREAM_TASKS):
        fail("aggregate downstream gate ownership set changed")
    return [
        {
            "blocking_for_build_input_lock": False,
            "id": by_owner[owner]["blocker_id"],
            "gate_id": by_owner[owner]["gate_id"],
            "owner_task": owner,
            "status": "open",
            "summary": by_owner[owner]["summary"],
        }
        for owner in EXPECTED_DOWNSTREAM_TASKS
    ]


def verify_codex_t089_candidate_state(
    root: Path,
    codex: dict[str, Any],
    *,
    locked: bool,
) -> None:
    """Bind T089 to ADR-013's minimal signed runner, never the retired package."""

    expected_keys = EXPECTED_CHILD_ROOT_KEYS["codex_managed_runner"]
    if type(codex) is not dict or set(codex) != expected_keys:
        fail("Codex minimal-runner v3 root shape changed")
    expected_identity = {
        "schema_version": "deeptwin-managed-runner-build-input-v3",
        "status": "candidate_not_release_qualified",
        "version": "0.153.4",
        "tag": "rust-v0.153.4",
        "source_commit": "3d2ee51ca2d5db578f328aa75e20aa22c0197c9a",
        "target_platforms": PLATFORMS,
    }
    if any(
        not _json_exactly_equal(codex.get(key), value)
        for key, value in expected_identity.items()
    ):
        fail("Codex minimal-runner identity or platform order changed")
    if not _json_exactly_equal(
        codex["signature_policy"], _expected_codex_signature_policy(root)
    ):
        fail("Codex executable-scoped signature policy changed")
    if not _json_exactly_equal(codex["runtime_layout"], CODEX_RUNTIME_LAYOUT):
        fail("Codex fixed sibling/runtime layout changed")
    if not _json_exactly_equal(codex["omitted_components"], CODEX_OMITTED_COMPONENTS):
        fail("Codex omitted full-package/rg/zsh boundary changed")
    if not _json_exactly_equal(
        codex["runtime_mutation_policy"], CODEX_RUNTIME_MUTATION_POLICY
    ):
        fail("Codex runtime mutation policy changed")

    platform_inputs = codex["platform_inputs"]
    if type(platform_inputs) is not list or len(platform_inputs) != len(PLATFORMS):
        fail("Codex platform_inputs must exactly cover both Linux targets")
    for index, platform in enumerate(PLATFORMS):
        platform_input = platform_inputs[index]
        target = CODEX_PLATFORM_TARGETS[platform]
        if type(platform_input) is not dict or set(platform_input) != {
            "platform", "target", "components", "runtime_image"
        }:
            fail(f"Codex {platform}: platform input shape changed")
        if platform_input["platform"] != platform or platform_input["target"] != target:
            fail("Codex platform input ordering or target changed")
        components = platform_input["components"]
        if (
            type(components) is not list
            or [item.get("name") if type(item) is dict else None for item in components]
            != CODEX_COMPONENTS
        ):
            fail(f"Codex {platform}: component set/order changed")
        for component, expected_name in zip(components, CODEX_COMPONENTS, strict=True):
            _verify_codex_component(
                component,
                platform=platform,
                target=target,
                expected_name=expected_name,
            )
        _verify_codex_runtime_image(
            platform_input["runtime_image"], platform=platform
        )

    build_blockers = _verify_codex_blocker_records(
        codex["build_input_blockers"],
        label="build_input_blockers",
        expected=EXPECTED_CODEX_BUILD_INPUT_BLOCKERS,
        owner="T089",
    )
    downstream_blockers = _verify_codex_blocker_records(
        codex["downstream_release_blockers"],
        label="downstream_release_blockers",
        expected=EXPECTED_CODEX_DOWNSTREAM_RELEASE_BLOCKERS,
        owner=None,
    )
    expected_build_gate = "not_satisfied" if build_blockers else "satisfied"
    if codex["build_input_gate"] != expected_build_gate:
        fail("Codex build_input_gate must depend only on T089 build blockers")
    expected_release_gate = (
        "not_satisfied" if build_blockers or downstream_blockers else "satisfied"
    )
    if codex["release_gate"] != expected_release_gate:
        fail("Codex release_gate must include downstream release blockers")
    if locked and build_blockers:
        fail("Codex T089 build-input blockers remain; the aggregate cannot be locked")


def verify_codex_rust_candidate_state(
    root: Path,
    rust_inventory: dict[str, Any],
) -> None:
    """Validate the Rust inventory and its evidence outside the runner schema."""

    expected = EXPECTED_CODEX_RUST_DEPENDENCY_INVENTORY
    identity = {
        "schema_version": expected["schema_version"],
        "status": expected["status"],
        "inventory_digest": expected["inventory_digest"],
        "release_gate": expected["release_gate"],
    }
    if any(rust_inventory.get(key) != value for key, value in identity.items()):
        fail("Codex Rust dependency inventory identity changed")
    packages = rust_inventory.get("packages")
    if type(packages) is not list or len(packages) != 1047:
        fail("Codex Rust dependency package inventory changed")

    for reference, label in (
        (expected, "Rust dependency inventory"),
        (expected["evidence"], "Rust dependency inventory evidence"),
    ):
        relative = reference["path"]
        path = _validate_relative_path(root, relative, label)
        if (
            path.stat().st_size != reference["bytes"]
            or sha256_file(path)
            != _require_sha256(reference["sha256"], f"{label}.sha256")
        ):
            fail(f"Codex {label} reference changed")

    verifier_path = _validate_relative_path(
        root,
        "deploy/locks/verify_codex_rust_inventory.py",
        "Codex Rust inventory verifier",
    )
    spec = importlib.util.spec_from_file_location(
        "deeptwin_aggregate_codex_rust_inventory_verifier", verifier_path
    )
    if spec is None or spec.loader is None:
        fail("Codex Rust inventory verifier could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    try:
        result = module.verify_inventory(root)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        fail(f"Codex Rust inventory verification failed: {exc}")
    verified_summary = {
        "inventory_digest": result.get("inventory_digest"),
        "package_count": result.get("package_count"),
        "release_gate": result.get("release_gate"),
    }
    expected_summary = {
        "inventory_digest": expected["inventory_digest"],
        "package_count": 1047,
        "release_gate": "not_satisfied",
    }
    if not _json_exactly_equal(verified_summary, expected_summary):
        fail("Codex Rust inventory verified summary changed")


def _receipt_evidence(kind: str, descriptor: Any) -> dict[str, Any]:
    """Keep every pass result attached to the exact child-manifest evidence."""

    return {"kind": kind, "descriptor": descriptor}


def _receipt_row(
    identity: str,
    category: str,
    platform: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": identity,
        "category": category,
        "platform": platform,
        "result": "pass",
        "evidence": evidence,
    }


def _expected_codex_provenance_rows(
    codex: dict[str, Any], *, result: str = "pass"
) -> list[dict[str, Any]]:
    """Project the v3 child into a finite, evidence-bearing result inventory."""

    if result not in {"pass", "recorded_not_replayable"}:
        fail("Codex provenance receipt result enum changed")

    rows: list[dict[str, Any]] = []
    signature_policy = codex["signature_policy"]
    signature_context = {
        "subject_scope": signature_policy["subject_scope"],
        "certificate_identity": signature_policy["certificate_identity"],
        "certificate_oidc_issuer": signature_policy["certificate_oidc_issuer"],
    }
    for platform_input in codex["platform_inputs"]:
        platform = platform_input["platform"]
        platform_id = platform.replace("/", "-")
        for component in platform_input["components"]:
            rows.append(
                _receipt_row(
                    f"openai-sigstore-{platform_id}-{component['name']}",
                    "openai-executable-sigstore",
                    platform,
                    [
                        _receipt_evidence("executable", component["executable"]),
                        _receipt_evidence(
                            "sigstore-bundle", component["sigstore_bundle"]
                        ),
                        _receipt_evidence("signature-policy", signature_context),
                    ],
                )
            )

    bootstrap = signature_policy["verifier_bootstrap"]
    checksum = bootstrap["checksum_manifest"]
    checksum_artifact = {
        key: checksum[key] for key in ("url", "filename", "bytes", "sha256")
    }
    checksum_bundle = checksum["sigstore_bundle"]
    if checksum["signature_chain_verified"] is not True:
        fail("Codex cosign checksum signature chain is not verified")
    rows.extend(
        (
            _receipt_row(
                "cosign-checksum-manifest",
                "cosign-bootstrap",
                "common",
                [
                    _receipt_evidence("checksum-manifest", checksum_artifact),
                    _receipt_evidence("sigstore-bundle", checksum_bundle),
                ],
            ),
            _receipt_row(
                "cosign-checksum-sigstore-bundle",
                "cosign-bootstrap",
                "common",
                [
                    _receipt_evidence("sigstore-bundle", checksum_bundle),
                    _receipt_evidence("signed-subject", checksum_artifact),
                ],
            ),
        )
    )
    for verifier in bootstrap["release_build_verifiers"]:
        platform = verifier["platform"]
        if (
            verifier["checksum_manifest_match"] is not True
            or verifier["signature_chain_verified"] is not True
        ):
            fail(f"Codex {platform} cosign release verifier is not fully verified")
        rows.append(
            _receipt_row(
                f"cosign-release-verifier-{platform.replace('/', '-')}",
                "cosign-bootstrap",
                platform,
                [
                    _receipt_evidence("executable", verifier["executable"]),
                    _receipt_evidence(
                        "sigstore-bundle", verifier["sigstore_bundle"]
                    ),
                    _receipt_evidence("checksum-manifest", checksum_artifact),
                ],
            )
        )
    audit_observations = bootstrap["audit_observations"]
    if type(audit_observations) is not list or len(audit_observations) != 1:
        fail("Codex cosign audit verifier inventory changed")
    audit = audit_observations[0]
    if (
        audit["eligible_for_release_build"] is not False
        or audit["checksum_manifest_match"] is not True
        or audit["signature_chain_verified"] is not True
    ):
        fail("Codex cosign audit verifier boundary changed")
    rows.append(
        _receipt_row(
            "cosign-audit-verifier-darwin-arm64",
            "cosign-audit-observation",
            "darwin/arm64",
            [
                _receipt_evidence("executable", audit["executable"]),
                _receipt_evidence("sigstore-bundle", audit["sigstore_bundle"]),
                _receipt_evidence("checksum-manifest", checksum_artifact),
            ],
        )
    )

    platform_inputs = codex["platform_inputs"]
    first_runtime = platform_inputs[0]["runtime_image"]
    if any(
        not _json_exactly_equal(
            platform_input["runtime_image"]["index"], first_runtime["index"]
        )
        for platform_input in platform_inputs[1:]
    ):
        fail("Codex platforms disagree on the common OCI index")
    rows.append(
        _receipt_row(
            "oci-bookworm-index",
            "oci-descriptor",
            "common",
            [
                _receipt_evidence("oci-index", first_runtime["index"]),
                _receipt_evidence(
                    "oci-reference",
                    {
                        "repository": first_runtime["repository"],
                        "tag": first_runtime["tag"],
                    },
                ),
            ],
        )
    )
    for platform_input in platform_inputs:
        platform = platform_input["platform"]
        platform_id = platform.replace("/", "-")
        runtime = platform_input["runtime_image"]
        for kind in ("manifest", "config"):
            rows.append(
                _receipt_row(
                    f"oci-bookworm-{kind}-{platform_id}",
                    "oci-descriptor",
                    platform,
                    [
                        _receipt_evidence(f"oci-{kind}", runtime[kind]),
                        _receipt_evidence("oci-index", runtime["index"]),
                    ],
                )
            )
        for layer in runtime["layers"]:
            rows.append(
                _receipt_row(
                    f"oci-bookworm-layer-{platform_id}-{layer['position']}",
                    "oci-descriptor",
                    platform,
                    [
                        _receipt_evidence("oci-layer", layer),
                        _receipt_evidence("oci-manifest", runtime["manifest"]),
                    ],
                )
            )

    first_bash = first_runtime["bash"]
    for platform_input in platform_inputs:
        platform = platform_input["platform"]
        platform_id = platform.replace("/", "-")
        bash = platform_input["runtime_image"]["bash"]
        rows.extend(
            (
                _receipt_row(
                    f"bash-debian-package-{platform_id}",
                    "bash-input",
                    platform,
                    [
                        _receipt_evidence(
                            "debian-binary-package", bash["binary_package"]
                        ),
                        _receipt_evidence(
                            "installed-member", bash["package_member"]
                        ),
                    ],
                ),
                _receipt_row(
                    f"bash-installed-executable-{platform_id}",
                    "bash-input",
                    platform,
                    [
                        _receipt_evidence(
                            "installed-member", bash["package_member"]
                        ),
                        _receipt_evidence(
                            "debian-binary-package", bash["binary_package"]
                        ),
                    ],
                ),
            )
        )
    if any(
        not _json_exactly_equal(
            platform_input["runtime_image"]["bash"]["license_member"],
            first_bash["license_member"],
        )
        for platform_input in platform_inputs[1:]
    ):
        fail("Codex platforms disagree on the common Bash copyright artifact")
    rows.append(
        _receipt_row(
            "bash-copyright-common",
            "bash-input",
            "common",
            [
                _receipt_evidence("copyright-member", first_bash["license_member"]),
                _receipt_evidence("used-by-platforms", PLATFORMS),
            ],
        )
    )
    first_sources = first_bash["source_inputs"]
    if any(
        not _json_exactly_equal(
            platform_input["runtime_image"]["bash"]["source_inputs"],
            first_sources,
        )
        for platform_input in platform_inputs[1:]
    ):
        fail("Codex platforms disagree on the common Bash source input set")
    for source in first_sources:
        stable_name = re.sub(r"[^a-z0-9]+", "-", source["filename"].lower()).strip("-")
        rows.append(
            _receipt_row(
                f"bash-source-{stable_name}",
                "bash-input",
                "common",
                [
                    _receipt_evidence("debian-source-file", source),
                    _receipt_evidence("used-by-platforms", PLATFORMS),
                ],
            )
        )

    for row in rows:
        row["result"] = result
    return sorted(rows, key=lambda item: item["id"])


def _reject_codex_receipt_backlink(value: Any, *, label: str = "codex") -> None:
    if type(value) is list:
        for index, item in enumerate(value):
            _reject_codex_receipt_backlink(item, label=f"{label}[{index}]")
        return
    if type(value) is not dict:
        if value == CODEX_PROVENANCE_RECEIPT_PATH:
            fail(f"{label}: Codex child provenance receipt back-reference is forbidden")
        return
    for key, item in value.items():
        if "receipt" in key.lower():
            fail(f"{label}.{key}: Codex child provenance receipt back-reference is forbidden")
        _reject_codex_receipt_backlink(item, label=f"{label}.{key}")


def _codex_runner_file_binding(value: dict[str, Any]) -> dict[str, Any]:
    """Project one already-validated runner input onto its exact file identity."""

    return {
        "filename": value["filename"],
        "bytes": value["bytes"],
        "sha256": value["sha256"],
    }


def _expected_codex_runner_report(
    codex: dict[str, Any], *, execution_platform: str
) -> dict[str, Any]:
    """Derive the complete report emitted by ``verify_codex_runner.py``.

    The child manifest is structurally and semantically verified before this helper
    is called.  This projection deliberately includes every runner-report field,
    all 17 files opened by the verifier, and each of the six Sigstore outcomes so a
    receipt cannot pass by retaining only a summary.
    """

    try:
        signature = codex["signature_policy"]
        bootstrap = signature["verifier_bootstrap"]
        release_verifiers = bootstrap["release_build_verifiers"]
        audit_verifiers = bootstrap["audit_observations"]
        if execution_platform in PLATFORMS:
            candidates = [
                item
                for item in release_verifiers
                if item["platform"] == execution_platform
            ]
            selection_mode = "release-build"
        elif execution_platform == "darwin/arm64":
            candidates = [
                item
                for item in audit_verifiers
                if item["platform"] == execution_platform
            ]
            selection_mode = "audit-only"
        else:
            fail("Codex provenance receipt execution platform changed")
        if len(candidates) != 1:
            fail("Codex provenance receipt verifier selection is not exact")
        selected_verifier = candidates[0]

        platform_reports: list[dict[str, Any]] = []
        verified_input_files: list[dict[str, Any]] = []
        bash_source_inputs = [
            dict(item)
            for item in codex["platform_inputs"][0]["runtime_image"]["bash"][
                "source_inputs"
            ]
        ]
        verified_input_files.extend(
            _codex_runner_file_binding(item) for item in bash_source_inputs
        )

        verification_outcome_count = 0
        for platform_input in codex["platform_inputs"]:
            runtime = platform_input["runtime_image"]
            bash = runtime["bash"]
            binary_package = bash["binary_package"]
            verified_input_files.append(
                _codex_runner_file_binding(binary_package)
            )
            component_reports: list[dict[str, Any]] = []
            for component in platform_input["components"]:
                archive = component["archive"]
                bundle = component["sigstore_bundle"]
                verified_input_files.extend(
                    (
                        _codex_runner_file_binding(archive),
                        _codex_runner_file_binding(bundle),
                    )
                )
                component_reports.append(
                    {
                        "name": component["name"],
                        "archive_sha256": archive["sha256"],
                        "executable_sha256": component["executable"]["sha256"],
                        "bundle_sha256": bundle["sha256"],
                        "sigstore_verified": True,
                    }
                )
                verification_outcome_count += 1
            platform_reports.append(
                {
                    "platform": platform_input["platform"],
                    "target": platform_input["target"],
                    "runtime_image": {
                        "index_digest": runtime["index"]["digest"],
                        "manifest_digest": runtime["manifest"]["digest"],
                        "config_digest": runtime["config"]["digest"],
                        "layer_digest": runtime["layers"][0]["digest"],
                        "source_revision": runtime["source_revision"],
                    },
                    "bash": {
                        **dict(binary_package),
                        "package_member": {
                            key: bash["package_member"][key]
                            for key in ("path", "bytes", "sha256")
                        },
                        "license_member": {
                            key: bash["license_member"][key]
                            for key in ("path", "bytes", "sha256")
                        },
                    },
                    "components": component_reports,
                }
            )

        verified_input_files.sort(key=lambda item: item["filename"])
        if (
            len(verified_input_files) != EXPECTED_CODEX_VERIFIED_INPUT_FILE_COUNT
            or len({item["filename"] for item in verified_input_files})
            != EXPECTED_CODEX_VERIFIED_INPUT_FILE_COUNT
            or verification_outcome_count != 6
        ):
            fail("Codex runner report input or verification inventory changed")

        return {
            "schema_version": codex["schema_version"],
            "status": codex["status"],
            "version": codex["version"],
            "platform_count": len(platform_reports),
            "component_count": verification_outcome_count,
            "layout": dict(codex["runtime_layout"]),
            "omitted_components": list(codex["omitted_components"]),
            "cosign": {
                "selected_verifier_platform": selected_verifier["platform"],
                "selection_mode": selection_mode,
                "artifact": _codex_runner_file_binding(
                    selected_verifier["executable"]
                ),
                "linux_platform_coverage": [
                    item["platform"] for item in release_verifiers
                ],
                "bootstrap_identity": bootstrap["certificate_identity"],
                "audit_only_platforms": [
                    item["platform"] for item in audit_verifiers
                ],
            },
            "signature_scope": signature["subject_scope"],
            "bash_source_inputs": bash_source_inputs,
            "verified_input_file_count": len(verified_input_files),
            "verified_input_files": verified_input_files,
            "platforms": platform_reports,
            "build_input_gate": codex["build_input_gate"],
            "build_input_blocker_count": len(codex["build_input_blockers"]),
            "release_gate": codex["release_gate"],
            "downstream_release_blocker_count": len(
                codex["downstream_release_blockers"]
            ),
        }
    except (IndexError, KeyError, TypeError) as exc:
        fail(f"Codex runner report projection failed: {exc}")


def verify_codex_provenance_receipt(
    root: Path,
    *,
    receipt_path: Path,
    codex_manifest_ref: dict[str, Any],
    codex: dict[str, Any],
) -> dict[str, Any]:
    """Verify the aggregate-only, one-way ADR-013 provenance receipt."""

    _reject_codex_receipt_backlink(codex)
    receipt = load_strict_json(
        receipt_path,
        max_total_items=CODEX_PROVENANCE_RECEIPT_MAX_TOTAL_ITEMS,
    )
    if type(receipt) is not dict or set(receipt) != {
        "schema_version", "subject", "verification", "result_rows"
    }:
        fail("Codex provenance receipt schema or root shape changed")
    if receipt["schema_version"] != CODEX_PROVENANCE_RECEIPT_SCHEMA:
        fail("Codex provenance receipt schema changed")

    expected_subject = {
        "path": "deploy/manifests/codex-0.153.4.json",
        "schema_version": "deeptwin-managed-runner-build-input-v3",
        "bytes": codex_manifest_ref.get("bytes"),
        "sha256": codex_manifest_ref.get("sha256"),
    }
    if not _json_exactly_equal(receipt["subject"], expected_subject):
        fail("Codex provenance receipt subject reference is stale or malformed")

    verifier_path = _validate_relative_path(
        root,
        "deploy/locks/verify_codex_runner.py",
        "Codex provenance receipt verifier",
    )
    verification = receipt["verification"]
    verification_keys = {
        "verifier", "execution_platform", "execution_mode",
        "verified_target_platforms", "result", "native_linux_verifier_executed",
        "runner_report", "limits",
    }
    if type(verification) is not dict or set(verification) != verification_keys:
        fail("Codex provenance receipt verification shape changed")
    expected_verifier = {
        "path": "deploy/locks/verify_codex_runner.py",
        "bytes": verifier_path.stat().st_size,
        "sha256": sha256_file(verifier_path),
    }
    if not _json_exactly_equal(verification["verifier"], expected_verifier):
        fail("Codex provenance receipt verifier binding changed")
    if verification["verified_target_platforms"] != PLATFORMS:
        fail("Codex provenance receipt target-platform coverage changed")

    receipt_result = verification["result"]
    if receipt_result == "recorded_not_replayable":
        expected_recorded = {
            "execution_platform": "darwin/arm64",
            "execution_mode": "historical-audit-observation",
            "native_linux_verifier_executed": False,
            "runner_report": None,
            "limits": list(CODEX_PROVENANCE_RECORDED_LIMITS),
        }
        if any(
            not _json_exactly_equal(verification[key], expected)
            for key, expected in expected_recorded.items()
        ):
            fail("Codex recorded provenance boundary changed")
    elif receipt_result == "pass":
        execution_platform = verification["execution_platform"]
        if (
            execution_platform not in {*PLATFORMS, "darwin/arm64"}
            or verification["execution_mode"]
            != "artifact-backed-offline-verification"
            or type(verification["native_linux_verifier_executed"]) is not bool
            or verification["native_linux_verifier_executed"]
            != (execution_platform in PLATFORMS)
            or verification["limits"] != list(CODEX_PROVENANCE_RECEIPT_LIMITS)
        ):
            fail("Codex artifact-backed provenance boundary changed")
        report = verification["runner_report"]
        expected_report = _expected_codex_runner_report(
            codex, execution_platform=execution_platform
        )
        if not _json_exactly_equal(report, expected_report):
            fail(
                "Codex artifact-backed runner report is not the exact complete "
                "verifier replay report"
            )
    else:
        fail("Codex provenance receipt result enum changed")

    rows = receipt["result_rows"]
    if type(rows) is not list or not rows or len(rows) > 64:
        fail("Codex provenance receipt result row inventory is not bounded")
    row_ids: list[str] = []
    for row in rows:
        if type(row) is not dict or set(row) != {
            "id", "category", "platform", "result", "evidence"
        }:
            fail("Codex provenance receipt result row inventory changed")
        identity = row["id"]
        if type(identity) is not str or re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", identity
        ) is None:
            fail("Codex provenance receipt result row ID is not stable")
        if identity in row_ids:
            fail(f"Codex provenance receipt duplicate result row: {identity}")
        row_ids.append(identity)
        if row["result"] == "pass" and (
            type(row["evidence"]) is not list or not row["evidence"]
        ):
            fail(f"Codex provenance receipt success without evidence: {identity}")
    expected_rows = _expected_codex_provenance_rows(codex, result=receipt_result)
    if set(row_ids) != {row["id"] for row in expected_rows}:
        fail("Codex provenance receipt result row inventory changed")
    if row_ids != sorted(row_ids):
        fail("Codex provenance receipt result rows are not canonically sorted")
    if not _json_exactly_equal(rows, expected_rows):
        fail("Codex provenance receipt result row inventory changed")

    categories = Counter(row["category"] for row in rows)
    return {
        "result": receipt_result,
        "result_row_count": len(rows),
        "category_counts": dict(sorted(categories.items())),
    }


def _verify_child_tree(
    value: Any,
    *,
    label: str,
    known_repository_refs: set[str],
    allowed_absolute_values: set[str],
) -> None:
    if type(value) is list:
        for index, item in enumerate(value):
            _verify_child_tree(
                item,
                label=f"{label}[{index}]",
                known_repository_refs=known_repository_refs,
                allowed_absolute_values=allowed_absolute_values,
            )
        return
    if type(value) is not dict:
        return
    for key, item in value.items():
        location = f"{label}.{key}"
        if key in CHILD_FORBIDDEN_DISTRIBUTION_FIELDS:
            fail(f"{location}: T081 final-distribution field is forbidden in a T089 child")
        if type(item) is str:
            if item.startswith("/") and item not in allowed_absolute_values:
                fail(f"{location}: undeclared absolute path is forbidden")
            repository_prefixes = (
                "deploy/", "specs/", "app/", "packaging/", "docs/", "schemas/", "evals/"
            )
            if item.startswith(repository_prefixes):
                repository_path = item.split("#", 1)[0]
                if repository_path not in known_repository_refs:
                    fail(f"{location}: repository-local value is absent from exact aggregate refs")
        if type(item) is str and (key == "path" or key.endswith("_path")):
            if item in allowed_absolute_values:
                continue
            if (
                "\\" in item
                or "\x00" in item
                or re.match(r"^[A-Za-z]:/", item)
                or item.startswith(("file:", "repository:"))
            ):
                fail(f"{location}: noncanonical path-like value")
            pure = PurePosixPath(item)
            if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
                fail(f"{location}: absolute, traversal or noncanonical path-like value")
            if pure.as_posix() != item:
                fail(f"{location}: noncanonical path-like value")
            repository_candidate = item.split("#", 1)[0] in known_repository_refs
            looks_repository_local = item.startswith(
                ("deploy/", "specs/", "app/", "packaging/", "docs/", "schemas/", "evals/")
            )
            if looks_repository_local and not repository_candidate:
                fail(f"{location}: repository-local path is absent from exact aggregate refs")
        _verify_child_tree(
            item,
            label=location,
            known_repository_refs=known_repository_refs,
            allowed_absolute_values=allowed_absolute_values,
        )


def _pointer_count(manifests: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    python = manifests["python_wheel_artifacts"]
    browser = manifests["browser_worker"]
    debian = manifests["browser_debian_runtime"]
    sources = manifests["browser_debian_sources"]
    codex = manifests["codex_managed_runner"]
    codex_rust = manifests["codex_rust_dependencies"]
    age = manifests["age_tool"]
    age_licenses = manifests["age_runtime_licenses"]
    codex_platform_inputs = codex["platform_inputs"]
    codex_component_count = sum(
        len(item["components"]) for item in codex_platform_inputs
    )
    first_runtime = codex_platform_inputs[0]["runtime_image"]
    first_bash = first_runtime["bash"]
    if any(
        not _json_exactly_equal(item["runtime_image"]["index"], first_runtime["index"])
        for item in codex_platform_inputs[1:]
    ):
        fail("Codex platform inputs do not share one common OCI index")
    if any(
        not _json_exactly_equal(
            item["runtime_image"]["bash"]["license_member"],
            first_bash["license_member"],
        )
        for item in codex_platform_inputs[1:]
    ):
        fail("Codex platform inputs do not share one Bash copyright artifact")
    if any(
        not _json_exactly_equal(
            item["runtime_image"]["bash"]["source_inputs"],
            first_bash["source_inputs"],
        )
        for item in codex_platform_inputs[1:]
    ):
        fail("Codex platform inputs do not share one Bash source input set")
    bootstrap = codex["signature_policy"]["verifier_bootstrap"]
    return [
        {"category": "age-archive-members", "manifest_ref": "age_tool", "json_pointer": "/platform_archives/*/copied_members", "count": sum(len(item["copied_members"]) for item in age["platform_archives"])},
        {"category": "age-license-components", "manifest_ref": "age_runtime_licenses", "json_pointer": "/components", "count": len(age_licenses["components"])},
        {"category": "age-license-files", "manifest_ref": "age_runtime_licenses", "json_pointer": "/license_files", "count": len(age_licenses["license_files"])},
        {"category": "age-platform-archives", "manifest_ref": "age_tool", "json_pointer": "/platform_archives", "count": len(age["platform_archives"])},
        {"category": "chromium-platform-assets", "manifest_ref": "browser_worker", "json_pointer": "/chromium_headless_shell/assets", "count": len(browser["chromium_headless_shell"]["assets"])},
        {"category": "codex-bash-binary-packages", "manifest_ref": "codex_managed_runner", "json_pointer": "/platform_inputs/*/runtime_image/bash/binary_package", "count": len(codex_platform_inputs)},
        {"category": "codex-bash-copyright-artifacts", "manifest_ref": "codex_managed_runner", "json_pointer": "/platform_inputs/*/runtime_image/bash/license_member", "count": 1, "usage_count": len(codex_platform_inputs)},
        {"category": "codex-bash-installed-executables", "manifest_ref": "codex_managed_runner", "json_pointer": "/platform_inputs/*/runtime_image/bash/package_member", "count": len(codex_platform_inputs)},
        {"category": "codex-bash-source-files", "manifest_ref": "codex_managed_runner", "json_pointer": "/platform_inputs/*/runtime_image/bash/source_inputs", "count": len(first_bash["source_inputs"]), "usage_count": len(first_bash["source_inputs"]) * len(codex_platform_inputs)},
        {"category": "codex-bookworm-oci-configs", "manifest_ref": "codex_managed_runner", "json_pointer": "/platform_inputs/*/runtime_image/config", "count": len(codex_platform_inputs)},
        {"category": "codex-bookworm-oci-index", "manifest_ref": "codex_managed_runner", "json_pointer": "/platform_inputs/*/runtime_image/index", "count": 1, "usage_count": len(codex_platform_inputs)},
        {"category": "codex-bookworm-oci-layers", "manifest_ref": "codex_managed_runner", "json_pointer": "/platform_inputs/*/runtime_image/layers", "count": sum(len(item["runtime_image"]["layers"]) for item in codex_platform_inputs)},
        {"category": "codex-bookworm-oci-manifests", "manifest_ref": "codex_managed_runner", "json_pointer": "/platform_inputs/*/runtime_image/manifest", "count": len(codex_platform_inputs)},
        {"category": "codex-cosign-audit-verifier-inputs", "manifest_ref": "codex_managed_runner", "json_pointer": "/signature_policy/verifier_bootstrap/audit_observations/*", "count": 2},
        {"category": "codex-cosign-checksum-inputs", "manifest_ref": "codex_managed_runner", "json_pointer": "/signature_policy/verifier_bootstrap/checksum_manifest", "count": 2},
        {"category": "codex-cosign-release-verifier-inputs", "manifest_ref": "codex_managed_runner", "json_pointer": "/signature_policy/verifier_bootstrap/release_build_verifiers/*", "count": 2 * len(bootstrap["release_build_verifiers"])},
        {"category": "codex-executable-sigstore-bundles", "manifest_ref": "codex_managed_runner", "json_pointer": "/platform_inputs/*/components/*/sigstore_bundle", "count": codex_component_count},
        {"category": "codex-platform-inputs", "manifest_ref": "codex_managed_runner", "json_pointer": "/platform_inputs", "count": len(codex_platform_inputs)},
        {"category": "codex-rust-dependency-packages", "manifest_ref": "codex_rust_dependencies", "json_pointer": "/packages", "count": len(codex_rust["packages"])},
        {"category": "codex-standalone-archives", "manifest_ref": "codex_managed_runner", "json_pointer": "/platform_inputs/*/components/*/archive", "count": codex_component_count},
        {"category": "codex-standalone-executables", "manifest_ref": "codex_managed_runner", "json_pointer": "/platform_inputs/*/components/*/executable", "count": codex_component_count},
        {"category": "debian-binary-packages", "manifest_ref": "browser_debian_runtime", "json_pointer": "/closure/packages", "count": len(debian["closure"]["packages"])},
        {"category": "debian-install-delta-artifacts", "manifest_ref": "browser_debian_runtime", "json_pointer": "/platforms/*/install_delta/packages", "count": sum(len(item["install_delta"]["packages"]) for item in debian["platforms"].values())},
        {"category": "debian-source-packages", "manifest_ref": "browser_debian_sources", "json_pointer": "/sources", "count": len(sources["sources"])},
        {"category": "node-platform-archives", "manifest_ref": "browser_worker", "json_pointer": "/node/official_release_provenance/platforms", "count": len(browser["node"]["official_release_provenance"]["platforms"])},
        {"category": "playwright-npm-packages", "manifest_ref": "browser_worker", "json_pointer": "/playwright_core", "count": 1},
        {"category": "python-service-locks", "manifest_ref": "python_wheel_artifacts", "json_pointer": "/service_locks", "count": len(python["service_locks"])},
        {"category": "python-wheel-artifacts", "manifest_ref": "python_wheel_artifacts", "json_pointer": "/artifacts", "count": len(python["artifacts"]), "usage_count": sum(len(item["usage"]) for item in python["artifacts"])},
        {"category": "speech-model-files", "manifest_ref": "speech_model", "json_pointer": "/files", "count": len(manifests["speech_model"]["files"])},
        {"category": "upstream-multiarch-images", "manifest_ref": "upstream_images", "json_pointer": "/images", "count": len(manifests["upstream_images"]["images"])},
        {"category": "upstream-provenance-artifacts", "manifest_ref": "upstream_images", "json_pointer": "/images/*/provenance_descriptors/*/artifacts", "count": sum(len(descriptor["artifacts"]) for image in manifests["upstream_images"]["images"] for descriptor in image["provenance_descriptors"])},
        {"category": "upstream-provenance-manifests", "manifest_ref": "upstream_images", "json_pointer": "/images/*/provenance_descriptors", "count": sum(len(image["provenance_descriptors"]) for image in manifests["upstream_images"]["images"])},
    ]


def _require_nonempty_artifact_counts(values: list[dict[str, Any]]) -> None:
    for item in values:
        if type(item.get("count")) is not int or item["count"] <= 0:
            fail(f"aggregate artifact category {item.get('category')} must be nonempty")
        if "usage_count" in item and (
            type(item["usage_count"]) is not int or item["usage_count"] <= 0
        ):
            fail(f"aggregate artifact category {item.get('category')} has no usages")


def verify_aggregate(root: Path, *, require_locked: bool = False) -> dict[str, Any]:
    root = root.resolve(strict=True)
    path = _validate_relative_path(
        root,
        "deploy/manifests/build-input-lock.json",
        "aggregate build-input lock",
    )
    aggregate = load_strict_json(path)
    if set(aggregate) != EXPECTED_ROOT_KEYS:
        missing = sorted(EXPECTED_ROOT_KEYS - set(aggregate))
        extra = sorted(set(aggregate) - EXPECTED_ROOT_KEYS)
        fail(f"aggregate root shape changed; missing={missing}, extra={extra}")
    forbidden = FORBIDDEN_T081_FIELDS & set(aggregate)
    if forbidden:
        fail(f"T081 final-distribution fields are forbidden in T089: {sorted(forbidden)}")
    if aggregate["schema_version"] != "deeptwin-build-input-lock-manifest-v1":
        fail("aggregate schema version changed")
    if aggregate["scope"] != "t089-build-inputs-only":
        fail("aggregate scope must remain T089 build inputs only")
    if aggregate["status"] not in {"candidate_ready", "locked"}:
        fail("aggregate status must be candidate_ready or locked")
    if require_locked and aggregate["status"] != "locked":
        fail("T089 aggregate is not locked")
    if type(aggregate["generated_at"]) is not str or not UTC_SECOND.fullmatch(aggregate["generated_at"]):
        fail("generated_at must be a second-precision UTC timestamp")
    try:
        datetime.strptime(aggregate["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        fail("generated_at is not a real UTC calendar timestamp")
    if aggregate["digest_profile"] != "deeptwin-adr008-canonical-json-v1" or aggregate["digest_algorithm"] != "sha256":
        fail("aggregate canonical digest profile changed")
    expected_digest = seal_manifest(aggregate)["build_input_lock_set_digest"]
    if aggregate["build_input_lock_set_digest"] != expected_digest:
        fail("aggregate build_input_lock_set_digest mismatch")
    if path.read_bytes() != canonical_bytes(aggregate):
        fail("aggregate file itself must use exact ADR-008 canonical JSON bytes")

    manifest_refs = _index_refs(aggregate["manifest_refs"], "manifest_refs", "id")
    if set(manifest_refs) != set(EXPECTED_MANIFESTS):
        fail("aggregate manifest reference set is incomplete or contains extras")
    manifests: dict[str, dict[str, Any]] = {}
    for identity, (relative, schema, role) in EXPECTED_MANIFESTS.items():
        manifests[identity] = _verify_ref(
            root,
            manifest_refs[identity],
            relative,
            role,
            schema=schema,
            max_total_items=EXPECTED_CHILD_MAX_TOTAL_ITEMS.get(identity, MAX_ITEMS),
        )

    file_refs = _index_refs(aggregate["file_refs"], "file_refs", "path")
    if set(file_refs) != set(EXPECTED_FILES):
        fail("aggregate leaf file reference set is incomplete or contains extras")
    for relative, role in EXPECTED_FILES.items():
        _verify_ref(root, file_refs[relative], relative, role)
    known_repository_refs = {
        relative for relative, _schema, _role in EXPECTED_MANIFESTS.values()
    } | set(EXPECTED_FILES)
    for identity, child in manifests.items():
        if set(child) != EXPECTED_CHILD_ROOT_KEYS[identity]:
            fail(f"{identity}: child root shape changed")
        expected_status = EXPECTED_CHILD_STATUSES.get(identity)
        if expected_status is not None and child.get("status") != expected_status:
            fail(f"{identity}: child status is outside its exact non-release enum")
        _verify_child_tree(
            child,
            label=identity,
            known_repository_refs=known_repository_refs,
            allowed_absolute_values=(
                CODEX_ALLOWED_RUNTIME_ABSOLUTE_VALUES
                if identity == "codex_managed_runner"
                else DEFAULT_ALLOWED_RUNTIME_ABSOLUTE_VALUES
            ),
        )

    verify_codex_t089_candidate_state(
        root,
        manifests["codex_managed_runner"],
        locked=aggregate["status"] == "locked",
    )
    verify_codex_rust_candidate_state(
        root,
        manifests["codex_rust_dependencies"],
    )
    receipt_summary = verify_codex_provenance_receipt(
        root,
        receipt_path=_validate_relative_path(
            root,
            CODEX_PROVENANCE_RECEIPT_PATH,
            CODEX_PROVENANCE_RECEIPT_PATH,
        ),
        codex_manifest_ref=manifest_refs["codex_managed_runner"],
        codex=manifests["codex_managed_runner"],
    )
    if aggregate["status"] == "locked" and receipt_summary["result"] != "pass":
        fail(
            "locked T089 aggregate requires an exact artifact-backed Codex "
            "verifier replay PASS receipt"
        )

    if aggregate["target_platforms"] != PLATFORMS:
        fail("aggregate target platform set/order changed")
    if not _json_exactly_equal(
        aggregate["runtime_mutation_policy"], CODEX_RUNTIME_MUTATION_POLICY
    ):
        fail("runtime mutation policy must deny every listed download/install path")
    if manifests["speech_model"].get("download_at_runtime") is not False:
        fail("speech model manifest permits runtime download")
    if manifests["service_python_roots"].get("target_platforms") != PLATFORMS:
        fail("service roots disagree with aggregate target platforms")
    if not _json_exactly_equal(aggregate["glibc_floor"], EXPECTED_GLIBC_FLOORS):
        fail("glibc floors must keep Python artifact and Bookworm runtime constraints separate")

    expected_resolvers = [
        {"name": "cosign", "version": "3.1.2"},
        {"name": "gpgv", "version": "2.2.40-1.1+deb12u2"},
        {"name": "npm", "version": "12.0.2"},
        {"name": "pip", "version": "26.2.1"},
        {"name": "sigsum-verify", "version": "0.13.1"},
    ]
    if not _json_exactly_equal(aggregate["resolver_versions"], expected_resolvers):
        fail("resolver/verifier version set changed")
    if not _json_exactly_equal(aggregate["runtime_abis"], EXPECTED_RUNTIME_ABIS):
        fail("runtime ABI set changed")

    expected_artifacts = _pointer_count(manifests)
    if not _json_exactly_equal(aggregate["artifacts"], expected_artifacts):
        fail("aggregate artifact pointer/count closure changed")
    _require_nonempty_artifact_counts(expected_artifacts)

    expected_images = [
        {"image_id": image["image_id"], "json_pointer": f"/images/{index}", "manifest_ref": "upstream_images"}
        for index, image in enumerate(manifests["upstream_images"]["images"])
    ]
    if not _json_exactly_equal(aggregate["upstream_image_locks"], expected_images):
        fail("aggregate upstream image pointer set changed")
    if any(len(image.get("platforms", [])) != 2 for image in manifests["upstream_images"]["images"]):
        fail("upstream image lock lost dual-platform closure")

    expected_components = [
        {"component": "age", "json_pointer": "/platform_archives", "manifest_ref": "age_tool"},
        {"component": "browser-runtime", "json_pointer": "/closure", "manifest_ref": "browser_debian_runtime"},
        {"component": "codex-managed-runner", "json_pointer": "/platform_inputs", "manifest_ref": "codex_managed_runner"},
        {"component": "codex-rust-dependencies", "json_pointer": "/packages", "manifest_ref": "codex_rust_dependencies"},
        {"component": "node-playwright-chromium", "json_pointer": "/", "manifest_ref": "browser_worker"},
        {"component": "python-services", "json_pointer": "/services", "manifest_ref": "service_python_roots"},
        {"component": "speech-model", "json_pointer": "/files", "manifest_ref": "speech_model"},
    ]
    if not _json_exactly_equal(aggregate["model_component_locks"], expected_components):
        fail("aggregate model/component lock pointer set changed")

    expected_licenses = [
        {"kind": "age-license-bundle", "json_pointer": "/", "manifest_ref": "age_runtime_licenses"},
        {"kind": "age-sigsum-provenance", "json_pointer": "/sigsum_policy", "manifest_ref": "age_tool"},
        {"kind": "chromium-license", "json_pointer": "/chromium_headless_shell/license_headless_shell", "manifest_ref": "browser_worker"},
        {"kind": "codex-bookworm-runtime-provenance-inputs", "json_pointer": "/platform_inputs/*/runtime_image", "manifest_ref": "codex_managed_runner"},
        {"kind": "codex-executable-signature-provenance", "json_pointer": "/signature_policy", "manifest_ref": "codex_managed_runner"},
        {"kind": "codex-rust-license-provenance-inputs", "json_pointer": "/packages", "manifest_ref": "codex_rust_dependencies"},
        {"kind": "debian-source-license-evidence", "json_pointer": "/", "manifest_ref": "browser_debian_sources"},
        {"kind": "node-license-provenance", "json_pointer": "/node/official_release_provenance", "manifest_ref": "browser_worker"},
        {"kind": "playwright-license-provenance", "json_pointer": "/playwright_core/npm_attestations", "manifest_ref": "browser_worker"},
        {"kind": "python-license-inputs", "json_pointer": "/legal_gate", "manifest_ref": "python_wheel_artifacts"},
        {"kind": "speech-license-inputs", "json_pointer": "/license_inputs", "manifest_ref": "speech_model"},
        {"kind": "upstream-image-provenance", "json_pointer": "/images/*/provenance_descriptors", "manifest_ref": "upstream_images"},
    ]
    if not _json_exactly_equal(aggregate["license_provenance_refs"], expected_licenses):
        fail("aggregate license/provenance pointer set changed")

    expected_verification = [
        {"file_ref": path, "role": role}
        for path, role in sorted(EXPECTED_FILES.items())
        if any(token in role for token in ("verifier", "test", "canary", "result evidence"))
    ]
    if not _json_exactly_equal(aggregate["verification_refs"], expected_verification):
        fail("aggregate verification reference set changed")

    gates = aggregate["gates"]
    if type(gates) is not dict or set(gates) != {"build_input_lock", "downstream_release"}:
        fail("aggregate gate classes changed")
    build_gates = gates["build_input_lock"]
    downstream = gates["downstream_release"]
    if type(build_gates) is not list or not build_gates or type(downstream) is not list or not downstream:
        fail("aggregate gate lists must be nonempty")
    if any(type(item) is not dict for item in build_gates):
        fail("aggregate T089 gates must use structured records")
    if [item.get("id") for item in build_gates] != EXPECTED_BUILD_GATES:
        fail("T089 gate ID set/order changed")
    if any(
        set(item) != {
            "blocking_for_build_input_lock",
            "id",
            "gate_id",
            "owner_task",
            "status",
            "summary",
        }
        for item in build_gates
    ):
        fail("T089 gate shape changed")
    if any(
        item["owner_task"] != "T089"
        or item["gate_id"] != f"t089-{item['id']}"
        or item["summary"] != EXPECTED_BUILD_GATE_SUMMARIES[item["id"]]
        or item["blocking_for_build_input_lock"] is not True
        for item in build_gates
    ):
        fail("T089 gate ownership changed")
    if any(item["status"] not in {"open", "pass"} for item in build_gates):
        fail("T089 gate status must be open or pass")
    expected_build_statuses = dict(CANDIDATE_BUILD_GATE_STATUSES)
    if receipt_summary["result"] == "pass":
        expected_build_statuses["provenance-receipt-capture"] = "pass"
    if aggregate["status"] == "locked":
        expected_build_statuses = {
            gate_id: "pass" for gate_id in EXPECTED_BUILD_GATES
        }
    if {item["id"]: item["status"] for item in build_gates} != expected_build_statuses:
        fail("T089 gate statuses do not match the aggregate lifecycle state")
    if any(type(item) is not dict for item in downstream):
        fail("aggregate downstream gates must use structured records")
    expected_downstream = _aggregate_downstream_gate_records(
        manifests["codex_managed_runner"]
    )
    if not _json_exactly_equal(downstream, expected_downstream):
        fail(
            "downstream gate stable IDs, ownership, mapping, or open status changed"
        )

    # Candidate and locked aggregates both claim an internally coherent input snapshot. Only
    # readiness differs, so both must survive the same component-structure verifier.
    component_path = root / "deploy" / "locks" / "verify_build_inputs.py"
    spec = importlib.util.spec_from_file_location(
        "deeptwin_component_build_input_verifier", component_path
    )
    if spec is None or spec.loader is None:
        fail("component build-input verifier could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    try:
        module.verify_repository(
            root,
            require_release_ready=False,
            verify_aggregate_lock=False,
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        fail(f"component build-input verification failed: {exc}")

    return aggregate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--require-locked", action="store_true")
    args = parser.parse_args()
    aggregate = verify_aggregate(args.root, require_locked=args.require_locked)
    print(
        "build-input aggregate: verified "
        f"status={aggregate['status']} digest={aggregate['build_input_lock_set_digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
