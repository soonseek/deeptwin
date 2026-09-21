"""Fresh, closed Draft 2020-12 provider source declarations (not authority)."""

from copy import deepcopy


def _object(**properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


def _string(maximum=1024, pattern=None):
    value = {"type": "string", "minLength": 1, "maxLength": maximum}
    if pattern is not None:
        value["pattern"] = "^(?:" + pattern + ")$"
    return value


def _integer(low, high):
    return {"type": "integer", "minimum": low, "maximum": high}


def _constant(value):
    if type(value) is dict:
        return _object(**{key: _constant(child) for key, child in value.items()})
    if type(value) is list:
        return {"type": "array", "prefixItems": [_constant(child) for child in value],
                "minItems": len(value), "maxItems": len(value), "items": False}
    return {"const": deepcopy(value), "type": {str: "string", int: "integer", bool: "boolean"}[type(value)]}


def _array(item, minimum, maximum):
    return {"type": "array", "items": item, "minItems": minimum, "maxItems": maximum}


def _hash():
    return _string(64, "[0-9a-f]{64}")


def _identity():
    return _string(32, "[0-9a-f]{32}")


def _uuid():
    return _string(36, r"(?!00000000-0000-0000-0000-000000000000$)[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def _profile_id():
    return {"type": "string", "enum": ["local-no-terminal-v1", "portable-compose-v1"]}


def _document(stem, **properties):
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:deeptwin:schemas:v2:deployment:" + stem,
            **_object(**properties)}


def _reference(cap):
    return _object(sha256=_hash(), size_bytes=_integer(1, cap))


def _control(pair=False):
    value = {"service_identity": "control", "uid": 20102, "gid": 20102}
    if pair:
        value["pair_gid"] = 21201
    return _constant(value)


def _operator():
    return _constant({"service_identity": "deployment-receipt-job", "uid": 20113,
                      "gid": 20113, "pair_gid": 21201})


def provider_geometry_schema():
    from .contracts import BUDGET
    profile = _object(
        deployment_profile_id=_profile_id(), instance_id=_identity(),
        mode={"enum": ["local_loopback", "portable_https"]},
        scheme={"enum": ["http", "https"]}, host=_string(253), port=_integer(1, 65535),
        base_path=_string(34), origin_base=_string(1024), digest=_hash(),
    )
    slot = _object(
        slot_number=_integer(1, 16), service_identity=_string(39, r"ext-[0-9a-f]{32}-[0-9]{2}"),
        uid=_integer(22001, 22016), gid=_integer(22001, 22016),
        channel_id=_string(42, r"cp-ext-[0-9a-f]{32}-[0-9]{2}"), pair_gid=_integer(23001, 23016),
        socket_mount=_object(mount_id=_string(4, r"xs[0-9]{2}"),
                             volume_name=_string(44, r"dt-[0-9a-f]{32}-ipc-xs[0-9]{2}"),
                             container_path=_string(24, r"/run/deeptwin/ipc/xs[0-9]{2}"),
                             read_only=_constant(False), purpose=_constant("broker_pair")),
        socket_name=_constant("worker.sock"), protocol_id=_constant("deeptwin-extension-worker-v1"),
        resource_budget=_constant(BUDGET),
    )
    return _document("provider-stage-geometry-v1",
        schema_version=_constant("provider-stage-geometry-v1"),
        original_recipe=_object(sha256=_hash(), size_bytes=_constant(606)),
        original_instance=_reference(4096), original_topology=_reference(65536),
        origin_profile=profile, instance_id=_identity(), topology_id=_uuid(),
        topology_revision=_constant(1), platform={"enum": ["linux/amd64", "linux/arm64"]},
        control=_control(), slots=_array(slot, 1, 16))


def provider_recipe_schema():
    from .provider_source_contracts import PROVIDER_RECIPE_BYTES
    import json
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:deeptwin:schemas:v2:deployment:provider-source-recipe-v1",
            **_constant(json.loads(PROVIDER_RECIPE_BYTES))}


def provider_instance_schema():
    return _document("provider-source-instance-v1",
        schema_version=_constant("deployment-provider-source-instance-v1"),
        original_prepare_instance_sha256=_hash(), original_receipt_instance_sha256=_hash(),
        geometry_sha256=_hash(), provider_recipe_sha256=_hash(), provider_trust_sha256=_hash(),
        context_id=_uuid(), exchange_id=_uuid(), ingress_id=_uuid(), consumption_exchange_id=_uuid(),
        initializer_image=_string(584, r"[a-z0-9.:-]+/[a-z0-9/._-]+@sha256:[0-9a-f]{64}"))


def provider_trust_schema():
    return _document("provider-public-trust-set-v1",
        schema_version=_constant("deployment-provider-public-trust-set-v1"), version=_constant(1),
        instance_id=_identity(), origin_profile_digest=_hash(),
        keys=_array(_object(key_id=_uuid(), algorithm=_constant("ed25519"),
                            public_key=_string(43, r"[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]"),
                            trust_class=_constant("instance_operator"),
                            adapter_ids=_constant(["deeptwin-provider-stage-operator-v1"])), 1, 8),
        adapter=_object(operator_adapter=_constant("deeptwin-provider-stage-operator-v1"),
                        operator_version=_constant("1.0.0"), deployment_profile_id=_profile_id()))


def _channel(kind):
    ingress = kind == "receipt-ingress"
    consumption = kind == "consumption-exchange"
    suffix = "receipts" if ingress else "consumed" if consumption else "outbox"
    common = dict(schema_version=_constant("deployment-provider-" + kind + "-v1"),
                  document_id=_uuid(), revision=_constant(1), instance_id=_identity(),
                  origin_profile_digest=_hash(), geometry_sha256=_hash(),
                  provider_recipe_sha256=_hash(), provider_instance_sha256=_hash())
    if ingress or consumption:
        common.update(outgoing_exchange_sha256=_hash(), trust_sha256=_hash())
    if consumption:
        common["receipt_ingress_sha256"] = _hash()
    channel = dict(volume_name=_string(100, r"dt-[0-9a-f]{32}-provider-deployment-" + suffix),
                   container_path=_constant("/run/deeptwin/provider-deployment-" + suffix),
                   owner_uid=_constant(20113 if ingress else 20102), group_gid=_constant(21201),
                   root_mode=_constant("0750"), namespace_mode=_constant("0750"),
                   final_file_mode=_constant("0440"))
    if ingress:
        common.update(writer=_operator(), reader=_control(True))
        channel.update(writer_read_only=_constant(False), control_read_only=_constant(True),
                       namespaces=_constant(["receipts"]))
    else:
        common.update(control=_control(), reader=_operator())
        channel.update(control_read_only=_constant(False), reader_read_only=_constant(True),
                       namespaces=_constant(["consumed"] if consumption else ["cancelled", "requests"]))
    common["incoming" if ingress else "outgoing"] = _object(**channel)
    return _document("provider-" + kind + "-v1", **common)


def provider_exchange_schema():
    return _channel("outgoing-exchange")


def provider_ingress_schema():
    return _channel("receipt-ingress")


def provider_consumption_schema():
    return _channel("consumption-exchange")


def provider_context_schema():
    from .provider_source_contracts import BUNDLE_LAYOUT
    references = [_object(name=_constant(name), sha256=_hash(), size_bytes=_integer(1, cap))
                  for name, cap in BUNDLE_LAYOUT[:16]]
    return _document("provider-source-context-v1",
        schema_version=_constant("deployment-provider-source-context-v1"), context_id=_uuid(),
        epoch=_constant(1), instance_id=_identity(), origin_profile_digest=_hash(), topology_id=_uuid(),
        topology_revision=_constant(1), geometry_sha256=_hash(),
        worker_profile=_constant("claude-text-transform-v1"), layout_id=_constant("provider-source-bundle-v1"),
        documents={"type": "array", "prefixItems": references, "items": False, "minItems": 16, "maxItems": 16})


def provider_pins_schema():
    return _document("provider-source-pins-v1",
        schema_version=_constant("deployment-provider-source-pins-v1"), instance_id=_identity(),
        origin_profile_digest=_hash(), context_id=_uuid(), context_sha256=_hash(),
        context_size_bytes=_integer(1, 16384), provider_recipe_sha256=_hash(),
        provider_instance_sha256=_hash(), geometry_sha256=_hash())


def provider_expansion_record_schema():
    return _document("provider-source-expansion-record-v1",
        schema_version=_constant("deployment-provider-source-expansion-record-v1"),
        scope=_constant("provider_sources_only"), renderer_id=_constant("deeptwin-provider-source-expand-v1"),
        initializer_id=_constant("deeptwin-provider-source-init-v1"),
        original_expansion_sha256=_hash(), original_expansion_size_bytes=_integer(1, 1048576),
        original_expansion_record_sha256=_hash(), provider_recipe_sha256=_hash(),
        provider_instance_sha256=_hash(), geometry_sha256=_hash(), context_sha256=_hash(), pins_sha256=_hash(),
        initializer_image=provider_instance_schema()["properties"]["initializer_image"],
        expanded_compose_sha256=_hash(), expanded_compose_size_bytes=_integer(1, 1048576))


def exported_schemas():
    factories = (provider_geometry_schema, provider_recipe_schema, provider_instance_schema,
                 provider_trust_schema, provider_exchange_schema, provider_ingress_schema,
                 provider_consumption_schema, provider_context_schema, provider_pins_schema,
                 provider_expansion_record_schema)
    return {schema["$id"].rsplit(":", 1)[1] + ".schema.json": schema
            for schema in (factory() for factory in factories)}
