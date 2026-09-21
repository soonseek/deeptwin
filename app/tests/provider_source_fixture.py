"""Independent provider document oracle; only original receipt rendering is reused.

Image and public key are visibly synthetic declarations, never build/trust evidence.
No new producer/parser/schema factory is used to create expected bytes.
"""

import json
from base64 import urlsafe_b64encode
from hashlib import sha256

from app.domain.refs import canonical_json as encode
from app.deployment.receipt_render import render_receipt_sources
from app.tests.test_deployment_receipt_source_render import receipt_inputs

NAMES = (
    "original-prepare-recipe.json", "original-prepare-instance.json",
    "original-topology.json", "original-outgoing-exchange.json",
    "original-receipt-recipe.json", "original-receipt-instance.json",
    "original-trust-set.json", "original-receipt-ingress.json",
    "original-consumption-exchange.json", "geometry.json", "provider-recipe.json",
    "provider-instance.json", "provider-trust-set.json", "outgoing-exchange.json",
    "receipt-ingress.json", "consumption-exchange.json", "source-context.json",
    "source-pins.json",
)
IDS = tuple(f"{n:08d}-5555-4555-8555-{n:012d}" for n in range(5, 9))
IMAGE = "registry.example.invalid/synthetic/provider-init@sha256:" + "a" * 64


def digest(raw):
    return sha256(raw).hexdigest()


def reference(raw):
    return {"sha256": digest(raw), "size_bytes": len(raw)}


def recipe():
    return {
        "schema_version": "deployment-provider-source-recipe-v1",
        "recipe_id": "private-provider-source-channels-v1",
        "original_prepare_recipe": {
            "path": "deploy/security/deployment-prepare-recipe-v1.json",
            "sha256": "03490ee7c676a0c78915fdef3ec48c52d6b88838ad71bce001ad2fe72f5e67b7",
            "size_bytes": 606,
        },
        "original_receipt_recipe": {
            "path": "deploy/security/deployment-receipt-recipe-v1.json",
            "sha256": "3417fbc488ab745019b909564282cc9ff971c99fa2d5ba592e4faeb2f742e173",
            "size_bytes": 487,
        },
        "renderer_id": "deeptwin-provider-source-expand-v1",
        "initializer_id": "deeptwin-provider-source-init-v1",
        "layout_id": "provider-source-bundle-v1",
        "worker_profile": "claude-text-transform-v1",
        "channel_bootstrap_policy": "owned-channel-layout-v1",
        "bundle_file_limit": 18, "bundle_bytes_max": 524288,
        "request_bytes_max": 65536, "cancellation_bytes_max": 8192,
        "receipt_bytes_max": 16384, "consumption_bytes_max": 8192,
    }


def expected_geometry(raw, old):
    instance = json.loads(raw[3])
    origin = instance["origin_profile"]
    identity = origin["instance_id"]
    slots = []
    for n in range(1, instance["slot_capacity"] + 1):
        suffix = f"{n:02}"
        slots.append({
            "slot_number": n, "service_identity": f"ext-{identity}-{suffix}",
            "uid": 22000 + n, "gid": 22000 + n,
            "channel_id": f"cp-ext-{identity}-{suffix}", "pair_gid": 23000 + n,
            "socket_mount": {
                "mount_id": f"xs{suffix}", "volume_name": f"dt-{identity}-ipc-xs{suffix}",
                "container_path": f"/run/deeptwin/ipc/xs{suffix}",
                "read_only": False, "purpose": "broker_pair",
            },
            "socket_name": "worker.sock", "protocol_id": "deeptwin-extension-worker-v1",
            "resource_budget": {"memory_bytes": 1073741824, "cpu_millicores": 1000,
                                "pids_limit": 128, "tmpfs_bytes": 134217728},
        })
    return {
        "schema_version": "provider-stage-geometry-v1",
        "original_recipe": reference(raw[2]), "original_instance": reference(raw[3]),
        "original_topology": reference(old.prepare_artifacts.topology_bytes),
        "origin_profile": origin, "instance_id": identity,
        "topology_id": instance["topology_id"], "topology_revision": 1,
        "platform": instance["platform"],
        "control": {"service_identity": "control", "uid": 20102, "gid": 20102},
        "slots": slots,
    }


def case(**options):
    raw = receipt_inputs(**options)
    old = render_receipt_sources(*raw)
    g = encode(expected_geometry(raw, old))
    origin = json.loads(raw[3])["origin_profile"]
    identity = origin["instance_id"]
    r = encode(recipe())
    t = encode({
        "schema_version": "deployment-provider-public-trust-set-v1", "version": 1,
        "instance_id": identity, "origin_profile_digest": origin["digest"],
        "keys": [{"key_id": "99999999-9999-4999-8999-999999999999",
                  "algorithm": "ed25519",
                  "public_key": urlsafe_b64encode(b"synthetic-public-key-material-32").rstrip(b"=").decode(),
                  "trust_class": "instance_operator",
                  "adapter_ids": ["deeptwin-provider-stage-operator-v1"]}],
        "adapter": {"operator_adapter": "deeptwin-provider-stage-operator-v1",
                    "operator_version": "1.0.0",
                    "deployment_profile_id": origin["deployment_profile_id"]},
    })
    i = encode({
        "schema_version": "deployment-provider-source-instance-v1",
        "original_prepare_instance_sha256": digest(raw[3]),
        "original_receipt_instance_sha256": digest(raw[5]),
        "geometry_sha256": digest(g), "provider_recipe_sha256": digest(r),
        "provider_trust_sha256": digest(t), "context_id": IDS[0],
        "exchange_id": IDS[1], "ingress_id": IDS[2],
        "consumption_exchange_id": IDS[3], "initializer_image": IMAGE,
    })
    common = {
        "revision": 1, "instance_id": identity, "origin_profile_digest": origin["digest"],
        "geometry_sha256": digest(g), "provider_recipe_sha256": digest(r),
        "provider_instance_sha256": digest(i),
    }
    control = {"service_identity": "control", "uid": 20102, "gid": 20102}
    operator = {"service_identity": "deployment-receipt-job", "uid": 20113,
                "gid": 20113, "pair_gid": 21201}
    modes = {"group_gid": 21201, "root_mode": "0750", "namespace_mode": "0750",
             "final_file_mode": "0440"}
    e = encode({
        **common, "schema_version": "deployment-provider-outgoing-exchange-v1",
        "document_id": IDS[1], "control": control, "reader": operator,
        "outgoing": {**modes, "volume_name": f"dt-{identity}-provider-deployment-outbox",
                     "container_path": "/run/deeptwin/provider-deployment-outbox",
                     "owner_uid": 20102, "control_read_only": False,
                     "reader_read_only": True, "namespaces": ["cancelled", "requests"]},
    })
    ingress = encode({
        **common, "schema_version": "deployment-provider-receipt-ingress-v1",
        "document_id": IDS[2], "outgoing_exchange_sha256": digest(e),
        "trust_sha256": digest(t), "writer": operator,
        "reader": {**control, "pair_gid": 21201},
        "incoming": {**modes, "volume_name": f"dt-{identity}-provider-deployment-receipts",
                     "container_path": "/run/deeptwin/provider-deployment-receipts",
                     "owner_uid": 20113, "writer_read_only": False,
                     "control_read_only": True, "namespaces": ["receipts"]},
    })
    consumption = encode({
        **common, "schema_version": "deployment-provider-consumption-exchange-v1",
        "document_id": IDS[3], "outgoing_exchange_sha256": digest(e),
        "trust_sha256": digest(t), "receipt_ingress_sha256": digest(ingress),
        "control": control, "reader": operator,
        "outgoing": {**modes, "volume_name": f"dt-{identity}-provider-deployment-consumed",
                     "container_path": "/run/deeptwin/provider-deployment-consumed",
                     "owner_uid": 20102, "control_read_only": False,
                     "reader_read_only": True, "namespaces": ["consumed"]},
    })
    content = (raw[2], raw[3], old.prepare_artifacts.topology_bytes,
               old.prepare_artifacts.exchange_bytes, raw[4], raw[5], raw[6],
               old.ingress_bytes, old.consumption_exchange_bytes, g, r, i, t,
               e, ingress, consumption)
    context = encode({
        "schema_version": "deployment-provider-source-context-v1", "context_id": IDS[0],
        "epoch": 1, "instance_id": identity, "origin_profile_digest": origin["digest"],
        "topology_id": json.loads(raw[3])["topology_id"], "topology_revision": 1,
        "geometry_sha256": digest(g), "worker_profile": "claude-text-transform-v1",
        "layout_id": "provider-source-bundle-v1",
        "documents": [{"name": name, **reference(data)} for name, data in zip(NAMES, content)],
    })
    pins = encode({
        "schema_version": "deployment-provider-source-pins-v1", "instance_id": identity,
        "origin_profile_digest": origin["digest"], "context_id": IDS[0],
        "context_sha256": digest(context), "context_size_bytes": len(context),
        "provider_recipe_sha256": digest(r), "provider_instance_sha256": digest(i),
        "geometry_sha256": digest(g),
    })
    kwargs = dict(zip((
        "base_compose_bytes", "base_service_ids_bytes", "original_prepare_recipe_bytes",
        "original_prepare_instance_bytes", "original_receipt_recipe_bytes",
        "original_receipt_instance_bytes", "original_trust_bytes", "provider_recipe_bytes",
        "provider_instance_bytes", "provider_trust_bytes",
    ), (*raw, r, i, t)))
    return kwargs, tuple(zip(NAMES, (*content, context, pins))), old


def refresh_outer(bundle, index, value):
    """Mutate a document while fixing every outer context/pins hash, for join tests."""
    pairs = list(bundle)
    pairs[index] = (pairs[index][0], encode(value))
    context = json.loads(pairs[16][1])
    context["documents"] = [{"name": name, **reference(raw)} for name, raw in pairs[:16]]
    pairs[16] = (pairs[16][0], encode(context))
    pins = json.loads(pairs[17][1])
    pins["context_sha256"] = digest(pairs[16][1])
    pins["context_size_bytes"] = len(pairs[16][1])
    pairs[17] = (pairs[17][0], encode(pins))
    return tuple(pairs)
