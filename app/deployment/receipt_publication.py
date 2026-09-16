"""Consumed-marker codec and inert filesystem observations."""

from dataclasses import dataclass

from app.domain.refs import DomainContractError, canonical_json, uuid_string
from app.domain.wire import WireInputError, WireLimits, parse_json_object
from app.operations.setup import SetupContractError, parse_base64url_32

from . import contracts as sources
from . import files as f
from .publication import _timestamp

_CONSUMED_FIELDS = (
    "schema",
    "domain",
    "consumption_id",
    "request_id",
    "request_digest",
    "receipt_digest",
    "winning_lifecycle_revision",
    "consumed_at",
    "outcome",
)


@dataclass(frozen=True, slots=True)
class ConsumedFileObservation:
    receipt_digest: str
    payload: bytes
    file_identity: f.FileIdentity


@dataclass(frozen=True, slots=True)
class ConsumedPublicationObservation:
    role: str
    receipt_digest: str
    payload_sha256: str
    size_bytes: int
    file_identity: f.FileIdentity


def validate_consumed_marker(*, receipt_digest: str, payload: bytes) -> dict:
    """Return one fresh inert marker after closed grammar and selector validation."""
    try:
        parse_base64url_32(receipt_digest)
        value = parse_json_object(
            payload,
            required=_CONSUMED_FIELDS,
            field_types={
                "schema": str,
                "domain": str,
                "consumption_id": str,
                "request_id": str,
                "request_digest": str,
                "receipt_digest": str,
                "winning_lifecycle_revision": int,
                "consumed_at": str,
                "outcome": str,
            },
            limits=WireLimits(
                max_bytes=4096,
                max_depth=4,
                max_items=32,
                max_members=16,
                max_string_bytes=256,
            ),
        )
        if canonical_json(value) != payload:
            raise sources.DeploymentSourceError()
        if (
            value["schema"] != "deployment-consumption-v1"
            or value["domain"] != "deeptwin-deployment-consumption-v1"
            or value["winning_lifecycle_revision"] != 2
            or value["receipt_digest"] != receipt_digest
            or value["outcome"] not in ("failed", "unknown")
        ):
            raise sources.DeploymentSourceError()
        uuid_string(value["consumption_id"])
        uuid_string(value["request_id"])
        parse_base64url_32(value["request_digest"])
        parse_base64url_32(value["receipt_digest"])
        _timestamp(value["consumed_at"])
        return value
    except sources.DeploymentSourceError:
        raise
    except (
        DomainContractError,
        SetupContractError,
        WireInputError,
        KeyError,
        TypeError,
        ValueError,
        RecursionError,
    ):
        raise sources.DeploymentSourceError() from None


def publish_consumed(source, *, receipt_digest, payload):
    from . import publication
    from .receipt_sources import ConsumptionExchangeSource

    if type(source) is not ConsumptionExchangeSource or getattr(
        source, "_closed", True
    ):
        raise sources.DeploymentSourceError()
    validate_consumed_marker(receipt_digest=receipt_digest, payload=payload)
    try:
        filename = parse_base64url_32(receipt_digest).hex() + ".json"
        _identity, inventory = source._inspect_inventory()
        directory = source._consumed
        scan = f._scan_namespace(directory, policy=f._CONSUMED_NAMESPACE)
        stage = None
        try:
            if filename not in {entry.name for entry in scan.finals}:
                if (
                    len(inventory) >= f._CONSUMED_NAMESPACE.final_limit
                    or scan.stages >= f._CONSUMED_NAMESPACE.stage_limit
                ):
                    raise sources.DeploymentSourceError()
                stage = publication._stage_payload(
                    directory, payload, policy=f._CONSUMED_NAMESPACE
                )
                source.recheck_current()
                try:
                    publication._commit_stage(directory, stage, filename)
                except FileExistsError:
                    pass
            file_identity = publication._existing_for_policy(
                directory,
                filename,
                payload,
                policy=f._CONSUMED_NAMESPACE,
            )
            _after_identity, after_inventory = source._inspect_inventory()
            winner = next(
                (
                    item
                    for item in after_inventory
                    if item.receipt_digest == receipt_digest
                ),
                None,
            )
            if (
                winner is None
                or winner.payload != payload
                or winner.file_identity != file_identity
            ):
                raise sources.DeploymentSourceError()
            return ConsumedPublicationObservation(
                "consumed",
                receipt_digest,
                sources.digest(payload),
                len(payload),
                file_identity,
            )
        finally:
            if stage is not None:
                stage.close()
    except OSError:
        raise sources.PublicationUnavailable() from None


__all__ = [
    "ConsumedFileObservation",
    "ConsumedPublicationObservation",
    "validate_consumed_marker",
]
