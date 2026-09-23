"""The owner's own version of a run artifact: revision-safe drafts, then an explicit freeze
(US4, T052 server half; growth.md journey steps 1–2, FR-016/017, UX-AC05).

A draft edits a copy of one exact original — a text artifact as text, a CSV
artifact as a table of cells — and is saved as immutable revisions: revision n is
the record version n of the draft, linked to revision n-1, so two screens saving
from the same revision collide on the same identity and the second is refused
(`conflict`) instead of overwriting (a stale-tab save never wins). Every save
carries a command id; a replay of the same command returns the same revision and
a reused command with different content is a conflict. No reason or instruction
is required at any step.

A draft is not an alternative (G-01: an empty or unfrozen draft is never
promoted). `freeze` turns one exact draft revision into an `own_alternative`
through `alternatives.accept_own_alternative`, against the original execution
boundary the run actually recorded (its work revision, environment and the
result record that holds the artifact); what this server does not trace at that
boundary (inputs, handoffs, tools, model bindings) is stated as observation
gaps, never invented. Coverage is honest: by default the changed lines or cells
are the evidence scope (`partial`, selectors bound to the original's digest, the
rest stated as unreviewed); `whole` only when the owner explicitly says they
reviewed the whole artifact — an assembled full preview is not a human
whole-work.
"""

from __future__ import annotations

import base64
import binascii
import csv
import io
import re
from datetime import UTC, datetime
from difflib import SequenceMatcher
from functools import wraps
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import EntityRef, canonical_json, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import BlobRef, _writer
from .alternatives import AlternativeContractError, accept_own_alternative
from .alternatives import OriginalExecution as _Original
from .owner_auth import OwnerAuthError
from .run_approvals import _authenticate_owner, _owner_actor_ref
from .run_artifacts import PersistentRunArtifacts, RunArtifactError
from .runs import RunServiceError

__all__ = ["FILE_SCHEMA", "FREEZE_SCHEMA", "SAVE_SCHEMA", "DraftError", "PersistentAlternativeDrafts"]

FILE_SCHEMA = "alternative-file-v1"
MAX_FILE_BYTES = 4 * 1024 * 1024
ALIGNMENT_NOTE = ("대안 파일과 원본 사이의 의미 정렬은 계산하지 않았다: 선택 영역은 원본 위의 형식상 위치이며 "
                  "정렬은 unresolved로 남는다.")
_MEDIA = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}\Z")
_POINTER = re.compile(r"(/([^~/]|~[01])*)*\Z")
# the selector kinds each original format can bind (growth.md Selector)
REGION_KINDS = {
    "application/pdf": frozenset({"page_region"}),
    "application/json": frozenset({"structured_path", "text_span"}),
    "text/csv": frozenset({"table_range"}),
    "text/plain": frozenset({"text_span"}),
    "text/markdown": frozenset({"text_span"}),
}

SAVE_SCHEMA = "alternative-draft-save-v1"
FREEZE_SCHEMA = "alternative-freeze-v1"
TEXT_MEDIA = frozenset({"text/plain", "text/markdown", "application/json"})
TABLE_MEDIA = frozenset({"text/csv"})
MAX_TEXT_BYTES = 262_144
MAX_ROWS = 2_000
MAX_COLUMNS = 64
MAX_CELL_CHARS = 4_000
MAX_REVISIONS = 10_000
MAX_SELECTORS = 64
CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found",
                   "conflict", "too_large", "unavailable"})


class DraftError(ValueError):
    """Closed codes; storage detail never leaks."""

    def __init__(self, code="invalid_input"):
        if code not in CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (DraftError, OwnerAuthError):
            raise
        except (RunArtifactError, RunServiceError) as error:
            raise DraftError(error.code) from None
        except AlternativeContractError:
            raise DraftError("invalid_input") from None
        except Exception:  # noqa: BLE001 - storage errors must not disclose detail
            raise DraftError("unavailable") from None

    return invoke


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _uuid(value):
    try:
        return uuid_string(value)
    except (TypeError, ValueError):
        raise DraftError("invalid_input") from None


def _csv_rows(data: bytes):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise DraftError("invalid_input") from None
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if len(rows) > MAX_ROWS or any(len(row) > MAX_COLUMNS for row in rows):
        raise DraftError("too_large")
    return rows


def _csv_bytes(rows) -> bytes:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _content(payload_format, payload):
    """The draft's exact bytes from the wire, bounded."""

    if payload_format == "text":
        text = payload.get("text")
        if type(text) is not str or "rows" in payload:
            raise DraftError("invalid_input")
        data = text.encode("utf-8")
        if len(data) > MAX_TEXT_BYTES:
            raise DraftError("too_large")
        return data
    rows = payload.get("rows")
    if "text" in payload or type(rows) is not list or len(rows) > MAX_ROWS:
        raise DraftError("invalid_input" if type(rows) is not list else "too_large")
    for row in rows:
        if (type(row) is not list or len(row) > MAX_COLUMNS
                or any(type(cell) is not str or len(cell) > MAX_CELL_CHARS for cell in row)):
            raise DraftError("invalid_input")
    data = _csv_bytes(rows)
    if len(data) > MAX_TEXT_BYTES:
        raise DraftError("too_large")
    return data


def _selectors(fmt, original: bytes, draft: bytes, source_hash: str) -> list[dict]:
    """The changed regions as formal selectors on the exact original (proposed alignment)."""

    selectors = []
    if fmt == "text":
        left = original.decode("utf-8").splitlines()
        right = draft.decode("utf-8").splitlines()
        for tag, i1, i2, _j1, _j2 in SequenceMatcher(a=left, b=right, autojunk=False).get_opcodes():
            if tag != "equal":
                selectors.append({"kind": "text_span", "locator": {
                    "unit": "line", "start": i1 + 1, "end": max(i1 + 1, i2), "operation": tag},
                    "source_hash": source_hash, "alignment": "proposed"})
    else:
        left, right = _csv_rows(original), _csv_rows(draft)
        for row in range(max(len(left), len(right))):
            before = left[row] if row < len(left) else []
            after = right[row] if row < len(right) else []
            changed = [column for column in range(max(len(before), len(after)))
                       if (before[column] if column < len(before) else None)
                       != (after[column] if column < len(after) else None)]
            if changed:
                selectors.append({"kind": "table_range", "locator": {
                    "row": row + 1, "first_column": changed[0] + 1, "last_column": changed[-1] + 1},
                    "source_hash": source_hash, "alignment": "proposed"})
    if len(selectors) > MAX_SELECTORS:
        raise DraftError("too_large")  # too many scattered edits for a partial claim: say whole
    return selectors


# region coordinates are integer basis points of the page or image (0..10 000): exact,
# resolution-free, and never a float in a canonical record
REGION_SCALE = 10_000


def _unit(value) -> bool:
    return type(value) is int and 0 <= value <= REGION_SCALE


def _region_selectors(original_media, raw, source_hash):
    """Formal selections on the exact original, bounded per kind; alignment `unresolved`."""

    if not 1 <= len(raw) <= MAX_SELECTORS:
        raise DraftError("invalid_input")  # partial coverage names what it covers
    allowed = REGION_KINDS.get(original_media)
    if allowed is None:
        if original_media.startswith("image/"):
            allowed = frozenset({"image_region"})
        elif original_media.startswith(("audio/", "video/")):
            allowed = frozenset({"time_range"})
        else:
            raise DraftError("invalid_input")  # no formal selector for this format: whole only
    selectors = []
    for value in raw:
        if type(value) is not dict or set(value) != {"kind", "locator"} or value["kind"] not in allowed:
            raise DraftError("invalid_input")
        kind, locator = value["kind"], value["locator"]
        if type(locator) is not dict:
            raise DraftError("invalid_input")
        if kind in {"image_region", "page_region"}:
            keys = {"x", "y", "width", "height"} | ({"page"} if kind == "page_region" else set())
            if set(locator) != keys or not all(_unit(locator[name]) for name in ("x", "y", "width", "height")):
                raise DraftError("invalid_input")
            if locator["width"] <= 0 or locator["height"] <= 0 \
                    or locator["x"] + locator["width"] > REGION_SCALE \
                    or locator["y"] + locator["height"] > REGION_SCALE:
                raise DraftError("invalid_input")
            if kind == "page_region" and (type(locator["page"]) is not int or not 1 <= locator["page"] <= 10_000):
                raise DraftError("invalid_input")
        elif kind == "time_range":
            if (set(locator) != {"start_ms", "end_ms"} or any(type(locator[name]) is not int
                                                             for name in locator)
                    or not 0 <= locator["start_ms"] < locator["end_ms"] <= 86_400_000):
                raise DraftError("invalid_input")
        elif kind == "structured_path":
            if (set(locator) != {"pointer"} or type(locator["pointer"]) is not str
                    or len(locator["pointer"]) > 1_024 or _POINTER.fullmatch(locator["pointer"]) is None):
                raise DraftError("invalid_input")
        elif kind == "text_span":
            if (set(locator) != {"unit", "start", "end"} or locator["unit"] != "line"
                    or type(locator["start"]) is not int or type(locator["end"]) is not int
                    or not 1 <= locator["start"] <= locator["end"] <= 1_000_000):
                raise DraftError("invalid_input")
        elif kind == "table_range":
            if (set(locator) != {"row", "first_column", "last_column"}
                    or any(type(locator[name]) is not int for name in locator)
                    or not 1 <= locator["row"] <= MAX_ROWS
                    or not 1 <= locator["first_column"] <= locator["last_column"] <= MAX_COLUMNS):
                raise DraftError("invalid_input")
        selectors.append({"kind": kind, "locator": dict(locator), "source_hash": source_hash,
                          "alignment": "unresolved"})
    return selectors


class PersistentAlternativeDrafts:
    """Owner-authenticated drafts and freezes over one run's actual artifacts."""

    def __init__(self, artifacts):
        if type(artifacts) is not PersistentRunArtifacts:
            raise TypeError("Exact PersistentRunArtifacts required")
        self._artifacts = artifacts
        self._domain = artifacts._domain
        self._owner = artifacts._owner
        self._runs = artifacts._runs

    # --- the original ---------------------------------------------------------------

    def _original(self, run_id, artifact_id, base_path):
        _run, items = self._artifacts._catalog(run_id, base_path=base_path)
        item = self._artifacts._find(items, artifact_id)
        media = item["media_type"]
        fmt = "text" if media in TEXT_MEDIA else "table" if media in TABLE_MEDIA else None
        if fmt is None:
            raise DraftError("invalid_input")  # other formats need their own selector flows (T053)
        data = self._artifacts._bytes(item)
        if data is None:
            raise DraftError("unavailable")
        if fmt == "text":
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                raise DraftError("invalid_input") from None
        else:
            _csv_rows(data)
        return item, fmt, data

    # --- draft records --------------------------------------------------------------

    def _versions(self, db, roots, draft_id):
        return db.execute(
            "SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind='artifact' "
            "AND id=? ORDER BY version DESC LIMIT 1", (roots.genesis.id, draft_id)).fetchone()

    def _load(self, db, roots, draft_id, version=None):
        if version is None:
            row = self._versions(db, roots, draft_id)
            if row is None:
                return None
            version, digest = row["version"], row["sha256"]
        else:
            row = db.execute(
                "SELECT sha256 FROM domain_records WHERE vault_id=? AND kind='artifact' AND id=? "
                "AND version=?", (roots.genesis.id, draft_id, version)).fetchone()
            if row is None:
                return None
            digest = row["sha256"]
        record = self._domain._load(db, EntityRef("artifact", draft_id, version, digest), roots)[0]
        if "alternative_draft" not in record.body["content"]:
            return None
        return record

    def _by_command(self, db, roots, command_id):
        needle = f'"command_id":"{command_id}"'.encode()
        for row in db.execute(
                "SELECT id, version FROM domain_records WHERE vault_id=? AND kind='artifact' "
                "AND instr(body, ?) > 0 LIMIT 4", (roots.genesis.id, needle)).fetchall():
            record = self._load(db, roots, row["id"], row["version"])
            if record is not None and record.body["content"]["alternative_draft"][
                    "command_id"] == command_id:
                return record
        return None

    def _projection(self, record, *, data=None, include_content=False):
        draft = record.body["content"]["alternative_draft"]
        value = {
            "draft_id": record.ref.id, "revision": record.ref.version, "run_id": draft["run_id"],
            "artifact_id": draft["artifact_id"], "format": draft["format"],
            "original_sha256": draft["original_sha256"], "sha256": draft["sha256"],
            "saved_at_utc": record.body["created_at_utc"], "ref": record.ref.as_dict(),
        }
        if include_content:
            if draft["format"] == "text":
                value["text"] = data.decode("utf-8")
            else:
                value["rows"] = _csv_rows(data)
        return value

    def _bytes(self, record):
        blob = BlobRef.from_dict(record.body["content"]["blob"])
        data = self._domain.read_blob(blob, purpose=blob.purpose)
        if sha256(data).hexdigest() != record.body["content"]["alternative_draft"]["sha256"]:
            raise DraftError("unavailable")
        return data

    @_closed
    def save(self, request, run_id, artifact_id, payload, *, base_path) -> dict:
        _authenticate_owner(self._owner, request)
        if type(payload) is not dict or payload.get("schema_version") != SAVE_SCHEMA:
            raise DraftError("invalid_input")
        allowed = {"schema_version", "command_id", "draft_id", "expected_revision", "format",
                   "text", "rows"}
        if set(payload) - allowed or not {"command_id", "draft_id", "expected_revision",
                                          "format"} <= set(payload):
            raise DraftError("invalid_input")
        command_id = _uuid(payload["command_id"])
        expected = payload["expected_revision"]
        if type(expected) is not int or not 0 <= expected <= MAX_REVISIONS:
            raise DraftError("invalid_input")
        draft_id = payload["draft_id"]
        if (draft_id is None) != (expected == 0):
            raise DraftError("invalid_input")  # a new draft starts at 0; an existing one names itself
        draft_id = str(uuid5(NAMESPACE_URL, f"deeptwin:alternative-draft:{command_id}")) \
            if draft_id is None else _uuid(draft_id)
        run_id, artifact_id = _uuid(run_id), _uuid(artifact_id)
        item, fmt, _original = self._original(run_id, artifact_id, base_path)
        if payload["format"] != fmt:
            raise DraftError("invalid_input")
        data = _content(fmt, payload)
        digest = sha256(canonical_json({"draft_id": draft_id, "expected": expected,
                                        "sha256": sha256(data).hexdigest()})).hexdigest()
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            replay = self._by_command(db, roots, command_id)
        if replay is not None:
            if replay.body["content"]["alternative_draft"]["command_digest"] != digest:
                raise DraftError("conflict")
            return self._projection(replay)
        blob = self._domain.put_blob(data, purpose="operational")
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            replay = self._by_command(db, roots, command_id)
            if replay is not None:
                if replay.body["content"]["alternative_draft"]["command_digest"] != digest:
                    raise DraftError("conflict")
                return self._projection(replay)
            latest = self._load(db, roots, draft_id)
            current = 0 if latest is None else latest.ref.version
            if current != expected:
                raise DraftError("conflict")  # another screen saved first: never overwritten
            if latest is not None:
                bound = latest.body["content"]["alternative_draft"]
                if (bound["run_id"], bound["artifact_id"]) != (run_id, artifact_id):
                    raise DraftError("not_found")
            record = ImmutableRecord.create(
                kind="artifact", id=draft_id, version=current + 1, created_at_utc=_stamp(),
                actor_ref=actor_ref,
                parent_refs=(EntityRef.from_dict(item["result_ref"]),) if latest is None
                else (latest.ref,),
                purpose="operational", access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy,
                content={
                    "alternative_draft": {
                        "run_id": run_id, "artifact_id": artifact_id, "format": fmt,
                        "original_sha256": item["blob"].sha256, "sha256": blob.sha256,
                        "command_id": command_id, "command_digest": digest,
                    },
                    "blob": blob.as_dict(),
                },
            )
            self._domain._put_in_transaction(db, record)
        return self._projection(record)

    @_closed
    def list(self, request, run_id, artifact_id, *, base_path) -> dict:
        if request is None:
            raise DraftError("unauthenticated")
        self._owner.authenticate_bound(request.session)
        run_id, artifact_id = _uuid(run_id), _uuid(artifact_id)
        item, fmt, original_bytes = self._original(run_id, artifact_id, base_path)
        if len(original_bytes) > MAX_TEXT_BYTES:
            raise DraftError("too_large")  # an in-place editor holds the whole copy
        original = {"format": fmt, "sha256": item["blob"].sha256, "media_type": item["media_type"]}
        if fmt == "text":
            original["text"] = original_bytes.decode("utf-8")
        else:
            original["rows"] = _csv_rows(original_bytes)
        needle = f'"artifact_id":"{artifact_id}"'.encode()
        drafts = {}
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            for row in db.execute(
                    "SELECT DISTINCT id FROM domain_records WHERE vault_id=? AND kind='artifact' "
                    "AND instr(body, ?) > 0 LIMIT 64", (roots.genesis.id, needle)).fetchall():
                record = self._load(db, roots, row["id"])
                if record is not None and record.body["content"]["alternative_draft"][
                        "run_id"] == run_id:
                    drafts[record.ref.id] = self._projection(record)
            frozen = self._frozen_ids(db, roots, list(drafts))
        for draft_id, value in drafts.items():
            value["frozen_revisions"] = frozen.get(draft_id, [])
        return {"run_id": run_id, "artifact_id": artifact_id, "original": original,
                "drafts": sorted(drafts.values(), key=lambda item: item["saved_at_utc"])}

    @_closed
    def read(self, request, run_id, artifact_id, draft_id, *, base_path) -> dict:
        if request is None:
            raise DraftError("unauthenticated")
        self._owner.authenticate_bound(request.session)
        run_id, artifact_id, draft_id = _uuid(run_id), _uuid(artifact_id), _uuid(draft_id)
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            record = self._load(db, roots, draft_id)
            frozen = self._frozen_ids(db, roots, [draft_id]).get(draft_id, [])
        if record is None:
            raise DraftError("not_found")
        bound = record.body["content"]["alternative_draft"]
        if (bound["run_id"], bound["artifact_id"]) != (run_id, artifact_id):
            raise DraftError("not_found")
        value = self._projection(record, data=self._bytes(record), include_content=True)
        value["frozen_revisions"] = frozen
        return value

    @_closed
    def differences(self, request, run_id, artifact_id, draft_id, *, base_path) -> dict:
        """What the framework observes between the original and one draft revision (T055)."""

        from .difference_observer import DifferenceObservationError, observe_differences

        if request is None:
            raise DraftError("unauthenticated")
        self._owner.authenticate_bound(request.session)
        run_id, artifact_id, draft_id = _uuid(run_id), _uuid(artifact_id), _uuid(draft_id)
        item, _fmt, original = self._original(run_id, artifact_id, base_path)
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            record = self._load(db, roots, draft_id)
        if record is None:
            raise DraftError("not_found")
        bound = record.body["content"]["alternative_draft"]
        if (bound["run_id"], bound["artifact_id"]) != (run_id, artifact_id):
            raise DraftError("not_found")
        try:
            observed = observe_differences(original, self._bytes(record), media_type=item["media_type"])
        except DifferenceObservationError:
            raise DraftError("too_large") from None
        return {"draft_id": draft_id, "revision": record.ref.version, "format": observed.format,
                "identical": observed.identical, "observations": list(observed.observations),
                "uncertainties": list(observed.uncertainties)}

    # --- the explicit freeze --------------------------------------------------------

    def _frozen_ids(self, db, roots, draft_ids):
        frozen = {}
        for draft_id in draft_ids:
            for row in db.execute(
                    "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? "
                    "AND kind='own_alternative' AND instr(body, ?) > 0",
                    (roots.genesis.id, f'"id":"{draft_id}"'.encode())).fetchall():
                record = self._domain._load(db, EntityRef("own_alternative", row["id"], row["version"],
                                                          row["sha256"]), roots)[0]
                ref = record.body["content"]["alternative_artifact_ref"]
                if ref["id"] == draft_id:
                    frozen.setdefault(draft_id, []).append(ref["version"])
        return {key: sorted(value) for key, value in frozen.items()}

    def _seal_alternative(self, db, roots, actor_ref, *, item, manifest, alternative, reviewed_whole,
                          selectors, alternative_id, command_id, run_id, artifact_id):
        """Accept one alternative against the run's recorded boundary and seal it once."""

        result_ref = EntityRef.from_dict(item["result_ref"])
        boundary = _Original.from_untrusted({
            "boundary_id": f"execution-{item['execution_id']}",
            "work_revision_ref": manifest.inputs["work_revision_ref"].as_dict(),
            "environment_ref": manifest.inputs["environment_ref"].as_dict(),
            "input_refs": [], "output_refs": [result_ref.as_dict()], "handoff_refs": [],
            "tool_refs": [], "model_binding_refs": [],
            "observation_gaps": [
                "이 경계의 입력 산출물·전달·도구·모델 바인딩은 이 서버가 아직 추적하지 않는다.",
            ],
        })
        existing = db.execute(
            "SELECT version, sha256 FROM domain_records WHERE vault_id=? "
            "AND kind='own_alternative' AND id=?", (roots.genesis.id, alternative_id)).fetchone()
        if existing is not None:
            stored = self._domain._load(db, EntityRef("own_alternative", alternative_id, 1,
                                                      existing["sha256"]), roots)[0]
            if stored.body["content"]["alternative_artifact_ref"] != alternative.as_dict():
                raise DraftError("conflict")
            return stored
        accepted = accept_own_alternative(boundary, {
            "author_id": actor_ref.id, "created_at": _stamp(), "submission_kind": "user_artifact",
            "original_artifact": result_ref.as_dict(), "alternative_artifact": alternative.as_dict(),
            "coverage": "whole" if reviewed_whole else "partial",
            "selectors": selectors, "optional_explanation": None, "synthetic": False,
        })
        content = {**accepted.as_dict(), "command_id": command_id,
                   "original_artifact_id": artifact_id, "run_id": run_id,
                   "observation_gaps": list(boundary.observation_gaps),
                   "boundary_work_revision_ref": boundary.work_revision_ref.as_dict(),
                   "boundary_environment_ref": boundary.environment_ref.as_dict()}
        frozen = ImmutableRecord.create(
            kind="own_alternative", id=alternative_id, version=1, created_at_utc=_stamp(),
            actor_ref=actor_ref, parent_refs=(alternative, result_ref), purpose="operational",
            access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
            content=content,
        )
        self._domain._put_in_transaction(db, frozen)
        return frozen

    @staticmethod
    def _frozen_view(frozen, **extra):
        body = frozen.body["content"]
        return {"alternative_ref": frozen.ref.as_dict(), **extra, "coverage": body["coverage"],
                "selectors": body["selectors"], "evidence_scope": body["evidence_scope"],
                "unreviewed_scope": body["unreviewed_scope"], "impact_scope": body["impact_scope"],
                "observation_gaps": body["observation_gaps"]}

    # --- a whole alternative file, with formal selectors on the original --------------

    @_closed
    def upload_file(self, request, run_id, artifact_id, payload, *, base_path) -> dict:
        """A user-made file as the alternative; region selectors bind the original.

        Any original format may be answered with a file. The server computes no
        semantic alignment between the two here, so every selector's alignment is
        `unresolved` — stated, never implied.
        """

        _authenticate_owner(self._owner, request)
        if (type(payload) is not dict or set(payload) != {
                "schema_version", "command_id", "media_type", "name", "content_b64", "selectors",
                "reviewed_whole"}
                or payload["schema_version"] != FILE_SCHEMA
                or type(payload["reviewed_whole"]) is not bool
                or type(payload["selectors"]) is not list):
            raise DraftError("invalid_input")
        command_id = _uuid(payload["command_id"])
        run_id, artifact_id = _uuid(run_id), _uuid(artifact_id)
        media, name = payload["media_type"], payload["name"]
        if (type(media) is not str or _MEDIA.fullmatch(media) is None or type(name) is not str
                or not 1 <= len(name) <= 255 or any(ch in name for ch in '/\\\x00')):
            raise DraftError("invalid_input")
        try:
            data = base64.b64decode(payload["content_b64"], validate=True)
        except (TypeError, ValueError, binascii.Error):
            raise DraftError("invalid_input") from None
        if not data:
            raise DraftError("invalid_input")  # an empty file is an empty draft, never an alternative
        if len(data) > MAX_FILE_BYTES:
            raise DraftError("too_large")
        _run, items = self._artifacts._catalog(run_id, base_path=base_path)
        item = self._artifacts._find(items, artifact_id)
        original = self._artifacts._bytes(item)
        if original is None:
            raise DraftError("unavailable")
        if data == original:
            raise DraftError("invalid_input")  # the same bytes are not an alternative
        result_ref = EntityRef.from_dict(item["result_ref"])
        if payload["reviewed_whole"]:
            if payload["selectors"]:
                raise DraftError("invalid_input")
            selectors = []
        else:
            selectors = _region_selectors(item["media_type"], payload["selectors"], result_ref.sha256)
        file_id = str(uuid5(NAMESPACE_URL, f"deeptwin:alternative-file:{command_id}"))
        alternative_id = str(uuid5(NAMESPACE_URL, f"deeptwin:own-alternative:{command_id}"))
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            manifest = self._runs._manifest_by_run(db, roots, run_id)
        if manifest is None:
            raise DraftError("not_found")
        blob = self._domain.put_blob(data, purpose="operational")
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            row = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind='artifact' "
                             "AND id=? AND version=1", (roots.genesis.id, file_id)).fetchone()
            if row is not None:
                stored = self._domain._load(db, EntityRef("artifact", file_id, 1, row["sha256"]), roots)[0]
                if stored.body["content"]["alternative_file"]["sha256"] != blob.sha256:
                    raise DraftError("conflict")
                file_ref = stored.ref
            else:
                record = ImmutableRecord.create(
                    kind="artifact", id=file_id, version=1, created_at_utc=_stamp(),
                    actor_ref=actor_ref, parent_refs=(result_ref,), purpose="operational",
                    access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                    content={"alternative_file": {
                        "run_id": run_id, "artifact_id": artifact_id, "media_type": media, "name": name,
                        "sha256": blob.sha256, "original_sha256": item["blob"].sha256,
                        "command_id": command_id}, "blob": blob.as_dict()})
                self._domain._put_in_transaction(db, record)
                file_ref = record.ref
            frozen = self._seal_alternative(
                db, roots, actor_ref, item=item, manifest=manifest, alternative=file_ref,
                reviewed_whole=payload["reviewed_whole"], selectors=selectors,
                alternative_id=alternative_id, command_id=command_id, run_id=run_id,
                artifact_id=artifact_id)
        return self._frozen_view(frozen, file_ref=file_ref.as_dict(), alignment_note=ALIGNMENT_NOTE)

    @_closed
    def freeze(self, request, run_id, artifact_id, draft_id, payload, *, base_path) -> dict:
        _authenticate_owner(self._owner, request)
        if (type(payload) is not dict or set(payload) != {
                "schema_version", "command_id", "expected_revision", "reviewed_whole"}
                or payload["schema_version"] != FREEZE_SCHEMA
                or type(payload["expected_revision"]) is not int
                or type(payload["reviewed_whole"]) is not bool):
            raise DraftError("invalid_input")
        command_id = _uuid(payload["command_id"])
        run_id, artifact_id, draft_id = _uuid(run_id), _uuid(artifact_id), _uuid(draft_id)
        item, fmt, original = self._original(run_id, artifact_id, base_path)
        alternative_id = str(uuid5(NAMESPACE_URL, f"deeptwin:own-alternative:{command_id}"))
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            record = self._load(db, roots, draft_id)
            manifest = self._runs._manifest_by_run(db, roots, run_id)
        if record is None or manifest is None:
            raise DraftError("not_found")
        bound = record.body["content"]["alternative_draft"]
        if (bound["run_id"], bound["artifact_id"]) != (run_id, artifact_id):
            raise DraftError("not_found")
        if record.ref.version != payload["expected_revision"]:
            raise DraftError("conflict")  # freeze exactly the revision the owner saw
        if bound["original_sha256"] != item["blob"].sha256:
            raise DraftError("conflict")
        data = self._bytes(record)
        if data == original:
            raise DraftError("invalid_input")  # an unchanged copy is not an alternative
        result_ref = EntityRef.from_dict(item["result_ref"])
        selectors = [] if payload["reviewed_whole"] else _selectors(
            fmt, original, data, result_ref.sha256)
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            frozen = self._seal_alternative(
                db, roots, actor_ref, item=item, manifest=manifest, alternative=record.ref,
                reviewed_whole=payload["reviewed_whole"], selectors=selectors,
                alternative_id=alternative_id, command_id=command_id, run_id=run_id,
                artifact_id=artifact_id)
        return self._frozen_view(frozen, draft_id=draft_id, revision=record.ref.version)
