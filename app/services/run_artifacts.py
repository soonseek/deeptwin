"""The owner's view of what a run produced: artifact listing, originals,
bounded ranges and derived previews (T045; runtime.md §5, FR-015).

A run's artifacts are exactly the registered output blobs its accepted node
results name: a result record of kind `artifact` whose content carries an
`artifacts` list (`ordinal`, `role`, `media_type`, `blob`), as the extension
and provider attempt transports seal them. Nothing else is an artifact — not
a path, a filename or a caller-supplied reference. The store verifies every
blob a record names when it reads the record, so an original whose bytes
vanished fails the read closed (`unavailable`) instead of being listed.

The original is preserved and served as-is (whole or one bounded byte range),
never transcoded. A preview is a DERIVED artifact with its own digest, a
fidelity note and its disclosed coverage: this process derives previews only
for formats it can read with bounded standard-library parsers — UTF-8 text,
JSON and CSV. Images are identified by their magic bytes and left to the
browser to decode; PDF, DOCX and every other format are disclosed as needing
the artifact codec port (runtime.md §6 `artifact-codec-port-v1`), which runs
in an isolated worker: worker-produced documents are untrusted input and are
never parsed here. The declared media type is shown as declared; what the
preview does follows the bytes.
"""

from __future__ import annotations

import csv
import io
import json
import re
from functools import wraps
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import DomainContractError, EntityRef, uuid_string
from ..domain.store import BlobRef
from .owner_auth import OwnerAuthError
from .runs import RunServiceError

__all__ = ["PersistentRunArtifacts", "RunArtifactError", "artifact_identity"]

CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found",
                   "unavailable", "range_not_satisfiable"})
MAX_ARTIFACTS = 256
MAX_RANGE_BYTES = 1_048_576
PREVIEW_TEXT_BYTES = 65_536
PREVIEW_TABLE_ROWS = 200
PREVIEW_TABLE_COLUMNS = 50
PREVIEW_CELL_CHARS = 1_000
PREVIEW_JSON_DEPTH = 32
_ROLE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_MEDIA = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}\Z")
_RANGE = re.compile(r"bytes=(\d{1,19})-(\d{0,19})\Z")
_IMAGES = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"))
_CODEC_FORMATS = ((b"%PDF-", "pdf"), (b"PK\x03\x04", "zip_container"))


class RunArtifactError(ValueError):
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
        except RunServiceError as error:
            raise RunArtifactError(error.code) from None  # the run's own closed code
        except (RunArtifactError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage errors must not disclose detail
            raise RunArtifactError("unavailable") from None

    return invoke


def artifact_identity(result_ref: EntityRef, ordinal: int) -> str:
    """One stable ID per (exact result record version, ordinal)."""

    return str(uuid5(NAMESPACE_URL,
                     f"deeptwin:run-artifact:{result_ref.id}:{result_ref.version}:{ordinal}"))


def _entries(record) -> list[dict]:
    """A result record's declared artifacts, validated strictly or not at all."""

    if record.ref.kind != "artifact":
        return []
    content = record.body["content"]
    items = content.get("artifacts") if type(content) is dict else None
    if items is None:
        return []
    if type(items) is not list or len(items) > MAX_ARTIFACTS:
        raise RunArtifactError("unavailable")
    entries = []
    for index, item in enumerate(items):
        if (type(item) is not dict or set(item) != {"ordinal", "role", "media_type", "blob"}
                or item["ordinal"] != index or type(item["ordinal"]) is not int
                or type(item["role"]) is not str or _ROLE.fullmatch(item["role"]) is None
                or type(item["media_type"]) is not str
                or _MEDIA.fullmatch(item["media_type"]) is None
                or type(item["blob"]) is not dict):
            raise RunArtifactError("unavailable")  # a malformed result is not an artifact list
        blob = BlobRef(**item["blob"])
        entries.append({"ordinal": index, "role": item["role"],
                        "media_type": item["media_type"], "blob": blob})
    return entries


def _sniff(data: bytes) -> str:
    for magic, media in _IMAGES:
        if data.startswith(magic):
            return media
    for magic, name in _CODEC_FORMATS:
        if data.startswith(magic):
            return name
    return "bytes"


def _text_of(data: bytes) -> str | None:
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _json_depth(value, depth=0) -> None:
    if depth > PREVIEW_JSON_DEPTH:
        raise ValueError("depth")
    if type(value) is dict:
        for item in value.values():
            _json_depth(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _json_depth(item, depth + 1)


def _derived(kind, body, *, fidelity, covered, omissions, total):
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return {
        "kind": kind,
        "derived": True,
        "sha256": sha256(encoded).hexdigest(),
        "fidelity": fidelity,
        "coverage": {"original_bytes": total, "covered": covered, "omissions": omissions},
        "body": body,
    }


def derive_preview(entry: dict, data: bytes) -> dict:
    """The bounded derived preview of one original's bytes (never the original)."""

    total = len(data)
    sniffed = _sniff(data)
    if sniffed.startswith("image/"):
        return {"kind": "image", "derived": False, "sha256": None,
                "fidelity": "the original image bytes, decoded by the browser",
                "coverage": {"original_bytes": total, "covered": [[0, total]], "omissions": []},
                "body": {"media_type": sniffed}}
    if sniffed in {"pdf", "zip_container"}:
        return {"kind": "codec_required", "derived": False, "sha256": None,
                "fidelity": "no preview: this format is rendered only by the artifact codec "
                            "worker, which is not connected; the original is downloadable",
                "coverage": {"original_bytes": total, "covered": [], "omissions": [[0, total]]},
                "body": {"format": sniffed}}
    head = data[:PREVIEW_TEXT_BYTES]
    text = _text_of(head)
    if text is None and len(head) < total:
        # the cut may split one multi-byte character: drop at most three trailing bytes
        for cut in range(1, 4):
            text = _text_of(head[:-cut])
            if text is not None:
                head = head[:-cut]
                break
    if text is None:
        return {"kind": "unsupported", "derived": False, "sha256": None,
                "fidelity": "no preview: the bytes are neither UTF-8 text nor a recognised image",
                "coverage": {"original_bytes": total, "covered": [], "omissions": [[0, total]]},
                "body": {}}
    shown = len(head)
    omissions = [] if shown == total else [[shown, total]]
    declared = entry["media_type"]
    if declared == "application/json" and shown == total:
        try:
            value = json.loads(text)
            _json_depth(value)
        except (ValueError, RecursionError):
            value = None
        if value is not None:
            return _derived("json", {"text": json.dumps(value, ensure_ascii=False, indent=2)},
                            fidelity="parsed and re-indented; key order and values preserved",
                            covered=[[0, total]], omissions=[], total=total)
    if declared == "text/csv":
        rows, cut = [], False
        for row in csv.reader(io.StringIO(text, newline="")):
            if len(rows) == PREVIEW_TABLE_ROWS:
                cut = True
                break
            clipped = [cell[:PREVIEW_CELL_CHARS] for cell in row[:PREVIEW_TABLE_COLUMNS]]
            cut = cut or len(row) > PREVIEW_TABLE_COLUMNS or clipped != row[:PREVIEW_TABLE_COLUMNS]
            rows.append(clipped)
        return _derived("table", {"rows": rows, "truncated": cut or bool(omissions)},
                        fidelity="cells shown as text; formulas are never evaluated",
                        covered=[[0, shown]], omissions=omissions, total=total)
    return _derived("text", {"text": text},
                    fidelity="UTF-8 text shown verbatim, never rendered as markup",
                    covered=[[0, shown]], omissions=omissions, total=total)


class PersistentRunArtifacts:
    """Owner-read artifacts of one run, resolved from its accepted results."""

    def __init__(self, domain_store, owner_authority, runs):
        self._domain = domain_store
        self._owner = owner_authority
        self._runs = runs

    def _check(self, request):
        if request is None:
            raise RunArtifactError("unauthenticated")
        self._owner.authenticate_bound(request.session)

    def _catalog(self, run_id, *, base_path):
        try:
            run_id = uuid_string(run_id)
        except (TypeError, ValueError):
            raise RunArtifactError("invalid_input") from None
        outcome = self._runs.read(run_id, base_path=base_path)["outcome"]
        nodes = {execution: node for node, execution in outcome["execution_ids"]}
        items = []
        seen = set()
        for execution_id, raw in outcome["result_refs"]:
            ref = EntityRef.from_dict(raw)
            if ref in seen:
                continue  # one result named by several visits lists its artifacts once
            seen.add(ref)
            record = self._domain.get(ref)
            for entry in _entries(record):
                items.append({
                    "artifact_id": artifact_identity(ref, entry["ordinal"]),
                    "execution_id": execution_id,
                    "node_id": nodes.get(execution_id),
                    "result_ref": ref.as_dict(),
                    **entry,
                })
                if len(items) > MAX_ARTIFACTS:
                    raise RunArtifactError("unavailable")
        return run_id, items

    def _bytes(self, item):
        blob = item["blob"]
        try:
            return self._domain.read_blob(blob, purpose=blob.purpose)
        except (DomainContractError, KeyError, OSError, ValueError):
            return None

    def _projection(self, item, *, available):
        blob = item["blob"]
        return {
            "artifact_id": item["artifact_id"], "execution_id": item["execution_id"],
            "node_id": item["node_id"], "ordinal": item["ordinal"], "role": item["role"],
            "declared_media_type": item["media_type"], "sha256": blob.sha256,
            "size": blob.size, "result_ref": item["result_ref"],
            "availability": "available" if available else "missing",
        }

    def _find(self, items, artifact_id):
        try:
            artifact_id = uuid_string(artifact_id)
        except (TypeError, ValueError):
            raise RunArtifactError("invalid_input") from None
        for item in items:
            if item["artifact_id"] == artifact_id:
                return item
        raise RunArtifactError("not_found")

    @_closed
    def list(self, request, run_id, *, base_path) -> dict:
        self._check(request)
        run_id, items = self._catalog(run_id, base_path=base_path)
        return {"run_id": run_id, "artifacts": [
            self._projection(item, available=self._bytes(item) is not None) for item in items]}

    @_closed
    def read(self, request, run_id, artifact_id, *, base_path) -> dict:
        self._check(request)
        _run, items = self._catalog(run_id, base_path=base_path)
        item = self._find(items, artifact_id)
        return self._projection(item, available=self._bytes(item) is not None)

    @_closed
    def content(self, request, run_id, artifact_id, *, base_path, range_header=None):
        """(metadata, bytes, served range or None, sniffed media) of the original."""

        self._check(request)
        _run, items = self._catalog(run_id, base_path=base_path)
        item = self._find(items, artifact_id)
        data = self._bytes(item)
        if data is None:
            raise RunArtifactError("not_found")  # a missing original serves nothing
        served = None
        if range_header is not None:
            match = _RANGE.fullmatch(range_header)
            if match is None:
                raise RunArtifactError("invalid_input")
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else len(data) - 1
            if start >= len(data) or end < start:
                raise RunArtifactError("range_not_satisfiable")
            end = min(end, len(data) - 1, start + MAX_RANGE_BYTES - 1)
            served = (start, end)
            data = data[start:end + 1]
        return (self._projection(item, available=True), data, served,
                _sniff(self._bytes(item) if served else data))

    @_closed
    def preview(self, request, run_id, artifact_id, *, base_path) -> dict:
        self._check(request)
        _run, items = self._catalog(run_id, base_path=base_path)
        item = self._find(items, artifact_id)
        data = self._bytes(item)
        if data is None:
            raise RunArtifactError("not_found")
        return {"artifact": self._projection(item, available=True),
                "preview": derive_preview(item, data)}
