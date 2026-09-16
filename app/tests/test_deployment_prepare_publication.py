"""Committed intent, actual retained FDs, and controlled no-clobber syscalls."""

from base64 import urlsafe_b64decode
from uuid import uuid4

import pytest

from app.domain.refs import canonical_json
from app.tests.deployment_prepare_fixture import service_context
from app.tests.test_deployment_publication import syscall_fixture


def final_path(actual, receipt, role="requests"):
    return actual.actual.actual(actual.actual.c.OUTBOX_ROOT / role) / (
        urlsafe_b64decode(receipt["request_digest"] + "=").hex() + ".json"
    )


def test_successful_mutation_publishes_exact_committed_bytes_but_receipt_stays_pending(
    tmp_path, monkeypatch
):
    syscall_fixture(monkeypatch)
    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        current = actual.service.read(actual.read_request, receipt["request_id"])
        assert receipt["publication_state"] == "pending"
        assert current["publication_state"] == "published"
        assert final_path(actual, receipt).read_bytes() == canonical_json(
            current["request"]
        )
        assert actual.service.prepare(actual.request, actual.payload) == receipt


def test_cancel_first_suppresses_request_and_recovers_cancel_with_only_retained_exchange(
    tmp_path, monkeypatch
):
    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        actual.topology.close()
        syscall_fixture(monkeypatch)
        cancelled = actual.service.cancel(
            actual.request,
            receipt["request_id"],
            {
                "command_id": str(uuid4()),
                "request_digest": receipt["request_digest"],
                "expected_revision": 1,
            },
        )
        assert cancelled["publication_state"] == "suppressed"
        current = actual.service.read(actual.read_request, receipt["request_id"])
        assert current["cancellation_publication_state"] == "published"
        assert final_path(actual, receipt, "cancelled").exists()
        assert not final_path(actual, receipt).exists()
        actual.service.reconcile_startup()
        assert not final_path(actual, receipt).exists()


def test_explicit_reconcile_recovers_pending_without_changing_frozen_command(
    tmp_path, monkeypatch
):
    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        assert (
            actual.service.read(actual.read_request, receipt["request_id"])[
                "publication_state"
            ]
            == "pending"
        )
        syscall_fixture(monkeypatch)
        assert actual.service.reconcile_startup() is None
        assert final_path(actual, receipt).exists()
        assert (
            actual.service.read(actual.read_request, receipt["request_id"])[
                "publication_state"
            ]
            == "published"
        )
        assert actual.service.prepare(actual.request, actual.payload) == receipt


@pytest.mark.parametrize("cancel_after_crash", [False, True])
def test_file_visible_before_failed_ack_recovers_exact_bytes_or_suppresses(
    tmp_path, monkeypatch, cancel_after_crash
):
    import sqlite3

    from app.deployment import prepare_storage
    from app.deployment.prepare_service import PersistentDeploymentPrepare

    syscall_fixture(monkeypatch)
    with service_context(tmp_path, monkeypatch) as actual:
        original = prepare_storage.advance

        def fail_ack(db, table, old, changes):
            if table == "outbox" and changes["state"] == "published":
                raise sqlite3.OperationalError("private nonce/path canary")
            return original(db, table, old, changes)

        monkeypatch.setattr(prepare_storage, "advance", fail_ack)
        receipt = actual.service.prepare(actual.request, actual.payload)
        assert (
            receipt["state"] == "prepared" and receipt["publication_state"] == "pending"
        )
        path = final_path(actual, receipt)
        before = path.read_bytes()
        monkeypatch.setattr(prepare_storage, "advance", original)
        reopened = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=actual.topology,
            exchange_source=actual.exchange,
        )
        assert (
            reopened.read(actual.read_request, receipt["request_id"])[
                "publication_state"
            ]
            == "pending"
        )
        if cancel_after_crash:
            result = reopened.cancel(
                actual.request,
                receipt["request_id"],
                {
                    "command_id": str(uuid4()),
                    "request_digest": receipt["request_digest"],
                    "expected_revision": 1,
                },
            )
            assert result["publication_state"] == "suppressed"
        else:
            reopened.reconcile_startup()
            assert (
                reopened.read(actual.read_request, receipt["request_id"])[
                    "publication_state"
                ]
                == "published"
            )
        assert path.read_bytes() == before
        assert reopened.prepare(actual.request, actual.payload) == receipt


def test_publisher_holds_same_writer_until_ack_so_cancel_cannot_interleave(
    tmp_path, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.deployment.prepare_service import PersistentDeploymentPrepare

    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        second = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=actual.topology,
            exchange_source=actual.exchange,
        )
        publication = syscall_fixture(monkeypatch)
        original = publication._rename_noreplace
        entered, release, attempted = Event(), Event(), Event()

        def held(fd, stage, final):
            entered.set()
            assert release.wait(5)
            original(fd, stage, final)

        def cancel():
            attempted.set()
            return second.cancel(
                actual.request,
                receipt["request_id"],
                {
                    "command_id": str(uuid4()),
                    "request_digest": receipt["request_digest"],
                    "expected_revision": 1,
                },
            )

        monkeypatch.setattr(publication, "_rename_noreplace", held)
        with ThreadPoolExecutor(max_workers=2) as pool:
            publishing = pool.submit(actual.service.reconcile_startup)
            assert entered.wait(5)
            cancelling = pool.submit(cancel)
            assert attempted.wait(5)
            assert not cancelling.done()
            release.set()
            publishing.result(timeout=10)
            cancelled = cancelling.result(timeout=10)
        assert cancelled["publication_state"] == "published"
        assert final_path(actual, receipt).exists()


def test_new_exchange_namespace_identity_never_reenrolls_old_pending_work(
    tmp_path, monkeypatch
):
    from app.deployment.prepare_service import PersistentDeploymentPrepare

    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        actual.exchange.close()
        directory = actual.actual.actual(actual.actual.c.OUTBOX_ROOT / "requests")
        directory.rename(directory.with_name("prior-requests"))
        directory.mkdir(mode=0o750)
        actual.actual.register(directory, 20102, 21201)
        # The root must again have exactly its two namespaces; keep old bytes elsewhere.
        directory.with_name("prior-requests").rename(
            actual.actual.base / "retained-prior-requests"
        )
        from app.deployment.sources import open_exchange_source
        from app.domain.refs import parse_canonical

        pins = parse_canonical(actual.output.pins_bytes)
        with open_exchange_source(
            profile=actual.profile,
            recipe_sha256=pins["recipe_sha256"],
            instance_sha256=pins["instance_sha256"],
            exchange_sha256=pins["exchange_sha256"],
            protected_roots=(),
        ) as exchange:
            reopened = PersistentDeploymentPrepare(
                actual.domain,
                actual.owner,
                actual.registry,
                topology_source=None,
                exchange_source=exchange,
            )
            syscall_fixture(monkeypatch)
            cancelled = reopened.cancel(
                actual.request,
                receipt["request_id"],
                {
                    "command_id": str(uuid4()),
                    "request_digest": receipt["request_digest"],
                    "expected_revision": 1,
                },
            )
            assert cancelled["state"] == "cancelled"
            assert (
                reopened.read(actual.read_request, receipt["request_id"])[
                    "cancellation_publication_state"
                ]
                == "pending"
            )
            assert not final_path(actual, receipt, "cancelled").exists()


def test_long_io_ack_can_follow_expiry_and_startup_then_materializes_expiry(
    tmp_path, monkeypatch
):
    import time

    from app.deployment.prepare_contracts import epoch_ms

    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        request = actual.service.read(actual.read_request, receipt["request_id"])[
            "request"
        ]
        deadline = epoch_ms(request["expires_at"])
        publication = syscall_fixture(monkeypatch)
        original = publication._rename_noreplace

        def slow(fd, stage, final):
            original(fd, stage, final)
            monkeypatch.setattr(time, "time_ns", lambda: (deadline + 1000) * 1000000)

        monkeypatch.setattr(publication, "_rename_noreplace", slow)
        actual.service.reconcile_startup()
        assert (
            actual.service.read(actual.read_request, receipt["request_id"])[
                "publication_state"
            ]
            == "published"
        )
        actual.service.reconcile_startup()
        assert (
            actual.service.read(actual.read_request, receipt["request_id"])["state"]
            == "expired"
        )


def test_read_replay_and_constructor_never_publish_pending_work(tmp_path, monkeypatch):
    from app.deployment.prepare_service import PersistentDeploymentPrepare

    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        syscall_fixture(monkeypatch)
        reopened = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=actual.topology,
            exchange_source=actual.exchange,
        )
        assert not final_path(actual, receipt).exists()
        assert (
            reopened.read(actual.read_request, receipt["request_id"])[
                "publication_state"
            ]
            == "pending"
        )
        assert reopened.prepare(actual.request, actual.payload) == receipt
        assert not final_path(actual, receipt).exists()


def test_post_commit_checkpoint_storage_failure_preserves_frozen_success(
    tmp_path, monkeypatch
):
    from app.deployment import prepare_storage
    from app.domain.store import StorageError

    with service_context(tmp_path, monkeypatch) as actual:
        original = prepare_storage.advance

        def fail_completion_checkpoint(db, table, old, changes):
            if (
                table == "control"
                and db.execute(
                    "SELECT 1 FROM deployment_prepare_commands LIMIT 1"
                ).fetchone()
            ):
                raise StorageError("private-state-canary")
            return original(db, table, old, changes)

        monkeypatch.setattr(prepare_storage, "advance", fail_completion_checkpoint)
        receipt = actual.service.prepare(actual.request, actual.payload)
        assert (
            receipt["state"] == "prepared" and receipt["publication_state"] == "pending"
        )
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_requests"
                ).fetchone()[0]
                == 1
            )


def test_cold_owner_domain_reopen_with_only_same_exchange_preserves_replay_and_cancel(
    tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient

    from app.deployment.prepare_service import PersistentDeploymentPrepare
    from app.deployment.sources import open_exchange_source
    from app.domain.refs import parse_canonical
    from app.server import create_app
    from app.tests.test_web_owner_integration import headers

    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        saved = dict(actual.client.cookies)
        original_owner, original_domain = actual.owner, actual.domain
    app = create_app(tmp_path / "data", **actual.arguments)
    pins = parse_canonical(actual.output.pins_bytes)
    with (
        TestClient(app, base_url=actual.profile.http_origin) as client,
        open_exchange_source(
            profile=actual.profile,
            recipe_sha256=pins["recipe_sha256"],
            instance_sha256=pins["instance_sha256"],
            exchange_sha256=pins["exchange_sha256"],
            protected_roots=(),
        ) as exchange,
    ):
        client.cookies.update(saved)
        csrf = client.get(
            actual.profile.base_path + "session", headers=headers(actual.profile)
        ).json()["csrf_token"]
        owner = app.state.owner_authority
        request = owner.authenticate_request(
            method="POST",
            host=actual.request.host,
            origin=actual.request.origin,
            sec_fetch_site="same-origin",
            cookie_header="; ".join(k + "=" + v for k, v in client.cookies.items()),
            csrf_token=csrf,
        )
        service = PersistentDeploymentPrepare(
            app.state.domain_store,
            owner,
            app.state.first_party_exports["extension-candidates.registry"],
            topology_source=None,
            exchange_source=exchange,
        )
        assert (
            owner is not original_owner
            and app.state.domain_store is not original_domain
        )
        assert service.prepare(request, actual.payload) == receipt
        syscall_fixture(monkeypatch)
        cancelled = service.cancel(
            request,
            receipt["request_id"],
            {
                "command_id": str(uuid4()),
                "request_digest": receipt["request_digest"],
                "expected_revision": 1,
            },
        )
        assert cancelled["state"] == "cancelled"
        assert final_path(actual, receipt, "cancelled").exists()


def test_ineligible_published_request_does_not_consume_budget_ahead_of_due_expiry(
    tmp_path, monkeypatch
):
    import time
    from types import SimpleNamespace

    from app.deployment import prepare_service
    from app.deployment.prepare_contracts import epoch_ms
    from app.tests.deployment_prepare_fixture import register_variant

    syscall_fixture(monkeypatch)
    with service_context(tmp_path, monkeypatch, capacity=2) as actual:
        first = actual.service.prepare(
            actual.request, {**actual.payload, "expires_in_seconds": 120}
        )
        second = actual.service.prepare(
            actual.request,
            register_variant(actual, extension_id="second-tool", slot_id=2),
        )
        assert (
            actual.service.read(actual.read_request, first["request_id"])[
                "publication_state"
            ]
            == "published"
        )
        deadline = epoch_ms(
            actual.service.read(actual.read_request, second["request_id"])["request"][
                "expires_at"
            ]
        )
        monkeypatch.setattr(time, "time_ns", lambda: deadline * 1000000)
        observations = iter((0.0, 0.1, 1.0))
        monkeypatch.setattr(
            prepare_service,
            "time",
            SimpleNamespace(monotonic=lambda: next(observations)),
        )
        actual.service.reconcile_startup()
        assert (
            actual.service.read(actual.read_request, second["request_id"])["state"]
            == "expired"
        )


def test_smaller_replacement_topology_blocks_request_projection_but_keeps_read_and_cancel(
    tmp_path, monkeypatch
):
    from app.deployment.prepare_service import PersistentDeploymentPrepare
    from app.deployment.render import render_prepare_sources
    from app.deployment.sources import open_topology_source
    from app.domain.refs import parse_canonical
    from app.tests.deployment_prepare_fixture import register_variant
    from app.tests.deployment_source_fixture import inputs

    with service_context(tmp_path, monkeypatch, capacity=2) as actual:
        receipt = actual.service.prepare(
            actual.request,
            register_variant(actual, extension_id="second-tool", slot_id=2),
        )
        actual.topology.close()
        release = inputs(capacity=1)
        instance = {
            **parse_canonical(release[3]),
            "origin_profile": actual.profile.as_dict(),
        }
        replacement = render_prepare_sources(*release[:3], canonical_json(instance))
        path = actual.actual.actual(actual.actual.c.TOPOLOGY_ROOT / "topology.json")
        path.chmod(0o640)
        path.write_bytes(replacement.topology_bytes)
        path.chmod(0o440)
        pins = parse_canonical(replacement.pins_bytes)
        with open_topology_source(
            profile=actual.profile,
            recipe_sha256=pins["recipe_sha256"],
            instance_sha256=pins["instance_sha256"],
            topology_sha256=pins["topology_sha256"],
            protected_roots=(),
        ) as topology:
            reopened = PersistentDeploymentPrepare(
                actual.domain,
                actual.owner,
                actual.registry,
                topology_source=topology,
                exchange_source=actual.exchange,
            )
            syscall_fixture(monkeypatch)
            reopened.reconcile_startup()
            assert (
                reopened.read(actual.read_request, receipt["request_id"])[
                    "publication_state"
                ]
                == "pending"
            )
            assert not final_path(actual, receipt).exists()
            cancelled = reopened.cancel(
                actual.request,
                receipt["request_id"],
                {
                    "command_id": str(uuid4()),
                    "request_digest": receipt["request_digest"],
                    "expected_revision": 1,
                },
            )
            assert cancelled["state"] == "cancelled"
            assert final_path(actual, receipt, "cancelled").exists()


def test_soft_budget_starts_no_new_item_after_one_second(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.deployment import prepare_service

    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        syscall_fixture(monkeypatch)
        observations = iter((0.0, 1.0))
        monkeypatch.setattr(
            prepare_service,
            "time",
            SimpleNamespace(monotonic=lambda: next(observations)),
        )
        actual.service.reconcile_startup()
        assert not final_path(actual, receipt).exists()
        assert (
            actual.service.read(actual.read_request, receipt["request_id"])[
                "publication_state"
            ]
            == "pending"
        )
