"""Frozen runtime schema versions. Verification never mutates the database."""
import re
import sqlite3
from hashlib import sha256


def _normalize_schema_sql(value):
    if type(value) is not str:
        return ""
    return re.sub(r"\s*([(),=<>])\s*", r"\1", " ".join(value.split()).casefold())


def _compiled_schema(statements):
    db = sqlite3.connect(":memory:")
    try:
        for statement in statements:
            db.execute(statement)
        return {name: (kind, _normalize_schema_sql(sql)) for kind, name, sql in
                db.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL "
                           "AND name GLOB 'runtime_*'")}
    finally:
        db.close()


def _schema_version(db):
    """Return 0 only for an empty ledger, or an exact supported version."""
    from .ledger import CorruptLedger
    expected = {1: _V1_SHAPE, 2: _V2_SHAPE}
    known = set(_V2_SHAPE)
    # Budget tables share the prefix, but have their own registered schema.
    from .budgets import _DDL as budget_ddl
    budget_names = {re.match(r"CREATE (?:UNIQUE )?(?:TABLE|INDEX) ([a-z_]+)", sql)[1]
                    for sql in budget_ddl}
    rows = list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
                           "WHERE lower(name) GLOB 'runtime_*' OR type='trigger' "
                           "OR (sql IS NOT NULL AND lower(tbl_name) GLOB 'runtime_*')"))
    actual = {}
    for kind, name, table, sql in rows:
        if kind == "trigger":
            raise CorruptLedger("Unexpected shared-database trigger")
        if name not in known and name not in budget_names:
            raise CorruptLedger("Unexpected runtime ledger schema object")
        if name in known:
            actual[name] = (kind, _normalize_schema_sql(sql))
    if not actual:
        return 0
    registry = {"runtime_migrations": _V1_SHAPE["runtime_migrations"]}
    if actual.get("runtime_migrations") != registry["runtime_migrations"]:
        raise CorruptLedger("Shared runtime migration ledger lacks the exact version constraint")
    chain = [tuple(row) for row in db.execute("SELECT version,sha256 FROM runtime_migrations "
                                             "WHERE component='ledger' ORDER BY version")]
    if actual == registry and not chain:
        return 0
    version = {((1, LEDGER_V1_SHA256),): 1,
               ((1, LEDGER_V1_SHA256), (2, LEDGER_V2_SHA256)): 2}.get(tuple(chain))
    if version is None:
        raise CorruptLedger("Unknown or corrupt runtime ledger migration")
    if actual != expected[version]:
        raise CorruptLedger("Partial or inconsistent runtime ledger schema")
    return version


def _representation_version(db):
    """Select exact current relational representation, never dispatch authority.

    Descriptive reads and historical transaction-fault paths do not perform the
    separate all-object/trigger authority check. Startup and real dispatch do.
    """
    from .ledger import CorruptLedger
    if (type(db) is not sqlite3.Connection or not db.in_transaction
            or db.row_factory is not sqlite3.Row):
        raise CorruptLedger("Representation requires an active transaction")
    names = ("runtime_migrations", "runtime_attempts", "runtime_dispatch_subjects")
    actual = {name: (kind, _normalize_schema_sql(sql)) for kind, name, sql in db.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE lower(name) IN (?,?,?)", names)}
    if actual.get("runtime_migrations") != _V1_SHAPE["runtime_migrations"]:
        raise CorruptLedger("Runtime representation migration schema changed")
    chain = tuple(tuple(row) for row in db.execute("SELECT version,sha256 FROM runtime_migrations "
                                                  "WHERE component='ledger' ORDER BY version LIMIT 3"))
    version = {((1, LEDGER_V1_SHA256),): 1,
               ((1, LEDGER_V1_SHA256), (2, LEDGER_V2_SHA256)): 2}.get(chain)
    if version is None:
        raise CorruptLedger("Runtime representation migration changed")
    shape = _V1_SHAPE if version == 1 else _V2_SHAPE
    expected = {name: shape[name] for name in names if name in shape}
    if actual != expected:
        raise CorruptLedger("Runtime attempt or subject representation changed")
    return version

LEDGER_V1_DDL = (
    "CREATE TABLE runtime_migrations (component TEXT NOT NULL, version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version>0), sha256 TEXT NOT NULL, PRIMARY KEY(component,version))",
    "CREATE TABLE runtime_control (singleton INTEGER PRIMARY KEY CHECK(singleton=1), vault_id TEXT NOT NULL UNIQUE REFERENCES domain_vault(vault_id), last_clock_ms INTEGER NOT NULL CHECK(typeof(last_clock_ms)='integer' AND last_clock_ms>=0), active_session_id TEXT, reconciliation_generation INTEGER NOT NULL DEFAULT 0 CHECK(typeof(reconciliation_generation)='integer' AND reconciliation_generation>=0))",
    'CREATE TABLE runtime_commands (vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id), command_id TEXT NOT NULL, kind TEXT NOT NULL, payload BLOB NOT NULL, payload_digest TEXT NOT NULL, result BLOB NOT NULL, result_digest TEXT NOT NULL, created_at_ms INTEGER NOT NULL, PRIMARY KEY(vault_id,command_id))',
    "CREATE TABLE runtime_runs (vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id), id TEXT NOT NULL, spec BLOB NOT NULL, spec_digest TEXT NOT NULL, phase TEXT NOT NULL, revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>0), created_at_ms INTEGER NOT NULL, PRIMARY KEY(vault_id,id))",
    'CREATE TABLE runtime_run_refs (vault_id TEXT NOT NULL, run_id TEXT NOT NULL, role TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(vault_id,run_id,role), FOREIGN KEY(vault_id,run_id) REFERENCES runtime_runs(vault_id,id), FOREIGN KEY(vault_id,kind,id,version,sha256) REFERENCES domain_records(vault_id,kind,id,version,sha256))',
    "CREATE TABLE runtime_node_executions (vault_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL, node_id TEXT NOT NULL, visit_id TEXT NOT NULL, spec BLOB NOT NULL, spec_digest TEXT NOT NULL, phase TEXT NOT NULL, revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>0), created_at_ms INTEGER NOT NULL, PRIMARY KEY(vault_id,id), UNIQUE(vault_id,run_id,node_id,visit_id), FOREIGN KEY(vault_id,run_id) REFERENCES runtime_runs(vault_id,id))",
    'CREATE TABLE runtime_execution_parents (vault_id TEXT NOT NULL, execution_id TEXT NOT NULL, position INTEGER NOT NULL, parent_execution_id TEXT NOT NULL, PRIMARY KEY(vault_id,execution_id,position), UNIQUE(vault_id,execution_id,parent_execution_id), FOREIGN KEY(vault_id,execution_id) REFERENCES runtime_node_executions(vault_id,id), FOREIGN KEY(vault_id,parent_execution_id) REFERENCES runtime_node_executions(vault_id,id))',
    "CREATE TABLE runtime_attempts (vault_id TEXT NOT NULL, id TEXT NOT NULL, execution_id TEXT NOT NULL, attempt_no INTEGER NOT NULL, idempotency_key TEXT NOT NULL, reservation_id TEXT NOT NULL, spec BLOB NOT NULL, spec_digest TEXT NOT NULL, phase TEXT NOT NULL, dispatch_gate TEXT NOT NULL, send_finality TEXT NOT NULL, cancel_state TEXT NOT NULL, recovery_state TEXT NOT NULL, terminal_outcome TEXT, revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>0), lease_owner BLOB NOT NULL, lease_owner_digest TEXT NOT NULL, lease_fence INTEGER NOT NULL, lease_expires_at_ms INTEGER NOT NULL, dispatch_blocked_at_ms INTEGER, send_intent_at_ms INTEGER, local_transport_closed_at_ms INTEGER, owned_process_exit INTEGER, remote_terminal_observed TEXT NOT NULL, usage_finality TEXT NOT NULL, accepted_observation_id TEXT, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL, PRIMARY KEY(vault_id,id), UNIQUE(vault_id,execution_id,attempt_no), UNIQUE(vault_id,idempotency_key), FOREIGN KEY(vault_id,execution_id) REFERENCES runtime_node_executions(vault_id,id))",
    'CREATE TABLE runtime_attempt_refs (vault_id TEXT NOT NULL, attempt_id TEXT NOT NULL, role TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(vault_id,attempt_id,role), FOREIGN KEY(vault_id,attempt_id) REFERENCES runtime_attempts(vault_id,id), FOREIGN KEY(vault_id,kind,id,version,sha256) REFERENCES domain_records(vault_id,kind,id,version,sha256))',
    'CREATE TABLE runtime_result_observations (sequence INTEGER PRIMARY KEY AUTOINCREMENT, vault_id TEXT NOT NULL, id TEXT NOT NULL, attempt_id TEXT NOT NULL, payload BLOB NOT NULL, payload_digest TEXT NOT NULL, semantic_digest TEXT NOT NULL, classification TEXT NOT NULL, observed_at_ms INTEGER NOT NULL, UNIQUE(vault_id,id), FOREIGN KEY(vault_id,attempt_id) REFERENCES runtime_attempts(vault_id,id))',
    'CREATE TABLE runtime_result_refs (vault_id TEXT NOT NULL, observation_id TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(vault_id,observation_id), FOREIGN KEY(vault_id,observation_id) REFERENCES runtime_result_observations(vault_id,id), FOREIGN KEY(vault_id,kind,id,version,sha256) REFERENCES domain_records(vault_id,kind,id,version,sha256))',
    'CREATE TABLE runtime_tool_calls (vault_id TEXT NOT NULL, id TEXT NOT NULL, attempt_id TEXT NOT NULL, tool_id TEXT NOT NULL, version TEXT NOT NULL, effect_class TEXT NOT NULL, inputs BLOB NOT NULL, inputs_digest TEXT NOT NULL, state TEXT NOT NULL, result_kind TEXT, result_id TEXT, result_version INTEGER, result_sha256 TEXT, command_id TEXT NOT NULL, created_at_ms INTEGER NOT NULL, settled_at_ms INTEGER, approval_kind TEXT, approval_id TEXT, approval_version INTEGER, approval_sha256 TEXT, PRIMARY KEY(vault_id,id), UNIQUE(vault_id,attempt_id), UNIQUE(vault_id,command_id), FOREIGN KEY(vault_id,attempt_id) REFERENCES runtime_attempts(vault_id,id))',
    'CREATE TABLE runtime_checkpoints (vault_id TEXT NOT NULL, run_id TEXT NOT NULL, namespace TEXT NOT NULL, revision INTEGER NOT NULL, cursor BLOB NOT NULL, cursor_sha256 TEXT NOT NULL, bound_attempt_id TEXT, bound_attempt_revision INTEGER, bound_execution_id TEXT, bound_envelope_sha256 TEXT, created_at_ms INTEGER NOT NULL, command_id TEXT NOT NULL, PRIMARY KEY(vault_id,run_id,namespace,revision), UNIQUE(vault_id,command_id), FOREIGN KEY(vault_id,run_id) REFERENCES runtime_runs(vault_id,id))',
    'CREATE TABLE runtime_attempt_journal (sequence INTEGER PRIMARY KEY AUTOINCREMENT, vault_id TEXT NOT NULL, attempt_id TEXT NOT NULL, transition TEXT NOT NULL, payload BLOB NOT NULL, payload_digest TEXT NOT NULL, at_ms INTEGER NOT NULL, FOREIGN KEY(vault_id,attempt_id) REFERENCES runtime_attempts(vault_id,id))',
    'CREATE TABLE runtime_public_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, vault_id TEXT NOT NULL, event_type TEXT NOT NULL, object_kind TEXT NOT NULL, object_id TEXT NOT NULL, payload BLOB NOT NULL, payload_digest TEXT NOT NULL, at_ms INTEGER NOT NULL)',
    'CREATE INDEX runtime_attempts_execution ON runtime_attempts(vault_id,execution_id,attempt_no)',
    'CREATE INDEX runtime_results_attempt ON runtime_result_observations(vault_id,attempt_id,observed_at_ms,id)',
    'CREATE INDEX runtime_checkpoints_latest ON runtime_checkpoints(vault_id,run_id,namespace,revision)',
)
LEDGER_V1_SHA256 = 'b761957cfb9c21a63f928ba5c7d173ba7a4804d0dc72b240fdade0bc860ad118'

LEDGER_V2_DDL = (
    "CREATE TABLE runtime_migrations (component TEXT NOT NULL, version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version>0), sha256 TEXT NOT NULL, PRIMARY KEY(component,version))",
    "CREATE TABLE runtime_control (singleton INTEGER PRIMARY KEY CHECK(singleton=1), vault_id TEXT NOT NULL UNIQUE REFERENCES domain_vault(vault_id), last_clock_ms INTEGER NOT NULL CHECK(typeof(last_clock_ms)='integer' AND last_clock_ms>=0), active_session_id TEXT, reconciliation_generation INTEGER NOT NULL DEFAULT 0 CHECK(typeof(reconciliation_generation)='integer' AND reconciliation_generation>=0))",
    'CREATE TABLE runtime_commands (vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id), command_id TEXT NOT NULL, kind TEXT NOT NULL, payload BLOB NOT NULL, payload_digest TEXT NOT NULL, result BLOB NOT NULL, result_digest TEXT NOT NULL, created_at_ms INTEGER NOT NULL, PRIMARY KEY(vault_id,command_id))',
    "CREATE TABLE runtime_runs (vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id), id TEXT NOT NULL, spec BLOB NOT NULL, spec_digest TEXT NOT NULL, phase TEXT NOT NULL, revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>0), created_at_ms INTEGER NOT NULL, PRIMARY KEY(vault_id,id))",
    'CREATE TABLE runtime_run_refs (vault_id TEXT NOT NULL, run_id TEXT NOT NULL, role TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(vault_id,run_id,role), FOREIGN KEY(vault_id,run_id) REFERENCES runtime_runs(vault_id,id), FOREIGN KEY(vault_id,kind,id,version,sha256) REFERENCES domain_records(vault_id,kind,id,version,sha256))',
    "CREATE TABLE runtime_node_executions (vault_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL, node_id TEXT NOT NULL, visit_id TEXT NOT NULL, spec BLOB NOT NULL, spec_digest TEXT NOT NULL, phase TEXT NOT NULL, revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>0), created_at_ms INTEGER NOT NULL, PRIMARY KEY(vault_id,id), UNIQUE(vault_id,run_id,node_id,visit_id), FOREIGN KEY(vault_id,run_id) REFERENCES runtime_runs(vault_id,id))",
    'CREATE TABLE runtime_execution_parents (vault_id TEXT NOT NULL, execution_id TEXT NOT NULL, position INTEGER NOT NULL, parent_execution_id TEXT NOT NULL, PRIMARY KEY(vault_id,execution_id,position), UNIQUE(vault_id,execution_id,parent_execution_id), FOREIGN KEY(vault_id,execution_id) REFERENCES runtime_node_executions(vault_id,id), FOREIGN KEY(vault_id,parent_execution_id) REFERENCES runtime_node_executions(vault_id,id))',
    "CREATE TABLE runtime_dispatch_subjects (vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id), subject_kind TEXT NOT NULL, subject_id TEXT NOT NULL, node_execution_id TEXT, generation_kind TEXT, generation_version INTEGER, generation_sha256 TEXT, PRIMARY KEY(vault_id,subject_kind,subject_id), FOREIGN KEY(vault_id,node_execution_id) REFERENCES runtime_node_executions(vault_id,id), FOREIGN KEY(vault_id,generation_kind,subject_id,generation_version,generation_sha256) REFERENCES domain_records(vault_id,kind,id,version,sha256), CHECK((subject_kind='node_execution' AND node_execution_id IS NOT NULL AND node_execution_id=subject_id AND generation_kind IS NULL AND generation_version IS NULL AND generation_sha256 IS NULL) OR (subject_kind='generation_call' AND node_execution_id IS NULL AND generation_kind IS NOT NULL AND generation_kind='generation_call' AND generation_version IS NOT NULL AND typeof(generation_version)='integer' AND generation_version>0 AND generation_sha256 IS NOT NULL AND length(generation_sha256)=64 AND generation_sha256 NOT GLOB '*[^0-9a-f]*')))",
    "CREATE TABLE runtime_attempts (vault_id TEXT NOT NULL, id TEXT NOT NULL, execution_id TEXT, subject_kind TEXT NOT NULL, subject_id TEXT NOT NULL, attempt_no INTEGER NOT NULL, idempotency_key TEXT NOT NULL, reservation_id TEXT NOT NULL, spec BLOB NOT NULL, spec_digest TEXT NOT NULL, phase TEXT NOT NULL, dispatch_gate TEXT NOT NULL, send_finality TEXT NOT NULL, cancel_state TEXT NOT NULL, recovery_state TEXT NOT NULL, terminal_outcome TEXT, revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>0), lease_owner BLOB NOT NULL, lease_owner_digest TEXT NOT NULL, lease_fence INTEGER NOT NULL, lease_expires_at_ms INTEGER NOT NULL, dispatch_blocked_at_ms INTEGER, send_intent_at_ms INTEGER, local_transport_closed_at_ms INTEGER, owned_process_exit INTEGER, remote_terminal_observed TEXT NOT NULL, usage_finality TEXT NOT NULL, accepted_observation_id TEXT, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL, PRIMARY KEY(vault_id,id), UNIQUE(vault_id,execution_id,attempt_no), UNIQUE(vault_id,subject_kind,subject_id,attempt_no), UNIQUE(vault_id,idempotency_key), FOREIGN KEY(vault_id,execution_id) REFERENCES runtime_node_executions(vault_id,id), FOREIGN KEY(vault_id,subject_kind,subject_id) REFERENCES runtime_dispatch_subjects(vault_id,subject_kind,subject_id), CHECK((subject_kind='node_execution' AND execution_id IS NOT NULL AND execution_id=subject_id) OR (subject_kind='generation_call' AND execution_id IS NULL)))",
    'CREATE TABLE runtime_attempt_refs (vault_id TEXT NOT NULL, attempt_id TEXT NOT NULL, role TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(vault_id,attempt_id,role), FOREIGN KEY(vault_id,attempt_id) REFERENCES runtime_attempts(vault_id,id), FOREIGN KEY(vault_id,kind,id,version,sha256) REFERENCES domain_records(vault_id,kind,id,version,sha256))',
    'CREATE TABLE runtime_result_observations (sequence INTEGER PRIMARY KEY AUTOINCREMENT, vault_id TEXT NOT NULL, id TEXT NOT NULL, attempt_id TEXT NOT NULL, payload BLOB NOT NULL, payload_digest TEXT NOT NULL, semantic_digest TEXT NOT NULL, classification TEXT NOT NULL, observed_at_ms INTEGER NOT NULL, UNIQUE(vault_id,id), FOREIGN KEY(vault_id,attempt_id) REFERENCES runtime_attempts(vault_id,id))',
    'CREATE TABLE runtime_result_refs (vault_id TEXT NOT NULL, observation_id TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(vault_id,observation_id), FOREIGN KEY(vault_id,observation_id) REFERENCES runtime_result_observations(vault_id,id), FOREIGN KEY(vault_id,kind,id,version,sha256) REFERENCES domain_records(vault_id,kind,id,version,sha256))',
    'CREATE TABLE runtime_tool_calls (vault_id TEXT NOT NULL, id TEXT NOT NULL, attempt_id TEXT NOT NULL, tool_id TEXT NOT NULL, version TEXT NOT NULL, effect_class TEXT NOT NULL, inputs BLOB NOT NULL, inputs_digest TEXT NOT NULL, state TEXT NOT NULL, result_kind TEXT, result_id TEXT, result_version INTEGER, result_sha256 TEXT, command_id TEXT NOT NULL, created_at_ms INTEGER NOT NULL, settled_at_ms INTEGER, approval_kind TEXT, approval_id TEXT, approval_version INTEGER, approval_sha256 TEXT, PRIMARY KEY(vault_id,id), UNIQUE(vault_id,attempt_id), UNIQUE(vault_id,command_id), FOREIGN KEY(vault_id,attempt_id) REFERENCES runtime_attempts(vault_id,id))',
    'CREATE TABLE runtime_checkpoints (vault_id TEXT NOT NULL, run_id TEXT NOT NULL, namespace TEXT NOT NULL, revision INTEGER NOT NULL, cursor BLOB NOT NULL, cursor_sha256 TEXT NOT NULL, bound_attempt_id TEXT, bound_attempt_revision INTEGER, bound_execution_id TEXT, bound_envelope_sha256 TEXT, created_at_ms INTEGER NOT NULL, command_id TEXT NOT NULL, PRIMARY KEY(vault_id,run_id,namespace,revision), UNIQUE(vault_id,command_id), FOREIGN KEY(vault_id,run_id) REFERENCES runtime_runs(vault_id,id))',
    'CREATE TABLE runtime_attempt_journal (sequence INTEGER PRIMARY KEY AUTOINCREMENT, vault_id TEXT NOT NULL, attempt_id TEXT NOT NULL, transition TEXT NOT NULL, payload BLOB NOT NULL, payload_digest TEXT NOT NULL, at_ms INTEGER NOT NULL, FOREIGN KEY(vault_id,attempt_id) REFERENCES runtime_attempts(vault_id,id))',
    'CREATE TABLE runtime_public_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, vault_id TEXT NOT NULL, event_type TEXT NOT NULL, object_kind TEXT NOT NULL, object_id TEXT NOT NULL, payload BLOB NOT NULL, payload_digest TEXT NOT NULL, at_ms INTEGER NOT NULL)',
    'CREATE INDEX runtime_attempts_execution ON runtime_attempts(vault_id,execution_id,attempt_no)',
    'CREATE INDEX runtime_results_attempt ON runtime_result_observations(vault_id,attempt_id,observed_at_ms,id)',
    'CREATE INDEX runtime_checkpoints_latest ON runtime_checkpoints(vault_id,run_id,namespace,revision)',
)
LEDGER_V2_SHA256 = '3131be5d54e0ffdfcf980353d04b81428f27e64711f4762993e63915deeda255'

assert sha256("\n".join(LEDGER_V1_DDL).encode()).hexdigest() == LEDGER_V1_SHA256
assert sha256("\n".join(LEDGER_V2_DDL).encode()).hexdigest() == LEDGER_V2_SHA256
_V1_SHAPE = _compiled_schema(LEDGER_V1_DDL)
_V2_SHAPE = _compiled_schema(LEDGER_V2_DDL)
