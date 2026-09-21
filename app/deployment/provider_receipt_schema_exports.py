"""Detached provider receipt schemas; values confer no authority."""

from copy import deepcopy
from ..extensions.candidate_schema_exports import (
    DRAFT,
    BROKER,
    ID,
    actor,
    array,
    const,
    enum,
    integer,
    obj,
    text,
    uuid_schema,
)
from .provider_prepare_schema_exports import (
    _b32,
    _blob,
    _entity,
    _hash,
    _timestamp,
    provider_request_schema,
    provider_prepare_input_schema,
    provider_cancel_input_schema,
)
from .provider_prepare_api_schema_exports import (
    provider_command_receipt_schema,
    provider_request_read_schema,
)
from .receipt_schema_exports import FAILURES, UNKNOWN_FAILURES, FACTS, b64u64
from .prepare_contracts import ERRORS


def _document(name, value):
    return {
        "$schema": DRAFT,
        "$id": "urn:deeptwin:schemas:v2:deployment:" + name,
        **value,
    }


def _identity():
    inode = obj(device=integer(0, 2**63 - 1), inode=integer(1, 2**63 - 1))
    channel = obj(root=inode, namespace=deepcopy(inode), backing_root_digest=_hash())
    return obj(
        schema_version=const("deployment-provider-receipt-channel-identity-v1"),
        source_context_sha256=_hash(),
        incoming=channel,
        consumed=deepcopy(channel),
    )


def _snapshot():
    return obj(
        observed_at=_timestamp(),
        engine_id=text(128, r"[A-Za-z0-9:._-]{1,128}"),
        container_id=_hash(),
        image_config_digest=text(71, "sha256:[0-9a-f]{64}"),
        started_at={
            **text(
                30, r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{9}Z"
            ),
            "format": "date-time",
        },
        restart_count=integer(0, 2**31 - 1),
        init_pid=integer(1, 2**31 - 1),
        configured_uid=integer(1, 2**32 - 1),
        configured_gid=integer(1, 2**32 - 1),
        socket_volume=text(256, r"dt-[0-9a-f]{32}-ipc-xs(?:0[1-9]|1[0-6])"),
        socket_path=text(256, r"/run/deeptwin/ipc/xs(?:0[1-9]|1[0-6])"),
        socket_read_only=const(False),
    )


def _result(presence, preservation):
    target = {
        "service_identity": text(64, BROKER),
        "manifest_digest": _hash(),
        "service_descriptor_digest": _hash(),
        "selected_platform_entry_digest": _hash(),
        "image_manifest_digest": text(71, "sha256:[0-9a-f]{64}"),
    }
    service = obj(presence=const("absent"))
    if presence == "present":
        service = obj(
            presence=const(presence),
            **target,
            reachable_after_effect={"type": "boolean"},
            observed_at=_timestamp(),
        )
    elif presence == "unknown":
        service = obj(
            presence=const(presence),
            **{"expected_" + k: v for k, v in target.items()},
            failure_class=enum(*UNKNOWN_FAILURES),
            observed_at=_timestamp(),
        )
    preserved = obj(
        state=const("preserved"),
        observations=array(
            obj(
                slot_id=integer(1, 16),
                service_identity=text(64, BROKER),
                before=_snapshot(),
                after=_snapshot(),
            ),
            0,
            1,
        ),
    )
    arm = {
        "not_attempted": obj(state=const("not_attempted")),
        "preserved": preserved,
        "unconfirmed": obj(
            state=const("unconfirmed"), failure_class=enum(*UNKNOWN_FAILURES)
        ),
    }[preservation]
    return obj(
        schema_id=const("deeptwin.provider-stage-result.v1"),
        extension_id=text(128, ID),
        expected_installation_head=obj(state=const("absent")),
        expected_next_installation_revision=const(1),
        old_service=obj(presence=const("absent")),
        new_service=service,
        stage_profile=const("claude-text-transform-v1"),
        source_context=obj(
            context_id=uuid_schema(),
            epoch=const(1),
            sha256=_hash(),
            size_bytes=integer(1, 16384),
        ),
        geometry=obj(sha256=_hash(), size_bytes=integer(1, 65536)),
        preserved_inventory_sha256=_hash(),
        preservation=arm,
    )


def provider_receipt_v1_schema():
    arms = []
    for outcome, presence, preservation in (
        ("succeeded", "present", "preserved"),
        *(
            ("failed", "absent", p)
            for p in ("not_attempted", "preserved", "unconfirmed")
        ),
        *(("failed", "unknown", p) for p in ("preserved", "unconfirmed")),
        *(("unknown", "unknown", p) for p in ("preserved", "unconfirmed")),
    ):
        arms.append(
            obj(
                schema=const("deployment-provider-receipt-v1"),
                domain=const("deeptwin-deployment-provider-receipt-v1"),
                request_id=uuid_schema(),
                request_digest=_b32(),
                request_nonce=_b32(),
                kind=const("extension_stage"),
                instance_id=text(32, "[0-9a-f]{32}"),
                origin_profile_digest=_b32(),
                deployment_profile_id=enum("https-private-v1", "http-loopback-v1"),
                operator_adapter=const("deeptwin-provider-stage-operator-v1"),
                operator_version=const("1.0.0"),
                effect_result=_result(presence, preservation),
                started_at=_timestamp(),
                completed_at=_timestamp(),
                outcome=const(outcome),
                failure_class={"type": "null"}
                if outcome == "succeeded"
                else enum(*(UNKNOWN_FAILURES if outcome == "unknown" else FAILURES)),
                claimed_facts=array(enum(*FACTS), 0, 8, True),
                verified_facts=array(enum(*FACTS), 0, 8, True),
                unverified_facts=array(enum(*FACTS), 0, 8, True),
                key_id=uuid_schema(),
                trust_set_digest=_b32(),
                trust_class=const("instance_operator"),
                signature=b64u64(),
            )
        )
    # The original profile vocabulary is owned by the unchanged receipt schema.
    from .receipt_schema_exports import receipt_schema

    profiles = receipt_schema()["properties"]["deployment_profile_id"]
    for arm in arms:
        arm["properties"]["deployment_profile_id"] = deepcopy(profiles)
    return _document("provider-receipt-v1", {"oneOf": arms})


def _selector(revision):
    return obj(
        command_id=uuid_schema(),
        request_digest=_b32(),
        receipt_digest=_b32(),
        expected_revision=const(revision),
    )


def provider_receipt_import_input_v1_schema():
    return _document("provider-receipt-import-input-v1", _selector(1))


def provider_consume_input_v1_schema():
    return _document("provider-consume-input-v1", _selector(2))


def provider_cancel_input_v2_schema():
    return _document("provider-cancel-input-v2", _selector(2))


def _marker(schema):
    return dict(
        schema=const(schema),
        domain=const("deeptwin-" + schema),
        request_id=uuid_schema(),
        request_digest=_b32(),
        receipt_digest=_b32(),
        instance_id=text(32, "[0-9a-f]{32}"),
        origin_profile_digest=_b32(),
        source_context_sha256=_hash(),
        preserved_inventory_sha256=_hash(),
    )


def provider_cancellation_v2_schema():
    return _document(
        "provider-cancellation-v2",
        obj(
            **_marker("deployment-provider-cancellation-v2"),
            lifecycle_revision=const(3),
            cancelled_at=_timestamp(),
        ),
    )


def provider_consumption_v1_schema():
    return _document(
        "provider-consumption-v1",
        obj(
            **_marker("deployment-provider-consumption-v1"),
            consumption_id=uuid_schema(),
            winning_lifecycle_revision=const(2),
            consumed_at=_timestamp(),
            outcome=enum("failed", "unknown"),
        ),
    )


def provider_receipt_anchor_v1_schema():
    return _document(
        "provider-receipt-anchor-v1",
        obj(
            schema_version=const("deployment-provider-receipt-anchor-v1"),
            request_ref=_entity("deployment_request"),
            receipt_blob_ref=_blob(16384),
            source_context_sha256=_hash(),
            channel_identity=_identity(),
            import_command_id=uuid_schema(),
        ),
    )


def provider_installation_anchor_v1_schema():
    return _document(
        "provider-installation-anchor-v1",
        obj(
            schema_version=const("extension-provider-installation-anchor-v1"),
            extension_id=text(128, ID),
            manifest_digest=_hash(),
            service_descriptor_digest=_hash(),
            selected_platform_entry_digest=_hash(),
            image_manifest_digest=text(71, "sha256:[0-9a-f]{64}"),
            platform=enum("linux/amd64", "linux/arm64"),
            service_identity=text(64, BROKER),
            staging_authority=const("deployment-provider-receipt-v1"),
            request_ref=_entity("deployment_request"),
            receipt_ref=_entity("deployment_receipt"),
            postcondition_evidence_blob_ref=_blob(8192),
            consume_command_id=uuid_schema(),
            state=const("staged"),
            revision=const(1),
            previous_record_digest={"type": "null"},
            installed_at=_timestamp(),
            actor_ref=actor(),
            stage_profile=const("claude-text-transform-v1"),
            source_context_sha256=_hash(),
            preserved_inventory_sha256=_hash(),
        ),
    )


def _expected():
    return obj(
        service_identity=text(64, BROKER),
        build_identity_digest=_hash(),
        port_schema_set_digest=_hash(),
        port_contract_version=const("provider-port-v1"),
        platform=enum("linux/amd64", "linux/arm64"),
        uid=integer(1, 2**32 - 1),
        gid=integer(1, 2**32 - 1),
        worker_profile=const("claude-text-transform-v1"),
        implemented_transforms={"type": "array", "const": ["catalog", "text"]},
    )


def provider_stage_postcondition_v1_schema():
    identity = _expected()["properties"]
    reply = obj(
        schema=const("provider-worker-identity-v1"),
        challenge=_hash(),
        **{k: v for k, v in identity.items() if k != "port_contract_version"},
    )
    observation = obj(
        ordinal=integer(1, 2),
        observed_at=_timestamp(),
        connection_id=_hash(),
        requester_boot_id=_hash(),
        responder_boot_id=_hash(),
        listener_record_sha256=_hash(),
        peer_uid=integer(1, 2**32 - 1),
        peer_gid=integer(1, 2**32 - 1),
        nonce=_hash(),
        challenge=_hash(),
        request_message_id=uuid_schema(),
        reply_message_id=uuid_schema(),
        reply=reply,
    )
    return _document(
        "provider-stage-postcondition-v1",
        obj(
            schema_version=const("provider-stage-postcondition-v1"),
            request_id=uuid_schema(),
            request_digest=_b32(),
            receipt_digest=_b32(),
            request_blob_sha256=_hash(),
            receipt_blob_sha256=_hash(),
            source_context_sha256=_hash(),
            preserved_inventory_sha256=_hash(),
            observed_at=_timestamp(),
            attempt_ms=integer(1, 2000),
            expected=_expected(),
            observations=array(observation, 2, 2),
            comparison=const("equal"),
        ),
    )


def _responses(read):
    path = r"/(?:[0-9a-f]{32}/)?api/v1/deployment/provider-requests/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
    links = obj(
        **{
            k: text(256, path + suffix)
            for k, suffix in (
                ("self", ""),
                ("cancel", "/cancel"),
                ("receipts", "/receipts"),
                ("consume", "/consume"),
            )
        },
        events=text(128, r"/(?:[0-9a-f]{32}/)?api/v1/events"),
    )
    arms = []
    for state, rev, outcomes in (
        ("receipt_pending", 2, ("succeeded",)),
        ("rejected", 2, ("failed", "unknown")),
        ("accepted", 3, ("succeeded",)),
        ("cancelled", 3, ("succeeded",)),
        *(([("expired", 3, ("succeeded",))]) if read else []),
    ):
        nullable = {"type": "null"}
        props = dict(
            request_id=uuid_schema(),
            request_digest=_b32(),
            kind=const("extension_stage"),
            state=const(state),
            revision=const(rev),
            publication_state=enum("published", "suppressed"),
            cancellation_publication_state=enum("pending", "published")
            if read and state == "cancelled"
            else const("pending")
            if state == "cancelled"
            else nullable,
            consumption_publication_state=enum("pending", "published")
            if read and state == "rejected"
            else const("pending")
            if state == "rejected"
            else nullable,
            source_context_sha256=_hash(),
            preserved_inventory_sha256=_hash(),
            receipt=obj(
                receipt_ref=_entity("deployment_receipt"),
                receipt_digest=_b32(),
                outcome=enum(*outcomes),
                import_revision=const(2),
            ),
            consumption_ref=_entity("deployment_receipt_consumption")
            if state in ("rejected", "accepted")
            else nullable,
            installation_ref=_entity("extension_installation")
            if state == "accepted"
            else nullable,
            links=links,
        )
        props.update(request=provider_request_schema()) if read else props.update(
            command_id=uuid_schema(), event_cursor=text(4096)
        )
        arms.append(obj(**props))
    return {"oneOf": arms}


def provider_command_receipt_v2_schema():
    return _document("provider-command-receipt-v2", _responses(False))


def provider_request_read_v2_schema():
    return _document("provider-request-read-v2", _responses(True))


def provider_receipt_api_schema():
    return _document(
        "provider-receipt-api-v1",
        {
            "oneOf": [
                provider_prepare_input_schema(),
                provider_cancel_input_schema(),
                _selector(1),
                _selector(2),
                provider_command_receipt_schema(),
                provider_request_read_schema(),
                provider_command_receipt_v2_schema(),
                provider_request_read_v2_schema(),
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
            ]
        },
    )


def exported_schemas():
    factories = (
        provider_receipt_v1_schema,
        provider_stage_postcondition_v1_schema,
        provider_receipt_import_input_v1_schema,
        provider_consume_input_v1_schema,
        provider_cancel_input_v2_schema,
        provider_cancellation_v2_schema,
        provider_consumption_v1_schema,
        provider_receipt_anchor_v1_schema,
        provider_installation_anchor_v1_schema,
        provider_command_receipt_v2_schema,
        provider_request_read_v2_schema,
        provider_receipt_api_schema,
    )
    values = [f() for f in factories]
    return deepcopy({v["$id"].split(":")[-1] + ".schema.json": v for v in values})
