"""The owner's process feedback on a run (docs/ui/2026-09-26-product-ux-redesign.md §6;
decisions.md "2026-09-26 — Owner decisions on the product UI after a usability review").

Beside the owner's own version of an artifact (an alternative, `alternative_drafts.py`),
the owner may leave on a run an optional mark — `ok` (괜찮음) or `needs_attention`
(확인 필요) — and an optional plain-text memo, on the run as a whole or on one node's
exact visit and attempt. No explanation is ever required (FR-016): a mark alone, a memo
alone or both are each a complete feedback.

Feedback is **not an alternative** and is never counted as one (UX-AC05): it is a separate
record kind (`process_feedback`) that no alternative, difference, hypothesis, inquiry or
export-alternatives path reads, and the memory compiler, the change compiler and the
knowledge registry refuse a reference to it. Exploration may only ever read it as an
owner-supplied observation, never as ground truth.

Storage: one immutable `process_feedback` record per revision. A target (the run, or
`node_id` + `visit_no` + `attempt_no`) has one identity derived from the run and the target,
so revision n is record version n of that identity, linked to revision n-1 (revision 1 to
the run manifest). A change is a new revision that supersedes the previous one, and a clear
is a new revision whose state is `cleared` — nothing is overwritten or deleted, and the
whole history stays readable. Every write names the revision it was made from
(`expected_revision`): a stale screen is refused (`conflict`), never silently wins.

Writes go through the owner-command path every owner write here uses: a CSRF-verified
same-origin POST of the owner's live session (`run_approvals._authenticate_owner`), one
command id per command (an exact replay returns the same revision; the same id with
another body is a conflict), and the record and its `feedback.recorded` public event in one
writer transaction. The public event carries only the scope, the mark, whether a memo exists,
whether it was a clear and the revision — never the memo text.

The target must exist in the run's own trace (`run_traces.py`): the node, the visit number
and, when the visit has ledger attempts, one of those attempt numbers (a visit the executor
ran in-process has none, and its target names `attempt_no: null`).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from ..domain.public_events import _append_event_in_transaction
from ..domain.refs import DomainContractError, EntityRef, ObjectRef, canonical_json, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import _writer
from .owner_auth import OwnerAuthError
from .run_approvals import _authenticate_owner, _owner_actor_ref
from .run_traces import PersistentRunTraces, RunTraceReadError
from .runs import RunServiceError

__all__ = [
    "COMMAND_SCHEMA", "FEEDBACK_KIND", "LIST_SCHEMA", "MARKS", "MAX_MEMO_CHARS", "RECORD_SCHEMA",
    "PersistentRunFeedback", "RunFeedbackError", "current_feedback", "feedback_history", "feedback_identity",
]

FEEDBACK_KIND = "process_feedback"
COMMAND_SCHEMA = "process-feedback-command-v1"
RECORD_SCHEMA = "process-feedback-v1"
LIST_SCHEMA = "process-feedback-list-v1"
MARKS = ("ok", "needs_attention")
ACTIONS = ("set", "clear")
# the memo is bounded plain text: at most 4,000 characters (Unicode code points), with at least
# one visible character; tabs and line breaks are kept, other control characters are refused
MAX_MEMO_CHARS = 4_000
MAX_REVISIONS = 1_000         # revisions of one target
MAX_RECORDS_PER_RUN = 10_000  # the history one run's read returns
MAX_VISIT = 1_000_000
COMMAND_FIELDS = frozenset({"schema_version", "command_id", "action", "target", "expected_revision",
                            "mark", "memo"})
CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "conflict",
                   "too_large", "unavailable"})
_NODE_ID = re.compile(r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*\Z")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class RunFeedbackError(ValueError):
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
        except (RunFeedbackError, OwnerAuthError):
            raise
        except (RunTraceReadError, RunServiceError) as error:
            # the trace reader's own closed codes (an unknown run, a malformed id) pass through
            raise RunFeedbackError(error.code) from None
        except Exception:  # noqa: BLE001 - storage detail stays private
            raise RunFeedbackError("unavailable") from None

    return invoke


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _uuid(value):
    try:
        return uuid_string(value)
    except (DomainContractError, TypeError, ValueError):
        raise RunFeedbackError("invalid_input") from None


def _count(value, *, low=1, high=MAX_VISIT):
    if type(value) is not int or not low <= value <= high:
        raise RunFeedbackError("invalid_input")
    return value


def target_value(value) -> dict:
    """The exact target: `{"scope": "run"}`, or `{"scope": "step", "node_id", "visit_no",
    "attempt_no"}` where `attempt_no` is a number or null (a visit without ledger attempts)."""

    if type(value) is not dict:
        raise RunFeedbackError("invalid_input")
    if value.get("scope") == "run" and set(value) == {"scope"}:
        return {"scope": "run"}
    if value.get("scope") != "step" or set(value) != {"scope", "node_id", "visit_no", "attempt_no"}:
        raise RunFeedbackError("invalid_input")
    node_id = value["node_id"]
    if type(node_id) is not str or not 1 <= len(node_id) <= 64 or _NODE_ID.fullmatch(node_id) is None:
        raise RunFeedbackError("invalid_input")
    attempt = value["attempt_no"]
    return {"scope": "step", "node_id": node_id, "visit_no": _count(value["visit_no"]),
            "attempt_no": None if attempt is None else _count(attempt)}


def memo_value(value):
    """None, or bounded plain text with a visible character (too long: `too_large`)."""

    if value is None:
        return None
    if type(value) is not str or not value.strip() or _CONTROL.search(value) is not None:
        raise RunFeedbackError("invalid_input")
    if len(value) > MAX_MEMO_CHARS:
        raise RunFeedbackError("too_large")
    return value


def feedback_identity(run_id: str, target: dict) -> str:
    """One identity per run and exact target: every revision of it is a version of this id."""

    key = sha256(canonical_json({"run_id": run_id, "target": target})).hexdigest()
    return str(uuid5(NAMESPACE_URL, f"deeptwin:process-feedback:{key}"))


def _command(payload) -> dict:
    if type(payload) is not dict or set(payload) != COMMAND_FIELDS or payload["schema_version"] != COMMAND_SCHEMA:
        raise RunFeedbackError("invalid_input")
    action, mark = payload["action"], payload["mark"]
    if action not in ACTIONS or (mark is not None and mark not in MARKS):
        raise RunFeedbackError("invalid_input")
    command = {"command_id": _uuid(payload["command_id"]), "action": action,
               "target": target_value(payload["target"]),
               "expected_revision": _count(payload["expected_revision"], low=0, high=MAX_REVISIONS),
               "mark": mark, "memo": memo_value(payload["memo"])}
    if action == "set" and command["mark"] is None and command["memo"] is None:
        raise RunFeedbackError("invalid_input")  # a mark, a memo or both: never an empty feedback
    if action == "clear" and (command["mark"] is not None or command["memo"] is not None):
        raise RunFeedbackError("invalid_input")
    return command


def _item(record) -> dict:
    content = record.body["content"]
    return {"feedback_id": record.ref.id, "revision": record.ref.version, "target": dict(content["target"]),
            "state": content["state"], "mark": content["mark"], "memo": content["memo"],
            "recorded_at_utc": record.body["created_at_utc"], "ref": record.ref.as_dict()}


def _order(item):
    target = item["target"]
    if target["scope"] == "run":
        return (0, "", 0, 0)
    return (1, target["node_id"], target["visit_no"], target["attempt_no"] or 0)


def _run_records(domain, db, roots, run_id):
    """Every feedback record of one run (every revision), read back and checked."""

    needle = f'"run_id":"{run_id}"'.encode()
    rows = db.execute(
        "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND kind=? AND instr(body, ?) > 0 "
        "ORDER BY id, version LIMIT ?", (roots.genesis.id, FEEDBACK_KIND, needle, MAX_RECORDS_PER_RUN + 1)).fetchall()
    if len(rows) > MAX_RECORDS_PER_RUN:
        raise RunFeedbackError("too_large")
    records = []
    for row in rows:
        record = domain._load(db, EntityRef(FEEDBACK_KIND, row["id"], row["version"], row["sha256"]), roots)[0]
        content = record.body["content"]
        if type(content) is not dict or content.get("schema_version") != RECORD_SCHEMA:
            raise RunFeedbackError("unavailable")
        if content["run_id"] == run_id:
            records.append(record)
    return records


def _current_from(records) -> dict:
    latest = {}
    for record in records:
        known = latest.get(record.ref.id)
        if known is None or known.ref.version < record.ref.version:
            latest[record.ref.id] = record
    items = sorted((_item(record) for record in latest.values()), key=_order)
    run = next((item for item in items if item["target"]["scope"] == "run"), None)
    return {"run": run, "steps": [item for item in items if item["target"]["scope"] == "step"]}


def current_feedback(domain, run_id: str) -> dict:
    """The latest revision of every target of one run (a cleared one included, with its
    state): `{"run": item | None, "steps": [item, …]}`. A read for the trace; no auth here."""

    with domain._connection() as db:
        roots = domain._read_roots(db)
        return _current_from(_run_records(domain, db, roots, run_id))


def feedback_history(domain, db, roots, run_id: str) -> list[dict]:
    """Every revision of one run's feedback in the order it was recorded (the export's view)."""

    items = [_item(record) for record in _run_records(domain, db, roots, run_id)]
    return sorted(items, key=lambda item: (item["recorded_at_utc"], item["feedback_id"], item["revision"]))


class PersistentRunFeedback:
    """Owner-authenticated process feedback over one app's run traces."""

    def __init__(self, traces):
        if type(traces) is not PersistentRunTraces:
            raise TypeError("Exact PersistentRunTraces required")
        self._traces = traces
        self._domain = traces._domain
        self._owner = traces._owner
        self._runs = traces._runs

    # --- the target must be in the run's own trace ----------------------------------------

    def _check_target(self, request, run_id, target, *, base_path):
        trace = self._traces.read(request, run_id, base_path=base_path, feedback=False)
        if target["scope"] == "run":
            return
        node = next((item for item in trace["nodes"] if item["node_id"] == target["node_id"]), None)
        visit = None if node is None else next(
            (item for item in node["visits"] if item["visit_no"] == target["visit_no"]), None)
        if visit is None:
            raise RunFeedbackError("not_found")
        numbers = [item["attempt_no"] for item in visit["attempts"]]
        if (target["attempt_no"] is None) != (not numbers) or (
                target["attempt_no"] is not None and target["attempt_no"] not in numbers):
            raise RunFeedbackError("not_found")

    # --- records ------------------------------------------------------------------------------

    def _latest(self, db, roots, feedback_id):
        row = db.execute(
            "SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind=? AND id=? "
            "ORDER BY version DESC LIMIT 1", (roots.genesis.id, FEEDBACK_KIND, feedback_id)).fetchone()
        if row is None:
            return None
        return self._domain._load(db, EntityRef(FEEDBACK_KIND, feedback_id, row["version"], row["sha256"]), roots)[0]

    def _by_command(self, db, roots, command_id):
        needle = f'"command_id":"{command_id}"'.encode()
        for row in db.execute(
                "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND kind=? AND instr(body, ?) > 0 "
                "LIMIT 4", (roots.genesis.id, FEEDBACK_KIND, needle)).fetchall():
            record = self._domain._load(db, EntityRef(FEEDBACK_KIND, row["id"], row["version"], row["sha256"]),
                                        roots)[0]
            if record.body["content"].get("command_id") == command_id:
                return record
        return None

    @staticmethod
    def _replay(record, digest):
        if record.body["content"]["command_digest"] != digest:
            raise RunFeedbackError("conflict")  # the same command id with another body
        return record

    def _event(self, db, roots, actor_ref, record, command_id, run_id):
        content = record.body["content"]
        stamp = record.body["created_at_utc"]
        return _append_event_in_transaction(
            db, vault_id=roots.genesis.id, recorded_at_utc=stamp, observed_at_utc=stamp, actor_kind="human",
            actor_ref=actor_ref, event_type="feedback.recorded",
            object_refs=(ObjectRef(FEEDBACK_KIND, record.ref.id, record.ref.version, record.ref.sha256),
                         ObjectRef("run", run_id)),
            correlation_id=command_id, causation_id=None, status="succeeded", error_code=None,
            public_metadata={"scope": content["target"]["scope"], "mark": content["mark"] or "none",
                             "memo": content["memo"] is not None, "cleared": content["state"] == "cleared",
                             "revision": record.ref.version},
            private_evidence_refs=(), retention_class="core", policy_ref=roots.access_policy)

    # --- the owner's routes ----------------------------------------------------------------------

    @_closed
    def record(self, request, run_id, payload, *, base_path) -> dict:
        """Set or clear one target's feedback as a new revision: (201 body, replayed)."""

        _authenticate_owner(self._owner, request)
        command = _command(payload)
        run_id = _uuid(run_id)
        target = command["target"]
        self._check_target(request, run_id, target, base_path=base_path)
        feedback_id = feedback_identity(run_id, target)
        digest = sha256(canonical_json({"run_id": run_id, **{name: command[name] for name in (
            "action", "target", "expected_revision", "mark", "memo")}})).hexdigest()
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            replay = self._by_command(db, roots, command["command_id"])
            manifest = self._runs._manifest_by_run(db, roots, run_id)
        if replay is not None:
            return self._answer(self._replay(replay, digest), run_id, replayed=True)
        if manifest is None:
            raise RunFeedbackError("not_found")
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            replay = self._by_command(db, roots, command["command_id"])
            if replay is not None:
                record = self._replay(replay, digest)
            else:
                latest = self._latest(db, roots, feedback_id)
                current = 0 if latest is None else latest.ref.version
                if current != command["expected_revision"]:
                    raise RunFeedbackError("conflict")  # another screen changed it first
                if latest is not None and (latest.body["content"]["run_id"], latest.body["content"]["target"]) \
                        != (run_id, target):
                    raise RunFeedbackError("unavailable")
                if command["action"] == "clear" and (latest is None or latest.body["content"]["state"] != "set"):
                    raise RunFeedbackError("invalid_input")  # nothing to clear
                if current >= MAX_REVISIONS:
                    raise RunFeedbackError("too_large")
                cleared = command["action"] == "clear"
                record = ImmutableRecord.create(
                    kind=FEEDBACK_KIND, id=feedback_id, version=current + 1, created_at_utc=_stamp(),
                    actor_ref=actor_ref, parent_refs=(manifest.manifest_ref,) if latest is None else (latest.ref,),
                    purpose="operational", access_policy_ref=roots.access_policy,
                    retention_policy_ref=roots.retention_policy,
                    content={"schema_version": RECORD_SCHEMA, "run_id": run_id, "target": target,
                             "state": "cleared" if cleared else "set", "mark": None if cleared else command["mark"],
                             "memo": None if cleared else command["memo"], "command_id": command["command_id"],
                             "command_digest": digest})
                self._domain._put_in_transaction(db, record)
                self._event(db, roots, actor_ref, record, command["command_id"], run_id)
                replay = None
        return self._answer(record, run_id, replayed=replay is not None)

    def _answer(self, record, run_id, *, replayed):
        return {"schema_version": LIST_SCHEMA, "run_id": run_id, "recorded": _item(record), "replayed": replayed,
                "current": current_feedback(self._domain, run_id)}

    @_closed
    def read(self, request, run_id, *, base_path) -> dict:
        """The run's feedback: the latest revision of every target and the whole history."""

        if request is None:
            raise RunFeedbackError("unauthenticated")
        self._owner.authenticate_bound(request.session)
        run_id = _uuid(run_id)
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            if self._runs._manifest_by_run(db, roots, run_id) is None:
                raise RunFeedbackError("not_found")
            records = _run_records(self._domain, db, roots, run_id)
        history = sorted((_item(record) for record in records),
                         key=lambda item: (item["recorded_at_utc"], item["feedback_id"], item["revision"]))
        return {"schema_version": LIST_SCHEMA, "run_id": run_id, "memo_max_chars": MAX_MEMO_CHARS,
                "marks": list(MARKS), "current": _current_from(records), "history": history}
