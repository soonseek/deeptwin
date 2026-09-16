"""Pure first-stage reconstruction and wire parsing. No parsed value is authority."""

from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import MappingProxyType

from jsonschema import Draft202012Validator, FormatChecker

from ..domain.refs import canonical_json, parse_canonical, uuid_string
from ..domain.wire import WireLimits, parse_json_object
from ..extensions.candidate_contracts import CandidateBundle, parse_bundle
from ..extensions.port_contracts import PORT_CONTRACTS
from . import contracts as sources
from .prepare_schema_exports import (
    cancel_input_schema,
    prepare_input_schema,
    request_schema,
    stage_schema,
)
from .publication import validate_projection

MAX_MS = 253402300799999
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
ERRORS = MappingProxyType(
    {
        "invalid_input": (400, "Invalid deployment request."),
        "unauthenticated": (401, "Authentication is required."),
        "access_denied": (403, "This action is not allowed."),
        "not_found": (404, "Deployment request, candidate or slot was not found."),
        "conflict": (409, "Deployment request state conflicts with this command."),
        "too_large": (413, "Deployment request is too large."),
        "capacity": (429, "Deployment preparation capacity is exhausted."),
        "dependency_unavailable": (503, "Deployment preparation is unavailable."),
        "unavailable": (503, "Deployment state is unavailable."),
    }
)


class DeploymentPrepareError(ValueError):
    def __init__(self, code="invalid_input"):
        if type(code) is not str or code not in ERRORS:
            raise ValueError("Unknown deployment error code")
        self.code = code
        super().__init__(ERRORS[code][1])


def require(condition, code="invalid_input"):
    if not condition:
        raise DeploymentPrepareError(code)


def b64(raw):
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def validate(value, schema):
    require(
        Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value)
    )


def _input(value, schema):
    try:
        raw = canonical_json(value)
        require(len(raw) <= 4096, "too_large")
        parsed = parse_json_object(
            raw,
            required=schema["required"],
            limits=WireLimits(
                max_bytes=4096,
                max_depth=4,
                max_items=32,
                max_members=8,
                max_string_bytes=256,
            ),
        )
        validate(parsed, schema)
        return parsed
    except DeploymentPrepareError:
        raise
    except (ValueError, TypeError, RecursionError):
        raise DeploymentPrepareError() from None


def parse_prepare(value):
    return _input(value, prepare_input_schema())


def parse_cancel(request_id, value):
    try:
        uuid_string(request_id)
        return {**_input(value, cancel_input_schema()), "request_id": request_id}
    except DeploymentPrepareError:
        raise
    except (ValueError, TypeError):
        raise DeploymentPrepareError() from None


def stamp(milliseconds):
    require(type(milliseconds) is int and 0 <= milliseconds <= MAX_MS)
    value = EPOCH + timedelta(milliseconds=milliseconds)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def epoch_ms(value):
    try:
        instant = datetime.fromisoformat(value)
        delta = instant - EPOCH
        result = (
            delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000
        )
        require(stamp(result) == value)
        return result
    except (ValueError, TypeError, OverflowError):
        raise DeploymentPrepareError() from None


def interval(created_ms, ttl_seconds):
    require(type(ttl_seconds) is int and 60 <= ttl_seconds <= 86400)
    require(type(created_ms) is int and 0 <= created_ms <= MAX_MS - ttl_seconds * 1000)
    return stamp(created_ms), stamp(created_ms + ttl_seconds * 1000)


def stage_for_candidate(bundle, topology, slot):
    """Reconstruct from an intact bundle; caller still authenticates its actual DB origin."""
    try:
        require(type(bundle) is CandidateBundle)
        # Dataclass construction is public inert data, so never trust its cached members.
        bundle = parse_bundle(bundle.as_dict())
        m, d = bundle.manifest.as_dict(), bundle.descriptor.as_dict()
        port = PORT_CONTRACTS[m["port_contract_version"]]
        require(
            (
                port.port_contract_version,
                port.extension_kind,
                port.artifact_form,
                port.trust_tier,
            )
            == ("tool-port-v1", "tool", "oci_extension_service", "runtime_worker")
        )
        require(
            m["requirements"]["grant_ids"] == []
            and m["requirements"]["secret_needs"] == []
            and m["requirements"]["filesystem_needs"] == ["owned_scratch"]
            and d["secret_needs"] == []
        )
        require(
            topology["control"]
            == {"service_identity": "control", "uid": 20102, "gid": 20102}
        )
        require(slot in topology["slots"])
        require(
            [v["platform"] for v in d["platforms"]] == ["linux/amd64", "linux/arm64"]
        )
        require(all(d[key] == slot[key] for key in ("service_identity", "uid", "gid")))
        require(
            d["socket_mounts"] == [slot["socket_mount"]]
            and d["named_volume_mounts"] == []
        )
        require(d["command"]["protocol_id"] == slot["protocol_id"])
        require(
            d["broker_endpoint"]
            == {
                "channel_id": slot["channel_id"],
                "requester_service": "control",
                "responder_service": slot["service_identity"],
                "protocol_id": slot["protocol_id"],
                "requester_uid": 20102,
                "requester_gid": 20102,
                "pair_gid": slot["pair_gid"],
                "socket_mount_id": slot["socket_mount"]["mount_id"],
                "socket_name": slot["socket_name"],
            }
        )
        documents = {
            kind: parse_canonical(raw)
            for kind, raw in bundle.documents
            if kind
            in {"network_declaration", "resource_declaration", "isolation_declaration"}
        }
        require(
            documents["network_declaration"]
            == {
                "schema_version": "extension-network-declaration-v1",
                "network_mode": "none",
            }
        )
        require(
            documents["isolation_declaration"]
            == {
                "schema_version": "extension-isolation-declaration-v1",
                "read_only_rootfs": True,
                "no_new_privileges": True,
                "cap_drop": ["ALL"],
                "seccomp_profile": "runtime-default",
                "privileged": False,
                "host_namespaces": [],
            }
        )
        resources = documents["resource_declaration"]
        require(
            all(
                resources[key] <= slot["resource_budget"][key]
                for key in (
                    "memory_bytes",
                    "cpu_millicores",
                    "pids_limit",
                    "tmpfs_bytes",
                )
            )
        )
        selected = next(
            v for v in d["platforms"] if v["platform"] == topology["platform"]
        )
        result = {
            "schema_id": "deeptwin.extension-stage-request.v1",
            "extension_id": m["extension_id"],
            "manifest_digest": bundle.manifest.digest,
            "service_descriptor_digest": bundle.descriptor.digest,
            "selected_platform_entry": {
                "platform": selected["platform"],
                "index_digest": d["index"]["digest"],
                "manifest_digest": selected["manifest"]["digest"],
                "config_digest": selected["config"]["digest"],
                "ordered_layer_digests": [v["digest"] for v in selected["layers"]],
            },
            "new_service_effect": {
                "service_identity": d["service_identity"],
                "socket_mounts": d["socket_mounts"],
                "named_volume_mounts": [],
                "network_policy_ref": d["network_policy_ref"],
                "resource_profile_ref": d["resource_profile_ref"],
            },
            "expected_installation_head": {"state": "absent"},
            "expected_next_installation_revision": 1,
        }
        validate(result, stage_schema())
        return result
    except DeploymentPrepareError:
        raise
    except (ValueError, KeyError, TypeError, StopIteration):
        raise DeploymentPrepareError() from None


def make_request(
    *,
    bundle,
    topology,
    slot,
    profile,
    request_id,
    nonce,
    actor_ref,
    created_ms,
    ttl_seconds,
):
    require(type(nonce) is bytes and len(nonce) == 32)
    created_at, expires_at = interval(created_ms, ttl_seconds)
    value = {
        "schema": "deployment-request-v1",
        "domain": "deeptwin-deployment-request-v1",
        "request_id": request_id,
        "kind": "extension_stage",
        "request_nonce": b64(nonce),
        "instance_id": profile.instance_id,
        "origin_profile_digest": b64(bytes.fromhex(profile.digest)),
        "effect_payload": stage_for_candidate(bundle, topology, slot),
        "preconditions": {},
        "created_by": actor_ref,
        "created_at": created_at,
        "expires_at": expires_at,
    }
    value["request_digest"] = b64(sha256(canonical_json(value)).digest())
    return parse_request(canonical_json(value), profile=profile)


def parse_request(raw, *, profile):
    try:
        require(type(raw) is bytes and len(raw) <= 65536)
        value = parse_canonical(raw)
        validate(value, request_schema())
        validate_projection(
            role="request",
            request_digest=value["request_digest"],
            payload=raw,
            profile=profile,
        )
        duration = epoch_ms(value["expires_at"]) - epoch_ms(value["created_at"])
        require(60000 <= duration <= 86400000 and duration % 1000 == 0)
        return value
    except DeploymentPrepareError:
        raise
    except (
        ValueError,
        KeyError,
        TypeError,
        RecursionError,
        sources.DeploymentSourceError,
    ):
        raise DeploymentPrepareError() from None


def cancellation(request, transitioned_ms, *, profile):
    """Validate the inert marker against an explicit profile, never inferred claims."""
    try:
        require(type(request) is dict)
        raw = canonical_json(
            {
                "schema": "deployment-cancellation-v1",
                "domain": "deeptwin-deployment-cancellation-v1",
                "request_id": request["request_id"],
                "request_digest": request["request_digest"],
                "instance_id": request["instance_id"],
                "origin_profile_digest": request["origin_profile_digest"],
                "lifecycle_revision": 2,
                "cancelled_at": stamp(transitioned_ms),
            }
        )
        validate_projection(
            role="cancel",
            request_digest=request["request_digest"],
            payload=raw,
            profile=profile,
        )
        return raw
    except (ValueError, KeyError, TypeError, RecursionError):
        raise DeploymentPrepareError() from None


def links(request_id):
    uuid_string(request_id)
    path = "/api/v1/deployment/requests/" + request_id
    return {"self": path, "cancel": path + "/cancel", "events": "/api/v1/events"}
