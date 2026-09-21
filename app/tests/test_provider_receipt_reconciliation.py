"""Actual publication and acknowledgement of committed provider consequences."""

from uuid import uuid4
import pytest
import time
from app.deployment.prepare_contracts import epoch_ms
from app.tests.provider_receipt_fixture import (
    provider_receipt_context,
    signed_receipt,
    install_receipt,
)
from app.tests.test_provider_publication import final_path


@pytest.mark.parametrize("fault", ["deadline", "control_cleanup"])
def test_consumed_reconcile_deadline_and_primary_finalizer(
    tmp_path, monkeypatch, fault
):
    from app.deployment import publication, provider_receipt_service
    from app.deployment.provider_receipt_sources import ProviderReceiptChannels
    from pathlib import Path

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        digest = install_receipt(
            actual, signed_receipt(actual, request, outcome="failed")
        )
        value = {
            "command_id": str(uuid4()),
            "request_digest": prepared["request_digest"],
            "receipt_digest": digest,
            "expected_revision": 1,
        }

        def unavailable(*args, **kwargs):
            raise OSError("bounded synthetic publication outage")

        with monkeypatch.context() as outage:
            outage.setattr(publication, "_stage_payload", unavailable)
            actual.service.import_provider_receipt(
                actual.request, prepared["request_id"], value
            )
        namespace = actual.tree.actual(
            Path("/run/deeptwin/provider-deployment-consumed/consumed")
        )
        baseline = set(actual.tree.live)
        if fault == "deadline":
            actual.service._provider_reconcile_deadline = 0
            provider_receipt_service.reconcile_consumed(
                actual.service, prepared["request_id"]
            )
            assert not tuple(namespace.glob("*.json"))
            assert (
                actual.service.read_provider(
                    actual.read_request, prepared["request_id"]
                )["consumption_publication_state"]
                == "pending"
            )
        else:
            primary = KeyboardInterrupt(
                "actual committed final then primary interruption"
            )
            original_commit, original_close, original_journal = (
                publication._commit_stage,
                ProviderReceiptChannels.close,
                actual.service._journal,
            )
            state = {"primary": False, "closed": False, "journal_after_primary": False}

            def commit(*args, **kwargs):
                original_commit(*args, **kwargs)
                state["primary"] = True
                raise primary

            def close(owner):
                original_close(owner)
                state["closed"] = True
                raise OSError("secondary owned channel close failure")

            def journal(*args, **kwargs):
                state["journal_after_primary"] |= state["primary"]
                return original_journal(*args, **kwargs)

            with monkeypatch.context() as negative:
                # Reach the real fault checkpoint independently of host throughput.
                from types import SimpleNamespace
                from app.deployment import prepare_service

                sampled = time.monotonic()
                clock = SimpleNamespace(monotonic=lambda: sampled, time_ns=time.time_ns)
                negative.setattr(prepare_service, "time", clock)
                negative.setattr(provider_receipt_service, "time", clock)
                negative.setattr(publication, "_commit_stage", commit)
                negative.setattr(ProviderReceiptChannels, "close", close)
                negative.setattr(actual.service, "_journal", journal)
                with pytest.raises(KeyboardInterrupt) as caught:
                    actual.service.reconcile_startup()
                assert caught.value is primary
            assert state == {
                "primary": True,
                "closed": True,
                "journal_after_primary": False,
            }
            assert tuple(namespace.glob("*.json"))
        assert set(actual.tree.live) == baseline
        assert actual.context.read_current() == actual.tree.bundle
        actual.service.reconcile_startup()
        assert (
            actual.service.read_provider(actual.read_request, prepared["request_id"])[
                "consumption_publication_state"
            ]
            == "published"
        )


def test_pending_receipt_cancel_publishes_exact_v2_bytes(tmp_path, monkeypatch):
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
        result = actual.service.cancel_provider(
            actual.request,
            prepared["request_id"],
            {**value, "command_id": str(uuid4()), "expected_revision": 2},
        )
        current = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )
        assert current["cancellation_publication_state"] == "published"
        with actual.domain._connection() as db:
            item = actual.service._journal(db)["requests"][prepared["request_id"]]
        from app.deployment.provider_receipt_lifecycle import cancellation_payload

        assert final_path(
            actual.tree, "cancel", prepared["request_digest"]
        ).read_bytes() == cancellation_payload(item, profile=actual.profile)
        assert result["cancellation_publication_state"] == "pending"


@pytest.mark.parametrize("fault", ["stage", "commit", "fsync", "postcheck"])
def test_consumed_native_crash_window_recovers_exact_final_without_second_event(
    tmp_path, monkeypatch, fault
):
    from app.deployment import publication
    from app.deployment.provider_receipt_sources import ProviderReceiptChannels

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        digest = install_receipt(
            actual, signed_receipt(actual, request, outcome="failed")
        )
        value = {
            "command_id": str(uuid4()),
            "request_digest": prepared["request_digest"],
            "receipt_digest": digest,
            "expected_revision": 1,
        }
        reached = []
        attribute = (
            "_stage_payload"
            if fault == "stage"
            else "_commit_stage"
            if fault == "commit"
            else "_existing_for_policy"
            if fault == "fsync"
            else "_require_consumed"
        )
        original = getattr(publication, attribute, None)
        if fault == "postcheck":
            original = ProviderReceiptChannels.publish_consumed
            target = ProviderReceiptChannels
            attribute = "publish_consumed"
        else:
            target = publication

        def refuse(*args, **kwargs):
            result = original(*args, **kwargs)
            reached.append(fault)
            if fault == "stage":
                result.close()
            raise OSError("synthetic native projection checkpoint")

        with monkeypatch.context() as negative:
            negative.setattr(target, attribute, refuse)
            imported = actual.service.import_provider_receipt(
                actual.request, prepared["request_id"], value
            )
        assert reached
        assert (
            actual.service.read_provider(actual.read_request, prepared["request_id"])[
                "consumption_publication_state"
            ]
            == "pending"
        )
        with actual.domain._connection() as db:
            events = tuple(
                tuple(row)
                for row in db.execute(
                    "SELECT * FROM api_event_envelopes ORDER BY sequence"
                )
            )
        actual.service.reconcile_startup()
        current = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )
        assert current["consumption_publication_state"] == "published"
        assert (
            actual.service.import_provider_receipt(
                actual.request, prepared["request_id"], value
            )
            == imported
        )
        with actual.domain._connection() as db:
            assert (
                tuple(
                    tuple(row)
                    for row in db.execute(
                        "SELECT * FROM api_event_envelopes ORDER BY sequence"
                    )
                )
                == events
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_consumptions"
                ).fetchone()[0]
                == 1
            )


def test_v2_cancel_committed_before_expiry_publishes_after_expiry(
    tmp_path, monkeypatch
):
    from app.deployment import provider_publication
    from app.deployment.contracts import DeploymentSourceError

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

        def unavailable(*args, **kwargs):
            raise DeploymentSourceError()

        with monkeypatch.context() as outage:
            outage.setattr(
                provider_publication, "open_provider_outbox_lease", unavailable
            )
            result = actual.service.cancel_provider(
                actual.request,
                prepared["request_id"],
                {**value, "command_id": str(uuid4()), "expected_revision": 2},
            )
        assert (
            actual.service.read_provider(actual.read_request, prepared["request_id"])[
                "cancellation_publication_state"
            ]
            == "pending"
        )
        monkeypatch.setattr(
            time, "time_ns", lambda: (epoch_ms(request["expires_at"]) + 1) * 1_000_000
        )
        actual.service.reconcile_startup()
        assert (
            actual.service.read_provider(actual.read_request, prepared["request_id"])[
                "cancellation_publication_state"
            ]
            == "published"
        )
        assert result["cancellation_publication_state"] == "pending"


def test_pending_cancel_publisher_requires_exact_signed_receipt_bijection_before_own_fds(
    tmp_path, monkeypatch
):
    from app.deployment.provider_publication import open_provider_outbox_lease
    from app.deployment.provider_receipt_lifecycle import cancellation_payload
    from app.deployment.contracts import DeploymentSourceError
    from app.deployment.receipt_contracts import ReceiptWireError

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        raw = signed_receipt(actual, request)
        digest = install_receipt(actual, raw)
        value = {
            "command_id": str(uuid4()),
            "request_digest": prepared["request_digest"],
            "receipt_digest": digest,
            "expected_revision": 1,
        }
        actual.service.import_provider_receipt(
            actual.request, prepared["request_id"], value
        )
        actual.service.cancel_provider(
            actual.request,
            prepared["request_id"],
            {**value, "command_id": str(uuid4()), "expected_revision": 2},
        )
        with actual.domain._connection() as db:
            item = actual.service._journal(db)["requests"][prepared["request_id"]]
        pairs = (
            ("request", item["raw"]),
            ("cancel", cancellation_payload(item, profile=actual.profile)),
        )
        baseline = set(actual.tree.live)
        for receipts in (
            (),
            (raw, raw),
            (raw + b" ",),
            (b"x" * 16385,),
            tuple(raw for _ in range(17)),
        ):
            with pytest.raises((DeploymentSourceError, ReceiptWireError)):
                open_provider_outbox_lease(
                    actual.context,
                    profile=actual.profile,
                    expected_payloads=pairs,
                    expected_receipts=receipts,
                )
            assert set(actual.tree.live) == baseline


def test_original_cancel_noncanonical_bytes_keep_source_error_partition(
    tmp_path, monkeypatch
):
    from app.deployment.provider_publication import open_provider_outbox_lease
    from app.deployment.provider_prepare_contracts import make_provider_cancellation
    from app.deployment.contracts import DeploymentSourceError

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        with actual.domain._connection() as db:
            item = actual.service._journal(db)["requests"][prepared["request_id"]]
        marker = make_provider_cancellation(
            item["raw"], profile=actual.profile, cancelled_ms=item["row"]["created_ms"]
        )
        with pytest.raises(DeploymentSourceError):
            open_provider_outbox_lease(
                actual.context,
                profile=actual.profile,
                expected_payloads=(("request", item["raw"]), ("cancel", marker + b" ")),
            )
