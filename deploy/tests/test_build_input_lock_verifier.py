from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCKS = REPOSITORY_ROOT / "deploy" / "locks"
sys.path.insert(0, str(LOCKS))

VERIFY_SPEC = importlib.util.spec_from_file_location(
    "deeptwin_build_input_lock_verifier", LOCKS / "verify_build_input_lock.py"
)
assert VERIFY_SPEC is not None and VERIFY_SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFIER)

GENERATOR_SPEC = importlib.util.spec_from_file_location(
    "deeptwin_build_input_lock_generator", LOCKS / "generate_build_input_lock.py"
)
assert GENERATOR_SPEC is not None and GENERATOR_SPEC.loader is not None
GENERATOR = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(GENERATOR)

CAPTURE_SPEC = importlib.util.spec_from_file_location(
    "deeptwin_codex_provenance_capture",
    LOCKS / "capture_codex_provenance_receipt.py",
)
assert CAPTURE_SPEC is not None and CAPTURE_SPEC.loader is not None
CAPTURE = importlib.util.module_from_spec(CAPTURE_SPEC)
CAPTURE_SPEC.loader.exec_module(CAPTURE)


class AggregateBuildInputLockTests(unittest.TestCase):
    @staticmethod
    def v3_codex_child() -> dict[str, object]:
        path = REPOSITORY_ROOT / "deploy/manifests/codex-0.153.4.json"
        child = json.loads(path.read_text(encoding="utf-8"))
        if child.get("schema_version") != "deeptwin-managed-runner-build-input-v3":
            raise AssertionError("the receipt fixture requires the v3 child")
        return child

    @staticmethod
    def codex_receipt() -> dict[str, object]:
        path = REPOSITORY_ROOT / VERIFIER.CODEX_PROVENANCE_RECEIPT_PATH
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def codex_subject() -> dict[str, object]:
        path = REPOSITORY_ROOT / "deploy/manifests/codex-0.153.4.json"
        child = json.loads(path.read_text(encoding="utf-8"))
        return {
            "path": "deploy/manifests/codex-0.153.4.json",
            "schema_version": child["schema_version"],
            "bytes": path.stat().st_size,
            "sha256": VERIFIER.sha256_file(path),
        }

    def make_fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory(prefix="deeptwin-aggregate-lock-")
        root = Path(temporary.name)
        shutil.copytree(REPOSITORY_ROOT / "deploy", root / "deploy")
        for relative in sorted(VERIFIER.EXPECTED_FILES):
            if not relative.startswith("specs/"):
                continue
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPOSITORY_ROOT / relative, destination)
        return temporary, root

    @staticmethod
    def aggregate_path(root: Path) -> Path:
        return root / "deploy" / "manifests" / "build-input-lock.json"

    def read_aggregate(self, root: Path) -> dict[str, object]:
        return json.loads(self.aggregate_path(root).read_text(encoding="utf-8"))

    def write_aggregate(self, root: Path, value: dict[str, object], *, reseal: bool = True) -> None:
        payload = VERIFIER.seal_manifest(value) if reseal else value
        self.aggregate_path(root).write_bytes(VERIFIER.canonical_bytes(payload))

    def fixture_with_lock(self, *, locked: bool = False) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary, root = self.make_fixture()
        value = GENERATOR.build_manifest(
            root, generated_at="2026-09-08T03:30:00Z", locked=locked
        )
        GENERATOR.write_manifest(root, value)
        return temporary, root

    def test_repository_lock_is_exact(self) -> None:
        value = VERIFIER.verify_aggregate(REPOSITORY_ROOT, require_locked=False)
        self.assertEqual(value["scope"], "t089-build-inputs-only")
        self.assertIn(value["status"], {"candidate_ready", "locked"})

    def test_codex_provenance_receipt_accepts_bounded_artifact_backed_leaf(self) -> None:
        child = self.v3_codex_child()
        subject = self.codex_subject()
        with tempfile.TemporaryDirectory() as raw:
            receipt_path = Path(raw) / "codex-provenance-receipt.json"
            shutil.copy2(
                REPOSITORY_ROOT / VERIFIER.CODEX_PROVENANCE_RECEIPT_PATH,
                receipt_path,
            )
            result = VERIFIER.verify_codex_provenance_receipt(
                REPOSITORY_ROOT,
                receipt_path=receipt_path,
                codex_manifest_ref=subject,
                codex=child,
            )
        self.assertEqual(result["result"], "pass")
        self.assertEqual(result["result_row_count"], 26)
        categories = result["category_counts"]
        self.assertEqual(categories["openai-executable-sigstore"], 6)
        self.assertEqual(categories["oci-descriptor"], 7)
        self.assertEqual(categories["bash-input"], 8)

    def test_codex_provenance_receipt_rejects_stale_or_circular_subject(self) -> None:
        child = self.v3_codex_child()
        subject = self.codex_subject()
        for mutation, message in (
            (lambda receipt, _child: receipt["subject"].__setitem__("bytes", 1), "subject reference"),
            (lambda receipt, _child: receipt["subject"].__setitem__("sha256", "0" * 64), "subject reference"),
            (
                lambda _receipt, candidate: candidate["runtime_layout"].__setitem__(
                    "receipt_path", VERIFIER.CODEX_PROVENANCE_RECEIPT_PATH
                ),
                "back-reference",
            ),
        ):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as raw:
                candidate = copy.deepcopy(child)
                receipt = copy.deepcopy(self.codex_receipt())
                mutation(receipt, candidate)
                path = Path(raw) / "receipt.json"
                path.write_bytes(VERIFIER.canonical_bytes(receipt))
                with self.assertRaisesRegex(VERIFIER.LockVerificationError, message):
                    VERIFIER.verify_codex_provenance_receipt(
                        REPOSITORY_ROOT,
                        receipt_path=path,
                        codex_manifest_ref=subject,
                        codex=candidate,
                    )

    def test_codex_provenance_receipt_rows_are_fail_closed(self) -> None:
        child = self.v3_codex_child()
        subject = self.codex_subject()
        mutations = (
            (lambda rows: rows.pop(), "result row inventory"),
            (lambda rows: rows.append(copy.deepcopy(rows[0])), "duplicate result row"),
            (lambda rows: rows[0].__setitem__("result", "fail"), "result row inventory"),
            (lambda rows: rows[0].__setitem__("evidence", []), "success without evidence"),
            (lambda rows: rows[0].__setitem__("id", "unknown-check"), "result row inventory"),
        )
        for mutation, message in mutations:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as raw:
                receipt = copy.deepcopy(self.codex_receipt())
                mutation(receipt["result_rows"])
                path = Path(raw) / "receipt.json"
                path.write_bytes(VERIFIER.canonical_bytes(receipt))
                with self.assertRaisesRegex(VERIFIER.LockVerificationError, message):
                    VERIFIER.verify_codex_provenance_receipt(
                        REPOSITORY_ROOT,
                        receipt_path=path,
                        codex_manifest_ref=subject,
                        codex=child,
                    )

    def test_codex_provenance_receipt_runner_report_is_exact_and_complete(self) -> None:
        child = self.v3_codex_child()
        report = self.codex_receipt()["verification"]["runner_report"]
        expected = VERIFIER._expected_codex_runner_report(
            child, execution_platform="darwin/arm64"
        )
        self.assertEqual(report, expected)
        self.assertEqual(report["verified_input_file_count"], 17)
        self.assertEqual(len(report["verified_input_files"]), 17)
        self.assertEqual(
            [item["filename"] for item in report["verified_input_files"]],
            sorted(item["filename"] for item in report["verified_input_files"]),
        )
        outcomes = [
            component["sigstore_verified"]
            for platform in report["platforms"]
            for component in platform["components"]
        ]
        self.assertEqual(outcomes, [True] * 6)

    def test_codex_provenance_receipt_rejects_every_deleted_or_extra_report_field(
        self,
    ) -> None:
        child = self.v3_codex_child()
        subject = self.codex_subject()
        original = self.codex_receipt()
        report = original["verification"]["runner_report"]

        dict_paths: list[tuple[object, ...]] = []
        list_paths: list[tuple[object, ...]] = []

        def inventory(value: object, path: tuple[object, ...] = ()) -> None:
            if type(value) is dict:
                dict_paths.append(path)
                for key, item in value.items():
                    inventory(item, (*path, key))
            elif type(value) is list:
                list_paths.append(path)
                for index, item in enumerate(value):
                    inventory(item, (*path, index))

        def locate(value: object, path: tuple[object, ...]) -> object:
            current = value
            for step in path:
                current = current[step]  # type: ignore[index]
            return current

        def assert_rejected(mutated_report: dict[str, object], case: str) -> None:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as raw:
                receipt = copy.deepcopy(original)
                receipt["verification"]["runner_report"] = mutated_report
                path = Path(raw) / "receipt.json"
                path.write_bytes(VERIFIER.canonical_bytes(receipt))
                with self.assertRaisesRegex(
                    VERIFIER.LockVerificationError, "exact complete verifier replay"
                ):
                    VERIFIER.verify_codex_provenance_receipt(
                        REPOSITORY_ROOT,
                        receipt_path=path,
                        codex_manifest_ref=subject,
                        codex=child,
                    )

        inventory(report)
        for dict_path in dict_paths:
            source = locate(report, dict_path)
            self.assertIs(type(source), dict)
            for key in tuple(source):
                candidate = copy.deepcopy(report)
                target = locate(candidate, dict_path)
                del target[key]  # type: ignore[index]
                assert_rejected(candidate, f"deleted {dict_path!r}/{key}")
            candidate = copy.deepcopy(report)
            target = locate(candidate, dict_path)
            target["unexpected_report_field"] = "forbidden"  # type: ignore[index]
            assert_rejected(candidate, f"extra field at {dict_path!r}")

        for list_path in list_paths:
            source = locate(report, list_path)
            self.assertIs(type(source), list)
            for index in range(len(source)):
                candidate = copy.deepcopy(report)
                target = locate(candidate, list_path)
                target.pop(index)  # type: ignore[union-attr]
                assert_rejected(candidate, f"deleted {list_path!r}[{index}]")
            candidate = copy.deepcopy(report)
            target = locate(candidate, list_path)
            target.append(copy.deepcopy(source[0]) if source else "extra")  # type: ignore[union-attr,index]
            assert_rejected(candidate, f"extra list item at {list_path!r}")

    def test_codex_provenance_receipt_execution_boundary_is_fail_closed(self) -> None:
        child = self.v3_codex_child()
        subject = self.codex_subject()
        receipt = copy.deepcopy(self.codex_receipt())
        receipt["verification"]["native_linux_verifier_executed"] = True
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "receipt.json"
            path.write_bytes(VERIFIER.canonical_bytes(receipt))
            with self.assertRaisesRegex(
                VERIFIER.LockVerificationError, "provenance boundary"
            ):
                VERIFIER.verify_codex_provenance_receipt(
                    REPOSITORY_ROOT,
                    receipt_path=path,
                    codex_manifest_ref=subject,
                    codex=child,
                )

    def test_codex_provenance_receipt_rejects_unknown_schema_and_duplicate_json(self) -> None:
        child = self.v3_codex_child()
        subject = self.codex_subject()
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            receipt = copy.deepcopy(self.codex_receipt())
            receipt["schema_version"] = "unknown"
            path = directory / "unknown.json"
            path.write_bytes(VERIFIER.canonical_bytes(receipt))
            with self.assertRaisesRegex(VERIFIER.LockVerificationError, "schema"):
                VERIFIER.verify_codex_provenance_receipt(
                    REPOSITORY_ROOT,
                    receipt_path=path,
                    codex_manifest_ref=subject,
                    codex=child,
                )
            duplicate = directory / "duplicate.json"
            duplicate.write_text('{"schema_version":"x","schema_version":"y"}')
            with self.assertRaisesRegex(VERIFIER.LockVerificationError, "duplicate JSON"):
                VERIFIER.verify_codex_provenance_receipt(
                    REPOSITORY_ROOT,
                    receipt_path=duplicate,
                    codex_manifest_ref=subject,
                    codex=child,
                )

    def test_candidate_status_is_valid_but_not_locked(self) -> None:
        temporary, root = self.fixture_with_lock(locked=False)
        self.addCleanup(temporary.cleanup)
        value = VERIFIER.verify_aggregate(root, require_locked=False)
        observed = {
            item["id"]: item["status"] for item in value["gates"]["build_input_lock"]
        }
        expected = dict(VERIFIER.CANDIDATE_BUILD_GATE_STATUSES)
        expected["provenance-receipt-capture"] = "pass"
        self.assertEqual(observed, expected)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "not locked"):
            VERIFIER.verify_aggregate(root, require_locked=True)

    def test_candidate_cannot_reopen_a_frozen_input_gate(self) -> None:
        temporary, root = self.fixture_with_lock(locked=False)
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        gate = next(
            item
            for item in value["gates"]["build_input_lock"]
            if item["id"] == "license-provenance-inputs"
        )
        gate["status"] = "open"
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "lifecycle state"):
            VERIFIER.verify_aggregate(root)

    def test_candidate_generation_still_validates_component_structure(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        path = root / "deploy" / "manifests" / "upstream-images.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["images"][0]["platforms"][1]["architecture"] = "amd64"
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate platform"):
            GENERATOR.build_manifest(
                root, generated_at="2026-09-08T03:30:00Z", locked=False
            )

    def test_generator_cannot_mint_a_missing_provenance_receipt(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        receipt = root / VERIFIER.CODEX_PROVENANCE_RECEIPT_PATH
        receipt.unlink()
        self.assertFalse(hasattr(GENERATOR, "build_codex_provenance_receipt"))
        self.assertFalse(hasattr(GENERATOR, "write_codex_provenance_receipt"))
        argv = [
            "generate_build_input_lock.py",
            "--root",
            str(root),
            "--generated-at",
            "2026-09-08T03:30:00Z",
            "--locked",
        ]
        with (
            mock.patch.object(sys, "argv", argv),
            self.assertRaisesRegex(ValueError, "referenced file is missing"),
        ):
            GENERATOR.main()
        self.assertFalse(receipt.exists())

    def test_generator_never_replaces_the_receipt_leaf(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        receipt = root / VERIFIER.CODEX_PROVENANCE_RECEIPT_PATH
        before = receipt.read_bytes()
        argv = [
            "generate_build_input_lock.py",
            "--root",
            str(root),
            "--generated-at",
            "2026-09-08T03:30:00Z",
            "--locked",
        ]
        with mock.patch.object(sys, "argv", argv):
            self.assertEqual(GENERATOR.main(), 0)
        self.assertEqual(receipt.read_bytes(), before)

    def test_capture_tool_refuses_to_replace_existing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "receipt.json"
            output.write_bytes(b"existing-evidence")
            with self.assertRaisesRegex(CAPTURE.CaptureError, "create-only"):
                CAPTURE.write_new_receipt(
                    root=REPOSITORY_ROOT,
                    output=output,
                    receipt={"result": "forged-pass"},
                )
            self.assertEqual(output.read_bytes(), b"existing-evidence")

    def test_capture_tool_requires_a_real_locked_verifier_result(self) -> None:
        manifest = REPOSITORY_ROOT / "deploy/manifests/codex-0.153.4.json"
        child = self.v3_codex_child()
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            artifacts = directory / "artifacts"
            artifacts.mkdir()
            cosign = directory / "cosign-darwin-arm64"
            cosign.write_bytes(b"test-verifier")
            report = VERIFIER._expected_codex_runner_report(
                child, execution_platform="darwin/arm64"
            )
            with (
                mock.patch.object(
                    CAPTURE, "_host_platform", return_value="darwin/arm64"
                ),
                mock.patch.object(
                    CAPTURE.runner_verifier,
                    "verify_minimal_runner",
                    return_value=report,
                ) as verifier,
            ):
                receipt = CAPTURE.build_receipt(
                    root=REPOSITORY_ROOT,
                    manifest_path=manifest,
                    artifacts_directory=artifacts,
                    cosign_path=cosign,
                )
            verifier.assert_called_once_with(
                manifest.resolve(),
                artifacts.resolve(),
                cosign.resolve(),
                locked=True,
                allow_audit_verifier=True,
            )
            self.assertIs(receipt["verification"]["runner_report"], report)

    def test_capture_tool_rejects_an_incomplete_verifier_report(self) -> None:
        manifest = REPOSITORY_ROOT / "deploy/manifests/codex-0.153.4.json"
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            artifacts = directory / "artifacts"
            artifacts.mkdir()
            cosign = directory / "cosign-darwin-arm64"
            cosign.write_bytes(b"test-verifier")
            incomplete = {
                "cosign": {
                    "selected_verifier_platform": "darwin/arm64",
                    "selection_mode": "audit-only",
                }
            }
            with (
                mock.patch.object(
                    CAPTURE, "_host_platform", return_value="darwin/arm64"
                ),
                mock.patch.object(
                    CAPTURE.runner_verifier,
                    "verify_minimal_runner",
                    return_value=incomplete,
                ),
                self.assertRaisesRegex(CAPTURE.CaptureError, "exact complete"),
            ):
                CAPTURE.build_receipt(
                    root=REPOSITORY_ROOT,
                    manifest_path=manifest,
                    artifacts_directory=artifacts,
                    cosign_path=cosign,
                )

    def test_generation_rejects_a_symlinked_leaf_parent(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        evidence = root / "specs" / "001-autonomous-release" / "evidence"
        replacement = root / "evidence-backing"
        evidence.rename(replacement)
        evidence.symlink_to(replacement, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            GENERATOR.build_manifest(
                root, generated_at="2026-09-08T03:30:00Z", locked=False
            )

    def test_digest_excludes_only_digest_field(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["status"] = "locked"
        self.write_aggregate(root, value, reseal=False)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "digest mismatch"):
            VERIFIER.verify_aggregate(root)

    def test_empty_manifest_refs_are_rejected_even_with_valid_digest(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["manifest_refs"] = []
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "manifest reference set"):
            VERIFIER.verify_aggregate(root)

    def test_missing_manifest_ref_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["manifest_refs"].pop()
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "manifest reference set"):
            VERIFIER.verify_aggregate(root)

    def test_extra_manifest_ref_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        extra = copy.deepcopy(value["manifest_refs"][0])
        extra["id"] = "unexpected"
        value["manifest_refs"].append(extra)
        value["manifest_refs"].sort(key=lambda item: item["id"])
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "manifest reference set"):
            VERIFIER.verify_aggregate(root)

    def test_missing_leaf_ref_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["file_refs"].pop()
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "leaf file reference set"):
            VERIFIER.verify_aggregate(root)

    def test_codex_receipt_is_a_required_aggregate_verification_reference(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        self.assertIn(
            {
                "file_ref": VERIFIER.CODEX_PROVENANCE_RECEIPT_PATH,
                "role": "Codex provenance result evidence",
            },
            value["verification_refs"],
        )
        value["file_refs"] = [
            item
            for item in value["file_refs"]
            if item["path"] != VERIFIER.CODEX_PROVENANCE_RECEIPT_PATH
        ]
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(
            VERIFIER.LockVerificationError, "leaf file reference set"
        ):
            VERIFIER.verify_aggregate(root)

    def test_aggregate_rejects_a_stale_codex_receipt_subject(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        receipt_path = root / VERIFIER.CODEX_PROVENANCE_RECEIPT_PATH
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["subject"]["sha256"] = "0" * 64
        receipt_path.write_bytes(VERIFIER.canonical_bytes(receipt))
        value = self.read_aggregate(root)
        receipt_ref = next(
            item
            for item in value["file_refs"]
            if item["path"] == VERIFIER.CODEX_PROVENANCE_RECEIPT_PATH
        )
        receipt_ref["bytes"] = receipt_path.stat().st_size
        receipt_ref["sha256"] = VERIFIER.sha256_file(receipt_path)
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(
            VERIFIER.LockVerificationError, "subject reference"
        ):
            VERIFIER.verify_aggregate(root)

    def test_referenced_leaf_tamper_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        path = root / "deploy" / "locks" / "browser-worker-seccomp.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "byte count changed"):
            VERIFIER.verify_aggregate(root)

    def test_manifest_tamper_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        path = root / "deploy" / "manifests" / "speech-model.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "byte count changed"):
            VERIFIER.verify_aggregate(root)

    def test_path_escape_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["file_refs"][0]["path"] = "../outside"
        value["file_refs"].sort(key=lambda item: item["path"])
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "leaf file reference set"):
            VERIFIER.verify_aggregate(root)

    def test_symlinked_leaf_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        path = root / "deploy" / "locks" / "requirements-document-linux.lock"
        replacement = root / "replacement.lock"
        replacement.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(replacement)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "symlink"):
            VERIFIER.verify_aggregate(root)

    def test_symlinked_aggregate_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        path = self.aggregate_path(root)
        replacement = root / "replacement-aggregate.json"
        replacement.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(replacement)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "symlink"):
            VERIFIER.verify_aggregate(root)

    def test_missing_architecture_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["target_platforms"] = ["linux/arm64"]
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "target platform"):
            VERIFIER.verify_aggregate(root)

    def test_macos_historical_input_cannot_enter_current_lock(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["runtime_abis"].append(
            {"abi": "universal2", "runtime": "CPython", "version": "3.12.14"}
        )
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "runtime ABI"):
            VERIFIER.verify_aggregate(root)

    def test_runtime_download_flip_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["runtime_mutation_policy"]["model_download_at_runtime"] = True
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "runtime mutation"):
            VERIFIER.verify_aggregate(root)

    def test_runtime_mutation_boolean_cannot_be_spoofed_with_integer_zero(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["runtime_mutation_policy"]["model_download_at_runtime"] = 0
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "runtime mutation"):
            VERIFIER.verify_aggregate(root)

    def test_locked_status_with_open_t089_gate_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["gates"]["build_input_lock"][0]["status"] = "open"
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "lifecycle state"):
            VERIFIER.verify_aggregate(root)

    def test_fake_replacement_t089_gate_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["gates"]["build_input_lock"] = [
            {
                "blocking_for_build_input_lock": True,
                "id": "fake",
                "status": "pass",
                "task": "T089",
            }
        ]
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "gate ID set"):
            VERIFIER.verify_aggregate(root)

    def test_downstream_gates_remain_open_in_t089_candidate(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        verified = VERIFIER.verify_aggregate(root)
        self.assertTrue(
            all(
                item["blocking_for_build_input_lock"] is False
                and item["status"] == "open"
                for item in verified["gates"]["downstream_release"]
            )
        )
        codex = json.loads(
            (root / "deploy/manifests/codex-0.153.4.json").read_text(encoding="utf-8")
        )
        downstream_by_owner = {
            item["owner_task"]: item
            for item in verified["gates"]["downstream_release"]
        }
        for blocker in codex["downstream_release_blockers"]:
            mapped = downstream_by_owner[blocker["owner_task"]]
            self.assertEqual(mapped["id"], blocker["blocker_id"])
            self.assertEqual(mapped["gate_id"], blocker["gate_id"])
            self.assertEqual(mapped["summary"], blocker["summary"])
        self.assertEqual(
            downstream_by_owner["T083"]["id"],
            "aggregate-fresh-host-deployment-qualification",
        )

    def test_aggregate_gate_records_reject_legacy_unknown_duplicate_and_misowned(self) -> None:
        mutations = (
            (
                lambda gates: gates.__setitem__("downstream_release", ["T018"]),
                "structured records",
            ),
            (
                lambda gates: gates["downstream_release"].append(
                    copy.deepcopy(gates["downstream_release"][0])
                ),
                "stable IDs, ownership",
            ),
            (
                lambda gates: gates["downstream_release"][0].__setitem__(
                    "owner_task", "T089"
                ),
                "stable IDs, ownership",
            ),
            (
                lambda gates: gates["downstream_release"][0].__setitem__(
                    "gate_id", "t999-unknown"
                ),
                "stable IDs, ownership",
            ),
            (
                lambda gates: gates["build_input_lock"][0].__setitem__(
                    "owner_task", "T082"
                ),
                "T089 gate ownership",
            ),
        )
        for mutation, message in mutations:
            with self.subTest(message=message):
                temporary, root = self.fixture_with_lock()
                self.addCleanup(temporary.cleanup)
                value = self.read_aggregate(root)
                mutation(value["gates"])
                self.write_aggregate(root, value)
                with self.assertRaisesRegex(VERIFIER.LockVerificationError, message):
                    VERIFIER.verify_aggregate(root)

    def test_locked_generation_allows_only_downstream_release_blockers(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        value = GENERATOR.build_manifest(
            root, generated_at="2026-09-08T03:30:00Z", locked=True
        )
        self.assertEqual(value["status"], "locked")
        codex = json.loads(
            (root / "deploy/manifests/codex-0.153.4.json").read_text(encoding="utf-8")
        )
        self.assertEqual(codex["build_input_blockers"], [])
        self.assertTrue(codex["downstream_release_blockers"])

    def test_codex_v3_gate_and_blocker_inventory_are_fail_closed(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        codex_path = root / "deploy" / "manifests" / "codex-0.153.4.json"
        original = json.loads(codex_path.read_text(encoding="utf-8"))
        mutations = (
            (
                lambda child: child.__setitem__("build_input_gate", "not_satisfied"),
                "depend only on T089",
            ),
            (
                lambda child: child.__setitem__("release_gate", "satisfied"),
                "include downstream",
            ),
            (
                lambda child: child.__setitem__(
                    "downstream_release_blockers", ["legacy free text"]
                ),
                "structured blocker records",
            ),
            (
                lambda child: child.__setitem__(
                    "downstream_release_blockers",
                    [
                        *child["downstream_release_blockers"],
                        copy.deepcopy(child["downstream_release_blockers"][0]),
                    ],
                ),
                "duplicate blocker or gate IDs",
            ),
            (
                lambda child: child["downstream_release_blockers"][0].__setitem__(
                    "owner_task", "T089"
                ),
                "inventory, ownership",
            ),
            (
                lambda child: child["downstream_release_blockers"][0].__setitem__(
                    "gate_id", "t999-unknown-gate"
                ),
                "inventory, ownership",
            ),
            (
                lambda child: child["build_input_blockers"].append(
                    {
                        "blocker_id": "unknown-build-input",
                        "owner_task": "T089",
                        "gate_id": "t089-unknown-build-input",
                        "summary": "An unknown T089 blocker.",
                    }
                ),
                "inventory, ownership",
            ),
            (
                lambda child: child["build_input_blockers"].append(
                    {
                        "blocker_id": "misowned-build-input",
                        "owner_task": "T082",
                        "gate_id": "t089-misowned-build-input",
                        "summary": "A misowned T089 blocker.",
                    }
                ),
                "blocker ownership changed",
            ),
        )
        for mutation, message in mutations:
            with self.subTest(message=message):
                child = copy.deepcopy(original)
                mutation(child)
                with self.assertRaisesRegex(VERIFIER.LockVerificationError, message):
                    VERIFIER.verify_codex_t089_candidate_state(root, child, locked=False)

    def test_codex_v1_fields_and_parent_digest_backlinks_are_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        codex_path = root / "deploy" / "manifests" / "codex-0.153.4.json"
        original = json.loads(codex_path.read_text(encoding="utf-8"))
        for field, value in (
            ("platform_packages", []),
            ("official_checksum_manifest", {}),
            ("imported_sidecar_inputs", []),
            ("rust_dependency_inventory", {}),
            ("parent_manifest", {"sha256": "0" * 64}),
        ):
            with self.subTest(field=field):
                child = copy.deepcopy(original)
                child[field] = value
                with self.assertRaisesRegex(
                    VERIFIER.LockVerificationError, "v3 root shape"
                ):
                    VERIFIER.verify_codex_t089_candidate_state(root, child, locked=False)

    def test_codex_v3_platform_signature_layout_and_omission_contract(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        codex_path = root / "deploy" / "manifests" / "codex-0.153.4.json"
        original = json.loads(codex_path.read_text(encoding="utf-8"))
        mutations = (
            (lambda child: child["platform_inputs"].pop(), "both Linux targets"),
            (
                lambda child: child["platform_inputs"][0]["components"][1].__setitem__(
                    "name", "codex-package"
                ),
                "component set/order",
            ),
            (
                lambda child: child["platform_inputs"][0]["components"][0].__setitem__(
                    "signature_scope", "archive"
                ),
                "executable-scoped",
            ),
            (
                lambda child: child["platform_inputs"][0]["components"][2][
                    "sigstore_bundle"
                ].__setitem__("verified", False),
                "independently verified",
            ),
            (
                lambda child: child["signature_policy"].__setitem__(
                    "certificate_identity", "https://example.invalid/release"
                ),
                "signature policy",
            ),
            (
                lambda child: child["runtime_layout"].__setitem__(
                    "path_env", "/usr/local/bin:/usr/bin:/bin"
                ),
                "fixed sibling/runtime layout",
            ),
            (
                lambda child: child["platform_inputs"][0]["runtime_image"][
                    "bash"
                ].__setitem__("installed_path", "/usr/bin/bash"),
                "Bash package/source/member identity",
            ),
            (
                lambda child: child["platform_inputs"][0]["runtime_image"][
                    "config"
                ].__setitem__("digest", "sha256:" + "A" * 64),
                "full lowercase sha256 descriptor digest",
            ),
            (
                lambda child: child["platform_inputs"][0]["runtime_image"][
                    "bash"
                ]["binary_package"].__setitem__(
                    "url", "http://snapshot.debian.org/file/" + "0" * 40
                ),
                "exact Debian snapshot content URL",
            ),
            (
                lambda child: child["platform_inputs"][0]["runtime_image"][
                    "bash"
                ]["source_inputs"].pop(),
                "exact Bash source input set",
            ),
            (
                lambda child: child["platform_inputs"][0]["runtime_image"][
                    "bash"
                ]["package_member"].__setitem__("bytes", True),
                "bounded positive integer",
            ),
            (
                lambda child: child["omitted_components"].remove("ripgrep"),
                "omitted full-package/rg/zsh",
            ),
            (
                lambda child: child["runtime_mutation_policy"].__setitem__(
                    "tool_download_at_runtime", True
                ),
                "runtime mutation policy",
            ),
        )
        for mutation, message in mutations:
            with self.subTest(message=message):
                child = copy.deepcopy(original)
                mutation(child)
                with self.assertRaisesRegex(VERIFIER.LockVerificationError, message):
                    VERIFIER.verify_codex_t089_candidate_state(root, child, locked=False)

    def test_codex_v3_downstream_blockers_do_not_block_the_input_lock(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        codex_path = root / "deploy" / "manifests" / "codex-0.153.4.json"
        codex = json.loads(codex_path.read_text(encoding="utf-8"))
        VERIFIER.verify_codex_t089_candidate_state(root, codex, locked=True)
        self.assertTrue(codex["downstream_release_blockers"])

    def test_codex_rust_inventory_is_independently_verified(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        rust_path = root / "deploy" / "manifests" / "codex-0.153.4-rust-dependencies.json"
        rust = json.loads(rust_path.read_text(encoding="utf-8"))
        VERIFIER.verify_codex_rust_candidate_state(root, rust)
        rust["inventory_digest"] = "0" * 64
        with self.assertRaisesRegex(
            VERIFIER.LockVerificationError, "inventory identity changed"
        ):
            VERIFIER.verify_codex_rust_candidate_state(root, rust)

    def test_t089_cannot_claim_a_downstream_gate_passed(self) -> None:
        temporary, root = self.fixture_with_lock(locked=False)
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["gates"]["downstream_release"][3]["status"] = "pass"
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "open status"):
            VERIFIER.verify_aggregate(root)

    def test_t081_final_image_field_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["image_locks"] = []
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "root shape"):
            VERIFIER.verify_aggregate(root)

    def test_t081_final_image_field_is_rejected_inside_child(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        child_path = root / "deploy" / "manifests" / "speech-model.json"
        child = json.loads(child_path.read_text(encoding="utf-8"))
        child["image_locks"] = [{"fake": "sha256:" + "0" * 64}]
        child_path.write_bytes(VERIFIER.canonical_bytes(child))
        value = self.read_aggregate(root)
        reference = next(item for item in value["manifest_refs"] if item["id"] == "speech_model")
        reference["bytes"] = child_path.stat().st_size
        reference["sha256"] = VERIFIER.sha256_file(child_path)
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "child root shape"):
            VERIFIER.verify_aggregate(root)

    def test_absolute_child_repository_path_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        child_path = root / "deploy" / "manifests" / "browser-worker.json"
        child = json.loads(child_path.read_text(encoding="utf-8"))
        child["node"]["official_release_provenance"]["signed_checksums"]["path"] = "/tmp/external"
        child_path.write_bytes(VERIFIER.canonical_bytes(child))
        value = self.read_aggregate(root)
        reference = next(item for item in value["manifest_refs"] if item["id"] == "browser_worker")
        reference["bytes"] = child_path.stat().st_size
        reference["sha256"] = VERIFIER.sha256_file(child_path)
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "absolute"):
            VERIFIER.verify_aggregate(root)

    def test_drive_and_file_uri_child_paths_are_rejected(self) -> None:
        for replacement in ("C:/outside", "file:///tmp/outside"):
            with self.subTest(replacement=replacement):
                temporary, root = self.fixture_with_lock()
                self.addCleanup(temporary.cleanup)
                child_path = root / "deploy" / "manifests" / "browser-worker.json"
                child = json.loads(child_path.read_text(encoding="utf-8"))
                child["node"]["official_release_provenance"]["signed_checksums"][
                    "path"
                ] = replacement
                child_path.write_bytes(VERIFIER.canonical_bytes(child))
                aggregate = self.read_aggregate(root)
                reference = next(
                    item
                    for item in aggregate["manifest_refs"]
                    if item["id"] == "browser_worker"
                )
                reference["bytes"] = child_path.stat().st_size
                reference["sha256"] = VERIFIER.sha256_file(child_path)
                self.write_aggregate(root, aggregate)
                with self.assertRaisesRegex(
                    VERIFIER.LockVerificationError, "noncanonical path-like"
                ):
                    VERIFIER.verify_aggregate(root)

    def test_non_path_named_child_repository_reference_is_confined(self) -> None:
        for replacement, message in (
            ("/tmp/evil", "absolute"),
            ("deploy/locks/licenses/not-in-lock.txt", "absent from exact aggregate refs"),
        ):
            with self.subTest(replacement=replacement):
                temporary, root = self.fixture_with_lock()
                self.addCleanup(temporary.cleanup)
                child_path = root / "deploy" / "manifests" / "age-1.3.2-runtime-licenses.json"
                child = json.loads(child_path.read_text(encoding="utf-8"))
                child["components"][0]["license_file"] = replacement
                child_path.write_bytes(VERIFIER.canonical_bytes(child))
                value = self.read_aggregate(root)
                reference = next(
                    item
                    for item in value["manifest_refs"]
                    if item["id"] == "age_runtime_licenses"
                )
                reference["bytes"] = child_path.stat().st_size
                reference["sha256"] = VERIFIER.sha256_file(child_path)
                self.write_aggregate(root, value)
                with self.assertRaisesRegex(VERIFIER.LockVerificationError, message):
                    VERIFIER.verify_aggregate(root)

    def test_artifact_pointer_count_tamper_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["artifacts"][0]["count"] += 1
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "pointer/count"):
            VERIFIER.verify_aggregate(root)

    def test_artifact_integer_one_cannot_be_spoofed_with_boolean_true(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        playwright = next(
            item
            for item in value["artifacts"]
            if item["category"] == "playwright-npm-packages"
        )
        self.assertEqual(playwright["count"], 1)
        playwright["count"] = True
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "pointer/count"):
            VERIFIER.verify_aggregate(root)

    def test_age_license_inventory_is_counted_and_counts_must_be_nonzero(self) -> None:
        temporary, root = self.fixture_with_lock(locked=False)
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        counts = {item["category"]: item["count"] for item in value["artifacts"]}
        self.assertEqual(counts["age-license-components"], 8)
        self.assertEqual(counts["age-license-files"], 3)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "must be nonempty"):
            VERIFIER._require_nonempty_artifact_counts(
                [{"category": "empty-build-input", "count": 0}]
            )

    def test_upstream_provenance_inventory_and_evidence_are_aggregated(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        counts = {item["category"]: item["count"] for item in value["artifacts"]}
        self.assertEqual(counts["upstream-provenance-manifests"], 6)
        self.assertEqual(counts["upstream-provenance-artifacts"], 12)
        refs = {item["path"] for item in value["file_refs"]}
        self.assertIn(
            "specs/001-autonomous-release/evidence/upstream-image-provenance-results.json",
            refs,
        )
        self.assertIn(
            "specs/001-autonomous-release/evidence/codex-minimal-runner-decision.proposal.md",
            refs,
        )
        self.assertNotIn(
            "specs/001-autonomous-release/evidence/codex-0.153.4-sidecar-closure.proposal.json",
            refs,
        )

    def test_codex_minimal_runner_inputs_are_aggregated_without_v1_sidecars(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        counts = {item["category"]: item["count"] for item in value["artifacts"]}
        self.assertEqual(counts["codex-bookworm-oci-index"], 1)
        self.assertEqual(counts["codex-bookworm-oci-manifests"], 2)
        self.assertEqual(counts["codex-bookworm-oci-configs"], 2)
        self.assertEqual(counts["codex-bookworm-oci-layers"], 2)
        self.assertEqual(counts["codex-bash-binary-packages"], 2)
        self.assertEqual(counts["codex-bash-installed-executables"], 2)
        self.assertEqual(counts["codex-bash-copyright-artifacts"], 1)
        self.assertEqual(counts["codex-bash-source-files"], 3)
        usages = {
            item["category"]: item.get("usage_count")
            for item in value["artifacts"]
        }
        self.assertEqual(usages["codex-bookworm-oci-index"], 2)
        self.assertEqual(usages["codex-bash-copyright-artifacts"], 2)
        self.assertEqual(usages["codex-bash-source-files"], 6)
        self.assertEqual(counts["codex-cosign-checksum-inputs"], 2)
        self.assertEqual(counts["codex-cosign-release-verifier-inputs"], 4)
        self.assertEqual(counts["codex-cosign-audit-verifier-inputs"], 2)
        self.assertEqual(counts["codex-executable-sigstore-bundles"], 6)
        self.assertEqual(counts["codex-platform-inputs"], 2)
        self.assertEqual(counts["codex-standalone-archives"], 6)
        self.assertEqual(counts["codex-standalone-executables"], 6)
        self.assertFalse(
            {
                "codex-imported-sidecar-inputs",
                "codex-package-members",
                "codex-platform-packages",
                "codex-redistribution-inputs",
                "codex-sidecar-provenance-assets",
            }
            & set(counts)
        )
        self.assertIn(
            {
                "abi": "musl-static-artifacts+glibc-shell",
                "runtime": "Codex managed runner",
                "version": "glibc-2.36",
            },
            value["runtime_abis"],
        )
        self.assertEqual(value["glibc_floor"]["codex_runner_bookworm"], "2.36")
        self.assertIn(
            {
                "component": "codex-managed-runner",
                "json_pointer": "/platform_inputs",
                "manifest_ref": "codex_managed_runner",
            },
            value["model_component_locks"],
        )
        self.assertIn(
            {
                "kind": "codex-executable-signature-provenance",
                "json_pointer": "/signature_policy",
                "manifest_ref": "codex_managed_runner",
            },
            value["license_provenance_refs"],
        )
        self.assertFalse(
            {"/verification", "/redistribution_inputs"}
            & {
                item["json_pointer"]
                for item in value["license_provenance_refs"]
                if item["manifest_ref"] == "codex_managed_runner"
            }
        )

    def test_codex_rust_inventory_and_inputs_are_aggregated(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        manifests = {item["id"]: item for item in value["manifest_refs"]}
        self.assertEqual(
            manifests["codex_rust_dependencies"]["path"],
            "deploy/manifests/codex-0.153.4-rust-dependencies.json",
        )
        counts = {item["category"]: item["count"] for item in value["artifacts"]}
        self.assertEqual(counts["codex-rust-dependency-packages"], 1047)
        refs = {item["path"] for item in value["file_refs"]}
        self.assertTrue(
            {
                "deploy/locks/codex-0.153.4/Cargo.lock.effective",
                "deploy/locks/codex-0.153.4/Cargo.lock.source",
                "deploy/locks/generate_codex_rust_inventory.py",
                "deploy/locks/verify_codex_rust_inventory.py",
                "deploy/tests/test_codex_rust_inventory_verifier.py",
                "specs/001-autonomous-release/evidence/codex-0.153.4-rust-dependency-inventory.md",
            }.issubset(refs)
        )
        self.assertIn(
            {
                "component": "codex-rust-dependencies",
                "json_pointer": "/packages",
                "manifest_ref": "codex_rust_dependencies",
            },
            value["model_component_locks"],
        )
        self.assertIn(
            {
                "kind": "codex-rust-license-provenance-inputs",
                "json_pointer": "/packages",
                "manifest_ref": "codex_rust_dependencies",
            },
            value["license_provenance_refs"],
        )

    def test_reference_order_is_canonical(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["manifest_refs"].reverse()
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "canonically sorted"):
            VERIFIER.verify_aggregate(root)

    def test_duplicate_json_key_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        self.aggregate_path(root).write_bytes(b'{"schema_version":"x","schema_version":"y"}')
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "duplicate JSON"):
            VERIFIER.verify_aggregate(root)

    def test_float_and_nan_are_rejected(self) -> None:
        for invalid in (b'{"x":1.5}', b'{"x":NaN}'):
            with self.subTest(invalid=invalid):
                temporary, root = self.fixture_with_lock()
                self.addCleanup(temporary.cleanup)
                self.aggregate_path(root).write_bytes(invalid)
                with self.assertRaisesRegex(VERIFIER.LockVerificationError, "forbidden"):
                    VERIFIER.verify_aggregate(root)

    def test_integer_bound_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        self.aggregate_path(root).write_bytes(b'{"x":9223372036854775808}')
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "63-bit"):
            VERIFIER.verify_aggregate(root)

    def test_total_item_bound_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        self.aggregate_path(root).write_text(
            json.dumps({"a": [0] * 6000, "b": [0] * 6000}, separators=(",", ":")),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "total items"):
            VERIFIER.verify_aggregate(root)

    def test_calendar_invalid_generated_at_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        value["generated_at"] = "2026-02-31T03:30:00Z"
        self.write_aggregate(root, value)
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "real UTC calendar"):
            VERIFIER.verify_aggregate(root)

    def test_unpaired_surrogate_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        self.aggregate_path(root).write_bytes(b'{"x":"\\ud800"}')
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "surrogate"):
            VERIFIER.verify_aggregate(root)

    def test_noncanonical_file_encoding_is_rejected(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        value = self.read_aggregate(root)
        self.aggregate_path(root).write_text(json.dumps(value, indent=2), encoding="utf-8")
        with self.assertRaisesRegex(VERIFIER.LockVerificationError, "canonical JSON bytes"):
            VERIFIER.verify_aggregate(root)

    def test_child_status_must_use_its_exact_nonrelease_enum(self) -> None:
        for spoofed_status in ("release_ready", "release-ready", "production_ready", "unknown"):
            with self.subTest(spoofed_status=spoofed_status):
                temporary, root = self.fixture_with_lock()
                self.addCleanup(temporary.cleanup)
                child_path = root / "deploy" / "manifests" / "speech-model.json"
                child = json.loads(child_path.read_text(encoding="utf-8"))
                child["status"] = spoofed_status
                child_path.write_bytes(VERIFIER.canonical_bytes(child))
                value = self.read_aggregate(root)
                reference = next(
                    item for item in value["manifest_refs"] if item["id"] == "speech_model"
                )
                reference["bytes"] = child_path.stat().st_size
                reference["sha256"] = VERIFIER.sha256_file(child_path)
                self.write_aggregate(root, value)
                with self.assertRaisesRegex(
                    VERIFIER.LockVerificationError, "exact non-release enum"
                ):
                    VERIFIER.verify_aggregate(root)

    def test_leaf_change_changes_regenerated_lock_digest(self) -> None:
        temporary, root = self.fixture_with_lock()
        self.addCleanup(temporary.cleanup)
        before = GENERATOR.build_manifest(root, generated_at="2026-09-08T03:30:00Z", locked=False)
        leaf = root / "deploy" / "tests" / "test_build_input_verifier.py"
        leaf.write_bytes(leaf.read_bytes() + b"\n")
        after = GENERATOR.build_manifest(root, generated_at="2026-09-08T03:30:00Z", locked=False)
        self.assertNotEqual(
            before["build_input_lock_set_digest"], after["build_input_lock_set_digest"]
        )


if __name__ == "__main__":
    unittest.main()
