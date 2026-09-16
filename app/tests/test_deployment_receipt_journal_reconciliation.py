"""One reconciliation budget with durable consumed intent and enrolled K gates."""

import time
from base64 import urlsafe_b64decode
from uuid import uuid4

import pytest

from app.deployment import prepare_storage as storage
from app.deployment import receipt_sources
from app.deployment.prepare_contracts import DeploymentPrepareError, epoch_ms
from app.tests.deployment_prepare_fixture import register_variant
from app.tests.deployment_receipt_import_fixture import (
    receipt_context,
    reopen,
    signed_case,
)
from app.tests.test_deployment_publication import syscall_fixture


def consumed_path(actual, command):
    return actual.actual.actual(receipt_sources.CONSUMED_NAMESPACE_ROOT) / (
        urlsafe_b64decode(command["receipt_digest"] + "=").hex() + ".json"
    )


def test_consumed_intent_publishes_only_committed_exact_marker_and_replay_is_inert(
    tmp_path, monkeypatch
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(actual, monkeypatch)
        result = actual.service.import_receipt(
            actual.request, prepared["request_id"], command
        )
        syscall_fixture(monkeypatch)
        actual.service.reconcile_startup()
        current = actual.service.read(actual.read_request, prepared["request_id"])
        assert current["consumption_publication_state"] == "published"
        from app.domain.refs import parse_canonical

        marker = parse_canonical(consumed_path(actual, command).read_bytes())
        assert (
            marker["receipt_digest"] == command["receipt_digest"]
            and marker["outcome"] == "failed"
        )
        with actual.domain._connection() as db:
            row = db.execute("SELECT * FROM deployment_prepare_consumptions").fetchone()
            assert marker["consumption_id"] == row["consumption_id"]
            assert (
                marker["consumed_at"].endswith("Z") and len(marker["consumed_at"]) == 24
            )
            assert (
                row["event_id"]
                == db.execute(
                    "SELECT event_id FROM deployment_prepare_lifecycle WHERE revision=2"
                ).fetchone()[0]
            )
        actual.consumption.close()
        assert (
            actual.service.import_receipt(
                actual.request, prepared["request_id"], command
            )
            == result
        )


@pytest.mark.parametrize("end", ["cancel", "expire"])
def test_pending_success_keeps_evidence_and_can_reach_revision_three(
    tmp_path, monkeypatch, end
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(
            actual, monkeypatch, case_name="valid_succeeded_present"
        )
        imported = actual.service.import_receipt(
            actual.request, prepared["request_id"], command
        )
        before = actual.service.read(actual.read_request, prepared["request_id"])
        syscall_fixture(monkeypatch)
        if end == "cancel":
            payload = {
                "command_id": str(uuid4()),
                "request_digest": prepared["request_digest"],
                "expected_revision": 2,
            }
            reply = actual.service.cancel(
                actual.request, prepared["request_id"], payload
            )
            assert reply["revision"] == 3
            assert (
                actual.service.cancel(actual.request, prepared["request_id"], payload)
                == reply
            )
        else:
            deadline = epoch_ms(before["request"]["expires_at"])
            monkeypatch.setattr(time, "time_ns", lambda: deadline * 1000000)
            actual.service.reconcile_startup()
        current = actual.service.read(actual.read_request, prepared["request_id"])
        assert (current["state"], current["revision"]) == (
            "cancelled" if end == "cancel" else "expired",
            3,
        )
        assert (
            current["receipt"] == before["receipt"]
            and current["consumption_publication_state"] is None
        )
        if end == "cancel":
            assert current["cancellation_publication_state"] == "published"
            actual.exchange.recheck_current()
            from app.domain.refs import parse_canonical

            target = actual.actual.actual(actual.actual.c.OUTBOX_ROOT / "cancelled") / (
                urlsafe_b64decode(prepared["request_digest"] + "=").hex() + ".json"
            )
            marker = parse_canonical(target.read_bytes())
            assert (
                marker["schema"] == "deployment-cancellation-v2"
                and marker["lifecycle_revision"] == 3
            )
        assert (
            actual.service.import_receipt(
                actual.request, prepared["request_id"], command
            )
            == imported
        )


def test_success_enrollment_without_consumption_blocks_new_positive_publication_when_k_missing(
    tmp_path, monkeypatch
):
    with receipt_context(tmp_path, monkeypatch, capacity=2) as actual:
        prepared, command, _, _ = signed_case(
            actual, monkeypatch, case_name="valid_succeeded_present"
        )
        actual.service.import_receipt(actual.request, prepared["request_id"], command)
        second = register_variant(actual, extension_id="second-extension", slot_id=2)
        actual.service = reopen(actual, consumption=False)
        syscall_fixture(monkeypatch)
        reply = actual.service.prepare(actual.request, second)
        assert reply["publication_state"] == "pending"
        current = actual.service.read(actual.read_request, reply["request_id"])
        assert current["publication_state"] == "pending"
        cancelled = actual.service.cancel(
            actual.request,
            reply["request_id"],
            {
                "command_id": str(uuid4()),
                "request_digest": reply["request_digest"],
                "expected_revision": 1,
            },
        )
        assert cancelled["state"] == "cancelled"
        assert (
            actual.service.read(actual.read_request, reply["request_id"])[
                "cancellation_publication_state"
            ]
            == "published"
        )


def test_file_before_ack_crash_recovers_but_missing_acknowledged_final_never_republishes(
    tmp_path, monkeypatch
):
    import sqlite3

    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(actual, monkeypatch)
        actual.service.import_receipt(actual.request, prepared["request_id"], command)
        syscall_fixture(monkeypatch)
        original = storage.advance

        def fail_ack(db, table, old, changes):
            if table == "consumed_outbox":
                raise sqlite3.OperationalError("controlled pre-ack crash")
            return original(db, table, old, changes)

        with monkeypatch.context() as fault:
            fault.setattr(storage, "advance", fail_ack)
            actual.service.reconcile_startup()
        path = consumed_path(actual, command)
        assert path.exists()
        before = path.read_bytes()
        actual.service = reopen(actual)
        assert (
            actual.service.read(actual.read_request, prepared["request_id"])[
                "consumption_publication_state"
            ]
            == "pending"
        )
        actual.service.reconcile_startup()
        assert path.read_bytes() == before
        assert (
            actual.service.read(actual.read_request, prepared["request_id"])[
                "consumption_publication_state"
            ]
            == "published"
        )
        path.rename(tmp_path / "saved-consumed.json")
        actual.service.reconcile_startup()
        assert not path.exists() and not actual.service._unavailable
        assert (
            actual.service.read(actual.read_request, prepared["request_id"])[
                "consumption_publication_state"
            ]
            == "published"
        )


def test_k_inventory_crossing_deadline_expires_instead_of_publishing_request(
    tmp_path, monkeypatch
):
    with receipt_context(tmp_path, monkeypatch, capacity=2) as actual:
        prepared, command, _, _ = signed_case(
            actual, monkeypatch, case_name="valid_succeeded_present"
        )
        actual.service.import_receipt(actual.request, prepared["request_id"], command)
        second = register_variant(actual, extension_id="second-extension", slot_id=2)
        actual.service = reopen(actual, consumption=False)
        reply = actual.service.prepare(actual.request, second)
        deadline = epoch_ms(
            actual.service.read(actual.read_request, reply["request_id"])["request"][
                "expires_at"
            ]
        )
        actual.service = reopen(actual)
        original = actual.consumption.inspect_consumed

        def cross_deadline():
            result = original()
            monkeypatch.setattr(time, "time_ns", lambda: deadline * 1000000)
            return result

        monkeypatch.setattr(actual.consumption, "inspect_consumed", cross_deadline)
        syscall_fixture(monkeypatch)
        actual.service.reconcile_startup()
        current = actual.service.read(actual.read_request, reply["request_id"])
        assert (
            current["state"] == "expired"
            and current["publication_state"] == "suppressed"
        )
        target = actual.actual.actual(actual.actual.c.OUTBOX_ROOT / "requests") / (
            urlsafe_b64decode(reply["request_digest"] + "=").hex() + ".json"
        )
        assert not target.exists()


def test_k_loss_after_request_visibility_keeps_pending_ack_and_cancel_stays_available(
    tmp_path, monkeypatch
):
    with receipt_context(tmp_path, monkeypatch, capacity=2) as actual:
        prepared, command, _, _ = signed_case(
            actual, monkeypatch, case_name="valid_succeeded_present"
        )
        actual.service.import_receipt(actual.request, prepared["request_id"], command)
        second = register_variant(actual, extension_id="second-extension", slot_id=2)
        syscall_fixture(monkeypatch)
        original = actual.exchange.publish

        def disappear(**kwargs):
            result = original(**kwargs)
            if kwargs["role"] == "request":
                actual.consumption.close()
            return result

        monkeypatch.setattr(actual.exchange, "publish", disappear)
        reply = actual.service.prepare(actual.request, second)
        target = actual.actual.actual(actual.actual.c.OUTBOX_ROOT / "requests") / (
            urlsafe_b64decode(reply["request_digest"] + "=").hex() + ".json"
        )
        assert target.exists()
        assert (
            actual.service.read(actual.read_request, reply["request_id"])[
                "publication_state"
            ]
            == "pending"
        )
        assert not actual.service._unavailable
        actual.service.cancel(
            actual.request,
            reply["request_id"],
            {
                "command_id": str(uuid4()),
                "request_digest": reply["request_digest"],
                "expected_revision": 1,
            },
        )
        assert (
            actual.service.read(actual.read_request, reply["request_id"])[
                "cancellation_publication_state"
            ]
            == "published"
        )


def test_alien_consumed_final_blocks_import_without_latching_local_history(
    tmp_path, monkeypatch
):
    from app.domain.refs import parse_canonical
    from app.tests.deployment_receipt_source_fixture import consumed_marker

    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(actual, monkeypatch)
        marker = consumed_marker()
        digest = parse_canonical(marker)["receipt_digest"]
        target = actual.actual.actual(receipt_sources.CONSUMED_NAMESPACE_ROOT) / (
            urlsafe_b64decode(digest + "=").hex() + ".json"
        )
        target.write_bytes(marker)
        target.chmod(0o440)
        actual.actual.register(target, 20102, 21201)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.import_receipt(
                actual.request, prepared["request_id"], command
            )
        assert failure.value.code == "dependency_unavailable"
        assert not actual.service._unavailable
        assert (
            actual.service.read(actual.read_request, prepared["request_id"])["state"]
            == "prepared"
        )
        syscall_fixture(monkeypatch)
        actual.service.cancel(
            actual.request,
            prepared["request_id"],
            {
                "command_id": str(uuid4()),
                "request_digest": prepared["request_digest"],
                "expected_revision": 1,
            },
        )
        assert (
            actual.service.read(actual.read_request, prepared["request_id"])[
                "cancellation_publication_state"
            ]
            == "published"
        )


def test_shared_soft_budget_publishes_cancel_before_consumed_before_request(
    tmp_path, monkeypatch
):
    with receipt_context(tmp_path, monkeypatch, capacity=3) as actual:
        rejected, command, _, _ = signed_case(actual, monkeypatch)
        actual.service.import_receipt(actual.request, rejected["request_id"], command)
        cancel_value = register_variant(actual, extension_id="cancel-tool", slot_id=2)
        cancelled = actual.service.prepare(actual.request, cancel_value)
        actual.service.cancel(
            actual.request,
            cancelled["request_id"],
            {
                "command_id": str(uuid4()),
                "request_digest": cancelled["request_digest"],
                "expected_revision": 1,
            },
        )
        prepare_value = register_variant(actual, extension_id="prepare-tool", slot_id=3)
        prepared = actual.service.prepare(actual.request, prepare_value)
        syscall_fixture(monkeypatch)
        ticks = [0.0]
        original = actual.service._reconcile_item
        visited = []

        def one_item(identity, role):
            original(identity, role)
            visited.append(role)
            ticks[0] += 2.0

        monkeypatch.setattr(actual.service, "_reconcile_item", one_item)
        monkeypatch.setattr(time, "monotonic", lambda: ticks[0])
        for expected in (
            ("cancel",),
            ("cancel", "consumed"),
            ("cancel", "consumed", "request"),
        ):
            actual.service.reconcile_startup()
            assert tuple(visited) == expected
        assert (
            actual.service.read(actual.read_request, cancelled["request_id"])[
                "cancellation_publication_state"
            ]
            == "published"
        )
        assert (
            actual.service.read(actual.read_request, rejected["request_id"])[
                "consumption_publication_state"
            ]
            == "published"
        )
        assert (
            actual.service.read(actual.read_request, prepared["request_id"])[
                "publication_state"
            ]
            == "published"
        )
