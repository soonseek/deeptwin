"""Private transaction-only validation. No ledger, permission or filesystem authority."""
import sqlite3

from ..domain.refs import EntityRef, parse_canonical
from ..domain.store import DomainStore, VaultRoots, _ROOT_NAMES, _MIGRATION_ROWS
from ..domain.schemas import GENESIS_VERSION, BOOTSTRAP_VERSION
from .ledger import RuntimeLedger, CorruptLedger, RunSpec, ExecutionSpec, _decode_canonical
from .ledger_schema import _schema_version
from .worker_response_capture import _capture_journal_value, _validate_capture_relationship


class _HistoryReader:
    """Explicit pure-function allowlist, deliberately not a RuntimeLedger subclass."""
    __slots__ = ("vault_id",)
    _object_ref = staticmethod(RuntimeLedger._object_ref)
    _run_snapshot = RuntimeLedger._run_snapshot
    _execution_snapshot = RuntimeLedger._execution_snapshot
    _attempt_snapshot = RuntimeLedger._attempt_snapshot
    _validate_domain_ref_row = RuntimeLedger._validate_domain_ref_row
    _validate_ref_roles = RuntimeLedger._validate_ref_roles
    _validate_run_bindings = RuntimeLedger._validate_run_bindings
    _validate_execution_bindings = RuntimeLedger._validate_execution_bindings
    _validate_result_binding = RuntimeLedger._validate_result_binding
    _resolve_node_dispatch_context = RuntimeLedger._resolve_node_dispatch_context
    _run_spec_for_attempt = RuntimeLedger._run_spec_for_attempt
    _load_attempt = RuntimeLedger._load_attempt
    _checkpoint = RuntimeLedger._checkpoint

    def __init__(self, vault_id):
        self.vault_id = vault_id


def _verify_history(db, vault_id):
    """Caller has already bounded every selected scalar and installed the deadline."""
    if (type(db) is not sqlite3.Connection or not db.in_transaction
            or db.row_factory is not sqlite3.Row or db.execute("PRAGMA foreign_keys").fetchone()[0] != 1):
        raise CorruptLedger("History requires a checked FK-on transaction")
    DomainStore._verify_schema(db, through_version=2)
    if [tuple(row) for row in db.execute("SELECT version,sha256 FROM domain_migrations ORDER BY version")] != list(_MIGRATION_ROWS):
        raise CorruptLedger("Domain migration history changed")
    registry = db.execute("SELECT * FROM domain_vault").fetchall()
    if len(registry) != 1 or registry[0]["vault_id"] != vault_id or registry[0]["dispatch_enabled"] != 0:
        raise CorruptLedger("Vault binding changed")
    root_value = parse_canonical(registry[0]["roots"])
    if set(root_value) != set(_ROOT_NAMES):
        raise CorruptLedger("Vault roots changed")
    roots = VaultRoots(**{name: EntityRef.from_dict(root_value[name]) for name in _ROOT_NAMES})
    if roots.genesis.id != vault_id:
        raise CorruptLedger("Vault genesis changed")
    for name in _ROOT_NAMES:
        ref = getattr(roots, name)
        if ref.kind != ("vault_genesis" if name == "genesis" else name) or ref.version != 1:
            raise CorruptLedger("Vault root identity changed")
        record = DomainStore._load(db, ref, roots)[0]
        if record.body["schema_version"] != (GENESIS_VERSION if name == "genesis" else BOOTSTRAP_VERSION):
            raise CorruptLedger("Vault root schema changed")
    control = db.execute("SELECT * FROM runtime_control").fetchall()
    if len(control) != 1 or control[0]["vault_id"] != vault_id:
        raise CorruptLedger("Runtime vault binding changed")
    RuntimeLedger._validate_control(control[0])
    reader = _HistoryReader(vault_id)
    for row in db.execute("SELECT * FROM runtime_runs"):
        _same_vault(row, vault_id)
        reader._validate_run_bindings(db, RunSpec.from_dict(reader._run_snapshot(row)["spec"]))
    for row in db.execute("SELECT * FROM runtime_node_executions"):
        _same_vault(row, vault_id)
        reader._validate_execution_bindings(db, ExecutionSpec.from_dict(reader._execution_snapshot(row)["spec"]))
    for row in db.execute("SELECT * FROM runtime_attempts"):
        _same_vault(row, vault_id)
        reader._load_attempt(db, row["id"])
    for row in db.execute("SELECT * FROM runtime_checkpoints"):
        _same_vault(row, vault_id)
        reader._checkpoint(db, row["run_id"], row["namespace"], revision=row["revision"])
    for row in db.execute("SELECT * FROM runtime_result_observations"):
        _same_vault(row, vault_id)
        value = RuntimeLedger._result_observation(row)
        reader._validate_result_binding(db, value)
        if row["classification"] == "accepted":
            attempt = db.execute("SELECT accepted_observation_id FROM runtime_attempts "
                                 "WHERE vault_id=? AND id=?", (vault_id, row["attempt_id"])).fetchone()
            if attempt is None or attempt[0] != row["id"]:
                raise CorruptLedger("Accepted result reverse binding changed")
    for table, pairs in (
            ("runtime_commands", (("payload", "payload_digest"), ("result", "result_digest"))),
            ("runtime_tool_calls", (("inputs", "inputs_digest"),))):
        for row in db.execute(f"SELECT * FROM {table}"):
            _same_vault(row, vault_id)
            for body, digest in pairs:
                _decode_canonical(row[body], row[digest], "history")
            if table == "runtime_tool_calls":
                for role in ("result", "approval"):
                    values = tuple(row[f"{role}_{field}"] for field in
                                   ("kind", "id", "version", "sha256"))
                    if all(value is None for value in values):
                        continue
                    if any(value is None for value in values):
                        raise CorruptLedger("Tool call reference is incomplete")
                    reader._validate_domain_ref_row(db, EntityRef(*values))
    for row in db.execute("SELECT * FROM runtime_attempt_journal"):
        _same_vault(row, vault_id)
        RuntimeLedger._journal_snapshot(row)
    for row in db.execute("SELECT * FROM runtime_public_events"):
        _same_vault(row, vault_id)
        RuntimeLedger._event_snapshot(row)
    captures, commands = set(), set()
    for row in db.execute("SELECT * FROM runtime_attempt_journal WHERE transition='response_captured'"):
        value, ref = _capture_journal_value(row)
        record = DomainStore._load(db, ref, roots)[0]
        envelope = DomainStore._load(db, EntityRef.from_dict(
            record.body["content"]["execution_envelope_ref"]), roots)[0]
        _validate_capture_relationship(reader, db, row, value, record, roots, envelope)
        if row["attempt_id"] in captures or value["command_id"] in commands:
            raise CorruptLedger("Capture attachment duplicated")
        captures.add(row["attempt_id"])
        commands.add(value["command_id"])
    if db.execute("SELECT count(*) FROM domain_records WHERE kind='worker_response_capture'").fetchone()[0] != len(captures):
        raise CorruptLedger("Capture attachment missing")
    if _schema_version(db) == 2:
        subjects = db.execute("SELECT * FROM runtime_dispatch_subjects")
        count = 0
        for row in subjects:
            _same_vault(row, vault_id)
            if (row["subject_kind"] != "node_execution" or row["subject_id"] != row["node_execution_id"]
                    or any(row[key] is not None for key in ("generation_kind", "generation_version", "generation_sha256"))):
                raise CorruptLedger("Unsupported dispatch subject")
            count += 1
        if count != db.execute("SELECT count(*) FROM runtime_node_executions").fetchone()[0]:
            raise CorruptLedger("Node dispatch subjects incomplete")
    return roots


def _same_vault(row, vault_id):
    if row["vault_id"] != vault_id:
        raise CorruptLedger("Foreign runtime history")
