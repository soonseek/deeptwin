from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = REPOSITORY_ROOT / "deploy" / "locks" / "verify_build_inputs.py"
SPEC = importlib.util.spec_from_file_location("deeptwin_build_input_verifier", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class BuildInputVerifierTests(unittest.TestCase):
    def make_fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory(prefix="deeptwin-build-input-test-")
        root = Path(temporary.name)
        shutil.copytree(REPOSITORY_ROOT / "deploy", root / "deploy")
        shutil.copytree(
            REPOSITORY_ROOT / "specs" / "001-autonomous-release" / "evidence",
            root / "specs" / "001-autonomous-release" / "evidence",
        )
        return temporary, root

    def rewrite_age_license_bundle(
        self, root: Path, mutate: object
    ) -> None:
        license_path = (
            root / "deploy" / "manifests" / "age-1.3.2-runtime-licenses.json"
        )
        license_manifest = json.loads(license_path.read_text(encoding="utf-8"))
        assert callable(mutate)
        mutate(license_manifest)
        rendered = json.dumps(license_manifest, separators=(",", ":"))
        license_path.write_text(rendered, encoding="utf-8")

        age_path = root / "deploy" / "manifests" / "age-1.3.2.json"
        age = json.loads(age_path.read_text(encoding="utf-8"))
        encoded = rendered.encode("utf-8")
        age["runtime_license_bundle"]["bytes"] = len(encoded)
        age["runtime_license_bundle"]["sha256"] = hashlib.sha256(encoded).hexdigest()
        age_path.write_text(json.dumps(age), encoding="utf-8")

    def rewrite_upstream_provenance_evidence(
        self, root: Path, mutate: object
    ) -> None:
        result_path = (
            root
            / "specs"
            / "001-autonomous-release"
            / "evidence"
            / "upstream-image-provenance-results.json"
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert callable(mutate)
        mutate(result)
        rendered = json.dumps(result, separators=(",", ":"))
        result_path.write_text(rendered, encoding="utf-8")

        manifest_path = root / "deploy" / "manifests" / "upstream-images.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        encoded = rendered.encode("utf-8")
        manifest["provenance_verification"]["bytes"] = len(encoded)
        manifest["provenance_verification"]["sha256"] = hashlib.sha256(
            encoded
        ).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def rewrite_codex_manifest(self, root: Path, mutate: object) -> None:
        manifest_path = root / "deploy" / "manifests" / "codex-0.153.4.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert callable(mutate)
        mutate(manifest)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_current_candidate_is_structurally_closed(self) -> None:
        VERIFIER.verify_repository(
            REPOSITORY_ROOT,
            require_release_ready=False,
            verify_aggregate_lock=False,
        )

    def test_json_loader_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deeptwin-json-loader-test-") as raw:
            path = Path(raw) / "duplicate.json"
            path.write_bytes(b'{"schema_version":"unsafe","schema_version":"safe"}')
            with self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
                VERIFIER.load_json(path)

    def test_json_loader_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deeptwin-json-loader-test-") as raw:
            root = Path(raw)
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            link = root / "link.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "regular non-symlink file"):
                VERIFIER.load_json(link)

    def test_json_loader_rejects_oversized_body(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deeptwin-json-loader-test-") as raw:
            path = Path(raw) / "oversized.json"
            path.write_bytes(b"{" + b" " * VERIFIER.MAX_BODY_BYTES + b"}")
            with self.assertRaisesRegex(ValueError, "JSON body exceeds 1 MiB"):
                VERIFIER.load_json(path)

    def test_json_loader_rejects_float_and_nonfinite_values(self) -> None:
        invalid_values = {
            "float": b'{"value":1.5}',
            "nan": b'{"value":NaN}',
            "infinity": b'{"value":Infinity}',
        }
        for label, payload in invalid_values.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory(
                    prefix="deeptwin-json-loader-test-"
                ) as raw:
                    path = Path(raw) / f"{label}.json"
                    path.write_bytes(payload)
                    expected = (
                        "floating-point JSON values are forbidden"
                        if label == "float"
                        else "non-finite JSON value is forbidden"
                    )
                    with self.assertRaisesRegex(ValueError, expected):
                        VERIFIER.load_json(path)

    def test_json_loader_rejects_deep_nesting(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deeptwin-json-loader-test-") as raw:
            path = Path(raw) / "deep.json"
            nested = "0"
            for _ in range(VERIFIER.MAX_DEPTH + 1):
                nested = f'{{"child":{nested}}}'
            path.write_text(nested, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON nesting exceeds depth 32"):
                VERIFIER.load_json(path)

    def test_json_loader_rejects_excess_total_items(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deeptwin-json-loader-test-") as raw:
            path = Path(raw) / "items.json"
            path.write_text(
                json.dumps({"items": [0] * VERIFIER.MAX_ITEMS}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "JSON tree exceeds 10000 total items"):
                VERIFIER.load_json(path)

    def test_json_loader_rejects_oversized_string_and_integer(self) -> None:
        invalid_values = {
            "string": json.dumps({"value": "x" * (VERIFIER.MAX_STRING_BYTES + 1)}),
            "integer": json.dumps({"value": VERIFIER.MAX_INTEGER + 1}),
        }
        expected_errors = {
            "string": "JSON string exceeds 64 KiB",
            "integer": "JSON integer exceeds signed 63-bit domain",
        }
        for label, payload in invalid_values.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory(
                    prefix="deeptwin-json-loader-test-"
                ) as raw:
                    path = Path(raw) / f"{label}.json"
                    path.write_text(payload, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, expected_errors[label]):
                        VERIFIER.load_json(path)

    def test_json_loader_supports_explicit_large_codex_rust_item_bound(self) -> None:
        path = (
            REPOSITORY_ROOT
            / "deploy"
            / "manifests"
            / "codex-0.153.4-rust-dependencies.json"
        )
        value = VERIFIER.load_json(path, max_total_items=50_000)
        self.assertEqual(
            value["schema_version"],
            "deeptwin-codex-rust-dependency-inventory-v1",
        )

    def test_release_ready_mode_rejects_declared_blockers(self) -> None:
        with self.assertRaisesRegex(ValueError, "unresolved release blockers"):
            VERIFIER.verify_repository(
                REPOSITORY_ROOT,
                require_release_ready=True,
                verify_aggregate_lock=False,
            )

    def test_unused_service_lock_hash_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        lock_path = root / "deploy" / "locks" / "requirements-control-plane-linux.lock"
        lock = lock_path.read_text(encoding="utf-8")
        lock = lock.replace(
            "fastapi==0.141.1 --hash=sha256:",
            "fastapi==0.141.1 --hash=sha256:"
            + "0" * 64
            + " --hash=sha256:",
            1,
        )
        lock_path.write_text(lock, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "lock contains unused hash"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_cross_architecture_artifact_usage_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "deploy" / "manifests" / "python-wheel-artifacts.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact = next(
            item
            for item in manifest["artifacts"]
            if item["wheel"]["platform"] == {"os": "linux", "architecture": "amd64"}
        )
        artifact["usage"][0]["architecture"] = "arm64"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "wheel/usage platform mismatch"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_external_source_license_resource_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "deploy" / "manifests" / "python-wheel-artifacts.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        resource = manifest["legal_gate"]["external_source_license_resources"][0][
            "resources"
        ][0]
        license_path = root / resource["path"]
        license_path.write_bytes(license_path.read_bytes() + b"\nTAMPERED\n")
        with self.assertRaisesRegex(ValueError, "external license bytes changed"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_missing_external_source_license_coverage_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "deploy" / "manifests" / "python-wheel-artifacts.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["legal_gate"]["external_source_license_resources"].pop()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "external license package coverage mismatch"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_derived_speech_digest_must_match_service_roots(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "deploy" / "manifests" / "python-wheel-artifacts.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact = next(
            item
            for item in manifest["artifacts"]
            if item["name"] == "deeptwin-faster-whisper"
        )
        artifact["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "artifact absent from lock"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_browser_seccomp_profile_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        profile_path = root / "deploy" / "locks" / "browser-worker-seccomp.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["defaultAction"] = "SCMP_ACT_ALLOW"
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "seccomp profile reference changed"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_browser_capability_expansion_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "deploy" / "manifests" / "browser-worker.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["runtime_security"]["linux_capabilities"]["add"].append("SYS_ADMIN")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "capability boundary changed"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_playwright_provenance_postcheck_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        verifier_path = root / "deploy" / "locks" / "verify_playwright_provenance.mjs"
        verifier_path.write_bytes(verifier_path.read_bytes() + b"\n// TAMPERED\n")
        with self.assertRaisesRegex(
            ValueError, "Playwright provenance postcheck reference changed"
        ):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_node_release_keyring_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        keyring_path = (
            root
            / "deploy"
            / "locks"
            / "nodejs"
            / "release-keys-5b7f55f4a7e35d1176d27a6b81b0c3c3b794216b.kbx"
        )
        keyring_path.write_bytes(keyring_path.read_bytes() + b"TAMPERED")
        with self.assertRaisesRegex(ValueError, "Node verification keyring reference changed"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_node_release_result_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        result_path = (
            root
            / "specs"
            / "001-autonomous-release"
            / "evidence"
            / "node-24.20.0-release-results.json"
        )
        result_path.write_bytes(result_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "Node offline verification result reference changed"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_playwright_runtime_result_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        result_path = (
            root
            / "specs"
            / "001-autonomous-release"
            / "evidence"
            / "playwright-1.63.0-provenance-results.json"
        )
        result_path.write_bytes(result_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(
            ValueError, "Playwright provenance runtime result reference changed"
        ):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_missing_codex_architecture_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            platform_inputs = manifest["platform_inputs"]
            assert isinstance(platform_inputs, list)
            platform_inputs.pop()

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "exact supported pair"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_rust_reference_constants_match_current_exact_bytes(self) -> None:
        inventory = REPOSITORY_ROOT / VERIFIER.CODEX_RUST_DEPENDENCY_INVENTORY["path"]
        evidence_record = VERIFIER.CODEX_RUST_DEPENDENCY_INVENTORY["evidence"]
        evidence = REPOSITORY_ROOT / evidence_record["path"]
        self.assertEqual(
            inventory.stat().st_size,
            VERIFIER.CODEX_RUST_DEPENDENCY_INVENTORY["bytes"],
        )
        self.assertEqual(
            VERIFIER.sha256_file(inventory),
            VERIFIER.CODEX_RUST_DEPENDENCY_INVENTORY["sha256"],
        )
        self.assertEqual(evidence.stat().st_size, evidence_record["bytes"])
        self.assertEqual(VERIFIER.sha256_file(evidence), evidence_record["sha256"])

    def test_codex_platform_order_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            platform_inputs = manifest["platform_inputs"]
            assert isinstance(platform_inputs, list)
            platform_inputs.reverse()

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "platform input ordering"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_missing_codex_component_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            platform_inputs = manifest["platform_inputs"]
            assert isinstance(platform_inputs, list)
            components = platform_inputs[0]["components"]
            assert isinstance(components, list)
            components.pop()

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "component ordering"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_component_order_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            platform_inputs = manifest["platform_inputs"]
            assert isinstance(platform_inputs, list)
            components = platform_inputs[0]["components"]
            assert isinstance(components, list)
            components.reverse()

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "component ordering"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_standalone_archive_digest_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            component = manifest["platform_inputs"][0]["components"][0]
            component["archive"]["sha256"] = "0" * 64

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "standalone component input"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_executable_layout_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            component = manifest["platform_inputs"][0]["components"][1]
            component["executable"]["installed_path"] = "/usr/local/bin/host"

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "standalone component input"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_bundle_verification_claim_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            component = manifest["platform_inputs"][1]["components"][2]
            component["sigstore_bundle"]["verified"] = False

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "standalone component input"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_signature_scope_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            component = manifest["platform_inputs"][0]["components"][0]
            component["signature_scope"] = "archive"

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "standalone component input"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_signature_policy_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            policy = manifest["signature_policy"]
            assert isinstance(policy, dict)
            policy["offline"] = False

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "signature policy"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_sibling_layout_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            layout = manifest["runtime_layout"]
            assert isinstance(layout, dict)
            layout["code_mode_host_path"] = "/opt/deeptwin/host"

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "fixed runtime layout"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_omitted_component_boundary_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            omitted = manifest["omitted_components"]
            assert isinstance(omitted, list)
            omitted.remove("ripgrep")

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "omitted component boundary"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_runtime_mutation_enablement_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            policy = manifest["runtime_mutation_policy"]
            assert isinstance(policy, dict)
            policy["tool_download_at_runtime"] = True

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "runtime mutation policy"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_runtime_image_coordinate_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            runtime = manifest["platform_inputs"][0]["runtime_image"]
            runtime["manifest"]["digest"] = "sha256:" + "c" * 64

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "Bookworm runtime closure"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_bash_coordinate_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            bash = manifest["platform_inputs"][1]["runtime_image"]["bash"]
            bash["package_version"] = "5.2.15-2+b9"

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "Bookworm runtime closure"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_missing_codex_downstream_release_blocker_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            blockers = manifest["downstream_release_blockers"]
            assert isinstance(blockers, list)
            blockers.pop(0)

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "inventory, ownership"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_duplicate_codex_downstream_release_blocker_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            blockers = manifest["downstream_release_blockers"]
            assert isinstance(blockers, list)
            blockers.append(blockers[0])

        self.rewrite_codex_manifest(root, mutate)
        with self.assertRaisesRegex(ValueError, "duplicate blocker or gate IDs"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_false_release_gate_claim_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        self.rewrite_codex_manifest(
            root, lambda manifest: manifest.__setitem__("release_gate", "satisfied")
        )
        with self.assertRaisesRegex(ValueError, "include downstream"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_legacy_free_text_and_misowned_build_blockers_are_rejected(self) -> None:
        mutations = (
            (
                lambda manifest: manifest.__setitem__(
                    "build_input_blockers", ["legacy free text"]
                ),
                "structured blocker records",
            ),
            (
                lambda manifest: manifest["build_input_blockers"].append(
                    {
                        "blocker_id": "misowned-input",
                        "owner_task": "T082",
                        "gate_id": "t089-misowned-input",
                        "summary": "A misowned input blocker.",
                    }
                ),
                "blocker ownership changed",
            ),
            (
                lambda manifest: manifest["build_input_blockers"].append(
                    {
                        "blocker_id": "unknown-input",
                        "owner_task": "T089",
                        "gate_id": "t089-unknown-input",
                        "summary": "An unknown input blocker.",
                    }
                ),
                "inventory, ownership",
            ),
        )
        for mutation, message in mutations:
            with self.subTest(message=message):
                temporary_case, case_root = self.make_fixture()
                self.addCleanup(temporary_case.cleanup)
                self.rewrite_codex_manifest(case_root, mutation)
                with self.assertRaisesRegex(ValueError, message):
                    VERIFIER.verify_repository(
                        case_root,
                        require_release_ready=False,
                        verify_aggregate_lock=False,
                    )

    def test_codex_downstream_blockers_only_block_release_readiness(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        VERIFIER.verify_repository(
            root, require_release_ready=False, verify_aggregate_lock=False
        )
        with self.assertRaisesRegex(ValueError, "codex: unresolved release blockers: 7"):
            VERIFIER.verify_repository(
                root, require_release_ready=True, verify_aggregate_lock=False
            )

    def test_codex_runner_manifest_cannot_embed_rust_inventory(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        self.rewrite_codex_manifest(
            root,
            lambda manifest: manifest.__setitem__(
                "rust_dependency_inventory", {"path": "not-allowed"}
            ),
        )
        with self.assertRaisesRegex(ValueError, "root claim inventory"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_rust_inventory_reference_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        inventory_path = (
            root
            / "deploy"
            / "manifests"
            / "codex-0.153.4-rust-dependencies.json"
        )
        inventory_path.write_bytes(inventory_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(
            ValueError, "Rust dependency inventory reference changed"
        ):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_codex_rust_inventory_verifier_is_invoked(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        verifier_path = root / "deploy" / "locks" / "verify_codex_rust_inventory.py"
        verifier_path.write_text(
            "def verify_inventory(root):\n"
            "    raise ValueError('rust-inventory-verifier-sentinel')\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "rust-inventory-verifier-sentinel"):
            VERIFIER.verify_repository(
                root, require_release_ready=False, verify_aggregate_lock=False
            )

    def test_age_native_result_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        result_path = (
            root
            / "specs"
            / "001-autonomous-release"
            / "evidence"
            / "age-1.3.2-native-results.json"
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["native_canaries"][0]["status"] = "fail"
        result_path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "age native result reference changed"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_empty_age_platform_archive_inventory_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "deploy" / "manifests" / "age-1.3.2.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["platform_archives"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "dual-platform archive inventory"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_partial_age_archive_member_inventory_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "deploy" / "manifests" / "age-1.3.2.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["platform_archives"][0]["copied_members"].pop()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "dual-platform archive inventory"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_empty_age_embedded_module_inventory_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "deploy" / "manifests" / "age-1.3.2.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["embedded_modules"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "embedded-module inventory"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_self_consistent_empty_age_license_components_are_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            manifest["components"] = []

        self.rewrite_age_license_bundle(root, mutate)
        age_path = root / "deploy" / "manifests" / "age-1.3.2.json"
        age = json.loads(age_path.read_text(encoding="utf-8"))
        age["runtime_license_bundle"]["component_count"] = 0
        age_path.write_text(json.dumps(age), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "license component/file inventory"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_self_consistent_empty_age_license_files_are_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(manifest: dict[str, object]) -> None:
            manifest["license_files"] = []

        self.rewrite_age_license_bundle(root, mutate)
        age_path = root / "deploy" / "manifests" / "age-1.3.2.json"
        age = json.loads(age_path.read_text(encoding="utf-8"))
        age["runtime_license_bundle"]["unique_license_file_count"] = 0
        age_path.write_text(json.dumps(age), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "license component/file inventory"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_empty_chromium_platform_asset_inventory_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "deploy" / "manifests" / "browser-worker.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["chromium_headless_shell"]["assets"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "dual-platform asset inventory"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_empty_chromium_license_object_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "deploy" / "manifests" / "browser-worker.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["chromium_headless_shell"]["license_headless_shell"] = {}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "identity or license binding"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_empty_speech_license_input_inventory_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "deploy" / "manifests" / "speech-model.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["license_inputs"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "nonempty license input inventory"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_speech_vendored_license_byte_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        license_path = root / "deploy" / "locks" / "licenses" / "OpenAI-Whisper-MIT.txt"
        license_path.write_bytes(license_path.read_bytes() + b"TAMPERED")
        with self.assertRaisesRegex(ValueError, "vendored license bytes changed"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_empty_upstream_provenance_inventory_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "deploy" / "manifests" / "upstream-images.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["images"][0]["provenance_descriptors"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "dual-platform provenance records"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_upstream_provenance_subject_mismatch_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "deploy" / "manifests" / "upstream-images.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["images"][0]["provenance_descriptors"][0][
            "subject_manifest_digest"
        ] = "sha256:" + "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "provenance subject binding"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_upstream_provenance_requires_both_artifact_types(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "deploy" / "manifests" / "upstream-images.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["images"][0]["provenance_descriptors"][0]["artifacts"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exact SPDX and SLSA artifacts"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_upstream_provenance_evidence_byte_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        result_path = (
            root
            / "specs"
            / "001-autonomous-release"
            / "evidence"
            / "upstream-image-provenance-results.json"
        )
        result_path.write_bytes(result_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "verification reference changed"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_self_consistent_upstream_evidence_subject_tamper_is_rejected(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(result: dict[str, object]) -> None:
            images = result["images"]
            assert isinstance(images, list)
            images[0]["platforms"][0]["spdx"]["subject_digest"] = (
                "sha256:" + "0" * 64
            )

        self.rewrite_upstream_provenance_evidence(root, mutate)
        with self.assertRaisesRegex(ValueError, "statement binding changed"):
            VERIFIER.verify_repository(root, require_release_ready=False)

    def test_upstream_evidence_boolean_count_is_not_an_integer(self) -> None:
        temporary, root = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def mutate(result: dict[str, object]) -> None:
            images = result["images"]
            assert isinstance(images, list)
            images[0]["platforms"][0]["slsa"]["materials_count"] = True

        self.rewrite_upstream_provenance_evidence(root, mutate)
        with self.assertRaisesRegex(ValueError, "statement binding changed"):
            VERIFIER.verify_repository(root, require_release_ready=False)


if __name__ == "__main__":
    unittest.main()
