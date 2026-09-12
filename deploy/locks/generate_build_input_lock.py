#!/usr/bin/env python3
"""Materialize DeepTwin's deterministic T089 aggregate build-input lock."""

from __future__ import annotations

import argparse
import tempfile
from datetime import datetime
from pathlib import Path

import verify_build_inputs as component_verifier
from verify_build_input_lock import (
    CANDIDATE_BUILD_GATE_STATUSES,
    CODEX_PROVENANCE_RECEIPT_PATH,
    EXPECTED_BUILD_GATE_SUMMARIES,
    EXPECTED_BUILD_GATES,
    EXPECTED_CHILD_MAX_TOTAL_ITEMS,
    EXPECTED_FILES,
    EXPECTED_GLIBC_FLOORS,
    EXPECTED_MANIFESTS,
    EXPECTED_RUNTIME_ABIS,
    MAX_ITEMS,
    PLATFORMS,
    UTC_SECOND,
    _aggregate_downstream_gate_records,
    _pointer_count,
    _validate_relative_path,
    canonical_bytes,
    load_strict_json,
    seal_manifest,
    sha256_file,
    verify_aggregate,
    verify_codex_provenance_receipt,
    verify_codex_rust_candidate_state,
    verify_codex_t089_candidate_state,
)


def _manifest_ref(root: Path, identity: str) -> tuple[dict[str, object], dict[str, object]]:
    relative, schema, role = EXPECTED_MANIFESTS[identity]
    path = _validate_relative_path(root, relative, relative)
    value = load_strict_json(
        path,
        max_total_items=EXPECTED_CHILD_MAX_TOTAL_ITEMS.get(identity, MAX_ITEMS),
    )
    if value.get("schema_version") != schema:
        raise ValueError(f"{relative}: expected schema {schema}")
    return (
        {
            "bytes": path.stat().st_size,
            "id": identity,
            "path": relative,
            "role": role,
            "schema_version": schema,
            "sha256": sha256_file(path),
        },
        value,
    )


def build_manifest(root: Path, *, generated_at: str, locked: bool) -> dict[str, object]:
    root = root.resolve(strict=True)
    if not UTC_SECOND.fullmatch(generated_at):
        raise ValueError("generated_at must be a second-precision UTC timestamp")
    # This also rejects calendar-invalid timestamps while keeping the serialized form exact.
    datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ")
    # Candidate and locked manifests both describe a coherent input snapshot.  Candidate means
    # readiness is still open, not that malformed component manifests may be recorded.
    component_verifier.verify_repository(
        root,
        require_release_ready=False,
        verify_aggregate_lock=False,
    )

    manifest_refs: list[dict[str, object]] = []
    manifests: dict[str, dict[str, object]] = {}
    for identity in sorted(EXPECTED_MANIFESTS):
        reference, value = _manifest_ref(root, identity)
        manifest_refs.append(reference)
        manifests[identity] = value

    verify_codex_t089_candidate_state(
        root,
        manifests["codex_managed_runner"],
        locked=locked,
    )
    verify_codex_rust_candidate_state(
        root,
        manifests["codex_rust_dependencies"],
    )

    file_refs: list[dict[str, object]] = []
    for relative, role in sorted(EXPECTED_FILES.items()):
        path = _validate_relative_path(root, relative, relative)
        file_refs.append(
            {
                "bytes": path.stat().st_size,
                "path": relative,
                "role": role,
                "sha256": sha256_file(path),
            }
        )

    codex_manifest_ref = next(
        reference
        for reference in manifest_refs
        if reference["id"] == "codex_managed_runner"
    )
    receipt_summary = verify_codex_provenance_receipt(
        root,
        receipt_path=_validate_relative_path(
            root,
            CODEX_PROVENANCE_RECEIPT_PATH,
            CODEX_PROVENANCE_RECEIPT_PATH,
        ),
        codex_manifest_ref=codex_manifest_ref,
        codex=manifests["codex_managed_runner"],
    )
    if locked and receipt_summary["result"] != "pass":
        raise ValueError(
            "locked T089 aggregate requires an exact artifact-backed Codex "
            "verifier replay PASS receipt"
        )

    upstream_images = [
        {
            "image_id": image["image_id"],
            "json_pointer": f"/images/{index}",
            "manifest_ref": "upstream_images",
        }
        for index, image in enumerate(manifests["upstream_images"]["images"])
    ]
    components = [
        {"component": "age", "json_pointer": "/platform_archives", "manifest_ref": "age_tool"},
        {"component": "browser-runtime", "json_pointer": "/closure", "manifest_ref": "browser_debian_runtime"},
        {"component": "codex-managed-runner", "json_pointer": "/platform_inputs", "manifest_ref": "codex_managed_runner"},
        {"component": "codex-rust-dependencies", "json_pointer": "/packages", "manifest_ref": "codex_rust_dependencies"},
        {"component": "node-playwright-chromium", "json_pointer": "/", "manifest_ref": "browser_worker"},
        {"component": "python-services", "json_pointer": "/services", "manifest_ref": "service_python_roots"},
        {"component": "speech-model", "json_pointer": "/files", "manifest_ref": "speech_model"},
    ]
    licenses = [
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
    verification_refs = [
        {"file_ref": path, "role": role}
        for path, role in sorted(EXPECTED_FILES.items())
        if any(token in role for token in ("verifier", "test", "canary", "result evidence"))
    ]
    build_gates = [
        {
            "blocking_for_build_input_lock": True,
            "id": identity,
            "gate_id": f"t089-{identity}",
            "owner_task": "T089",
            "status": (
                "pass"
                if locked
                else (
                    "pass"
                    if identity == "provenance-receipt-capture"
                    and receipt_summary["result"] == "pass"
                    else CANDIDATE_BUILD_GATE_STATUSES[identity]
                )
            ),
            "summary": EXPECTED_BUILD_GATE_SUMMARIES[identity],
        }
        for identity in EXPECTED_BUILD_GATES
    ]
    downstream = _aggregate_downstream_gate_records(
        manifests["codex_managed_runner"]
    )

    value: dict[str, object] = {
        "artifacts": _pointer_count(manifests),
        "digest_algorithm": "sha256",
        "digest_profile": "deeptwin-adr008-canonical-json-v1",
        "file_refs": file_refs,
        "gates": {"build_input_lock": build_gates, "downstream_release": downstream},
        "generated_at": generated_at,
        "glibc_floor": EXPECTED_GLIBC_FLOORS,
        "license_provenance_refs": licenses,
        "manifest_refs": manifest_refs,
        "model_component_locks": components,
        "resolver_versions": [
            {"name": "cosign", "version": "3.1.2"},
            {"name": "gpgv", "version": "2.2.40-1.1+deb12u2"},
            {"name": "npm", "version": "12.0.2"},
            {"name": "pip", "version": "26.2.1"},
            {"name": "sigsum-verify", "version": "0.13.1"},
        ],
        "runtime_abis": EXPECTED_RUNTIME_ABIS,
        "runtime_mutation_policy": {
            "browser_download_at_runtime": False,
            "model_download_at_runtime": False,
            "package_install_at_runtime": False,
            "package_resolution_at_runtime": False,
            "tool_download_at_runtime": False,
        },
        "schema_version": "deeptwin-build-input-lock-manifest-v1",
        "scope": "t089-build-inputs-only",
        "status": "locked" if locked else "candidate_ready",
        "target_platforms": PLATFORMS,
        "upstream_image_locks": upstream_images,
        "verification_refs": verification_refs,
    }
    return seal_manifest(value)


def write_manifest(root: Path, value: dict[str, object]) -> Path:
    output = root / "deploy" / "manifests" / "build-input-lock.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_bytes(value)
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".build-input-lock.", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
        stream.flush()
    temporary.chmod(0o644)
    temporary.replace(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--locked", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    expected_output = root / "deploy" / "manifests" / "build-input-lock.json"
    previous = expected_output.read_bytes() if expected_output.exists() else None
    try:
        value = build_manifest(root, generated_at=args.generated_at, locked=args.locked)
        output = write_manifest(root, value)
        verify_aggregate(root, require_locked=args.locked)
    except Exception:
        if previous is None:
            expected_output.unlink(missing_ok=True)
        else:
            with tempfile.NamedTemporaryFile(
                dir=expected_output.parent,
                prefix=".build-input-lock.rollback.",
                delete=False,
            ) as stream:
                rollback = Path(stream.name)
                stream.write(previous)
                stream.flush()
            rollback.chmod(0o644)
            rollback.replace(expected_output)
        raise
    print(f"wrote {output} digest={value['build_input_lock_set_digest']} status={value['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
