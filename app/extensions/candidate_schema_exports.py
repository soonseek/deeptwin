"""Structural candidate schemas, distinct from historical v1 extension artifacts.

Runtime additionally verifies canonical byte bounds, URI/host canonicality, refs,
digest equality, numeric versions, ordering, identity and inert authority limits.
"""

import json
from pathlib import Path

from .port_contracts import PORT_CONTRACTS

DRAFT = "https://json-schema.org/draft/2020-12/schema"
ID = r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?"
BROKER = r"[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*"
HEX = r"[0-9a-f]{64}"
VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
KINDS = (
    "service_descriptor",
    "license",
    "provenance",
    "sbom",
    "network_declaration",
    "resource_declaration",
    "isolation_declaration",
)


def obj(**properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def text(maximum, pattern=None):
    result = {"type": "string", "minLength": 1, "maxLength": maximum}
    if pattern:
        # Unlike $, (?![\s\S]) does not also match immediately before final LF.
        result["pattern"] = "^(?:" + pattern + r")(?![\s\S])"
    return result


def enum(*values):
    return {"type": "string", "enum": list(values)}


def const(value):
    return {"type": "boolean" if type(value) is bool else "integer" if type(value) is int else "string", "const": value}


def integer(low, high):
    return {"type": "integer", "minimum": low, "maximum": high}


def array(item, low, high, unique=False):
    return {"type": "array", "items": item, "minItems": low, "maxItems": high, "uniqueItems": unique}


def uuid_schema():
    return {
        **text(36, r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"),
        "not": {"const": "00000000-0000-0000-0000-000000000000"},
    }


def meta(kind=None):
    return obj(
        document_kind=enum(*(KINDS if kind is None else (kind,))),
        sha256=text(64, HEX),
        size_bytes=integer(1, 262144 if kind == "service_descriptor" else 65536),
    )


def blob():
    return obj(vault_id=uuid_schema(), purpose=const("operational"), sha256=text(64, HEX), size=integer(1, 1048576))


def actor():
    return obj(kind=const("actor"), id=uuid_schema(), version=integer(1, 2**63 - 1), sha256=text(64, HEX))


def policies():
    return {
        "network_declaration": obj(
            schema_version=const("extension-network-declaration-v1"), network_mode=const("none")
        ),
        "resource_declaration": obj(
            schema_version=const("extension-resource-declaration-v1"),
            memory_bytes=integer(16777216, 4294967296),
            cpu_millicores=integer(100, 4000),
            pids_limit=integer(1, 256),
            tmpfs_bytes=integer(1048576, 1073741824),
        ),
        "isolation_declaration": obj(
            schema_version=const("extension-isolation-declaration-v1"),
            read_only_rootfs=const(True),
            no_new_privileges=const(True),
            cap_drop={"type": "array", "const": ["ALL"]},
            seccomp_profile=const("runtime-default"),
            privileged=const(False),
            host_namespaces={"type": "array", "maxItems": 0},
        ),
    }


def documents():
    leaves = {"license": text(65536), "sbom": {"type": "object"}, "provenance": {"type": "object"}, **policies()}
    return array({"oneOf": [obj(document_kind=const(k), content=v) for k, v in leaves.items()]}, 1, 32, True)


def refinement_definitions():
    """Closed structural vocabulary; runtime checks refs, bounds and schema semantics."""
    node = {"$ref": "#/$defs/RefinementNode"}
    strings = {"type": "string", "maxLength": 4096}
    mapping = {"type": "object", "maxProperties": 64, "additionalProperties": node}
    fields = {
        "$schema": const(DRAFT),
        "$ref": text(4096, r"#[^\x00-\x1f\x7f]*"),
        "$defs": mapping,
        "type": enum("object", "array", "string", "integer", "boolean", "null"),
        "additionalProperties": const(False),
        "properties": mapping,
        "required": array(strings, 0, 64, True),
        "items": node,
        "uniqueItems": {"type": "boolean"},
        "const": {},
        "enum": array({}, 1, 256, True),
    }
    for key in ("$comment", "description", "title", "pattern", "format"):
        fields[key] = strings
    for key in ("minLength", "maxLength"):
        fields[key] = integer(0, 4096)
    for key in ("minItems", "maxItems"):
        fields[key] = integer(0, 256)
    for key in ("minProperties", "maxProperties"):
        fields[key] = integer(0, 64)
    for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"):
        fields[key] = integer(-(2**53 - 1), 2**53 - 1)
    for key in ("allOf", "anyOf", "oneOf"):
        fields[key] = array(node, 1, 64)
    for key in ("not", "if", "then", "else"):
        fields[key] = node
    return {"RefinementNode": {"type": "object", "properties": fields, "additionalProperties": False}}


def manifest_schema():
    ident, version = text(128, ID), text(32, VERSION)
    refinement = {
        "allOf": [
            {"$ref": "#/$defs/RefinementNode"},
            {
                "type": "object",
                "properties": {"type": const("object"), "additionalProperties": const(False)},
                "required": ["type", "additionalProperties"],
            },
        ],
        "$comment": "Runtime validate_refinement_schema also validates local refs, type/bound relationships and Draft semantics.",
    }
    result = obj(
        schema_version=const("extension-manifest-v2"),
        extension_id=ident,
        extension_version=version,
        extension_kind=enum(
            *sorted({p.extension_kind for p in PORT_CONTRACTS.values() if p.artifact_form != "code_free_definition"})
        ),
        port_contract_version=enum(*sorted(PORT_CONTRACTS)),
        artifact=obj(
            artifact_form=enum(
                *sorted({p.artifact_form for p in PORT_CONTRACTS.values() if p.artifact_form != "code_free_definition"})
            ),
            service_descriptor_ref=meta("service_descriptor"),
        ),
        source=obj(
            kind=enum("third_party", "built_in", "operator_deployment"),
            locator=text(2048),
            provenance_ref=meta("provenance"),
        ),
        license=obj(expression=text(256), text_ref=meta("license")),
        compatibility=obj(
            framework_min=version,
            framework_max=version,
            extension_api_min=version,
            extension_api_max=version,
            schema_versions=array(enum("domain-v1"), 1, 16, True),
        ),
        refinements=obj(
            config=refinement,
            operations=array(
                obj(
                    operation=enum(*sorted({op for p in PORT_CONTRACTS.values() for op in p.operations})),
                    request=refinement,
                    result=refinement,
                    extension_error_codes=array(ident, 0, 64, True),
                ),
                0,
                52,
                True,
            ),
        ),
        requirements=obj(
            grant_ids=array(ident, 0, 64, True),
            network_policy_ref=meta("network_declaration"),
            resource_profile_ref=meta("resource_declaration"),
            isolation_profile_ref=meta("isolation_declaration"),
            filesystem_needs=array(enum("owned_scratch", "declared_named_volumes"), 0, 2, True),
            secret_needs=array(ident, 0, 16, True),
        ),
        migration_policy=enum("none", "compatible", "required"),
        uninstall_policy=enum("retain_records", "block_if_bound"),
    )
    return {**result, "$defs": refinement_definitions()}


def descriptor_schema():
    ident, broker = text(128, ID), text(64, BROKER)
    uid = integer(1, 2**32 - 1)

    def oci(kind):
        media = (
            ["application/vnd.oci.image.layer.v1.tar" + suffix for suffix in ("", "+gzip", "+zstd")]
            if kind == "layer"
            else ["application/vnd.oci.image." + kind + ".v1+json"]
        )
        return obj(media_type=enum(*media), digest=text(71, "sha256:" + HEX), size_bytes=integer(1, 2**40))

    def mount(socket):
        return obj(
            mount_id=broker,
            volume_name=broker,
            container_path=text(128),
            read_only=const(False) if socket else {"type": "boolean"},
            purpose=const("broker_pair" if socket else "extension_state"),
        )

    return obj(
        schema_version=const("extension-service-descriptor-v1"),
        extension_id=ident,
        extension_version=text(32, VERSION),
        port_contract_version=enum(*sorted(PORT_CONTRACTS)),
        service_identity=broker,
        image_repository=text(512),
        index=oci("index"),
        platforms=array(
            obj(
                platform=enum("linux/amd64", "linux/arm64"),
                manifest=oci("manifest"),
                config=oci("config"),
                layers=array(obj(position=integer(1, 128), **oci("layer")["properties"]), 1, 128),
            ),
            1,
            2,
            True,
        ),
        command=obj(argv=array(text(256), 1, 32), protocol_id=broker),
        uid=uid,
        gid=uid,
        network_policy_ref=meta("network_declaration"),
        resource_profile_ref=meta("resource_declaration"),
        isolation_profile_ref=meta("isolation_declaration"),
        secret_needs=array(ident, 0, 16, True),
        broker_endpoint=obj(
            channel_id=broker,
            requester_service=broker,
            responder_service=broker,
            protocol_id=broker,
            requester_uid=uid,
            requester_gid=uid,
            pair_gid=uid,
            socket_mount_id=broker,
            socket_name=broker,
        ),
        socket_mounts=array(mount(True), 1, 4, True),
        named_volume_mounts=array(mount(False), 0, 8, True),
        evidence=obj(sbom_ref=meta("sbom"), provenance_ref=meta("provenance"), license_ref=meta("license")),
    )


def registration_schema():
    return obj(
        schema_version=const("extension-candidate-registration-v1"),
        candidate_id=uuid_schema(),
        extension_id=text(128, ID),
        manifest_digest=text(64, HEX),
        service_descriptor_digest=text(64, HEX),
        support_refs=array(meta(), 1, 32, True),
        registered_by=actor(),
        registered_at=text(24, r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z"),
        source_class=const("owner_proposal"),
        command_id=uuid_schema(),
    )


def anchor_schema():
    return obj(
        schema_version=const("extension-candidate-anchor-v1"),
        candidate_id=uuid_schema(),
        manifest_blob_ref=blob(),
        service_descriptor_blob_ref=blob(),
        registration_blob_ref=blob(),
        support_documents=array(obj(document_kind=enum(*KINDS[1:]), blob_ref=blob()), 1, 32, True),
    )


def input_schema():
    return {
        **obj(
            command_id=uuid_schema(),
            manifest=manifest_schema(),
            service_descriptor=descriptor_schema(),
            documents=documents(),
        ),
        "$defs": refinement_definitions(),
    }


def api_schema():
    receipt = obj(
        command_id=uuid_schema(),
        state=const("registered_unqualified"),
        event_cursor=text(4096),
        links=obj(
            self=text(256, r"/(?:[0-9a-f]{32}/)?api/v1/extensions/candidates/[0-9a-f-]{36}"),
            events=text(128, r"/(?:[0-9a-f]{32}/)?api/v1/events"),
        ),
        candidate_ref=obj(
            candidate_id=uuid_schema(), manifest_digest=text(64, HEX), service_descriptor_digest=text(64, HEX)
        ),
        registration_digest=text(64, HEX),
    )
    read = obj(
        **receipt["properties"],
        registration=registration_schema(),
        manifest=manifest_schema(),
        service_descriptor=descriptor_schema(),
        documents=documents(),
    )
    error = obj(
        code=enum(
            "invalid_input",
            "unauthenticated",
            "access_denied",
            "not_found",
            "conflict",
            "too_large",
            "capacity",
            "unavailable",
        ),
        message=const("Candidate request could not be admitted"),
        retryability=const("not_retryable"),
        affected_refs={"type": "array", "maxItems": 0},
        correlation_id=uuid_schema(),
    )
    return {"oneOf": [input_schema(), receipt, read, error], "$defs": refinement_definitions()}


def exported_schemas():
    values = {
        "manifest-v2": manifest_schema(),
        "service-descriptor-v1": descriptor_schema(),
        "candidate-registration-v1": registration_schema(),
        "candidate-anchor-v1": anchor_schema(),
        "candidate-api-v1": api_schema(),
    }
    return {
        name + ".schema.json": {
            "$schema": DRAFT,
            "$id": "urn:deeptwin:schemas:v1:extensions:" + name,
            "$comment": "Structural only; runtime verifies byte/digest/ref/order/identity and authority relationships. Metadata grants no execution authority.",
            **value,
        }
        for name, value in values.items()
    }


if __name__ == "__main__":
    destination = Path(__file__).resolve().parents[2] / "schemas/v1/extensions"
    for name, value in exported_schemas().items():
        (destination / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
