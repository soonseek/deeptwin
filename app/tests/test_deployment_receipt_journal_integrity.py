"""Retained receipt history rejects rehashed relationship and bounded-value corruption."""

import sqlite3
from uuid import uuid4

import pytest

from app.deployment import prepare_storage as storage
from app.deployment.prepare_contracts import DeploymentPrepareError
from app.tests.deployment_receipt_import_fixture import (
    receipt_context,
    reopen,
    signed_case,
)
from app.tests.test_deployment_prepare_integrity import corrupt


@pytest.mark.parametrize(
    "table,change",
    [
        ("receipt_sources", {"trust_size": 1}),
        ("receipt_sources", {"trust_sha256": "0" * 64}),
        (
            "receipt_sources",
            {"identity_json": '{"consumption":{},"ingress":{},"trust":{}}'},
        ),
        ("receipts", {"outcome": "succeeded"}),
        ("receipts", {"receipt_size": 1}),
        ("receipts", {"import_command_id": str(uuid4())}),
        ("receipts", {"anchor_digest": "0" * 64}),
        ("consumptions", {"event_id": str(uuid4())}),
        ("consumptions", {"consumed_ms": 1}),
        ("consumptions", {"receipt_sha256": "0" * 64}),
        ("consumptions", {"command_id": str(uuid4())}),
        ("consumed_outbox", {"payload_sha256": "0" * 64}),
        ("consumed_outbox", {"payload_size": 1}),
        ("consumed_outbox", {"state": "published", "revision": 2, "published_ms": 1}),
    ],
)
def test_rehashed_receipt_relationship_corruption_fails_closed(
    tmp_path, monkeypatch, table, change
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(actual, monkeypatch)
        actual.service.import_receipt(actual.request, prepared["request_id"], command)
        corrupt(actual.domain, table, change)
        service = reopen(actual, trust=False, ingress=False, consumption=False)
        with pytest.raises(DeploymentPrepareError) as failure:
            service.read(actual.read_request, prepared["request_id"])
        assert failure.value.code == "unavailable"


@pytest.mark.parametrize(
    "table,column,value",
    [
        ("receipt_sources", "identity_json", "x" * 8193),
        ("receipt_sources", "identity_json", "é" * 4097),
        ("receipts", "receipt_size", "x" * 100000),
        ("consumptions", "consumed_ms", "x" * 100000),
        ("consumed_outbox", "published_ms", "x" * 100000),
    ],
)
def test_new_scalar_preflight_precedes_full_checksum_loader(
    tmp_path, monkeypatch, table, column, value
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(actual, monkeypatch)
        actual.service.import_receipt(actual.request, prepared["request_id"], command)
        with sqlite3.connect(actual.domain.path) as db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute(
                "UPDATE deployment_prepare_" + table + " SET " + column + "=?", (value,)
            )
        monkeypatch.setattr(
            storage,
            "verify",
            lambda _db: pytest.fail("oversized scalar reached full checksum loader"),
        )
        assert reopen(actual)._unavailable


@pytest.mark.parametrize(
    "table", ["receipt_sources", "receipts", "consumptions", "consumed_outbox"]
)
def test_deleted_new_index_or_intent_never_erases_committed_history(
    tmp_path, monkeypatch, table
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(actual, monkeypatch)
        actual.service.import_receipt(actual.request, prepared["request_id"], command)
        with sqlite3.connect(actual.domain.path) as db:
            db.execute("DELETE FROM deployment_prepare_" + table)
        assert reopen(
            actual, trust=False, ingress=False, consumption=False
        )._unavailable


def test_cancel_intent_references_actual_cancel_revision(tmp_path, monkeypatch):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(
            actual, monkeypatch, case_name="valid_succeeded_present"
        )
        actual.service.import_receipt(actual.request, prepared["request_id"], command)
        actual.service.cancel(
            actual.request,
            prepared["request_id"],
            {
                "command_id": str(uuid4()),
                "request_digest": prepared["request_digest"],
                "expected_revision": 2,
            },
        )
        with sqlite3.connect(actual.domain.path) as db:
            db.row_factory = sqlite3.Row
            row = dict(
                db.execute(
                    "SELECT * FROM deployment_prepare_outbox WHERE role='cancel'"
                ).fetchone()
            )
            row["lifecycle_revision"] = 2
            row["hash"] = storage.digest("outbox", row)
            db.execute(
                "UPDATE deployment_prepare_outbox SET lifecycle_revision=2,hash=? WHERE role='cancel'",
                (row["hash"],),
            )
        assert reopen(actual)._unavailable
