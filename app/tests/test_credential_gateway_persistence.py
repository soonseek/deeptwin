"""T090 lost-response, race and lost-ingress persistence over the credential gateway channel.

The gateway service answers each `credential_op` over real authenticated broker
frames (socket pairs, the same harness shape as test_credential_gateway_service).
A lost response is simulated at the one place it can happen after a commit: the
service's reply write closes the connection instead of answering, so the vault has
durably committed while the control plane observes only a sanitized channel
failure. Recovery follows the custody contract — `query_record`, or a replay under
the same command id, never a new command or a new secret. The vault itself is the
oracle for every outcome.
"""

from __future__ import annotations

import multiprocessing
import socket
import sqlite3
import threading
from hashlib import sha256
from uuid import uuid4

import pytest

from app.tests.test_credential_custody import _crash_store, metadata
from app.tests.test_credential_gateway_service import (
    REQUESTER_BOOT,
    RESPONDER_BOOT,
    channel_spec,
)
from app.tests.test_credential_root import initialized
from app.workers import broker, credential_gateway_service
from app.workers.credential_channel import CredentialGatewayClient, GatewayServiceError
from app.workers.credential_gateway_service import CredentialGatewayService
from app.workers.credential_vault import CredentialVault

SECRET = b"sk-synthetic-persistence-original-01"
OTHER = b"sk-synthetic-persistence-replacement-02"
BOOT_SECRET = broker.BootSecret(b"p" * broker.AUTH_SECRET_BYTES)


class Gateway:
    """One vault served per connection over real handshakes; reopenable."""

    def __init__(self, tmp_path):
        self.args = initialized(tmp_path)
        self.tmp_path = tmp_path
        self.spec = channel_spec(tmp_path / "pair")
        self.vault = CredentialVault(**self.args)
        self.threads = []
        self.lost = []  # operations whose committed response was dropped

    def reopen(self):
        self.vault.close()
        self.vault = CredentialVault(**self.args)

    def _transport(self):
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        service = CredentialGatewayService(self.vault, self.spec, BOOT_SECRET)
        errors = []

        def serve():
            try:
                session = broker._server_handshake_impl(
                    right, self.spec, BOOT_SECRET, requester_boot_id=REQUESTER_BOOT,
                    responder_boot_id=RESPONDER_BOOT, deadline=broker.Deadline.after_ms(10_000),
                    verify_peer=False)
                codec = broker.FrameCodec(self.spec, session, local_service=self.spec.responder_service)
                try:
                    service.serve_one(right, codec, deadline=broker.Deadline.after_ms(10_000))
                finally:
                    codec.close()
            except BaseException as exc:  # noqa: BLE001 - surfaced at teardown
                errors.append(exc)
            finally:
                right.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.threads.append((thread, errors))
        session = broker._client_handshake_impl(
            left, self.spec, BOOT_SECRET, requester_boot_id=REQUESTER_BOOT,
            responder_boot_id=RESPONDER_BOOT, deadline=broker.Deadline.after_ms(10_000),
            verify_peer=False)
        return left, broker.FrameCodec(self.spec, session, local_service=self.spec.requester_service)

    def client(self):
        return CredentialGatewayClient(self._transport, deadline_ms=10_000)

    def send_client(self, port, *, on_serve=None):
        """A provider-send client whose every dialogue is served, over real authenticated
        frames on a socket pair, by a `ProviderSendService` over this same vault, bound to a
        loopback upstream on `port` (the gateway's send path; test transport only)."""
        from app.tests.support.transport_manifest import loopback_binding
        from app.workers.provider_gateway import CredentialedProviderTransport
        from app.workers.provider_send_client import ProviderSendClient
        from app.workers.provider_send_service import ProviderSendService

        # the shipped manifest's binding, its origin replaced by the loopback mock (T087)
        binding = loopback_binding(port)

        def factory():
            left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            service = ProviderSendService(CredentialedProviderTransport(self.vault, binding))
            if on_serve is not None:
                on_serve(service)
            errors = []

            def serve():
                try:
                    session = broker._server_handshake_impl(
                        right, self.spec, BOOT_SECRET, requester_boot_id=REQUESTER_BOOT,
                        responder_boot_id=RESPONDER_BOOT, deadline=broker.Deadline.after_ms(10_000),
                        verify_peer=False)
                    codec = broker.FrameCodec(self.spec, session, local_service=self.spec.responder_service)
                    try:
                        service.serve_authenticated(right, codec, deadline=broker.Deadline.after_ms(10_000))
                    finally:
                        codec.close()
                except BaseException as exc:  # noqa: BLE001 - surfaced at teardown
                    errors.append(exc)
                finally:
                    right.close()

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            self.threads.append((thread, errors))
            session = broker._client_handshake_impl(
                left, self.spec, BOOT_SECRET, requester_boot_id=REQUESTER_BOOT,
                responder_boot_id=RESPONDER_BOOT, deadline=broker.Deadline.after_ms(10_000),
                verify_peer=False)
            return left, broker.FrameCodec(self.spec, session, local_service=self.spec.requester_service)

        return ProviderSendClient(transport_factory=factory, deadline_ms=10_000)

    def counts(self):
        path = self.args["records_directory"] / "journal.sqlite"
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            return tuple(db.execute("SELECT count(*) FROM " + table).fetchone()[0]
                         for table in ("commands", "nonces", "receipts", "retirements"))

    def plaintext_of(self, meta):
        """Gateway-private authenticated open (a self-check, never a provider binding)."""
        return self.vault._root.open(self.vault._published(meta), meta)

    def close(self):
        for thread, errors in self.threads:
            thread.join(10)
            assert not thread.is_alive()
            assert errors == []
        self.vault.close()


@pytest.fixture
def gateway(tmp_path):
    subject = Gateway(tmp_path)
    yield subject
    subject.close()


@pytest.fixture
def lose_responses(monkeypatch, gateway):
    """Arm the next `n` service replies to be lost after the operation committed."""

    original = credential_gateway_service._write_logical_connection
    armed = []

    def reply(connection, **kwargs):
        if armed:
            armed.pop()
            gateway.lost.append(kwargs["correlation_id"])
            connection.close()  # the committed result never reaches the control plane
            return None
        return original(connection, **kwargs)

    monkeypatch.setattr(credential_gateway_service, "_write_logical_connection", reply)
    return lambda count=1: armed.extend([True] * count)


def ref(receipt):
    return {key: receipt[key] for key in ("record_id", "record_version", "ciphertext_sha256")}


def rotation_of(receipt, **changes):
    return metadata(record_id=receipt["record_id"], record_version=receipt["record_version"] + 1,
                    predecessor=ref(receipt)) | changes


def assert_sanitized(error, *secrets):
    text = str(error) + repr(error) + str(getattr(error, "code", ""))
    for secret in secrets:
        assert secret.decode() not in text
        assert sha256(secret).hexdigest() not in text
    assert error.__cause__ is None or secrets[0].decode() not in str(error.__cause__)


# --- lost responses ----------------------------------------------------------------

@pytest.mark.parametrize("kind", ["create", "rotate"])
def test_a_store_response_lost_after_commit_recovers_by_query_and_same_command_replay(gateway, lose_responses, kind):
    client = gateway.client()
    before = (0, 0, 0, 0)
    meta = predecessor_meta = metadata()
    if kind == "rotate":
        predecessor = client.store_at(metadata=predecessor_meta, secret=b"sk-synthetic-predecessor-00")
        meta = rotation_of(predecessor)
        before = gateway.counts()
    lose_responses()
    with pytest.raises(GatewayServiceError) as lost:
        client.store_at(metadata=meta, secret=SECRET)
    assert str(lost.value) == "gateway channel failed"
    assert lost.value.code == "credential_operation_rejected"
    assert_sanitized(lost.value, SECRET)
    assert len(gateway.lost) == 1
    committed = gateway.vault.query_record(metadata=meta)  # the vault is the oracle
    assert committed["state"] == "stored_unbound"
    # the ambiguous submission is resolved by query, then by replay of the SAME command:
    # the original receipt returns and the replacement bytes are never ingested
    assert client.query_record(metadata=meta) == committed
    assert client.store_at(metadata=meta, secret=OTHER) == committed
    assert gateway.plaintext_of(meta) == SECRET
    assert gateway.counts() == tuple(value + (1 if index < 3 else 0) for index, value in enumerate(before))
    # a changed intent under the lost command id is a conflict, never a second record
    with pytest.raises(GatewayServiceError) as changed:
        client.store_at(metadata=meta | {"created_at": "2026-09-25T00:00:01.000000Z"}, secret=OTHER)
    assert changed.value.code == "conflict"
    assert_sanitized(changed.value, OTHER, SECRET)
    if kind == "rotate":
        # storing a rotation candidate alone never retires or alters its predecessor
        assert client.query_record(metadata=predecessor_meta) == predecessor
    gateway.reopen()
    assert client.query_record(metadata=meta) == committed


@pytest.mark.parametrize("reason", ["owner_delete", "superseded"])
def test_a_retire_response_lost_after_commit_is_idempotent_under_the_same_command_id(gateway, lose_responses, reason):
    client = gateway.client()
    meta = metadata()
    receipt = client.store_at(metadata=meta, secret=SECRET)
    command = str(uuid4())
    lose_responses()
    with pytest.raises(GatewayServiceError) as lost:
        client.retire(command_id=command, record=ref(receipt), reason=reason)
    assert str(lost.value) == "gateway channel failed"
    assert gateway.vault.query_record(metadata=meta)["state"] == "cleanup_pending"
    replayed = client.retire(command_id=command, record=ref(receipt), reason=reason)
    assert replayed == {"command_id": command, "record": ref(receipt), "reason": reason,
                        "state": "cleanup_pending"}
    assert gateway.counts() == (1, 1, 1, 1)
    other_reason = "superseded" if reason == "owner_delete" else "owner_delete"
    with pytest.raises(GatewayServiceError) as changed:
        client.retire(command_id=command, record=ref(receipt), reason=other_reason)
    assert changed.value.code == "conflict"
    # retirement is irreversible: neither a replayed store nor a reopen restores it
    assert client.store_at(metadata=meta, secret=OTHER)["state"] == "cleanup_pending"
    gateway.reopen()
    assert client.query_record(metadata=meta)["state"] == "cleanup_pending"
    assert gateway.counts() == (1, 1, 1, 1)


def test_a_lost_response_never_licenses_a_fresh_command_to_alias_the_same_target(gateway, lose_responses):
    client = gateway.client()
    meta = metadata()
    lose_responses()
    with pytest.raises(GatewayServiceError):
        client.store_at(metadata=meta, secret=SECRET)
    # a caller that wrongly retries under a NEW command id for the same record/version
    # is refused: one target ingests at most once
    with pytest.raises(GatewayServiceError) as alias:
        client.store_at(metadata=meta | {"command_id": str(uuid4())}, secret=OTHER)
    assert alias.value.code == "conflict"
    assert gateway.counts() == (1, 1, 1, 0)
    assert gateway.plaintext_of(meta) == SECRET


# --- races -------------------------------------------------------------------------

def _race(calls):
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def run(index, call):
        barrier.wait(5)
        try:
            results[index] = ("ok", call())
        except GatewayServiceError as error:
            results[index] = ("error", error.code)

    threads = [threading.Thread(target=run, args=(i, call), daemon=True) for i, call in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
        assert not thread.is_alive()
    return results


@pytest.mark.parametrize("kind", ["create", "rotate"])
def test_concurrent_submissions_under_one_command_id_commit_exactly_once(gateway, kind):
    client = gateway.client()
    meta = metadata()
    if kind == "rotate":
        meta = rotation_of(client.store_at(metadata=meta, secret=b"sk-synthetic-predecessor-00"))
    before = gateway.counts()
    secrets = [b"sk-synthetic-race-%02d" % index for index in range(6)]
    results = _race([lambda secret=secret: gateway.client().store_at(metadata=meta, secret=secret)
                     for secret in secrets])
    assert all(outcome == "ok" for outcome, _ in results), results
    receipts = {value["ciphertext_sha256"] for _, value in results}
    assert len(receipts) == 1  # every racer observes the one committed receipt
    assert gateway.counts() == (before[0] + 1, before[1] + 1, before[2] + 1, before[3])
    assert gateway.plaintext_of(meta) in secrets


def test_concurrent_rotations_of_one_predecessor_under_distinct_commands_admit_one_successor(gateway):
    client = gateway.client()
    predecessor = client.store_at(metadata=metadata(), secret=b"sk-synthetic-predecessor-00")
    candidates = [rotation_of(predecessor) for _ in range(4)]  # same record/version target
    results = _race([lambda meta=meta, i=i: gateway.client().store_at(
        metadata=meta, secret=b"sk-synthetic-rotation-%02d" % i) for i, meta in enumerate(candidates)])
    winners = [value for outcome, value in results if outcome == "ok"]
    assert len(winners) == 1 and winners[0]["state"] == "stored_unbound"
    assert sorted(value for outcome, value in results if outcome == "error") == ["conflict"] * 3
    assert gateway.counts() == (2, 2, 2, 0)


@pytest.mark.parametrize("order", ["delete_first", "rotate_first", "concurrent"])
def test_delete_racing_rotate_never_reactivates_the_predecessor(gateway, order):
    client = gateway.client()
    first_meta = metadata()
    first = client.store_at(metadata=first_meta, secret=b"sk-synthetic-predecessor-00")
    successor_meta = rotation_of(first)
    delete_command, supersede_command = str(uuid4()), str(uuid4())

    def delete():
        return gateway.client().retire(command_id=delete_command, record=ref(first), reason="owner_delete")

    def rotate():
        stored = gateway.client().store_at(metadata=successor_meta, secret=SECRET)
        retired = gateway.client().retire(command_id=supersede_command, record=ref(first), reason="superseded")
        return stored, retired

    if order == "delete_first":
        results = [("ok", delete()), ("ok", rotate())]
    elif order == "rotate_first":
        rotated = rotate()
        results = [("ok", delete()), ("ok", rotated)]
    else:
        results = _race([delete, rotate])
    assert [outcome for outcome, _ in results] == ["ok", "ok"], results
    deleted, (stored, superseded) = results[0][1], results[1][1]
    assert deleted["state"] == superseded["state"] == "cleanup_pending"
    assert stored["state"] == "stored_unbound"
    for _ in range(2):  # before and after a reopen
        assert client.query_record(metadata=first_meta)["state"] == "cleanup_pending"
        assert client.query_record(metadata=successor_meta) == stored
        # neither retirement intent can be replayed into anything else
        assert client.retire(command_id=delete_command, record=ref(first), reason="owner_delete") == deleted
        assert client.store_at(metadata=first_meta, secret=OTHER)["state"] == "cleanup_pending"
        assert gateway.counts() == (2, 2, 2, 2)
        gateway.reopen()
    assert gateway.plaintext_of(successor_meta) == SECRET


# --- lost ingress -------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["create", "rotate"])
def test_a_journaled_command_whose_ingress_was_lost_reports_secret_input_lost_and_never_ingests(gateway, kind):
    client = gateway.client()
    predecessor = None
    meta = metadata()
    if kind == "rotate":
        predecessor_meta = meta
        predecessor = client.store_at(metadata=predecessor_meta, secret=b"sk-synthetic-predecessor-00")
        meta = rotation_of(predecessor)
    before = gateway.counts()
    gateway.vault.close()  # the crash helper is a separate process on the same vault
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_store, args=(gateway.args, meta, "after_reservation"))
    process.start()
    process.join(20)
    if process.is_alive():
        process.terminate()
        process.join(3)
        pytest.fail("owned crash helper exceeded its deadline")
    assert process.exitcode == 71
    process.close()
    gateway.vault = CredentialVault(**gateway.args)  # startup recovery marks the loss
    lost = {"command_id": meta["command_id"], "state": "secret_input_lost"}
    assert client.query_record(metadata=meta) == lost
    # a replay under the same command id with fresh bytes never resurrects the record
    assert client.store_at(metadata=meta, secret=OTHER) == lost
    assert lost in client.snapshot()
    assert gateway.counts() == (before[0] + 1, before[1] + 1, before[2], before[3])
    # the record has no receipt, so no reference to it can be retired or resolved
    with pytest.raises(GatewayServiceError) as retire:
        client.retire(command_id=str(uuid4()), record={"record_id": meta["record_id"],
                      "record_version": meta["record_version"], "ciphertext_sha256": "0" * 64},
                      reason="unbound_orphan")
    assert retire.value.code == "conflict"
    if predecessor is not None:
        # a lost rotation leaves its predecessor exactly as it was
        assert client.query_record(metadata=predecessor_meta) == predecessor
    for path in gateway.tmp_path.rglob("*"):
        if path.is_file():
            assert OTHER not in path.read_bytes()


# --- zero-effect reads ----------------------------------------------------------------

def test_query_snapshot_health_and_capabilities_over_frames_have_zero_vault_effect(gateway, monkeypatch):
    from app.workers.credential_root import CredentialRoot

    client = gateway.client()
    meta = metadata()
    receipt = client.store_at(metadata=meta, secret=SECRET)
    tree = {path: path.read_bytes() for path in gateway.tmp_path.rglob("*")
            if path.is_file() and path.name != "journal.sqlite-journal"}
    counts = gateway.counts()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a read touched cryptography")

    monkeypatch.setattr(CredentialRoot, "open", forbidden)
    monkeypatch.setattr(CredentialRoot, "seal", forbidden)
    assert client.query_record(metadata=meta) == receipt
    assert client.query_record(metadata=metadata())["state"] == "unknown"
    assert client.snapshot() == [receipt]
    assert client._call({"schema": "credential-op-v2", "op": "health"})["stored_unbound"] == 1
    capabilities = client._call({"schema": "credential-op-v2", "op": "capabilities"})
    assert capabilities["provider_resolution"] is False and capabilities["erasure"] is False
    assert gateway.counts() == counts
    after = {path: path.read_bytes() for path in gateway.tmp_path.rglob("*")
             if path.is_file() and path.name != "journal.sqlite-journal"}
    assert after == tree


# --- create/rotate/delete make zero provider effect -------------------------------------

def test_create_rotate_and_delete_through_the_owned_ingress_make_zero_provider_effect(tmp_path, tmp_path_factory, monkeypatch):
    """Over the real listener and the shared ingress (credential + send services on one
    vault), the credential lifecycle never decrypts for an exchange, never opens an HTTP
    connection and never enters the send engine."""
    import http.client

    from app.tests.support.provider_gateway_harness import (
        CONTROL_BOOT,
        fixed_profile_into,
        gateway_pair,
        served_gateway,
    )
    from app.tests.test_provider_gateway_owned import services
    from app.workers.provider_send_service import ProviderSendService

    effects = []

    def record(name):
        def observed(*_args, **_kwargs):
            effects.append(name)
            raise AssertionError(name)
        return observed

    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec):
        vault = CredentialVault(**initialized(tmp_path))
        try:
            fixed_profile_into(monkeypatch, root, spec)
            _credential, _send, ingress = services(vault, spec)
            for owner, name in ((CredentialVault, "delivery_for_exchange"),
                                (http.client.HTTPConnection, "connect"),
                                (http.client.HTTPSConnection, "connect"),
                                (socket, "create_connection"),
                                (socket, "getaddrinfo")):
                monkeypatch.setattr(owner, name, record(name))
            # every entry into the send engine: the ingress's own branch and the public ones
            for name in ("_serve_dialogue", "serve_authenticated", "serve_connection", "prepare"):
                monkeypatch.setattr(ProviderSendService, name, record("send." + name))
            client = CredentialGatewayClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=10_000)
            with served_gateway(root, spec, ingress) as served:
                served.serve(5)
                first = client.store_at(metadata=metadata(), secret=SECRET)                  # create
                successor = client.store_at(metadata=rotation_of(first), secret=OTHER)        # rotate
                client.retire(command_id=str(uuid4()), record=ref(first), reason="superseded")
                client.retire(command_id=str(uuid4()), record=ref(successor), reason="owner_delete")  # delete
                assert [entry["state"] for entry in client.snapshot()].count("cleanup_pending") == 2
                assert served.join() == []
        finally:
            vault.close()
    assert effects == []
