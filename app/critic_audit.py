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
