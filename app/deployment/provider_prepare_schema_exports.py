"""Fresh closed schemas for the pure provider preparation protocol."""

from __future__ import annotations

from copy import deepcopy

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
    obj,
    text,
    uuid_schema,
)
from .provider_source_contracts import BUNDLE_LAYOUT


def _hash():
    return text(64, HEX)


def _b32():
    return text(43, r"[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]")


def _timestamp():
    return {
        **text(24, r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z"),
        "format": "date-time",
    }


def _entity(kind):
    return obj(kind=const(kind), id=uuid_schema(), version=const(1), sha256=_hash())


def _blob(cap):
    return obj(
        vault_id=uuid_schema(),
        purpose=const("operational"),
        sha256=_hash(),
        size=integer(1, cap),
    )


def provider_inventory_schema():
    installation = obj(
        installation_ref=_entity("extension_installation"),
        extension_id=text(128, ID),
        request_ref=_entity("deployment_request"),
        head_revision=const(1),
        head_digest=_hash(),
        slot_id=integer(1, 16),
        service_identity=text(64, BROKER),
        accepted_event_id=uuid_schema(),
        staged_event_id=uuid_schema(),
    )
    return obj(
        schema_version=const("deployment-provider-preserved-inventory-v1"),
        vault_id=uuid_schema(),
        instance_id=text(32, r"[0-9a-f]{32}"),
        origin_profile_digest=_hash(),
        topology_id=uuid_schema(),
        topology_sha256=_hash(),
        at_event_sequence=integer(0, 2**40),
        installations=array(installation, 0, 16),
    )


def provider_stage_schema():
    oci = text(71, "sha256:" + HEX)
    return obj(
        schema_id=const("deeptwin.extension-stage-request.v2"),
        extension_id=text(128, ID),
        manifest_digest=_hash(),
        service_descriptor_digest=_hash(),
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
            network_policy_ref=_metadata("network_declaration"),
            resource_profile_ref=_metadata("resource_declaration"),
        ),
        expected_installation_head=obj(state=const("absent")),
        expected_next_installation_revision=const(1),
        stage_profile=const("claude-text-transform-v1"),
        source_context=obj(
            context_id=uuid_schema(),
            epoch=const(1),
            sha256=_hash(),
            size_bytes=integer(1, 16384),
        ),
        geometry=obj(sha256=_hash(), size_bytes=integer(1, 65536)),
        preserved_inventory=provider_inventory_schema(),
        preserved_inventory_sha256=_hash(),
    )


def _metadata(kind):
    return obj(document_kind=const(kind), sha256=_hash(), size_bytes=integer(1, 65536))


def provider_request_schema():
    return obj(
        schema=const("deployment-request-v2"),
        domain=const("deeptwin-deployment-request-v2"),
        request_id=uuid_schema(),
        kind=const("extension_stage"),
        request_nonce=_b32(),
        request_digest=_b32(),
        instance_id=text(32, r"[0-9a-f]{32}"),
        origin_profile_digest=_b32(),
        effect_payload=provider_stage_schema(),
        preconditions=obj(),
        created_by=actor(),
        created_at=_timestamp(),
        expires_at=_timestamp(),
    )


def provider_prepare_input_schema():
    return obj(
        command_id=uuid_schema(),
        kind=const("extension_stage"),
        candidate_id=uuid_schema(),
        slot_id=integer(1, 16),
        expires_in_seconds=integer(60, 86400),
        source_context_sha256=_hash(),
    )


def provider_cancel_input_schema():
    return obj(
        command_id=uuid_schema(),
        request_digest=_b32(),
        expected_revision=const(1),
    )


def provider_cancellation_schema():
    return obj(
        schema=const("deployment-provider-cancellation-v1"),
        domain=const("deeptwin-deployment-provider-cancellation-v1"),
        request_id=uuid_schema(),
        request_digest=_b32(),
        instance_id=text(32, r"[0-9a-f]{32}"),
        origin_profile_digest=_b32(),
        source_context_sha256=_hash(),
        preserved_inventory_sha256=_hash(),
        lifecycle_revision=const(2),
        cancelled_at=_timestamp(),
    )


def provider_request_anchor_schema():
    source_refs = [
        obj(name=const(name), blob_ref=_blob(cap)) for name, cap in BUNDLE_LAYOUT
    ]
    return obj(
        schema_version=const("deployment-provider-request-anchor-v2"),
        request_id=uuid_schema(),
        request_blob_ref=_blob(65536),
        source_documents={
            "type": "array",
            "prefixItems": source_refs,
            "items": False,
            "minItems": 18,
            "maxItems": 18,
        },
        preserved_inventory_blob_ref=_blob(16384),
        candidate_ref=_entity("extension_manifest"),
        topology_id=uuid_schema(),
        topology_revision=const(1),
        slot_id=integer(1, 16),
        reservation_revision=const(1),
        prepare_command_id=uuid_schema(),
    )


_FACTORIES = (
    ("provider-preserved-inventory-v1", provider_inventory_schema),
    ("provider-stage-request-v2", provider_stage_schema),
    ("provider-request-v2", provider_request_schema),
    ("provider-prepare-input-v1", provider_prepare_input_schema),
    ("provider-cancel-input-v1", provider_cancel_input_schema),
    ("provider-cancellation-v1", provider_cancellation_schema),
    ("provider-request-anchor-v2", provider_request_anchor_schema),
)


def _document(name, factory):
    return {
        "$schema": DRAFT,
        "$id": "urn:deeptwin:schemas:v2:deployment:" + name,
        "$comment": "Structural only; pure parsing and joins grant no deployment authority.",
        **deepcopy(factory()),
    }


def exported_schemas():
    return {
        name + ".schema.json": _document(name, factory) for name, factory in _FACTORIES
    }


__all__ = [
    "exported_schemas",
    "provider_cancel_input_schema",
    "provider_cancellation_schema",
    "provider_inventory_schema",
    "provider_prepare_input_schema",
    "provider_request_anchor_schema",
    "provider_request_schema",
    "provider_stage_schema",
]
