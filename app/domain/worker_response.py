"""Closed worker-response-capture-v1 content contract; parsing grants no authority."""

import re

from .refs import DomainContractError, EntityRef, positive_integer, uuid_string

CAPTURE_VERSION = "worker-response-capture-v1"
CAPTURE_FIELDS = frozenset({
    "capture_schema_version", "command_id", "attempt_id", "permit_id",
    "execution_envelope_ref", "runtime_profile_ref", "lease_fence", "connection_id",
    "requester_boot_id", "worker_boot_id", "channel_id", "requester_service",
    "responder_service", "message_id", "correlation_id", "message_type",
    "payload_blob", "artifacts",
})
BOOT_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"
NAME_PATTERN = r"[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*"
MEDIA_PATTERN = r"[a-z0-9][a-z0-9!#$&\-^_.+]{0,126}/[a-z0-9][a-z0-9!#$&\-^_.+]{0,126}"
HASH_PATTERN = r"[0-9a-f]{64}"


def validate_capture_content(content):
    # Local imports avoid an envelope/store import cycle. Constructors are pure;
    # this function never opens storage or a transport.
    from ..workers.artifact_stream import (
        ArtifactDescriptor,
        ArtifactStreamError,
        StreamLimits,
        validate_batch,
    )
    from .store import BlobRef

    try:
        if (type(content) is not dict or set(content) != CAPTURE_FIELDS
                or content["capture_schema_version"] != CAPTURE_VERSION):
            raise ValueError
        for name in ("command_id", "attempt_id", "permit_id", "message_id", "correlation_id"):
            uuid_string(content[name])
        if content["correlation_id"] != content["command_id"]:
            raise ValueError
        for name, kind in (("execution_envelope_ref", "execution_envelope"),
                           ("runtime_profile_ref", "runtime_profile")):
            if EntityRef.from_dict(content[name]).kind != kind:
                raise ValueError
        positive_integer(content["lease_fence"])
        for name, pattern in (
            ("connection_id", HASH_PATTERN), ("requester_boot_id", BOOT_PATTERN),
            ("worker_boot_id", BOOT_PATTERN), ("channel_id", NAME_PATTERN),
            ("requester_service", NAME_PATTERN), ("responder_service", NAME_PATTERN),
            ("message_type", NAME_PATTERN),
        ):
            if type(content[name]) is not str or re.fullmatch(pattern, content[name]) is None:
                raise ValueError
            if name in {"channel_id", "requester_service", "responder_service", "message_type"} \
                    and len(content[name]) > 64:
                raise ValueError
        if (content["requester_boot_id"] == content["worker_boot_id"]
                or content["requester_service"] == content["responder_service"]):
            raise ValueError
        payload = BlobRef.from_dict(content["payload_blob"])
        artifacts = content["artifacts"]
        if type(artifacts) is not list or len(artifacts) > 256:
            raise ValueError
        descriptors = []
        for item in artifacts:
            if type(item) is not dict or set(item) != {"descriptor", "blob"}:
                raise ValueError
            descriptor = ArtifactDescriptor(**item["descriptor"])
            blob = BlobRef.from_dict(item["blob"])
            if (descriptor.request_id != content["command_id"]
                    or descriptor.declared_size != blob.size or descriptor.sha256 != blob.sha256
                    or blob.vault_id != payload.vault_id or blob.purpose != payload.purpose):
                raise ValueError
            descriptors.append(descriptor)
        if descriptors:
            validate_batch(descriptors, StreamLimits())
    except (KeyError, TypeError, ValueError, ArtifactStreamError):
        raise DomainContractError("Invalid closed worker response capture") from None


def capture_content_schema():
    from .schema_exports import (
        DOMAIN_ID,
        _constant,
        _hash,
        _object,
        _positive,
        _ref,
        _uuid,
    )
    from .schemas import PURPOSES

    blob = _object({"vault_id": _uuid(), "purpose": {"enum": sorted(PURPOSES)},
                    "sha256": _hash(), "size": {"type": "integer", "minimum": 0,
                                                "maximum": 2**63 - 1}})
    # JSON Schema uses search semantics; `$` permits a trailing line terminator.
    # This negative lookahead is a strict end assertion in both Python and ECMAScript.
    strict_end = r"(?![\s\S])"
    stream_uuid = {"type": "string", "pattern":
                   "^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
                   + strict_end}
    descriptor = _object({
        "batch_id": stream_uuid, "request_id": stream_uuid,
        "ordinal": {"type": "integer", "minimum": 0, "maximum": 255},
        "count": {"type": "integer", "minimum": 1, "maximum": 256},
        "media_type": {"type": "string", "pattern": "^" + MEDIA_PATTERN + strict_end},
        "declared_size": {"type": "integer", "minimum": 0, "maximum": 64 * 1024 * 1024},
        "sha256": _hash(),
    })
    properties = {"capture_schema_version": _constant(CAPTURE_VERSION),
                  "lease_fence": _positive(), "connection_id": _hash(),
                  "payload_blob": blob,
                  "artifacts": {"type": "array", "maxItems": 256,
                                "items": _object({"descriptor": descriptor, "blob": blob})}}
    for name in ("command_id", "attempt_id", "permit_id", "message_id", "correlation_id"):
        properties[name] = _uuid()
    for name, kind in (("execution_envelope_ref", "execution_envelope"),
                       ("runtime_profile_ref", "runtime_profile")):
        value = _ref(kind)
        value["allOf"][0]["$ref"] = DOMAIN_ID + "#/$defs/EntityRef"
        properties[name] = value
    for name in ("requester_boot_id", "worker_boot_id", "channel_id", "requester_service",
                 "responder_service", "message_type"):
        pattern = BOOT_PATTERN if name.endswith("boot_id") else NAME_PATTERN
        properties[name] = {"type": "string", "pattern": "^" + pattern + strict_end}
        if not name.endswith("boot_id"):
            properties[name]["maxLength"] = 64
    return _object(properties)


def capture_schema():
    from .schema_exports import DRAFT

    return {"$schema": DRAFT, "$id": "urn:deeptwin:schemas:v1:worker-response-capture",
            **capture_content_schema(),
            "$comment": "Closed content only. Runtime also checks exact ordered batch, correlation, "
                        "blob partitions and original dispatch binding. No semantic acceptance."}
