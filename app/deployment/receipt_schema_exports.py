"""Closed receipt/trust schemas; structural validity grants no authority."""

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
from .prepare_schema_exports import b64u32, timestamp

FAILURES = (
    "operator_refused",
    "precondition_failed",
    "image_unavailable",
    "effect_failed",
    "observation_unavailable",
    "deadline_exceeded",
    "operator_interrupted",
    "internal_error",
)
UNKNOWN_FAILURES = (
    "observation_unavailable",
    "deadline_exceeded",
    "operator_interrupted",
    "internal_error",
)
FACTS = (
    "request_binding",
    "image_identity",
    "mount_configuration",
    "service_presence",
    "service_reachability",
    "network_configuration",
    "resource_configuration",
    "operator_preconditions",
)


def b64u64():
    return text(86, r"[A-Za-z0-9_-]{85}[AQgw]")


def _stage_common():
    return {
        "schema_id": const("deeptwin.extension-stage-result.v1"),
        "extension_id": text(128, ID),
        "expected_installation_head": obj(state=const("absent")),
        "expected_next_installation_revision": const(1),
        "old_service": obj(presence=const("absent")),
    }


def _present_service():
    return obj(
        presence=const("present"),
        service_identity=text(128, ID),
        manifest_digest=text(64, HEX),
        service_descriptor_digest=text(64, HEX),
        selected_platform_entry_digest=text(64, HEX),
        image_manifest_digest=text(71, "sha256:" + HEX),
        reachable_after_effect={"type": "boolean"},
        observed_at=timestamp(),
    )


def _unknown_service():
    return obj(
        presence=const("unknown"),
        expected_service_identity=text(128, ID),
        expected_manifest_digest=text(64, HEX),
        expected_service_descriptor_digest=text(64, HEX),
        expected_selected_platform_entry_digest=text(64, HEX),
        expected_image_manifest_digest=text(71, "sha256:" + HEX),
        failure_class=enum(*UNKNOWN_FAILURES),
        observed_at=timestamp(),
    )


def stage_result_schema():
    return {
        "oneOf": [
            obj(**_stage_common(), new_service=obj(presence=const("absent"))),
            obj(**_stage_common(), new_service=_present_service()),
            obj(**_stage_common(), new_service=_unknown_service()),
        ]
    }


def receipt_schema():
    value = obj(
        schema=const("deployment-receipt-v1"),
        domain=const("deeptwin-deployment-receipt-v1"),
        request_id=uuid_schema(),
        request_digest=b64u32(),
        request_nonce=b64u32(),
        kind=const("extension_stage"),
        instance_id=text(32, r"[0-9a-f]{32}"),
        origin_profile_digest=b64u32(),
        deployment_profile_id=enum(
            "local-no-terminal-v1", "portable-compose-v1"
        ),
        operator_adapter=const("deeptwin-stage-operator-v1"),
        operator_version=const("1.0.0"),
        effect_result=stage_result_schema(),
        started_at=timestamp(),
        completed_at=timestamp(),
        outcome=enum("succeeded", "failed", "unknown"),
        failure_class={"oneOf": [{"type": "null"}, enum(*FAILURES)]},
        claimed_facts=array(enum(*FACTS), 0, 8, True),
        verified_facts=array(enum(*FACTS), 0, 8, True),
        unverified_facts=array(enum(*FACTS), 0, 8, True),
        key_id=uuid_schema(),
        trust_set_digest=b64u32(),
        trust_class=const("instance_operator"),
        signature=b64u64(),
    )
    value["allOf"] = [
        {
            "oneOf": [
                {
                    "properties": {
                        "outcome": const("succeeded"),
                        "failure_class": {"type": "null"},
                        "effect_result": {
                            "properties": {
                                "new_service": {
                                    "properties": {"presence": const("present")}
                                }
                            }
                        },
                    }
                },
                {
                    "properties": {
                        "outcome": const("failed"),
                        "failure_class": enum(*FAILURES),
                        "effect_result": {
                            "properties": {
                                "new_service": {
                                    "properties": {
                                        "presence": enum("absent", "unknown")
                                    }
                                }
                            }
                        },
                    }
                },
                {
                    "properties": {
                        "outcome": const("unknown"),
                        "failure_class": enum(*UNKNOWN_FAILURES),
                        "effect_result": {
                            "properties": {
                                "new_service": {
                                    "properties": {"presence": const("unknown")}
                                }
                            }
                        },
                    }
                },
            ]
        }
    ]
    return value


def trust_set_schema():
    key = obj(
        key_id=uuid_schema(),
        algorithm=const("ed25519"),
        public_key=b64u32(),
        trust_class=const("instance_operator"),
        adapter_ids={"type": "array", "const": ["deeptwin-stage-operator-v1"]},
    )
    adapter = obj(
        operator_adapter=const("deeptwin-stage-operator-v1"),
        operator_version=const("1.0.0"),
        deployment_profile_id=enum(
            "local-no-terminal-v1", "portable-compose-v1"
        ),
    )
    return obj(
        schema=const("deployment-public-trust-set-v1"),
        domain=const("deeptwin-deployment-public-trust-set-v1"),
        version=const(1),
        instance_id=text(32, r"[0-9a-f]{32}"),
        origin_profile_digest=b64u32(),
        keys=array(key, 1, 8, True),
        adapters=array(adapter, 1, 1, True),
    )


def exported_schemas():
    values = {
        "receipt-stage-v1": receipt_schema(),
        "public-trust-set-v1": trust_set_schema(),
    }
    return {
        name + ".schema.json": {
            "$schema": DRAFT,
            "$id": "urn:deeptwin:schemas:v1:deployment:" + name,
            "$comment": (
                "Structural only; request/trust relations, signature authenticity, "
                "source pinning and currentness remain separately required."
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
    write_schemas(Path(__file__).resolve().parents[2] / "schemas/v1/deployment")
