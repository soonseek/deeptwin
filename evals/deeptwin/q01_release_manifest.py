"""Release-v3 pre-dispatch manifest check, shared by the harness and the sealed verifier.

``evals/deeptwin/qualification/release-v3/qualification_design.json`` (``pre_dispatch``)
requires a manifest, frozen by sha256 before the first dispatch, that fixes the
critic configuration and its digest, the run identity, the attempt number and
every prior attempt. The harness refuses to dispatch unless the manifest it
loads hashes to the committed value; the verifier checks the same value.

Canonical JSON (used for ``critic_configuration_digest``)::

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

DESIGN_DIR = Path(__file__).resolve().parent / "qualification" / "release-v3"
MANIFEST_SCHEMA_FILE = DESIGN_DIR / "pre_dispatch_manifest.schema.json"
DESIGN_ID = "q01-release-v3"
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def canonical_bytes(value) -> bytes:
    """The canonical JSON encoding named in the release-v3 design."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def critic_configuration_digest(configuration: dict) -> str:
    return sha256(canonical_bytes(configuration)).hexdigest()


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


def check_pre_dispatch_manifest(data: bytes | Path, *, committed_sha256: str | None,
                                harness: dict | None = None, verifier: dict | None = None) -> ManifestCheck:
    """Check one pre-dispatch manifest; never raises for a bad manifest.

    * the bytes hash to ``committed_sha256`` (``None`` or a non-hex value is an error:
      there is no dispatch without a committed value);
    * strict JSON that validates against ``pre_dispatch_manifest.schema.json``;
    * ``critic_configuration_digest`` recomputes from ``critic_configuration``;
    * ``attempt == len(prior_attempts) + 1`` and the prior attempts are numbered 1..k-1;
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
    prior = manifest["prior_attempts"]
    if manifest["attempt"] != len(prior) + 1:
        errors.append("attempt_does_not_follow_prior_attempts")
    elif [item["attempt"] for item in prior] != list(range(1, len(prior) + 1)):
        errors.append("prior_attempts_not_numbered_in_order")
    identity = manifest["run_identity"]
    if harness is not None and identity["harness"] != harness:
        errors.append("harness_identity_mismatch")
    if verifier is not None and identity["verifier"] != verifier:
        errors.append("verifier_identity_mismatch")
    return ManifestCheck(digest, manifest, tuple(errors))


def file_set_sha256(root: Path, relatives) -> str:
    """sha256 of the canonical JSON ``{relative path: file sha256}`` of a set of source files."""
    root = Path(root)
    return sha256(canonical_bytes({relative: sha256((root / relative).read_bytes()).hexdigest()
                                   for relative in relatives})).hexdigest()


__all__ = [
    "DESIGN_ID",
    "ManifestCheck",
    "canonical_bytes",
    "check_pre_dispatch_manifest",
    "critic_configuration_digest",
    "file_set_sha256",
    "is_sha256",
    "strict_json",
]
