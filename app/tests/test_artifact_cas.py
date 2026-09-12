"""CAS-backed artifact sources/import for the T018 bounded byte route.

The contract requires the control plane to open the exact immutable object and move
its bytes only through the digest/chunk/receiver-credit stream, and to import worker
output back as immutable content.  These tests bind the stream to the DomainStore CAS.
"""

import hashlib
import threading

import pytest

from app.domain.store import BlobRef, DomainStore
from app.runtime.artifact_cas import StoredArtifactSource, store_received_artifact
from app.runtime.worker_coordinator import ReceivedWorkerArtifact
from app.storage import Store
from app.tests.test_worker_artifact_stream import (
    ScriptedTransport,
    descriptor,
    make_pair,
)
from app.workers.artifact_stream import (
    ArtifactStreamError,
    BytesSink,
    StreamLimits,
    _encode,
    receive_artifact,
    send_artifact,
)


@pytest.fixture
def domain(tmp_path):
    store = DomainStore(Store(tmp_path / "vault"))
    store.initialize_vault()
    return store


def stream_pair(desc, source, *, limits=None):
    sender_side, receiver_side = make_pair()
    sink = BytesSink()
    errors: dict[str, BaseException] = {}

    def do_send():
        try:
            send_artifact(sender_side, desc, source, limits=limits)
        except BaseException as exc:  # noqa: BLE001
            errors["send"] = exc

    def do_recv():
        try:
            receive_artifact(receiver_side, desc, sink, limits=limits)
        except BaseException as exc:  # noqa: BLE001
            errors["recv"] = exc

    ts = threading.Thread(target=do_send)
    tr = threading.Thread(target=do_recv)
    tr.start(); ts.start()
    ts.join(5); tr.join(5)
    assert not ts.is_alive() and not tr.is_alive(), "stream deadlocked"
    return errors, sink


def test_stored_source_streams_the_exact_blob_bytes(domain):
    data = bytes((i * 29) % 256 for i in range(40_000))
    blob = domain.put_blob(data, purpose="operational")
    desc = descriptor(data, media_type="application/pdf")
    source = StoredArtifactSource(domain, blob, desc)
    limits = StreamLimits(max_chunk_bytes=4_096, credit_window_chunks=2)
    errors, sink = stream_pair(desc, source, limits=limits)
    assert errors == {}
    assert sink.value == data


def test_stored_source_rejects_an_identity_mismatch_before_any_transport(domain):
    data = b"the stored bytes"
    blob = domain.put_blob(data, purpose="operational")
    foreign = descriptor(b"different bytes")
    with pytest.raises(ArtifactStreamError):
        StoredArtifactSource(domain, blob, foreign)
    short = descriptor(data, size=len(data) - 1)
    with pytest.raises(ArtifactStreamError):
        StoredArtifactSource(domain, blob, short)
    with pytest.raises(ArtifactStreamError):
        StoredArtifactSource(object(), blob, descriptor(data))
    with pytest.raises(ArtifactStreamError):
        StoredArtifactSource(domain, object(), descriptor(data))
    with pytest.raises(ArtifactStreamError):
        StoredArtifactSource(domain, blob, object())


def test_a_missing_blob_cancels_the_stream_terminally(domain):
    ghost = b"never stored"
    blob = BlobRef(
        domain.roots().genesis.id,
        "operational",
        hashlib.sha256(ghost).hexdigest(),
        len(ghost),
    )
    desc = descriptor(ghost)
    source = StoredArtifactSource(domain, blob, desc)
    scripted = ScriptedTransport([
        _encode({
            "type": "artifact-credit", "batch_id": desc.batch_id, "ordinal": 0,
            "consumed_through": 0, "credit_through": len(ghost),
        }),
    ])
    with pytest.raises(ArtifactStreamError):
        send_artifact(scripted, desc, source)
    assert scripted.sent[-1]["type"] == "artifact-cancel"


def test_store_received_artifact_imports_and_reads_back(domain):
    payload = b"worker output bytes"
    desc = descriptor(payload, media_type="text/plain")
    artifact = ReceivedWorkerArtifact(descriptor=desc, payload=payload)
    blob = store_received_artifact(domain, artifact, purpose="operational")
    assert blob.sha256 == desc.sha256
    assert blob.size == desc.declared_size
    assert domain.read_blob(blob, purpose="operational") == payload


def test_store_received_artifact_rejects_foreign_types(domain):
    payload = b"bytes"
    desc = descriptor(payload)
    artifact = ReceivedWorkerArtifact(descriptor=desc, payload=payload)
    with pytest.raises(ArtifactStreamError):
        store_received_artifact(object(), artifact, purpose="operational")
    with pytest.raises(ArtifactStreamError):
        store_received_artifact(domain, object(), purpose="operational")
