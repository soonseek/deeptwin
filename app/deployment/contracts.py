"""Closed inert deployment source documents and fixed release profile."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.domain.refs import DomainContractError, canonical_json, uuid_string
from app.operations.setup import OriginProfile, SetupContractError

BASE_COMPOSE_SHA256 = "6a18faa38379724a18466f39b42f66c4405fe11eb790b8e9c21addd39cbd152e"
BASE_SERVICE_IDS_SHA256 = (
    "4330b2080d5579847909fb086ebde6144b1fc54fdee6251a97383acd1e5565f4"
)
TOPOLOGY_ROOT = Path("/run/deeptwin/extension-topology")
EXCHANGE_ROOT = Path("/run/deeptwin/deployment-exchange")
OUTBOX_ROOT = Path("/run/deeptwin/deployment-outbox")
IPC_ROOT = Path("/run/deeptwin/ipc")
RELEASE_ROOT = Path("/opt/deeptwin")
INPUT_ROOT = Path("/run/deeptwin/prepare-init-input")
BUILTIN_ROOTS = (Path("/var/lib/deeptwin"),) + tuple(
    IPC_ROOT / name
    for name in (
        "cp-provider",
        "cp-fetch",
        "cp-codex",
        "cp-browser",
        "cp-document",
        "cp-speech",
        "cp-evaluation",
        "cp-runtime",
        "cp-backup",
    )
)
CONTROL = {"service_identity": "control", "uid": 20102, "gid": 20102}
BUDGET = {
    "memory_bytes": 1073741824,
    "cpu_millicores": 1000,
    "pids_limit": 128,
    "tmpfs_bytes": 134217728,
}
RECIPE = {
    "schema_version": "deployment-prepare-recipe-v1",
    "recipe_id": "ordinary-tool-slots-v1",
    "base_compose": {
        "path": "deploy/compose.yaml",
        "sha256": BASE_COMPOSE_SHA256,
        "size_bytes": 25731,
    },
    "base_service_ids": {
        "path": "deploy/security/service-ids.json",
        "sha256": BASE_SERVICE_IDS_SHA256,
        "size_bytes": 9544,
    },
    "renderer_id": "deeptwin-prepare-expand-v1",
    "initializer_id": "deeptwin-prepare-source-init-v1",
    "slot_capacity_max": 16,
    "slot_budget": BUDGET,
}


class DeploymentSourceError(ValueError):
    code = "deployment_source_invalid"

    def __init__(self):
        super().__init__(self.code)


class DeploymentSourceUnavailable(DeploymentSourceError):
    code = "deployment_source_unavailable"


class DeploymentSourceBusy(DeploymentSourceError):
    code = "deployment_source_busy"


class PublicationUnavailable(DeploymentSourceError):
    code = "deployment_publication_unavailable"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def hex_digest(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise DeploymentSourceError()
    return value


def identifier(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value) is None:
        raise DeploymentSourceError()
    return value


def uuid(value):
    try:
        return uuid_string(value)
    except DomainContractError:
        raise DeploymentSourceError() from None


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise DeploymentSourceError()
    return value


def fields(value, names):
    if type(value) is not dict or set(value) != set(names.split()):
        raise DeploymentSourceError()


def encode(value):
    try:
        return canonical_json(value)
    except (DomainContractError, TypeError, ValueError, RecursionError):
        raise DeploymentSourceError() from None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DeploymentSourceError()
        result[key] = value
    return result


def _nonfinite(_value):
    raise DeploymentSourceError()


def parse(data, *, cap, depth, items, canonical=True):
    if type(data) is not bytes or not 1 <= len(data) <= cap:
        raise DeploymentSourceError()
    try:
        value = json.loads(
            data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_nonfinite
        )
        count = 0

        def inspect(item, level):
            nonlocal count
            count += 1
            if level > depth or count > items:
                raise DeploymentSourceError()
            if isinstance(item, dict):
                for key, child in item.items():
                    inspect(key, level + 1)
                    inspect(child, level + 1)
            elif isinstance(item, list):
                for child in item:
                    inspect(child, level + 1)

        inspect(value, 0)
        if canonical and encode(value) != data:
            raise DeploymentSourceError()
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise DeploymentSourceError() from None


def parse_recipe(data):
    value = parse(data, cap=4096, depth=6, items=128)
    if data != encode(RECIPE):
        raise DeploymentSourceError()
    return value


def parse_instance(data):
    value = parse(data, cap=4096, depth=6, items=128)
    fields(
        value,
        "schema_version origin_profile topology_id exchange_id platform slot_capacity",
    )
    if value["schema_version"] != "deployment-prepare-instance-v1":
        raise DeploymentSourceError()
    try:
        OriginProfile.from_dict(value["origin_profile"])
    except SetupContractError:
        raise DeploymentSourceError() from None
    uuid(value["topology_id"])
    uuid(value["exchange_id"])
    if value["topology_id"] == value["exchange_id"] or value["platform"] not in (
        "linux/amd64",
        "linux/arm64",
    ):
        raise DeploymentSourceError()
    integer(value["slot_capacity"], 1, 16)
    return value


def slot(instance_id, number):
    identifier(instance_id)
    integer(number, 1, 16)
    suffix = f"{number:02}"
    return {
        "slot_number": number,
        "service_identity": f"ext-{instance_id}-{suffix}",
        "uid": 22000 + number,
        "gid": 22000 + number,
        "channel_id": f"cp-ext-{instance_id}-{suffix}",
        "pair_gid": 23000 + number,
        "socket_mount": {
            "mount_id": f"xs{suffix}",
            "volume_name": f"dt-{instance_id}-ipc-xs{suffix}",
            "container_path": str(IPC_ROOT / f"xs{suffix}"),
            "read_only": False,
            "purpose": "broker_pair",
        },
        "socket_name": "worker.sock",
        "protocol_id": "deeptwin-extension-worker-v1",
        "resource_budget": dict(BUDGET),
    }


def topology(profile, topology_id, platform, capacity, recipe_sha256):
    return {
        "schema_version": "extension-topology-v1",
        "instance_id": profile.instance_id,
        "origin_profile_digest": profile.digest,
        "topology_id": uuid(topology_id),
        "revision": 1,
        "deployment_recipe_digest": hex_digest(recipe_sha256),
        "static_service_identity_digest": BASE_SERVICE_IDS_SHA256,
        "platform": platform,
        "control": dict(CONTROL),
        "slots": [slot(profile.instance_id, n) for n in range(1, capacity + 1)],
    }


def exchange(profile, exchange_id, recipe_sha256, instance_sha256):
    return {
        "schema_version": "deployment-outgoing-exchange-v1",
        "exchange_id": uuid(exchange_id),
        "revision": 1,
        "instance_id": profile.instance_id,
        "origin_profile_digest": profile.digest,
        "deployment_recipe_digest": hex_digest(recipe_sha256),
        "instance_configuration_digest": hex_digest(instance_sha256),
        "control": dict(CONTROL),
        "reader": {
            "service_identity": "deployment-receipt-job",
            "uid": 20113,
            "gid": 20113,
            "pair_gid": 21201,
        },
        "outgoing": {
            "volume_name": f"dt-{profile.instance_id}-deployment-outbox",
            "container_path": str(OUTBOX_ROOT),
            "owner_uid": 20102,
            "group_gid": 21201,
            "root_mode": "0750",
            "namespace_mode": "0750",
            "final_file_mode": "0440",
            "control_read_only": False,
            "reader_read_only": True,
            "namespaces": ["cancelled", "requests"],
        },
    }


def parse_topology(data, *, profile, recipe_sha256, platform):
    value = parse(data, cap=65536, depth=12, items=2048)
    fields(
        value,
        "schema_version instance_id origin_profile_digest topology_id revision deployment_recipe_digest static_service_identity_digest platform control slots",
    )
    if type(value["slots"]) is not list:
        raise DeploymentSourceError()
    capacity = integer(len(value["slots"]), 1, 16)
    expected = topology(
        profile, value["topology_id"], platform, capacity, recipe_sha256
    )
    if data != encode(expected):
        raise DeploymentSourceError()
    return value


def parse_exchange(data, *, profile, recipe_sha256, instance_sha256):
    value = parse(data, cap=8192, depth=8, items=256)
    fields(
        value,
        "schema_version exchange_id revision instance_id origin_profile_digest deployment_recipe_digest instance_configuration_digest control reader outgoing",
    )
    expected = exchange(profile, value["exchange_id"], recipe_sha256, instance_sha256)
    if data != encode(expected):
        raise DeploymentSourceError()
    return value


@dataclass(frozen=True, slots=True)
class PrepareSourceArtifacts:
    topology_bytes: bytes
    exchange_bytes: bytes
    pins_bytes: bytes
    expanded_compose_bytes: bytes
    expansion_record_bytes: bytes
