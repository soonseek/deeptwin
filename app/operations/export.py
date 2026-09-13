"""Export: previewed scope, honest redaction, no circular hashes
(US7, T071; operations.md ExportRequest/Manifest/Receipt; FR-028/029).

An export request names its exact scope and categories — hidden reasoning
and credentials are not selectable, and raw originals are included only by
explicit selection on the request. The manifest distinguishes the original
source hash from the exported bytes hash (`source_sha256` exists only when
raw inclusion was explicit), keeps missing-evidence reasons distinct
(redaction, non-selection and real record gaps are never one error), uses
restricted relative paths only, and never re-exposes bodies, real paths or
keys — a supplied secret canary appearing anywhere in the manifest refuses
the build. The receipt is a record OUTSIDE the archive: the manifest never
contains the archive's own hash, and the receipt binds the manifest hash
and the bundle hash together. Nothing here transmits anything anywhere.
Values are issued, never constructed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256

from ..domain.refs import DomainContractError, EntityRef, canonical_json
from ..runtime.gateway import carries_host_path

EXPORT_CATEGORIES = frozenset({
    "events", "artifacts_metadata", "originals", "model_final_responses",
    "tool_observations", "alternatives", "evaluation_evidence",
})
CONTENT_MODES = frozenset({"raw", "redacted", "metadata_only"})
MISSING_REASONS = frozenset({
    "not_selected", "redacted", "deleted", "unavailable",
    "not_recorded", "access_denied", "rights_restricted",
})
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_ISSUE_TOKEN = object()


class ExportError(ValueError):
    """An export request, manifest or receipt is invalid."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _ref(value, kind, label):
    try:
        result = EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise ExportError(f"invalid {label} reference") from exc
    if result.kind != kind:
        raise ExportError(f"invalid {label} reference kind")
    return result


def _text(value, label, maximum=256):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        raise ExportError(f"{label} is out of bounds")
    return value


@dataclass(frozen=True, slots=True, init=False)
class ExportRequest:
    """One explicit export selection; settings alone export nothing."""

    request_id: str
    scope: str
    selected_categories: tuple[str, ...]
    include_raw_refs: tuple[EntityRef, ...]
    redaction_policy_ref: EntityRef
    author_consent_ref: EntityRef
    created_at: str
    _issuer_token: object = field(repr=False, compare=False)


def create_export_request(value) -> ExportRequest:
    if type(value) is not dict or set(value) != {
        "request_id", "scope", "selected_categories", "include_raw_refs",
        "redaction_policy_ref", "author_consent_ref", "created_at",
    }:
        raise ExportError("expected the exact export request object")
    request_id = value["request_id"]
    if type(request_id) is not str or _UUID.fullmatch(request_id) is None:
        raise ExportError("request id is not a canonical UUID")
    categories = value["selected_categories"]
    if (
        type(categories) is not list or not 1 <= len(categories) <= 8
        or any(item not in EXPORT_CATEGORIES for item in categories)
        or len(set(categories)) != len(categories)
    ):
        # Hidden reasoning and credentials are not in the closed set: they
        # are not selectable items at all.
        raise ExportError("selected categories are out of bounds")
    raw_refs_value = value["include_raw_refs"]
    if type(raw_refs_value) is not list or len(raw_refs_value) > 64:
        raise ExportError("raw inclusion refs are out of bounds")
    raw_refs = tuple(
        _ref(item, "artifact", "raw inclusion") for item in raw_refs_value
    )
    created_at = value["created_at"]
    if type(created_at) is not str or _STAMP.fullmatch(created_at) is None:
        raise ExportError("created time must be a canonical UTC timestamp")
    return _issue(
        ExportRequest,
        request_id=request_id,
        scope=_text(value["scope"], "scope", 512),
        selected_categories=tuple(sorted(categories)),
        include_raw_refs=raw_refs,
        redaction_policy_ref=_ref(
            value["redaction_policy_ref"], "access_policy", "redaction policy",
        ),
        author_consent_ref=_ref(
            value["author_consent_ref"], "run_consent", "author consent",
        ),
        created_at=created_at,
        _issuer_token=_ISSUE_TOKEN,
    )


@dataclass(frozen=True, slots=True, init=False)
class ExportItem:
    """One exported entry; exported bytes and source hashes stay distinct."""

    export_id: str
    kind: str
    relative_path: str
    media_type: str
    size_bytes: int
    export_sha256: str
    linked_export_ids: tuple[str, ...]
    content_mode: str
    source_hash_included: bool
    source_sha256: str | None
    license_or_share_basis: str | None


@dataclass(frozen=True, slots=True, init=False)
class MissingEvidence:
    """One explicit gap; its reason is never merged with another kind."""

    export_ref: str
    reason: str
    affected_claims: tuple[str, ...]
    recoverable_by_user: bool


@dataclass(frozen=True, slots=True, init=False)
class ExportManifest:
    """The manifest; it never contains the archive's own hash."""

    request_id: str
    scope: str
    items: tuple[ExportItem, ...]
    missing_evidence: tuple[MissingEvidence, ...]
    redaction_summary: tuple[tuple[str, int], ...]
    checksum_algorithm: str
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": "export-manifest-v1",
            "request_id": self.request_id,
            "scope": self.scope,
            "items": [
                {
                    "export_id": item.export_id,
                    "kind": item.kind,
                    "relative_path": item.relative_path,
                    "media_type": item.media_type,
                    "size_bytes": item.size_bytes,
                    "export_sha256": item.export_sha256,
                    "linked_export_ids": list(item.linked_export_ids),
                    "content_mode": item.content_mode,
                    "source_hash_included": item.source_hash_included,
                    "source_sha256": item.source_sha256,
                    "license_or_share_basis": item.license_or_share_basis,
                }
                for item in self.items
            ],
            "missing_evidence": [
                {
                    "export_ref": entry.export_ref,
                    "reason": entry.reason,
                    "affected_claims": list(entry.affected_claims),
                    "recoverable_by_user": entry.recoverable_by_user,
                }
                for entry in self.missing_evidence
            ],
            "redaction_summary": dict(self.redaction_summary),
            "checksum_algorithm": self.checksum_algorithm,
        }

    @property
    def manifest_sha(self) -> str:
        return sha256(canonical_json(self.as_dict())).hexdigest()


def _restricted_path(value: str) -> str:
    _text(value, "relative path", 512)
    if carries_host_path(value):
        raise ExportError("archive paths are restricted relative paths only")
    return value


def _scan_canaries(payload: str, canaries) -> None:
    for canary in canaries:
        if canary and canary in payload:
            # A secret anywhere in the manifest refuses the whole build.
            raise ExportError("the manifest carries a secret canary")


def build_export_manifest(request, items, missing, *, secret_canaries):
    """Build one manifest honestly; nothing is transmitted anywhere."""

    if (
        type(request) is not ExportRequest
        or getattr(request, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise ExportError("a framework-issued export request is required")
    if type(secret_canaries) is not list or len(secret_canaries) > 64:
        raise ExportError("secret canaries are out of bounds")
    if type(items) is not list or not 1 <= len(items) <= 4_096:
        raise ExportError("export items are out of bounds")
    raw_allowed = len(request.include_raw_refs) > 0
    parsed_items = []
    redactions: dict[str, int] = {}
    for value in items:
        if type(value) is not dict or set(value) != {
            "export_id", "kind", "relative_path", "media_type",
            "size_bytes", "export_sha256", "linked_export_ids",
            "content_mode", "source_hash_included", "source_sha256",
            "license_or_share_basis",
        }:
            raise ExportError("expected the exact export item object")
        content_mode = value["content_mode"]
        if content_mode not in CONTENT_MODES:
            raise ExportError("unknown content mode")
        if content_mode == "raw" and not raw_allowed:
            # Raw originals exist in a bundle only by explicit selection.
            raise ExportError(
                "raw content requires explicit raw inclusion on the request"
            )
        included = value["source_hash_included"]
        if type(included) is not bool:
            raise ExportError("source inclusion must be explicit")
        source_sha = value["source_sha256"]
        if included:
            if type(source_sha) is not str or _SHA256.fullmatch(source_sha) is None:
                raise ExportError("an included source hash is invalid")
        elif source_sha is not None:
            # A source hash without explicit inclusion re-exposes the
            # original identity; absence stays absence.
            raise ExportError(
                "source hashes exist only with explicit inclusion"
            )
        export_sha = value["export_sha256"]
        if type(export_sha) is not str or _SHA256.fullmatch(export_sha) is None:
            raise ExportError("an export hash is invalid")
        size = value["size_bytes"]
        if type(size) is not int or not 0 <= size <= 2 ** 40:
            raise ExportError("item size is out of bounds")
        linked = value["linked_export_ids"]
        if type(linked) is not list or len(linked) > 64 or any(
            type(item) is not str for item in linked
        ):
            raise ExportError("linked export ids are out of bounds")
        basis = value["license_or_share_basis"]
        if basis is not None:
            basis = _text(basis, "share basis", 512)
        if content_mode == "redacted":
            redactions[value["kind"]] = redactions.get(value["kind"], 0) + 1
        parsed_items.append(_issue(
            ExportItem,
            export_id=_text(value["export_id"], "export id", 128),
            kind=_text(value["kind"], "item kind", 128),
            relative_path=_restricted_path(value["relative_path"]),
            media_type=_text(value["media_type"], "media type", 128),
            size_bytes=size,
            export_sha256=export_sha,
            linked_export_ids=tuple(linked),
            content_mode=content_mode,
            source_hash_included=included,
            source_sha256=source_sha if included else None,
            license_or_share_basis=basis,
        ))
    if type(missing) is not list or len(missing) > 1_024:
        raise ExportError("missing evidence entries are out of bounds")
    parsed_missing = []
    for value in missing:
        if type(value) is not dict or set(value) != {
            "export_ref", "reason", "affected_claims", "recoverable_by_user",
        }:
            raise ExportError("expected the exact missing evidence object")
        reason = value["reason"]
        if reason not in MISSING_REASONS:
            # Redaction, non-selection and real gaps stay distinct reasons.
            raise ExportError("unknown missing-evidence reason")
        claims = value["affected_claims"]
        if type(claims) is not list or len(claims) > 32 or any(
            type(item) is not str
            or not 1 <= len(item.encode("utf-8")) <= 512
            for item in claims
        ):
            raise ExportError("affected claims are out of bounds")
        recoverable = value["recoverable_by_user"]
        if type(recoverable) is not bool:
            raise ExportError("recoverability must be explicit")
        parsed_missing.append(_issue(
            MissingEvidence,
            export_ref=_text(value["export_ref"], "export ref", 128),
            reason=reason,
            affected_claims=tuple(claims),
            recoverable_by_user=recoverable,
        ))
    manifest = _issue(
        ExportManifest,
        request_id=request.request_id,
        scope=request.scope,
        items=tuple(parsed_items),
        missing_evidence=tuple(parsed_missing),
        redaction_summary=tuple(sorted(redactions.items())),
        checksum_algorithm="sha256",
        _issuer_token=_ISSUE_TOKEN,
    )
    _scan_canaries(
        canonical_json(manifest.as_dict()).decode("utf-8"), secret_canaries,
    )
    return manifest


@dataclass(frozen=True, slots=True, init=False)
class ExportReceipt:
    """The confirmation record OUTSIDE the completed archive."""

    bundle_id: str
    manifest_sha256: str
    bundle_sha256: str
    size_bytes: int
    completed_at: str
    artifact_ref: EntityRef


def seal_export(manifest, *, bundle_sha256, size_bytes, completed_at,
                artifact_ref) -> ExportReceipt:
    """Bind the manifest and bundle hashes outside the archive itself."""

    if (
        type(manifest) is not ExportManifest
        or getattr(manifest, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise ExportError("a framework-issued export manifest is required")
    if type(bundle_sha256) is not str or _SHA256.fullmatch(bundle_sha256) is None:
        raise ExportError("the bundle hash is invalid")
    if type(size_bytes) is not int or not 1 <= size_bytes <= 2 ** 40:
        raise ExportError("the bundle size is out of bounds")
    if type(completed_at) is not str or _STAMP.fullmatch(completed_at) is None:
        raise ExportError("completed time must be a canonical UTC timestamp")
    return _issue(
        ExportReceipt,
        bundle_id=manifest.request_id,
        manifest_sha256=manifest.manifest_sha,
        bundle_sha256=bundle_sha256,
        size_bytes=size_bytes,
        completed_at=completed_at,
        artifact_ref=_ref(artifact_ref, "artifact", "bundle artifact"),
    )


__all__ = [
    "CONTENT_MODES",
    "EXPORT_CATEGORIES",
    "MISSING_REASONS",
    "ExportError",
    "ExportItem",
    "ExportManifest",
    "ExportReceipt",
    "ExportRequest",
    "MissingEvidence",
    "build_export_manifest",
    "create_export_request",
    "seal_export",
]
