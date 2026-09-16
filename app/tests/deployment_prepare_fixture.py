"""Actual owner/candidate/domain bytes for deployment foundation tests.

No prepare service or source authority is simulated here. Physical source-reader
tests will use deployment_source_fixture.ActualSources in the service phase.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from app.deployment.prepare_contracts import make_request
from app.deployment.render import render_prepare_sources
from app.domain.refs import EntityRef, canonical_json, parse_canonical
from app.domain.schemas import ImmutableRecord
from app.domain.store import _writer
from app.extensions.candidate_contracts import parse_bundle
from app.extensions.candidate_records import load_candidate
from app.tests.deployment_source_fixture import inputs
from app.tests.test_deployment_prepare_contracts import matching_bundle
from app.tests.test_extension_candidates_persistent import owner


@contextmanager
def pre_deployment_catalog():
    """Standalone absent-schema tests run the fixed earlier installed build."""
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    from app.api import first_party, first_party_catalog

    entries = first_party_catalog.INSTALLED[:2]
    source = Path(first_party.__file__).with_name("route_contributions")
    with TemporaryDirectory(prefix="deeptwin-pre-deployment-") as directory:
        root = Path(directory) / "route_contributions"
        root.mkdir()
        for entry in entries:
            (root / entry.descriptor_name).write_bytes(
                (source / entry.descriptor_name).read_bytes()
            )
        with (
            patch.object(first_party_catalog, "INSTALLED", entries),
            patch.object(
                first_party, "__file__", str(Path(directory) / "first_party.py")
            ),
        ):
            yield


def http_sources(tmp_path, monkeypatch, profile, *, capacity=1):
    """Real source files/FDs; map only Linux path/mount/owner observations."""
    from pathlib import Path

    from app.tests.deployment_source_fixture import ActualSources

    (tmp_path / "sources").mkdir()
    (tmp_path / "data").mkdir(mode=0o700, exist_ok=True)
    actual = ActualSources(tmp_path / "sources", monkeypatch, capacity=capacity)
    original_actual = actual.actual
    roots = (tmp_path / "data", tmp_path / "root")
    actual.actual = lambda path: (
        Path(path) if Path(path) in roots else original_actual(path)
    )
    for index, root in enumerate(roots, 100):
        actual.mount_lines.append(
            f"{index} 999 {actual.device} /private{index} {root} rw - ext4 /dev/fake rw\n"
        )
    release = inputs(capacity=capacity)
    instance = {**parse_canonical(release[3]), "origin_profile": profile.as_dict()}
    output = render_prepare_sources(*release[:3], canonical_json(instance))
    for root, name, raw in (
        (actual.c.TOPOLOGY_ROOT, "topology.json", output.topology_bytes),
        (actual.c.EXCHANGE_ROOT, "exchange.json", output.exchange_bytes),
    ):
        path = actual.actual(root) / name
        path.chmod(0o640)
        path.write_bytes(raw)
        path.chmod(0o440)
    pins = parse_canonical(output.pins_bytes)
    values = {
        "DEEPTWIN_PREPARE_RECIPE_SHA256": pins["recipe_sha256"],
        "DEEPTWIN_PREPARE_INSTANCE_SHA256": pins["instance_sha256"],
        "DEEPTWIN_TOPOLOGY_SHA256": pins["topology_sha256"],
        "DEEPTWIN_EXCHANGE_SHA256": pins["exchange_sha256"],
    }
    return actual, values


@contextmanager
def service_context(tmp_path, monkeypatch, *, capacity=1):
    """Real owner and source factories; only OS observations are controlled."""
    import importlib
    from contextlib import ExitStack
    from dataclasses import replace

    import pytest

    from app.deployment import sources
    from app.tests.deployment_source_fixture import ActualSources

    try:
        implementation = importlib.import_module("app.deployment.prepare_service")
    except ModuleNotFoundError:
        pytest.fail("Actual deployment prepare service is missing")
    with (
        owner(tmp_path) as (app, client, request, profile, arguments),
        ExitStack() as stack,
    ):
        domain = app.state.domain_store
        registry = app.state.first_party_exports["extension-candidates.registry"]
        registration = registry.register(request, matching_bundle()[0].as_dict())
        source_root = tmp_path / "sources"
        source_root.mkdir()
        actual = ActualSources(source_root, monkeypatch, capacity=capacity)
        release = inputs(capacity=capacity)
        instance = {**parse_canonical(release[3]), "origin_profile": profile.as_dict()}
        output = render_prepare_sources(*release[:3], canonical_json(instance))
        for root, name, raw in (
            (actual.c.TOPOLOGY_ROOT, "topology.json", output.topology_bytes),
            (actual.c.EXCHANGE_ROOT, "exchange.json", output.exchange_bytes),
        ):
            path = actual.actual(root) / name
            path.chmod(0o640)
            path.write_bytes(raw)
            path.chmod(0o440)
        pins = parse_canonical(output.pins_bytes)
        common = {
            "profile": profile,
            "recipe_sha256": pins["recipe_sha256"],
            "instance_sha256": pins["instance_sha256"],
            "protected_roots": (),
        }
        topology = sources.open_topology_source(
            **common, topology_sha256=pins["topology_sha256"]
        )
        stack.callback(topology.close)
        exchange = sources.open_exchange_source(
            **common, exchange_sha256=pins["exchange_sha256"]
        )
        stack.callback(exchange.close)
        service = implementation.PersistentDeploymentPrepare(
            domain,
            app.state.owner_authority,
            registry,
            topology_source=topology,
            exchange_source=exchange,
        )
        yield SimpleNamespace(
            service=service,
            domain=domain,
            owner=app.state.owner_authority,
            registry=registry,
            request=request,
            read_request=replace(request, method="GET"),
            profile=profile,
            client=client,
            arguments=arguments,
            actual=actual,
            topology=topology,
            exchange=exchange,
            output=output,
            payload={
                "command_id": str(uuid4()),
                "kind": "extension_stage",
                "candidate_id": registration["candidate_ref"]["candidate_id"],
                "slot_id": 1,
                "expires_in_seconds": 60,
            },
        )


def register_variant(actual, *, extension_id, slot_id=1):
    from app.extensions.candidate_contracts import metadata_ref

    payload = matching_bundle()[0].as_dict()
    payload["command_id"] = str(uuid4())
    payload["manifest"]["extension_id"] = extension_id
    slot = parse_canonical(actual.output.topology_bytes)["slots"][slot_id - 1]
    descriptor = payload["service_descriptor"]
    descriptor["extension_id"] = extension_id
    descriptor.update({key: slot[key] for key in ("service_identity", "uid", "gid")})
    descriptor["socket_mounts"] = [slot["socket_mount"]]
    descriptor["broker_endpoint"].update(
        channel_id=slot["channel_id"],
        responder_service=slot["service_identity"],
        pair_gid=slot["pair_gid"],
        socket_mount_id=slot["socket_mount"]["mount_id"],
    )
    payload["manifest"]["artifact"]["service_descriptor_ref"] = metadata_ref(
        "service_descriptor", canonical_json(descriptor)
    )
    receipt = actual.registry.register(actual.request, payload)
    return {
        **actual.payload,
        "command_id": str(uuid4()),
        "candidate_id": receipt["candidate_ref"]["candidate_id"],
        "slot_id": slot_id,
    }


@contextmanager
def retained_anchor(tmp_path, *, pre_deployment=False):
    from contextlib import nullcontext

    with (
        pre_deployment_catalog() if pre_deployment else nullcontext(),
        owner(tmp_path) as (app, client, request, profile, arguments),
    ):
        domain = app.state.domain_store
        registry = app.state.first_party_exports["extension-candidates.registry"]
        bundle = matching_bundle()[0]
        receipt = registry.register(request, bundle.as_dict())
        candidate_id = receipt["candidate_ref"]["candidate_id"]
        with _writer(), domain._connection(write=True) as db:
            registry._authenticate(request, db)
            registry._verify(db)
            row = db.execute(
                "SELECT * FROM extension_candidate_index WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            actual, _ = load_candidate(domain, db, row)
            candidate_ref = EntityRef(
                "extension_manifest", candidate_id, 1, row["anchor_digest"]
            )
            roots = domain._read_roots(db)
        bundle = parse_bundle(
            {
                "command_id": actual["command_id"],
                "manifest": actual["manifest"],
                "service_descriptor": actual["service_descriptor"],
                "documents": actual["documents"],
            }
        )
        release = inputs()
        instance = {**parse_canonical(release[3]), "origin_profile": profile.as_dict()}
        output = render_prepare_sources(*release[:3], canonical_json(instance))
        topology = parse_canonical(output.topology_bytes)
        actor_ref = EntityRef.from_dict(actual["registration"]["registered_by"])
        command_id = str(uuid4())
        value = make_request(
            bundle=bundle,
            topology=topology,
            slot=topology["slots"][0],
            profile=profile,
            request_id=str(uuid4()),
            nonce=b"n" * 32,
            actor_ref=actor_ref.as_dict(),
            created_ms=1700000000000,
            ttl_seconds=60,
        )
        raw = canonical_json(value)
        blobs = [
            domain.put_blob(data, purpose="operational")
            for data in (raw, output.topology_bytes, output.exchange_bytes)
        ]
        content = {
            "schema_version": "deployment-request-anchor-v1",
            "request_id": value["request_id"],
            "request_blob_ref": blobs[0].as_dict(),
            "topology_blob_ref": blobs[1].as_dict(),
            "exchange_blob_ref": blobs[2].as_dict(),
            "candidate_ref": candidate_ref.as_dict(),
            "topology_id": topology["topology_id"],
            "topology_revision": 1,
            "slot_id": 1,
            "reservation_revision": 1,
            "prepare_command_id": command_id,
        }
        record = ImmutableRecord.create(
            kind="deployment_request",
            id=value["request_id"],
            version=1,
            created_at_utc="2023-11-14T22:13:20.000000Z",
            actor_ref=actor_ref,
            parent_refs=(candidate_ref,),
            purpose="operational",
            access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
            content=content,
        )
        with _writer(), domain._connection(write=True) as db:
            domain._put_in_transaction(db, record)
        yield SimpleNamespace(
            domain=domain,
            owner=app.state.owner_authority,
            registry=registry,
            authenticated_request=request,
            record=record,
            raw=raw,
            sources=output,
            profile=profile,
            arguments=arguments,
            client=client,
            blobs=blobs,
        )
