"""Portable structural schemas; runtime remains authoritative for bytes and trust."""

import json
from pathlib import Path

from .events import EVENT_TYPES, event_schema
from .refs import ENTITY_KINDS, LOCATOR_KINDS, MAX_INTEGER, MAX_ITEMS, MAX_STRING_BYTES
from .schemas import BOOTSTRAP_VERSION, GENESIS_VERSION, PURPOSES, ROOT_KINDS, SCHEMA_VERSION


DRAFT = "https://json-schema.org/draft/2020-12/schema"
DOMAIN_ID = "urn:deeptwin:schemas:v1:domain-envelopes"
EVENTS_ID = "urn:deeptwin:schemas:v1:event-metadata"


def _object(properties, *, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False}


def _constant(value):
    kind = "integer" if type(value) is int else "string"
    return {"type": kind, "const": value}


def _enum(values):
    return {"type": "string", "enum": sorted(values)}


def _uuid():
    return {"type": "string", "minLength": 36, "maxLength": 36,
            "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            "not": {"const": "00000000-0000-0000-0000-000000000000"}}


def _hash():
    return {"type": "string", "minLength": 64, "maxLength": 64,
            "pattern": "^[0-9a-f]{64}$"}


def _positive():
    return {"type": "integer", "minimum": 1, "maximum": MAX_INTEGER}


def _timestamp():
    return {"type": "string", "minLength": 27, "maxLength": 27,
            "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$",
            "format": "date-time",
            "$comment": "Runtime also validates the calendar date; format assertion support varies."}


def _ref(kind=None):
    reference = {"$ref": "#/$defs/EntityRef"}
    if kind is None:
        return reference
    return {"allOf": [reference, {"properties": {"kind": _constant(kind)}}]}


def _identity(schema_version, kind, *, bootstrap=False):
    return {"schema_version": _constant(schema_version), "kind": kind, "id": _uuid(),
            "version": _constant(1) if bootstrap else _positive(),
            "created_at_utc": _timestamp()}


def domain_schema():
    """Export base envelopes, including narrow acyclic bootstrap variants.

    No returned object shares mutable state with the runtime registries or another call.
    Feature-specific content schemas must further constrain DomainBody.content.
    """
    entity = _object({"kind": _enum(ENTITY_KINDS), "id": _uuid(),
                      "version": _positive(), "sha256": _hash()})
    locator = _object({"kind": _enum(LOCATOR_KINDS), "id": _uuid(),
                       "version": _positive(), "content_hash": _hash()}, required=["kind", "id"])
    locator["$comment"] = "Navigation only; an ObjectRef never substitutes for an EntityRef."
    ordinary = _identity(SCHEMA_VERSION, _enum(ENTITY_KINDS - {"vault_genesis"}))
    ordinary.update({"actor_ref": _ref("actor"),
                     "parent_refs": {"type": "array", "maxItems": 256, "uniqueItems": True,
                                     "items": _ref()},
                     "purpose": _enum(PURPOSES), "access_policy_ref": _ref("access_policy"),
                     "retention_policy_ref": _ref("retention_policy"),
                     "content": {"$ref": "#/$defs/CanonicalObject"}})
    genesis = _identity(GENESIS_VERSION, _constant("vault_genesis"), bootstrap=True)
    genesis.update({"vault_id": _uuid(), "profile": _constant("local-deny-by-default-v1")})
    genesis = _object(genesis)
    genesis["$comment"] = "Runtime requires id == vault_id. Parsing grants no installation authority."
    bootstrap = _identity(BOOTSTRAP_VERSION, _enum(ROOT_KINDS), bootstrap=True)
    bootstrap.update({"genesis_ref": _ref("vault_genesis"), "content": {"type": "object"}})
    bootstrap = _object(bootstrap)
    root_payloads = {
        "actor": _object({"id": _uuid(), "kind": _constant("system"),
                           "origin": _constant("host_service")}),
        "access_policy": _object({"profile": _constant("deny-by-default-v1")}),
        "retention_policy": _object({"core_mode": _constant("manual_only"),
                                      "cache_max_age_days": _constant(14),
                                      "cache_max_bytes": _constant(1_073_741_824),
                                      "diagnostics_max_age_days": _constant(30),
                                      "diagnostics_max_bytes": _constant(104_857_600)}),
    }
    bootstrap["oneOf"] = [{"properties": {"kind": _constant(kind), "content": payload}}
                          for kind, payload in root_payloads.items()]
    bootstrap["$comment"] = ("Runtime requires actor content.id == header id. Only authenticated "
                             "atomic first store initialization may install the three roots.")
    string = {"type": "string", "maxLength": MAX_STRING_BYTES,
              "pattern": "^[^\\uD800-\\uDFFF]*$",
              "$comment": "Runtime additionally limits UTF-8 byte length, not only character count."}
    canonical_object = {"type": "object", "maxProperties": MAX_ITEMS,
                        "propertyNames": {"$ref": "#/$defs/CanonicalString"},
                        "additionalProperties": {"$ref": "#/$defs/CanonicalValue"}}
    canonical_value = {"anyOf": [{"type": "null"}, {"type": "boolean"},
                                  {"type": "integer", "minimum": -MAX_INTEGER, "maximum": MAX_INTEGER},
                                  {"$ref": "#/$defs/CanonicalString"},
                                  {"type": "array", "maxItems": MAX_ITEMS,
                                   "items": {"$ref": "#/$defs/CanonicalValue"}},
                                  {"$ref": "#/$defs/CanonicalObject"}]}
    body_variants = {"oneOf": [{"$ref": "#/$defs/" + name}
                               for name in ("DomainBody", "GenesisBody", "BootstrapBody")]}
    record = _object({"ref": _ref(), "body": body_variants})
    record["$comment"] = ("Runtime verifies ref identity/version and SHA-256 against the exact "
                          "canonical body bytes. Mutable observation metadata is separate.")
    from .worker_response import capture_content_schema

    capture_content = capture_content_schema()
    for name in ("execution_envelope_ref", "runtime_profile_ref"):
        capture_content["properties"][name]["allOf"][0]["$ref"] = "#/$defs/EntityRef"
    ordinary_body = _object(ordinary)
    ordinary_body["allOf"] = [{
        "if": {"properties": {"kind": _constant("worker_response_capture")}},
        "then": {"properties": {"version": _constant(1), "content": capture_content}},
    }]
    from .deployment_request import anchor_content_schema

    ordinary_body["allOf"].append({
        "if": {"properties": {"kind": _constant("deployment_request")}},
        "then": {"properties": {"version": _constant(1), "purpose": _constant("operational"),
                                "content": anchor_content_schema(),
                                "parent_refs": {"type": "array", "minItems": 1, "maxItems": 1,
                                                "items": {"allOf": [_ref("extension_manifest"),
                                                                     {"properties": {"version": _constant(1)}}]}}}},
        "$comment": "Runtime also requires header id == content.request_id and the parent == content.candidate_ref.",
    })
    from .deployment_receipt import consumption_content_variants, receipt_content_schema

    receipt_request = _ref("deployment_request")
    receipt_request["allOf"].append({"properties": {"version": _constant(1)}})
    ordinary_body["allOf"].append({
        "if": {"properties": {"kind": _constant("deployment_receipt")}},
        "then": {"properties": {"version": _constant(1), "purpose": _constant("operational"),
                                "content": receipt_content_schema(),
                                "parent_refs": {"type": "array", "minItems": 1, "maxItems": 1,
                                                "items": receipt_request}}},
        "$comment": ("Runtime also requires header id and sole parent to match request_ref, "
                     "all four blobs to share one vault and the complete body to fit 8192 bytes. "
                     "Structure grants no import authority."),
    })
    consumption_request = _ref("deployment_request")
    consumption_request["allOf"].append({"properties": {"version": _constant(1)}})
    consumption_receipt = _ref("deployment_receipt")
    consumption_receipt["allOf"].append({"properties": {"version": _constant(1)}})
    consumption_installation = _ref("extension_installation")
    consumption_installation["allOf"].append({"properties": {"version": _constant(1)}})
    consumption_parents = [consumption_request, consumption_receipt, consumption_installation]
    ordinary_body["allOf"].append({
        "if": {"properties": {"kind": _constant("deployment_receipt_consumption")}},
        # each content variant is paired with its exact parent arity: the v1
        # non-success shape has the request and receipt parents, the v2 success
        # shape adds the installation it created
        "then": {"oneOf": [
            {"properties": {"version": _constant(1), "purpose": _constant("operational"),
                            "content": content,
                            "parent_refs": {"type": "array", "minItems": arity,
                                            "maxItems": arity,
                                            "prefixItems": consumption_parents[:arity],
                                            "items": False}}}
            for content, arity in consumption_content_variants()]},
        "$comment": ("Runtime also requires exact ordered duplicated parents, matching request/"
                     "receipt ids (and the v2 effect as the third parent), actor and six-digit "
                     "consumption time, and caps the complete body at 8192 bytes. Event syntax "
                     "proves no event exists."),
    })
    from .extension_installation import installation_content_schema

    installation_request = _ref("deployment_request")
    installation_request["allOf"].append({"properties": {"version": _constant(1)}})
    installation_receipt = _ref("deployment_receipt")
    installation_receipt["allOf"].append({"properties": {"version": _constant(1)}})
    ordinary_body["allOf"].append({
        "if": {"properties": {"kind": _constant("extension_installation")}},
        "then": {"properties": {"version": _constant(1), "purpose": _constant("operational"),
                                "content": installation_content_schema(),
                                "parent_refs": {"type": "array", "minItems": 2, "maxItems": 2,
                                                "prefixItems": [installation_request,
                                                                installation_receipt],
                                                "items": False}}},
        "$comment": ("Runtime also requires the ordered duplicated request/receipt parents with "
                     "matching ids, the actor, the six-digit installation time, an operational "
                     "evidence blob and the 8192-byte cap. Structure grants no installation, "
                     "acceptance or head authority."),
    })
    return {"$schema": DRAFT, "$id": DOMAIN_ID,
            "title": "DeepTwin version 1 immutable record envelopes", "$ref": "#/$defs/Record",
            "$comment": ("Structural envelope contract only. Runtime also checks canonical compact "
                         "sorted UTF-8 bytes, integer lexical representation, Unicode scalars, "
                         "64 KiB strings, 1 MiB total bytes, depth 32 and 10000 total items, "
                         "reference/body equality, non-self/future parents, hash integrity, "
                         "same-vault resolution, lineage, trusted provenance and authorization. "
                         "Feature schemas further constrain domain content. Schema validity "
                         "never grants root installation, human approval or dispatch authority."),
            "$defs": {"EntityRef": entity, "ObjectRef": locator,
                      "DomainBody": ordinary_body, "GenesisBody": genesis,
                      "BootstrapBody": bootstrap, "Record": record,
                      "CanonicalString": string, "CanonicalObject": canonical_object,
                      "CanonicalValue": canonical_value}}


def events_schema():
    """Export exact registered metadata payloads, selected through their $defs fragment."""
    return {"$schema": DRAFT, "$id": EVENTS_ID,
            "title": "DeepTwin version 1 public event metadata payloads",
            "$comment": ("Select the exact event type through #/$defs/<category.action>. "
                         "This document is a payload schema registry, not the EventEnvelope "
                         "or a substitute for authenticated emission or private-detail access. "
                         "Metadata observations are optional unless the selected event schema "
                         "requires its exact field set; absence means unknown."),
            "$defs": {name: event_schema(name) for name in sorted(EVENT_TYPES)}}


def write_domain_schemas(destination):
    """Deterministically export domain registries and the closed capture content."""
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    from ..services.owner_auth_schema import owner_auth_schema
    from .worker_response import capture_schema

    for name, schema in (
        ("domain-envelopes.schema.json", domain_schema()),
        ("event-metadata.schema.json", events_schema()),
        ("worker-response-capture.schema.json", capture_schema()),
        ("owner-auth-public.schema.json", owner_auth_schema()),
    ):
        (root / name).write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
