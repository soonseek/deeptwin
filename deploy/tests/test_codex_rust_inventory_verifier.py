from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = REPOSITORY_ROOT / "deploy/locks/verify_codex_rust_inventory.py"
SPEC = importlib.util.spec_from_file_location(
    "deeptwin_codex_rust_inventory_verifier", VERIFIER_PATH
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

GENERATOR_PATH = REPOSITORY_ROOT / "deploy/locks/generate_codex_rust_inventory.py"
GENERATOR_SPEC = importlib.util.spec_from_file_location(
    "deeptwin_codex_rust_inventory_generator", GENERATOR_PATH
)
assert GENERATOR_SPEC is not None and GENERATOR_SPEC.loader is not None
GENERATOR = importlib.util.module_from_spec(GENERATOR_SPEC)
sys.modules[GENERATOR_SPEC.name] = GENERATOR
GENERATOR_SPEC.loader.exec_module(GENERATOR)


class CodexRustInventoryVerifierTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.inventory_path = (
            REPOSITORY_ROOT
            / "deploy/manifests/codex-0.153.4-rust-dependencies.json"
        )

    def load_inventory(self) -> dict[str, object]:
        return json.loads(self.inventory_path.read_text(encoding="utf-8"))

    def write_inventory(
        self, directory: Path, value: dict[str, object], *, recalc: bool = True
    ) -> Path:
        if recalc:
            digest_input = dict(value)
            digest_input.pop("inventory_digest", None)
            value["inventory_digest"] = VERIFIER.canonical_digest(digest_input)
        path = directory / "inventory.json"
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        return path

    def copy_repository_inputs(self, directory: Path) -> None:
        destination = directory / "deploy/locks/codex-0.153.4"
        destination.mkdir(parents=True)
        for name in ("Cargo.lock.source", "Cargo.lock.effective"):
            shutil.copy2(
                REPOSITORY_ROOT / "deploy/locks/codex-0.153.4" / name,
                destination / name,
            )

    def verify_mutation(
        self,
        value: dict[str, object],
        *,
        enforce_expected_digest: bool = False,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = self.write_inventory(directory, value)
            VERIFIER.verify_inventory(
                REPOSITORY_ROOT,
                inventory_path=path,
                enforce_expected_digest=enforce_expected_digest,
            )

    def test_current_inventory_passes_and_stays_non_release(self) -> None:
        result = VERIFIER.verify_inventory(REPOSITORY_ROOT)
        self.assertEqual(result["package_count"], 1_047)
        self.assertEqual(result["registry_archive_count"], 908)
        self.assertEqual(result["git_source_count"], 4)
        self.assertEqual(result["rusty_v8_asset_count"], 6)
        self.assertEqual(result["release_gate"], "not_satisfied")

    def test_generator_and_verifier_share_adr013_qualification_limits(self) -> None:
        value = self.load_inventory()
        self.assertEqual(
            list(GENERATOR.QUALIFICATION_LIMITS),
            VERIFIER.EXPECTED_QUALIFICATION_LIMITS,
        )
        self.assertEqual(
            value["qualification_limits"],
            VERIFIER.EXPECTED_QUALIFICATION_LIMITS,
        )
        rendered = "\n".join(value["qualification_limits"])
        self.assertIn("ADR-013's minimal standalone Codex runner", rendered)
        self.assertIn("73 registry archives", rendered)
        self.assertIn("notice-text selection", rendered)
        self.assertIn("source offers", rendered)
        self.assertIn("redistribution/legal/publication approval remain T084", rendered)
        self.assertIn("Per-final-image SBOMs", rendered)
        self.assertIn("source-to-binary provenance", rendered)
        self.assertIn("T082 outputs", rendered)
        self.assertIn("Codex and rusty_v8 commits are unsigned", rendered)
        self.assertIn("mutable release", rendered)
        self.assertIn("T079 integrated security qualification", rendered)
        self.assertIn("does not reopen T089", rendered)
        self.assertIn("bit-for-bit reproduction", rendered)
        for obsolete in (
            "full-package",
            "ripgrep",
            "zsh",
            "package-archive signature",
            "private/immutable staging",
        ):
            self.assertNotIn(obsolete, rendered)

    def test_semantic_mutation_fails_the_pinned_digest(self) -> None:
        value = self.load_inventory()
        value["status"] = "release_qualified"
        with self.assertRaisesRegex(
            VERIFIER.VerificationError, "identity or non-release status"
        ):
            self.verify_mutation(value, enforce_expected_digest=True)

    def test_package_deletion_fails_even_with_new_self_digest(self) -> None:
        value = self.load_inventory()
        value["packages"].pop()
        value["summary"]["package_count_union"] -= 1
        with self.assertRaisesRegex(VERIFIER.VerificationError, "1,047-package"):
            self.verify_mutation(value)

    def test_package_membership_change_fails_fixed_tree_set(self) -> None:
        value = self.load_inventory()
        package = next(
            item
            for item in value["packages"]
            if item["memberships"] == ["codex@linux/amd64"]
        )
        package["memberships"] = ["codex@linux/arm64"]
        with self.assertRaisesRegex(
            VERIFIER.VerificationError, "root-platform package set"
        ):
            self.verify_mutation(value)

    def test_registry_digest_change_fails_lock_crosscheck(self) -> None:
        value = self.load_inventory()
        package = next(
            item for item in value["packages"] if item["source_kind"] == "registry"
        )
        package["archive"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(VERIFIER.VerificationError, "Cargo.lock"):
            self.verify_mutation(value)

    def test_license_file_deletion_fails_fixed_derived_count(self) -> None:
        value = self.load_inventory()
        package = next(item for item in value["packages"] if item["license_files"])
        package["license_files"].pop()
        value["summary"]["registry_license_file_count"] -= 1
        with self.assertRaisesRegex(
            VERIFIER.VerificationError, "artifact or license counts"
        ):
            self.verify_mutation(value)

    def test_boolean_integer_confusion_is_rejected(self) -> None:
        value = self.load_inventory()
        value["packages"][0]["custom_build"] = 1
        with self.assertRaisesRegex(VERIFIER.VerificationError, "scalar field"):
            self.verify_mutation(value)

    def test_v8_false_attestation_claim_is_rejected(self) -> None:
        value = self.load_inventory()
        value["external_build_inputs"][0]["asset_signature_or_attestation"] = "verified"
        with self.assertRaisesRegex(
            VERIFIER.VerificationError, "rusty_v8 provenance boundary"
        ):
            self.verify_mutation(value)

    def test_open_gap_removal_is_rejected(self) -> None:
        value = self.load_inventory()
        value["qualification_limits"] = ["all inputs are qualified"] * 4
        with self.assertRaisesRegex(
            VERIFIER.VerificationError, "qualification limits"
        ):
            self.verify_mutation(value)

    def test_git_commit_substitution_is_rejected(self) -> None:
        value = self.load_inventory()
        value["git_sources"][0]["commit"] = "0" * 40
        with self.assertRaisesRegex(
            VERIFIER.VerificationError, "Git source archive binding"
        ):
            self.verify_mutation(value)

    def test_inventory_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / "inventory.json"
            path.symlink_to(self.inventory_path)
            with self.assertRaisesRegex(
                VERIFIER.VerificationError, "regular JSON file"
            ):
                VERIFIER.verify_inventory(
                    REPOSITORY_ROOT, inventory_path=path
                )

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "inventory.json"
            path.write_text('{"schema_version":1,"schema_version":2}\n')
            with self.assertRaisesRegex(VERIFIER.VerificationError, "duplicate JSON key"):
                VERIFIER.verify_inventory(REPOSITORY_ROOT, inventory_path=path)

    def test_effective_lock_mutation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.copy_repository_inputs(root)
            lock = root / "deploy/locks/codex-0.153.4/Cargo.lock.effective"
            lock.write_bytes(lock.read_bytes() + b"\n")
            with self.assertRaisesRegex(
                VERIFIER.VerificationError, "effective Cargo.lock"
            ):
                VERIFIER.verify_inventory(
                    root, inventory_path=self.inventory_path
                )

    def test_lock_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "deploy/locks/codex-0.153.4"
            destination.mkdir(parents=True)
            (destination / "Cargo.lock.source").symlink_to(
                REPOSITORY_ROOT
                / "deploy/locks/codex-0.153.4/Cargo.lock.source"
            )
            shutil.copy2(
                REPOSITORY_ROOT
                / "deploy/locks/codex-0.153.4/Cargo.lock.effective",
                destination / "Cargo.lock.effective",
            )
            with self.assertRaisesRegex(
                VERIFIER.VerificationError, "original Cargo.lock"
            ):
                VERIFIER.verify_inventory(
                    root, inventory_path=self.inventory_path
                )

    def test_missing_optional_registry_artifact_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                VERIFIER.VerificationError, "crates.io archive"
            ):
                VERIFIER.verify_inventory(
                    REPOSITORY_ROOT, cargo_cache=Path(temporary)
                )

    def test_wrong_optional_source_archive_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.tar.gz"
            path.write_bytes(b"not the pinned source")
            with self.assertRaisesRegex(
                VERIFIER.VerificationError, "Codex source archive"
            ):
                VERIFIER.verify_inventory(
                    REPOSITORY_ROOT, source_archive=path
                )


if __name__ == "__main__":
    unittest.main()
