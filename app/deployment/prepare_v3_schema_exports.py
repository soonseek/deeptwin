"""Closed v3 deployment shapes (contracts/deployment-receipt-journal-v3.md §6):
the consume command input, its frozen 200 reply and the prepare-api-v3 read
structure with the `accepted` state and the installation summary. Schema
validity grants no acceptance, installation, head or journal authority; the
v1/v2 artifacts stay byte-identical."""

import json
from pathlib import Path

from ..extensions.candidate_schema_exports import (
    DRAFT,
    HEX,
    ID,
    array,
    const,
    enum,
    obj,
    text,
    uuid_schema,
)
from .prepare_schema_exports import (
    b64u32,
    links_schema,
    prepare_input_schema,
    request_schema,
)
from .prepare_v2_schema_exports import (
    cancel_input_schema,
    command_receipt_schema,
    import_receipt_schema,
    receipt_import_input_schema,
)

STATES = ("prepared", "cancelled", "expired", "receipt_pending", "rejected", "accepted")
DISPOSITIONS = ("pending_postconditions", "consumed_non_success", "consumed_success")


def consume_input_schema():
    """`expected_revision` is exactly 2: consume only leaves receipt_pending2."""
    return obj(
        command_id=uuid_schema(),
        request_digest=b64u32(),
        receipt_digest=b64u32(),
        expected_revision=const(2),
    )


def installation_schema():
    """The installation summary: the anchor's envelope sha256 and its id let a
    client build the exact EntityRef the staged event carries."""
    return obj(
        installation_id=uuid_schema(),
        extension_id=text(128, ID),
        installation_digest=text(64, HEX),
        revision=const(1),
    )


def consume_receipt_schema():
    """The frozen consume 200 body."""
    return obj(
        command_id=uuid_schema(),
        request_id=uuid_schema(),
        receipt_digest=b64u32(),
        outcome=const("succeeded"),
        disposition=const("consumed_success"),
        revision=const(3),
        installation=installation_schema(),
        event_cursor=text(4096),
    )


def _state_schema():
    return {
        "request_id": uuid_schema(),
        "request_digest": b64u32(),
        "kind": const("extension_stage"),
        "state": enum(*STATES),
        "revision": {"type": "integer", "minimum": 1, "maximum": 3},
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
        disposition=enum(*DISPOSITIONS),
        import_revision=const(2),
    )
    result["oneOf"] = [
        {"properties": {"outcome": const("succeeded"),
                        "disposition": const("pending_postconditions")}},
        {"properties": {"outcome": enum("failed", "unknown"),
                        "disposition": const("consumed_non_success")}},
        {"properties": {"outcome": const("succeeded"),
                        "disposition": const("consumed_success")}},
    ]
    return result


def _receipt(outcome, disposition):
    return {
        "allOf": [
            _receipt_state_schema(),
            {"properties": {"outcome": outcome, "disposition": const(disposition)}},
        ]
    }


def read_schema():
    none = {"type": "null"}
    result = obj(
        **_state_schema(),
        request=request_schema(),
        receipt={"oneOf": [none, _receipt_state_schema()]},
        consumption_publication_state={"oneOf": [none, enum("pending", "published")]},
        installation={"oneOf": [none, installation_schema()]},
    )
    pending = _receipt(const("succeeded"), "pending_postconditions")
    consumed = _receipt(enum("failed", "unknown"), "consumed_non_success")
    accepted = _receipt(const("succeeded"), "consumed_success")
    published = enum("published", "suppressed")

    def arm(state, revision, *, cancellation=none, receipt=none, consumption=none,
            installation=none, publication=published):
        return {
            "properties": {
                "state": const(state),
                "revision": const(revision),
                "publication_state": publication,
                "cancellation_publication_state": cancellation,
                "receipt": receipt,
                "consumption_publication_state": consumption,
                "installation": installation,
            }
        }

    result["oneOf"] = [
        arm("prepared", 1, publication=enum("pending", "published")),
        arm("cancelled", 2, cancellation=enum("pending", "published")),
        arm("expired", 2),
        arm("receipt_pending", 2, receipt=pending),
        arm("rejected", 2, receipt=consumed, consumption=enum("pending", "published")),
        arm("cancelled", 3, cancellation=enum("pending", "published"), receipt=pending),
        arm("expired", 3, receipt=pending),
        # the v3 head: the success consumption has no marker, so its
        # publication state stays null; the installation summary is present
        arm("accepted", 3, receipt=accepted, installation=installation_schema()),
    ]
    return result


def api_schema():
    from .prepare_contracts import ERRORS

    errors = [
        obj(
            code=const(code),
            message=const(message),
            retryability=const("not_retryable"),
            affected_refs=array({}, 0, 0),  # the v2 error envelope, byte for byte
            correlation_id=uuid_schema(),
        )
        for code, (_, message) in ERRORS.items()
    ]
    # the consume input has the import input's wire shape (its route pins
    # expected_revision to 2), so the artifact's input alternative for both
    # routes is the import-shaped input: listing consume_input_schema as well
    # would make every consume body match two alternatives
    return {
        "oneOf": [
            prepare_input_schema(),
            cancel_input_schema(),
            receipt_import_input_schema(),
            command_receipt_schema(),
            import_receipt_schema(),
            consume_receipt_schema(),
            read_schema(),
            *errors,
        ]
    }


def exported_schemas():
    return {
        "prepare-api-v3.schema.json": {
            "$schema": DRAFT,
            "$id": "urn:deeptwin:schemas:v1:deployment:prepare-api-v3",
            "$comment": (
                "Structural only; actual owner, source, signature, currentness, "
                "observation and journal admission remain required. The consume "
                "route's body has the receipt-import input shape with "
                "expected_revision fixed to 2 at the route."
            ),
            **api_schema(),
        }
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
