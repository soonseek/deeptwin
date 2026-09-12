"""Durable ServiceClient credential revisions, heads, usage CAS and recovery."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from itertools import cycle
from uuid import uuid4

import pytest

from app.domain.schemas import Actor
from app.services.service_clients import (
    CorruptServiceClient,
    PersistentServiceClientRegistry,
    ServiceClientDenied,
    _payload_hash,
    _record_payload,
)
from app.storage import Store


def identifier():
    return str(uuid4())


def build_registry(store, *, clock, random_values, owner_token, owner, recovery_token):
    return PersistentServiceClientRegistry(
        store,
        verify_owner=lambda candidate: owner if candidate is owner_token else None,
        verify_recovery=lambda candidate: candidate is recovery_token,
        clock=lambda: clock[0],
        random_bytes=lambda size: next(random_values) if size == 32 else b"",
    )


@pytest.fixture
def durable(tmp_path):
    store = Store(tmp_path)
    clock = [1_000]
    owner_token = object()
    recovery_token = object()
    owner = Actor(identifier(), "human", "local_session")
    random_values = iter((b"a" * 32, b"b" * 32, b"c" * 32, b"d" * 32))
    registry = build_registry(
        store,
        clock=clock,
        random_values=random_values,
        owner_token=owner_token,
        owner=owner,
        recovery_token=recovery_token,
    )
    return registry, store, clock, owner_token, owner, recovery_token, random_values


def issue(registry, owner_token, **changes):
    values = {
        "client_id": identifier(),
        "name": "내 자동화",
        "scopes": ("command:work.revise", "events.read"),
        "allowed_network_profile": "portable_https",
        "expires_at": 2_000,
    }
    values.update(changes)
    return registry.issue(owner_token, **values)


def test_secret_is_returned_once_digest_only_and_survives_cold_restart(durable):
    registry, store, clock, owner_token, owner, recovery_token, random_values = durable
    issued = issue(registry, owner_token)
    expected_digest = hashlib.sha256(issued.secret.encode("ascii")).hexdigest()
    assert issued.client.credential_digest == "0" * 64

    with store._connection() as db:
        record = db.execute("SELECT * FROM service_client_records").fetchone()
        head = db.execute("SELECT * FROM service_client_heads").fetchone()
        events = [dict(row) for row in db.execute("SELECT * FROM service_client_events")]
        serialized = json.dumps([dict(record), dict(head), events], sort_keys=True)
        assert issued.secret not in serialized
        assert record["credential_digest"] == expected_digest
        assert head["revision"] == 1
        assert [event["event_type"] for event in events] == ["service_client.created"]

    reopened = build_registry(
        store,
        clock=clock,
        random_values=random_values,
        owner_token=owner_token,
        owner=owner,
        recovery_token=recovery_token,
    )
    principal = reopened.authenticate(
        issued.secret, network_profile="portable_https",
    )
    assert principal.client_id == issued.client.client_id
    snapshot = reopened.snapshot(owner_token, issued.client.client_id)
    assert "credential_digest" not in snapshot
    assert snapshot["revision"] == 1


def test_rotation_appends_immutable_revision_and_invalidates_predecessor_after_restart(durable):
    registry, store, clock, owner_token, owner, recovery_token, random_values = durable
    first = issue(registry, owner_token)
    second = registry.rotate(
        owner_token, first.client.client_id, expected_revision=1,
    )
    assert second.client.revision == 2
    with pytest.raises(ServiceClientDenied):
        registry.authenticate(first.secret, network_profile="portable_https")

    reopened = build_registry(
        store,
        clock=clock,
        random_values=random_values,
        owner_token=owner_token,
        owner=owner,
        recovery_token=recovery_token,
    )
    assert reopened.authenticate(
        second.secret, network_profile="portable_https",
    ).credential_revision == 2
    with store._connection() as db:
        rows = db.execute(
            "SELECT revision,state FROM service_client_records ORDER BY revision"
        ).fetchall()
        assert [(row["revision"], row["state"]) for row in rows] == [
            (1, "active"), (2, "active"),
        ]


def test_revoke_is_a_durable_terminal_head_without_erasing_history(durable):
    registry, store, _, owner_token, _, _, _ = durable
    issued = issue(registry, owner_token)
    revoked = registry.revoke(
        owner_token, issued.client.client_id, expected_revision=1,
    )
    assert revoked.state == "revoked" and revoked.revision == 2
    with pytest.raises(ServiceClientDenied):
        registry.authenticate(issued.secret, network_profile="portable_https")
    with store._connection() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM service_client_records"
        ).fetchone()[0] == 2
        assert db.execute(
            "SELECT state FROM service_client_heads"
        ).fetchone()[0] == "revoked"


def test_expiry_and_network_profile_remain_enforced_after_restart(durable):
    registry, _, clock, owner_token, _, _, _ = durable
    issued = issue(registry, owner_token, expires_at=1_100)
    with pytest.raises(ServiceClientDenied, match="network"):
        registry.authenticate(issued.secret, network_profile="dedicated_https")
    clock[0] = 1_100
    with pytest.raises(ServiceClientDenied, match="expired"):
        registry.authenticate(issued.secret, network_profile="portable_https")


def test_owner_list_is_bounded_stable_and_never_exposes_digests(durable):
    registry, _, _, owner_token, _, _, _ = durable
    issued = [issue(registry, owner_token) for _ in range(3)]
    expected = sorted(value.client.client_id for value in issued)

    first = registry.list_for_owner(owner_token, limit=2)
    assert [item["client_id"] for item in first["items"]] == expected[:2]
    assert first["next_cursor"] == expected[1]
    assert "credential_digest" not in json.dumps(first)

    second = registry.list_for_owner(
        owner_token, after_client_id=first["next_cursor"], limit=2,
    )
    assert [item["client_id"] for item in second["items"]] == expected[2:]
    assert second["next_cursor"] is None
    with pytest.raises(ServiceClientDenied):
        registry.list_for_owner(owner_token, limit=101)


def test_last_used_is_a_concurrent_durable_cas_bound_to_current_revision(durable):
    registry, store, clock, owner_token, owner, recovery_token, _ = durable
    issued = issue(registry, owner_token)
    clock[0] = 1_001
    registries = [
        build_registry(
            store,
            clock=clock,
            random_values=cycle((b"z" * 32,)),
            owner_token=owner_token,
            owner=owner,
            recovery_token=recovery_token,
        )
        for _ in range(4)
    ]

    def authenticate(index):
        return registries[index % len(registries)].authenticate(
            issued.secret, network_profile="portable_https",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(authenticate, range(20)))
    assert len(results) == 20
    usage = registry.usage_snapshot(owner_token, issued.client.client_id)
    assert usage == {
        "credential_revision": 1,
        "last_used_at": 1_001,
        "use_revision": 20,
    }


def test_concurrent_rotation_has_one_expected_revision_winner(durable):
    registry, store, clock, owner_token, owner, recovery_token, _ = durable
    first = issue(registry, owner_token)
    candidates = [
        build_registry(
            store,
            clock=clock,
            random_values=cycle((byte * 32,)),
            owner_token=owner_token,
            owner=owner,
            recovery_token=recovery_token,
        )
        for byte in (b"x", b"y")
    ]

    def rotate(candidate):
        try:
            return candidate.rotate(
                owner_token, first.client.client_id, expected_revision=1,
            )
        except ServiceClientDenied:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(rotate, candidates))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert winners[0].client.revision == 2
    assert registry.authenticate(
        winners[0].secret, network_profile="portable_https",
    ).credential_revision == 2
    with pytest.raises(ServiceClientDenied):
        registry.authenticate(first.secret, network_profile="portable_https")


def test_authentication_racing_recovery_cannot_survive_new_epoch(durable):
    registry, store, clock, owner_token, owner, recovery_token, _ = durable
    issued = issue(registry, owner_token)
    peer = build_registry(
        store,
        clock=clock,
        random_values=cycle((b"z" * 32,)),
        owner_token=owner_token,
        owner=owner,
        recovery_token=recovery_token,
    )

    def authenticate():
        try:
            peer.authenticate(issued.secret, network_profile="portable_https")
            return "authenticated-before-recovery"
        except ServiceClientDenied:
            return "denied"

    def recover():
        return registry.revoke_all_for_recovery(
            recovery_token, expected_epoch=0, new_epoch=1,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        auth_future = pool.submit(authenticate)
        recovery_future = pool.submit(recover)
        assert auth_future.result() in {"authenticated-before-recovery", "denied"}
        assert recovery_future.result()["new_epoch"] == 1
    with pytest.raises(ServiceClientDenied):
        peer.authenticate(issued.secret, network_profile="portable_https")


def test_recovery_epoch_atomically_revokes_all_heads_and_prevents_replay(durable):
    registry, store, _, owner_token, _, recovery_token, _ = durable
    first = issue(registry, owner_token)
    second = issue(registry, owner_token)
    receipt = registry.revoke_all_for_recovery(
        recovery_token, expected_epoch=0, new_epoch=1,
    )
    assert receipt == {"previous_epoch": 0, "new_epoch": 1, "revoked_count": 2}
    for issued in (first, second):
        with pytest.raises(ServiceClientDenied):
            registry.authenticate(issued.secret, network_profile="portable_https")
    with pytest.raises(ServiceClientDenied):
        registry.revoke_all_for_recovery(
            recovery_token, expected_epoch=0, new_epoch=1,
        )
    with store._connection() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM service_client_heads WHERE state='active'"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT recovery_epoch FROM service_client_control WHERE singleton=1"
        ).fetchone()[0] == 1


def test_recovery_advances_already_revoked_heads_and_survives_cold_restart(durable):
    registry, store, clock, owner_token, owner, recovery_token, random_values = durable
    already_revoked = issue(
        registry, owner_token, client_id="00000000-0000-4000-8000-000000000001",
    )
    still_active = issue(
        registry, owner_token, client_id="00000000-0000-4000-8000-000000000002",
    )
    registry.revoke(
        owner_token, already_revoked.client.client_id, expected_revision=1,
    )

    receipt = registry.revoke_all_for_recovery(
        recovery_token, expected_epoch=0, new_epoch=7,
    )

    assert receipt == {"previous_epoch": 0, "new_epoch": 7, "revoked_count": 1}
    with store._connection() as db:
        heads = list(db.execute(
            "SELECT h.client_id,h.revision,h.state,r.recovery_epoch "
            "FROM service_client_heads h JOIN service_client_records r "
            "ON r.client_id=h.client_id AND r.revision=h.revision "
            "ORDER BY h.client_id"
        ))
        assert {(row["state"], row["recovery_epoch"]) for row in heads} == {
            ("revoked", 7),
        }
        assert {
            row["client_id"]: row["revision"] for row in heads
        } == {
            already_revoked.client.client_id: 3,
            still_active.client.client_id: 2,
        }
        assert [
            row["event_type"]
            for row in db.execute(
                "SELECT event_type FROM service_client_events ORDER BY sequence"
            )
        ][-2:] == [
            "service_client.recovery_advanced",
            "service_client.recovery_revoked",
        ]

    reopened = build_registry(
        store,
        clock=clock,
        random_values=random_values,
        owner_token=owner_token,
        owner=owner,
        recovery_token=recovery_token,
    )
    assert reopened.snapshot(
        owner_token, already_revoked.client.client_id,
    )["state"] == "revoked"
    for issued in (already_revoked, still_active):
        with pytest.raises(ServiceClientDenied):
            reopened.authenticate(issued.secret, network_profile="portable_https")


def test_corrupt_immutable_record_or_head_fails_closed(durable):
    registry, store, _, owner_token, _, _, _ = durable
    issued = issue(registry, owner_token)
    with store._connection() as db:
        db.execute(
            "UPDATE service_client_records SET name='tampered' WHERE client_id=?",
            (issued.client.client_id,),
        )
    with pytest.raises(CorruptServiceClient):
        registry.snapshot(owner_token, issued.client.client_id)
    with pytest.raises(CorruptServiceClient):
        registry.authenticate(issued.secret, network_profile="portable_https")


def test_rehashed_revision_cannot_change_immutable_client_fields(durable):
    registry, store, clock, owner_token, owner, recovery_token, random_values = durable
    issued = issue(registry, owner_token)
    registry.rotate(owner_token, issued.client.client_id, expected_revision=1)
    with store._connection() as db:
        row = dict(db.execute(
            "SELECT * FROM service_client_records WHERE client_id=? AND revision=2",
            (issued.client.client_id,),
        ).fetchone())
        payload = _record_payload(
            client_id=row["client_id"],
            revision=row["revision"],
            owner_id=row["owner_id"],
            name="forged second-revision name",
            scopes=tuple(json.loads(row["scopes_json"])),
            network_profile=row["network_profile"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            state=row["state"],
            credential_digest=row["credential_digest"],
            recovery_epoch=row["recovery_epoch"],
            recorded_at=row["recorded_at"],
            previous_hash=row["previous_hash"],
        )
        forged_hash = _payload_hash(payload)
        db.execute(
            "UPDATE service_client_records SET name=?,record_hash=? "
            "WHERE client_id=? AND revision=2",
            (payload["name"], forged_hash, issued.client.client_id),
        )
        db.execute(
            "UPDATE service_client_heads SET record_hash=? WHERE client_id=?",
            (forged_hash, issued.client.client_id),
        )
    with pytest.raises(CorruptServiceClient, match="transition"):
        build_registry(
            store,
            clock=clock,
            random_values=random_values,
            owner_token=owner_token,
            owner=owner,
            recovery_token=recovery_token,
        )


def test_missing_or_orphan_usage_revision_blocks_cold_restart(durable):
    registry, store, clock, owner_token, owner, recovery_token, random_values = durable
    issued = issue(registry, owner_token)
    with store._connection() as db:
        db.execute(
            "DELETE FROM service_client_usage WHERE client_id=?",
            (issued.client.client_id,),
        )
    with pytest.raises(CorruptServiceClient, match="usage coverage"):
        build_registry(
            store,
            clock=clock,
            random_values=random_values,
            owner_token=owner_token,
            owner=owner,
            recovery_token=recovery_token,
        )


def test_event_chain_tamper_blocks_cold_restart(durable):
    registry, store, clock, owner_token, owner, recovery_token, random_values = durable
    issued = issue(registry, owner_token)
    registry.rotate(owner_token, issued.client.client_id, expected_revision=1)
    with store._connection() as db:
        db.execute(
            "UPDATE service_client_events SET event_type='forged' WHERE sequence=1"
        )
    with pytest.raises(CorruptServiceClient):
        build_registry(
            store,
            clock=clock,
            random_values=random_values,
            owner_token=owner_token,
            owner=owner,
            recovery_token=recovery_token,
        )


def test_event_truncation_alone_blocks_cold_restart(durable):
    registry, store, clock, owner_token, owner, recovery_token, random_values = durable
    issued = issue(registry, owner_token)
    registry.rotate(owner_token, issued.client.client_id, expected_revision=1)
    with store._connection() as db:
        db.execute("DELETE FROM service_client_events")

    with pytest.raises(CorruptServiceClient, match="event head"):
        build_registry(
            store,
            clock=clock,
            random_values=random_values,
            owner_token=owner_token,
            owner=owner,
            recovery_token=recovery_token,
        )


def test_migration_or_same_column_constraint_tamper_blocks_cold_restart(durable):
    registry, store, clock, owner_token, owner, recovery_token, random_values = durable
    issue(registry, owner_token)
    with store._connection() as db:
        valid_hash = db.execute(
            "SELECT sha256 FROM service_client_migrations WHERE version=1"
        ).fetchone()["sha256"]
        db.execute("UPDATE service_client_migrations SET sha256='bad'")
    with pytest.raises(CorruptServiceClient):
        build_registry(
            store,
            clock=clock,
            random_values=random_values,
            owner_token=owner_token,
            owner=owner,
            recovery_token=recovery_token,
        )

    with store._connection() as db:
        db.execute(
            "UPDATE service_client_migrations SET sha256=?",
            (valid_hash,),
        )
        db.execute("PRAGMA writable_schema=ON")
        db.execute(
            "UPDATE sqlite_master SET sql=replace(sql, 'state TEXT NOT NULL', "
            "'state TEXT') WHERE type='table' AND name='service_client_heads'"
        )
        db.execute("PRAGMA writable_schema=OFF")
    with pytest.raises(CorruptServiceClient, match="constraints"):
        build_registry(
            store,
            clock=clock,
            random_values=random_values,
            owner_token=owner_token,
            owner=owner,
            recovery_token=recovery_token,
        )


def test_trigger_attached_elsewhere_cannot_mutate_service_client_tables(durable):
    registry, store, clock, owner_token, owner, recovery_token, random_values = durable
    issue(registry, owner_token)
    with store._connection() as db:
        db.execute(
            "CREATE TRIGGER alien_mutator AFTER INSERT ON works "
            "BEGIN DELETE FROM service_client_heads; END"
        )
    with pytest.raises(CorruptServiceClient, match="schema object"):
        build_registry(
            store,
            clock=clock,
            random_values=random_values,
            owner_token=owner_token,
            owner=owner,
            recovery_token=recovery_token,
        )


def test_expiry_denial_persists_time_and_prevents_restart_resurrection(durable):
    registry, store, clock, owner_token, owner, recovery_token, _ = durable
    issued = issue(registry, owner_token, expires_at=2_000)
    clock[0] = 1_999
    registry.authenticate(issued.secret, network_profile="portable_https")

    clock[0] = 2_000
    with pytest.raises(ServiceClientDenied, match="expired"):
        registry.authenticate(issued.secret, network_profile="portable_https")
    with store._connection() as db:
        control = db.execute(
            "SELECT last_observed_at FROM service_client_control WHERE singleton=1"
        ).fetchone()
        assert control["last_observed_at"] == 2_000

    clock[0] = 1_999
    reopened = build_registry(
        store,
        clock=clock,
        random_values=cycle((b"z" * 32,)),
        owner_token=owner_token,
        owner=owner,
        recovery_token=recovery_token,
    )
    with pytest.raises(ServiceClientDenied, match="backwards"):
        reopened.authenticate(issued.secret, network_profile="portable_https")
    with store._connection() as db:
        assert db.execute(
            "SELECT use_revision FROM service_client_usage WHERE client_id=?",
            (issued.client.client_id,),
        ).fetchone()["use_revision"] == 1


def test_duplicate_secret_and_failed_owner_or_recovery_are_atomic(durable):
    registry, store, _, owner_token, owner, recovery_token, _ = durable
    first = issue(registry, owner_token)
    duplicate_registry = PersistentServiceClientRegistry(
        store,
        verify_owner=lambda candidate: owner if candidate is owner_token else None,
        verify_recovery=lambda candidate: candidate is recovery_token,
        clock=lambda: 1_000,
        random_bytes=lambda size: b"a" * size,
    )
    raw = first.secret
    with pytest.raises(ServiceClientDenied, match="credential") as captured:
        issue(duplicate_registry, owner_token)
    current = captured.value.__traceback__
    while current is not None:
        if current.tb_frame.f_globals.get("__name__") == "app.services.service_clients":
            assert raw not in repr(current.tb_frame.f_locals)
        current = current.tb_next
    with pytest.raises(ServiceClientDenied, match="owner"):
        registry.rotate(object(), first.client.client_id, expected_revision=1)
    with pytest.raises(ServiceClientDenied, match="recovery"):
        registry.revoke_all_for_recovery(object(), expected_epoch=0, new_epoch=1)
    with store._connection() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM service_client_records"
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT recovery_epoch FROM service_client_control WHERE singleton=1"
        ).fetchone()[0] == 0
