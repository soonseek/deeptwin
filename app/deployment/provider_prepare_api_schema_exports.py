"""Three detached closed browser response schemas for provider preparation."""

from copy import deepcopy

from ..extensions.candidate_schema_exports import (
    DRAFT,
    const,
    enum,
    obj,
    text,
    uuid_schema,
)
from .prepare_contracts import ERRORS
from .provider_prepare_schema_exports import (
    _b32,
    _hash,
    provider_cancel_input_schema,
    provider_prepare_input_schema,
    provider_request_schema,
)


def _links():
    path = r"/(?:[0-9a-f]{32}/)?api/v1/deployment/provider-requests/[0-9a-f-]{36}"
    return obj(
        self=text(256, path),
        cancel=text(256, path + "/cancel"),
        events=text(128, r"/(?:[0-9a-f]{32}/)?api/v1/events"),
    )


def _summary(state, revision, publication, cancellation):
    return {
        "request_id": uuid_schema(),
        "request_digest": _b32(),
        "kind": const("extension_stage"),
        "state": const(state),
        "revision": const(revision),
        "publication_state": enum(*publication),
        "cancellation_publication_state": {"type": "null"}
        if cancellation == (None,)
        else enum(*cancellation),
        "source_context_sha256": _hash(),
        "preserved_inventory_sha256": _hash(),
        "links": _links(),
    }


def _schema(name, arms):
    return {
        "$schema": DRAFT,
        "$id": "urn:deeptwin:schemas:v2:deployment:" + name,
        "oneOf": arms,
    }


def provider_command_receipt_schema():
    return _schema(
        "provider-command-receipt-v1",
        [
            obj(
                **_summary(state, revision, publications, cancellations),
                command_id=uuid_schema(),
                event_cursor=text(4096),
            )
            for state, revision, publications, cancellations in (
                ("prepared", 1, ("pending",), (None,)),
                ("cancelled", 2, ("published", "suppressed"), ("pending",)),
            )
        ],
    )


def provider_request_read_schema():
    return _schema(
        "provider-request-read-v1",
        [
            obj(
                **_summary(state, revision, publications, cancellations),
                request=provider_request_schema(),
            )
            for state, revision, publications, cancellations in (
                ("prepared", 1, ("pending", "published"), (None,)),
                ("cancelled", 2, ("published", "suppressed"), ("pending", "published")),
                ("expired", 2, ("published", "suppressed"), (None,)),
            )
        ],
    )


def provider_prepare_api_schema():
    return _schema(
        "provider-prepare-api-v1",
        [
            provider_prepare_input_schema(),
            provider_cancel_input_schema(),
            provider_command_receipt_schema(),
            provider_request_read_schema(),
            *(
                obj(
                    code=const(code),
                    message=const(message),
                    retryability=const("not_retryable"),
                    affected_refs={"type": "array", "maxItems": 0},
                    correlation_id=uuid_schema(),
                )
                for code, (_, message) in ERRORS.items()
            ),
        ],
    )


def exported_schemas():
    return deepcopy(
        {
            "provider-command-receipt-v1.schema.json": provider_command_receipt_schema(),
            "provider-request-read-v1.schema.json": provider_request_read_schema(),
            "provider-prepare-api-v1.schema.json": provider_prepare_api_schema(),
        }
    )
