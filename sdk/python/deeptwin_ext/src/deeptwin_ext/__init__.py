"""Dependency-free authoring helpers for DeepTwin extension protocol v1.

The kit creates data and typed worker messages only. Importing it never discovers,
installs, qualifies, binds, or executes an extension.
"""

from .manifest import build_manifest, canonical_manifest_bytes
from .protocol import (
    PROTOCOL_VERSION,
    WORKER_FAILURE_CODES,
    WORKER_OPERATIONS,
    ProtocolError,
    WorkerRequest,
    WorkerResult,
)

__all__ = (
    "ProtocolError",
    "PROTOCOL_VERSION",
    "WORKER_FAILURE_CODES",
    "WORKER_OPERATIONS",
    "WorkerRequest",
    "WorkerResult",
    "build_manifest",
    "canonical_manifest_bytes",
)
