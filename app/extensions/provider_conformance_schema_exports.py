"""Detached structural schemas for the provider conformance boundary."""

from copy import deepcopy
import json
from pathlib import Path


DRAFT = "https://json-schema.org/draft/2020-12/schema"
URN = "urn:deeptwin:schemas:v2:extensions:"
MAX_TIME = 253402300799999


def _object(properties, *, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else list(required),
            "additionalProperties": False}


def _const(value):
    return {"type": "integer" if type(value) is int else "string", "const": value}


def _uuid():
    return {"type": "string", "minLength": 36, "maxLength": 36,
        "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        "not": {"const": "00000000-0000-0000-0000-000000000000"}}


def _hash():
    return {"type": "string", "minLength": 64, "maxLength": 64, "pattern": "^[0-9a-f]{64}$"}


def _ref(kind=None, version=None):
    result = _object({"kind": {"type": "string"}, "id": _uuid(),
                      "version": {"type": "integer", "minimum": 1}, "sha256": _hash()})
    if kind is not None:
        result["properties"]["kind"] = _const(kind)
    if version is not None:
        result["properties"]["version"] = _const(version)
    return result


def _blob():
    return _object({"vault_id": _uuid(), "purpose": _const("operational"), "sha256": _hash(),
                    "size": {"type": "integer", "minimum": 0, "maximum": 1048576}})


def _subject():
    return _object({"vault_id": _uuid(),
        "instance_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
        "origin_digest": _hash(), "topology_id": _uuid(), "source_context_sha256": _hash(),
        "provider_geometry_sha256": _hash(), "installation_ref": _ref("extension_installation", 1),
        "candidate_ref": _ref("extension_manifest", 1), "request_ref": _ref("deployment_request", 1),
        "receipt_ref": _ref("deployment_receipt", 1),
        "platform": {"type": "string", "enum": ["linux/amd64", "linux/arm64"]},
        "selected_platform_entry_digest": _hash(),
        "image_manifest_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "service_descriptor_digest": _hash(),
        "service_identity": {"type": "string", "minLength": 1, "maxLength": 64,
                             "pattern": "^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$"},
        "slot_id": {"type": "integer", "minimum": 1, "maximum": 16},
        "build_identity_digest": _hash(), "port_schema_set_digest": _hash(),
        "port_contract_version": _const("provider-port-v1"),
        "worker_profile": _const("claude-text-transform-v1"),
        "implemented_transforms": {"type": "array", "prefixItems": [_const("catalog"), _const("text")],
                                     "items": False, "minItems": 2, "maxItems": 2}})


def input_schema():
    return {"$schema": DRAFT, "$id": URN + "provider-conformance-input-v1",
            'oneOf':[_object({"command_id": _uuid(),"installation_ref": _ref("extension_installation", 1)}),
                _object({'schema_version':_const('provider-conformance-command-v2'),'command_id':_uuid(),
                    'staged_installation_ref':_ref('extension_installation',1),
                    'expected_verified_installation_ref':_ref('extension_installation',2)})]}


def _legacy_reply_schema():
    common = {"schema_version": _const("provider-conformance-reply-v1"), "command_id": _uuid(),
        "installation_ref": _ref("extension_installation", 1),
        "intent_ref": _ref("provider_conformance_run", 1),
        "suite_version": _const("private-provider-conformance-v1"), "suite_sha256": _hash(),
        "context_sha256": _hash(),
        "event_cursor": {"type": "string", "minLength": 1, "maxLength": 4096},
        "links": _object({"self": {"type": "string", "minLength": 1, "maxLength": 512},
                          "events": {"type": "string", "minLength": 1, "maxLength": 512}})}
    def variant(result, state, completed, matched):
        properties = {"result_ref": result, "state": _const(state),
                      "completed_count": _const(completed), "matched_count": _const(matched)}
        return {"type": "object", "properties": properties,
                "required": list(properties)}

    variants = [
        variant({"type": "null"}, "pending", 0, 0),
        variant(_ref("provider_conformance_run", 2), "matched", 4, 4),
    ]
    for state in ("mismatch", "incomplete"):
        for completed in range(5):
            for matched in range(completed + 1):
                variants.append(variant(_ref("provider_conformance_run", 2), state,
                                        completed, matched))
    base = _object({**common,
        "result_ref": {"oneOf": [{"type": "null"}, _ref("provider_conformance_run", 2)]},
        "state": {"type": "string", "enum": ["pending", "matched", "mismatch", "incomplete"]},
        "completed_count": {"type": "integer", "minimum": 0, "maximum": 4},
        "matched_count": {"type": "integer", "minimum": 0, "maximum": 4}})
    return {"$schema": DRAFT, "$id": URN + "provider-conformance-reply-v1",
            **base, "oneOf": variants}


def reply_schema():
    old = _legacy_reply_schema()
    legacy = {key:value for key,value in old.items() if key not in ('$schema','$id')}
    verified = deepcopy(legacy)
    properties = verified['properties']
    del properties['installation_ref'],properties['context_sha256']
    properties.update(schema_version=_const('provider-conformance-reply-v2'),
        staged_installation_ref=_ref('extension_installation',1),verified_installation_ref=_ref('extension_installation',2),
        stage_context_sha256=_hash(),admission_sha256=_hash())
    verified['required'] = list(properties)
    return {'$schema':DRAFT,'$id':old['$id'],'oneOf':[legacy,verified]}


def _verified_admission():
    return _object({'schema_version':_const('provider-conformance-verified-admission-v1'),
        'stage_subject':_subject(),'stage_context_sha256':_hash(),
        'staged_installation_ref':_ref('extension_installation',1),'verified_installation_ref':_ref('extension_installation',2),
        'installation_head_hash':_hash(),'release_review_sha256':_hash(),'verification_source_context_sha256':_hash()})


def _verified_intent_content():
    properties = _intent_content()['properties']
    for name in ('installation_ref','subject','context_sha256'): del properties[name]
    properties.update(schema_version=_const('provider-conformance-intent-v2'),
        staged_installation_ref=_ref('extension_installation',1),verified_installation_ref=_ref('extension_installation',2),
        admission=_verified_admission(),admission_sha256=_hash())
    return _object(properties)


def _verified_report_content():
    properties = _report_content()['properties']
    del properties['installation_ref'],properties['context_sha256']
    properties.update(schema_version=_const('provider-conformance-report-v2'),
        staged_installation_ref=_ref('extension_installation',1),verified_installation_ref=_ref('extension_installation',2),
        admission_sha256=_hash(),stage_context_sha256=_hash())
    return _object(properties)


def _intent_content():
    return _object({"schema_version": _const("provider-conformance-intent-v1"), "command_id": _uuid(),
        "request_sha256": _hash(), "installation_ref": _ref("extension_installation", 1),
        "subject": _subject(), "context_sha256": _hash(),
        "suite_version": _const("private-provider-conformance-v1"), "suite_sha256": _hash(),
        "requester_version": _const("private-provider-requester-v1"),
        "comparator_version": _const("private-provider-literal-oracle-v1"),
        "admitted_ms": {"type": "integer", "minimum": 0, "maximum": MAX_TIME - 60000},
        "deadline_ms": {"type": "integer", "minimum": 60000, "maximum": MAX_TIME}})


def _report_content():
    vector_ids = ("text-basic-v1", "text-refusal-v1", "catalog-two-pages-v1",
                  "catalog-negative-capability-v1")
    vector = lambda vector_id: _object({"vector_id": _const(vector_id),
        "comparison": {"type": "string", "enum": ["matched", "mismatch", "not_observed"]}})
    return _object({"schema_version": _const("provider-conformance-report-v1"), "command_id": _uuid(),
        "intent_ref": _ref("provider_conformance_run", 1),
        "installation_ref": _ref("extension_installation", 1), "context_sha256": _hash(),
        "suite_sha256": _hash(), "finished_ms": {"type": "integer", "minimum": 0, "maximum": MAX_TIME},
        "elapsed_ms": {"oneOf": [{"type": "null"}, {"type": "integer", "minimum": 0,
                                                                   "maximum": 2**63 - 1}]},
        "observations_blob_ref": {"oneOf": [{"type": "null"}, _blob()]},
        "completion": {"type": "string", "enum": ["matched", "mismatch", "incomplete"]},
        "reason": {"type": "string", "enum": ["compared", "connection_unavailable",
            "identity_mismatch", "source_changed", "protocol_error", "deadline", "observation_limit",
            "interrupted", "owner_revoked", "storage_unavailable"]},
        "vectors": {"type": "array", "prefixItems": [vector(value) for value in vector_ids],
                    "items": False, "minItems": 4, "maxItems": 4},
        "covered_subchecks": {"type": "array", "maxItems": 4, "uniqueItems": True,
            "items": {"type": "string", "enum": list(vector_ids)}},
        "recovery_command_id": {"oneOf": [{"type": "null"}, _uuid()]}})


def _header(content, version, parents):
    timestamp = {"type": "string", "pattern":
        "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$"}
    return _object({"schema_version": _const("domain-v1"), "kind": _const("provider_conformance_run"),
        "id": _uuid(), "version": _const(version), "created_at_utc": timestamp,
        "actor_ref": _ref("actor"), "parent_refs": parents, "purpose": _const("operational"),
        "access_policy_ref": _ref("access_policy"), "retention_policy_ref": _ref("retention_policy"),
        "content": content})


def record_body_condition():
    intent_parents = {"type": "array", "prefixItems": [_ref("extension_installation", 1)],
                      "items": False, "minItems": 1, "maxItems": 1}
    report_parents = {"type": "array", "prefixItems": [_ref("provider_conformance_run", 1),
        _ref("extension_installation", 1)], "items": False, "minItems": 2, "maxItems": 2}
    def verified_parents(prior):
        return {**prior,'prefixItems':[*prior['prefixItems'],_ref('extension_installation',2)],
            'minItems':prior['minItems']+1,'maxItems':prior['maxItems']+1}
    return {"oneOf": [_header(_intent_content(), 1, intent_parents),
                      _header(_report_content(), 2, report_parents),
        _header(_verified_intent_content(),1,verified_parents(intent_parents)),
        _header(_verified_report_content(),2,verified_parents(report_parents))]}


def record_schema():
    intent_parents = {"type": "array", "prefixItems": [_ref("extension_installation", 1)],
                      "items": False, "minItems": 1, "maxItems": 1}
    report_parents = {"type": "array", "prefixItems": [_ref("provider_conformance_run", 1),
        _ref("extension_installation", 1)], "items": False, "minItems": 2, "maxItems": 2}
    base = _object({"ref": _ref("provider_conformance_run"),
                    "body": record_body_condition()})
    return {"$schema": DRAFT, "$id": URN + "provider-conformance-record-v1", **base, "oneOf": [
        _object({'ref':_ref('provider_conformance_run',1 if index % 2 == 0 else 2),'body':body})
        for index,body in enumerate(record_body_condition()['oneOf'])]}


def exported_schemas():
    return {name: deepcopy(schema) for name, schema in (
        ("provider-conformance-input-v1.schema.json", input_schema()),
        ("provider-conformance-reply-v1.schema.json", reply_schema()),
        ("provider-conformance-record-v1.schema.json", record_schema()))}


def write_schemas(destination):
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    for name, schema in exported_schemas().items():
        (root / name).write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8")
