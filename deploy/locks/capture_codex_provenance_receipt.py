#!/usr/bin/env python3
"""Capture an artifact-backed Codex provenance receipt after real verification.

This command is intentionally separate from aggregate lock generation.  It
requires every exact runner artifact plus either a locked native Linux Cosign
binary or the explicitly audit-only locked Darwin verifier, runs
``verify_codex_runner.verify_minimal_runner`` first, and writes a new receipt
only after that verifier returns a complete report.  It never replaces an
existing receipt, and Darwin capture never claims native Linux execution.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import verify_build_input_lock as aggregate_verifier
import verify_codex_runner as runner_verifier


class CaptureError(ValueError):
    """Raised when a receipt cannot be captured without overstating evidence."""


def _host_platform() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    aliases = {
        ("Linux", "x86_64"): "linux/amd64",
        ("Linux", "amd64"): "linux/amd64",
        ("Linux", "aarch64"): "linux/arm64",
        ("Linux", "arm64"): "linux/arm64",
        ("Darwin", "arm64"): "darwin/arm64",
    }
    try:
        return aliases[(system, machine)]
    except KeyError as exc:
        raise CaptureError(f"unsupported verifier host: {system}/{machine}") from exc


def build_receipt(
    *,
    root: Path,
    manifest_path: Path,
    artifacts_directory: Path,
    cosign_path: Path,
) -> dict[str, Any]:
    """Run the real offline verifier, then construct its bounded receipt."""

    root = root.resolve(strict=True)
    expected_manifest = (
        root / "deploy" / "manifests" / "codex-0.153.4.json"
    ).resolve(strict=True)
    if manifest_path.resolve(strict=True) != expected_manifest:
        raise CaptureError("receipt subject must be the repository Codex v3 manifest")

    execution_platform = _host_platform()
    audit_mode = execution_platform == "darwin/arm64"
    report = runner_verifier.verify_minimal_runner(
        expected_manifest,
        artifacts_directory.resolve(strict=True),
        cosign_path.resolve(strict=True),
        locked=True,
        allow_audit_verifier=audit_mode,
    )
    cosign_report = report.get("cosign")
    if (
        type(cosign_report) is not dict
        or cosign_report.get("selected_verifier_platform") != execution_platform
        or cosign_report.get("selection_mode")
        != ("audit-only" if audit_mode else "release-build")
    ):
        raise CaptureError(
            "the selected Cosign artifact does not match the current verifier host/mode"
        )

    child = aggregate_verifier.load_strict_json(
        expected_manifest,
        max_total_items=aggregate_verifier.MAX_ITEMS,
    )
    expected_report = aggregate_verifier._expected_codex_runner_report(
        child, execution_platform=execution_platform
    )
    if not aggregate_verifier._json_exactly_equal(report, expected_report):
        raise CaptureError(
            "the verifier did not return the exact complete artifact-backed report"
        )
    verifier_path = root / "deploy" / "locks" / "verify_codex_runner.py"
    return {
        "schema_version": aggregate_verifier.CODEX_PROVENANCE_RECEIPT_SCHEMA,
        "subject": {
            "path": "deploy/manifests/codex-0.153.4.json",
            "schema_version": child["schema_version"],
            "bytes": expected_manifest.stat().st_size,
            "sha256": aggregate_verifier.sha256_file(expected_manifest),
        },
        "verification": {
            "verifier": {
                "path": "deploy/locks/verify_codex_runner.py",
                "bytes": verifier_path.stat().st_size,
                "sha256": aggregate_verifier.sha256_file(verifier_path),
            },
            "execution_platform": execution_platform,
            "execution_mode": "artifact-backed-offline-verification",
            "verified_target_platforms": list(aggregate_verifier.PLATFORMS),
            "result": "pass",
            "native_linux_verifier_executed": not audit_mode,
            "runner_report": report,
            "limits": list(aggregate_verifier.CODEX_PROVENANCE_RECEIPT_LIMITS),
        },
        "result_rows": aggregate_verifier._expected_codex_provenance_rows(child),
    }


def write_new_receipt(*, root: Path, output: Path, receipt: dict[str, Any]) -> Path:
    """Validate and atomically install a new receipt without overwriting evidence."""

    output = output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise CaptureError("receipt output already exists; capture is create-only")
    payload = aggregate_verifier.canonical_bytes(receipt)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent,
            prefix=".codex-provenance-capture.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o644)
        child_path = root / "deploy" / "manifests" / "codex-0.153.4.json"
        child = aggregate_verifier.load_strict_json(
            child_path,
            max_total_items=aggregate_verifier.MAX_ITEMS,
        )
        aggregate_verifier.verify_codex_provenance_receipt(
            root,
            receipt_path=temporary,
            codex_manifest_ref={
                "bytes": child_path.stat().st_size,
                "sha256": aggregate_verifier.sha256_file(child_path),
            },
            codex=child,
        )
        os.link(temporary, output)
    except FileExistsError as exc:
        raise CaptureError("receipt output already exists; capture is create-only") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root_default = Path(__file__).resolve().parents[2]
    parser.add_argument("--root", type=Path, default=root_default)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifacts-directory", type=Path, required=True)
    parser.add_argument("--cosign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        receipt = build_receipt(
            root=root,
            manifest_path=args.manifest,
            artifacts_directory=args.artifacts_directory,
            cosign_path=args.cosign,
        )
        output = write_new_receipt(root=root, output=args.output, receipt=receipt)
    except (CaptureError, OSError, runner_verifier.VerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"wrote artifact-backed PASS receipt {output} "
        f"sha256={aggregate_verifier.sha256_file(output)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
