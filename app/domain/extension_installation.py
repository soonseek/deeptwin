"""Closed immutable `extension_installation` anchor (`extension-installation-anchor-v1`;
contracts/deployment-receipt-journal-v3.md §4).

The durable stage-installation record: revision 1 from an absent head, the
request/receipt it was accepted from, the presealed postcondition evidence
blob and the consume command id. Valid structure grants no installation,
acceptance, head, qualification or binding authority; the registry-owned
`extension-installation-v1` shape (app/extensions/contracts.py) coexists
in memory and is never written as a domain anchor by this path.
"""

from jsonschema import Draft202012Validator, FormatChecker

from .refs import DomainContractError, EntityRef, canonical_json, uuid_string

SCHEMA_VERSION = "extension-installation-anchor-v1"
STAGING_AUTHORITY = "deployment-receipt-v1"
PLATFORMS = ("linux/amd64", "linux/arm64")
_ID = r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?"
_BROKER = r"[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*"
_HEX = "[0-9a-f]{64}"
_MAX_BODY_BYTES = 8_192
_EVIDENCE_CAP = 8_192


def installation_content_schema():
    # `text` anchors with a lookahead: jsonschema patterns run under re.search,
    # where a bare `$` would also admit a value with a trailing newline
    from ..deployment.prepare_schema_exports import timestamp
    from ..extensions.candidate_schema_exports import text
    from .deployment_receipt import _blob, _entity
    from .schema_exports import _constant, _enum, _object, _uuid

    return _object(
        {
            "schema_version": _constant(SCHEMA_VERSION),
            "extension_id": text(128, _ID),
            "manifest_digest": text(64, _HEX),
            "service_descriptor_digest": text(64, _HEX),
            "selected_platform_entry_digest": text(64, _HEX),
            "image_manifest_digest": text(71, "sha256:" + _HEX),
            "platform": _enum(set(PLATFORMS)),
            "service_identity": text(64, _BROKER),
            "staging_authority": _constant(STAGING_AUTHORITY),
            "request_ref": _entity("deployment_request"),
            "receipt_ref": _entity("deployment_receipt"),
            "postcondition_evidence_blob_ref": _blob(_EVIDENCE_CAP),
            "consume_command_id": _uuid(),
            "state": _constant("staged"),
            "revision": _constant(1),
            "previous_record_digest": {"type": "null"},
            "installed_at": timestamp(),
            "actor_ref": _entity("actor"),
        }
    )


def validate_installation_body(body):
    """Validate only the immutable installation envelope; storage proves its
    graph, blob and head later and no acceptance is inferred."""
    from .store import BlobRef

    try:
        if isinstance(body["content"], dict) and body["content"].get("schema_version") == "provider-installation-verified-v1":
            _validate_verified_body(body)
            return
        schema = installation_content_schema()
        if isinstance(body["content"], dict) and body["content"].get("schema_version") == "extension-provider-installation-anchor-v1":
            from ..deployment.provider_receipt_schema_exports import provider_installation_anchor_v1_schema
            schema = provider_installation_anchor_v1_schema()
        if len(canonical_json(body)) > _MAX_BODY_BYTES or not Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).is_valid(body["content"]):
            raise ValueError
        content = body["content"]
        request = EntityRef.from_dict(content["request_ref"])
        receipt = EntityRef.from_dict(content["receipt_ref"])
        actor = EntityRef.from_dict(content["actor_ref"])
        evidence = BlobRef.from_dict(content["postcondition_evidence_blob_ref"])
        uuid_string(content["consume_command_id"])
        if (
            type(body["version"]) is not int
            or body["version"] != 1
            or body["purpose"] != "operational"
            or type(content["revision"]) is not int
            or content["revision"] != 1
            or request.kind != "deployment_request"
            or request.version != 1
            or receipt.kind != "deployment_receipt"
            or receipt.version != 1
            or receipt.id != request.id
            or actor.kind != "actor"
            or evidence.purpose != "operational"
            or body["actor_ref"] != content["actor_ref"]
            or body["parent_refs"] != [content["request_ref"], content["receipt_ref"]]
            or body["created_at_utc"] != content["installed_at"][:-1] + "000Z"
        ):
            raise ValueError
    except (DomainContractError, KeyError, TypeError, ValueError, RecursionError):
        raise DomainContractError("Invalid extension installation anchor") from None


def _validate_verified_body(body):
    from datetime import datetime, timedelta, timezone
    from .store import BlobRef
    from ..extensions.provider_installation_schema_exports import installation_content_schema as verified_schema
    from ..extensions.provider_installation_contracts import parse_installation_header
    from ..extensions.lineage_contracts import _valid_version

    content = body['content']
    if len(canonical_json(body)) > 65536 or not Draft202012Validator(verified_schema()).is_valid(content):
        raise ValueError
    stage = EntityRef.from_dict(content['stage_ref'])
    if (type(body['version']) is not int or body['version'] != 2 or stage.version != 1
            or stage.kind != 'extension_installation' or body['id'] != stage.id
            or body['purpose'] != 'operational' or body['parent_refs'] != [stage.as_dict()]
            or content['previous_record_digest'] != stage.sha256 or not _valid_version(content['extension_version'])):
        raise ValueError
    instant = datetime(1970,1,1,tzinfo=timezone.utc) + timedelta(milliseconds=content['verified_at_ms'])
    if body['created_at_utc'] != instant.strftime('%Y-%m-%dT%H:%M:%S.%fZ'):
        raise ValueError
    sources = [BlobRef.from_dict(content[key]) for key in ('release_context_blob_ref','release_trust_blob_ref')]
    evidence = [BlobRef.from_dict(item['blob_ref']) for item in content['evidence']]
    if any(ref.purpose != 'operational' or ref.vault_id != sources[0].vault_id for ref in (*sources,*evidence)):
        raise ValueError
    if (content['release_source_context_sha256'] != sources[0].sha256
            or content['release_review_sha256'] != evidence[0].sha256):
        raise ValueError
    header = {'schema_version':'provider-installation-command-v1','command_id':content['command_id'],
        'staged_installation_ref':stage.as_dict(),'objects':[{'role':item['role'],'sha256':ref.sha256,'size_bytes':ref.size}
            for item,ref in zip(content['evidence'],evidence,strict=True)]}
    parse_installation_header(canonical_json(header))
