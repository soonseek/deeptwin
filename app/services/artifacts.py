"""Purpose-scoped artifacts: originals, derived previews, range reads
(US3, T045 value slice; runtime.md §5, FR-015).

An artifact is bytes plus MIME, digest, size, provenance, access purposes
and availability — a hash whose bytes are gone is ``missing`` and never
counts as a reproducible original. A preview is a DERIVED artifact with its
own digest, an explicit fidelity note and disclosed coverage (covered spans
and omissions); deriving never touches the original, and a derived artifact
can never masquerade as an original. Range reads are purpose-scoped: a
purpose the artifact was never granted refuses, missing bytes refuse, and
every range is bounded by the real byte length. The browser viewers and the
actual byte store are separate concerns; this module owns the access
contract. Values are issued, never constructed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain.refs import DomainContractError, EntityRef

ACCESS_PURPOSES = frozenset({"operation", "tuning", "audit", "export"})
AVAILABILITIES = frozenset({"available", "missing"})
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ISSUE_TOKEN = object()


class ArtifactServiceError(ValueError):
    """An artifact registration, derivation or read is invalid."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _ref(value, kind, label):
    try:
        result = EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise ArtifactServiceError(f"invalid {label} reference") from exc
    if result.kind != kind:
        raise ArtifactServiceError(f"invalid {label} reference kind")
    return result


def _text(value, label, maximum=256):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        raise ArtifactServiceError(f"{label} is out of bounds")
    return value


@dataclass(frozen=True, slots=True, init=False)
class ArtifactEntry:
    """One original or derived artifact's access contract."""

    artifact_id: str
    media_type: str
    byte_length: int
    sha256: str
    provenance_ref: EntityRef | None
    access_purposes: tuple[str, ...]
    availability: str
    is_original: bool
    derived_from: str | None
    fidelity_note: str | None
    covered: tuple[str, ...]
    omissions: tuple[str, ...]
    _issuer_token: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True, init=False)
class ArtifactCatalog:
    """One catalog value; evolution only through the module functions."""

    entries: tuple[ArtifactEntry, ...]
    _issuer_token: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True, init=False)
class RangeDescriptor:
    """One admitted range read: exact offsets against the exact digest."""

    artifact_id: str
    sha256: str
    start: int
    length: int
    purpose: str


def _require_catalog(value) -> None:
    if (
        type(value) is not ArtifactCatalog
        or getattr(value, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise ArtifactServiceError(
            "a framework-issued artifact catalog is required"
        )


def open_artifact_catalog() -> ArtifactCatalog:
    return _issue(ArtifactCatalog, entries=(), _issuer_token=_ISSUE_TOKEN)


def _find(catalog: ArtifactCatalog, artifact_id: str) -> ArtifactEntry | None:
    return next(
        (item for item in catalog.entries if item.artifact_id == artifact_id),
        None,
    )


def _common(value, *, id_key):
    artifact_id = value[id_key]
    if type(artifact_id) is not str or _UUID.fullmatch(artifact_id) is None:
        raise ArtifactServiceError("artifact id is not a canonical UUID")
    sha = value["sha256"]
    if type(sha) is not str or _SHA256.fullmatch(sha) is None:
        raise ArtifactServiceError("the digest is invalid")
    byte_length = value["byte_length"]
    if type(byte_length) is not int or not 0 <= byte_length <= 2 ** 40:
        raise ArtifactServiceError("the byte length is out of bounds")
    return artifact_id, _text(value["media_type"], "media type", 128), \
        byte_length, sha


def register_artifact(catalog, value) -> ArtifactCatalog:
    """Register one original; a hash without bytes is missing, not an original."""

    _require_catalog(catalog)
    if type(value) is not dict or set(value) != {
        "artifact_id", "media_type", "byte_length", "sha256",
        "provenance_ref", "access_purposes", "availability",
    }:
        raise ArtifactServiceError("expected the exact artifact object")
    artifact_id, media_type, byte_length, sha = _common(
        value, id_key="artifact_id",
    )
    if _find(catalog, artifact_id) is not None:
        raise ArtifactServiceError("an artifact id registers exactly once")
    purposes = value["access_purposes"]
    if (
        type(purposes) is not list or not 1 <= len(purposes) <= 4
        or any(item not in ACCESS_PURPOSES for item in purposes)
        or len(set(purposes)) != len(purposes)
    ):
        raise ArtifactServiceError("access purposes are out of bounds")
    availability = value["availability"]
    if availability not in AVAILABILITIES:
        # Only two honest states exist: the bytes are here, or they are
        # gone — a missing artifact never counts as a reproducible original.
        raise ArtifactServiceError("unknown availability")
    entry = _issue(
        ArtifactEntry,
        artifact_id=artifact_id,
        media_type=media_type,
        byte_length=byte_length,
        sha256=sha,
        provenance_ref=_ref(
            value["provenance_ref"], "original_execution", "provenance",
        ),
        access_purposes=tuple(purposes),
        availability=availability,
        is_original=True,
        derived_from=None,
        fidelity_note=None,
        covered=(),
        omissions=(),
        _issuer_token=_ISSUE_TOKEN,
    )
    return _issue(
        ArtifactCatalog,
        entries=(*catalog.entries, entry),
        _issuer_token=_ISSUE_TOKEN,
    )


def derive_preview(catalog, artifact_id, value) -> ArtifactCatalog:
    """Derive one preview: own digest, explicit fidelity, disclosed coverage."""

    _require_catalog(catalog)
    original = _find(catalog, artifact_id)
    if original is None:
        raise ArtifactServiceError("unknown artifact id")
    if not original.is_original:
        raise ArtifactServiceError("a preview derives from an original")
    if original.availability != "available":
        raise ArtifactServiceError(
            "missing bytes derive nothing; absence stays absence"
        )
    if type(value) is not dict or set(value) != {
        "preview_id", "media_type", "byte_length", "sha256",
        "fidelity_note", "covered", "omissions",
    }:
        raise ArtifactServiceError("expected the exact preview object")
    preview_id, media_type, byte_length, sha = _common(
        value, id_key="preview_id",
    )
    if _find(catalog, preview_id) is not None:
        raise ArtifactServiceError("an artifact id registers exactly once")
    fidelity = _text(value["fidelity_note"], "fidelity note", 1_024)
    spans = {}
    for name in ("covered", "omissions"):
        items = value[name]
        if type(items) is not list or len(items) > 64 or any(
            type(item) is not str
            or not 1 <= len(item.encode("utf-8")) <= 256
            for item in items
        ):
            raise ArtifactServiceError(f"preview {name} are out of bounds")
        spans[name] = tuple(items)
    entry = _issue(
        ArtifactEntry,
        artifact_id=preview_id,
        media_type=media_type,
        byte_length=byte_length,
        sha256=sha,
        provenance_ref=original.provenance_ref,
        access_purposes=original.access_purposes,
        availability="available",
        is_original=False,
        derived_from=original.artifact_id,
        fidelity_note=fidelity,
        covered=spans["covered"],
        omissions=spans["omissions"],
        _issuer_token=_ISSUE_TOKEN,
    )
    return _issue(
        ArtifactCatalog,
        entries=(*catalog.entries, entry),
        _issuer_token=_ISSUE_TOKEN,
    )


def derived_coverage(catalog, artifact_id) -> dict:
    """What a derived artifact actually covers, and what it omits."""

    _require_catalog(catalog)
    entry = _find(catalog, artifact_id)
    if entry is None:
        raise ArtifactServiceError("unknown artifact id")
    if entry.is_original:
        raise ArtifactServiceError(
            "an original has no derived coverage; it IS the coverage"
        )
    return {
        "derived_from": entry.derived_from,
        "fidelity_note": entry.fidelity_note,
        "covered": entry.covered,
        "omissions": entry.omissions,
    }


def read_range(catalog, artifact_id, *, purpose, start, length) -> RangeDescriptor:
    """Admit one purpose-scoped bounded range read, or refuse."""

    _require_catalog(catalog)
    entry = _find(catalog, artifact_id)
    if entry is None:
        raise ArtifactServiceError("unknown artifact id")
    if purpose not in ACCESS_PURPOSES:
        raise ArtifactServiceError("unknown access purpose")
    if purpose not in entry.access_purposes:
        # Purpose scope is granted at registration, never at read time.
        raise ArtifactServiceError(
            "this artifact was never granted to that purpose"
        )
    if entry.availability != "available":
        raise ArtifactServiceError("missing bytes cannot be read")
    if (
        type(start) is not int or type(length) is not int
        or start < 0 or length < 1
        or start + length > entry.byte_length
    ):
        raise ArtifactServiceError("the range exceeds the real byte length")
    return _issue(
        RangeDescriptor,
        artifact_id=entry.artifact_id,
        sha256=entry.sha256,
        start=start,
        length=length,
        purpose=purpose,
    )


__all__ = [
    "ACCESS_PURPOSES",
    "AVAILABILITIES",
    "ArtifactCatalog",
    "ArtifactEntry",
    "ArtifactServiceError",
    "RangeDescriptor",
    "derive_preview",
    "derived_coverage",
    "open_artifact_catalog",
    "read_range",
    "register_artifact",
]
