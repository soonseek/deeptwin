"""Durable control-plane journal for explicitly supplied, isolated audit storage.

This module records dispatch intent and lifecycle state; it performs no provider
calls or semantic scoring. Hashes detect accidental payload corruption, not
adversarial storage modification. Recovery requires caller-confirmed worker absence.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def positive_seconds(value):
    if type(value) not in (int, float):
        raise ValueError("seconds must be a positive finite number")
    try:
        seconds = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError("seconds must be a positive finite number") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("seconds must be a positive finite number")
    return seconds


def identifier(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) is None:
        raise ValueError("identifier must contain 1 to 100 ASCII letters, digits, underscores or hyphens")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("nonfinite JSON number")


def _parse_canonical(payload):
    value = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if canonical(value) != payload:
        raise ValueError("JSON must use canonical encoding")
    return value


def _bounded_json(value, limit):
    payload = canonical(value)
    if len(payload.encode("utf-8")) > limit:
        raise ValueError("canonical JSON exceeds the byte limit")
    return payload


@dataclass(frozen=True)
class FrozenCall:
    request_id: str
    run_id: str
    purpose: str
    candidate_id: str
    candidate_version: str
    prompt: str
    schema_json: str
    manifest_json: str
    selection_json: str
    metadata_json: str

    def __post_init__(self):
        data = self.as_dict()
        if any(not isinstance(value, str) or not value for value in data.values()):
            raise ValueError("all call fields must be nonempty strings")
        identifier(self.request_id)
        identifier(self.run_id)
        if self.purpose not in {"review", "counterexample_proposal", "counterexample_validity", "candidate_response"}:
            raise ValueError("unsupported critic purpose")
        for name in ("schema_json", "manifest_json", "selection_json", "metadata_json"):
            _parse_canonical(data[name])
        _bounded_json(data, 1_000_000)

    def as_dict(self):
        return asdict(self)

    @property
    def digest(self):
        return hashlib.sha256(canonical(self.as_dict()).encode("utf-8")).hexdigest()


_PARENT_PURPOSES = {
    "counterexample_proposal": "review",
    "counterexample_validity": "counterexample_proposal",
    "candidate_response": "counterexample_validity",
}


class Ledger:
    """Journal at an explicit dedicated path; callers choose synthetic audit storage.

    Deadlines use the injected wall clock so they survive reopening the journal.
    Each operation uses and closes its own SQLite connection.
    """

    def __init__(self, path: Path, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        if not self.path.is_absolute() or self.path.name != "eval.sqlite3":
            raise ValueError("an absolute dedicated eval.sqlite3 path is required")
        for component in (self.path, *self.path.parents):
            if component.is_symlink():
                raise ValueError("audit storage must not contain symlinks")
        parent = self.path.parent
        if parent.exists():
            for entry in parent.iterdir():
                if entry.name not in {"eval.sqlite3", "eval.sqlite3-journal"} or entry.is_symlink() or not entry.is_file():
                    raise ValueError("audit storage requires a dedicated directory of regular files")
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent.chmod(0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        with self._transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, deadline REAL NOT NULL,
                max_calls INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                payload TEXT NOT NULL, digest TEXT NOT NULL,
                state TEXT NOT NULL, details TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY, request_id TEXT NOT NULL REFERENCES calls(id),
                at REAL NOT NULL, kind TEXT NOT NULL, details TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS evidence (
                request_id TEXT NOT NULL REFERENCES calls(id),
                sha TEXT NOT NULL,
                PRIMARY KEY (request_id, sha)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS authored_evidence (
                run_id TEXT NOT NULL REFERENCES runs(id),
                sha TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_version TEXT NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY (run_id, sha)
            )""")

    @contextmanager
    def _transaction(self, *, write=True):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def open_run(self, run_id, *, max_calls, max_seconds):
        identifier(run_id)
        if type(max_calls) is not int or not 1 <= max_calls <= 1_000_000:
            raise ValueError("max_calls must be an integer from 1 to 1000000")
        seconds = positive_seconds(max_seconds)
        try:
            deadline = self.clock() + seconds
            finite = math.isfinite(deadline)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("run deadline must be finite") from exc
        if not finite:
            raise ValueError("run deadline must be finite")
        with self._transaction() as db:
            db.execute("INSERT INTO runs (id, deadline, max_calls) VALUES (?, ?, ?)", (run_id, deadline, max_calls))

    def reserve(self, call):
        if type(call) is not FrozenCall:
            raise ValueError("reservation requires an exact FrozenCall")
        if call.purpose in _PARENT_PURPOSES:
            # The B4 chain is mandatory, not opt-in: a downstream purpose
            # can only ever be reserved through reserve_with_lineage.
            raise ValueError("this purpose requires a lineage reservation")
        payload = canonical(call.as_dict())
        with self._transaction() as db:
            run = db.execute("SELECT * FROM runs WHERE id = ?", (call.run_id,)).fetchone()
            now = self.clock()
            if run is None or now >= run["deadline"] or run["used"] >= run["max_calls"]:
                raise ValueError("run budget unavailable")
            if db.execute("SELECT 1 FROM calls WHERE id = ?", (call.request_id,)).fetchone() is not None:
                raise ValueError("request identifier already used")
            db.execute("INSERT INTO calls (id, run_id, payload, digest, state, details) VALUES (?, ?, ?, ?, 'reserved', '{}')",
                       (call.request_id, call.run_id, payload, call.digest))
            db.execute("UPDATE runs SET used = used + 1 WHERE id = ?", (call.run_id,))
            db.execute("INSERT INTO events (request_id, at, kind, details) VALUES (?, ?, 'reserved', '{}')",
                       (call.request_id, now))

    def register_result_evidence(self, request_id, items):
        """Record the exact evidence hashes one COMPLETED call produced.

        These hashes are the only cross-call currency: a child call may
        bind its parent only through a hash registered here.
        """
        if type(items) is not list or not 1 <= len(items) <= 64 or any(
            not isinstance(item, dict) for item in items
        ):
            raise ValueError("evidence must be a bounded list of objects")
        shas = [
            hashlib.sha256(canonical(item).encode("utf-8")).hexdigest()
            for item in items
        ]
        with self._transaction() as db:
            call = db.execute(
                "SELECT state FROM calls WHERE id = ?", (request_id,),
            ).fetchone()
            if call is None:
                raise ValueError("unknown request identifier")
            if call["state"] != "completed":
                # Only a completed call's result exists as evidence.
                raise ValueError("evidence requires a completed call")
            for sha in shas:
                db.execute(
                    "INSERT OR IGNORE INTO evidence (request_id, sha) VALUES (?, ?)",
                    (request_id, sha),
                )
        return shas

    def register_authored_evidence(self, run_id, *, candidate_id, candidate_version, item, source):
        """Record one authored (not model-produced) counterexample for one run.

        An authored boundary counterexample is fixed synthetic material, not
        a proposal: it is never registered under a proposal request, so it
        cannot masquerade as model output. Its exact hash, the exact
        candidate it targets and a bounded source label are recorded before
        any validity call may bind it.
        """
        identifier(run_id)
        if (type(item) is not dict or not isinstance(candidate_id, str) or not candidate_id
                or not isinstance(candidate_version, str) or not candidate_version
                or not isinstance(source, str) or not 1 <= len(source) <= 200):
            raise ValueError("authored evidence needs an object, a candidate binding and a bounded source")
        if (item.get("candidate_id"), item.get("candidate_version")) != (candidate_id, candidate_version):
            raise ValueError("authored evidence binds a different candidate")
        sha = hashlib.sha256(canonical(item).encode("utf-8")).hexdigest()
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone() is None:
                raise ValueError("unknown run identifier")
            db.execute(
                "INSERT OR IGNORE INTO authored_evidence (run_id, sha, candidate_id, candidate_version, source)"
                " VALUES (?, ?, ?, ?, ?)",
                (run_id, sha, candidate_id, candidate_version, source),
            )
        return sha

    def reserve_with_lineage(self, call, *, parent_request_id, evidence_sha):
        """Reserve a downstream call bound to its exact parent evidence.

        Forged cross-call evidence — a hash the parent never produced, a
        parent that never completed, a parent from another run or
        candidate, or a parent of the wrong purpose — refuses (B4).

        A validity call may instead bind an authored counterexample: its
        ``parent_request_id`` is ``None`` and ``evidence_sha`` must be an
        authored hash registered for the same run and candidate.
        """
        if type(call) is not FrozenCall:
            raise ValueError("reservation requires an exact FrozenCall")
        expected_parent = _PARENT_PURPOSES.get(call.purpose)
        if expected_parent is None:
            raise ValueError("this purpose has no lineage parent")
        if parent_request_id is None:
            return self._reserve_authored(call, evidence_sha)
        needs_hash = call.purpose != "counterexample_proposal"
        if needs_hash:
            if (
                not isinstance(evidence_sha, str)
                or len(evidence_sha) != 64
            ):
                raise ValueError("a parent evidence hash is required")
        elif evidence_sha is not None:
            raise ValueError("a proposal binds its review by request only")
        payload = canonical(call.as_dict())
        with self._transaction() as db:
            parent = db.execute(
                "SELECT payload, state FROM calls WHERE id = ?",
                (parent_request_id,),
            ).fetchone()
            if parent is None:
                raise ValueError("the lineage parent does not exist")
            if parent["state"] != "completed":
                raise ValueError("the lineage parent never completed")
            parent_call = json.loads(parent["payload"])
            if parent_call["purpose"] != expected_parent:
                raise ValueError("the lineage parent purpose is wrong")
            if (
                parent_call["run_id"] != call.run_id
                or parent_call["candidate_id"] != call.candidate_id
                or parent_call["candidate_version"] != call.candidate_version
            ):
                raise ValueError(
                    "the lineage parent binds a different run or candidate"
                )
            if needs_hash:
                recorded = db.execute(
                    "SELECT 1 FROM evidence WHERE request_id = ? AND sha = ?",
                    (parent_request_id, evidence_sha),
                ).fetchone()
                if recorded is None:
                    raise ValueError(
                        "the evidence hash was never produced by this parent"
                    )
            run = db.execute(
                "SELECT * FROM runs WHERE id = ?", (call.run_id,),
            ).fetchone()
            now = self.clock()
            if run is None or now >= run["deadline"] or run["used"] >= run["max_calls"]:
                raise ValueError("run budget unavailable")
            if db.execute(
                "SELECT 1 FROM calls WHERE id = ?", (call.request_id,),
            ).fetchone() is not None:
                raise ValueError("request identifier already used")
            db.execute(
                "INSERT INTO calls (id, run_id, payload, digest, state, details) VALUES (?, ?, ?, ?, 'reserved', ?)",
                (call.request_id, call.run_id, payload, call.digest,
                 canonical({"lineage_parent": parent_request_id,
                            "lineage_sha": evidence_sha})),
            )
            db.execute("UPDATE runs SET used = used + 1 WHERE id = ?", (call.run_id,))
            db.execute(
                "INSERT INTO events (request_id, at, kind, details) VALUES (?, ?, 'reserved', ?)",
                (call.request_id, now,
                 canonical({"lineage_parent": parent_request_id})),
            )

    def _reserve_authored(self, call, evidence_sha):
        if call.purpose != "counterexample_validity":
            raise ValueError("only a validity call may bind an authored counterexample")
        if not isinstance(evidence_sha, str) or re.fullmatch(r"[0-9a-f]{64}", evidence_sha) is None:
            raise ValueError("an authored evidence hash is required")
        payload = canonical(call.as_dict())
        with self._transaction() as db:
            authored = db.execute(
                "SELECT candidate_id, candidate_version, source FROM authored_evidence"
                " WHERE run_id = ? AND sha = ?", (call.run_id, evidence_sha),
            ).fetchone()
            if authored is None:
                raise ValueError("the authored evidence hash was never registered for this run")
            if (authored["candidate_id"], authored["candidate_version"]) != (
                    call.candidate_id, call.candidate_version):
                raise ValueError("the authored evidence binds a different candidate")
            run = db.execute("SELECT * FROM runs WHERE id = ?", (call.run_id,)).fetchone()
            now = self.clock()
            if run is None or now >= run["deadline"] or run["used"] >= run["max_calls"]:
                raise ValueError("run budget unavailable")
            if db.execute("SELECT 1 FROM calls WHERE id = ?", (call.request_id,)).fetchone() is not None:
                raise ValueError("request identifier already used")
            lineage = {"lineage_parent": None, "lineage_sha": evidence_sha,
                       "lineage_source": "authored:" + authored["source"]}
            db.execute(
                "INSERT INTO calls (id, run_id, payload, digest, state, details) VALUES (?, ?, ?, ?, 'reserved', ?)",
                (call.request_id, call.run_id, payload, call.digest, canonical(lineage)),
            )
            db.execute("UPDATE runs SET used = used + 1 WHERE id = ?", (call.run_id,))
            db.execute(
                "INSERT INTO events (request_id, at, kind, details) VALUES (?, ?, 'reserved', ?)",
                (call.request_id, now, canonical(lineage)),
            )

    def remaining(self, run_id):
        with self._transaction(write=False) as db:
            run = db.execute("SELECT deadline FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(run_id)
            return max(0, run["deadline"] - self.clock())

    def begin(self, request_id):
        with self._transaction() as db:
            call = db.execute("SELECT calls.state, runs.deadline FROM calls JOIN runs ON calls.run_id = runs.id WHERE calls.id = ?",
                              (request_id,)).fetchone()
            if call is None:
                raise KeyError(request_id)
            if call["state"] != "reserved":
                return False
            now = self.clock()
            expired = now >= call["deadline"]
            state = "timed_out" if expired else "dispatching"
            details = canonical({"transfer": "not_started"})
            db.execute("UPDATE calls SET state = ?, details = ? WHERE id = ?", (state, details, request_id))
            db.execute("INSERT INTO events (request_id, at, kind, details) VALUES (?, ?, ?, ?)",
                       (request_id, now, state, details))
            return not expired

    def finish(self, request_id, state, details):
        if state not in ("completed", "invalid", "cancelled", "timed_out", "interrupted"):
            raise ValueError("unsupported terminal state")
        if not isinstance(details, dict):
            raise ValueError("details must be a dict")
        payload = _bounded_json(details, 1_000_000)
        with self._transaction() as db:
            changed = db.execute("UPDATE calls SET state = ?, details = ? WHERE id = ? AND state IN ('reserved', 'dispatching')",
                                 (state, payload, request_id)).rowcount
            if not changed:
                return False
            db.execute("INSERT INTO events (request_id, at, kind, details) VALUES (?, ?, ?, ?)",
                       (request_id, self.clock(), state, payload))
            return True

    def cancel(self, request_id):
        return self.finish(request_id, "cancelled", {"remote_stop": "unconfirmed", "score": None})

    def observe(self, request_id, kind, details):
        if kind != "late_worker_finished" or not isinstance(details, dict):
            raise ValueError("observation requires late_worker_finished and a details dict")
        payload = _bounded_json(details, 10_000)
        with self._transaction() as db:
            db.execute("INSERT INTO events (request_id, at, kind, details) VALUES (?, ?, ?, ?)",
                       (request_id, self.clock(), kind, payload))

    def recover(self):
        """Interrupt unfinished calls only after the caller confirms workers are absent."""
        details = canonical({"reason": "restart", "score": None, "remote_stop": "unconfirmed"})
        with self._transaction() as db:
            calls = db.execute("SELECT id FROM calls WHERE state IN ('reserved', 'dispatching') ORDER BY id").fetchall()
            for call in calls:
                db.execute("UPDATE calls SET state = 'interrupted', details = ? WHERE id = ?", (details, call["id"]))
                db.execute("INSERT INTO events (request_id, at, kind, details) VALUES (?, ?, 'interrupted', ?)",
                           (call["id"], self.clock(), details))
            return len(calls)

    def get(self, request_id):
        # A read transaction keeps call state and its events in the same snapshot.
        with self._transaction(write=False) as db:
            row = db.execute("SELECT * FROM calls WHERE id = ?", (request_id,)).fetchone()
            if row is None:
                raise KeyError(request_id)
            try:
                call = FrozenCall(**_parse_canonical(row["payload"]))
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid frozen call in audit journal") from exc
            if call.digest != row["digest"]:
                raise ValueError("frozen call digest mismatch")
            events = db.execute("SELECT seq, at, kind, details FROM events WHERE request_id = ? ORDER BY seq",
                                (request_id,)).fetchall()
            return {
                "call": call.as_dict(), "digest": row["digest"], "state": row["state"],
                "details": json.loads(row["details"]),
                "events": [{"seq": event["seq"], "at": event["at"], "kind": event["kind"],
                            "details": json.loads(event["details"])} for event in events],
            }
