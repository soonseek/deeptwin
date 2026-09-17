"""Signed actual service admission, atomic evidence and one-use non-success."""

from uuid import uuid4

import pytest

from app.deployment.prepare_contracts import DeploymentPrepareError
from app.tests.deployment_receipt_import_fixture import (
    receipt_context,
    reopen,
    signed_case,
)


def authority_counts(domain):
    with domain._connection() as db:
        return tuple(
            db.execute(sql).fetchone()[0]
            for sql in (
                "SELECT count(*) FROM domain_records WHERE kind IN ('deployment_receipt','deployment_receipt_consumption')",
                "SELECT count(*) FROM deployment_prepare_receipts",
                "SELECT count(*) FROM deployment_prepare_receipt_sources",
                "SELECT count(*) FROM deployment_prepare_consumptions",
                "SELECT count(*) FROM deployment_prepare_consumed_outbox",
                "SELECT count(*) FROM api_event_envelopes WHERE event_type='deployment.receipt_committed'",
                "SELECT count(*) FROM deployment_prepare_commands",
                "SELECT count(*) FROM deployment_prepare_lifecycle",
            )
        )


@pytest.mark.parametrize(
    "case,outcome,state,consumptions",
    [
        ("valid_succeeded_present", "succeeded", "receipt_pending", 0),
        ("valid_failed_absent", "failed", "rejected", 1),
        ("valid_failed_unknown", "failed", "rejected", 1),
        ("valid_unknown_unknown", "unknown", "rejected", 1),
    ],
)
def test_actual_signed_receipt_commits_exact_disposition_and_replays_without_sources(
    tmp_path, monkeypatch, case, outcome, state, consumptions
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(actual, monkeypatch, case_name=case)
        result = actual.service.import_receipt(
            actual.request, prepared["request_id"], command
        )
        assert result == {
            "command_id": command["command_id"],
            "request_id": prepared["request_id"],
            "receipt_digest": command["receipt_digest"],
            "outcome": outcome,
            "disposition": "consumed_non_success"
            if consumptions
            else "pending_postconditions",
            "revision": 2,
            "event_cursor": result["event_cursor"],
        }
        current = actual.service.read(actual.read_request, prepared["request_id"])
        assert current["state"] == state and current["revision"] == 2
        assert current["publication_state"] == "suppressed"
        assert current["receipt"]["outcome"] == outcome
        assert current["consumption_publication_state"] == (
            "pending" if consumptions else None
        )
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_receipts"
                ).fetchone()[0]
                == 1
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_consumptions"
                ).fetchone()[0]
                == consumptions
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_consumed_outbox"
                ).fetchone()[0]
                == consumptions
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM domain_records WHERE kind IN ('extension_installation','extension_qualification','extension_binding')"
                ).fetchone()[0]
                == 0
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM api_event_envelopes WHERE event_type='deployment.receipt_committed'"
                ).fetchone()[0]
                == 1
            )
        historical = reopen(
            actual, trust=False, ingress=False, consumption=False, prepare_sources=False
        )
        assert (
            historical.import_receipt(actual.request, prepared["request_id"], command)
            == result
        )
        assert historical.read(actual.read_request, prepared["request_id"]) == current
        with pytest.raises(DeploymentPrepareError) as error:
            historical.import_receipt(
                actual.request,
                prepared["request_id"],
                {**command, "command_id": str(uuid4())},
            )
        assert error.value.code == "conflict"


@pytest.mark.parametrize(
    "case,expected",
    [
        ("invalid_cross_request", "conflict"),
        ("invalid_tuple", "conflict"),
        ("invalid_service_identity", "conflict"),
        ("invalid_profile", "dependency_unavailable"),
        ("invalid_key_adapter", "invalid_input"),
        ("invalid_time", "invalid_input"),
        ("invalid_expiry", "invalid_input"),
        ("invalid_fact", "invalid_input"),
    ],
)
def test_signature_source_and_private_mismatch_error_partition(
    tmp_path, monkeypatch, case, expected
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(actual, monkeypatch, case_name=case)
        before = authority_counts(actual.domain)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.import_receipt(
                actual.request, prepared["request_id"], command
            )
        assert failure.value.code == expected
        assert authority_counts(actual.domain) == before


@pytest.mark.parametrize("change", ["forged_mismatch", "malformed", "missing"])
def test_forged_mismatch_is_never_conflict_and_selected_safe_malformed_is_400(
    tmp_path, monkeypatch, change
):
    from hashlib import sha256

    from app.domain.refs import canonical_json, parse_canonical
    from app.tests.deployment_receipt_import_fixture import b64

    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, raw, final = signed_case(actual, monkeypatch)
        if change == "forged_mismatch":
            parsed = parse_canonical(raw)
            parsed["request_nonce"] = b64(b"x" * 32)
            raw = canonical_json(parsed)
        elif change == "malformed":
            raw = b"{}"
        else:
            raw = b"missing"
        command["receipt_digest"] = b64(sha256(raw).digest())
        if change != "missing":
            target = final.with_name(sha256(raw).hexdigest() + ".json")
            target.write_bytes(raw)
            target.chmod(0o440)
            actual.actual.register(target, 20113, 21201)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.import_receipt(
                actual.request, prepared["request_id"], command
            )
        assert failure.value.code == (
            "dependency_unavailable" if change == "missing" else "invalid_input"
        )


@pytest.mark.parametrize("mismatch", [None, "revision", "digest"])
def test_matching_due_head_expires_before_any_source_access_but_wrong_head_does_not(
    tmp_path, monkeypatch, mismatch
):
    import time

    from app.deployment.prepare_contracts import epoch_ms
    from app.tests.deployment_receipt_import_fixture import b64

    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(actual, monkeypatch)
        current = actual.service.read(actual.read_request, prepared["request_id"])
        deadline = epoch_ms(current["request"]["expires_at"])
        monkeypatch.setattr(time, "time_ns", lambda: deadline * 1000000)
        actual.service = reopen(actual, trust=False, ingress=False, consumption=False)
        if mismatch == "revision":
            command["expected_revision"] = 2
        elif mismatch == "digest":
            command["request_digest"] = b64(b"x" * 32)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.import_receipt(
                actual.request, prepared["request_id"], command
            )
        assert failure.value.code == "conflict"
        assert actual.service.read(actual.read_request, prepared["request_id"])[
            "state"
        ] == ("expired" if mismatch is None else "prepared")
        assert authority_counts(actual.domain)[:6] == (0, 0, 0, 0, 0, 0)


@pytest.mark.parametrize(
    "target",
    [
        "receipt_sources",
        "receipt_anchor",
        "event",
        "lifecycle",
        "heads",
        "commands",
        "receipts",
        "consumption_anchor",
        "consumptions",
        "consumed_outbox",
        "suppress",
        "commit",
    ],
)
def test_each_authority_write_fault_leaves_no_partial_admission_and_closes_lease(
    tmp_path, monkeypatch, target
):
    import sqlite3

    from app.deployment import prepare_lifecycle as lifecycle
    from app.deployment import prepare_storage as storage

    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(actual, monkeypatch)
        before = authority_counts(actual.domain)
        leases = []
        original_open = actual.ingress.open_receipt

        def open_receipt(digest):
            lease = original_open(digest)
            leases.append(lease)
            return lease

        monkeypatch.setattr(actual.ingress, "open_receipt", open_receipt)
        original_insert, original_advance = storage.insert, storage.advance
        original_put, original_event = (
            actual.domain._put_in_transaction,
            lifecycle._append_event_in_transaction,
        )

        def fail():
            raise sqlite3.OperationalError("controlled authority fault")

        def insert(db, table, values):
            result = original_insert(db, table, values)
            if table == target:
                fail()
            if target == "commit" and table == "consumed_outbox":
                db.set_authorizer(
                    lambda action, arg1, arg2, database, trigger: (
                        sqlite3.SQLITE_DENY
                        if action == sqlite3.SQLITE_TRANSACTION and arg1 == "COMMIT"
                        else sqlite3.SQLITE_OK
                    )
                )
            return result

        def advance(db, table, old, changes):
            result = original_advance(db, table, old, changes)
            if table == target or (target == "suppress" and table == "outbox"):
                fail()
            return result

        def put(db, record):
            result = original_put(db, record)
            if (
                target == "receipt_anchor" and record.ref.kind == "deployment_receipt"
            ) or (
                target == "consumption_anchor"
                and record.ref.kind == "deployment_receipt_consumption"
            ):
                fail()
            return result

        def event(db, **kwargs):
            result = original_event(db, **kwargs)
            if target == "event":
                fail()
            return result

        monkeypatch.setattr(storage, "insert", insert)
        monkeypatch.setattr(storage, "advance", advance)
        monkeypatch.setattr(actual.domain, "_put_in_transaction", put)
        monkeypatch.setattr(lifecycle, "_append_event_in_transaction", event)
        with pytest.raises(DeploymentPrepareError):
            actual.service.import_receipt(
                actual.request, prepared["request_id"], command
            )
        assert authority_counts(actual.domain) == before
        assert len(leases) == 1 and leases[0]._closed


@pytest.mark.parametrize("competitor", ["import", "cancel"])
def test_competing_actual_services_retain_single_winner_and_reservation(
    tmp_path, monkeypatch, competitor
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(actual, monkeypatch)
        second = reopen(actual)
        gate = Barrier(2)

        def attempt(service, kind):
            gate.wait(timeout=5)
            try:
                if kind == "import":
                    service.import_receipt(
                        actual.request,
                        prepared["request_id"],
                        {**command, "command_id": str(uuid4())},
                    )
                else:
                    service.cancel(
                        actual.request,
                        prepared["request_id"],
                        {
                            "command_id": str(uuid4()),
                            "request_digest": prepared["request_digest"],
                            "expected_revision": 1,
                        },
                    )
                return "won"
            except DeploymentPrepareError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(attempt, actual.service, "import")
            b = pool.submit(attempt, second, competitor)
            assert sorted([a.result(timeout=20), b.result(timeout=20)]) == [
                "conflict",
                "won",
            ]
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_requests"
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
    "change",
    ["revoke", "trust", "ingress", "consumption", "lease", "deadline", "managed_kind"],
)
def test_final_writer_rechecks_actual_admission_after_preseal(
    tmp_path, monkeypatch, change
):
    import sqlite3
    import time

    from app.deployment.prepare_contracts import epoch_ms
    from app.tests.test_web_owner_integration import headers

    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, final = signed_case(actual, monkeypatch)
        current = actual.service.read(actual.read_request, prepared["request_id"])
        deadline = epoch_ms(current["request"]["expires_at"])
        original = actual.domain.put_blob
        modified = False

        def preseal(*args, **kwargs):
            nonlocal modified
            blob = original(*args, **kwargs)
            if not modified:
                modified = True
                if change == "revoke":
                    token = actual.client.get(
                        actual.profile.base_path + "session",
                        headers=headers(actual.profile),
                    ).json()["csrf_token"]
                    assert (
                        actual.client.post(
                            actual.profile.base_path + "session/logout",
                            headers=headers(actual.profile, token),
                            json={"command_id": str(uuid4())},
                        ).status_code
                        == 200
                    )
                elif change in {"trust", "ingress", "consumption"}:
                    getattr(actual, change).close()
                elif change == "lease":
                    final.rename(tmp_path / "old-receipt.saved")
                elif change == "deadline":
                    monkeypatch.setattr(time, "time_ns", lambda: deadline * 1000000)
                else:
                    # a managed kind this journal does not own: under journal
                    # v3 an extension_installation anchor outside the index
                    # is an integrity failure, so the guard is proved here
                    # with a qualification row
                    with sqlite3.connect(actual.domain.path) as db:
                        row = db.execute(
                            "SELECT vault_id,id,version,sha256,purpose,body FROM domain_records WHERE kind='deployment_request'"
                        ).fetchone()
                        db.execute(
                            "INSERT INTO domain_records VALUES(?,?,?,?,?,?,?)",
                            (row[0], "extension_qualification", *row[1:]),
                        )
            return blob

        monkeypatch.setattr(actual.domain, "put_blob", preseal)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.import_receipt(
                actual.request, prepared["request_id"], command
            )
        expected = (
            "unauthenticated"
            if change == "revoke"
            else "conflict"
            if change in {"deadline", "managed_kind"}
            else "dependency_unavailable"
        )
        assert failure.value.code == expected
        assert authority_counts(actual.domain)[:6] == (0, 0, 0, 0, 0, 0)
        if change == "deadline":
            assert (
                actual.service.read(actual.read_request, prepared["request_id"])[
                    "state"
                ]
                == "expired"
            )


def test_first_source_inventory_uses_same_actual_writer_as_matching_head(
    tmp_path, monkeypatch
):
    from contextlib import contextmanager

    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(actual, monkeypatch)
        original_connection = actual.domain._connection
        original_inventory = actual.service._consumption_inventory
        writers = []
        inspections = []

        @contextmanager
        def connection(*, write=False):
            with original_connection(write=write) as db:
                if write:
                    writers.append(db)
                try:
                    yield db
                finally:
                    if write:
                        writers.remove(db)

        def inventory(journal):
            assert len(writers) == 1 and writers[0].in_transaction, (
                "live K inventory escaped matching-head writer"
            )
            inspections.append(True)
            return original_inventory(journal)

        monkeypatch.setattr(actual.domain, "_connection", connection)
        monkeypatch.setattr(actual.service, "_consumption_inventory", inventory)
        actual.service.import_receipt(actual.request, prepared["request_id"], command)
        assert len(inspections) >= 2


def test_competing_commit_publishes_k_at_first_writer_exit_before_loser_resumes(
    tmp_path, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from threading import get_ident

    from app.deployment import prepare_service
    from app.tests.test_deployment_publication import syscall_fixture

    with (
        receipt_context(tmp_path, monkeypatch) as actual,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        prepared, command, _, _ = signed_case(actual, monkeypatch)
        second = reopen(actual)
        syscall_fixture(monkeypatch)
        original_writer = prepare_service._writer
        original_head = actual.service._import_head
        losing_thread = get_ident()
        initial = []
        winner = []

        def head(db, journal, value):
            item = original_head(db, journal, value)
            if not initial:
                initial.append(db)
            return item

        @contextmanager
        def writer():
            with original_writer():
                yield
            if initial and get_ident() == losing_thread and not winner:
                winner.append(
                    pool.submit(
                        second.import_receipt,
                        actual.request,
                        prepared["request_id"],
                        {**command, "command_id": str(uuid4())},
                    ).result(timeout=20)
                )
                assert len(actual.consumption.inspect_consumed()) == 1

        monkeypatch.setattr(prepare_service, "_writer", writer)
        monkeypatch.setattr(actual.service, "_import_head", head)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.import_receipt(
                actual.request, prepared["request_id"], command
            )
        assert len(winner) == 1
        assert failure.value.code == "conflict"
        assert authority_counts(actual.domain)[:6] == (2, 1, 1, 1, 1, 1)


def test_import_never_reacquires_t_slot_or_live_e_and_exact_replay_never_advances_clock(
    tmp_path, monkeypatch
):
    import time

    from app.deployment.prepare_contracts import epoch_ms

    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(actual, monkeypatch)
        actual.topology.close()
        actual.exchange.close()
        result = actual.service.import_receipt(
            actual.request, prepared["request_id"], command
        )
        actual.trust.close()
        actual.ingress.close()
        actual.consumption.close()
        before = authority_counts(actual.domain)
        highest = actual.service._highest
        current = actual.service.read(actual.read_request, prepared["request_id"])
        later = epoch_ms(current["request"]["expires_at"]) + 1
        monkeypatch.setattr(time, "time_ns", lambda: later * 1000000)
        assert (
            actual.service.import_receipt(
                actual.request, prepared["request_id"], command
            )
            == result
        )
        assert (
            authority_counts(actual.domain) == before
            and actual.service._highest == highest
        )
        for route, body in (
            (str(uuid4()), command),
            (prepared["request_id"], {**command, "expected_revision": 2}),
        ):
            with pytest.raises(DeploymentPrepareError) as failure:
                actual.service.import_receipt(actual.request, route, body)
            assert failure.value.code == "conflict"
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.cancel(
                actual.request,
                prepared["request_id"],
                {
                    key: value
                    for key, value in command.items()
                    if key != "receipt_digest"
                },
            )
        assert failure.value.code == "conflict"
