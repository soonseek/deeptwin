"""Closed v2 deployment shapes; schema validity grants no journal authority."""

import json
from pathlib import Path

from ..extensions.candidate_schema_exports import (
    DRAFT,
    array,
    const,
    enum,
    integer,
    obj,
    text,
    uuid_schema,
)
from .prepare_schema_exports import (
    b64u32,
    links_schema,
    prepare_input_schema,
    request_schema,
    timestamp,
)


def cancel_input_schema():
    return obj(
        command_id=uuid_schema(),
        request_digest=b64u32(),
        expected_revision=integer(1, 3),
    )


def receipt_import_input_schema():
    return obj(
        command_id=uuid_schema(),
        request_digest=b64u32(),
        receipt_digest=b64u32(),
        expected_revision=integer(1, 3),
    )


def cancellation_schema():
    return obj(
        schema=const("deployment-cancellation-v2"),
        domain=const("deeptwin-deployment-cancellation-v2"),
        request_id=uuid_schema(),
        request_digest=b64u32(),
        instance_id=text(32, r"[0-9a-f]{32}"),
        origin_profile_digest=b64u32(),
        lifecycle_revision=integer(2, 3),
        cancelled_at=timestamp(),
    )


def _state_schema():
    return {
        "request_id": uuid_schema(),
        "request_digest": b64u32(),
        "kind": const("extension_stage"),
        "state": enum(
            "prepared", "cancelled", "expired", "receipt_pending", "rejected"
        ),
        "revision": integer(1, 3),
        "publication_state": enum("pending", "published", "suppressed"),
        "cancellation_publication_state": {
            "oneOf": [{"type": "null"}, enum("pending", "published")]
        },
        "links": links_schema(),
    }


def _receipt_state_schema():
    result = obj(
        receipt_digest=b64u32(),
        outcome=enum("succeeded", "failed", "unknown"),
        disposition=enum("pending_postconditions", "consumed_non_success"),
        import_revision=const(2),
    )
    result["oneOf"] = [
        {
            "properties": {
                "outcome": const("succeeded"),
                "disposition": const("pending_postconditions"),
            }
        },
        {
            "properties": {
                "outcome": enum("failed", "unknown"),
                "disposition": const("consumed_non_success"),
            }
        },
    ]
    return result


def command_receipt_schema():
    """Frozen prepare/cancel command replies, including only the new cancel revision."""
    result = obj(**_state_schema(), command_id=uuid_schema(), event_cursor=text(4096))
    result["oneOf"] = [
        {
            "properties": {
                "state": const("prepared"),
                "revision": const(1),
                "publication_state": const("pending"),
                "cancellation_publication_state": {"type": "null"},
            }
        },
        {
            "properties": {
                "state": const("cancelled"),
                "revision": integer(2, 3),
                "publication_state": enum("published", "suppressed"),
                "cancellation_publication_state": const("pending"),
            }
        },
    ]
    return result


def import_receipt_schema():
    result = obj(
        command_id=uuid_schema(),
        request_id=uuid_schema(),
        receipt_digest=b64u32(),
        outcome=enum("succeeded", "failed", "unknown"),
        disposition=enum("pending_postconditions", "consumed_non_success"),
        revision=const(2),
        event_cursor=text(4096),
    )
    result["oneOf"] = [
        {
            "properties": {
                "outcome": const("succeeded"),
                "disposition": const("pending_postconditions"),
            }
        },
        {
            "properties": {
                "outcome": enum("failed", "unknown"),
                "disposition": const("consumed_non_success"),
            }
        },
    ]
    return result


def read_schema():
    result = obj(
        **_state_schema(),
        request=request_schema(),
        receipt={"oneOf": [{"type": "null"}, _receipt_state_schema()]},
        consumption_publication_state={
            "oneOf": [{"type": "null"}, enum("pending", "published")]
        },
    )
    none = {"type": "null"}
    pending_receipt = {
        "allOf": [
            _receipt_state_schema(),
            {
                "properties": {
                    "outcome": const("succeeded"),
                    "disposition": const("pending_postconditions"),
                }
            },
        ]
    }
    consumed_receipt = {
        "allOf": [
            _receipt_state_schema(),
            {
                "properties": {
                    "outcome": enum("failed", "unknown"),
                    "disposition": const("consumed_non_success"),
                }
            },
        ]
    }
    result["oneOf"] = [
        {
            "properties": {
                "state": const("prepared"),
                "revision": const(1),
                "publication_state": enum("pending", "published"),
                "cancellation_publication_state": none,
                "receipt": none,
                "consumption_publication_state": none,
            }
        },
        {
            "properties": {
                "state": const("cancelled"),
                "revision": const(2),
                "publication_state": enum("published", "suppressed"),
                "cancellation_publication_state": enum("pending", "published"),
                "receipt": none,
                "consumption_publication_state": none,
            }
        },
        {
            "properties": {
                "state": const("expired"),
                "revision": const(2),
                "publication_state": enum("published", "suppressed"),
                "cancellation_publication_state": none,
                "receipt": none,
                "consumption_publication_state": none,
            }
        },
        {
            "properties": {
                "state": const("receipt_pending"),
                "revision": const(2),
                "publication_state": enum("published", "suppressed"),
                "cancellation_publication_state": none,
                "receipt": pending_receipt,
                "consumption_publication_state": none,
            }
        },
        {
            "properties": {
                "state": const("rejected"),
                "revision": const(2),
                "publication_state": enum("published", "suppressed"),
                "cancellation_publication_state": none,
                "receipt": consumed_receipt,
                "consumption_publication_state": enum("pending", "published"),
            }
        },
        {
            "properties": {
                "state": const("cancelled"),
                "revision": const(3),
                "publication_state": enum("published", "suppressed"),
                "cancellation_publication_state": enum("pending", "published"),
                "receipt": pending_receipt,
                "consumption_publication_state": none,
            }
        },
        {
            "properties": {
                "state": const("expired"),
                "revision": const(3),
                "publication_state": enum("published", "suppressed"),
                "cancellation_publication_state": none,
                "receipt": pending_receipt,
                "consumption_publication_state": none,
            }
        },
    ]
    return result


def api_schema():
    from .prepare_contracts import ERRORS

    errors = [
        obj(
            code=const(code),
            message=const(message),
            retryability=const("not_retryable"),
            affected_refs=array({}, 0, 0),
            correlation_id=uuid_schema(),
        )
        for code, (_, message) in ERRORS.items()
    ]
    return {
        "oneOf": [
            prepare_input_schema(),
            cancel_input_schema(),
            receipt_import_input_schema(),
            command_receipt_schema(),
            import_receipt_schema(),
            read_schema(),
            *errors,
        ]
    }


def exported_schemas():
    values = {
        "prepare-api-v2": api_schema(),
        "cancellation-v2": cancellation_schema(),
    }
    return {
        name + ".schema.json": {
            "$schema": DRAFT,
            "$id": "urn:deeptwin:schemas:v1:deployment:" + name,
            "$comment": (
                "Structural only; actual owner, source, signature, currentness, "
                "approval "
                "and journal admission remain required."
            ),
            **value,
        }
        for name, value in values.items()
    }


def write_schemas(destination):
    """Artifacts use sorted, indented UTF-8 and one newline, not ADR008 wire bytes."""
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    for name, schema in exported_schemas().items():
        (root / name).write_text(
            json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    write_schemas(Path(__file__).resolve().parents[2] / "schemas/v1/deployment")
