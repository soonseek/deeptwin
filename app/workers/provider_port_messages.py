"""Closed worker proposal/observation values; never durable refs or authority."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from ..domain.refs import canonical_json
from ..extensions.provider_semantic_contracts import (ProviderSemanticError,
                                                       semantic_request_key,
                                                       validate_operation)
from .provider_semantic_codec import CatalogTraversal


@dataclass(frozen=True, slots=True)
class ProviderProposal:
    request_id: str
    operation: str
    request_sha256: str
    endpoint: str
    after_id: str | None
    body: bytes | None = field(repr=False)
    traversal: CatalogTraversal = CatalogTraversal()


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    request_id: str
    operation: str
    reason: str
    complete: bool
    observed_model: str | None = None
    stop_reason: str | None = None
    text_blocks: tuple[bytes, ...] = field(default=(), repr=False)
    usage: dict | None = None
    model_ids: tuple[str, ...] = ()
    traversal: CatalogTraversal | None = None


def validate_request(value):
    semantic_request_key(value)
    validate_operation(value["operation"])
    return value


def request_digest(value):
    validate_request(value)
    return sha256(canonical_json(value)).hexdigest()


__all__ = ["ProviderObservation", "ProviderProposal", "request_digest", "validate_request"]
