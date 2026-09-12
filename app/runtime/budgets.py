"""Durable finite session budgets with conservative atomic reservations."""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import re
import sqlite3
from threading import RLock
from uuid import uuid4

from ..domain.refs import EntityRef, MAX_INTEGER, canonical_json, parse_canonical, uuid_string
from ..domain.store import DomainStore, StorageError, _writer
from ..storage import Store


_DIMENSIONS = ("model_calls", "tool_calls", "node_visits", "loop_rounds",
               "output_bytes", "candidates")
_PROFILES = frozenset({"execution", "design", "growth"})
_MODES = frozenset({"subscription", "api"})
_RESERVATION_STATES = frozenset({"reserved", "dispatched", "unknown", "finalized",
                                 "overage", "cancelled"})
_AUDIT_TRANSITIONS = {
    None: frozenset({"reserved"}),
    "reserved": frozenset({"dispatched", "cancelled"}),
    "dispatched": frozenset({"unknown", "finalized", "overage"}),
    "unknown": frozenset({"finalized", "overage"}),
    "finalized": frozenset(), "overage": frozenset(), "cancelled": frozenset(),
}


class BudgetError(ValueError):
    pass


class BudgetExceeded(BudgetError):
    pass


class SessionConflict(BudgetError):
    pass


class RequestConflict(BudgetError):
    pass


class ReservationConflict(BudgetError):
    pass


class ClockError(BudgetError):
    pass


class CorruptBudget(BudgetError):
    """Persisted budget state cannot be trusted and must not authorize work."""


def _positive(name, value):
    if type(value) is not int or not 1 <= value <= MAX_INTEGER:
        raise ValueError(f"{name} must be a bounded positive integer")
    return value


def _count(name, value):
    if type(value) is not int or not 0 <= value <= MAX_INTEGER:
        raise ValueError(f"{name} must be a bounded nonnegative integer")
    return value


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    id: str
    profile: str
    provider_mode: str
    max_model_calls: int
    max_tool_calls: int
    max_node_visits: int
    max_loop_rounds: int
    max_output_bytes: int
    max_concurrency: int
    max_wall_seconds: int
    max_candidates: int
    currency: str | None
    max_api_microunits: int | None
    body_bytes: bytes

    @classmethod
    def create(cls, *, profile, provider_mode, max_model_calls, max_tool_calls,
               max_node_visits, max_loop_rounds, max_output_bytes, max_concurrency,
               max_wall_seconds, currency=None, max_api_microunits=None,
               max_candidates=1):
        if type(profile) is not str or profile not in _PROFILES:
            raise ValueError("Unknown budget profile")
        if type(provider_mode) is not str or provider_mode not in _MODES:
            raise ValueError("Unknown provider mode")
        values = {
            "max_model_calls": _positive("max_model_calls", max_model_calls),
            "max_tool_calls": _positive("max_tool_calls", max_tool_calls),
            "max_node_visits": _positive("max_node_visits", max_node_visits),
            "max_loop_rounds": _positive("max_loop_rounds", max_loop_rounds),
            "max_output_bytes": _positive("max_output_bytes", max_output_bytes),
            "max_concurrency": _positive("max_concurrency", max_concurrency),
            "max_wall_seconds": _positive("max_wall_seconds", max_wall_seconds),
            "max_candidates": _positive("max_candidates", max_candidates),
        }
        if provider_mode == "api":
            if (type(currency) is not str or re.fullmatch(r"[A-Z]{3}", currency) is None
                    or type(max_api_microunits) is not int
                    or not 1 <= max_api_microunits <= MAX_INTEGER):
                raise ValueError("API mode requires an explicit currency and positive cap")
        elif currency is not None or max_api_microunits is not None:
            raise ValueError("Subscription mode cannot claim an API currency cap")
        body = canonical_json({"schema_version": "budget-policy-v1", "profile": profile,
            "provider_mode": provider_mode, **values, "currency": currency,
            "max_api_microunits": max_api_microunits})
        return cls(sha256(body).hexdigest(), profile, provider_mode,
                   *(values[name] for name in ("max_model_calls", "max_tool_calls",
                     "max_node_visits", "max_loop_rounds", "max_output_bytes",
                     "max_concurrency", "max_wall_seconds", "max_candidates")),
                   currency, max_api_microunits, body)

    @classmethod
    def recommended(cls, profile, *, provider_mode, currency=None,
                    max_api_microunits=None):
        defaults = {
            "execution": dict(max_model_calls=100, max_tool_calls=200,
                              max_node_visits=200, max_loop_rounds=5,
                              max_output_bytes=64 * 1024 * 1024, max_concurrency=2,
                              max_wall_seconds=1800, max_candidates=1),
            "design": dict(max_model_calls=64, max_tool_calls=128,
                           max_node_visits=200, max_loop_rounds=2,
                           max_output_bytes=64 * 1024 * 1024, max_concurrency=2,
                           max_wall_seconds=1200, max_candidates=12),
            "growth": dict(max_model_calls=500, max_tool_calls=1000,
                           max_node_visits=2000, max_loop_rounds=10,
                           max_output_bytes=256 * 1024 * 1024, max_concurrency=2,
                           max_wall_seconds=7200, max_candidates=10),
        }
        if profile not in defaults:
            raise ValueError("Unknown budget profile")
        return cls.create(profile=profile, provider_mode=provider_mode,
                          currency=currency, max_api_microunits=max_api_microunits,
                          **defaults[profile])

    def domain_content(self):
        """Exact immutable-record content used to bind runtime attempts."""
        return {
            "schema_version": "budget-policy-binding-v1",
            "policy_hash": self.id,
            "policy": parse_canonical(self.body_bytes),
        }


@dataclass(frozen=True, slots=True)
class Reservation:
    request_id: str
    session_id: str
    state: str
    request_hash: str
    model_calls: int
    tool_calls: int
    node_visits: int
    loop_rounds: int
    output_bytes: int
    candidates: int
    api_microunits: int | None


@dataclass(frozen=True, slots=True)
class BudgetDispatchRequest:
    """Typed request consumed by the atomic runtime send-intent boundary."""

    session_id: str
    request_id: str
    policy_ref: EntityRef
    model_calls: int
    tool_calls: int
    node_visits: int
    loop_rounds: int
    output_bytes: int
    candidates: int
    api_microunits: int | None

    @classmethod
    def create(cls, *, session_id, request_id, policy_ref, model_calls, tool_calls,
               node_visits, loop_rounds, output_bytes, api_microunits, candidates=0):
        uuid_string(session_id)
        uuid_string(request_id)
        if type(policy_ref) is not EntityRef or policy_ref.kind != "budget_policy":
            raise ValueError("Budget dispatch requires an exact budget_policy reference")
        values = {name: _count(name, value) for name, value in {
            "model_calls": model_calls,
            "tool_calls": tool_calls,
            "node_visits": node_visits,
            "loop_rounds": loop_rounds,
            "output_bytes": output_bytes,
            "candidates": candidates,
        }.items()}
        if not any(values.values()):
            raise ValueError("Budget dispatch must consume at least one finite dimension")
        if api_microunits is not None:
            _count("api_microunits", api_microunits)
        return cls(
            session_id,
            request_id,
            policy_ref,
            *(values[name] for name in _DIMENSIONS),
            api_microunits,
        )

    def as_dict(self):
        return {
            "session_id": self.session_id,
            "request_id": self.request_id,
            "policy_ref": self.policy_ref.as_dict(),
            **{name: getattr(self, name) for name in _DIMENSIONS},
            "api_microunits": self.api_microunits,
        }


_RUNTIME_MIGRATIONS_DDL = (
    "CREATE TABLE runtime_migrations(component TEXT NOT NULL, version INTEGER NOT NULL "
    "CHECK(typeof(version)='integer' AND version>0), sha256 TEXT NOT NULL, "
    "PRIMARY KEY(component,version))"
)
_DDL = (
"""CREATE TABLE runtime_budget_sessions (
  id TEXT PRIMARY KEY, policy BLOB NOT NULL, policy_hash TEXT NOT NULL,
  started_at INTEGER NOT NULL, deadline INTEGER NOT NULL, last_observed INTEGER NOT NULL,
  model_calls INTEGER NOT NULL DEFAULT 0, tool_calls INTEGER NOT NULL DEFAULT 0,
  node_visits INTEGER NOT NULL DEFAULT 0, loop_rounds INTEGER NOT NULL DEFAULT 0,
  output_bytes INTEGER NOT NULL DEFAULT 0, candidates INTEGER NOT NULL DEFAULT 0,
  api_microunits INTEGER, active INTEGER NOT NULL DEFAULT 0,
  reservation_rows INTEGER NOT NULL DEFAULT 0,
  accounting_overflow INTEGER NOT NULL DEFAULT 0,
  audit_sequence INTEGER NOT NULL DEFAULT 0,
  audit_head TEXT,
  blocked_reason TEXT)""",
"""CREATE TABLE runtime_budget_reservations (
  request_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES runtime_budget_sessions(id),
  request_hash TEXT NOT NULL, state TEXT NOT NULL, created_at INTEGER NOT NULL,
  dispatched_at INTEGER, settled_at INTEGER, usage_finality TEXT,
  model_calls INTEGER NOT NULL, tool_calls INTEGER NOT NULL, node_visits INTEGER NOT NULL,
  loop_rounds INTEGER NOT NULL, output_bytes INTEGER NOT NULL, candidates INTEGER NOT NULL,
  api_microunits INTEGER,
  actual_model_calls INTEGER, actual_tool_calls INTEGER, actual_node_visits INTEGER,
  actual_loop_rounds INTEGER, actual_output_bytes INTEGER, actual_candidates INTEGER,
  actual_api_microunits INTEGER)""",
"""CREATE INDEX runtime_budget_reservations_session
  ON runtime_budget_reservations(session_id, state)""",
"""CREATE TABLE runtime_budget_audit (
  session_id TEXT NOT NULL REFERENCES runtime_budget_sessions(id),
  sequence INTEGER NOT NULL, request_id TEXT, kind TEXT NOT NULL,
  observed_at INTEGER NOT NULL, snapshot BLOB NOT NULL,
  previous_hash TEXT, event_hash TEXT NOT NULL,
  PRIMARY KEY(session_id, sequence))""",
"""CREATE INDEX runtime_budget_audit_request
  ON runtime_budget_audit(session_id, request_id, sequence)""",
)
RUNTIME_MIGRATION_SHA256 = sha256("\n".join(_DDL).encode("utf-8")).hexdigest()
_BUDGET_SCHEMA_OBJECTS = frozenset({
    "runtime_budget_sessions", "runtime_budget_reservations", "runtime_budget_audit",
    "runtime_budget_reservations_session", "runtime_budget_audit_request",
})


def _normalize_schema_sql(value):
    if type(value) is not str:
        return ""
    # SQLite preserves harmless authoring whitespace in sqlite_master.  Compare
    # semantic tokens so the ledger-first and budget-first canonical declarations
    # agree while a missing CHECK, extra clause or rewritten object cannot hide.
    compact = " ".join(value.split()).casefold()
    return re.sub(r"\s*([(),=<>])\s*", r"\1", compact)


_EXPECTED_MIGRATION_SQL = _normalize_schema_sql(_RUNTIME_MIGRATIONS_DDL)
_EXPECTED_SCHEMA_SQL = {}
for _statement in _DDL:
    _match = re.match(r"CREATE (?:TABLE|INDEX) ([a-z_]+)", _statement)
    if _match is None:  # pragma: no cover - module constant construction invariant
        raise RuntimeError("Invalid runtime budget migration statement")
    _EXPECTED_SCHEMA_SQL[_match.group(1)] = _normalize_schema_sql(_statement)


class BudgetBook:
    """SQLite budget owner with an internal same-transaction dispatch boundary."""

    def __init__(self, legacy_store, *, clock):
        if type(legacy_store) is not Store or not callable(clock):
            raise TypeError("BudgetBook requires the existing Store and a trusted clock")
        self._domain = DomainStore(legacy_store)
        self.path = self._domain.path
        self.clock = clock
        self._clock_lock = RLock()
        self._last_now = None
        self._schema_ready = False
        with self._connection(immediate=True) as db:
            self._install(db)
        self._schema_ready = True

    @staticmethod
    def _migration_table_shape(db):
        return [(row["name"], row["type"].upper(), row["notnull"], row["pk"])
                for row in db.execute("PRAGMA table_info(runtime_migrations)")]

    @classmethod
    def _install(cls, db):
        migration_exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_migrations'"
        ).fetchone() is not None
        if not migration_exists:
            db.execute(_RUNTIME_MIGRATIONS_DDL)
        expected_shape = [
            ("component", "TEXT", 1, 1),
            ("version", "INTEGER", 1, 2),
            ("sha256", "TEXT", 1, 0),
        ]
        if cls._migration_table_shape(db) != expected_shape:
            raise CorruptBudget("Shared runtime migration ledger has an incompatible shape")
        migration_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='runtime_migrations'"
        ).fetchone()
        if (migration_sql is None
                or _normalize_schema_sql(migration_sql["sql"]) != _EXPECTED_MIGRATION_SQL):
            raise CorruptBudget("Shared runtime migration ledger constraints are incompatible")
        probe = f"__budget_schema_constraint_probe_{uuid4().hex}__"
        probe_digest = "0" * 64
        try:
            db.execute("INSERT INTO runtime_migrations VALUES (?,?,?)",
                       (probe, 1, probe_digest))
        except sqlite3.IntegrityError as exc:
            raise CorruptBudget("Shared runtime migration ledger rejects a valid version") from exc
        else:
            deleted = db.execute(
                "DELETE FROM runtime_migrations WHERE component=? AND version=1 AND sha256=?",
                (probe, probe_digest),
            ).rowcount
            if deleted != 1:
                raise CorruptBudget("Shared runtime migration ledger changed a probe row")
        for suffix, invalid in (("zero", 0), ("real", 1.5)):
            try:
                db.execute("INSERT INTO runtime_migrations VALUES (?,?,?)",
                           (f"{probe}_{suffix}", invalid, "0" * 64))
            except sqlite3.IntegrityError:
                continue
            raise CorruptBudget("Shared runtime migration ledger lacks the exact version constraint")

        stored_objects = {row["name"]: _normalize_schema_sql(row["sql"])
                          for row in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE name IN (?,?,?,?,?)",
            tuple(sorted(_BUDGET_SCHEMA_OBJECTS)))}
        owned_tables = ("runtime_migrations", "runtime_budget_sessions",
                        "runtime_budget_reservations", "runtime_budget_audit")
        if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='trigger' LIMIT 1"
        ).fetchone() is not None:
            raise CorruptBudget("Unexpected shared-database trigger")
        unexpected = []
        for row in db.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE type='index' AND lower(tbl_name) IN (?,?,?,?)",
                owned_tables):
            automatic = row["type"] == "index" and row["sql"] is None \
                and row["name"].casefold().startswith("sqlite_autoindex_")
            expected = row["name"].casefold() in _BUDGET_SCHEMA_OBJECTS
            if not automatic and not expected:
                unexpected.append((row["type"], row["name"], row["tbl_name"]))
        if unexpected:
            raise CorruptBudget("Unexpected runtime budget schema object")
        objects = set(stored_objects)
        rows = list(db.execute(
            "SELECT version,sha256 FROM runtime_migrations WHERE component='budgets' "
            "ORDER BY version"))
        if rows:
            if ([(row["version"], row["sha256"]) for row in rows]
                    != [(1, RUNTIME_MIGRATION_SHA256)]
                    or objects != _BUDGET_SCHEMA_OBJECTS
                    or stored_objects != _EXPECTED_SCHEMA_SQL):
                raise CorruptBudget("Runtime budget migration digest or schema is inconsistent")
            return
        if objects:
            raise CorruptBudget("Unversioned or partial runtime budget schema exists")
        for statement in _DDL:
            db.execute(statement)
        db.execute("INSERT INTO runtime_migrations(component,version,sha256) VALUES ('budgets',1,?)",
                   (RUNTIME_MIGRATION_SHA256,))

    @contextmanager
    def _connection(self, *, immediate=False):
        try:
            with _writer(), self._domain._connection(write=immediate) as db:
                db.execute("PRAGMA trusted_schema=OFF")
                settings = {
                    name: db.execute(f"PRAGMA {name}").fetchone()[0]
                    for name in ("journal_mode", "synchronous", "fullfsync",
                                 "foreign_keys", "trusted_schema")
                }
                if (type(settings["journal_mode"]) is not str
                        or settings["journal_mode"].casefold() != "wal"
                        or settings["synchronous"] != 2
                        or settings["fullfsync"] != 1
                        or settings["foreign_keys"] != 1
                        or settings["trusted_schema"] != 0):
                    raise CorruptBudget(
                        "Runtime budget database safety settings are unavailable"
                    )
                if self._schema_ready:
                    self._assert_transaction_schema(db)
                yield db
        except StorageError as exc:
            raise CorruptBudget("Runtime budget vault path is unsafe") from exc

    def _now(self):
        with self._clock_lock:
            try:
                value = self.clock()
            except Exception:
                raise ClockError("Trusted budget clock failed") from None
            if type(value) is not int or not 0 <= value <= MAX_INTEGER:
                raise ClockError("Trusted clock must return a bounded integer")
            if self._last_now is not None and value < self._last_now:
                raise ClockError("Trusted budget clock moved backwards")
            self._last_now = value
            return value

    def _observed_clock_floor(self):
        with self._clock_lock:
            if type(self._last_now) is not int:
                raise ClockError("Trusted budget clock has not been observed")
            return self._last_now

    def sqlite_settings(self):
        """Observed settings on this component's configured connection."""
        with self._connection() as db:
            return {name: db.execute(f"PRAGMA {name}").fetchone()[0] for name in
                    ("journal_mode", "synchronous", "fullfsync", "foreign_keys",
                     "busy_timeout", "trusted_schema")}

    @staticmethod
    def _max_reservations(policy):
        return min(MAX_INTEGER, sum(getattr(policy, "max_" + name)
                                    for name in _DIMENSIONS if name != "output_bytes"))

    @staticmethod
    def _reservation_snapshot(row):
        names = ("request_id", "session_id", "request_hash", "state", "created_at",
                 "dispatched_at", "settled_at", "usage_finality", *_DIMENSIONS,
                 "api_microunits", *("actual_" + name for name in _DIMENSIONS),
                 "actual_api_microunits")
        return canonical_json({name: row[name] for name in names})

    @staticmethod
    def _append_audit(db, session_id, request_id, kind, observed_at, snapshot):
        if type(snapshot) is not bytes:
            raise TypeError("Audit snapshots must be canonical bytes")
        previous = db.execute(
            "SELECT sequence,event_hash FROM runtime_budget_audit WHERE session_id=? "
            "ORDER BY sequence DESC LIMIT 1", (session_id,)).fetchone()
        sequence = 1 if previous is None else previous["sequence"] + 1
        previous_hash = None if previous is None else previous["event_hash"]
        envelope = canonical_json({"session_id": session_id, "sequence": sequence,
            "request_id": request_id, "kind": kind, "observed_at": observed_at,
            "snapshot_sha256": sha256(snapshot).hexdigest(),
            "previous_hash": previous_hash})
        event_hash = sha256(envelope).hexdigest()
        db.execute("INSERT INTO runtime_budget_audit VALUES (?,?,?,?,?,?,?,?)",
                   (session_id, sequence, request_id, kind, observed_at, snapshot,
                    previous_hash, event_hash))
        changed = db.execute(
            "UPDATE runtime_budget_sessions SET audit_sequence=?,audit_head=? "
            "WHERE id=? AND audit_sequence=? AND audit_head IS ?",
            (sequence, event_hash, session_id, sequence - 1, previous_hash)).rowcount
        if changed != 1:
            raise CorruptBudget("Runtime budget audit head changed concurrently")

    def _append_reservation_audit(self, db, request_id, observed_at):
        row = db.execute("SELECT * FROM runtime_budget_reservations WHERE request_id=?",
                         (request_id,)).fetchone()
        if row is None:
            raise CorruptBudget("Reservation disappeared before audit append")
        self._append_audit(db, row["session_id"], request_id, row["state"], observed_at,
                           self._reservation_snapshot(row))

    def _validate_audit(self, db, session, policy):
        expected_sequence = 1
        previous_hash = None
        previous_time = None
        states = {}
        snapshots = {}
        reservation_rows = 0
        physical_rows = {row["request_id"]: row for row in db.execute(
            "SELECT * FROM runtime_budget_reservations WHERE session_id=?",
            (session["id"],))}
        for event in db.execute(
                "SELECT * FROM runtime_budget_audit WHERE session_id=? ORDER BY sequence",
                (session["id"],)):
            try:
                if event["sequence"] != expected_sequence:
                    raise ValueError("Audit sequence is not contiguous")
                observed = _count("audit observed_at", event["observed_at"])
                if (previous_time is not None and observed < previous_time) or observed > session["last_observed"]:
                    raise ValueError("Audit time is inconsistent")
                if type(event["snapshot"]) is not bytes:
                    raise ValueError("Audit snapshot is not a BLOB")
                snapshot = event["snapshot"]
                parse_canonical(snapshot)
                envelope = canonical_json({"session_id": session["id"],
                    "sequence": expected_sequence, "request_id": event["request_id"],
                    "kind": event["kind"], "observed_at": observed,
                    "snapshot_sha256": sha256(snapshot).hexdigest(),
                    "previous_hash": previous_hash})
                if (event["previous_hash"] != previous_hash
                        or event["event_hash"] != sha256(envelope).hexdigest()):
                    raise ValueError("Audit hash chain mismatch")
                if expected_sequence == 1:
                    expected_start = canonical_json({"policy_hash": session["policy_hash"],
                        "started_at": session["started_at"], "deadline": session["deadline"]})
                    if (event["request_id"] is not None or event["kind"] != "session_started"
                            or snapshot != expected_start or observed != session["started_at"]):
                        raise ValueError("Invalid budget session genesis event")
                else:
                    request_id = uuid_string(event["request_id"])
                    kind = event["kind"]
                    if type(kind) is not str or kind not in _RESERVATION_STATES:
                        raise ValueError("Unknown budget audit transition")
                    if kind not in _AUDIT_TRANSITIONS[states.get(request_id)]:
                        raise ValueError("Invalid budget audit transition")
                    body = parse_canonical(snapshot)
                    if (type(body) is not dict or body.get("request_id") != request_id
                            or body.get("session_id") != session["id"]
                            or body.get("state") != kind):
                        raise ValueError("Audit snapshot identity mismatch")
                    states[request_id] = kind
                    snapshots[request_id] = snapshot
                    if kind == "reserved":
                        reservation_rows += 1
                previous_hash = event["event_hash"]
                previous_time = observed
                expected_sequence += 1
            except (TypeError, ValueError, KeyError) as exc:
                raise CorruptBudget("Runtime budget audit failed integrity validation") from exc
        if expected_sequence == 1:
            raise CorruptBudget("Runtime budget audit is missing its genesis event")
        if (session["audit_sequence"] != expected_sequence - 1
                or session["audit_head"] != previous_hash):
            raise CorruptBudget("Runtime budget audit head does not match its chain")
        if (set(states) != set(physical_rows)
                or reservation_rows != session["reservation_rows"]):
            raise CorruptBudget("Runtime budget audit does not match reservation membership")
        for request_id, row in physical_rows.items():
            if snapshots[request_id] != self._reservation_snapshot(row):
                raise CorruptBudget("Runtime budget row differs from its latest audit snapshot")

    @staticmethod
    def _synchronize_accounting(db, session_id):
        """Rebuild bounded cache counters from authoritative reservation rows."""
        totals = {name: 0 for name in _DIMENSIONS}
        api_total = 0
        active = 0
        saw_overage = False
        for row in db.execute(
                "SELECT * FROM runtime_budget_reservations WHERE session_id=?",
                (session_id,)):
            if row["state"] in ("reserved", "dispatched", "unknown"):
                charged = {name: row[name] for name in _DIMENSIONS}
                charged_api = row["api_microunits"] or 0
                active += 1
            elif row["state"] in ("finalized", "overage"):
                charged = {name: row["actual_" + name] for name in _DIMENSIONS}
                charged_api = row["actual_api_microunits"] or 0
                saw_overage = saw_overage or row["state"] == "overage"
            else:
                charged = {name: 0 for name in _DIMENSIONS}
                charged_api = 0
            for name in _DIMENSIONS:
                totals[name] += charged[name]
            api_total += charged_api
        overflow = any(value > MAX_INTEGER for value in (*totals.values(), api_total))
        assignments = ",".join(f"{name}=?" for name in _DIMENSIONS)
        db.execute(f"UPDATE runtime_budget_sessions SET {assignments},api_microunits=?,"
                   "active=?,accounting_overflow=?,blocked_reason=? WHERE id=?",
                   (*(min(MAX_INTEGER, totals[name]) for name in _DIMENSIONS),
                    min(MAX_INTEGER, api_total), active, int(overflow),
                    "reservation_overrun" if saw_overage else None, session_id))

    @staticmethod
    def _policy(row):
        try:
            if type(row["policy"]) is not bytes:
                raise TypeError("Persisted policy is not a BLOB")
            encoded = row["policy"]
            body = parse_canonical(encoded)
            expected = {"schema_version", "profile", "provider_mode",
                        "max_model_calls", "max_tool_calls", "max_node_visits",
                        "max_loop_rounds", "max_output_bytes", "max_concurrency",
                        "max_wall_seconds", "max_candidates", "currency",
                        "max_api_microunits"}
            if type(body) is not dict or set(body) != expected:
                raise ValueError("Unexpected persisted policy fields")
            if body["schema_version"] != "budget-policy-v1":
                raise ValueError("Unknown persisted policy schema")
            policy = BudgetPolicy.create(**{key: value for key, value in body.items()
                if key != "schema_version"})
            if (policy.body_bytes != encoded or policy.id != row["policy_hash"]
                    or sha256(encoded).hexdigest() != row["policy_hash"]):
                raise ValueError("Persisted policy digest mismatch")
            return policy
        except (TypeError, ValueError, KeyError) as exc:
            raise CorruptBudget("Persisted budget policy failed integrity validation") from exc

    @staticmethod
    def _validate_session_row(row, policy):
        try:
            started_at = _count("started_at", row["started_at"])
            deadline = _positive("deadline", row["deadline"])
            last_observed = _count("last_observed", row["last_observed"])
            if (policy.max_wall_seconds > MAX_INTEGER - started_at
                    or deadline != started_at + policy.max_wall_seconds
                    or last_observed < started_at):
                raise ValueError("Persisted budget timestamps are inconsistent")
            for name in _DIMENSIONS:
                consumed = _count(name, row[name])
                if (consumed > getattr(policy, "max_" + name)
                        and row["blocked_reason"] != "reservation_overrun"):
                    raise ValueError("Persisted counter exceeds its policy")
            active = _count("active", row["active"])
            if active > policy.max_concurrency:
                raise ValueError("Persisted active count exceeds its policy")
            reservation_rows = _count("reservation_rows", row["reservation_rows"])
            if reservation_rows > BudgetBook._max_reservations(policy):
                raise ValueError("Persisted reservation row count exceeds its policy")
            if type(row["accounting_overflow"]) is not int or row["accounting_overflow"] not in (0, 1):
                raise ValueError("Invalid accounting overflow marker")
            audit_sequence = _positive("audit_sequence", row["audit_sequence"])
            if (type(row["audit_head"]) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", row["audit_head"]) is None):
                raise ValueError("Invalid persisted audit head")
            api_consumed = _count("api_microunits", row["api_microunits"])
            if policy.provider_mode == "subscription":
                if api_consumed != 0:
                    raise ValueError("Subscription budget has a currency counter")
            elif (api_consumed > policy.max_api_microunits
                  and row["blocked_reason"] != "reservation_overrun"):
                raise ValueError("Persisted currency counter exceeds its policy")
            if row["blocked_reason"] not in (None, "reservation_overrun"):
                raise ValueError("Unknown persisted budget block")
        except (TypeError, ValueError, KeyError) as exc:
            raise CorruptBudget("Persisted budget counters failed integrity validation") from exc

    @staticmethod
    def _validate_reservation(row, policy, session):
        try:
            uuid_string(row["request_id"])
            if row["session_id"] != session["id"]:
                raise ValueError("Reservation belongs to another session")
            state = row["state"]
            if type(state) is not str or state not in _RESERVATION_STATES:
                raise ValueError("Unknown reservation state")
            created = _count("created_at", row["created_at"])
            if created < session["started_at"] or created > session["last_observed"]:
                raise ValueError("Reservation creation time is inconsistent")
            requested = {name: _count(name, row[name]) for name in _DIMENSIONS}
            if not any(requested.values()):
                raise ValueError("Empty persisted reservation")
            if any(requested[name] > getattr(policy, "max_" + name)
                   for name in _DIMENSIONS):
                raise ValueError("Persisted reservation exceeds its policy")
            if policy.provider_mode == "api":
                api = _count("api_microunits", row["api_microunits"])
                if requested["model_calls"] and api == 0:
                    raise ValueError("API model call lacks a currency reservation")
            else:
                if row["api_microunits"] is not None:
                    raise ValueError("Subscription reservation has API currency")
                api = None
            payload = {"session_id": session["id"], **requested,
                       "api_microunits": api}
            expected_hash = sha256(canonical_json(payload)).hexdigest()
            if row["request_hash"] != expected_hash:
                raise ValueError("Reservation input digest mismatch")

            dispatched = row["dispatched_at"]
            settled = row["settled_at"]
            finality = row["usage_finality"]
            actual_values = [row["actual_" + name] for name in _DIMENSIONS]
            actual_api = row["actual_api_microunits"]
            if dispatched is not None:
                dispatched = _count("dispatched_at", dispatched)
                if not created <= dispatched <= session["last_observed"]:
                    raise ValueError("Dispatch time is inconsistent")
            if settled is not None:
                settled = _count("settled_at", settled)
                if not created <= settled <= session["last_observed"]:
                    raise ValueError("Settlement time is inconsistent")
            if created >= session["deadline"]:
                raise ValueError("Reservation was created after its deadline")
            if dispatched is not None and dispatched >= session["deadline"]:
                raise ValueError("Reservation was dispatched after its deadline")
            if dispatched is not None and settled is not None and settled < dispatched:
                raise ValueError("Settlement precedes dispatch")

            if state == "reserved":
                valid = dispatched is None and settled is None and finality is None
            elif state == "dispatched":
                valid = dispatched is not None and settled is None and finality is None
            elif state == "unknown":
                valid = dispatched is not None and settled is not None and finality == "unknown"
            elif state == "cancelled":
                valid = dispatched is None and settled is not None and finality == "not_dispatched"
            else:
                valid = dispatched is not None and settled is not None and finality == "known"
            if not valid:
                raise ValueError("Reservation lifecycle fields are inconsistent")

            if state in ("finalized", "overage"):
                actual = {name: _count("actual_" + name, row["actual_" + name])
                          for name in _DIMENSIONS}
                if policy.provider_mode == "api":
                    actual_api = _count("actual_api_microunits", actual_api)
                elif actual_api is not None:
                    raise ValueError("Subscription actual usage has API currency")
                exceeded = (any(actual[name] > requested[name] for name in _DIMENSIONS)
                            or (policy.provider_mode == "api" and actual_api > api))
                if exceeded != (state == "overage"):
                    raise ValueError("Reservation overage state is inconsistent")
            elif any(value is not None for value in actual_values) or actual_api is not None:
                raise ValueError("Nonfinal reservation contains actual usage")
            return requested
        except (TypeError, ValueError, KeyError) as exc:
            raise CorruptBudget("Persisted reservation failed integrity validation") from exc

    def _validate_accounting(self, db, session, policy):
        totals = {name: 0 for name in _DIMENSIONS}
        api_total = 0
        active = 0
        saw_overage = False
        for item in db.execute("SELECT * FROM runtime_budget_reservations WHERE session_id=?",
                               (session["id"],)):
            requested = self._validate_reservation(item, policy, session)
            if item["state"] in ("reserved", "dispatched", "unknown"):
                charged = requested
                charged_api = item["api_microunits"] or 0
                active += 1
            elif item["state"] in ("finalized", "overage"):
                charged = {name: item["actual_" + name] for name in _DIMENSIONS}
                charged_api = item["actual_api_microunits"] or 0
                saw_overage = saw_overage or item["state"] == "overage"
            else:
                charged = {name: 0 for name in _DIMENSIONS}
                charged_api = 0
            for name in _DIMENSIONS:
                totals[name] += charged[name]
            api_total += charged_api
        overflow = any(value > MAX_INTEGER for value in (*totals.values(), api_total))
        if (active != session["active"]
                or any(min(MAX_INTEGER, totals[name]) != session[name] for name in _DIMENSIONS)
                or min(MAX_INTEGER, api_total) != session["api_microunits"]
                or overflow != bool(session["accounting_overflow"])
                or saw_overage != (session["blocked_reason"] == "reservation_overrun")):
            raise CorruptBudget("Persisted session counters do not match reservations")
        self._validate_audit(db, session, policy)
        return totals, api_total

    def _session(self, db, session_id, *, require_open):
        row = db.execute("SELECT * FROM runtime_budget_sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise SessionConflict("Unknown budget session")
        policy = self._policy(row)
        self._validate_session_row(row, policy)
        self._validate_accounting(db, row, policy)
        now = self._now()
        if now < row["last_observed"]:
            raise ClockError("Clock moved backward across a persisted budget")
        if now != row["last_observed"]:
            db.execute("UPDATE runtime_budget_sessions SET last_observed=? WHERE id=?", (now, session_id))
            row = db.execute("SELECT * FROM runtime_budget_sessions WHERE id=?", (session_id,)).fetchone()
        if require_open and now >= row["deadline"]:
            raise BudgetExceeded("Session wall-time budget expired")
        return row, policy, now

    def _persist_clock_watermark_in_transaction(self, db, session_id, observed):
        """Persist a known session-clock floor without reserving or settling usage."""
        uuid_string(session_id)
        observed = _count("observed budget clock", observed)
        if (type(db) is not sqlite3.Connection or not db.in_transaction
                or db.row_factory is not sqlite3.Row):
            raise CorruptBudget("Budget clock recovery requires an exact transaction")
        self._assert_transaction_schema(db)
        row = db.execute(
            "SELECT * FROM runtime_budget_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if row is None:
            raise SessionConflict("Unknown budget session")
        policy = self._policy(row)
        self._validate_session_row(row, policy)
        self._validate_accounting(db, row, policy)
        previous = row["last_observed"]
        if observed > previous:
            changed = db.execute(
                "UPDATE runtime_budget_sessions SET last_observed=? "
                "WHERE id=? AND last_observed=?",
                (observed, session_id, previous),
            ).rowcount
            if changed != 1:
                raise CorruptBudget("Budget clock floor changed concurrently")
        return None

    def start(self, session_id, policy):
        uuid_string(session_id)
        if type(policy) is not BudgetPolicy:
            raise TypeError("Exact BudgetPolicy required")
        rebuilt = BudgetPolicy.create(profile=policy.profile,
            provider_mode=policy.provider_mode, max_model_calls=policy.max_model_calls,
            max_tool_calls=policy.max_tool_calls, max_node_visits=policy.max_node_visits,
            max_loop_rounds=policy.max_loop_rounds, max_output_bytes=policy.max_output_bytes,
            max_concurrency=policy.max_concurrency, max_wall_seconds=policy.max_wall_seconds,
            max_candidates=policy.max_candidates, currency=policy.currency,
            max_api_microunits=policy.max_api_microunits)
        if rebuilt != policy:
            raise ValueError("BudgetPolicy content or digest was forged")
        now = self._now()
        if policy.max_wall_seconds > MAX_INTEGER - now:
            raise ValueError("Session deadline exceeds bounded integer")
        with self._connection(immediate=True) as db:
            current = db.execute("SELECT policy_hash FROM runtime_budget_sessions WHERE id=?",
                                 (session_id,)).fetchone()
            if current is not None:
                if current[0] != policy.id:
                    raise SessionConflict("Budget session ID already has another policy")
            else:
                db.execute("INSERT INTO runtime_budget_sessions"
                           "(id,policy,policy_hash,started_at,deadline,last_observed,api_microunits) "
                           "VALUES (?,?,?,?,?,?,0)",
                           (session_id, policy.body_bytes, policy.id, now,
                            now + policy.max_wall_seconds, now))
                self._append_audit(db, session_id, None, "session_started", now,
                    canonical_json({"policy_hash": policy.id, "started_at": now,
                                    "deadline": now + policy.max_wall_seconds}))
        return self.status(session_id)

    @staticmethod
    def _reservation(row):
        return Reservation(row["request_id"], row["session_id"], row["state"],
            row["request_hash"], *(row[name] for name in _DIMENSIONS), row["api_microunits"])

    def _reserve_in_transaction(self, db, session_id, request_id, *, model_calls,
                                tool_calls, node_visits, loop_rounds, output_bytes,
                                api_microunits, candidates=0):
        uuid_string(session_id); uuid_string(request_id)
        requested = {name: _count(name, value) for name, value in {
            "model_calls": model_calls, "tool_calls": tool_calls,
            "node_visits": node_visits, "loop_rounds": loop_rounds,
            "output_bytes": output_bytes, "candidates": candidates}.items()}
        if not any(requested.values()):
            raise ValueError("Reservation must consume at least one finite dimension")
        session, policy, now = self._session(db, session_id, require_open=False)
        if policy.provider_mode == "api":
            if model_calls and (type(api_microunits) is not int or api_microunits <= 0):
                raise BudgetExceeded("API model calls require a conservative currency reservation")
            if api_microunits is None:
                api_microunits = 0
            _count("api_microunits", api_microunits)
        elif api_microunits is not None:
            raise ValueError("Subscription mode has no enforceable currency counter")
        payload = {"session_id": session_id, **requested,
                   "api_microunits": api_microunits}
        request_hash = sha256(canonical_json(payload)).hexdigest()
        existing = db.execute("SELECT * FROM runtime_budget_reservations WHERE request_id=?",
                              (request_id,)).fetchone()
        if existing is not None:
            if existing["session_id"] != session_id or existing["request_hash"] != request_hash:
                raise RequestConflict("Request ID was reused with different budget input")
            return existing, session, policy, now
        if session["blocked_reason"] is not None:
            raise BudgetExceeded("Budget session is blocked after an accounting overrun")
        if now >= session["deadline"]:
            raise BudgetExceeded("Session wall-time budget expired")
        if session["reservation_rows"] >= self._max_reservations(policy):
            raise BudgetExceeded("Finite reservation ledger row cap reached")
        maxima = {name: getattr(policy, "max_" + name) for name in _DIMENSIONS}
        if any(session[name] + requested[name] > maxima[name] for name in _DIMENSIONS):
            raise BudgetExceeded("A finite budget dimension would be exceeded")
        if session["active"] >= policy.max_concurrency:
            raise BudgetExceeded("Concurrent reservation cap reached")
        if (policy.provider_mode == "api"
                and session["api_microunits"] + api_microunits > policy.max_api_microunits):
            raise BudgetExceeded("API currency cap would be exceeded")
        columns = ",".join(_DIMENSIONS)
        marks = ",".join("?" for _ in _DIMENSIONS)
        db.execute(f"INSERT INTO runtime_budget_reservations"
            f"(request_id,session_id,request_hash,state,created_at,{columns},api_microunits) "
            f"VALUES (?,?,?,'reserved',?,{marks},?)",
            (request_id, session_id, request_hash, now,
             *(requested[name] for name in _DIMENSIONS), api_microunits))
        db.execute("UPDATE runtime_budget_sessions SET reservation_rows=reservation_rows+1 "
                   "WHERE id=?", (session_id,))
        self._synchronize_accounting(db, session_id)
        self._append_reservation_audit(db, request_id, now)
        row = db.execute("SELECT * FROM runtime_budget_reservations WHERE request_id=?",
                         (request_id,)).fetchone()
        return row, session, policy, now

    def reserve(self, session_id, request_id, *, model_calls, tool_calls, node_visits,
                loop_rounds, output_bytes, api_microunits, candidates=0):
        with self._connection(immediate=True) as db:
            row, _, _, _ = self._reserve_in_transaction(
                db, session_id, request_id, model_calls=model_calls,
                tool_calls=tool_calls, node_visits=node_visits,
                loop_rounds=loop_rounds, output_bytes=output_bytes,
                candidates=candidates, api_microunits=api_microunits,
            )
            return self._reservation(row)

    def _reserve_and_mark_dispatched_in_transaction(self, db, request):
        """Reserve and dispatch on a caller-owned transaction over this exact DB.

        This is intentionally internal: only the runtime ledger may turn the
        resulting transition into a process-local send permit after commit.
        """
        if type(request) is not BudgetDispatchRequest:
            raise TypeError("Exact BudgetDispatchRequest required")
        self._assert_transaction_schema(db)
        rebuilt = BudgetDispatchRequest.create(
            session_id=request.session_id,
            request_id=request.request_id,
            policy_ref=request.policy_ref,
            model_calls=request.model_calls,
            tool_calls=request.tool_calls,
            node_visits=request.node_visits,
            loop_rounds=request.loop_rounds,
            output_bytes=request.output_bytes,
            candidates=request.candidates,
            api_microunits=request.api_microunits,
        )
        if rebuilt != request:
            raise ValueError("Budget dispatch request was forged")
        row, session, policy, now = self._reserve_in_transaction(
            db,
            request.session_id,
            request.request_id,
            model_calls=request.model_calls,
            tool_calls=request.tool_calls,
            node_visits=request.node_visits,
            loop_rounds=request.loop_rounds,
            output_bytes=request.output_bytes,
            candidates=request.candidates,
            api_microunits=request.api_microunits,
        )
        if row["state"] != "reserved":
            raise ReservationConflict(
                "Only one attempt can consume a reserved budget request"
            )
        if session["blocked_reason"] is not None:
            raise BudgetExceeded("Budget session is blocked after an accounting overrun")
        if now >= session["deadline"]:
            raise BudgetExceeded("Session wall-time budget expired before dispatch")
        changed = db.execute(
            "UPDATE runtime_budget_reservations SET state='dispatched',dispatched_at=? "
            "WHERE request_id=? AND session_id=? AND state='reserved' "
            "AND dispatched_at IS NULL AND settled_at IS NULL",
            (now, request.request_id, request.session_id),
        ).rowcount
        if changed != 1:
            raise ReservationConflict("Budget dispatch reservation lost its state CAS")
        self._append_reservation_audit(db, request.request_id, now)
        updated = db.execute(
            "SELECT * FROM runtime_budget_reservations WHERE request_id=?",
            (request.request_id,),
        ).fetchone()
        return self._reservation(updated), policy, session["deadline"]

    @classmethod
    def _assert_transaction_schema(cls, db):
        """Fail closed if the shared transaction does not see the exact schema."""
        stored_objects = {row["name"]: _normalize_schema_sql(row["sql"])
                          for row in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE name IN (?,?,?,?,?)",
            tuple(sorted(_BUDGET_SCHEMA_OBJECTS)))}
        rows = list(db.execute(
            "SELECT version,sha256 FROM runtime_migrations WHERE component='budgets' "
            "ORDER BY version"))
        if ([(row["version"], row["sha256"]) for row in rows]
                != [(1, RUNTIME_MIGRATION_SHA256)]
                or stored_objects != _EXPECTED_SCHEMA_SQL):
            raise CorruptBudget("Runtime budget transaction schema is inconsistent")
        owned_tables = ("runtime_migrations", "runtime_budget_sessions",
                        "runtime_budget_reservations", "runtime_budget_audit")
        if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='trigger' LIMIT 1"
        ).fetchone() is not None:
            raise CorruptBudget("Unexpected shared-database trigger")
        for row in db.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE type='index' AND lower(tbl_name) IN (?,?,?,?)",
                owned_tables):
            automatic = (row["type"] == "index" and row["sql"] is None
                         and row["name"].casefold().startswith("sqlite_autoindex_"))
            expected = row["name"].casefold() in _BUDGET_SCHEMA_OBJECTS
            if not automatic and not expected:
                raise CorruptBudget("Unexpected runtime budget schema object")

    def _assert_dispatched_in_transaction(self, db, request_id, session_id):
        """Revalidate a dispatched reservation immediately before permit use."""
        self._assert_transaction_schema(db)
        row, session, policy, now = self._request(db, request_id)
        if row["session_id"] != session_id:
            raise ReservationConflict("Budget reservation belongs to another session")
        if row["state"] != "dispatched":
            raise ReservationConflict("Budget reservation is not dispatchable")
        if session["blocked_reason"] is not None:
            raise BudgetExceeded("Budget session is blocked after an accounting overrun")
        if now >= session["deadline"]:
            raise BudgetExceeded("Session wall-time budget expired before dispatch")
        return self._reservation(row), policy, session["deadline"], now

    def _request(self, db, request_id):
        uuid_string(request_id)
        row = db.execute("SELECT * FROM runtime_budget_reservations WHERE request_id=?",
                         (request_id,)).fetchone()
        if row is None:
            raise ReservationConflict("Unknown reservation")
        session, policy, now = self._session(db, row["session_id"], require_open=False)
        return row, session, policy, now

    def mark_dispatched(self, request_id):
        with self._connection(immediate=True) as db:
            row, session, _, now = self._request(db, request_id)
            if row["state"] == "reserved":
                if session["blocked_reason"] is not None:
                    raise BudgetExceeded("Budget session is blocked after an accounting overrun")
                if now >= session["deadline"]:
                    raise BudgetExceeded("Session wall-time budget expired before dispatch")
                db.execute("UPDATE runtime_budget_reservations SET state='dispatched',dispatched_at=? "
                           "WHERE request_id=?", (now, request_id))
                self._append_reservation_audit(db, request_id, now)
            elif row["state"] != "dispatched":
                raise ReservationConflict("Only a reserved request can dispatch")

    def cancel_before_dispatch(self, request_id):
        with self._connection(immediate=True) as db:
            row, _, _, now = self._request(db, request_id)
            if row["state"] == "cancelled":
                return
            if row["state"] != "reserved":
                raise ReservationConflict("A dispatched reservation cannot be released as unsent")
            db.execute("UPDATE runtime_budget_reservations SET state='cancelled',"
                       "usage_finality='not_dispatched',settled_at=? WHERE request_id=?",
                       (now, request_id))
            self._synchronize_accounting(db, row["session_id"])
            self._append_reservation_audit(db, request_id, now)

    @staticmethod
    def _actual(policy, values):
        actual = {name: _count(name, values[name]) for name in _DIMENSIONS}
        api = values["api_microunits"]
        if policy.provider_mode == "api":
            api = _count("api_microunits", api)
        elif api is not None:
            raise ValueError("Subscription usage cannot claim exact API currency")
        return actual, api

    def _finalize(self, db, row, session, policy, now, values):
        actual, api = self._actual(policy, values)
        overrun = (any(actual[name] > row[name] for name in _DIMENSIONS)
                   or (policy.provider_mode == "api" and api > row["api_microunits"]))
        actual_columns = ",".join(f"actual_{name}=?" for name in _DIMENSIONS)
        state = "overage" if overrun else "finalized"
        db.execute(f"UPDATE runtime_budget_reservations SET state=?,"
                   f"usage_finality='known',settled_at=?,{actual_columns},actual_api_microunits=? "
                   "WHERE request_id=?",
                   (state, now, *(actual[name] for name in _DIMENSIONS), api, row["request_id"]))
        self._synchronize_accounting(db, row["session_id"])
        self._append_reservation_audit(db, row["request_id"], now)

    def settle(self, request_id, *, usage_finality, model_calls=None, tool_calls=None,
               node_visits=None, loop_rounds=None, output_bytes=None,
               api_microunits=None, candidates=None):
        if usage_finality not in ("known", "unknown"):
            raise ValueError("Usage finality must be known or unknown")
        with self._connection(immediate=True) as db:
            row, session, policy, now = self._request(db, request_id)
            if row["state"] != "dispatched":
                raise ReservationConflict("Only a dispatched request can settle")
            if usage_finality == "unknown":
                if any(value is not None for value in
                       (model_calls, tool_calls, node_visits, loop_rounds, output_bytes,
                        api_microunits, candidates)):
                    raise ValueError("Unknown usage retains the full reservation")
                db.execute("UPDATE runtime_budget_reservations SET state='unknown',"
                           "usage_finality='unknown',settled_at=? WHERE request_id=?",
                           (now, request_id))
                self._append_reservation_audit(db, request_id, now)
                return
            values = dict(model_calls=model_calls, tool_calls=tool_calls,
                          node_visits=node_visits, loop_rounds=loop_rounds,
                          output_bytes=output_bytes,
                          candidates=candidates,
                          api_microunits=api_microunits)
            self._finalize(db, row, session, policy, now, values)

    def reconcile_unknown(self, request_id, *, model_calls, tool_calls, node_visits,
                          loop_rounds, output_bytes, candidates, api_microunits):
        with self._connection(immediate=True) as db:
            row, session, policy, now = self._request(db, request_id)
            if row["state"] != "unknown":
                raise ReservationConflict("Only unknown usage can be reconciled")
            self._finalize(db, row, session, policy, now, dict(
                model_calls=model_calls, tool_calls=tool_calls, node_visits=node_visits,
                loop_rounds=loop_rounds, output_bytes=output_bytes,
                candidates=candidates, api_microunits=api_microunits))

    def status(self, session_id):
        uuid_string(session_id)
        with self._connection(immediate=True) as db:
            row, policy, now = self._session(db, session_id, require_open=False)
            exact_totals, exact_api = self._validate_accounting(db, row, policy)
            remaining = {name: max(0, getattr(policy, "max_" + name) - row[name])
                         for name in _DIMENSIONS}
            remaining["api_microunits"] = (None if policy.provider_mode == "subscription"
                else max(0, policy.max_api_microunits - row["api_microunits"]))
            overrun = {name: min(MAX_INTEGER, max(
                0, exact_totals[name] - getattr(policy, "max_" + name)))
                       for name in _DIMENSIONS}
            overrun["api_microunits"] = (None if policy.provider_mode == "subscription"
                else min(MAX_INTEGER, max(0, exact_api - policy.max_api_microunits)))
            overflow_dimensions = [name for name in _DIMENSIONS
                                   if exact_totals[name] > MAX_INTEGER]
            if exact_api > MAX_INTEGER:
                overflow_dimensions.append("api_microunits")
            counts = {item[0]: item[1] for item in db.execute(
                "SELECT state,count(*) FROM runtime_budget_reservations "
                "WHERE session_id=? GROUP BY state", (session_id,))}
            total_rows = sum(counts.values())
            unknown = counts.get("unknown", 0)
            finalized = counts.get("finalized", 0)
            pending = counts.get("reserved", 0) + counts.get("dispatched", 0)
            exceeded = counts.get("overage", 0)
            return {"session_id": session_id, "policy_id": policy.id,
                    "started_at": row["started_at"], "deadline": row["deadline"],
                    "expired": now >= row["deadline"], "remaining": remaining,
                    "overrun": overrun, "blocked_reason": row["blocked_reason"],
                    "accounting_overflow": bool(row["accounting_overflow"]),
                    "overflow_dimensions": overflow_dimensions,
                    "overflow_exact_totals": {
                        name: str(exact_api if name == "api_microunits" else exact_totals[name])
                        for name in overflow_dimensions},
                    "reservation_slots_remaining": max(
                        0, self._max_reservations(policy) - row["reservation_rows"]),
                    "active_reservations": row["active"],
                    "reservation_count": sum(value for key, value in counts.items()
                                             if key != "cancelled"),
                    "usage_finality": "unknown" if unknown else
                        ("pending" if pending else
                         ("known_overrun" if exceeded else
                          ("known" if finalized or counts.get("cancelled", 0) else "pending")))}
