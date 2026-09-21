"""Whole-history refusals use the actual same-owner graph and stored receipt bytes."""

from uuid import uuid4
import sqlite3
import pytest
from app.deployment import prepare_storage as storage
from app.deployment.prepare_contracts import DeploymentPrepareError
from app.domain.refs import parse_canonical
from app.tests.provider_receipt_fixture import (
    provider_receipt_context,
    signed_receipt,
    install_receipt,
)


@pytest.mark.parametrize(
    "fault",
    [
        "source_identity",
        "receipt_outcome",
        "receipt_size",
        "command_reply",
        "missing_blob_edge",
        "missing_parent_edge",
        "source_only",
    ],
)
def test_rehashed_or_structural_receipt_corruption_never_replays(
    tmp_path, monkeypatch, fault
):
    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        digest = install_receipt(actual, signed_receipt(actual, request))
        selector = {
            "command_id": str(uuid4()),
            "request_digest": prepared["request_digest"],
            "receipt_digest": digest,
            "expected_revision": 1,
        }
        actual.service.import_provider_receipt(
            actual.request, prepared["request_id"], selector
        )
        with sqlite3.connect(actual.domain.path) as db:
            db.row_factory = sqlite3.Row
            if fault in {"missing_blob_edge", "missing_parent_edge"}:
                table = (
                    "domain_record_blobs"
                    if fault == "missing_blob_edge"
                    else "domain_edges"
                )
                db.execute(
                    "DELETE FROM " + table + " WHERE source_kind='deployment_receipt'"
                )
            elif fault == "source_only":
                db.execute("DELETE FROM deployment_prepare_receipts")
            else:
                table = (
                    "provider_receipt_sources"
                    if fault == "source_identity"
                    else "commands"
                    if fault == "command_reply"
                    else "receipts"
                )
                row = dict(
                    db.execute(
                        "SELECT * FROM deployment_prepare_"
                        + table
                        + (" WHERE command_id=?" if table == "commands" else ""),
                        (selector["command_id"],) if table == "commands" else (),
                    ).fetchone()
                )
                field = {
                    "source_identity": "identity_json",
                    "receipt_outcome": "outcome",
                    "receipt_size": "receipt_size",
                    "command_reply": "receipt_json",
                }[fault]
                if fault == "source_identity":
                    identity = parse_canonical(row[field].encode())
                    identity["incoming"]["root"]["inode"] += 1
                    row[field] = storage.encoded(identity)
                elif fault == "command_reply":
                    reply = parse_canonical(row[field].encode())
                    reply["links"]["consume"] += "/forged"
                    row[field] = storage.encoded(reply)
                else:
                    row[field] = (
                        "failed" if fault == "receipt_outcome" else row[field] + 1
                    )
                db.execute(
                    "UPDATE deployment_prepare_"
                    + table
                    + " SET "
                    + field
                    + "=?,hash=?"
                    + (" WHERE command_id=?" if table == "commands" else ""),
                    (row[field], storage.digest(table, row), selector["command_id"])
                    if table == "commands"
                    else (row[field], storage.digest(table, row)),
                )
        with pytest.raises(DeploymentPrepareError) as caught:
            actual.service.import_provider_receipt(
                actual.request, prepared["request_id"], selector
            )
        assert caught.value.code == "unavailable"


def test_bad_evidence_in_refreshed_installation_index_is_historical_unavailable(
    tmp_path, monkeypatch
):
    from app.tests.provider_receipt_fixture import provider_worker

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        digest = install_receipt(actual, signed_receipt(actual, request))
        value = {
            "command_id": str(uuid4()),
            "request_digest": prepared["request_digest"],
            "receipt_digest": digest,
            "expected_revision": 1,
        }
        actual.service.import_provider_receipt(
            actual.request, prepared["request_id"], value
        )
        with provider_worker(actual, monkeypatch):
            actual.service.consume_provider_receipt(
                actual.request,
                prepared["request_id"],
                {**value, "command_id": str(uuid4()), "expected_revision": 2},
            )
        bad = actual.domain.put_blob(b"{}", purpose="operational")
        with sqlite3.connect(actual.domain.path) as db:
            db.row_factory = sqlite3.Row
            row = dict(
                db.execute("SELECT * FROM deployment_prepare_installations").fetchone()
            )
            row.update(evidence_sha256=bad.sha256, evidence_size=bad.size)
            db.execute(
                "UPDATE deployment_prepare_installations SET evidence_sha256=?,evidence_size=?,hash=?",
                (bad.sha256, bad.size, storage.digest("installations", row)),
            )
        with pytest.raises(DeploymentPrepareError) as caught:
            actual.service.read_provider(actual.read_request, prepared["request_id"])
        assert caught.value.code == "unavailable"
