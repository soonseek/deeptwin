"""Actual owner, candidate, source and durable preparation lifecycle."""

from dataclasses import replace
from uuid import uuid4

import pytest

from app.deployment.prepare_contracts import DeploymentPrepareError
from app.tests.deployment_prepare_fixture import service_context


def test_matching_cancel_after_deadline_commits_expiry_but_no_cancel_command(
    tmp_path, monkeypatch
):
    import time

    from app.deployment.prepare_contracts import epoch_ms

    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        current = actual.service.read(actual.read_request, receipt["request_id"])
        deadline = epoch_ms(current["request"]["expires_at"])
        monkeypatch.setattr(time, "time_ns", lambda: deadline * 1000000)
        payload = {
            "command_id": str(uuid4()),
            "request_digest": receipt["request_digest"],
            "expected_revision": 1,
        }
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.cancel(actual.request, receipt["request_id"], payload)
        assert failure.value.code == "conflict"
        assert (
            actual.service.read(actual.read_request, receipt["request_id"])["state"]
            == "expired"
        )
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_commands"
                ).fetchone()[0]
                == 1
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_lifecycle"
                ).fetchone()[0]
                == 2
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_outbox WHERE role='cancel'"
                ).fetchone()[0]
                == 0
            )


def test_real_prepare_read_replay_and_cancel_without_sources(tmp_path, monkeypatch):
    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        assert receipt["state"] == "prepared" and receipt["revision"] == 1
        assert receipt["publication_state"] == "pending"
        assert receipt["cancellation_publication_state"] is None
        request_id = receipt["request_id"]
        current = actual.service.read(actual.read_request, request_id)
        assert current["request"]["created_by"]["id"] == actual.request.session.actor.id
        assert current["request"]["effect_payload"]["extension_id"] == "synthetic-tool"
        actual.topology.close()
        actual.exchange.close()
        assert actual.service.prepare(actual.request, actual.payload) == receipt
        payload = {
            "command_id": str(uuid4()),
            "request_digest": receipt["request_digest"],
            "expected_revision": 1,
        }
        cancelled = actual.service.cancel(actual.request, request_id, payload)
        assert cancelled["state"] == "cancelled" and cancelled["revision"] == 2
        assert cancelled["publication_state"] == "suppressed"
        assert cancelled["cancellation_publication_state"] == "pending"
        assert actual.service.cancel(actual.request, request_id, payload) == cancelled
        assert actual.service.prepare(actual.request, actual.payload) == receipt
        assert (
            actual.service.read(actual.read_request, request_id)["state"] == "cancelled"
        )


@pytest.mark.parametrize("change", ["copied", "method", "csrf", "host", "origin"])
def test_mutation_denies_invalid_actual_request_before_any_deployment_blob(
    tmp_path, monkeypatch, change
):
    with service_context(tmp_path, monkeypatch) as actual:
        request = {
            "copied": replace(actual.request, session=replace(actual.request.session)),
            "method": replace(actual.request, method="GET"),
            "csrf": replace(actual.request, csrf_verified=1),
            "host": replace(actual.request, host="other.invalid"),
            "origin": replace(actual.request, origin=None),
        }[change]
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.prepare(request, actual.payload)
        assert failure.value.code in {"access_denied", "unauthenticated"}
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_requests"
                ).fetchone()[0]
                == 0
            )


def test_command_change_and_terminal_reservations_remain_conflicts(
    tmp_path, monkeypatch
):
    with service_context(tmp_path, monkeypatch) as actual:
        prepared = actual.service.prepare(actual.request, actual.payload)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.prepare(
                actual.request, {**actual.payload, "expires_in_seconds": 61}
            )
        assert failure.value.code == "conflict"
        actual.service.cancel(
            actual.request,
            prepared["request_id"],
            {
                "command_id": str(uuid4()),
                "request_digest": prepared["request_digest"],
                "expected_revision": 1,
            },
        )
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.prepare(
                actual.request, {**actual.payload, "command_id": str(uuid4())}
            )
        assert failure.value.code == "conflict"


@pytest.mark.parametrize(
    "stage",
    [
        "anchor",
        "control",
        "requests",
        "event",
        "lifecycle",
        "heads",
        "commands",
        "outbox",
    ],
)
def test_each_authority_write_failure_rolls_back_entire_business_transaction(
    tmp_path, monkeypatch, stage
):
    import sqlite3

    from app.deployment import prepare_lifecycle, prepare_storage

    with service_context(tmp_path, monkeypatch) as actual:
        if stage == "anchor":
            target, name = actual.domain, "_put_in_transaction"
        elif stage == "event":
            target, name = prepare_lifecycle, "_append_event_in_transaction"
        else:
            target, name = prepare_storage, "insert"
        original = getattr(target, name)

        def fault(*args, **kwargs):
            result = original(*args, **kwargs)
            if stage in {"anchor", "event"} or args[1] == stage:
                raise sqlite3.OperationalError("private-path-nonce-canary")
            return result

        monkeypatch.setattr(target, name, fault)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.prepare(actual.request, actual.payload)
        assert failure.value.code == "unavailable" and "canary" not in str(
            failure.value
        )
        with actual.domain._connection() as db:
            for table in prepare_storage.TABLES:
                assert (
                    db.execute(
                        "SELECT count(*) FROM deployment_prepare_" + table
                    ).fetchone()[0]
                    == 0
                )
            assert (
                db.execute(
                    "SELECT count(*) FROM domain_records WHERE kind='deployment_request'"
                ).fetchone()[0]
                == 0
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM api_event_envelopes WHERE event_type LIKE 'deployment.%'"
                ).fetchone()[0]
                == 0
            )


@pytest.mark.parametrize("same_extension", [False, True])
def test_two_actual_service_writers_cannot_reserve_same_slot_or_extension(
    tmp_path, monkeypatch, same_extension
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.deployment.prepare_service import PersistentDeploymentPrepare
    from app.tests.deployment_prepare_fixture import register_variant

    with service_context(tmp_path, monkeypatch, capacity=2) as actual:
        other = register_variant(
            actual,
            extension_id="synthetic-tool" if same_extension else "other-tool",
            slot_id=2 if same_extension else 1,
        )
        second = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=actual.topology,
            exchange_source=actual.exchange,
        )
        barrier = Barrier(2)

        def attempt(service, payload):
            barrier.wait()
            try:
                return service.prepare(actual.request, payload)["state"]
            except DeploymentPrepareError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(attempt, actual.service, actual.payload)
            next_one = pool.submit(attempt, second, other)
            results = [first.result(timeout=20), next_one.result(timeout=20)]
        assert sorted(results) == sorted(
            ["prepared", "conflict" if same_extension else "capacity"]
        )
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_requests"
                ).fetchone()[0]
                == 1
            )


def test_rejected_new_command_checkpoints_clock_and_stale_cancel_never_expires(
    tmp_path, monkeypatch
):
    import time

    from app.deployment.prepare_contracts import epoch_ms
    from app.deployment.prepare_service import PersistentDeploymentPrepare

    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        deadline = epoch_ms(
            actual.service.read(actual.read_request, receipt["request_id"])["request"][
                "expires_at"
            ]
        )
        monkeypatch.setattr(time, "time_ns", lambda: deadline * 1000000)
        with pytest.raises(DeploymentPrepareError):
            actual.service.cancel(
                actual.request,
                receipt["request_id"],
                {
                    "command_id": str(uuid4()),
                    "request_digest": receipt["request_digest"],
                    "expected_revision": 2,
                },
            )
        assert (
            actual.service.read(actual.read_request, receipt["request_id"])["state"]
            == "prepared"
        )
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT clock_floor_ms FROM deployment_prepare_control"
                ).fetchone()[0]
                >= deadline
            )
        monkeypatch.setattr(time, "time_ns", lambda: (deadline - 120000) * 1000000)
        reopened = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=actual.topology,
            exchange_source=actual.exchange,
        )
        assert (
            reopened.read(actual.read_request, receipt["request_id"])["state"]
            == "prepared"
        )
        reopened.reconcile_startup()
        assert (
            reopened.read(actual.read_request, receipt["request_id"])["state"]
            == "expired"
        )


@pytest.mark.parametrize(
    "kind", ["extension_installation", "extension_qualification", "extension_binding"]
)
def test_any_actual_historical_managed_kind_denies_new_first_only_prepare(
    tmp_path, monkeypatch, kind
):
    from app.domain import extension_installation
    from app.domain.schemas import ImmutableRecord

    with service_context(tmp_path, monkeypatch) as actual:
        roots = actual.domain.roots()
        if kind == "extension_installation":
            # the guard denies on any row of the managed kind, whatever its
            # content (a row written under another schema); the closed
            # extension-installation-anchor-v1 codec is proven by its own
            # suite, so this historical row is admitted without it
            monkeypatch.setattr(
                extension_installation, "validate_installation_body", lambda body: None
            )
        record = ImmutableRecord.create(
            kind=kind,
            id=str(uuid4()),
            version=1,
            created_at_utc="2026-09-15T00:00:00.000000Z",
            actor_ref=roots.actor,
            parent_refs=(),
            purpose="operational",
            access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
            content={"historical_state": "tombstone"},
        )
        actual.domain.put(record)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.prepare(actual.request, actual.payload)
        # journal v3 owns every extension_installation anchor: one outside its
        # index is an integrity failure (a closed denial before the guard);
        # the first-only guard itself is proved by the other two kinds
        assert failure.value.code == (
            "unavailable" if kind == "extension_installation" else "conflict"
        )


def test_fresh_real_session_replays_terminal_command_but_revoked_and_copied_sessions_fail(
    tmp_path, monkeypatch
):
    from app.tests.test_web_owner_integration import headers

    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        cancellation = {
            "command_id": str(uuid4()),
            "request_digest": receipt["request_digest"],
            "expected_revision": 1,
        }
        cancelled = actual.service.cancel(
            actual.request, receipt["request_id"], cancellation
        )
        actual.topology.close()
        actual.exchange.close()
        token = actual.client.get(
            actual.profile.base_path + "session", headers=headers(actual.profile)
        ).json()["csrf_token"]
        response = actual.client.post(
            actual.profile.base_path + "session/logout",
            headers=headers(actual.profile, token),
            json={"command_id": str(uuid4())},
        )
        assert response.status_code == 200
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.prepare(actual.request, actual.payload)
        assert failure.value.code == "unauthenticated"
        response = actual.client.post(
            actual.profile.base_path + "session/login",
            headers=headers(actual.profile),
            json={"login_name": "owner", "password": "synthetic owner passphrase"},
        )
        assert response.status_code == 200
        token = response.json()["csrf_token"]
        request = actual.owner.authenticate_request(
            method="POST",
            host=actual.request.host,
            origin=actual.request.origin,
            sec_fetch_site="same-origin",
            cookie_header="; ".join(
                k + "=" + v for k, v in actual.client.cookies.items()
            ),
            csrf_token=token,
        )
        assert request.session is not actual.request.session
        assert actual.service.prepare(request, actual.payload) == receipt
        assert (
            actual.service.cancel(request, receipt["request_id"], cancellation)
            == cancelled
        )
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.cancel(
                replace(request, session=replace(request.session)),
                receipt["request_id"],
                cancellation,
            )
        assert failure.value.code == "unauthenticated"


@pytest.mark.parametrize(
    "change,code",
    [
        ("unknown_candidate", "not_found"),
        ("unknown_slot", "not_found"),
        ("missing_topology", "dependency_unavailable"),
        ("missing_exchange", "dependency_unavailable"),
        ("mismatched_candidate_slot", "dependency_unavailable"),
    ],
)
def test_prepare_error_matrix_for_actual_sources_and_missing_objects(
    tmp_path, monkeypatch, change, code
):
    from app.deployment.prepare_service import PersistentDeploymentPrepare

    with service_context(tmp_path, monkeypatch, capacity=2) as actual:
        payload = actual.payload
        if change == "unknown_candidate":
            payload = {**payload, "candidate_id": str(uuid4())}
        if change == "unknown_slot":
            payload = {**payload, "slot_id": 3}
        if change == "mismatched_candidate_slot":
            payload = {**payload, "slot_id": 2}
        service = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=None if change == "missing_topology" else actual.topology,
            exchange_source=None if change == "missing_exchange" else actual.exchange,
        )
        with pytest.raises(DeploymentPrepareError) as failure:
            service.prepare(actual.request, payload)
        assert failure.value.code == code


def test_expected_storage_failure_is_closed_before_presealing(tmp_path, monkeypatch):
    from app.domain.store import StorageError

    with service_context(tmp_path, monkeypatch) as actual:

        def failed_blob(*args, **kwargs):
            raise StorageError("private-nonce-source-path-canary")

        monkeypatch.setattr(actual.domain, "put_blob", failed_blob)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.prepare(actual.request, actual.payload)
        assert failure.value.code == "unavailable" and "canary" not in str(
            failure.value
        )


@pytest.mark.parametrize("change", ["revoke", "topology_loss", "exchange_loss"])
def test_final_actual_writer_rechecks_session_and_both_sources_after_preseal(
    tmp_path, monkeypatch, change
):
    from app.tests.test_web_owner_integration import headers

    with service_context(tmp_path, monkeypatch) as actual:
        original = actual.domain.put_blob
        changed = False

        def preseal(*args, **kwargs):
            nonlocal changed
            blob = original(*args, **kwargs)
            if not changed:
                changed = True
                if change == "revoke":
                    token = actual.client.get(
                        actual.profile.base_path + "session",
                        headers=headers(actual.profile),
                    ).json()["csrf_token"]
                    response = actual.client.post(
                        actual.profile.base_path + "session/logout",
                        headers=headers(actual.profile, token),
                        json={"command_id": str(uuid4())},
                    )
                    assert response.status_code == 200
                elif change == "topology_loss":
                    actual.topology.close()
                else:
                    actual.exchange.close()
            return blob

        monkeypatch.setattr(actual.domain, "put_blob", preseal)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.prepare(actual.request, actual.payload)
        assert failure.value.code == (
            "unauthenticated" if change == "revoke" else "dependency_unavailable"
        )
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_requests"
                ).fetchone()[0]
                == 0
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM domain_records WHERE kind='deployment_request'"
                ).fetchone()[0]
                == 0
            )


def test_wrong_service_binding_denied_and_unexpected_programmer_failure_stays_closed_failure(
    tmp_path, monkeypatch
):
    from app.deployment.prepare_service import PersistentDeploymentPrepare

    with service_context(tmp_path, monkeypatch) as actual:
        with pytest.raises(DeploymentPrepareError) as failure:
            PersistentDeploymentPrepare(
                actual.domain,
                actual.owner,
                object(),
                topology_source=actual.topology,
                exchange_source=actual.exchange,
            )
        assert failure.value.code == "unavailable"

        def broken(*args, **kwargs):
            raise RuntimeError("private-path-nonce-canary")

        monkeypatch.setattr(actual.domain, "put_blob", broken)
        with pytest.raises(RuntimeError) as failure:
            actual.service.prepare(actual.request, actual.payload)
        assert "canary" not in str(failure.value)


def test_replay_and_read_never_checkpoint_deployment_clock_even_past_deadline(
    tmp_path, monkeypatch
):
    import time

    from app.deployment.prepare_contracts import epoch_ms

    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        deadline = epoch_ms(
            actual.service.read(actual.read_request, receipt["request_id"])["request"][
                "expires_at"
            ]
        )
        with actual.domain._connection() as db:
            before = tuple(
                db.execute("SELECT * FROM deployment_prepare_control").fetchone()
            )
        monkeypatch.setattr(time, "time_ns", lambda: (deadline + 1000) * 1000000)
        assert actual.service.prepare(actual.request, actual.payload) == receipt
        assert (
            actual.service.read(actual.read_request, receipt["request_id"])["state"]
            == "prepared"
        )
        with actual.domain._connection() as db:
            assert (
                tuple(db.execute("SELECT * FROM deployment_prepare_control").fetchone())
                == before
            )


def test_high_final_sample_survives_business_rollback_and_later_wall_clock_rollback(
    tmp_path, monkeypatch
):
    import time

    from app.deployment.prepare_contracts import epoch_ms
    from app.tests.deployment_prepare_fixture import register_variant

    with service_context(tmp_path, monkeypatch, capacity=2) as actual:
        first = actual.service.prepare(actual.request, actual.payload)
        deadline = epoch_ms(
            actual.service.read(actual.read_request, first["request_id"])["request"][
                "expires_at"
            ]
        )
        next_payload = register_variant(actual, extension_id="next-tool", slot_id=2)
        original = actual.domain.put_blob
        sampled = False

        def crossing_deadline(*args, **kwargs):
            nonlocal sampled
            result = original(*args, **kwargs)
            if not sampled:
                sampled = True
                monkeypatch.setattr(
                    time, "time_ns", lambda: (deadline + 120000) * 1000000
                )
            return result

        monkeypatch.setattr(actual.domain, "put_blob", crossing_deadline)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.prepare(actual.request, next_payload)
        assert failure.value.code == "conflict"
        monkeypatch.setattr(time, "time_ns", lambda: (deadline - 30000) * 1000000)
        actual.service.reconcile_startup()
        assert (
            actual.service.read(actual.read_request, first["request_id"])["state"]
            == "expired"
        )
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT clock_floor_ms FROM deployment_prepare_control"
                ).fetchone()[0]
                >= deadline + 120000
            )


def test_clock_overflow_inhibits_actual_mutation_before_any_request_is_committed(
    tmp_path, monkeypatch
):
    import time

    from app.deployment.prepare_contracts import MAX_MS

    with service_context(tmp_path, monkeypatch) as actual:
        monkeypatch.setattr(time, "time_ns", lambda: (MAX_MS + 1) * 1000000)
        with pytest.raises(DeploymentPrepareError):
            actual.service.prepare(actual.request, actual.payload)
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_requests"
                ).fetchone()[0]
                == 0
            )
