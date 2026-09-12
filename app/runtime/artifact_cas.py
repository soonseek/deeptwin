"""Bind the bounded artifact stream to the DomainStore content-addressed store.

The contract's byte route starts and ends at exact immutable content: the control
plane opens one registered blob, verifies its digest/size against the declared
stream descriptor and moves the bytes only through the digest/chunk/receiver-credit
stream; verified worker output is imported back as registered content.  These
adapters never hand a worker the store itself — only bytes over the stream.
"""

from __future__ import annotations

from ..domain.refs import DomainContractError
from ..domain.store import BlobRef, DomainStore, StorageError
from ..workers.artifact_stream import ArtifactDescriptor, ArtifactStreamError
from .worker_coordinator import ReceivedWorkerArtifact


class StoredArtifactSource:
    """Forward-only reader over one exact registered blob, bound to its descriptor."""

    __slots__ = ("_blob", "_data", "_domain", "_offset")

    def __init__(
        self,
        domain_store: DomainStore,
        blob: BlobRef,
        descriptor: ArtifactDescriptor,
    ) -> None:
        if (
            type(domain_store) is not DomainStore
            or type(blob) is not BlobRef
            or type(descriptor) is not ArtifactDescriptor
            or descriptor.sha256 != blob.sha256
            or descriptor.declared_size != blob.size
        ):
            raise ArtifactStreamError("stored artifact does not match its descriptor")
        self._domain = domain_store
        self._blob = blob
        self._data: bytes | None = None
        self._offset = 0

    def read(self, size: int) -> bytes:
        if type(size) is not int or size < 0:
            raise ArtifactStreamError("source read size is invalid")
        if self._data is None:
            # read_blob re-verifies registration, size and digest against the store.
            try:
                self._data = self._domain.read_blob(
                    self._blob, purpose=self._blob.purpose
                )
            except (StorageError, DomainContractError) as exc:
                raise ArtifactStreamError(
                    "stored artifact bytes are unavailable"
                ) from exc
        chunk = self._data[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk


def store_received_artifact(
    domain_store: DomainStore,
    artifact: ReceivedWorkerArtifact,
    *,
    purpose: str,
) -> BlobRef:
    """Import one verified worker artifact as registered content; return its BlobRef."""

    if (
        type(domain_store) is not DomainStore
        or type(artifact) is not ReceivedWorkerArtifact
    ):
        raise ArtifactStreamError("an exact store and received artifact are required")
    blob = domain_store.put_blob(artifact.payload, purpose=purpose)
    if (
        blob.sha256 != artifact.descriptor.sha256
        or blob.size != artifact.descriptor.declared_size
    ):
        raise ArtifactStreamError("imported artifact identity diverged")
    return blob


__all__ = ["StoredArtifactSource", "store_received_artifact"]
