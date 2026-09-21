"""Verified owner intents reach the accepted real publisher in controlled trees."""

import sqlite3
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.deployment import contracts as sources
from app.deployment import prepare_storage as storage
from app.deployment import provider_publication as publisher
from app.deployment.prepare_contracts import epoch_ms
from app.deployment.prepare_service import PersistentDeploymentPrepare
from app.domain.refs import canonical_json
from app.tests.provider_prepare_fixture import provider_context
from app.tests.test_provider_prepare_service import borrowed_service
from app.tests.test_provider_publication import final_path


@pytest.mark.parametrize("capacity", [2, 16])
def test_prepare_publishes_exact_retained_bytes_and_cancel_publishes_marker(
    tmp_path, monkeypatch, capacity
):
    with provider_context(tmp_path, monkeypatch, capacity=capacity) as actual:
        if capacity == 16:
            # Deterministic cooperative clock for resource/namespace coverage only;
            # this is not a native or one-second throughput qualification.
            from app.deployment import prepare_service, provider_prepare_service

            sampled = time.monotonic()
            clock = SimpleNamespace(monotonic=lambda: sampled, time_ns=time.time_ns)
            monkeypatch.setattr(prepare_service, "time", clock)
            monkeypatch.setattr(provider_prepare_service, "time", clock)
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        current = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )
        target = final_path(actual.tree, "request", prepared["request_digest"])
        assert target.is_file()
        assert target.read_bytes() == canonical_json(current["request"])
        assert current["publication_state"] == "published"
        value = {
            "command_id": str(uuid4()),
            "request_digest": prepared["request_digest"],
            "expected_revision": 1,
        }
        cancelled = actual.service.cancel_provider(
            actual.request, prepared["request_id"], value
        )
        assert cancelled["state"] == "cancelled"
        assert cancelled["cancellation_publication_state"] == "pending"
        assert final_path(actual.tree, "cancel", prepared["request_digest"]).is_file()
        assert (
            actual.service.read_provider(actual.read_request, prepared["request_id"])[
                "cancellation_publication_state"
            ]
            == "published"
        )
        assert actual.tree.peak - actual.tree.caller_baseline <= 256
        assert actual.tree.source_open_count == 1
        print(
            f"provider FD measurement: caller startup baseline={actual.tree.caller_baseline}, "
            f"context retained={actual.tree.provider_retained}, observed total peak={actual.tree.peak}, "
            f"combined additional upper bound={actual.tree.peak - actual.tree.caller_baseline}"
        )


def test_file_visible_before_db_rollback_is_observed_without_republication(
    tmp_path, monkeypatch
):
    with provider_context(tmp_path, monkeypatch) as actual:
        advance = storage.advance

        def fail_ack(db, table, old, changes):
            result = advance(db, table, old, changes)
            if table == "outbox" and changes["state"] == "published":
                raise sqlite3.OperationalError("injected ack rollback")
            return result

        with monkeypatch.context() as fault:
            fault.setattr(storage, "advance", fail_ack)
            prepared = actual.service.prepare_provider(actual.request, actual.payload)
        target = final_path(actual.tree, "request", prepared["request_digest"])
        assert target.is_file()
        original_inode = target.stat().st_ino
        opened = borrowed_service(actual)
        assert (
            opened.read_provider(actual.read_request, prepared["request_id"])[
                "publication_state"
            ]
            == "pending"
        )
        with monkeypatch.context() as guard:
            guard.setattr(
                publisher.ProviderOutboxLease,
                "stage",
                lambda *a, **kw: pytest.fail("existing exact final was staged twice"),
            )
            opened.reconcile_startup()
        assert target.stat().st_ino == original_inode
        assert (
            opened.read_provider(actual.read_request, prepared["request_id"])[
                "publication_state"
            ]
            == "published"
        )
        assert opened.prepare_provider(actual.request, actual.payload) == prepared


@pytest.mark.parametrize("checkpoint", ["stage", "ack", "exposed_source_failure"])
def test_deadline_and_exposure_checkpoints_preserve_honest_publication_state(
    tmp_path, monkeypatch, checkpoint
):
    with provider_context(tmp_path, monkeypatch) as actual:
        method = "stage" if checkpoint == "stage" else "commit"
        original = getattr(publisher.ProviderOutboxLease, method)

        def cross_deadline(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            # Read committed request directly through the genuine owner journal.
            with actual.domain._connection() as db:
                deadline = db.execute(
                    "SELECT expires_ms FROM deployment_prepare_requests"
                ).fetchone()[0]
            monkeypatch.setattr(time, "time_ns", lambda: deadline * 1000000)
            if checkpoint == "exposed_source_failure":
                actual.context.close()
                raise sources.DeploymentSourceError()
            return result

        monkeypatch.setattr(publisher.ProviderOutboxLease, method, cross_deadline)
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        current = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )
        assert current["state"] == "expired" and current["revision"] == 2
        assert current["publication_state"] == (
            "published" if checkpoint == "ack" else "suppressed"
        )
        assert final_path(
            actual.tree, "request", prepared["request_digest"]
        ).exists() == (checkpoint != "stage")
        assert not final_path(
            actual.tree, "cancel", prepared["request_digest"]
        ).exists()
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_commands"
                ).fetchone()[0]
                == 1
            )
        assert (
            actual.service.prepare_provider(actual.request, actual.payload) == prepared
        )


def test_committed_cancellation_can_publish_after_request_deadline(
    tmp_path, monkeypatch
):
    with provider_context(tmp_path, monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        source_less = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=None,
            exchange_source=None,
        )
        cancelled = source_less.cancel_provider(
            actual.request,
            prepared["request_id"],
            {
                "command_id": str(uuid4()),
                "request_digest": prepared["request_digest"],
                "expected_revision": 1,
            },
        )
        assert cancelled["cancellation_publication_state"] == "pending"
        current = source_less.read_provider(actual.read_request, prepared["request_id"])
        deadline = epoch_ms(current["request"]["expires_at"])
        monkeypatch.setattr(time, "time_ns", lambda: (deadline + 1) * 1000000)
        actual.service.reconcile_startup()
        assert final_path(actual.tree, "cancel", prepared["request_digest"]).is_file()
        assert (
            actual.service.read_provider(actual.read_request, prepared["request_id"])[
                "state"
            ]
            == "cancelled"
        )


def test_deadline_early_return_reverifies_whole_journal_before_commit(
    tmp_path, monkeypatch
):
    with provider_context(tmp_path, monkeypatch) as actual:
        verified_states = []
        original_journal = actual.service._journal

        def verified(db):
            result = original_journal(db)
            verified_states.extend(
                item["history"][-1]["state"] for item in result["requests"].values()
            )
            return result

        original_stage = publisher.ProviderOutboxLease.stage

        def expire_after_stage(self, *args, **kwargs):
            result = original_stage(self, *args, **kwargs)
            with actual.domain._connection() as db:
                deadline = db.execute(
                    "SELECT expires_ms FROM deployment_prepare_requests"
                ).fetchone()[0]
            monkeypatch.setattr(time, "time_ns", lambda: deadline * 1000000)
            return result

        monkeypatch.setattr(actual.service, "_journal", verified)
        monkeypatch.setattr(publisher.ProviderOutboxLease, "stage", expire_after_stage)
        actual.service.prepare_provider(actual.request, actual.payload)
        assert verified_states[-1] == "expired"


@pytest.mark.parametrize("mutation", ["missing", "wrong_bytes", "unknown"])
def test_untrusted_outgoing_final_prevents_new_marker_without_poisoning_history(
    tmp_path, monkeypatch, mutation
):
    with provider_context(tmp_path, monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        target = final_path(actual.tree, "request", prepared["request_digest"])
        if mutation == "missing":
            target.unlink()
        elif mutation == "wrong_bytes":
            target.chmod(0o640)
            target.write_bytes(b"wrong")
            target.chmod(0o440)
        else:
            actual.tree.payload("requests", 97, raw=b"unknown")
        value = {
            "command_id": str(uuid4()),
            "request_digest": prepared["request_digest"],
            "expected_revision": 1,
        }
        actual.service.cancel_provider(actual.request, prepared["request_id"], value)
        current = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )
        assert (
            current["state"] == "cancelled"
            and current["cancellation_publication_state"] == "pending"
        )
        assert not final_path(
            actual.tree, "cancel", prepared["request_digest"]
        ).exists()
        assert not actual.service._unavailable


def test_provider_source_refusal_allows_old_cancellation_progress_and_opaque_incoming(
    tmp_path, monkeypatch
):
    from app.tests.deployment_prepare_fixture import register_variant

    with provider_context(tmp_path, monkeypatch) as actual:
        provider_request = actual.service.prepare_provider(
            actual.request, actual.payload
        )
        actual.output = actual.tree.old.prepare_artifacts
        old_payload = register_variant(actual, extension_id="later-old-tool", slot_id=2)
        old_payload.pop("source_context_sha256")
        old = actual.service.prepare(actual.request, old_payload)
        source_less = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=None,
            exchange_source=None,
        )
        for receipt, cancel in (
            (old, source_less.cancel),
            (provider_request, source_less.cancel_provider),
        ):
            cancel(
                actual.request,
                receipt["request_id"],
                {
                    "command_id": str(uuid4()),
                    "request_digest": receipt["request_digest"],
                    "expected_revision": 1,
                },
            )
        opaque = actual.tree.payload("receipts", 9, raw=b"opaque incoming bytes")
        incoming = opaque.read_bytes()
        actual.context.close()
        actual.service.reconcile_startup()
        assert not actual.service._unavailable
        assert (
            actual.service.read(actual.read_request, old["request_id"])[
                "cancellation_publication_state"
            ]
            == "published"
        )
        assert (
            actual.service.read_provider(
                actual.read_request, provider_request["request_id"]
            )["cancellation_publication_state"]
            == "pending"
        )
        assert opaque.read_bytes() == incoming


def test_real_stage_process_exception_closes_all_owned_handles_and_preserves_primary(
    tmp_path, monkeypatch
):
    from app.deployment.sources import SlotMetadataLease

    with provider_context(tmp_path, monkeypatch) as actual:
        retained = set(actual.tree.live)
        primary = SystemExit("injected after real stage")
        original_stage = publisher.ProviderOutboxLease.stage
        original_close = publisher.ProviderOutboxLease.close
        original_slot_close = SlotMetadataLease.close
        closed_slots = []

        def stage_then_interrupt(self, *args, **kwargs):
            original_stage(self, *args, **kwargs)
            raise primary

        def close_then_interrupt(self):
            original_close(self)
            raise KeyboardInterrupt("secondary cleanup failure")

        def close_slot(self):
            original_slot_close(self)
            closed_slots.append(self)

        monkeypatch.setattr(
            publisher.ProviderOutboxLease, "stage", stage_then_interrupt
        )
        monkeypatch.setattr(
            publisher.ProviderOutboxLease, "close", close_then_interrupt
        )
        monkeypatch.setattr(SlotMetadataLease, "close", close_slot)
        with pytest.raises(SystemExit) as caught:
            actual.service.prepare_provider(actual.request, actual.payload)
        assert caught.value is primary and len(closed_slots) >= 2
        assert set(actual.tree.live) == retained
        assert actual.context.read_current() == actual.tree.bundle
        with actual.domain._connection() as db:
            row = db.execute("SELECT state FROM deployment_prepare_outbox").fetchone()
            assert row[0] == "pending"


@pytest.mark.parametrize("finalizer", ["floor", "select"])
@pytest.mark.parametrize("interruption", [SystemExit, KeyboardInterrupt])
def test_stage_primary_survives_secondary_finalizer_database_failure(
    tmp_path, monkeypatch, finalizer, interruption
):
    from contextlib import contextmanager

    with provider_context(tmp_path.resolve(), monkeypatch) as actual:
        retained = set(actual.tree.live)
        primary = interruption("retained stage interruption")
        checkpoints, writers = [], []
        stage = publisher.ProviderOutboxLease.stage
        floor = actual.service._floor
        connection = actual.domain._connection

        @contextmanager
        def actual_connection(*args, **kwargs):
            with connection(*args, **kwargs) as db:
                if kwargs.get("write"):
                    writers.append(db)
                try:
                    yield db
                finally:
                    if kwargs.get("write"):
                        writers.pop()

        def interrupted_stage(self, *args, **kwargs):
            stage(self, *args, **kwargs)
            checkpoints.append("stage")
            if finalizer == "select":

                def deny_select(action, *args):
                    if action == sqlite3.SQLITE_SELECT:
                        checkpoints.append("secondary select")
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK

                writers[-1].set_authorizer(deny_select)
            raise primary

        def failing_floor(*args, **kwargs):
            if finalizer == "floor" and checkpoints:
                checkpoints.append("secondary floor")
                raise sqlite3.OperationalError("secondary finalizer failure")
            return floor(*args, **kwargs)

        monkeypatch.setattr(actual.domain, "_connection", actual_connection)
        monkeypatch.setattr(publisher.ProviderOutboxLease, "stage", interrupted_stage)
        monkeypatch.setattr(actual.service, "_floor", failing_floor)
        with pytest.raises(interruption) as caught:
            try:
                actual.service.prepare_provider(actual.request, actual.payload)
            finally:
                print("finalizer checkpoints", finalizer, checkpoints)
        assert caught.value is primary
        assert checkpoints == ["stage"]
        assert not actual.service._unavailable
        assert set(actual.tree.live) == retained
        assert actual.context.read_current() == actual.tree.bundle
        with actual.domain._connection() as db:
            row = db.execute("SELECT state FROM deployment_prepare_outbox").fetchone()
            assert row[0] == "pending"


def test_cooperative_budget_exhausted_after_stage_leaves_pending_without_rename(
    tmp_path, monkeypatch
):
    from app.deployment import prepare_service, provider_prepare_service

    with provider_context(tmp_path, monkeypatch) as actual:
        monotonic = [100.0]
        clock = SimpleNamespace(monotonic=lambda: monotonic[0], time_ns=time.time_ns)
        monkeypatch.setattr(prepare_service, "time", clock)
        monkeypatch.setattr(provider_prepare_service, "time", clock)
        stage = publisher.ProviderOutboxLease.stage

        def exhausted(self, *args, **kwargs):
            result = stage(self, *args, **kwargs)
            monotonic[0] += 2
            return result

        monkeypatch.setattr(publisher.ProviderOutboxLease, "stage", exhausted)
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        assert not actual.service._unavailable
        current = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )
        assert (
            current["state"] == "prepared" and current["publication_state"] == "pending"
        )
        assert not final_path(
            actual.tree, "request", prepared["request_digest"]
        ).exists()
