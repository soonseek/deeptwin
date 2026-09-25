"""Release-v4 pre-dispatch manifest check, shared by the harness and the sealed verifier.

``evals/deeptwin/qualification/release-v4/qualification_design.json`` (``pre_dispatch``)
requires a manifest, frozen by sha256 before the first dispatch, that fixes the
critic configuration and its digest, the run identity, the attempt number and
every prior attempt, the author/reviewer/sealing attestations and, for a
lens-effect run, every arm's critic configuration, text digest and attempt entry
and the arm x case order (``pre_dispatch_manifest.schema.json``, schema v2). The
harness refuses to dispatch unless the manifest it loads hashes to the committed
value; the verifier checks the same value.

Canonical JSON (used for ``critic_configuration_digest`` and lens digests)::

    json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
               allow_nan=False).encode("utf-8")

The manifest's own sha256 is over the exact file bytes that were committed,
never over a re-serialization. This module holds no expectations and reads no
case materials; it imports neither the harness nor any verifier.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

DESIGN_DIR = Path(__file__).resolve().parent / "qualification" / "release-v4"
MANIFEST_SCHEMA_FILE = DESIGN_DIR / "pre_dispatch_manifest.schema.json"
DESIGN_ID = "q01-release-v4"
EFFECT_DESIGN_ID = "lens-effects-v4"
# lens-effects-v4 arms that are dispatched; strong_existing_procedure is a
# duplicate of no_lens and user_construct is not runnable, so neither appears.
BASELINE_ARM = "no_lens"
TEXT_ARMS = frozenset({"general_multi_perspective", "single_L-P050-01", "single_L-P033-02", "mix"})
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def canonical_bytes(value) -> bytes:
    """The canonical JSON encoding named in the release designs."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def critic_configuration_digest(configuration: dict) -> str:
    return sha256(canonical_bytes(configuration)).hexdigest()


def lens_refs_and_digests(pack: dict) -> dict:
    """The ``critic_configuration.lens_refs_and_digests`` value of one lens pack.

    The pack is critic configuration, never dataset material: its id, version and
    canonical sha256, and each rule's id, version and canonical sha256 in order. The
    digests equal the ``lens_pack`` / ``lens_rules`` entries of the product's prepared
    input manifest for the same pack.
    """
    if type(pack) is not dict or type(pack.get("rules")) is not list:
        raise ValueError("a lens pack object is required")
    return {"pack_id": pack["id"], "pack_version": pack["version"],
            "pack_sha256": sha256(canonical_bytes(pack)).hexdigest(),
            "rules": [{"lens_id": rule["id"], "version": rule["version"],
                       "sha256": sha256(canonical_bytes(rule)).hexdigest()} for rule in pack["rules"]]}


def prepared_lens_refs(prepared_manifest: dict) -> dict | None:
    """The same value, read back from a prepared input manifest (``None`` without a pack)."""
    pack = prepared_manifest.get("lens_pack")
    if pack is None:
        return None
    return {"pack_id": pack["id"], "pack_version": pack["version"], "pack_sha256": pack["sha256"],
            "rules": [{"lens_id": rule["id"], "version": rule["version"], "sha256": rule["sha256"]}
                      for rule in prepared_manifest.get("lens_rules", [])]}


def is_sha256(value) -> bool:
    return type(value) is str and _HEX.fullmatch(value) is not None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(_value):
    raise ValueError("nonfinite JSON constant")


def strict_json(data: bytes):
    """Parse UTF-8 JSON bytes, refusing duplicate keys and NaN/Infinity."""
    return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_nonfinite)


def _schema_validator(path: Path) -> Draft202012Validator:
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@dataclass(frozen=True)
class ManifestCheck:
    """Outcome of one pre-dispatch manifest check. ``ok`` only when ``errors`` is empty."""

    manifest_sha256: str | None
    manifest: dict | None
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def _attempt_errors(attempt, prior, label):
    if attempt != len(prior) + 1:
        return [f"{label}attempt_does_not_follow_prior_attempts"]
    if [item["attempt"] for item in prior] != list(range(1, len(prior) + 1)):
        return [f"{label}prior_attempts_not_numbered_in_order"]
    return []


def _lens_effect_errors(manifest) -> list[str]:
    """lens-effects-v4: one sealed effect set, one run covering every arm."""
    effect = manifest["lens_effect"]
    if effect is None:
        return []
    errors = []
    identity, configuration = manifest["run_identity"], manifest["critic_configuration"]
    arms = effect["arms"]
    ids = [arm["id"] for arm in arms]
    if len(set(ids)) != len(ids):
        errors.append("lens_effect:duplicate_arm")
    if BASELINE_ARM not in ids:
        errors.append("lens_effect:no_baseline_arm")
    if effect["effect_set_sha256"] != identity["sealed_dataset_sha256"]:
        errors.append("lens_effect:effect_set_is_not_the_sealed_dataset")
    held = {name: value for name, value in configuration.items() if name != "lens_refs_and_digests"}
    for arm in arms:
        label = f"lens_effect:{arm['id']}:"
        arm_configuration = arm["critic_configuration"]
        if critic_configuration_digest(arm_configuration) != arm["critic_configuration_digest"]:
            errors.append(label + "critic_configuration_digest_mismatch")
        if {name: value for name, value in arm_configuration.items() if name != "lens_refs_and_digests"} != held:
            errors.append(label + "differs_from_the_run_configuration_beyond_its_lens_set")
        lenses = arm_configuration["lens_refs_and_digests"]
        if arm["id"] == BASELINE_ARM:
            if arm["text_sha256"] is not None or lenses["rules"]:
                errors.append(label + "baseline_carries_lens_text")
            if arm["critic_configuration_digest"] != manifest["critic_configuration_digest"]:
                errors.append(label + "baseline_is_not_the_run_configuration")
        elif arm["id"] in TEXT_ARMS:
            if arm["text_sha256"] is None:
                errors.append(label + "text_digest_not_fixed_before_dispatch")
            elif arm["text_sha256"] != lenses["pack_sha256"]:
                errors.append(label + "text_digest_is_not_the_sent_lens_pack")
        errors += _attempt_errors(arm["attempt"], arm["prior_attempts"], label)
    order = [(item["arm"], item["case_id"]) for item in effect["arm_case_order"]]
    planned = {(arm_id, case_id) for arm_id in ids for case_id in identity["case_order"]["order"]}
    if len(order) != len(set(order)) or set(order) != planned:
        errors.append("lens_effect:arm_case_order_is_not_every_arm_on_every_case_once")
    return errors


def _attestation_errors(manifest) -> list[str]:
    attestations, judge = manifest["attestations"], manifest["run_identity"]["judge_identity"]
    names = [attestations[role]["name"] for role in ("author", "reviewer")]
    errors = []
    if names[0] == names[1]:
        errors.append("attestation:author_is_reviewer")
    if judge in names:
        errors.append("attestation:judge_is_author_or_reviewer")
    return errors


def check_pre_dispatch_manifest(data: bytes | Path, *, committed_sha256: str | None,
                                harness: dict | None = None, verifier: dict | None = None) -> ManifestCheck:
    """Check one pre-dispatch manifest; never raises for a bad manifest.

    * the bytes hash to ``committed_sha256`` (``None`` or a non-hex value is an error:
      there is no dispatch without a committed value);
    * strict JSON that validates against ``pre_dispatch_manifest.schema.json`` (v2);
    * ``critic_configuration_digest`` recomputes from ``critic_configuration``;
    * ``attempt == len(prior_attempts) + 1`` and the prior attempts are numbered 1..k-1;
    * the author, reviewer and judge are three different identities;
    * a lens-effect section satisfies ``_lens_effect_errors``;
    * optionally, ``run_identity.harness`` / ``run_identity.verifier`` equal the given
      ``{"version", "sha256"}`` of the code that is about to run.
    """
    errors: list[str] = []
    if isinstance(data, Path):
        try:
            data = data.read_bytes()
        except OSError:
            return ManifestCheck(None, None, ("manifest_unreadable",))
    if type(data) is not bytes:
        return ManifestCheck(None, None, ("manifest_not_bytes",))
    digest = sha256(data).hexdigest()
    if not is_sha256(committed_sha256):
        errors.append("no_committed_manifest_sha256")
    elif digest != committed_sha256:
        errors.append("manifest_sha256_differs_from_committed")
    try:
        manifest = strict_json(data)
    except (ValueError, UnicodeDecodeError):
        return ManifestCheck(digest, None, (*errors, "manifest_not_strict_json"))
    schema_error = best_match(_schema_validator(MANIFEST_SCHEMA_FILE).iter_errors(manifest))
    if schema_error is not None:
        errors.append("manifest_schema:/" + "/".join(map(str, schema_error.absolute_path)))
        return ManifestCheck(digest, manifest if type(manifest) is dict else None, tuple(errors))
    if critic_configuration_digest(manifest["critic_configuration"]) != manifest["critic_configuration_digest"]:
        errors.append("critic_configuration_digest_mismatch")
    errors += _attempt_errors(manifest["attempt"], manifest["prior_attempts"], "")
    order = manifest["run_identity"]["case_order"]["order"]
    if len(set(order)) != len(order):
        errors.append("case_order_repeats_a_case")
    errors += _attestation_errors(manifest)
    errors += _lens_effect_errors(manifest)
    identity = manifest["run_identity"]
    if harness is not None and identity["harness"] != harness:
        errors.append("harness_identity_mismatch")
    if verifier is not None and identity["verifier"] != verifier:
        errors.append("verifier_identity_mismatch")
    return ManifestCheck(digest, manifest, tuple(errors))


def schema_valid(check: ManifestCheck) -> bool:
    return check.manifest is not None and not any(
        error.startswith(("manifest_schema", "manifest_not")) for error in check.errors)


def file_set_sha256(root: Path, relatives) -> str:
    """sha256 of the canonical JSON ``{relative path: file sha256}`` of a set of source files."""
    root = Path(root)
    return sha256(canonical_bytes({relative: sha256((root / relative).read_bytes()).hexdigest()
                                   for relative in relatives})).hexdigest()


__all__ = [
    "DESIGN_ID",
    "EFFECT_DESIGN_ID",
    "ManifestCheck",
    "canonical_bytes",
    "check_pre_dispatch_manifest",
    "critic_configuration_digest",
    "file_set_sha256",
    "is_sha256",
    "lens_refs_and_digests",
    "prepared_lens_refs",
    "schema_valid",
    "strict_json",
]
