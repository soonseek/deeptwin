from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPOSITORY / "deploy" / "compose.yaml"
IDENTITY_PATH = REPOSITORY / "deploy" / "security" / "service-ids.json"
SECCOMP_PATH = REPOSITORY / "deploy" / "security" / "browser-seccomp.json"
LOCKED_SECCOMP_PATH = REPOSITORY / "deploy" / "locks" / "browser-worker-seccomp.json"
SECCOMP_SHA256 = "8878c8683ef98daaaf9f296767581084d87969111e36d18a61bb70a8e3eff22a"

LONG_RUNNING_UIDS = {
    "edge-local": 20101,
    "control": 20102,
    "provider": 20103,
    "fetch": 20104,
    "browser": 20105,
    "document": 20106,
    "speech": 20107,
    "evaluation": 20108,
    "runtime-extension": 20109,
    "codex": 20110,
    "backup": 20111,
    "edge-portable": 20112,
}

PAIR_CONTRACT = {
    "cp-provider": (21101, "control", "provider"),
    "cp-fetch": (21102, "control", "fetch"),
    "cp-codex": (21103, "control", "codex"),
    "cp-browser": (21104, "control", "browser"),
    "cp-document": (21105, "control", "document"),
    "cp-speech": (21106, "control", "speech"),
    "cp-evaluation": (21107, "control", "evaluation"),
    "cp-runtime": (21108, "control", "runtime-extension"),
    "cp-backup": (21109, "control", "backup"),
    "browser-fetch": (21110, "browser", "fetch"),
}

EXPECTED_NETWORK_MEMBERS = {
    "edge-control": {"edge-local", "control", "edge-portable"},
    "provider-egress": {"provider"},
    "fetch-egress": {"fetch"},
    "codex-egress": {"codex"},
}

NETWORKLESS = {
    "browser",
    "document",
    "speech",
    "evaluation",
    "runtime-extension",
    "backup",
    "state-root-init",
    "ipc-root-init",
}

IMAGE_EXPRESSION = re.compile(
    r"^\$\{[A-Z][A-Z0-9_]*:\?T081 exact @sha256 image required\}$"
)
IMAGE_VARIABLES = {
    "edge-local": "EDGE_LOCAL_IMAGE",
    "control": "CONTROL_IMAGE",
    "provider": "PROVIDER_IMAGE",
    "fetch": "FETCH_IMAGE",
    "browser": "BROWSER_IMAGE",
    "document": "DOCUMENT_IMAGE",
    "speech": "SPEECH_IMAGE",
    "evaluation": "EVALUATION_IMAGE",
    "runtime-extension": "RUNTIME_EXTENSION_IMAGE",
    "codex": "CODEX_IMAGE",
    "backup": "BACKUP_IMAGE",
    "edge-portable": "EDGE_PORTABLE_IMAGE",
    "state-root-init": "STATE_ROOT_INIT_IMAGE",
    "ipc-root-init": "IPC_ROOT_INIT_IMAGE",
}
RESOURCE_BOUNDS = {
    "edge-local": (128, "256m", 0.5, 1024),
    "control": (256, "1g", 1.0, 4096),
    "provider": (128, "512m", 1.0, 2048),
    "fetch": (128, "512m", 1.0, 2048),
    "browser": (256, "1g", 1.0, 4096),
    "document": (128, "768m", 1.0, 2048),
    "speech": (128, "2g", 2.0, 2048),
    "evaluation": (128, "1g", 1.0, 2048),
    "runtime-extension": (128, "1g", 1.0, 2048),
    "codex": (256, "2g", 2.0, 4096),
    "backup": (128, "512m", 1.0, 2048),
    "edge-portable": (128, "256m", 0.5, 1024),
    "state-root-init": (32, "64m", 0.25, 256),
    "ipc-root-init": (32, "64m", 0.25, 256),
}
MEMORY_BOUND = re.compile(r"^[1-9][0-9]*(?:[bkmg])$")
TMPFS_SIZE = re.compile(r"^size=([1-9][0-9]*)m$")

EXPECTED_OPEN_GATES = [
    (
        "T025 must implement a control entrypoint that owns /var/lib/deeptwin and "
        "listens on the internal target http://control:8080; current app.server "
        "loopback behavior does not satisfy this."
    ),
    (
        "T025/T081 must validate exactly one edge profile and bind the exact "
        "OriginProfile across edge, control, session, CSRF, and receipts."
    ),
    (
        "Compose may interpolate global portable config/TLS resource variables "
        "before applying the local profile; T081 must split validated profile "
        "descriptors/overrides or qualify a full-resource model before this "
        "single-file skeleton is runnable."
    ),
    (
        "T081 must verify pinned external portable proxy configuration and operator "
        "TLS certificate/key content digests before startup."
    ),
    (
        "T018 must qualify state-root and per-boot IPC-secret initialization, "
        "rotation, crash behavior, Linux ownership, and SO_PEERCRED handshakes."
    ),
    (
        "T018/T081 must qualify each bounded tmpfs path against the final read-only "
        "service image and deny fallback writes to IPC volumes."
    ),
    (
        "T025/T081 must qualify provider credential, session-root, Codex "
        "device-auth ownership, and deployment-receipt secret lifecycles; this "
        "skeleton declares only IPC boot secrets, Codex auth state, portable edge "
        "TLS, and backup public-recipient input."
    ),
    (
        "T070/T081 must implement and qualify backup archive streaming, "
        "public-recipient validation, output atomicity, private restore identity "
        "handling, and restore verification."
    ),
    (
        "T025 must keep browser owner setup as the user entrypoint; Docker/Compose "
        "are external deployment operator mechanisms, not a product launcher or "
        "end-user CLI."
    ),
    (
        "T079/T081/T083 must supply exact final images and complete integrated "
        "security, dual-platform, and fresh-host runtime evidence."
    ),
]

EXPECTED_LIMITATIONS = [
    (
        "This manifest describes an IPC/network isolation skeleton; it is not a "
        "complete self-hosted topology or Linux, Docker Compose, SO_PEERCRED, "
        "Chromium sandbox, or fresh-host runtime evidence."
    ),
    (
        "Every Compose image variable must be supplied as an exact OCI image "
        "reference containing @sha256:; final T081 service image digests remain open."
    ),
    (
        "DeepTwin remains a self-hostable web-based open-source framework whose "
        "bundled official browser UI performs owner setup; Docker/Compose are "
        "external operator mechanisms, never a product launcher or end-user CLI."
    ),
    (
        "The single-file skeleton may interpolate global portable config/TLS "
        "resource variables even for the local profile; T081 must split validated "
        "profile descriptors/overrides or qualify a full-resource model."
    ),
    (
        "State-root initialization, per-boot IPC secret overwrite, edge profile "
        "exclusivity, external portable config/TLS verification, Codex auth "
        "ownership, backup semantics, tmpfs suitability, and final images require "
        "later implementation and runtime qualification."
    ),
]

COMMON_SERVICE_FIELDS = {
    "image",
    "user",
    "read_only",
    "init",
    "privileged",
    "cap_drop",
    "security_opt",
    "tty",
    "stdin_open",
    "pids_limit",
    "mem_limit",
    "cpus",
    "ulimits",
    "restart",
}

SERVICE_SPECIFIC_FIELDS = {
    "edge-local": {"profiles", "networks", "ports", "environment", "tmpfs"},
    "control": {"networks", "group_add", "depends_on", "tmpfs", "volumes"},
    "provider": {"networks", "group_add", "depends_on", "tmpfs", "volumes"},
    "fetch": {"networks", "group_add", "depends_on", "tmpfs", "volumes"},
    "browser": {
        "shm_size",
        "network_mode",
        "group_add",
        "depends_on",
        "tmpfs",
        "volumes",
    },
    "document": {"network_mode", "group_add", "depends_on", "tmpfs", "volumes"},
    "speech": {"network_mode", "group_add", "depends_on", "tmpfs", "volumes"},
    "evaluation": {"network_mode", "group_add", "depends_on", "tmpfs", "volumes"},
    "runtime-extension": {
        "network_mode",
        "group_add",
        "depends_on",
        "tmpfs",
        "volumes",
    },
    "codex": {"networks", "group_add", "depends_on", "tmpfs", "volumes"},
    "backup": {
        "network_mode",
        "group_add",
        "depends_on",
        "tmpfs",
        "secrets",
        "volumes",
    },
    "edge-portable": {
        "profiles",
        "networks",
        "ports",
        "environment",
        "tmpfs",
        "configs",
        "secrets",
    },
    "state-root-init": {"cap_add", "network_mode", "command", "volumes"},
    "ipc-root-init": {"cap_add", "network_mode", "command", "volumes"},
}

TMPFS_TARGETS = {
    service_name: {"/tmp"} for service_name in LONG_RUNNING_UIDS
}
TMPFS_TARGETS["browser"] = {"/tmp", "/run/deeptwin/browser-profile"}
EXPECTED_TMPFS = {
    "edge-local": [
        "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1770,uid=20101,gid=20101"
    ],
    "control": [
        "/tmp:rw,noexec,nosuid,nodev,size=128m,mode=1770,uid=20102,gid=20102"
    ],
    "provider": [
        "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1770,uid=20103,gid=20103"
    ],
    "fetch": [
        "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1770,uid=20104,gid=20104"
    ],
    "browser": [
        "/tmp:rw,noexec,nosuid,nodev,size=128m,mode=1770,uid=20105,gid=20105",
        (
            "/run/deeptwin/browser-profile:rw,noexec,nosuid,nodev,size=256m,"
            "mode=0700,uid=20105,gid=20105"
        ),
    ],
    "document": [
        "/tmp:rw,noexec,nosuid,nodev,size=256m,mode=1770,uid=20106,gid=20106"
    ],
    "speech": [
        "/tmp:rw,noexec,nosuid,nodev,size=256m,mode=1770,uid=20107,gid=20107"
    ],
    "evaluation": [
        "/tmp:rw,noexec,nosuid,nodev,size=128m,mode=1770,uid=20108,gid=20108"
    ],
    "runtime-extension": [
        "/tmp:rw,noexec,nosuid,nodev,size=128m,mode=1770,uid=20109,gid=20109"
    ],
    "codex": [
        "/tmp:rw,noexec,nosuid,nodev,size=512m,mode=1770,uid=20110,gid=20110"
    ],
    "backup": [
        "/tmp:rw,noexec,nosuid,nodev,size=256m,mode=1770,uid=20111,gid=20111"
    ],
    "edge-portable": [
        "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1770,uid=20112,gid=20112"
    ],
}


def _load_contract() -> tuple[dict[str, object], dict[str, object]]:
    # JSON is deliberately used as the YAML 1.2 subset so these checks have no PyYAML or
    # Docker dependency. Compose implementations accept this syntax in a .yaml document.
    return json.loads(COMPOSE_PATH.read_text()), json.loads(IDENTITY_PATH.read_text())


def _mounts_by_target(service: dict[str, object]) -> dict[str, dict[str, object]]:
    mounts = service.get("volumes", [])
    assert isinstance(mounts, list)
    return {mount["target"]: mount for mount in mounts}


def _expected_groups(service_name: str, pairs: dict[str, object]) -> set[str]:
    return {
        str(pair["pair_gid"])
        for pair in pairs.values()
        if service_name in {pair["requester"], pair["responder"]}
    }


def _parse_init_channels(command: object) -> dict[str, dict[str, str]]:
    assert isinstance(command, list)
    prefixes = (
        "--channel=",
        "--root=",
        "--root-owner=",
        "--root-mode=",
        "--endpoint=",
        "--endpoint-owner=",
        "--endpoint-mode=",
        "--generation-lock=",
        "--generation-lock-owner=",
        "--generation-lock-mode=",
        "--socket=",
        "--socket-owner=",
        "--socket-mode=",
        "--boot-secret=",
        "--boot-secret-owner=",
        "--boot-secret-mode=",
        "--boot-secret-bytes=",
        "--boot-secret-policy=",
    )
    assert len(command) == len(PAIR_CONTRACT) * len(prefixes)
    channels: dict[str, dict[str, str]] = {}
    for offset in range(0, len(command), len(prefixes)):
        chunk = command[offset : offset + len(prefixes)]
        assert all(
            isinstance(value, str) and value.startswith(prefix)
            for value, prefix in zip(chunk, prefixes, strict=True)
        )
        values = [value.split("=", 1)[1] for value in chunk]
        channel = values[0]
        assert channel not in channels
        channels[channel] = dict(zip(
            (
                "root",
                "root_owner",
                "root_mode",
                "endpoint",
                "endpoint_owner",
                "endpoint_mode",
                "generation_lock",
                "generation_lock_owner",
                "generation_lock_mode",
                "socket",
                "socket_owner",
                "socket_mode",
                "boot_secret",
                "boot_secret_owner",
                "boot_secret_mode",
                "boot_secret_bytes",
                "boot_secret_policy",
            ),
            values[1:],
            strict=True,
        ))
    return channels


def _assert_tmpfs(service_name: str, uid: int, entries: object) -> None:
    assert isinstance(entries, list) and entries
    assert entries == EXPECTED_TMPFS[service_name]
    targets: set[str] = set()
    for entry in entries:
        assert isinstance(entry, str)
        target, options_text = entry.split(":", 1)
        assert target.startswith("/") and target not in targets
        targets.add(target)
        options = options_text.split(",")
        assert len(options) == len(set(options))
        fixed_options = {
            "rw",
            "noexec",
            "nosuid",
            "nodev",
            f"uid={uid}",
            f"gid={uid}",
        }
        assert fixed_options.issubset(options)
        sizes = [option for option in options if option.startswith("size=")]
        assert len(sizes) == 1
        match = TMPFS_SIZE.fullmatch(sizes[0])
        assert match and 0 < int(match.group(1)) <= 512
        modes = [option for option in options if option.startswith("mode=")]
        assert len(modes) == 1 and modes[0] in {"mode=0700", "mode=1770"}
        assert set(options) == fixed_options | {sizes[0], modes[0]}
    assert targets == TMPFS_TARGETS[service_name]


def _service_consumers(
    services: dict[str, object], field: str, source: str
) -> set[str]:
    return {
        service_name
        for service_name, service in services.items()
        if any(item["source"] == source for item in service.get(field, []))
    }


def _assert_static_contract(compose: dict[str, object], identities: dict[str, object]) -> None:
    assert set(compose) == {
        "name",
        "x-deeptwin-contract",
        "services",
        "networks",
        "volumes",
        "configs",
        "secrets",
    }
    assert compose["name"] == "deeptwin-ipc-network-isolation-skeleton"
    metadata = compose["x-deeptwin-contract"]
    assert set(metadata) == {
        "status",
        "scope",
        "runtime_evidence",
        "image_requirement",
        "required_control_listener_target",
        "profile_selection",
        "open_gates",
    }
    assert metadata["status"] == "candidate_not_runtime_qualified"
    assert metadata["scope"] == "ipc_network_isolation_skeleton"
    assert metadata["runtime_evidence"] is False
    assert metadata["image_requirement"] == (
        "Each image variable must resolve to an exact OCI reference containing @sha256:."
    )
    assert metadata["required_control_listener_target"] == "http://control:8080"
    assert metadata["profile_selection"] == {
        "required_exactly_one": ["local", "portable"],
        "compose_limitation": (
            "Compose profiles do not prevent selecting both; deployment validation must "
            "reject zero or multiple edge profiles."
        ),
    }
    open_gates = metadata["open_gates"]
    assert open_gates == EXPECTED_OPEN_GATES
    gates_text = "\n".join(open_gates)
    for required in (
        "current app.server loopback behavior does not satisfy this",
        "exactly one edge profile",
        "interpolate global portable config/TLS resource variables",
        "external portable proxy configuration",
        "per-boot IPC-secret initialization",
        "bounded tmpfs",
        "Codex device-auth ownership",
        "backup archive streaming",
        "browser owner setup as the user entrypoint",
        "fresh-host runtime evidence",
    ):
        assert required in gates_text

    assert set(identities) == {
        "schema_version",
        "status",
        "scope",
        "services",
        "pairs",
        "limitations",
    }
    assert identities["schema_version"] == "deeptwin-static-service-identity-v1"
    assert identities["status"] == "candidate_not_runtime_qualified"
    assert identities["scope"] == "ipc_network_isolation_skeleton"
    assert identities["limitations"] == EXPECTED_LIMITATIONS
    limitations_text = "\n".join(identities["limitations"])
    assert "not a complete self-hosted topology" in limitations_text
    assert "edge profile exclusivity" in limitations_text
    assert "interpolate global portable config/TLS resource variables" in limitations_text
    assert "bundled official browser UI performs owner setup" in limitations_text
    assert "never a product launcher or end-user CLI" in limitations_text

    services = compose["services"]
    identity_services = identities["services"]
    one_shot = {"ipc-root-init", "state-root-init"}
    assert set(services) == set(LONG_RUNNING_UIDS) | one_shot
    assert set(identity_services) == set(services)

    images: set[str] = set()
    declared_volumes = set(compose["volumes"])
    for service_name, service in services.items():
        assert set(service) == COMMON_SERVICE_FIELDS | SERVICE_SPECIFIC_FIELDS[service_name]
        image = service["image"]
        assert isinstance(image, str) and IMAGE_EXPRESSION.fullmatch(image)
        assert image == (
            f"${{{IMAGE_VARIABLES[service_name]}:?T081 exact @sha256 image required}}"
        )
        assert image not in images
        images.add(image)
        assert "build" not in service
        assert service["read_only"] is True
        assert service["init"] is True
        assert service["privileged"] is False
        assert service["cap_drop"] == ["ALL"]
        if service_name == "browser":
            assert service["security_opt"] == [
                "no-new-privileges:true",
                "seccomp=./security/browser-seccomp.json",
            ]
        else:
            assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["tty"] is False
        assert service["stdin_open"] is False
        assert isinstance(service["pids_limit"], int) and 0 < service["pids_limit"] <= 512
        assert isinstance(service["mem_limit"], str)
        assert MEMORY_BOUND.fullmatch(service["mem_limit"])
        assert isinstance(service["cpus"], (int, float)) and 0 < service["cpus"] <= 4
        assert set(service["ulimits"]) == {"nofile"}
        nofile = service["ulimits"]["nofile"]
        assert set(nofile) == {"soft", "hard"}
        assert 0 < nofile["soft"] == nofile["hard"] <= 65536
        expected_pids, expected_memory, expected_cpus, expected_nofile = RESOURCE_BOUNDS[
            service_name
        ]
        assert service["pids_limit"] == expected_pids
        assert service["mem_limit"] == expected_memory
        assert service["cpus"] == expected_cpus
        assert nofile == {"soft": expected_nofile, "hard": expected_nofile}
        assert service.get("network_mode") != "host"
        assert all(service.get(namespace) != "host" for namespace in ("pid", "ipc", "uts"))
        assert "expose" not in service

        mounts = service.get("volumes", [])
        assert len({mount["target"] for mount in mounts}) == len(mounts)
        for mount in mounts:
            assert set(mount).issubset({"type", "source", "target", "read_only", "volume"})
            assert mount["type"] == "volume"
            assert mount["source"] in declared_volumes
            assert isinstance(mount["target"], str) and mount["target"].startswith("/")
            assert isinstance(mount["read_only"], bool)
            if "volume" in mount:
                assert mount["volume"] == {"nocopy": True}

    for service_name, uid in LONG_RUNNING_UIDS.items():
        service = services[service_name]
        identity = identity_services[service_name]
        assert identity == {"uid": uid, "gid": uid, "lifecycle": "long_running"}
        assert service["user"] == f"{uid}:{uid}"
        assert service["restart"] == "unless-stopped"
        assert service.get("cap_add", []) == []
        _assert_tmpfs(service_name, uid, service.get("tmpfs"))

    for init_name in one_shot:
        expected_identity = {
            "uid": 0,
            "gid": 0,
            "lifecycle": "one_shot",
            "capabilities": ["CHOWN"],
        }
        if init_name == "state-root-init":
            expected_identity["persistent_roots"] = [
                {
                    "volume": "deeptwin-state",
                    "target": "/var/lib/deeptwin",
                    "owner": "20102:20102",
                    "mode": "0700",
                },
                {
                    "volume": "codex-auth",
                    "target": "/var/lib/deeptwin/codex-auth",
                    "owner": "20110:20110",
                    "mode": "0700",
                },
                {
                    "volume": "backup-output",
                    "target": "/var/lib/deeptwin/backup-output",
                    "owner": "20111:20111",
                    "mode": "0700",
                },
            ]
        else:
            expected_identity["capabilities"] = ["CHOWN", "FOWNER", "FSETID"]
        assert identity_services[init_name] == expected_identity
        initializer = services[init_name]
        assert initializer["user"] == "0:0"
        assert initializer["restart"] == "no"
        assert initializer["network_mode"] == "none"
        expected_capabilities = (
            ["CHOWN"] if init_name == "state-root-init"
            else ["CHOWN", "FOWNER", "FSETID"]
        )
        assert initializer["cap_add"] == expected_capabilities
        assert initializer["security_opt"] == ["no-new-privileges:true"]

    networks = compose["networks"]
    assert networks == {
        "edge-control": {"internal": True},
        "provider-egress": {},
        "fetch-egress": {},
        "codex-egress": {},
    }
    for network_name, expected_members in EXPECTED_NETWORK_MEMBERS.items():
        actual_members = {
            service_name
            for service_name, service in services.items()
            if network_name in service.get("networks", [])
        }
        assert actual_members == expected_members
    for service_name in NETWORKLESS:
        assert services[service_name]["network_mode"] == "none"
        assert "networks" not in services[service_name]

    port_services = {
        service_name for service_name, service in services.items() if service.get("ports")
    }
    assert port_services == {"edge-local", "edge-portable"}
    assert services["edge-local"]["ports"] == [
        "127.0.0.1:${DEEPTWIN_LOCAL_PORT:-8080}:8080"
    ]
    assert services["edge-portable"]["ports"] == [
        "${DEEPTWIN_PORTABLE_BIND:-0.0.0.0}:${DEEPTWIN_PORTABLE_PORT:-8443}:8443"
    ]
    assert services["edge-local"].get("profiles") == ["local"]
    assert services["edge-portable"].get("profiles") == ["portable"]
    assert all(
        "profiles" not in service
        for service_name, service in services.items()
        if service_name not in port_services
    )
    for edge_name in port_services:
        edge = services[edge_name]
        assert "volumes" not in edge
        assert "group_add" not in edge
        assert edge["environment"]["DEEPTWIN_CONTROL_UPSTREAM"] == "http://control:8080"
    assert services["edge-local"]["environment"] == {
        "DEEPTWIN_CONTROL_UPSTREAM": "http://control:8080"
    }

    portable = services["edge-portable"]
    assert portable["configs"] == [{
        "source": "portable-edge-config",
        "target": "/etc/deeptwin/edge/edge.conf",
        "uid": "20112",
        "gid": "20112",
        "mode": 0o440,
    }]
    assert portable["secrets"] == [
        {
            "source": "portable-edge-tls-certificate",
            "target": "/run/secrets/deeptwin-edge-tls.crt",
            "uid": "20112",
            "gid": "20112",
            "mode": 0o440,
        },
        {
            "source": "portable-edge-tls-key",
            "target": "/run/secrets/deeptwin-edge-tls.key",
            "uid": "20112",
            "gid": "20112",
            "mode": 0o400,
        },
    ]
    assert set(portable["environment"]) == {
        "DEEPTWIN_CONTROL_UPSTREAM",
        "DEEPTWIN_PORTABLE_EDGE_CONFIG_SHA256",
        "DEEPTWIN_PORTABLE_TLS_CERT_SHA256",
        "DEEPTWIN_PORTABLE_TLS_KEY_SHA256",
    }
    assert portable["environment"] == {
        "DEEPTWIN_CONTROL_UPSTREAM": "http://control:8080",
        "DEEPTWIN_PORTABLE_EDGE_CONFIG_SHA256": (
            "${PORTABLE_EDGE_CONFIG_SHA256:?T081 pinned external edge config sha256 required}"
        ),
        "DEEPTWIN_PORTABLE_TLS_CERT_SHA256": (
            "${PORTABLE_EDGE_TLS_CERT_SHA256:?T081 operator TLS certificate sha256 required}"
        ),
        "DEEPTWIN_PORTABLE_TLS_KEY_SHA256": (
            "${PORTABLE_EDGE_TLS_KEY_SHA256:?T081 operator TLS key sha256 required}"
        ),
    }
    assert compose["configs"] == {
        "portable-edge-config": {
            "external": True,
            "name": (
                "${PORTABLE_EDGE_CONFIG_RESOURCE:?T081 pinned external edge config "
                "resource required}"
            ),
        }
    }
    assert compose["secrets"] == {
        "portable-edge-tls-certificate": {
            "external": True,
            "name": (
                "${PORTABLE_EDGE_TLS_CERT_RESOURCE:?T081 operator TLS certificate "
                "resource required}"
            ),
        },
        "portable-edge-tls-key": {
            "external": True,
            "name": (
                "${PORTABLE_EDGE_TLS_KEY_RESOURCE:?T081 operator TLS key resource required}"
            ),
        },
        "backup-public-key": {
            "external": True,
            "name": "${BACKUP_PUBLIC_KEY_RESOURCE:?T070 backup public key resource required}",
        },
    }
    assert _service_consumers(services, "configs", "portable-edge-config") == {
        "edge-portable"
    }
    assert _service_consumers(
        services, "secrets", "portable-edge-tls-certificate"
    ) == {"edge-portable"}
    assert _service_consumers(services, "secrets", "portable-edge-tls-key") == {
        "edge-portable"
    }
    assert _service_consumers(services, "secrets", "backup-public-key") == {"backup"}
    assert services["backup"]["secrets"] == [{
        "source": "backup-public-key",
        "target": "/run/secrets/deeptwin-backup-recipient.txt",
        "uid": "20111",
        "gid": "20111",
        "mode": 0o440,
    }]

    pairs = identities["pairs"]
    assert set(pairs) == set(PAIR_CONTRACT)
    ipc_volumes = {f"ipc-{pair_name}" for pair_name in PAIR_CONTRACT}
    assert declared_volumes == ipc_volumes | {
        "deeptwin-state",
        "codex-auth",
        "backup-output",
    }
    assert all(volume == {} for volume in compose["volumes"].values())
    for pair_name, (pair_gid, requester_name, responder_name) in PAIR_CONTRACT.items():
        pair = pairs[pair_name]
        responder_uid = LONG_RUNNING_UIDS[responder_name]
        root = f"/run/deeptwin/ipc/{pair_name}"
        assert pair == {
            "pair_gid": pair_gid,
            "requester": requester_name,
            "responder": responder_name,
            "root": root,
            "socket": "worker.sock",
            "root_uid": 0,
            "root_gid": pair_gid,
            "root_mode": "0710",
            "endpoint": "endpoint",
            "endpoint_uid": responder_uid,
            "endpoint_gid": pair_gid,
            "endpoint_mode": "02710",
            "generation_lock": "generation.lock",
            "generation_lock_uid": 0,
            "generation_lock_gid": pair_gid,
            "generation_lock_mode": "0640",
            "socket_uid": responder_uid,
            "socket_gid": pair_gid,
            "socket_mode": "0660",
            "boot_secret": "boot-secret",
            "boot_secret_uid": 0,
            "boot_secret_gid": pair_gid,
            "boot_secret_mode": "0640",
            "boot_secret_bytes": 32,
            "boot_secret_policy": "generate_or_overwrite_per_boot",
        }
        assert pair_gid not in {
            LONG_RUNNING_UIDS[requester_name],
            LONG_RUNNING_UIDS[responder_name],
        }
        volume_name = f"ipc-{pair_name}"
        requester_mount = _mounts_by_target(services[requester_name])[root]
        responder_mount = _mounts_by_target(services[responder_name])[root]
        assert requester_mount == {
            "type": "volume",
            "source": volume_name,
            "target": root,
            "read_only": True,
        }
        assert responder_mount == {
            "type": "volume",
            "source": volume_name,
            "target": root,
            "read_only": False,
        }
        assert _service_consumers(services, "volumes", volume_name) == {
            requester_name,
            responder_name,
            "ipc-root-init",
        }

    for service_name in LONG_RUNNING_UIDS:
        groups = set(services[service_name].get("group_add", []))
        assert groups == _expected_groups(service_name, pairs)
        if groups and service_name not in {"control", "codex", "backup"}:
            assert services[service_name]["depends_on"] == {
                "ipc-root-init": {"condition": "service_completed_successfully"}
            }
    persistent_services = {"control", "codex", "backup"}
    for service_name in persistent_services:
        assert services[service_name]["depends_on"] == {
            "ipc-root-init": {"condition": "service_completed_successfully"},
            "state-root-init": {"condition": "service_completed_successfully"},
        }

    initializer = services["ipc-root-init"]
    init_mounts = _mounts_by_target(initializer)
    assert set(init_mounts) == {pair["root"] for pair in pairs.values()}
    for pair_name, pair in pairs.items():
        assert init_mounts[pair["root"]] == {
            "type": "volume",
            "source": f"ipc-{pair_name}",
            "target": pair["root"],
            "read_only": False,
        }

    init_channels = _parse_init_channels(initializer["command"])
    assert set(init_channels) == set(pairs)
    for pair_name, pair in pairs.items():
        assert init_channels[pair_name] == {
            "root": pair["root"],
            "root_owner": f"{pair['root_uid']}:{pair['root_gid']}",
            "root_mode": pair["root_mode"],
            "endpoint": pair["endpoint"],
            "endpoint_owner": f"{pair['endpoint_uid']}:{pair['endpoint_gid']}",
            "endpoint_mode": pair["endpoint_mode"],
            "generation_lock": pair["generation_lock"],
            "generation_lock_owner": (
                f"{pair['generation_lock_uid']}:{pair['generation_lock_gid']}"
            ),
            "generation_lock_mode": pair["generation_lock_mode"],
            "socket": pair["socket"],
            "socket_owner": f"{pair['socket_uid']}:{pair['socket_gid']}",
            "socket_mode": pair["socket_mode"],
            "boot_secret": pair["boot_secret"],
            "boot_secret_owner": f"0:{pair['pair_gid']}",
            "boot_secret_mode": pair["boot_secret_mode"],
            "boot_secret_bytes": "32",
            "boot_secret_policy": "generate-or-overwrite-per-boot",
        }

    state_mount = {
        "type": "volume",
        "source": "deeptwin-state",
        "target": "/var/lib/deeptwin",
        "read_only": False,
        "volume": {"nocopy": True},
    }
    assert _mounts_by_target(services["control"])["/var/lib/deeptwin"] == state_mount
    assert _mounts_by_target(services["state-root-init"])["/var/lib/deeptwin"] == state_mount
    assert _service_consumers(services, "volumes", "deeptwin-state") == {
        "control",
        "state-root-init",
    }
    state_initializer = services["state-root-init"]
    assert set(_mounts_by_target(state_initializer)) == {
        "/var/lib/deeptwin",
        "/var/lib/deeptwin/codex-auth",
        "/var/lib/deeptwin/backup-output",
    }
    assert state_initializer["command"] == [
        "--root=/var/lib/deeptwin",
        "--owner=20102:20102",
        "--root-mode=0700",
        "--existing-policy=verify-or-initialize-empty",
        "--root=/var/lib/deeptwin/codex-auth",
        "--owner=20110:20110",
        "--root-mode=0700",
        "--existing-policy=verify-or-initialize-empty",
        "--root=/var/lib/deeptwin/backup-output",
        "--owner=20111:20111",
        "--root-mode=0700",
        "--existing-policy=verify-or-initialize-empty",
    ]

    assert _service_consumers(services, "volumes", "codex-auth") == {
        "codex",
        "state-root-init",
    }
    assert _mounts_by_target(services["codex"])["/var/lib/deeptwin/codex-auth"] == {
        "type": "volume",
        "source": "codex-auth",
        "target": "/var/lib/deeptwin/codex-auth",
        "read_only": False,
        "volume": {"nocopy": True},
    }
    assert _mounts_by_target(state_initializer)["/var/lib/deeptwin/codex-auth"] == {
        "type": "volume",
        "source": "codex-auth",
        "target": "/var/lib/deeptwin/codex-auth",
        "read_only": False,
        "volume": {"nocopy": True},
    }
    assert _service_consumers(services, "volumes", "backup-output") == {
        "backup",
        "state-root-init",
    }
    assert _mounts_by_target(services["backup"])[
        "/var/lib/deeptwin/backup-output"
    ] == {
        "type": "volume",
        "source": "backup-output",
        "target": "/var/lib/deeptwin/backup-output",
        "read_only": False,
        "volume": {"nocopy": True},
    }
    assert _mounts_by_target(state_initializer)[
        "/var/lib/deeptwin/backup-output"
    ] == {
        "type": "volume",
        "source": "backup-output",
        "target": "/var/lib/deeptwin/backup-output",
        "read_only": False,
        "volume": {"nocopy": True},
    }
    assert "deeptwin-state" not in {
        mount["source"] for mount in services["backup"]["volumes"]
    }

    browser_security = services["browser"]["security_opt"]
    assert browser_security == [
        "no-new-privileges:true",
        "seccomp=./security/browser-seccomp.json",
    ]
    seccomp_reference = browser_security[1].split("=", 1)[1]
    assert (COMPOSE_PATH.parent / seccomp_reference).resolve() == SECCOMP_PATH.resolve()
    assert services["browser"]["shm_size"] == "256m"

    serialized = json.dumps(compose).lower()
    for forbidden in (
        "docker.sock",
        "/var/run/docker",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "sys_admin",
        "seccomp=unconfined",
    ):
        assert forbidden not in serialized


def test_static_topology_contract() -> None:
    compose, identities = _load_contract()
    _assert_static_contract(compose, identities)


def test_browser_seccomp_is_the_exact_locked_policy() -> None:
    deployed = SECCOMP_PATH.read_bytes()
    locked = LOCKED_SECCOMP_PATH.read_bytes()
    assert deployed == locked
    assert hashlib.sha256(deployed).hexdigest() == SECCOMP_SHA256


@pytest.mark.parametrize(
    "threat",
    [
        "tagged_image",
        "privileged_worker",
        "sys_admin",
        "networked_browser",
        "shared_provider_egress",
        "published_control_port",
        "edge_data_mount",
        "docker_socket_bind",
        "browser_no_sandbox",
        "unconfined_seccomp",
        "root_long_running_service",
        "broadened_group",
        "requester_write_access",
        "init_extra_capability",
        "host_pid_namespace",
        "unprofiled_local_edge",
        "portable_missing_tls",
        "portable_tls_shared_with_local",
        "state_shared_with_backup",
        "state_read_only",
        "codex_auth_shared",
        "backup_output_shared",
        "tmpfs_without_noexec",
        "unbounded_tmpfs",
        "stale_boot_secret",
        "broad_boot_secret_mode",
        "false_listener_claim",
        "false_linux_runtime_flag",
        "false_linux_runtime_open_gate",
        "manifest_contradictory_qualification",
        "browser_volumes_from_control_rw",
        "edge_volumes_from_control_ro",
        "control_use_api_socket",
        "host_device",
        "browser_userns_host",
        "local_public_bind",
        "device_cgroup_rule",
        "cgroup_parent",
        "host_cgroup_namespace",
        "extra_hosts",
        "host_ipc_namespace",
        "host_volume_driver",
        "external_provider_egress",
        "shared_named_fetch_egress",
        "swapped_service_images",
        "weakened_restart_policy",
        "huge_memory_limit",
    ],
)
def test_adversarial_topology_mutations_fail_closed(threat: str) -> None:
    original_compose, original_identities = _load_contract()
    compose = copy.deepcopy(original_compose)
    identities = copy.deepcopy(original_identities)
    services = compose["services"]

    if threat == "tagged_image":
        services["provider"]["image"] = "deeptwin/provider:latest"
    elif threat == "privileged_worker":
        services["document"]["privileged"] = True
    elif threat == "sys_admin":
        services["browser"]["cap_add"] = ["SYS_ADMIN"]
    elif threat == "networked_browser":
        services["browser"].pop("network_mode")
        services["browser"]["networks"] = ["edge-control"]
    elif threat == "shared_provider_egress":
        services["control"]["networks"].append("provider-egress")
    elif threat == "published_control_port":
        services["control"]["ports"] = ["8081:8080"]
    elif threat == "edge_data_mount":
        services["edge-local"]["volumes"] = [{
            "type": "volume",
            "source": "deeptwin-state",
            "target": "/data",
            "read_only": True,
        }]
    elif threat == "docker_socket_bind":
        services["control"]["volumes"].append({
            "type": "bind",
            "source": "/var/run/docker.sock",
            "target": "/var/run/docker.sock",
            "read_only": False,
        })
    elif threat == "browser_no_sandbox":
        services["browser"]["command"] = ["chromium", "--no-sandbox"]
    elif threat == "unconfined_seccomp":
        services["browser"]["security_opt"][1] = "seccomp=unconfined"
    elif threat == "root_long_running_service":
        services["backup"]["user"] = "0:0"
    elif threat == "broadened_group":
        services["provider"]["group_add"].append("21102")
    elif threat == "requester_write_access":
        services["control"]["volumes"][1]["read_only"] = False
    elif threat == "init_extra_capability":
        services["ipc-root-init"]["cap_add"].append("DAC_OVERRIDE")
    elif threat == "host_pid_namespace":
        services["speech"]["pid"] = "host"
    elif threat == "unprofiled_local_edge":
        services["edge-local"].pop("profiles")
    elif threat == "portable_missing_tls":
        services["edge-portable"]["secrets"].pop()
    elif threat == "portable_tls_shared_with_local":
        services["edge-local"]["secrets"] = [
            services["edge-portable"]["secrets"][0]
        ]
    elif threat == "state_shared_with_backup":
        services["backup"]["volumes"].append({
            "type": "volume",
            "source": "deeptwin-state",
            "target": "/work",
            "read_only": True,
        })
    elif threat == "state_read_only":
        services["control"]["volumes"][0]["read_only"] = True
    elif threat == "codex_auth_shared":
        services["control"]["volumes"].append(copy.deepcopy(
            services["codex"]["volumes"][1]
        ))
    elif threat == "backup_output_shared":
        services["control"]["volumes"].append(copy.deepcopy(
            services["backup"]["volumes"][1]
        ))
    elif threat == "tmpfs_without_noexec":
        services["document"]["tmpfs"][0] = services["document"]["tmpfs"][0].replace(
            "noexec,", ""
        )
    elif threat == "unbounded_tmpfs":
        services["speech"]["tmpfs"][0] = services["speech"]["tmpfs"][0].replace(
            "size=256m,", ""
        )
    elif threat == "stale_boot_secret":
        services["ipc-root-init"]["command"][-1] = (
            "--boot-secret-policy=preserve-existing"
        )
    elif threat == "broad_boot_secret_mode":
        services["ipc-root-init"]["command"][-3] = "--boot-secret-mode=0660"
    elif threat == "false_listener_claim":
        compose["x-deeptwin-contract"]["open_gates"][0] = (
            "The current control server already supports http://control:8080."
        )
    elif threat == "false_linux_runtime_flag":
        compose["x-deeptwin-contract"]["linux_runtime_qualified"] = True
    elif threat == "false_linux_runtime_open_gate":
        compose["x-deeptwin-contract"]["open_gates"].append(
            "The Linux runtime is qualified."
        )
    elif threat == "manifest_contradictory_qualification":
        identities["limitations"].append(
            "The Linux runtime is qualified on this macOS audit host."
        )
    elif threat == "browser_volumes_from_control_rw":
        services["browser"]["volumes_from"] = ["control:rw"]
    elif threat == "edge_volumes_from_control_ro":
        services["edge-local"]["volumes_from"] = ["control:ro"]
    elif threat == "control_use_api_socket":
        services["control"]["use_api_socket"] = True
    elif threat == "host_device":
        services["document"]["devices"] = ["/dev/disk0:/dev/disk0"]
    elif threat == "browser_userns_host":
        services["browser"]["userns_mode"] = "host"
    elif threat == "local_public_bind":
        services["edge-local"]["ports"] = [
            "0.0.0.0:${DEEPTWIN_LOCAL_PORT:-8080}:8080"
        ]
    elif threat == "device_cgroup_rule":
        services["speech"]["device_cgroup_rules"] = ["c 10:232 rwm"]
    elif threat == "cgroup_parent":
        services["codex"]["cgroup_parent"] = "/host.slice"
    elif threat == "host_cgroup_namespace":
        services["control"]["cgroup"] = "host"
    elif threat == "extra_hosts":
        services["provider"]["extra_hosts"] = ["host.internal:host-gateway"]
    elif threat == "host_ipc_namespace":
        services["backup"]["ipc"] = "host"
    elif threat == "host_volume_driver":
        compose["volumes"]["deeptwin-state"] = {
            "driver_opts": {"type": "none", "o": "bind", "device": "/"}
        }
    elif threat == "external_provider_egress":
        compose["networks"]["provider-egress"] = {"external": True}
    elif threat == "shared_named_fetch_egress":
        compose["networks"]["fetch-egress"] = {"name": "shared-fetch-egress"}
    elif threat == "swapped_service_images":
        services["control"]["image"], services["backup"]["image"] = (
            services["backup"]["image"],
            services["control"]["image"],
        )
    elif threat == "weakened_restart_policy":
        services["provider"]["restart"] = "on-failure"
    elif threat == "huge_memory_limit":
        services["evaluation"]["mem_limit"] = "999999999g"
    else:  # pragma: no cover - parametrization is intentionally exhaustive.
        raise AssertionError(threat)

    with pytest.raises(AssertionError):
        _assert_static_contract(compose, identities)
