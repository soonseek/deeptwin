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

import csv
import io
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

__all__ = ["FREEZE_SCHEMA", "SAVE_SCHEMA", "DraftError", "PersistentAlternativeDrafts"]

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
        selectors = [] if payload["reviewed_whole"] else _selectors(
            fmt, original, data, result_ref.sha256)
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            existing = db.execute(
                "SELECT version, sha256 FROM domain_records WHERE vault_id=? "
                "AND kind='own_alternative' AND id=?", (roots.genesis.id, alternative_id)).fetchone()
            accepted = accept_own_alternative(boundary, {
                "author_id": actor_ref.id, "created_at": _stamp(), "submission_kind": "user_artifact",
                "original_artifact": result_ref.as_dict(),
                "alternative_artifact": record.ref.as_dict(),
                "coverage": "whole" if payload["reviewed_whole"] else "partial",
                "selectors": selectors, "optional_explanation": None, "synthetic": False,
            })
            content = {**accepted.as_dict(), "command_id": command_id,
                       "original_artifact_id": artifact_id, "run_id": run_id,
                       "observation_gaps": list(boundary.observation_gaps),
                       "boundary_work_revision_ref": boundary.work_revision_ref.as_dict(),
                       "boundary_environment_ref": boundary.environment_ref.as_dict()}
            if existing is not None:
                stored = self._domain._load(db, EntityRef("own_alternative", alternative_id, 1,
                                                          existing["sha256"]), roots)[0]
                if stored.body["content"]["alternative_artifact_ref"] != record.ref.as_dict():
                    raise DraftError("conflict")
                frozen = stored
            else:
                frozen = ImmutableRecord.create(
                    kind="own_alternative", id=alternative_id, version=1, created_at_utc=_stamp(),
                    actor_ref=actor_ref, parent_refs=(record.ref, result_ref), purpose="operational",
                    access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                    content=content,
                )
                self._domain._put_in_transaction(db, frozen)
        body = frozen.body["content"]
        return {"alternative_ref": frozen.ref.as_dict(), "draft_id": draft_id,
                "revision": record.ref.version, "coverage": body["coverage"],
                "selectors": body["selectors"], "evidence_scope": body["evidence_scope"],
                "unreviewed_scope": body["unreviewed_scope"], "impact_scope": body["impact_scope"],
                "observation_gaps": body["observation_gaps"]}
