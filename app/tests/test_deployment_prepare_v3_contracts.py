"""Task 24 step (c2): the pure v3 constants and codecs of
contracts/deployment-receipt-journal-v3.md — the thirteen-statement DDL_V3 with its
frozen checksum (§2/§8), the consume command input and frozen reply (§6), the
prepare-api-v3 structural artifact (§6) and `parse_consume` (§7).

Pure values only: no layout dispatch, migration, service, observer or route.
Schema validity grants no acceptance, installation or head authority.
"""

import hashlib
import importlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app.deployment import prepare_storage as storage
from app.domain.refs import canonical_json
from app.tests.deployment_source_fixture import profile
from app.tests.test_deployment_prepare_v2_contracts import (
    accepted_request,
    import_input,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT / "schemas/v1/deployment"
CHECKSUM_V3 = "ff0931661b7958805f3113bad954110ca702ba3c0205e6dadc73651508a51457"
STUBS = (
    "CREATE TABLE domain_vault(vault_id TEXT PRIMARY KEY)",
    (
        "CREATE TABLE domain_blobs(vault_id TEXT, purpose TEXT, sha256 TEXT,"
        " PRIMARY KEY(vault_id,purpose,sha256))"
    ),
    (
        "CREATE TABLE domain_records(vault_id TEXT, kind TEXT, id TEXT, version INTEGER,"
        " sha256 TEXT, PRIMARY KEY(vault_id,kind,id,version,sha256))"
    ),
    "CREATE TABLE api_event_envelopes(event_id TEXT PRIMARY KEY)",
)


def contracts():
    try:
        return importlib.import_module("app.deployment.prepare_v3_contracts")
    except ModuleNotFoundError:
        pytest.fail("Deployment prepare v3 contracts are missing")


def exports():
    try:
        return importlib.import_module("app.deployment.prepare_v3_schema_exports")
    except ModuleNotFoundError:
        pytest.fail("Deployment prepare v3 schema exports are missing")


def validator(schema):
    return Draft202012Validator(schema, format_checker=FormatChecker())


def consume_input():
    return {**import_input(revision=2)}


def installation():
    return {
        "installation_id": str(uuid4()),
        "extension_id": "synthetic-tool",
        "installation_digest": "c" * 64,
        "revision": 1,
    }


def consume_reply():
    return {
        "command_id": str(uuid4()),
        "request_id": str(uuid4()),
        "receipt_digest": "E" * 43,
        "outcome": "succeeded",
        "disposition": "consumed_success",
        "revision": 3,
        "installation": installation(),
        "event_cursor": "cursor",
    }


def receipt(outcome="succeeded", *, disposition=None):
    return {
        "receipt_digest": "E" * 43,
        "outcome": outcome,
        "disposition": disposition
        or ("pending_postconditions" if outcome == "succeeded" else "consumed_non_success"),
        "import_revision": 2,
    }


def state(*, state, revision, receipt=None, consumption=None, installation=None):
    return {
        "request_id": str(uuid4()),
        "request_digest": "A" * 43,
        "kind": "extension_stage",
        "state": state,
        "revision": revision,
        "publication_state": "suppressed" if revision > 1 else "pending",
        "cancellation_publication_state": "pending" if state == "cancelled" else None,
        "receipt": receipt,
        "consumption_publication_state": consumption,
        "installation": installation,
        "request": accepted_request(profile()),
        "links": {
            "self": "/api/v1/deployment/requests/" + str(uuid4()),
            "cancel": "/api/v1/deployment/requests/" + str(uuid4()) + "/cancel",
            "events": "/api/v1/events",
        },
    }


# --- storage constants ---


def test_ddl_v3_is_thirteen_statements_with_the_frozen_checksum_and_unchanged_history():
    assert len(storage.DDL_V3) == 13
    assert all(type(statement) is str for statement in storage.DDL_V3)
    names = [statement.split("(")[0].split()[-1] for statement in storage.DDL_V3]
    assert names == [
        "deployment_prepare_" + suffix
        for suffix in (
            "migrations", "control", "requests", "lifecycle", "heads", "commands",
            "outbox", "receipt_sources", "receipts", "consumptions", "consumed_outbox",
            "installations", "installation_heads",
        )
    ]
    # seven statements byte-identical to their v1/v2 strings, four changed, two new
    for index in (1, 2, 4, 6, 7, 8, 10):
        assert storage.DDL_V3[index] == storage.DDL_V2[index]
    for index in (0, 3, 5, 9):
        assert storage.DDL_V3[index] != storage.DDL_V2[index]
    assert storage.CHECKSUM_V3 == CHECKSUM_V3
    assert storage.CHECKSUM_V3 == hashlib.sha256(
        canonical_json(list(storage.DDL_V3))
    ).hexdigest()
    assert storage.CHECKSUM == "68a6ed89486cb48536873e4b107e2e7e1dd4061e5ce65773b0bebe46303cc2ec"
    assert storage.CHECKSUM_V2 == "d35202bc3d2b3f7be9a0a0d86ba32171c4055334f11531c40497d9b54165693f"
    assert storage.TABLES_V3 == (*storage.TABLES_V2, "installations", "installation_heads")
    assert storage.CAPS_V3 == {**storage.CAPS_V2, "installations": 16, "installation_heads": 16}
    assert storage.NULLABLE_V3 == storage.NULLABLE_V2
    assert storage.TABLES_V2 == (*storage.TABLES, "receipt_sources", "receipts",
                                 "consumptions", "consumed_outbox")


def fresh_v3():
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys=ON")
    for statement in (*STUBS, *storage.DDL_V3):
        db.execute(statement)
    return db


def test_ddl_v3_creates_in_order_under_foreign_keys_and_its_checks_close_the_matrix():
    db = fresh_v3()
    tables = {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'deployment_prepare_*'"
        )
    }
    assert len(tables) == 13
    # the changed CHECK arms alone: foreign keys are switched off here so that
    # only a CHECK can refuse, and the intended rows are shown admitted
    db.execute("PRAGMA foreign_keys=OFF")
    db.execute("INSERT INTO deployment_prepare_migrations VALUES (3, ?)", ("c" * 64,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO deployment_prepare_migrations VALUES (4, ?)", ("c" * 64,))
    lifecycle_columns = (
        "request_id, revision, previous_revision, previous_hash, state, transitioned_ms,"
        " actor_ref, command_id, event_id, hash"
    )

    def lifecycle(revision, state, previous, command, request="r"):
        db.execute(
            f"INSERT INTO deployment_prepare_lifecycle({lifecycle_columns})"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (request, revision, previous, None if previous is None else "h" * 64, state, 1,
             "actor", command, f"e{request}{revision}{state}", "h" * 64),
        )

    def command(namespace, status, revision, identity="c" * 36):
        db.execute(
            "INSERT INTO deployment_prepare_commands VALUES (?,?,?,?,?,?,?,?,?,?)",
            (identity, namespace, "r", "a", "{}", "d" * 64, status, "{}", revision, "h" * 64),
        )

    def head(revision):
        db.execute(
            "INSERT INTO deployment_prepare_installation_heads VALUES (?,?,?,?,?)",
            ("ext", "r", revision, "a" * 64, "h" * 64),
        )

    lifecycle(3, "accepted", 2, "c" * 36)  # admitted: accepted at revision 3 with a command
    command("deployment-consume-v1", 200, 3)  # admitted: consume is a 200 at revision 3
    head(1)  # admitted: the absent-only head is revision 1
    for refused in (
        lambda: lifecycle(2, "accepted", 1, "d" * 36, request="s"),  # accepted only at 3
        lambda: lifecycle(3, "rejected", 2, "d" * 36, request="t"),  # rejected only at 2
        lambda: lifecycle(3, "accepted", 2, None, request="u"),  # accepted needs a command
        lambda: command("deployment-consume-v1", 200, 2, identity="e" * 36),
        lambda: command("deployment-consume-v1", 201, 3, identity="f" * 36),
        lambda: command("deployment-receipt-import-v1", 200, 3, identity="g" * 36),
        lambda: head(2),
    ):
        # the named CHECK arm, not a key collision, is what refuses
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            refused()
    # the two new tables have no nullable column (NULLABLE_V3 adds nothing)
    for table in ("deployment_prepare_installations", "deployment_prepare_installation_heads"):
        columns = list(db.execute(f"PRAGMA table_info({table})"))
        # notnull, or a primary-key column (SQLite reports those as notnull 0)
        assert columns and all(row[3] == 1 or row[5] > 0 for row in columns), table
    db.close()


# --- pure consume codec ---


def test_parse_consume_retains_route_identity_and_returns_a_fresh_inert_value():
    module = contracts()
    request_id = str(uuid4())
    value = consume_input()
    first = module.parse_consume(request_id, value)
    assert first == {**value, "request_id": request_id}
    first["command_id"] = str(uuid4())
    assert module.parse_consume(request_id, value) == {**value, "request_id": request_id}


@pytest.mark.parametrize(
    "change",
    [
        {"expected_revision": 1},
        {"expected_revision": 3},
        {"expected_revision": True},
        {"receipt_digest": "A" * 42 + "B"},
        {"request_digest": "not-b32-private-canary"},
        {"command_id": "not-a-uuid-private-canary"},
        {"extra": None},
        {"request_id": str(uuid4())},
    ],
)
def test_parse_consume_rejects_every_closed_violation(change):
    module = contracts()
    with pytest.raises(module.DeploymentPrepareError) as error:
        module.parse_consume(str(uuid4()), {**consume_input(), **change})
    assert error.value.code in {"invalid_input", "too_large"}
    assert "private-canary" not in str(error.value)
    with pytest.raises(module.DeploymentPrepareError):
        module.parse_consume("00000000-0000-0000-0000-000000000000", consume_input())
    with pytest.raises(module.DeploymentPrepareError) as error:
        module.parse_consume(str(uuid4()), {**consume_input(), "command_id": "x" * 4097})
    assert error.value.code == "too_large"


# --- prepare-api-v3 ---


def test_consume_input_and_reply_schemas_are_closed():
    module = exports()
    check = validator(module.consume_input_schema())
    assert check.is_valid(consume_input())
    for bad in (
        {**consume_input(), "expected_revision": 1},
        {**consume_input(), "expected_revision": 3},
        {**consume_input(), "extra": None},
    ):
        assert not check.is_valid(bad)
    reply = validator(module.consume_receipt_schema())
    assert reply.is_valid(consume_reply())
    for bad in (
        {**consume_reply(), "outcome": "failed"},
        {**consume_reply(), "disposition": "pending_postconditions"},
        {**consume_reply(), "revision": 2},
        {**consume_reply(), "installation": None},
        {**consume_reply(), "installation": {**installation(), "revision": 2}},
        {**consume_reply(), "installation": {**installation(), "installation_digest": "C" * 43}},
        {**consume_reply(), "installation": {**installation(), "extra": 1}},
        {**consume_reply(), "extra": None},
    ):
        assert not reply.is_valid(bad), bad


def test_read_schema_v3_covers_accepted_and_keeps_every_v2_combination():
    module = exports()
    check = validator(module.read_schema())
    valid = [
        state(state="prepared", revision=1),
        state(state="cancelled", revision=2),
        state(state="expired", revision=2),
        state(state="receipt_pending", revision=2, receipt=receipt()),
        state(state="rejected", revision=2, receipt=receipt("failed"), consumption="pending"),
        state(state="rejected", revision=2, receipt=receipt("unknown"), consumption="published"),
        state(state="cancelled", revision=3, receipt=receipt()),
        state(state="expired", revision=3, receipt=receipt()),
        state(
            state="accepted",
            revision=3,
            receipt=receipt(disposition="consumed_success"),
            installation=installation(),
        ),
    ]
    for value in valid:
        assert check.is_valid(value), value["state"]
    accepted = valid[-1]
    invalid = [
        {**valid[0], "installation": installation()},
        {**valid[3], "installation": installation()},
        {**accepted, "installation": None},
        {**accepted, "receipt": receipt()},  # pending disposition on an accepted head
        {**accepted, "consumption_publication_state": "pending"},  # no K marker for success
        {**accepted, "revision": 2},
        {**accepted, "cancellation_publication_state": "pending"},
        {**valid[4], "receipt": receipt(disposition="consumed_success")},
        {**valid[6], "receipt": receipt(disposition="consumed_success")},
    ]
    for value in invalid:
        assert not check.is_valid(value), value["state"]


def test_exact_one_export_is_detached_and_matches_fresh_artifact_bytes(tmp_path):
    module = exports()
    values = module.exported_schemas()
    assert set(values) == {"prepare-api-v3.schema.json"}
    schema = values["prepare-api-v3.schema.json"]
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == "urn:deeptwin:schemas:v1:deployment:prepare-api-v3"
    assert "Structural only" in schema["$comment"]
    api = validator(schema)
    assert api.is_valid(consume_input()) and api.is_valid(consume_reply())
    assert api.is_valid(
        state(state="accepted", revision=3, receipt=receipt(disposition="consumed_success"),
              installation=installation())
    )
    schema.clear()
    assert exports().exported_schemas()["prepare-api-v3.schema.json"]
    module.write_schemas(tmp_path)
    for name, value in module.exported_schemas().items():
        expected = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        assert (tmp_path / name).read_bytes() == expected
        assert (ARTIFACT_ROOT / name).read_bytes() == expected
    # v1/v2 artifacts are untouched by the v3 export
    v2 = importlib.import_module("app.deployment.prepare_v2_schema_exports")
    for name, value in v2.exported_schemas().items():
        expected = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        assert (ARTIFACT_ROOT / name).read_bytes() == expected


def test_fresh_v3_import_loads_no_crypto_reader_owner_http_or_service():
    root = os.fspath(ROOT)
    program = """
import sys
import app.deployment.prepare_v3_contracts
import app.deployment.prepare_v3_schema_exports
forbidden = {
    'nacl',
    'app.deployment.receipt_sources',
    'app.deployment.sources',
    'app.deployment.prepare_service',
    'app.deployment.stage_observer',
    'app.services.owner_auth',
    'app.api.deployment_prepare',
    'app.workers.listener',
}
assert forbidden.isdisjoint(sys.modules), forbidden & set(sys.modules)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = root
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", "-c", program],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
