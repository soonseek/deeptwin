"""Actual temporary staged-provider composition for provider conformance tests.

All worker image, receipt, mount and native observations are public synthetic fixtures; they do
not establish native isolation, qualification, packaging provenance, or live provider operation.
"""

from contextlib import contextmanager
import sys
import threading
from types import SimpleNamespace
from uuid import uuid4

from app.domain.refs import EntityRef
from app.tests.provider_receipt_fixture import (
    install_receipt,
    provider_receipt_context,
    provider_worker,
    signed_receipt,
)


@contextmanager
def staged_conformance_app(tmp_path, monkeypatch, *, portable=False, slot_id=1):
    manager = provider_receipt_context(tmp_path.resolve(), monkeypatch,
                                       portable=portable, slot_id=slot_id)
    actual = manager.__enter__()
    owner = [manager, False]
    try:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(actual.read_request,
                                               prepared["request_id"])["request"]
        receipt_digest = install_receipt(actual, signed_receipt(actual, request))
        selector = {"command_id": str(uuid4()), "request_digest": prepared["request_digest"],
                    "receipt_digest": receipt_digest, "expected_revision": 1}
        actual.service.import_provider_receipt(actual.request, prepared["request_id"], selector)
        consume = {**selector, "command_id": str(uuid4()), "expected_revision": 2}
        with provider_worker(actual, monkeypatch):
            accepted = actual.service.consume_provider_receipt(
                actual.request, prepared["request_id"], consume)
        assert accepted["state"] == "accepted" and accepted["revision"] == 3
        subject = SimpleNamespace(client=actual.client, profile=actual.profile, csrf=actual.csrf,
            domain=actual.domain,
            service=actual.app.state.first_party_exports.get("provider-conformance.service"),
            prepare=actual.service,
            installation_ref=EntityRef.from_dict(accepted["installation_ref"]),
            path=actual.profile.base_path.rstrip("/") +
                 "/api/v1/extensions/provider-conformance", actual=actual,
            _receipt_owner=owner, _conformance_worker_owner=None)
        yield subject
    except BaseException:
        if not owner[1]:
            owner[1] = True
            manager.__exit__(*sys.exc_info())
        raise
    else:
        if not owner[1]:
            owner[1] = True
            manager.__exit__(None, None, None)


@contextmanager
def restart_without_provider(subject, monkeypatch):
    """Close the original app and reopen its exact store without the live provider source."""
    from starlette.testclient import TestClient
    from app.deployment.provider_sources import PROVIDER_CONTEXT_STARTUP_KEY
    from app.server import create_app

    owner = subject._receipt_owner
    if owner[1]:
        raise AssertionError("provider fixture already restarted")
    cookies = dict(subject.client.cookies)
    old_domain = subject.domain
    arguments = dict(subject.actual.arguments)
    values = dict(arguments["first_party_startup_values"])
    values.pop(PROVIDER_CONTEXT_STARTUP_KEY, None)
    arguments["first_party_startup_values"] = values
    worker_owner = subject._conformance_worker_owner
    if (type(worker_owner) is not list or len(worker_owner) != 3
            or worker_owner[2]
            or type(worker_owner[1].completion_count) is not int
            or not 0 <= worker_owner[1].completion_count <= 6):
        raise AssertionError("exercised provider worker owner is not retained")
    worker_owner[2] = True
    worker_owner[0].__exit__(None, None, None)
    stopped_worker_count = worker_owner[1].completion_count
    owner[1] = True
    owner[0].__exit__(None, None, None)

    application = create_app(subject.actual.data, **arguments)
    with TestClient(application, base_url=subject.profile.http_origin) as client:
        client.cookies.update(cookies)
        exports = application.state.first_party_exports
        reopened_actual = SimpleNamespace(app=application, client=client,
            owner=application.state.owner_authority, domain=application.state.domain_store,
            service=exports["deployment-prepare.service"],
            context=exports["deployment-provider.source-context"])
        reopened = SimpleNamespace(client=client, profile=subject.profile, csrf=subject.csrf,
            domain=application.state.domain_store,
            service=exports["provider-conformance.service"],
            prepare=exports["deployment-prepare.service"],
            installation_ref=subject.installation_ref, path=subject.path,
            actual=reopened_actual, _receipt_owner=[None, True],
            _conformance_worker_owner=None,
            stopped_worker_completion_count=stopped_worker_count)
        assert reopened.domain is not old_domain
        assert exports["deployment-provider.source-context"] is None
        yield reopened


WORKER_BUDGET_MS = 30_000  # the listener's connection window (app/workers/listener.py)


@contextmanager
def _retained_provider_conformance_worker(subject, monkeypatch, *, serve_count=6,
                                           allow_error=False):
    """Retain the exact exercised B worker owner until restart consumes it."""
    if subject._conformance_worker_owner is not None:
        raise AssertionError("provider conformance worker already retained")
    manager = _provider_conformance_worker(subject.actual, monkeypatch,
        serve_count=serve_count, allow_error=allow_error)
    identity, state = manager.__enter__()
    owner = [manager, state, False]
    subject._conformance_worker_owner = owner
    try:
        yield identity, state
    except BaseException:
        if not owner[2]:
            owner[2] = True
            manager.__exit__(*sys.exc_info())
        raise
    else:
        if not owner[2]:
            owner[2] = True
            manager.__exit__(None, None, None)


@contextmanager
def _provider_conformance_worker(actual, monkeypatch, *, serve_count=6, allow_stopped=False,
                                 allow_error=False):
    """Own one actual B worker service/thread for exactly the reached connection count."""
    import os
    import socket
    import tempfile
    from hashlib import sha256
    from pathlib import Path
    from app.deployment import files as f, mounts as m
    from app.domain.refs import canonical_json
    from app.tests.provider_receipt_fixture import WORKER_BYTES
    from app.tests.test_extension_worker_metadata import _write
    from app.tests.test_provider_lineage import shipped_schema_bytes
    from app.workers import broker, listener, provider_metadata as pm, provider_service as ps
    from app.workers.extension_channel import extension_channel

    assert (type(serve_count) is int and 1 <= serve_count <= 6
            and type(allow_stopped) is bool and type(allow_error) is bool
            and not (allow_stopped and allow_error))
    state = SimpleNamespace(completion_count=0, finished=threading.Event())
    tree = actual.tree
    root, _ = extension_channel(instance_id=actual.profile.instance_id,
                                slot_number=actual.payload["slot_id"])
    identity = next(document["content"] for document in actual.bundle.as_dict()["documents"]
                    if document["document_kind"] == "provenance")["platforms"][0]["build_identity"]
    assert identity["entrypoint"] == {"sha256": sha256(WORKER_BYTES).hexdigest(),
                                      "size_bytes": len(WORKER_BYTES)}
    alias = Path(tempfile.mkdtemp(prefix="dt-conformance-provider-",
        dir="/private/tmp" if sys.platform == "darwin" else None))
    service = thread = None
    box = {"socket_peak": 0}
    with monkeypatch.context() as patch:
        try:
            raw_socket = socket.socket
            socket_live = set()

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
            (alias / "endpoint").symlink_to(tree.actual(root.endpoint_path), target_is_directory=True)
            patch.setattr(listener, "_anchored_socket_path",
                          lambda fd, pair, name: str(alias / "endpoint" / name))
            patch.setattr(listener, "_process_identity",
                          lambda: (root.responder_uid, root.responder_gid,
                                   frozenset({root.pair_gid})))

            def chown(path, uid, gid, **kwargs):
                info = tree.raw_stat(path, **kwargs)
                tree.metadata[(info.st_dev, info.st_ino)] = (uid, gid)

            def fchown(fd, uid, gid):
                info = tree.raw_fstat(fd)
                prior = tree.metadata.get((info.st_dev, info.st_ino),
                                          (info.st_uid, info.st_gid))
                tree.metadata[(info.st_dev, info.st_ino)] = (
                    prior[0] if uid == -1 else uid, prior[1] if gid == -1 else gid)

            patch.setattr(os, "chown", chown)
            patch.setattr(os, "fchown", fchown)
            patch.setattr(broker, "_extension_server_handshake",
                lambda sock, channel, secret, **kwargs: broker._extension_server_handshake_impl(
                    sock, channel, secret, verify_peer=False, **kwargs))
            patch.setattr(broker, "_extension_client_handshake",
                lambda sock, channel, secret, **kwargs: broker._extension_client_handshake_impl(
                    sock, channel, secret, verify_peer=False, **kwargs))

            def connect(channel, *, local_service, deadline):
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    sock.connect(str(alias / "endpoint" / channel.socket_name))
                    return (sock, broker._endpoint_identity(os.stat(
                        alias / "endpoint" / channel.socket_name)),
                        broker.PeerCredentials(pid=4242, uid=root.responder_uid,
                                               gid=root.responder_gid))
                except BaseException:
                    sock.close()
                    raise

            patch.setattr(broker, "connect_verified", connect)
            side = {"worker": None}
            patch.setattr(listener, "_read_mountinfo", lambda: m.parse_mountinfo(
                f"1 1 {tree.device} / {root.pair_root} "
                f"{'rw' if threading.get_ident() == side['worker'] else 'ro'},relatime "
                "shared:1 - tmpfs tmpfs rw\n".encode()))
            image = tree.base / "provider-worker-image"
            prefix = image / "opt/deeptwin-extension"
            if image.exists():
                for path in (prefix / "bin/worker", prefix / "identity/build-identity-v2.json",
                        *(prefix / "ports/provider-port-v1" / (role + ".schema.json")
                          for role in ("config", "request", "result", "error"))):
                    path.chmod(0o600)
                for path in (image, image / "opt", prefix, prefix / "bin", prefix / "identity",
                             prefix / "ports", prefix / "ports/provider-port-v1"):
                    path.chmod(0o700)
            _write(prefix / "bin/worker", WORKER_BYTES, 0o555)
            _write(prefix / "identity/build-identity-v2.json", canonical_json(identity), 0o444)
            for role, raw in zip(("config", "request", "result", "error"),
                                 shipped_schema_bytes(), strict=True):
                _write(prefix / "ports/provider-port-v1" / (role + ".schema.json"), raw, 0o444)
            for directory in (image, image / "opt", prefix, prefix / "bin", prefix / "identity",
                              prefix / "ports", prefix / "ports/provider-port-v1"):
                directory.chmod(0o755)
            remapped_open = f.open_directory
            patch.setattr(f, "open_directory", lambda path, **kwargs: (
                actual.original_open_directory(path, **kwargs)
                if Path(path).is_relative_to(image) else remapped_open(path, **kwargs)))
            patch.setattr(pm, "EXTENSION_ROOT", image)
            patch.setattr(pm, "EXTENSION_PREFIX", prefix)
            patch.setattr(pm, "_expected_owner", lambda: (os.getuid(), os.getgid()))
            patch.setattr(pm, "_native_platform", lambda: identity["platform"])
            patch.setattr(pm, "_credentials", lambda: (root.responder_uid, root.responder_uid,
                                                        root.responder_gid, root.responder_gid))
            patch.setattr(pm, "_read_mountinfo", lambda: m.parse_mountinfo(
                f"1 1 {tree.device} / {image} ro - tmpfs tmpfs rw\n".encode()))
            service = ps.open_provider_worker_service(instance_id=actual.profile.instance_id,
                                                       slot_number=actual.payload["slot_id"])

            def serve():
                side["worker"] = threading.get_ident()
                try:
                    for _ in range(serve_count):
                        # the product's own connection window (listener: 30 s), never a
                        # budget so short that — under a frozen clock — it becomes a 5 s
                        # per-socket-operation timeout the loaded suite exceeds
                        state.completion_count += service.serve_one(
                            broker.Deadline.after_ms(WORKER_BUDGET_MS))
                except BaseException as error:
                    box["error"] = error
                finally:
                    state.finished.set()

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            yield identity, state
            if allow_stopped:
                service.listener.close()
            thread.join(WORKER_BUDGET_MS / 1000 + 1)
            assert not thread.is_alive(), box
            if allow_stopped:
                assert state.completion_count < serve_count
                assert isinstance(box.pop("error", None), ps.ProviderServiceError)
            elif allow_error:
                error = box.pop("error", None)
                assert (state.completion_count == serve_count and error is None
                        or state.completion_count < serve_count
                        and isinstance(error, ps.ProviderServiceError))
            else:
                assert "error" not in box, box
                assert state.completion_count == serve_count
        finally:
            if service is not None:
                if thread is not None and thread.is_alive():
                    service.listener.close()
                    thread.join(6)
                if not service.closed:
                    service.close()
            if thread is not None:
                thread.join(6)
            (alias / "endpoint").unlink(missing_ok=True)
            alias.rmdir()
