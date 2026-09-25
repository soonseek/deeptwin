"""Closed owner-recovery request/receipt/trust-set v2 schemas; structure grants no authority.

The v1 stage receipt and `deployment-public-trust-set-v1` stay exactly as exported under
schemas/v1/deployment. Recovery adds a separate trust-set version whose keys each name the
adapters they may sign for, so a stage-only key can never sign an owner recovery.
"""

import json
from pathlib import Path

from ..extensions.candidate_schema_exports import (
    DRAFT,
    HEX,
    actor,
    array,
    const,
    enum,
    obj,
    text,
    uuid_schema,
)
from ..operations.setup import MAX_RECOVERY_EPOCH
from .prepare_schema_exports import b64u32, timestamp
from .receipt_schema_exports import b64u64

STAGE_ADAPTER = "deeptwin-stage-operator-v1"
RECOVERY_ADAPTER = "deeptwin-recovery-operator-v1"
ADAPTER_VERSION = "1.0.0"
PROFILES = ("local-no-terminal-v1", "portable-compose-v1")


def _epoch(low=1):
    return {"type": "integer", "minimum": low, "maximum": MAX_RECOVERY_EPOCH}


def trust_set_v2_schema():
    key = obj(
        key_id=uuid_schema(),
        algorithm=const("ed25519"),
        public_key=b64u32(),
        trust_class=const("instance_operator"),
        adapter_ids=array(enum(RECOVERY_ADAPTER, STAGE_ADAPTER), 1, 2, True),
    )
    adapter = obj(
        operator_adapter=enum(STAGE_ADAPTER, RECOVERY_ADAPTER),
        operator_version=const(ADAPTER_VERSION),
        deployment_profile_id=enum(*PROFILES),
    )
    return obj(
        schema=const("deployment-public-trust-set-v2"),
        domain=const("deeptwin-deployment-public-trust-set-v2"),
        version=const(2),
        instance_id=text(32, r"[0-9a-f]{32}"),
        origin_profile_digest=b64u32(),
        # the exact v1 trust-set bytes this set supersedes (sha256, base64url), or null on
        # an instance whose first trust set was already v2
        previous_trust_set_digest={"oneOf": [{"type": "null"}, b64u32()]},
        keys=array(key, 1, 8, True),
        adapters=array(adapter, 2, 2, True),
    )


def recovery_request_schema():
    return obj(
        schema=const("deployment-request-v1"),
        domain=const("deeptwin-deployment-request-v1"),
        request_id=uuid_schema(),
        kind=const("owner_recovery"),
        request_nonce=b64u32(),
        request_digest=b64u32(),
        instance_id=text(32, r"[0-9a-f]{32}"),
        origin_profile_digest=b64u32(),
        effect_payload=obj(target_recovery_epoch=_epoch(2)),
        preconditions=obj(
            current_recovery_epoch=_epoch(),
            current_session_root_generation_id=uuid_schema(),
            current_session_root_manifest_sha256=text(64, HEX),
        ),
        created_by=actor(),
        created_at=timestamp(),
        expires_at=timestamp(),
    )


def recovery_receipt_schema():
    return obj(
        schema=const("deployment-recovery-receipt-v1"),
        domain=const("deeptwin-deployment-recovery-receipt-v1"),
        request_id=uuid_schema(),
        request_digest=b64u32(),
        request_nonce=b64u32(),
        kind=const("owner_recovery"),
        instance_id=text(32, r"[0-9a-f]{32}"),
        origin_profile_digest=b64u32(),
        deployment_profile_id=enum(*PROFILES),
        operator_adapter=const(RECOVERY_ADAPTER),
        operator_version=const(ADAPTER_VERSION),
        previous_epoch=_epoch(),
        previous_generation_id=uuid_schema(),
        previous_manifest_sha256=text(64, HEX),
        new_epoch=_epoch(2),
        new_generation_id=uuid_schema(),
        new_manifest_sha256=text(64, HEX),
        new_verifier_sha256=text(64, HEX),
        completed_at=timestamp(),
        key_id=uuid_schema(),
        trust_set_digest=b64u32(),
        trust_class=const("instance_operator"),
        signature=b64u64(),
    )


def recovered_session_root_schema():
    """The public (tag-free) manifest of a recovered session-root generation."""

    return obj(
        schema_version=const("session-root-v2"),
        generation_id=uuid_schema(),
        key_id=uuid_schema(),
        instance_id=text(32, r"[0-9a-f]{32}"),
        origin_profile_digest=text(64, HEX),
        recovery_epoch=_epoch(2),
        created_at=timestamp(),
        state=const("recovered"),
        parent_generation_id=uuid_schema(),
        recovery_receipt_sha256=text(64, HEX),
    )


def exported_schemas():
    values = {
        "public-trust-set-v2": trust_set_v2_schema(),
        "request-owner-recovery-v1": recovery_request_schema(),
        "receipt-recovery-v1": recovery_receipt_schema(),
        "session-root-recovered-v2": recovered_session_root_schema(),
    }
    return {
        name + ".schema.json": {
            "$schema": DRAFT,
            "$id": "urn:deeptwin:schemas:v2:deployment:" + name,
            "$comment": (
                "Structural only; request/trust relations, signature authenticity, "
                "epoch succession and generation binding remain separately required."
            ),
            **schema,
        }
        for name, schema in values.items()
    }


def write_schemas(destination):
    """Write deterministic developer artifacts; never establish trust authority."""
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    for name, schema in exported_schemas().items():
        (root / name).write_text(
            json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    write_schemas(Path(__file__).resolve().parents[2] / "schemas/v2/deployment")
