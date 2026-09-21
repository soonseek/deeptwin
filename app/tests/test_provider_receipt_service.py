"""Actual owner/provider receipt workflows; synthetic fixtures are not native proof."""

from uuid import uuid4
import pytest
import time
from app.deployment.prepare_contracts import DeploymentPrepareError, epoch_ms

from app.tests.provider_prepare_fixture import provider_context
from app.tests.provider_receipt_fixture import (
    provider_receipt_context,
    signed_receipt,
    install_receipt,
)


@pytest.mark.parametrize("legacy", [False, True])
def test_actual_two_connection_consume_creates_one_installation_and_restarts(
    tmp_path, monkeypatch, legacy
):
    from app.tests.provider_receipt_fixture import provider_worker
    from app.tests.test_provider_prepare_migration import reopen

    with provider_receipt_context(
        tmp_path.resolve(),
        monkeypatch,
        slot_id=2 if legacy else 1,
        legacy_staged=legacy,
    ) as actual:
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
        imported = actual.service.import_provider_receipt(
            actual.request, prepared["request_id"], selector
        )
        consume = {**selector, "command_id": str(uuid4()), "expected_revision": 2}
        reconcile_calls = []
        real_reconcile = actual.service._reconcile

        def reconcile():
            reconcile_calls.append("fresh-success")
            return real_reconcile()

        monkeypatch.setattr(actual.service, "_reconcile", reconcile)
        with provider_worker(actual, monkeypatch) as (_, measured):
            accepted = actual.service.consume_provider_receipt(
                actual.request, prepared["request_id"], consume
            )
        assert reconcile_calls == ["fresh-success"]
        assert (
            actual.service.consume_provider_receipt(
                actual.request, prepared["request_id"], consume
            )
            == accepted
        )
        assert reconcile_calls == ["fresh-success"]
        bound = actual.tree.peak + measured["socket_peak"]
        assert bound <= 256
        print(
            f"Task43 acceptance tracked file/scandir peak={actual.tree.peak}; socket peak={measured['socket_peak']}; measured combined upper bound={bound}"
        )
        assert accepted["state"] == "accepted" and accepted["revision"] == 3
        assert (
            accepted["installation_ref"] is not None
            and accepted["consumption_ref"] is not None
        )
        assert accepted["consumption_publication_state"] is None
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_installations"
                ).fetchone()[0]
                == 1 + legacy
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_installation_heads"
                ).fetchone()[0]
                == 1 + legacy
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_consumptions"
                ).fetchone()[0]
                == 1 + legacy
            )
            events = [
                tuple(row)
                for row in db.execute(
                    "SELECT sequence,event_type FROM api_event_envelopes ORDER BY sequence DESC LIMIT 2"
                )
            ]
            assert (
                events[0][1] == "extension.staged"
                and events[1][1] == "deployment.request_accepted"
            )
            assert events[0][0] == events[1][0] + 1
            assert (
                db.execute(
                    "SELECT count(*) FROM domain_records WHERE kind IN ('extension_qualification','extension_binding')"
                ).fetchone()[0]
                == 0
            )
        with pytest.raises(DeploymentPrepareError) as fresh:
            actual.service.prepare_provider(
                actual.request, {**actual.payload, "command_id": str(uuid4())}
            )
        assert fresh.value.code == "conflict"
        actual.context.close()
        service = reopen(actual)

        def forbidden(*args, **kwargs):
            raise AssertionError("exact replay invoked a live side effect")

        from app.deployment import provider_stage_observer, provider_receipt_records

        monkeypatch.setattr(service, "_now", forbidden)
        monkeypatch.setattr(service, "_reconcile", forbidden)
        monkeypatch.setattr(actual.domain, "put_blob", forbidden)
        monkeypatch.setattr(
            provider_stage_observer, "observe_provider_stage_postcondition", forbidden
        )
        monkeypatch.setattr(provider_receipt_records, "uuid4", forbidden)
        assert (
            service.consume_provider_receipt(
                actual.request, prepared["request_id"], consume
            )
            == accepted
        )
        assert (
            service.import_provider_receipt(
                actual.request, prepared["request_id"], selector
            )
            == imported
        )
        assert service.prepare_provider(actual.request, actual.payload) == prepared
        assert (
            service.read_provider(actual.read_request, prepared["request_id"])["state"]
            == "accepted"
        )
        if legacy:
            assert (
                service.prepare(actual.request, actual.legacy_payload)
                == actual.legacy_request
            )


@pytest.mark.parametrize("outcome", ["failed", "unknown"])
def test_actual_non_success_import_has_consumption_and_no_installation(
    tmp_path, monkeypatch, outcome
):
    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        reply = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, reply["request_id"]
        )["request"]
        digest = install_receipt(
            actual, signed_receipt(actual, request, outcome=outcome)
        )
        selector = {
            "command_id": str(uuid4()),
            "request_digest": reply["request_digest"],
            "receipt_digest": digest,
            "expected_revision": 1,
        }
        imported = actual.service.import_provider_receipt(
            actual.request, reply["request_id"], selector
        )
        assert (
            imported["state"] == "rejected" and imported["consumption_ref"] is not None
        )
        assert imported["consumption_publication_state"] == "pending"
        assert imported["installation_ref"] is None
        actual.context.close()
        assert (
            actual.service.import_provider_receipt(
                actual.request, reply["request_id"], selector
            )
            == imported
        )


def test_pending_cancellation_records_and_replays_without_source(tmp_path, monkeypatch):
    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        reply = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, reply["request_id"]
        )["request"]
        digest = install_receipt(actual, signed_receipt(actual, request))
        selector = {
            "command_id": str(uuid4()),
            "request_digest": reply["request_digest"],
            "receipt_digest": digest,
            "expected_revision": 1,
        }
        actual.service.import_provider_receipt(
            actual.request, reply["request_id"], selector
        )
        actual.context.close()
        cancel = {**selector, "command_id": str(uuid4()), "expected_revision": 2}
        result = actual.service.cancel_provider(
            actual.request, reply["request_id"], cancel
        )
        assert result["state"] == "cancelled" and result["revision"] == 3
        assert result["cancellation_publication_state"] == "pending"
        assert (
            actual.service.cancel_provider(actual.request, reply["request_id"], cancel)
            == result
        )
        assert (
            actual.service.read_provider(actual.read_request, reply["request_id"])[
                "state"
            ]
            == "cancelled"
        )


def test_actual_signed_import_is_pending_without_installation(tmp_path, monkeypatch):
    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        reply = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, reply["request_id"]
        )["request"]
        digest = install_receipt(actual, signed_receipt(actual, request))
        selector = {
            "command_id": str(uuid4()),
            "request_digest": reply["request_digest"],
            "receipt_digest": digest,
            "expected_revision": 1,
        }
        imported = actual.service.import_provider_receipt(
            actual.request, reply["request_id"], selector
        )
        assert imported["state"] == "receipt_pending" and imported["revision"] == 2
        assert imported["receipt"]["receipt_digest"] == digest
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_receipts"
                ).fetchone()[0]
                == 1
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_provider_receipt_sources"
                ).fetchone()[0]
                == 1
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_installations"
                ).fetchone()[0]
                == 0
            )
        actual.context.close()
        assert (
            actual.service.import_provider_receipt(
                actual.request, reply["request_id"], selector
            )
            == imported
        )
        assert actual.service.prepare_provider(actual.request, actual.payload) == reply


def test_existing_provider_replay_needs_no_live_context(tmp_path, monkeypatch):
    with provider_context(tmp_path.resolve(), monkeypatch) as actual:
        reply = actual.service.prepare_provider(actual.request, actual.payload)
        cancel = {
            "command_id": str(uuid4()),
            "request_digest": reply["request_digest"],
            "expected_revision": 1,
        }
        actual.context.close()
        cancelled = actual.service.cancel_provider(
            actual.request, reply["request_id"], cancel
        )
        assert cancelled["state"] == "cancelled"
        assert actual.service.prepare_provider(actual.request, actual.payload) == reply
        assert (
            actual.service.read_provider(actual.read_request, reply["request_id"])[
                "state"
            ]
            == "cancelled"
        )


@pytest.mark.parametrize(
    "checkpoint",
    ["first", "preseal", "pending_reconcile", "pending_cancel", "pending_consume"],
)
def test_exact_expiry_wins_durably_without_live_probe(
    tmp_path, monkeypatch, checkpoint
):
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
        deadline = epoch_ms(request["expires_at"])
        if checkpoint.startswith("pending"):
            actual.service.import_provider_receipt(
                actual.request, prepared["request_id"], value
            )
        if checkpoint == "preseal":
            original = actual.domain.put_blob

            def preseal(*args, **kwargs):
                blob = original(*args, **kwargs)
                monkeypatch.setattr(time, "time_ns", lambda: deadline * 1_000_000)
                return blob

            monkeypatch.setattr(actual.domain, "put_blob", preseal)
        else:
            monkeypatch.setattr(time, "time_ns", lambda: deadline * 1_000_000)
        if checkpoint == "pending_reconcile":
            actual.service.reconcile_startup()
        else:
            operation = (
                actual.service.cancel_provider
                if checkpoint == "pending_cancel"
                else actual.service.consume_provider_receipt
                if checkpoint == "pending_consume"
                else actual.service.import_provider_receipt
            )
            command = (
                {**value, "command_id": str(uuid4()), "expected_revision": 2}
                if checkpoint.startswith("pending")
                else value
            )
            with pytest.raises(DeploymentPrepareError) as caught:
                operation(actual.request, prepared["request_id"], command)
            assert caught.value.code == "conflict"
        current = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )
        assert current["state"] == "expired"
        assert current["revision"] == (3 if checkpoint.startswith("pending") else 2)
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_installations"
                ).fetchone()[0]
                == 0
            )


@pytest.mark.parametrize(
    "operation,target",
    [
        ("import", "context"),
        ("import", "selected"),
        ("import", "candidate_cas"),
        ("import", "managed_inventory"),
        ("consume", "context"),
        ("consume", "candidate_cas"),
    ],
)
def test_final_receipt_writer_rechecks_real_preseal_drift(
    tmp_path, monkeypatch, operation, target
):
    from pathlib import Path
    from contextlib import nullcontext
    from app.tests.provider_receipt_fixture import provider_worker
    from app.operations.setup import parse_base64url_32

    with provider_receipt_context(
        tmp_path.resolve(),
        monkeypatch,
        slot_id=2 if target == "managed_inventory" else 1,
        legacy_staged=target == "managed_inventory",
        defer_legacy_stage=target == "managed_inventory",
    ) as actual:
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
        if operation == "consume":
            actual.service.import_provider_receipt(
                actual.request, prepared["request_id"], value
            )
            value = {**value, "command_id": str(uuid4()), "expected_revision": 2}
        with actual.domain._connection() as db:
            candidate_blob = db.execute(
                "SELECT purpose,sha256 FROM domain_record_blobs WHERE source_kind='extension_manifest' AND source_id=? LIMIT 1",
                (actual.payload["candidate_id"],),
            ).fetchone()
        original = actual.domain.put_blob
        reached = []

        def preseal(raw, **kwargs):
            blob = original(raw, **kwargs)
            if not reached:
                reached.append(target)
                if target == "context":
                    actual.context.close()
                elif target == "selected":
                    selected = actual.tree.actual(
                        Path("/run/deeptwin/provider-deployment-receipts/receipts")
                        / (parse_base64url_32(digest).hex() + ".json")
                    )
                    selected.chmod(0o640)
                elif target == "candidate_cas":
                    selected = (
                        Path(actual.domain.data_dir)
                        / "domain-cas"
                        / candidate_blob[0]
                        / candidate_blob[1]
                    )
                    selected.write_bytes(selected.read_bytes() + b"!")
                else:
                    actual.stage_legacy()
            return blob

        monkeypatch.setattr(actual.domain, "put_blob", preseal)
        method = (
            actual.service.import_provider_receipt
            if operation == "import"
            else actual.service.consume_provider_receipt
        )
        with (
            provider_worker(actual, monkeypatch)
            if operation == "consume"
            else nullcontext()
        ):
            with pytest.raises(DeploymentPrepareError) as caught:
                method(actual.request, prepared["request_id"], value)
        assert reached == [target]
        assert caught.value.code == (
            "unavailable"
            if target == "candidate_cas"
            else "conflict"
            if target == "managed_inventory"
            else "dependency_unavailable"
        )
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_commands WHERE command_id=?",
                    (value["command_id"],),
                ).fetchone()[0]
                == 0
            )
            assert db.execute(
                "SELECT count(*) FROM deployment_prepare_installations"
            ).fetchone()[0] == (target == "managed_inventory")
            assert db.execute(
                "SELECT count(*) FROM deployment_prepare_receipts WHERE request_id=?",
                (prepared["request_id"],),
            ).fetchone()[0] == (operation == "consume")


@pytest.mark.parametrize("same_command", [False, True])
def test_two_real_service_import_race_has_one_winner(
    tmp_path, monkeypatch, same_command
):
    from app.deployment.prepare_service import PersistentDeploymentPrepare

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
        second = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=actual.service._topology,
            exchange_source=actual.service._exchange,
            public_trust_source=actual.service._trust,
            receipt_ingress_source=actual.service._ingress,
            consumption_exchange_source=actual.service._consumption,
            provider_source_context=actual.context,
        )
        winner = {
            **value,
            "command_id": value["command_id"] if same_command else str(uuid4()),
        }
        original = actual.domain.put_blob
        won = []

        def preseal(*args, **kwargs):
            blob = original(*args, **kwargs)
            if not won:
                won.append(None)
                won[0] = second.import_provider_receipt(
                    actual.request, prepared["request_id"], winner
                )
            return blob

        monkeypatch.setattr(actual.domain, "put_blob", preseal)
        if same_command:
            assert (
                actual.service.import_provider_receipt(
                    actual.request, prepared["request_id"], value
                )
                == won[0]
            )
        else:
            with pytest.raises(DeploymentPrepareError) as caught:
                actual.service.import_provider_receipt(
                    actual.request, prepared["request_id"], value
                )
            assert caught.value.code == "conflict"
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_receipts"
                ).fetchone()[0]
                == 1
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_lifecycle"
                ).fetchone()[0]
                == 2
            )


@pytest.mark.parametrize(
    "checkpoint",
    [
        "installation_record",
        "consumption_record",
        "accepted",
        "command",
        "consumptions",
        "installations",
        "installation_heads",
        "final_verify",
    ],
)
def test_each_acceptance_authority_checkpoint_rolls_back(
    tmp_path, monkeypatch, checkpoint
):
    import sqlite3
    from app.tests.provider_receipt_fixture import provider_worker
    from app.deployment import prepare_storage as storage, prepare_records

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
        consume = {**value, "command_id": str(uuid4()), "expected_revision": 2}
        with actual.domain._connection() as db:
            before_events = tuple(
                tuple(row)
                for row in db.execute(
                    "SELECT * FROM api_event_envelopes ORDER BY sequence"
                )
            )
        reached = []
        original_put, original_insert, original_verify = (
            actual.domain._put_in_transaction,
            storage.insert,
            prepare_records.verify,
        )

        def fail():
            reached.append(checkpoint)
            raise sqlite3.OperationalError("synthetic authority checkpoint refusal")

        def put(db, record, *args, **kwargs):
            result = original_put(db, record, *args, **kwargs)
            if (
                checkpoint == "installation_record"
                and record.ref.kind == "extension_installation"
            ) or (
                checkpoint == "consumption_record"
                and record.ref.kind == "deployment_receipt_consumption"
            ):
                fail()
            return result

        def insert(db, table, values):
            result = original_insert(db, table, values)
            if (
                table == checkpoint
                or (checkpoint == "command" and table == "commands")
                or (
                    checkpoint == "accepted"
                    and table == "lifecycle"
                    and values["state"] == "accepted"
                )
            ):
                fail()
            return result

        def verify(domain, db, profile):
            result = original_verify(domain, db, profile)
            if (
                checkpoint == "final_verify"
                and result["requests"][prepared["request_id"]]["history"][-1]["state"]
                == "accepted"
            ):
                fail()
            return result

        with provider_worker(actual, monkeypatch), monkeypatch.context() as fault:
            fault.setattr(actual.domain, "_put_in_transaction", put)
            fault.setattr(storage, "insert", insert)
            fault.setattr(prepare_records, "verify", verify)
            with pytest.raises(DeploymentPrepareError) as caught:
                actual.service.consume_provider_receipt(
                    actual.request, prepared["request_id"], consume
                )
            assert caught.value.code == "unavailable"
        assert reached == [checkpoint]
        with actual.domain._connection() as db:
            assert (
                tuple(
                    tuple(row)
                    for row in db.execute(
                        "SELECT * FROM api_event_envelopes ORDER BY sequence"
                    )
                )
                == before_events
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_installations"
                ).fetchone()[0]
                == 0
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_consumptions"
                ).fetchone()[0]
                == 0
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_commands WHERE command_id=?",
                    (consume["command_id"],),
                ).fetchone()[0]
                == 0
            )
            assert (
                original_verify(actual.domain, db, actual.profile)["requests"][
                    prepared["request_id"]
                ]["history"][-1]["state"]
                == "receipt_pending"
            )


def test_restarted_context_cannot_reenroll_replaced_mutable_receipt_root(
    tmp_path, monkeypatch
):
    from pathlib import Path
    from app.deployment.prepare_service import PersistentDeploymentPrepare
    from app.deployment import provider_stage_observer

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
        imported = actual.service.import_provider_receipt(
            actual.request, prepared["request_id"], value
        )
        actual.context.close()
        root = Path("/run/deeptwin/provider-deployment-receipts")
        path = actual.tree.actual(root)
        path.rename(path.with_name("old-receipt-root"))
        actual.tree.directory(root, 20113, 21201)
        actual.tree.directory(root / "receipts", 20113, 21201)

        def no_probe(**kwargs):
            raise AssertionError("replaced enrolled root reached probe")

        monkeypatch.setattr(
            provider_stage_observer, "observe_provider_stage_postcondition", no_probe
        )
        with actual.tree.open() as restarted_context:
            service = PersistentDeploymentPrepare(
                actual.domain,
                actual.owner,
                actual.registry,
                topology_source=actual.service._topology,
                exchange_source=actual.service._exchange,
                public_trust_source=actual.service._trust,
                receipt_ingress_source=actual.service._ingress,
                consumption_exchange_source=actual.service._consumption,
                provider_source_context=restarted_context,
            )
            assert (
                service.import_provider_receipt(
                    actual.request, prepared["request_id"], value
                )
                == imported
            )
            with pytest.raises(DeploymentPrepareError) as caught:
                service.consume_provider_receipt(
                    actual.request,
                    prepared["request_id"],
                    {**value, "command_id": str(uuid4()), "expected_revision": 2},
                )
            assert caught.value.code == "dependency_unavailable"
            assert (
                service.read_provider(actual.read_request, prepared["request_id"])[
                    "state"
                ]
                == "receipt_pending"
            )
