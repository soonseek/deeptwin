"""Closed immutable request anchor; structural validation grants no preparation authority."""

from jsonschema import Draft202012Validator

from .refs import DomainContractError, EntityRef, canonical_json, uuid_string


def anchor_content_schema():
    from .schema_exports import _constant, _hash, _object, _uuid

    def blob(cap):
        return _object(
            {
                "vault_id": _uuid(),
                "purpose": _constant("operational"),
                "sha256": _hash(),
                "size": {"type": "integer", "minimum": 1, "maximum": cap},
            }
        )

    return _object(
        {
            "schema_version": _constant("deployment-request-anchor-v1"),
            "request_id": _uuid(),
            "request_blob_ref": blob(65536),
            "topology_blob_ref": blob(65536),
            "exchange_blob_ref": blob(8192),
            "candidate_ref": _object(
                {
                    "kind": _constant("extension_manifest"),
                    "id": _uuid(),
                    "version": _constant(1),
                    "sha256": _hash(),
                }
            ),
            "topology_id": _uuid(),
            "topology_revision": _constant(1),
            "slot_id": {"type": "integer", "minimum": 1, "maximum": 16},
            "reservation_revision": _constant(1),
            "prepare_command_id": _uuid(),
        }
    )


def validate_anchor_content(content):
    from .store import BlobRef

    try:
        if len(canonical_json(content)) > 8192 or not Draft202012Validator(
            anchor_content_schema()
        ).is_valid(content):
            raise ValueError
        for name in ("request_id", "topology_id", "prepare_command_id"):
            uuid_string(content[name])
        candidate = EntityRef.from_dict(content["candidate_ref"])
        if candidate.kind != "extension_manifest" or candidate.version != 1:
            raise ValueError
        blobs = [
            BlobRef.from_dict(content[key])
            for key in ("request_blob_ref", "topology_blob_ref", "exchange_blob_ref")
        ]
        if len({blob.vault_id for blob in blobs}) != 1 or any(
            blob.purpose != "operational" for blob in blobs
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError, RecursionError):
        raise DomainContractError("Invalid deployment request anchor") from None


def validate_anchor_body(body):
    validate_anchor_content(body["content"])
    if (
        type(body["version"]) is not int
        or body["version"] != 1
        or body["purpose"] != "operational"
        or body["id"] != body["content"]["request_id"]
        or body["parent_refs"] != [body["content"]["candidate_ref"]]
    ):
        raise DomainContractError("Invalid deployment request envelope")
