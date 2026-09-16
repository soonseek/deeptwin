"""Complete synthetic inert metadata; no images or network resources are used."""

from hashlib import sha256
from uuid import uuid4

from app.domain.refs import canonical_json


def candidate_payload():
    leaves = {
        "license": "Synthetic license\n",
        "provenance": {"builder": "synthetic"},
        "sbom": {"packages": []},
        "network_declaration": {"schema_version": "extension-network-declaration-v1", "network_mode": "none"},
        "resource_declaration": {
            "schema_version": "extension-resource-declaration-v1",
            "memory_bytes": 16777216,
            "cpu_millicores": 100,
            "pids_limit": 1,
            "tmpfs_bytes": 1048576,
        },
        "isolation_declaration": {
            "schema_version": "extension-isolation-declaration-v1",
            "read_only_rootfs": True,
            "no_new_privileges": True,
            "cap_drop": ["ALL"],
            "seccomp_profile": "runtime-default",
            "privileged": False,
            "host_namespaces": [],
        },
    }

    def ref(kind, content):
        raw = content.encode() if isinstance(content, str) else canonical_json(content)
        return {"document_kind": kind, "sha256": sha256(raw).hexdigest(), "size_bytes": len(raw)}

    refs = {kind: ref(kind, value) for kind, value in leaves.items()}
    requirements = {
        "network_policy_ref": refs["network_declaration"],
        "resource_profile_ref": refs["resource_declaration"],
        "isolation_profile_ref": refs["isolation_declaration"],
        "secret_needs": [],
    }

    def oci(kind):
        return {"media_type": "application/vnd.oci.image." + kind, "digest": "sha256:" + "a" * 64, "size_bytes": 100}

    descriptor = {
        "schema_version": "extension-service-descriptor-v1",
        "extension_id": "synthetic-tool",
        "extension_version": "1.0.0",
        "port_contract_version": "tool-port-v1",
        "service_identity": "synthetic-worker",
        "image_repository": "registry.example.test/tools/synthetic",
        "index": oci("index.v1+json"),
        "platforms": [
            {
                "platform": platform,
                "manifest": oci("manifest.v1+json"),
                "config": oci("config.v1+json"),
                "layers": [{"position": 1, **oci("layer.v1.tar+gzip")}],
            }
            for platform in ["linux/amd64", "linux/arm64"]
        ],
        "command": {"argv": ["/opt/extension/worker", "--serve"], "protocol_id": "deeptwin-extension-worker-v1"},
        "uid": 2001,
        "gid": 2001,
        **requirements,
        "broker_endpoint": {
            "channel_id": "synthetic-channel",
            "requester_service": "synthetic-control",
            "responder_service": "synthetic-worker",
            "protocol_id": "deeptwin-extension-worker-v1",
            "requester_uid": 2002,
            "requester_gid": 2002,
            "pair_gid": 2003,
            "socket_mount_id": "synthetic-ipc",
            "socket_name": "worker",
        },
        "socket_mounts": [
            {
                "mount_id": "synthetic-ipc",
                "volume_name": "synthetic-ipc-volume",
                "container_path": "/run/deeptwin/ipc/synthetic-ipc",
                "read_only": False,
                "purpose": "broker_pair",
            }
        ],
        "named_volume_mounts": [],
        "evidence": {"sbom_ref": refs["sbom"], "provenance_ref": refs["provenance"], "license_ref": refs["license"]},
    }
    manifest = {
        "schema_version": "extension-manifest-v2",
        "extension_id": "synthetic-tool",
        "extension_version": "1.0.0",
        "extension_kind": "tool",
        "port_contract_version": "tool-port-v1",
        "artifact": {
            "artifact_form": "oci_extension_service",
            "service_descriptor_ref": ref("service_descriptor", descriptor),
        },
        "source": {
            "kind": "third_party",
            "locator": "https://example.test/synthetic",
            "provenance_ref": refs["provenance"],
        },
        "license": {"expression": "Synthetic", "text_ref": refs["license"]},
        "compatibility": {
            "framework_min": "1.0.0",
            "framework_max": "1.0.0",
            "extension_api_min": "1.0.0",
            "extension_api_max": "1.0.0",
            "schema_versions": ["domain-v1"],
        },
        "refinements": {
            "config": {"type": "object", "properties": {}, "additionalProperties": False},
            "operations": [],
        },
        "requirements": {**requirements, "grant_ids": [], "filesystem_needs": ["owned_scratch"]},
        "migration_policy": "none",
        "uninstall_policy": "retain_records",
    }
    return {
        "command_id": str(uuid4()),
        "manifest": manifest,
        "service_descriptor": descriptor,
        "documents": [{"document_kind": kind, "content": content} for kind, content in sorted(leaves.items())],
    }
