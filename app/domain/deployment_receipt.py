"""Closed immutable receipt anchors; valid structure grants no receipt authority."""

from jsonschema import Draft202012Validator, FormatChecker

from .refs import DomainContractError, EntityRef, canonical_json, uuid_string


def _entity(kind):
    from .schema_exports import _constant, _hash, _object, _uuid

    return _object(
        {
            "kind": _constant(kind),
            "id": _uuid(),
            "version": _constant(1),
            "sha256": _hash(),
        }
    )


def _blob(cap):
    from .schema_exports import _constant, _hash, _object, _uuid

    return _object(
        {
            "vault_id": _uuid(),
            "purpose": _constant("operational"),
            "sha256": _hash(),
            "size": {"type": "integer", "minimum": 1, "maximum": cap},
        }
    )


def receipt_content_schema():
    from .schema_exports import _constant, _object, _uuid

    return _object(
        {
            "schema_version": _constant("deployment-receipt-anchor-v1"),
            "receipt_blob_ref": _blob(16384),
            "request_ref": _entity("deployment_request"),
            "trust_blob_ref": _blob(16384),
            "ingress_blob_ref": _blob(8192),
            "consumption_exchange_blob_ref": _blob(8192),
            "import_command_id": _uuid(),
        }
    )


def _consumption_v1_schema():
    from ..deployment.prepare_schema_exports import timestamp
    from .schema_exports import _constant, _enum, _object, _uuid

    return _object(
        {
            "schema_version": _constant("deployment-receipt-consumption-anchor-v1"),
            "request_ref": _entity("deployment_request"),
            "receipt_ref": _entity("deployment_receipt"),
            "winning_lifecycle_revision": _constant(2),
            "consumed_at": timestamp(),
            "actor_ref": _entity("actor"),
            "transaction_id": _uuid(),
            "public_event_id": _uuid(),
            "outcome": _enum({"failed", "unknown"}),
        }
    )


def _consumption_v2_schema():
    """Success consumption (journal v3 §4): revision 3, `succeeded`, and the
    installation the acceptance created as `effect_ref`."""
    from ..deployment.prepare_schema_exports import timestamp
    from .schema_exports import _constant, _object, _uuid

    return _object(
        {
            "schema_version": _constant("deployment-receipt-consumption-anchor-v2"),
            "request_ref": _entity("deployment_request"),
            "receipt_ref": _entity("deployment_receipt"),
            "winning_lifecycle_revision": _constant(3),
            "consumed_at": timestamp(),
            "actor_ref": _entity("actor"),
            "transaction_id": _uuid(),
            "public_event_id": _uuid(),
            "outcome": _constant("succeeded"),
            "effect_ref": _entity("extension_installation"),
        }
    )


def consumption_content_variants():
    """The two closed consumption shapes with their parent arity: v1 has the
    request and receipt parents, v2 adds the installation it created."""
    return ((_consumption_v1_schema(), 2), (_consumption_v2_schema(), 3))


def consumption_content_schema():
    """Exactly one of the two closed consumption shapes, selected by schema_version."""
    return {"oneOf": [schema for schema, _arity in consumption_content_variants()]}


def _valid_schema(value, schema):
    return Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value)


def validate_receipt_body(body):
    """Validate only the immutable receipt envelope; storage proves its graph later."""
    from .store import BlobRef

    try:
        provider = isinstance(body["content"], dict) and body["content"].get("schema_version") == "deployment-provider-receipt-anchor-v1"
        schema = receipt_content_schema()
        if provider:
            from ..deployment.provider_receipt_schema_exports import provider_receipt_anchor_v1_schema
            from ..deployment.provider_receipt_contracts import validate_provider_channel_identity
            schema = provider_receipt_anchor_v1_schema()
            validate_provider_channel_identity(body["content"]["channel_identity"])
        if len(canonical_json(body)) > 8192 or not _valid_schema(
            body["content"], schema
        ):
            raise ValueError
        content = body["content"]
        request = EntityRef.from_dict(content["request_ref"])
        blobs = [
            BlobRef.from_dict(content[name])
            for name in (("receipt_blob_ref",) if provider else (
                "receipt_blob_ref",
                "trust_blob_ref",
                "ingress_blob_ref",
                "consumption_exchange_blob_ref",
            ))
        ]
        uuid_string(content["import_command_id"])
        if (
            type(body["version"]) is not int
            or body["version"] != 1
            or body["purpose"] != "operational"
            or request.kind != "deployment_request"
            or request.version != 1
            or body["id"] != request.id
            or body["parent_refs"] != [content["request_ref"]]
            or len({value.vault_id for value in blobs}) != 1
            or any(value.purpose != "operational" for value in blobs)
        ):
            raise ValueError
    except (DomainContractError, KeyError, TypeError, ValueError, RecursionError):
        raise DomainContractError("Invalid deployment receipt anchor") from None


def validate_consumption_body(body):
    """Validate only one inert consumption shape; no event existence is inferred."""
    try:
        if len(canonical_json(body)) > 8192 or not _valid_schema(
            body["content"], consumption_content_schema()
        ):
            raise ValueError
        content = body["content"]
        request = EntityRef.from_dict(content["request_ref"])
        receipt = EntityRef.from_dict(content["receipt_ref"])
        actor = EntityRef.from_dict(content["actor_ref"])
        uuid_string(content["transaction_id"])
        uuid_string(content["public_event_id"])
        parents = [content["request_ref"], content["receipt_ref"]]
        if content["schema_version"] == "deployment-receipt-consumption-anchor-v2":
            # success: the installation the acceptance created is the third
            # parent and the effect; the schema already fixed revision,
            # outcome and the effect kind/version (rechecked as defence)
            effect = EntityRef.from_dict(content["effect_ref"])
            if effect.kind != "extension_installation" or effect.version != 1:
                raise ValueError
            parents.append(content["effect_ref"])
        if (
            type(body["version"]) is not int
            or body["version"] != 1
            or body["purpose"] != "operational"
            or request.kind != "deployment_request"
            or request.version != 1
            or receipt.kind != "deployment_receipt"
            or receipt.version != 1
            or receipt.id != request.id
            or actor.kind != "actor"
            or body["actor_ref"] != content["actor_ref"]
            or body["parent_refs"] != parents
            or body["created_at_utc"] != content["consumed_at"][:-1] + "000Z"
        ):
            raise ValueError
    except (DomainContractError, KeyError, TypeError, ValueError, RecursionError):
        raise DomainContractError(
            "Invalid deployment receipt consumption anchor"
        ) from None
