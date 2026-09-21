"""Real owner, candidate, CAS and source/publisher fixture in temporary trees.

UID/GID, mount/platform observations and NOREPLACE syscall are controlled seams.
The actual guard, publisher FD/name/bytes/fsync, journal and owner remain real.
Synthetic lineage and boot material are not native packaging/qualification proof.
"""

import os
import sys
from base64 import urlsafe_b64encode
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.deployment import contracts as c
from app.domain.refs import canonical_json, parse_canonical
from app.operations.setup import (
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.server import create_app
from app.tests.test_provider_prepare_contracts import _provider_candidate
from app.tests.test_provider_publication import publication_tree
from app.tests.test_provider_source_startup import app_arguments
from app.tests.test_web_owner_integration import bootstrap_client, bound_request

WORKER_BYTES = (
    b"public synthetic provider worker image fixture; no native qualification"
)


def worker_candidate(slot):
    from app.extensions.candidate_contracts import metadata_ref, parse_bundle

    bundle, _ = _provider_candidate(slot)
    value = bundle.as_dict()
    lineage = next(
        d["content"] for d in value["documents"] if d["document_kind"] == "provenance"
    )
    for platform in lineage["platforms"]:
        platform["build_identity"]["entrypoint"] = {
            "sha256": sha256(WORKER_BYTES).hexdigest(),
            "size_bytes": len(WORKER_BYTES),
        }
    ref = metadata_ref("provenance", canonical_json(lineage))
    value["service_descriptor"]["evidence"]["provenance_ref"] = ref
    value["manifest"]["source"]["provenance_ref"] = ref
    value["manifest"]["artifact"]["service_descriptor_ref"] = metadata_ref(
        "service_descriptor", canonical_json(value["service_descriptor"])
    )
    return parse_bundle(value)


@contextmanager
def provider_worker(actual, monkeypatch):
    """Real service/metadata/framing; finite native observations are synthetic.

    The broker connector seam does not prove real broker acquisition behavior.
    Accepted42 supplies that separately. Every identity is the registered candidate's.
    """
    import socket
    import tempfile
    import threading
    from pathlib import Path
    from app.workers import (
        broker,
        listener,
        provider_metadata as pm,
        provider_service as ps,
    )
    from app.workers.extension_channel import extension_channel
    from app.deployment import files as f, mounts as m
    from app.tests.test_extension_worker_metadata import _write
    from app.tests.test_provider_lineage import shipped_schema_bytes

    tree = actual.tree
    root, spec = extension_channel(
        instance_id=actual.profile.instance_id, slot_number=actual.payload["slot_id"]
    )
    identity = next(
        d["content"]
        for d in actual.bundle.as_dict()["documents"]
        if d["document_kind"] == "provenance"
    )["platforms"][0]["build_identity"]
    assert identity["entrypoint"] == {
        "sha256": sha256(WORKER_BYTES).hexdigest(),
        "size_bytes": len(WORKER_BYTES),
    }
    alias = Path(
        tempfile.mkdtemp(
            prefix="dt-provider-",
            dir="/private/tmp" if sys.platform == "darwin" else None,
        )
    )
    service = thread = None
    box = {}
    with monkeypatch.context() as patch:
        try:
            raw_socket = socket.socket
            socket_live = set()
            box["socket_peak"] = 0

            class MeasuredSocket(raw_socket):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    socket_live.add(id(self))
                    box["socket_peak"] = max(box["socket_peak"], len(socket_live))

                def close(self):
                    try:
                        return super().close()
                    finally:
                        socket_live.discard(id(self))

            patch.setattr(socket, "socket", MeasuredSocket)
            (alias / "endpoint").symlink_to(
                tree.actual(root.endpoint_path), target_is_directory=True
            )
            patch.setattr(
                listener,
                "_anchored_socket_path",
                lambda fd, pair, name: str(alias / "endpoint" / name),
            )
            patch.setattr(
                listener,
                "_process_identity",
                lambda: (
                    root.responder_uid,
                    root.responder_gid,
                    frozenset({root.pair_gid}),
                ),
            )

            def chown(path, uid, gid, **kw):
                info = tree.raw_stat(path, **kw)
                tree.metadata[(info.st_dev, info.st_ino)] = (uid, gid)

            def fchown(fd, uid, gid):
                info = tree.raw_fstat(fd)
                prior = tree.metadata.get(
                    (info.st_dev, info.st_ino), (info.st_uid, info.st_gid)
                )
                tree.metadata[(info.st_dev, info.st_ino)] = (
                    prior[0] if uid == -1 else uid,
                    prior[1] if gid == -1 else gid,
                )

            patch.setattr(os, "chown", chown)
            patch.setattr(os, "fchown", fchown)
            patch.setattr(
                broker,
                "_extension_server_handshake",
                lambda sock, channel, secret, **kw: (
                    broker._extension_server_handshake_impl(
                        sock, channel, secret, verify_peer=False, **kw
                    )
                ),
            )
            patch.setattr(
                broker,
                "_extension_client_handshake",
                lambda sock, channel, secret, **kw: (
                    broker._extension_client_handshake_impl(
                        sock, channel, secret, verify_peer=False, **kw
                    )
                ),
            )

            def connect(channel, *, local_service, deadline):
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    sock.connect(str(alias / "endpoint" / channel.socket_name))
                    return (
                        sock,
                        broker._endpoint_identity(
                            os.stat(alias / "endpoint" / channel.socket_name)
                        ),
                        broker.PeerCredentials(
                            pid=4242, uid=root.responder_uid, gid=root.responder_gid
                        ),
                    )
                except BaseException:
                    sock.close()
                    raise

            patch.setattr(broker, "connect_verified", connect)
            side = {"worker": None}
            patch.setattr(
                listener,
                "_read_mountinfo",
                lambda: m.parse_mountinfo(
                    f"1 1 {tree.device} / {root.pair_root} {'rw' if threading.get_ident() == side['worker'] else 'ro'},relatime shared:1 - tmpfs tmpfs rw\n".encode()
                ),
            )
            image = tree.base / "provider-worker-image"
            prefix = image / "opt/deeptwin-extension"
            _write(prefix / "bin/worker", WORKER_BYTES, 0o555)
            _write(
                prefix / "identity/build-identity-v2.json",
                canonical_json(identity),
                0o444,
            )
            for role, raw in zip(
                ("config", "request", "result", "error"),
                shipped_schema_bytes(),
                strict=True,
            ):
                _write(
                    prefix / "ports/provider-port-v1" / (role + ".schema.json"),
                    raw,
                    0o444,
                )
            for directory in (
                image,
                image / "opt",
                prefix,
                prefix / "bin",
                prefix / "identity",
                prefix / "ports",
                prefix / "ports/provider-port-v1",
            ):
                directory.chmod(0o755)
            remapped_open = f.open_directory
            patch.setattr(
                f,
                "open_directory",
                lambda path, **kw: (
                    actual.original_open_directory(path, **kw)
                    if Path(path).is_relative_to(image)
                    else remapped_open(path, **kw)
                ),
            )
            patch.setattr(pm, "EXTENSION_ROOT", image)
            patch.setattr(pm, "EXTENSION_PREFIX", prefix)
            patch.setattr(pm, "_expected_owner", lambda: (os.getuid(), os.getgid()))
            patch.setattr(pm, "_native_platform", lambda: identity["platform"])
            patch.setattr(
                pm,
                "_credentials",
                lambda: (
                    root.responder_uid,
                    root.responder_uid,
                    root.responder_gid,
                    root.responder_gid,
                ),
            )
            patch.setattr(
                pm,
                "_read_mountinfo",
                lambda: m.parse_mountinfo(
                    f"1 1 {tree.device} / {image} ro - tmpfs tmpfs rw\n".encode()
                ),
            )
            service = ps.open_provider_worker_service(
                instance_id=actual.profile.instance_id,
                slot_number=actual.payload["slot_id"],
            )

            def serve():
                side["worker"] = threading.get_ident()
                try:
                    box["served"] = [
                        service.serve_one(broker.Deadline.after_ms(5000))
                        for _ in range(2)
                    ]
                except BaseException as error:
                    box["error"] = error

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            yield identity, box
            thread.join(6)
            assert (
                not thread.is_alive()
                and box.get("served") == [1, 1]
                and "error" not in box
            ), box
        finally:
            if thread is not None:
                thread.join(6)
            if service is not None:
                service.close()
            (alias / "endpoint").unlink(missing_ok=True)
            alias.rmdir()


def signed_receipt(actual, request, *, outcome="succeeded", preservation=None):
    """Public synthetic signature and claimed native observations, not native proof."""
    stage = request["effect_payload"]
    instant = request["created_at"]
    target = {
        "service_identity": stage["new_service_effect"]["service_identity"],
        "manifest_digest": stage["manifest_digest"],
        "service_descriptor_digest": stage["service_descriptor_digest"],
        "selected_platform_entry_digest": sha256(
            canonical_json(stage["selected_platform_entry"])
        ).hexdigest(),
        "image_manifest_digest": stage["selected_platform_entry"]["manifest_digest"],
    }
    failure = (
        None
        if outcome == "succeeded"
        else "effect_failed"
        if outcome == "failed"
        else "observation_unavailable"
    )
    service = (
        {
            "presence": "present",
            **target,
            "reachable_after_effect": False,
            "observed_at": instant,
        }
        if outcome == "succeeded"
        else {"presence": "absent"}
        if outcome == "failed"
        else {
            "presence": "unknown",
            **{"expected_" + k: v for k, v in target.items()},
            "failure_class": failure,
            "observed_at": instant,
        }
    )
    trust = parse_canonical(actual.tree.bundle[12][1])
    if preservation is None:
        observations = []
        for old in stage["preserved_inventory"]["installations"]:
            slot = c.slot(actual.profile.instance_id, old["slot_id"])
            snapshot = {
                "observed_at": instant,
                "engine_id": "public-synthetic-engine",
                "container_id": "1" * 64,
                "image_config_digest": "sha256:" + "2" * 64,
                "started_at": instant[:-1] + "000000Z",
                "restart_count": 0,
                "init_pid": 4242,
                "configured_uid": slot["uid"],
                "configured_gid": slot["gid"],
                "socket_volume": slot["socket_mount"]["volume_name"],
                "socket_path": slot["socket_mount"]["container_path"],
                "socket_read_only": False,
            }
            observations.append(
                {
                    "slot_id": old["slot_id"],
                    "service_identity": old["service_identity"],
                    "before": dict(snapshot),
                    "after": dict(snapshot),
                }
            )
        preservation = {"state": "preserved", "observations": observations}
    value = {
        "schema": "deployment-provider-receipt-v1",
        "domain": "deeptwin-deployment-provider-receipt-v1",
        **{
            k: request[k]
            for k in (
                "request_id",
                "request_digest",
                "request_nonce",
                "kind",
                "instance_id",
                "origin_profile_digest",
            )
        },
        "deployment_profile_id": actual.profile.deployment_profile_id,
        "operator_adapter": "deeptwin-provider-stage-operator-v1",
        "operator_version": "1.0.0",
        "effect_result": {
            "schema_id": "deeptwin.provider-stage-result.v1",
            **{
                k: stage[k]
                for k in (
                    "extension_id",
                    "expected_installation_head",
                    "expected_next_installation_revision",
                    "stage_profile",
                    "source_context",
                    "geometry",
                    "preserved_inventory_sha256",
                )
            },
            "old_service": {"presence": "absent"},
            "new_service": service,
            "preservation": preservation,
        },
        "started_at": instant,
        "completed_at": instant,
        "outcome": outcome,
        "failure_class": failure,
        "claimed_facts": [],
        "verified_facts": [],
        "unverified_facts": [],
        "key_id": trust["keys"][0]["key_id"],
        "trust_set_digest": urlsafe_b64encode(
            sha256(actual.tree.bundle[12][1]).digest()
        )
        .rstrip(b"=")
        .decode(),
        "trust_class": "instance_operator",
    }
    return resign(actual, value)


def resign(actual, value):
    unsigned = {k: v for k, v in value.items() if k != "signature"}
    signature = actual.signing_key.sign(canonical_json(unsigned)).signature
    return canonical_json(
        {**unsigned, "signature": urlsafe_b64encode(signature).rstrip(b"=").decode()}
    )


def install_receipt(actual, raw):
    from pathlib import Path

    digest = sha256(raw).digest()
    actual.tree.write(
        Path("/run/deeptwin/provider-deployment-receipts/receipts")
        / (digest.hex() + ".json"),
        raw,
        20113,
        21201,
    )
    return urlsafe_b64encode(digest).rstrip(b"=").decode()


@contextmanager
def provider_receipt_context(
    tmp_path,
    monkeypatch,
    *,
    capacity=2,
    portable=False,
    slot_id=1,
    legacy_staged=False,
    defer_legacy_stage=False,
    historical_v3=False,
    legacy_case="valid_succeeded_present",
):
    from app.deployment import files as source_files

    original_open_directory = source_files.open_directory
    tree = publication_tree(tmp_path, monkeypatch, capacity=capacity, portable=portable)
    sessions = ExitStack()
    session = None
    if legacy_staged:
        from app.deployment.provider_source_render import render_provider_sources
        from app.tests.deployment_receipt_session_fixture import OwnedReceiptSession
        from app.tests.provider_source_fixture import case
        from app.tests.provider_source_reader_fixture import ORIGINALS

        session = sessions.enter_context(OwnedReceiptSession(tree.profile))
        kwargs, _, _ = case(capacity=capacity, portable=portable)
        kwargs["original_trust_bytes"] = session.trust_bytes
        receipt_instance = parse_canonical(kwargs["original_receipt_instance_bytes"])
        receipt_instance["trust_set_sha256"] = sha256(session.trust_bytes).hexdigest()
        kwargs["original_receipt_instance_bytes"] = canonical_json(receipt_instance)
        instance = parse_canonical(kwargs["provider_instance_bytes"])
        instance["original_receipt_instance_sha256"] = sha256(
            kwargs["original_receipt_instance_bytes"]
        ).hexdigest()
        kwargs["provider_instance_bytes"] = canonical_json(instance)
        rendered = render_provider_sources(**kwargs)
        tree.bundle, tree.old = rendered.bundle_files, rendered.original_artifacts
        tree.install_bundle(tree.bundle)
        for root, leaf, gid, index in ORIGINALS:
            tree.write(root / leaf, tree.bundle[index][1], 0, gid)
    # Public, fixed test-only signing material, installed BEFORE real startup.
    from nacl.signing import SigningKey
    from app.deployment.provider_source_render import render_provider_sources
    from app.tests.provider_source_fixture import case
    from app.tests.provider_source_reader_fixture import ORIGINALS

    signing_key = SigningKey(bytes(range(32)))
    kwargs, _, _ = case(capacity=capacity, portable=portable)
    for key, index in (
        ("original_trust_bytes", 6),
        ("original_receipt_instance_bytes", 5),
    ):
        kwargs[key] = tree.bundle[index][1]
    trust = parse_canonical(kwargs["provider_trust_bytes"])
    trust["keys"][0]["public_key"] = (
        urlsafe_b64encode(bytes(signing_key.verify_key)).rstrip(b"=").decode()
    )
    kwargs["provider_trust_bytes"] = canonical_json(trust)
    instance = parse_canonical(kwargs["provider_instance_bytes"])
    instance["provider_trust_sha256"] = sha256(
        kwargs["provider_trust_bytes"]
    ).hexdigest()
    instance["original_receipt_instance_sha256"] = sha256(
        kwargs["original_receipt_instance_bytes"]
    ).hexdigest()
    kwargs["provider_instance_bytes"] = canonical_json(instance)
    rendered = render_provider_sources(**kwargs)
    tree.bundle, tree.old = rendered.bundle_files, rendered.original_artifacts
    tree.install_bundle(tree.bundle)
    for root, leaf, gid, index in ORIGINALS:
        tree.write(root / leaf, tree.bundle[index][1], 0, gid)
    from app.deployment import receipt_sources

    for root, child, uid, ro in (
        (receipt_sources.INCOMING_ROOT, "receipts", 20113, True),
        (receipt_sources.CONSUMED_ROOT, "consumed", 20102, False),
    ):
        tree.directory(root, uid, 21201)
        tree.directory(root / child, uid, 21201)
        tree.mount(root, ro)
    tree.directory(c.OUTBOX_ROOT, 20102, 21201)
    tree.mount(c.OUTBOX_ROOT, False)
    for name in ("requests", "cancelled"):
        tree.directory(c.OUTBOX_ROOT / name, 20102, 21201)
    for number in range(1, capacity + 1):
        path = c.IPC_ROOT / f"xs{number:02}"
        tree.directory(path, 0, 23000 + number)
        tree.actual(path).chmod(0o710)
        tree.mount(path, True)
        for name, size in (("generation.lock", 0), ("boot-secret", 32)):
            tree.write(path / name, b"a" * size, 0, 23000 + number, mode=0o640)
        tree.directory(path / "endpoint", 22000 + number, 23000 + number)
        tree.actual(path / "endpoint").chmod(0o2710)
    from app.workers import ipc_root

    original_open = ipc_root._open_absolute_directory
    monkeypatch.setattr(
        ipc_root,
        "_open_absolute_directory",
        lambda path, **kw: original_open(tree.actual(path), **kw),
    )
    monkeypatch.setattr(os, "fstat", lambda fd: tree.observed(tree.raw_fstat(fd)))
    monkeypatch.setattr(
        os, "stat", lambda *a, **kw: tree.observed(tree.raw_stat(*a, **kw))
    )
    data, arguments = app_arguments(tree)
    capability = urlsafe_b64encode(b"S" * 32).rstrip(b"=").decode()
    arguments["deployment_config"] = build_bootstrap_configuration(
        profile=tree.profile, verifier_b64u=derive_capability_verifier(capability)
    )
    pins = parse_canonical(tree.old.prepare_artifacts.pins_bytes)
    arguments["first_party_startup_values"].update(
        {
            "DEEPTWIN_PREPARE_RECIPE_SHA256": pins["recipe_sha256"],
            "DEEPTWIN_PREPARE_INSTANCE_SHA256": pins["instance_sha256"],
            "DEEPTWIN_TOPOLOGY_SHA256": pins["topology_sha256"],
            "DEEPTWIN_EXCHANGE_SHA256": pins["exchange_sha256"],
        }
    )
    receipt_pins = parse_canonical(tree.old.pins_bytes)
    arguments["first_party_startup_values"].update(
        {
            "DEEPTWIN_RECEIPT_RECIPE_SHA256": receipt_pins["receipt_recipe_sha256"],
            "DEEPTWIN_RECEIPT_INSTANCE_SHA256": receipt_pins["receipt_instance_sha256"],
            "DEEPTWIN_DEPLOYMENT_TRUST_SHA256": receipt_pins["trust_sha256"],
            "DEEPTWIN_RECEIPT_INGRESS_SHA256": receipt_pins["ingress_sha256"],
            "DEEPTWIN_CONSUMPTION_EXCHANGE_SHA256": receipt_pins[
                "consumption_exchange_sha256"
            ],
        }
    )
    baseline = len(tree.live)
    from app.api import deployment_prepare as assembly

    actual_open_context = assembly.open_provider_source_context
    tree.source_open_count = 0

    def measured_open_context(**kwargs):
        tree.source_open_count += 1
        tree.caller_baseline = len(tree.live)
        context = actual_open_context(**kwargs)
        tree.provider_retained = len(tree.live) - tree.caller_baseline
        return context

    monkeypatch.setattr(assembly, "open_provider_source_context", measured_open_context)
    app = create_app(data, **arguments)
    try:
        with TestClient(app, base_url=tree.profile.http_origin) as client:
            csrf = bootstrap_client(client, tree.profile, capability)
            request = bound_request(app, client, tree.profile, csrf)
            exports = app.state.first_party_exports
            registry = exports["extension-candidates.registry"]
            slot = parse_canonical(tree.bundle[9][1])["slots"][slot_id - 1]
            bundle = worker_candidate(slot)
            registered = registry.register(request, bundle.as_dict())
            actual = SimpleNamespace(
                app=app,
                client=client,
                csrf=csrf,
                request=request,
                read_request=replace(request, method="GET"),
                profile=tree.profile,
                domain=app.state.domain_store,
                owner=app.state.owner_authority,
                registry=registry,
                service=exports["deployment-prepare.service"],
                context=exports["deployment-provider.source-context"],
                tree=tree,
                bundle=bundle,
                baseline=baseline,
                original_open_directory=original_open_directory,
                arguments=arguments,
                data=data,
                actual=tree,
                session=session,
                signing_key=signing_key,
                payload={
                    "command_id": str(uuid4()),
                    "kind": "extension_stage",
                    "candidate_id": registered["candidate_ref"]["candidate_id"],
                    "slot_id": slot_id,
                    "expires_in_seconds": 60,
                    "source_context_sha256": sha256(tree.bundle[16][1]).hexdigest(),
                },
            )
            if historical_v3:
                from app.tests.test_provider_prepare_migration import install_empty_v3

                install_empty_v3(actual)

            def stage_legacy():
                assert legacy_staged
                from app.tests.deployment_receipt_import_fixture import signed_case
                from app.tests.test_deployment_consume import (
                    StagedWorker,
                    consume_payload,
                    lineage_bundle,
                )

                tool = registry.register(request, lineage_bundle()[0].as_dict())
                old_payload = {
                    "command_id": str(uuid4()),
                    "kind": "extension_stage",
                    "candidate_id": tool["candidate_ref"]["candidate_id"],
                    "slot_id": 1,
                    "expires_in_seconds": 86400,
                }
                prepared, command, _, _ = signed_case(
                    actual, monkeypatch, case_name=legacy_case, payload=old_payload
                )
                imported = actual.service.import_receipt(
                    request, prepared["request_id"], command
                )
                actual.legacy_request = prepared
                actual.legacy_payload = old_payload
                if legacy_case != "valid_succeeded_present":
                    actual.legacy_receipt = imported
                    return
                tree.original_stat, tree.original_fstat = tree.raw_stat, tree.raw_fstat
                tree.original_open_directory = original_open_directory
                with monkeypatch.context() as worker_seams:

                    def worker_chown(fd, uid, gid):
                        info = tree.raw_fstat(fd)
                        old_uid, old_gid = tree.metadata.get(
                            (info.st_dev, info.st_ino), (info.st_uid, info.st_gid)
                        )
                        tree.metadata[(info.st_dev, info.st_ino)] = (
                            old_uid if uid == -1 else uid,
                            old_gid if gid == -1 else gid,
                        )

                    worker_seams.setattr(os, "fchown", worker_chown)
                    worker = StagedWorker(tree, tree.profile, worker_seams)
                    try:
                        worker.start()
                        actual.legacy_receipt = actual.service.consume_receipt(
                            request,
                            prepared["request_id"],
                            consume_payload(prepared, command),
                        )
                    finally:
                        worker.stop()
                actual.legacy_request = prepared

            actual.stage_legacy = stage_legacy
            if legacy_staged and not defer_legacy_stage:
                stage_legacy()
            yield actual
    finally:
        # Do not mask retained-descriptor failures by closing leaked handles.
        primary = sys.exc_info()[0]
        sessions.close()
        if primary is None:
            assert len(tree.live) == baseline, tree.paths
