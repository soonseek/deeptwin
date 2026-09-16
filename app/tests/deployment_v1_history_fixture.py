"""Real pre-upgrade history, using original storage and shared lifecycle helpers.

Synthetic history assembly is not evidence of old live service clock/source admission.
Owner startup alone runs with the previous deployment-free catalog.
"""

from base64 import urlsafe_b64decode
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from secrets import token_bytes
from types import SimpleNamespace
from uuid import uuid4

from app.deployment import prepare_lifecycle as lifecycle
from app.deployment import prepare_records as records
from app.deployment import prepare_storage as storage
from app.deployment import sources
from app.deployment.prepare_contracts import make_request
from app.deployment.render import render_prepare_sources
from app.domain.refs import EntityRef, canonical_json, parse_canonical
from app.domain.schemas import ImmutableRecord
from app.domain.store import _writer
from app.tests.deployment_prepare_fixture import (
    pre_deployment_catalog,
    register_variant,
)
from app.tests.deployment_source_fixture import ActualSources, inputs
from app.tests.test_extension_candidates_persistent import owner


def snapshot_v1(domain):
    """Bounded deployment rows/bytes only; never owner/session/capability storage."""
    with domain._connection() as db:
        rows = {
            table: tuple(
                tuple(row)
                for row in db.execute(
                    "SELECT * FROM deployment_prepare_"
                    + table
                    + " ORDER BY 1,2 LIMIT ?",
                    (cap + 1,),
                )
            )
            for table, cap in {"migrations": 1, **storage.CAPS}.items()
        }
        deployment = tuple(
            tuple(row)
            for row in db.execute(
                "SELECT * FROM domain_records WHERE kind='deployment_request' ORDER BY id,version LIMIT 17"
            )
        )
        edges = tuple(
            tuple(row)
            for row in db.execute(
                "SELECT * FROM domain_edges WHERE source_kind='deployment_request' ORDER BY source_id,target_kind,target_id LIMIT 65"
            )
        )
        associations = tuple(
            tuple(row)
            for row in db.execute(
                "SELECT * FROM domain_record_blobs WHERE source_kind='deployment_request' ORDER BY source_id,sha256 LIMIT 49"
            )
        )
        roots = domain._read_roots(db)
        blobs = []
        from app.domain.store import BlobRef

        for row in associations:
            blob = BlobRef(row[0], row[4], row[5], row[6])
            blobs.append(
                (blob, domain._blob_bytes(db, blob, roots, purpose="operational"))
            )
        events = tuple(
            tuple(row)
            for row in db.execute(
                "SELECT * FROM api_event_envelopes WHERE event_type LIKE 'deployment.%' ORDER BY sequence LIMIT 49"
            )
        )
        return {
            "rows": rows,
            "records": deployment,
            "edges": edges,
            "associations": associations,
            "blobs": tuple(blobs),
            "events": events,
        }


@contextmanager
def v1_history(tmp_path, monkeypatch, *, states=()):
    assert type(states) is tuple and len(states) <= 16
    assert set(states) <= {"prepared", "cancelled", "expired"}
    with ExitStack() as stack:
        with pre_deployment_catalog():
            app, client, request, profile, arguments = stack.enter_context(
                owner(tmp_path)
            )
        domain, authority = app.state.domain_store, app.state.owner_authority
        registry = app.state.first_party_exports["extension-candidates.registry"]
        with _writer(), domain._connection(write=True) as db:
            storage.install(db)
            sampled = authority._now(db, write=True)
        source_root = tmp_path / "sources"
        source_root.mkdir()
        capacity = max(1, len(states))
        actual = ActualSources(source_root, monkeypatch, capacity=capacity)
        release = inputs(capacity=capacity)
        instance = {**parse_canonical(release[3]), "origin_profile": profile.as_dict()}
        output = render_prepare_sources(*release[:3], canonical_json(instance))
        for root, name, raw in (
            (actual.c.TOPOLOGY_ROOT, "topology.json", output.topology_bytes),
            (actual.c.EXCHANGE_ROOT, "exchange.json", output.exchange_bytes),
        ):
            target = actual.actual(root) / name
            target.chmod(0o640)
            target.write_bytes(raw)
            target.chmod(0o440)
        pins = parse_canonical(output.pins_bytes)
        exchange = sources.open_exchange_source(
            profile=profile,
            recipe_sha256=pins["recipe_sha256"],
            instance_sha256=pins["instance_sha256"],
            exchange_sha256=pins["exchange_sha256"],
            protected_roots=(),
        )
        stack.callback(exchange.close)
        fixture = SimpleNamespace(
            domain=domain,
            owner=authority,
            registry=registry,
            profile=profile,
            request=request,
            read_request=replace(request, method="GET"),
            client=client,
            arguments=arguments,
            actual=actual,
            exchange=exchange,
            output=output,
            payload={"kind": "extension_stage", "expires_in_seconds": 86400},
            cases=[],
        )
        topology = parse_canonical(output.topology_bytes)
        for number, state in enumerate(states, 1):
            value = register_variant(
                fixture, extension_id=f"history-{number}", slot_id=number
            )
            with _writer(), domain._connection(write=True) as db:
                bundle, candidate_ref = records.candidate(
                    domain, db, value["candidate_id"]
                )
                actor = EntityRef.from_dict(
                    parse_canonical(
                        db.execute(
                            "SELECT actor_ref FROM owner_auth_accounts WHERE owner_id=?",
                            (request.session.actor.id,),
                        )
                        .fetchone()[0]
                        .encode()
                    )
                )
                roots = domain._read_roots(db)
            created = sampled - 172800000 if state == "expired" else sampled
            proposal = make_request(
                bundle=bundle,
                topology=topology,
                slot=topology["slots"][number - 1],
                profile=profile,
                request_id=str(uuid4()),
                nonce=token_bytes(32),
                actor_ref=actor.as_dict(),
                created_ms=created,
                ttl_seconds=86400,
            )
            raw = canonical_json(proposal)
            blobs = [
                domain.put_blob(data, purpose="operational")
                for data in (raw, output.topology_bytes, output.exchange_bytes)
            ]
            record = ImmutableRecord.create(
                kind="deployment_request",
                id=proposal["request_id"],
                version=1,
                created_at_utc=lifecycle.instant(created),
                actor_ref=actor,
                parent_refs=(candidate_ref,),
                purpose="operational",
                access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy,
                content={
                    "schema_version": "deployment-request-anchor-v1",
                    "request_id": proposal["request_id"],
                    "request_blob_ref": blobs[0].as_dict(),
                    "topology_blob_ref": blobs[1].as_dict(),
                    "exchange_blob_ref": blobs[2].as_dict(),
                    "candidate_ref": candidate_ref.as_dict(),
                    "topology_id": topology["topology_id"],
                    "topology_revision": 1,
                    "slot_id": number,
                    "reservation_revision": 1,
                    "prepare_command_id": value["command_id"],
                },
            )
            with _writer(), domain._connection(write=True) as db:
                domain._put_in_transaction(db, record)
                if number == 1:
                    control = {
                        "singleton": 1,
                        "vault_id": roots.genesis.id,
                        "instance_id": profile.instance_id,
                        "origin_digest": profile.digest,
                        "topology_id": topology["topology_id"],
                        "topology_revision": 1,
                        "exchange_id": parse_canonical(output.exchange_bytes)[
                            "exchange_id"
                        ],
                        "exchange_revision": 1,
                        "exchange_identity_json": storage.encoded(
                            exchange.recheck_current().as_dict()
                        ),
                        "slot_capacity": capacity,
                        "clock_floor_ms": sampled + 1,
                        "revision": 1,
                    }
                    for name, blob in zip(
                        ("topology", "exchange"), blobs[1:], strict=True
                    ):
                        control.update(
                            {
                                name + "_" + key: getattr(blob, key)
                                for key in ("purpose", "sha256", "size")
                            }
                        )
                    storage.insert(db, "control", control)
                storage.insert(
                    db,
                    "requests",
                    {
                        "request_id": proposal["request_id"],
                        "vault_id": roots.genesis.id,
                        "kind": "deployment_request",
                        "version": 1,
                        "anchor_digest": record.ref.sha256,
                        "request_digest": proposal["request_digest"],
                        "nonce_hex": urlsafe_b64decode(
                            proposal["request_nonce"] + "="
                        ).hex(),
                        "topology_id": topology["topology_id"],
                        "slot_id": number,
                        "reservation_revision": 1,
                        "extension_id": f"history-{number}",
                        "created_ms": created,
                        "expires_ms": created + 86400000,
                    },
                )
                item = {
                    "ref": record.ref,
                    "request": proposal,
                    "raw": raw,
                    "history": [],
                    "outbox": {},
                }
                prepare_reply = lifecycle.transition(
                    db,
                    roots,
                    profile,
                    item,
                    state="prepared",
                    now=created,
                    actor_ref=actor,
                    value=value,
                )
                cancel_value = None
                cancel_reply = None
                if state != "prepared":
                    cancel_value = {
                        "command_id": str(uuid4()),
                        "request_id": proposal["request_id"],
                        "request_digest": proposal["request_digest"],
                        "expected_revision": 1,
                    }
                    cancel_reply = lifecycle.transition(
                        db,
                        roots,
                        profile,
                        item,
                        state=state,
                        now=sampled + 1,
                        actor_ref=roots.actor if state == "expired" else actor,
                        value=cancel_value if state == "cancelled" else None,
                    )
                records.bounded_candidates(domain, db)
                registry._verify(db)
                records.verify(domain, db, profile)
                assert db.execute("PRAGMA foreign_key_check").fetchone() is None
            fixture.cases.append((value, prepare_reply, cancel_value, cancel_reply))
        with domain._connection() as db:
            assert storage.shape(db) == storage.SHAPE
            assert [
                tuple(row)
                for row in db.execute("SELECT * FROM deployment_prepare_migrations")
            ] == [
                (1, "68a6ed89486cb48536873e4b107e2e7e1dd4061e5ce65773b0bebe46303cc2ec")
            ]
            records.bounded_candidates(domain, db)
            registry._verify(db)
            records.verify(domain, db, profile)
        yield fixture
