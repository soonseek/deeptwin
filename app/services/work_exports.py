"""The owner's export of one work: actual-content preview, bound consent, sealed bundle
(US7, T073 server half; operations.md export flow, FR-028/029, UX-AC08).

`preview` reads what the export would ACTUALLY contain right now — every revision
of the work (raw text only when the owner explicitly asks for raw originals,
otherwise metadata only), the work's revision history, and the sources its
revisions name — and states every selected category this server does not collect
yet as `unavailable` and every unselected one as `not_selected`, never as an
empty success. The preview is not stored: its `preview_sha` digests the request
id, the selection and every item's exact bytes, so `confirm` recomputes it and a
work that changed in between refuses (`conflict`) instead of exporting something
the owner never saw. Confirmation must be explicit (`confirmed: true`) and binds
the exact digest; it seals the owner's consent, the raw-inclusion artifacts, the
manifest (through `app.operations.export`, which never carries the archive's own
hash) and the bundle, and returns the external receipt. Nothing is transmitted:
the bundle is downloaded only by the owner through `download`.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
from uuid import uuid4

from ..domain.refs import EntityRef, canonical_json, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import BlobRef, _writer
from ..operations.export import (
    EXPORT_CATEGORIES,
    ExportError,
    build_export_manifest,
    create_export_request,
    seal_export,
)
from .owner_auth import OwnerAuthError
from .run_approvals import _authenticate_owner, _owner_actor_ref
from .works import PersistentWorks, WorkServiceError

__all__ = ["CONFIRM_SCHEMA", "PREVIEW_SCHEMA", "PersistentWorkExports"]

PREVIEW_SCHEMA = "work-export-preview-v1"
CONFIRM_SCHEMA = "work-export-confirm-v1"
MAX_REVISIONS = 512
APP_RELEASE = "deeptwin-dev"
# selected categories whose records this server does not yet collect into an export
UNCOLLECTED = frozenset({"model_final_responses", "tool_observations", "alternatives",
                         "evaluation_evidence"})
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (WorkServiceError, OwnerAuthError):
            raise
        except ExportError:
            raise WorkServiceError("invalid_input") from None
        except Exception:  # noqa: BLE001 - storage errors must not disclose detail
            raise WorkServiceError("unavailable") from None

    return invoke


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _selection(payload, *, confirm):
    fields = {"schema_version", "request_id", "categories", "include_raw"}
    if confirm:
        fields |= {"preview_sha", "confirmed"}
    if type(payload) is not dict or set(payload) != fields:
        raise WorkServiceError("invalid_input")
    if payload["schema_version"] != (CONFIRM_SCHEMA if confirm else PREVIEW_SCHEMA):
        raise WorkServiceError("invalid_input")
    try:
        request_id = uuid_string(payload["request_id"])
    except (TypeError, ValueError):
        raise WorkServiceError("invalid_input") from None
    categories = payload["categories"]
    if (type(categories) is not list or not 1 <= len(categories) <= len(EXPORT_CATEGORIES)
            or len(set(categories)) != len(categories)
            or any(item not in EXPORT_CATEGORIES for item in categories)):
        raise WorkServiceError("invalid_input")
    if type(payload["include_raw"]) is not bool:
        raise WorkServiceError("invalid_input")
    if payload["include_raw"] and "originals" not in categories:
        raise WorkServiceError("invalid_input")  # raw inclusion is a choice about originals
    return request_id, tuple(sorted(categories)), payload["include_raw"]


class PersistentWorkExports:
    """Owner-authenticated export of one work over the actual domain store."""

    def __init__(self, works):
        if type(works) is not PersistentWorks:
            raise TypeError("Exact PersistentWorks required")
        self._works = works
        self._domain = works._domain
        self._owner = works._owner

    # --- what the export actually contains ---------------------------------------

    def _revisions(self, db, roots, work_id):
        latest = self._works._latest(db, roots, work_id)
        if latest is None:
            raise WorkServiceError("not_found")
        if latest.ref.version > MAX_REVISIONS:
            raise WorkServiceError("too_large")
        return [self._works._version(db, roots, work_id, version)
                for version in range(1, latest.ref.version + 1)]

    @staticmethod
    def _collect(revisions, categories, include_raw):
        """(items with their exact bytes, missing entries), deterministically ordered."""

        items, missing = [], []

        def add(category, path, media_type, data, *, mode, label):
            items.append({"category": category, "relative_path": path, "media_type": media_type,
                          "data": data, "content_mode": mode, "label": label})

        if "originals" in categories:
            for record in revisions:
                content = record.body["content"]
                number = record.ref.version
                if include_raw:
                    add("originals", f"originals/revision-{number}.txt", "text/plain; charset=utf-8",
                        content["text"].encode("utf-8"), mode="raw", label=f"작업 설명 {number}판 원문")
                else:
                    add("originals", f"originals/revision-{number}.json", "application/json",
                        _json({"revision": number, "created_at_utc": record.body["created_at_utc"],
                               "characters": len(content["text"]), "text": "원문 미포함"}),
                        mode="metadata_only", label=f"작업 설명 {number}판 (원문 제외)")
        if "events" in categories:
            add("events", "events/work-history.json", "application/json", _json([
                {"revision": record.ref.version, "created_at_utc": record.body["created_at_utc"],
                 "input_origin": record.body["content"].get("input_origin", "owner_text"),
                 "source_count": len(record.body["content"].get("source_refs", []))}
                for record in revisions]), mode="metadata_only", label="작업 개정 기록")
        if "artifacts_metadata" in categories:
            sources = sorted({json.dumps(ref, sort_keys=True) for record in revisions
                              for ref in record.body["content"].get("source_refs", [])})
            if sources:
                add("artifacts_metadata", "artifacts/sources.json", "application/json",
                    _json([{"kind": json.loads(item)["kind"], "id": json.loads(item)["id"],
                            "version": json.loads(item)["version"]} for item in sources]),
                    mode="metadata_only", label=f"첨부 자료 {len(sources)}개의 목록")
            else:
                missing.append({"category": "artifacts_metadata", "reason": "not_recorded",
                                "claim": "이 작업에는 첨부 자료가 없다."})
        for category in sorted(EXPORT_CATEGORIES):
            if category not in categories:
                missing.append({"category": category, "reason": "not_selected",
                                "claim": "내보내기에서 선택하지 않았다."})
            elif category in UNCOLLECTED:
                missing.append({"category": category, "reason": "unavailable",
                                "claim": "이 서버의 내보내기는 아직 이 범주를 모으지 않는다."})
        for index, item in enumerate(items):
            item["export_id"] = f"item-{index + 1}"
            item["size_bytes"] = len(item["data"])
            item["export_sha256"] = sha256(item["data"]).hexdigest()
        return items, missing

    @staticmethod
    def _preview_value(work_id, request_id, categories, include_raw, items, missing):
        shown = [{name: item[name] for name in ("export_id", "category", "relative_path",
                                                 "media_type", "size_bytes", "export_sha256",
                                                 "content_mode", "label")} for item in items]
        digest = sha256(canonical_json({
            "work_id": work_id, "request_id": request_id, "categories": list(categories),
            "include_raw": include_raw, "items": shown, "missing": missing,
        })).hexdigest()
        return {"request_id": request_id, "work_id": work_id, "preview_sha": digest,
                "categories": list(categories), "include_raw": include_raw,
                "items": shown, "missing": missing, "exportable": bool(shown)}

    def _current(self, db, roots, work_id, request_id, categories, include_raw):
        revisions = self._revisions(db, roots, work_id)
        items, missing = self._collect(revisions, categories, include_raw)
        preview = self._preview_value(work_id, request_id, categories, include_raw, items, missing)
        return revisions, items, missing, preview

    @_closed
    def preview(self, request, work_id, payload) -> dict:
        """What the export would contain now; reads only, stores nothing."""

        work_id = uuid_string(work_id)
        request_id, categories, include_raw = _selection(payload, confirm=False)
        _authenticate_owner(self._owner, request)
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            return self._current(db, roots, work_id, request_id, categories, include_raw)[3]

    # --- the explicit, bound confirmation ------------------------------------------

    @staticmethod
    def _bundle(manifest_dict, items) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in (("manifest.json", _json(manifest_dict)),
                               *((item["relative_path"], item["data"]) for item in items)):
                info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, data)
        return buffer.getvalue()

    def _record(self, db, roots, actor_ref, kind, content, parents, *, record_id=None):
        record = ImmutableRecord.create(
            kind=kind, id=record_id or str(uuid4()), version=1, created_at_utc=_stamp(),
            actor_ref=actor_ref, parent_refs=tuple(parents), purpose="operational",
            access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
            content=content,
        )
        self._domain._put_in_transaction(db, record)
        return record.ref

    @_closed
    def confirm(self, request, work_id, payload) -> dict:
        work_id = uuid_string(work_id)
        request_id, categories, include_raw = _selection(payload, confirm=True)
        if payload["confirmed"] is not True:
            raise WorkServiceError("invalid_input")  # consent is never implicit
        shown = payload["preview_sha"]
        _authenticate_owner(self._owner, request)
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            if self._for_request(db, roots, request_id):
                raise WorkServiceError("conflict")  # one bundle per request id
            _revisions, items, _missing, preview = self._current(
                db, roots, work_id, request_id, categories, include_raw)
        if not preview["exportable"]:
            raise WorkServiceError("invalid_input")  # nothing selected exists to export
        if preview["preview_sha"] != shown:
            # the work (or the selection) differs from what the owner saw and consented to
            raise WorkServiceError("conflict")
        created_at = _stamp()
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            if self._for_request(db, roots, request_id):
                raise WorkServiceError("conflict")
            revisions, items, missing, again = self._current(
                db, roots, work_id, request_id, categories, include_raw)
            if again["preview_sha"] != shown:
                raise WorkServiceError("conflict")
            latest = revisions[-1].ref
            consent = self._record(db, roots, actor_ref, "run_consent", {
                "export_consent": {"work_id": work_id, "request_id": request_id,
                                   "preview_sha": shown, "categories": list(categories),
                                   "include_raw": include_raw}}, (latest,))
            raw_refs, by_revision = [], {record.ref.version: record.ref for record in revisions}
            for item in items:
                if item["content_mode"] == "raw":
                    number = int(item["relative_path"].rsplit("-", 1)[1].split(".")[0])
                    raw_refs.append(self._record(db, roots, actor_ref, "artifact", {
                        "export_original": {"revision": number, "export_sha256": item["export_sha256"],
                                            "media_type": item["media_type"]}},
                        (by_revision[number], consent)))
            export_request = create_export_request({
                "request_id": request_id, "scope": f"work:{work_id}",
                "selected_categories": list(categories),
                "include_raw_refs": [ref.as_dict() for ref in raw_refs],
                "redaction_policy_ref": roots.access_policy.as_dict(),
                "author_consent_ref": consent.as_dict(), "created_at": created_at,
            })
            manifest = build_export_manifest(
                export_request,
                [{"export_id": item["export_id"], "kind": item["category"],
                  "relative_path": item["relative_path"], "media_type": item["media_type"],
                  "size_bytes": item["size_bytes"], "export_sha256": item["export_sha256"],
                  "linked_export_ids": [], "content_mode": item["content_mode"],
                  "source_hash_included": False, "source_sha256": None,
                  "license_or_share_basis": None} for item in items],
                [{"export_ref": entry["category"], "reason": entry["reason"],
                  "affected_claims": [entry["claim"]],
                  "recoverable_by_user": entry["reason"] == "not_selected"} for entry in missing],
                secret_canaries=[], created_at=created_at, app_release=APP_RELEASE,
                pseudonym_map_scope=f"work:{work_id}",
                reproduction_limits=["모델·도구 실행 기록은 이 내보내기에 포함되지 않았다."],
            )
            manifest_dict = manifest.as_dict()
            bundle = self._bundle(manifest_dict, items)
        blob = self._domain.put_blob(bundle, purpose="operational")
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            if self._for_request(db, roots, request_id):
                raise WorkServiceError("conflict")  # one bundle per request id
            bundle_id = manifest.bundle_id
            artifact = self._record(db, roots, actor_ref, "artifact", {
                "export_bundle": {"bundle_id": bundle_id, "media_type": "application/zip"},
                "blob": blob.as_dict()}, (consent,))
            receipt = seal_export(manifest, bundle_sha256=blob.sha256, size_bytes=blob.size,
                                  completed_at=_stamp(), artifact_ref=artifact.as_dict())
            receipt_value = {
                "bundle_id": receipt.bundle_id, "manifest_sha256": receipt.manifest_sha256,
                "bundle_sha256": receipt.bundle_sha256, "size_bytes": receipt.size_bytes,
                "completed_at": receipt.completed_at,
            }
            self._record(db, roots, actor_ref, "export_manifest", {
                # the manifest's own `export_ref` names an entry, not a record: kept as its
                # exact canonical text, so the store never reads it as a reference
                "work_id": work_id, "request_id": request_id, "manifest_json": _json(manifest_dict).decode("utf-8"),
                "manifest_sha256": manifest.manifest_sha, "receipt": receipt_value,
                "bundle_artifact_ref": artifact.as_dict()}, (artifact,), record_id=bundle_id)
        return {**receipt_value, "work_id": work_id, "request_id": request_id,
                "item_count": len(items), "missing": [
                    {"category": entry["category"], "reason": entry["reason"]} for entry in missing]}

    # --- the owner's download ------------------------------------------------------

    def _for_request(self, db, roots, request_id) -> bool:
        # the canonical body escapes every quote inside a string, so the needle can only
        # be the top-level key itself; a match is read back and checked
        needle = f'"request_id":"{request_id}"'.encode()
        for row in db.execute(
                "SELECT id, sha256 FROM domain_records WHERE vault_id=? AND kind='export_manifest' "
                "AND version=1 AND instr(body, ?) > 0", (roots.genesis.id, needle)).fetchall():
            record = self._domain._load(db, EntityRef("export_manifest", row["id"], 1, row["sha256"]),
                                        roots)[0]
            if record.body["content"].get("request_id") == request_id:
                return True
        return False

    def _stored(self, db, roots, bundle_id):
        row = db.execute(
            "SELECT sha256 FROM domain_records WHERE vault_id=? AND kind='export_manifest' "
            "AND id=? AND version=1", (roots.genesis.id, bundle_id)).fetchone()
        if row is None:
            return None
        return self._domain._load(db, EntityRef("export_manifest", bundle_id, 1, row["sha256"]),
                                  roots)[0]

    @_closed
    def download(self, request, work_id, bundle_id):
        """(receipt, bundle bytes) — the store verifies the blob on read."""

        work_id, bundle_id = uuid_string(work_id), uuid_string(bundle_id)
        with self._domain._connection() as db:
            self._owner.authenticate_bound(request.session)
            roots = self._domain._read_roots(db)
            record = self._stored(db, roots, bundle_id)
            if record is None or record.body["content"]["work_id"] != work_id:
                raise WorkServiceError("not_found")
            content = record.body["content"]
            artifact = self._domain._load(
                db, EntityRef.from_dict(content["bundle_artifact_ref"]), roots)[0]
        blob = BlobRef.from_dict(artifact.body["content"]["blob"])
        data = self._domain.read_blob(blob, purpose=blob.purpose)
        receipt = content["receipt"]
        if sha256(data).hexdigest() != receipt["bundle_sha256"]:
            raise WorkServiceError("unavailable")
        return receipt, data
