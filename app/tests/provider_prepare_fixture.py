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


@contextmanager
def provider_context(
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
            bundle, _ = _provider_candidate(slot)
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
                arguments=arguments,
                actual=tree,
                session=session,
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
