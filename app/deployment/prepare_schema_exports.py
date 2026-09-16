"""Closed structural deployment documents; these schemas grant no effect authority."""

import json
from pathlib import Path

from ..extensions.candidate_schema_exports import (
    BROKER,
    DRAFT,
    HEX,
    ID,
    actor,
    array,
    const,
    descriptor_schema,
    enum,
    integer,
    meta,
    obj,
    text,
    uuid_schema,
)


def b64u32():
    return text(43, r"[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]")


def timestamp():
    return {
        **text(24, r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z"),
        "format": "date-time",
    }


def stage_schema():
    oci = text(71, "sha256:" + HEX)
    return obj(
        schema_id=const("deeptwin.extension-stage-request.v1"),
        extension_id=text(128, ID),
        manifest_digest=text(64, HEX),
        service_descriptor_digest=text(64, HEX),
        selected_platform_entry=obj(
            platform=enum("linux/amd64", "linux/arm64"),
            index_digest=oci,
            manifest_digest=oci,
            config_digest=oci,
            ordered_layer_digests=array(oci, 1, 128),
        ),
        new_service_effect=obj(
            service_identity=text(64, BROKER),
            socket_mounts=array(
                descriptor_schema()["properties"]["socket_mounts"]["items"], 1, 1
            ),
            named_volume_mounts=array({}, 0, 0),
            network_policy_ref=meta("network_declaration"),
            resource_profile_ref=meta("resource_declaration"),
        ),
        expected_installation_head=obj(state=const("absent")),
        expected_next_installation_revision=const(1),
    )


def request_schema():
    return obj(
        schema=const("deployment-request-v1"),
        domain=const("deeptwin-deployment-request-v1"),
        request_id=uuid_schema(),
        kind=const("extension_stage"),
        request_nonce=b64u32(),
        request_digest=b64u32(),
        instance_id=text(32, r"[0-9a-f]{32}"),
        origin_profile_digest=b64u32(),
        effect_payload=stage_schema(),
        preconditions=obj(),
        created_by=actor(),
        created_at=timestamp(),
        expires_at=timestamp(),
    )


def cancellation_schema():
    return obj(
        schema=const("deployment-cancellation-v1"),
        domain=const("deeptwin-deployment-cancellation-v1"),
        request_id=uuid_schema(),
        request_digest=b64u32(),
        instance_id=text(32, r"[0-9a-f]{32}"),
        origin_profile_digest=b64u32(),
        lifecycle_revision=const(2),
        cancelled_at=timestamp(),
    )


def prepare_input_schema():
    return obj(
        command_id=uuid_schema(),
        kind=const("extension_stage"),
        candidate_id=uuid_schema(),
        slot_id=integer(1, 16),
        expires_in_seconds=integer(60, 86400),
    )


def cancel_input_schema():
    return obj(
        command_id=uuid_schema(),
        request_digest=b64u32(),
        expected_revision=integer(1, 2),
    )


def links_schema():
    base = r"/(?:[0-9a-f]{32}/)?api/v1/"
    request = base + r"deployment/requests/[0-9a-f-]{36}"
    return obj(
        self=text(256, request),
        cancel=text(256, request + "/cancel"),
        events=text(128, base + "events"),
    )


def state_schema():
    return {
        "request_id": uuid_schema(),
        "request_digest": b64u32(),
        "kind": const("extension_stage"),
        "state": enum("prepared", "cancelled", "expired"),
        "revision": integer(1, 2),
        "publication_state": enum("pending", "published", "suppressed"),
        "cancellation_publication_state": {
            "oneOf": [{"type": "null"}, enum("pending", "published")]
        },
        "links": links_schema(),
    }


def receipt_schema():
    result = obj(**state_schema(), command_id=uuid_schema(), event_cursor=text(4096))
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
                "revision": const(2),
                "publication_state": enum("published", "suppressed"),
                "cancellation_publication_state": const("pending"),
            }
        },
    ]
    return result


def read_schema():
    result = obj(**state_schema(), request=request_schema())
    result["oneOf"] = [
        {
            "properties": {
                "state": const("prepared"),
                "revision": const(1),
                "publication_state": enum("pending", "published"),
                "cancellation_publication_state": {"type": "null"},
            }
        },
        {
            "properties": {
                "state": const("cancelled"),
                "revision": const(2),
                "publication_state": enum("published", "suppressed"),
                "cancellation_publication_state": enum("pending", "published"),
            }
        },
        {
            "properties": {
                "state": const("expired"),
                "revision": const(2),
                "publication_state": enum("published", "suppressed"),
                "cancellation_publication_state": {"type": "null"},
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
            receipt_schema(),
            read_schema(),
            *errors,
        ]
    }


def exported_schemas():
    from ..domain.deployment_request import anchor_content_schema

    values = {
        "request-stage-v1": request_schema(),
        "request-anchor-v1": anchor_content_schema(),
        "prepare-api-v1": api_schema(),
        "cancellation-v1": cancellation_schema(),
    }
    return {
        name + ".schema.json": {
            "$schema": DRAFT,
            "$id": "urn:deeptwin:schemas:v1:deployment:" + name,
            "$comment": "Structural only; actual owner, source and journal admission remain required.",
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
