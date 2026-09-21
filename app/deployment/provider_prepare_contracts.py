"""Pure provider preparation wire codecs and exact inert source joins."""

from __future__ import annotations

import hmac
import json
import re
from hashlib import sha256

from jsonschema import Draft202012Validator, FormatChecker

from ..domain.refs import EntityRef, canonical_json, parse_canonical, uuid_string
from ..domain.wire import WireLimits, parse_json_object
from ..extensions.candidate_contracts import CandidateBundle, metadata_ref, parse_bundle
from ..extensions.port_contracts import PORT_CONTRACTS
from ..extensions.provider_lineage import (
    parse_provider_lineage,
    validate_provider_descriptor_lineage,
)
from ..operations.setup import OriginProfile, parse_base64url_32
from . import contracts as source_contracts
from .prepare_contracts import (
    MAX_MS,
    DeploymentPrepareError,
    b64,
    epoch_ms,
    interval,
    stamp,
)
from .provider_geometry import parse_provider_geometry
from .provider_prepare_schema_exports import (
    provider_cancel_input_schema,
    provider_cancellation_schema,
    provider_inventory_schema,
    provider_prepare_input_schema,
    provider_request_anchor_schema,
    provider_request_schema,
)
from .provider_source_contracts import (
    BUNDLE_LAYOUT,
    parse_provider_context,
    parse_provider_instance,
    validate_provider_source_bundle,
)

_HEX = re.compile(r"[0-9a-f]{64}")
_EXTENSION_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?")
_BROKER = re.compile(r"[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*")
_ORDINARY_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
    UnicodeError,
    RecursionError,
    MemoryError,
    StopIteration,
)


def _fail(code="invalid_input"):
    return DeploymentPrepareError(code)


def _require(condition, code="invalid_input"):
    if not condition:
        raise _fail(code)


def _validate(value, schema):
    _require(
        Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value)
    )


def _profile(profile):
    _require(type(profile) is OriginProfile)
    rebuilt = OriginProfile.from_dict(profile.as_dict())
    _require(rebuilt == profile)
    return profile


def _limits(cap, *, depth=16, items=8192, members=32, string=1024):
    return WireLimits(
        max_bytes=cap,
        max_depth=depth,
        max_items=items,
        max_members=members,
        max_string_bytes=string,
        max_integer=2**40,
    )


def _raw_object(raw, schema, cap):
    if type(raw) is bytes and len(raw) > cap:
        raise _fail("too_large")
    value = parse_json_object(
        raw,
        required=schema["required"],
        limits=_limits(cap),  # type: ignore[arg-type]
    )
    _require(canonical_json(value) == raw)
    _validate(value, schema)
    return value


def _preflight_json_size(value, cap):
    try:
        size = 0
        encoder = json.JSONEncoder(
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        for fragment in encoder.iterencode(value):
            size += len(fragment.encode("utf-8"))
            if size > cap:
                raise _fail("too_large")
    except DeploymentPrepareError:
        raise
    except _ORDINARY_ERRORS:
        raise _fail() from None


def _input(value, schema):
    try:
        _preflight_json_size(value, 4096)
        raw = canonical_json(value)
        result = parse_json_object(
            raw,
            required=schema["required"],
            limits=_limits(4096, depth=4, items=32, members=8, string=256),
        )
        _validate(result, schema)
        return result
    except DeploymentPrepareError:
        raise
    except _ORDINARY_ERRORS:
        raise _fail() from None


def parse_provider_prepare(value: dict) -> dict:
    return _input(value, provider_prepare_input_schema())


def parse_provider_cancel(request_id: str, value: dict) -> dict:
    try:
        uuid_string(request_id)
        return {
            **_input(value, provider_cancel_input_schema()),
            "request_id": request_id,
        }
    except DeploymentPrepareError:
        raise
    except _ORDINARY_ERRORS:
        raise _fail() from None


def _head_digest(entry):
    preimage = {
        "namespace": "deployment-prepare-storage-v3",
        "table": "installation_heads",
        "row": {
            "extension_id": entry["extension_id"],
            "request_id": entry["request_ref"]["id"],
            "revision": entry["head_revision"],
            "installation_anchor_digest": entry["installation_ref"]["sha256"],
        },
    }
    return sha256(canonical_json(preimage)).hexdigest()


def parse_provider_inventory(raw: bytes) -> dict:
    try:
        value = _raw_object(raw, provider_inventory_schema(), 16384)
        uuid_string(value["vault_id"])
        uuid_string(value["topology_id"])
        entries = value["installations"]
        keys = [
            (entry["extension_id"], entry["installation_ref"]["id"])
            for entry in entries
        ]
        _require(keys == sorted(keys) and len(keys) == len(set(keys)))
        installations = []
        requests = []
        slots = []
        events = []
        extensions = []
        services = []
        for entry in entries:
            installation = EntityRef.from_dict(entry["installation_ref"])
            request = EntityRef.from_dict(entry["request_ref"])
            _require(
                installation.kind == "extension_installation"
                and installation.version == 1
                and request.kind == "deployment_request"
                and request.version == 1
                and _EXTENSION_ID.fullmatch(entry["extension_id"]) is not None
                and _BROKER.fullmatch(entry["service_identity"]) is not None
                and hmac.compare_digest(entry["head_digest"], _head_digest(entry))
            )
            uuid_string(entry["accepted_event_id"])
            uuid_string(entry["staged_event_id"])
            installations.append(installation.id)
            requests.append(request.id)
            slots.append(entry["slot_id"])
            events.extend((entry["accepted_event_id"], entry["staged_event_id"]))
            extensions.append(entry["extension_id"])
            services.append(entry["service_identity"])
        for sequence in (installations, requests, slots, events, extensions, services):
            _require(len(sequence) == len(set(sequence)))
        return parse_canonical(canonical_json(value))
    except DeploymentPrepareError:
        raise
    except _ORDINARY_ERRORS:
        raise _fail() from None


def _request_digest(value):
    unsigned = {name: item for name, item in value.items() if name != "request_digest"}
    return b64(sha256(canonical_json(unsigned)).digest())


def parse_provider_request(raw: bytes, *, profile: OriginProfile) -> dict:
    try:
        checked_profile = _profile(profile)
        value = _raw_object(raw, provider_request_schema(), 65536)
        uuid_string(value["request_id"])
        parse_base64url_32(value["request_nonce"])
        parse_base64url_32(value["request_digest"])
        parse_base64url_32(value["origin_profile_digest"])
        _require(
            value["instance_id"] == checked_profile.instance_id
            and value["origin_profile_digest"]
            == b64(bytes.fromhex(checked_profile.digest))
            and hmac.compare_digest(value["request_digest"], _request_digest(value))
            and value["preconditions"] == {}
        )
        actor = EntityRef.from_dict(value["created_by"])
        _require(actor.kind == "actor")
        duration = epoch_ms(value["expires_at"]) - epoch_ms(value["created_at"])
        _require(60_000 <= duration <= 86_400_000 and duration % 1000 == 0)
        inventory = value["effect_payload"]["preserved_inventory"]
        parse_provider_inventory(canonical_json(inventory))
        _require(
            value["effect_payload"]["preserved_inventory_sha256"]
            == sha256(canonical_json(inventory)).hexdigest()
        )
        return parse_canonical(canonical_json(value))
    except DeploymentPrepareError:
        raise
    except _ORDINARY_ERRORS:
        raise _fail() from None


def parse_provider_cancellation(raw: bytes, *, profile: OriginProfile) -> dict:
    try:
        checked_profile = _profile(profile)
        value = _raw_object(raw, provider_cancellation_schema(), 8192)
        uuid_string(value["request_id"])
        parse_base64url_32(value["request_digest"])
        parse_base64url_32(value["origin_profile_digest"])
        epoch_ms(value["cancelled_at"])
        _require(
            value["instance_id"] == checked_profile.instance_id
            and value["origin_profile_digest"]
            == b64(bytes.fromhex(checked_profile.digest))
        )
        return parse_canonical(canonical_json(value))
    except DeploymentPrepareError:
        raise
    except _ORDINARY_ERRORS:
        raise _fail() from None


def _blob(value, cap):
    _require(
        type(value) is dict and set(value) == {"vault_id", "purpose", "sha256", "size"}
    )
    uuid_string(value["vault_id"])
    _require(
        value["purpose"] == "operational"
        and type(value["sha256"]) is str
        and _HEX.fullmatch(value["sha256"]) is not None
        and type(value["size"]) is int
        and 1 <= value["size"] <= cap
    )
    return value["vault_id"]


def validate_provider_anchor_content(content: dict) -> None:
    try:
        _preflight_json_size(content, 8192)
        canonical_json(content)
        _validate(content, provider_request_anchor_schema())
        for name in ("request_id", "topology_id", "prepare_command_id"):
            uuid_string(content[name])
        candidate = EntityRef.from_dict(content["candidate_ref"])
        _require(candidate.kind == "extension_manifest" and candidate.version == 1)
        vaults = [
            _blob(content["request_blob_ref"], 65536),
            _blob(content["preserved_inventory_blob_ref"], 16384),
        ]
        _require(
            [item["name"] for item in content["source_documents"]]
            == [name for name, _ in BUNDLE_LAYOUT]
        )
        for item, (_, cap) in zip(
            content["source_documents"], BUNDLE_LAYOUT, strict=True
        ):
            vaults.append(_blob(item["blob_ref"], cap))
        _require(len(set(vaults)) == 1)
    except DeploymentPrepareError:
        raise
    except _ORDINARY_ERRORS:
        raise _fail() from None


def _reparse_candidate(candidate_bundle):
    _require(type(candidate_bundle) is CandidateBundle)
    raw = object.__getattribute__(candidate_bundle, "content_bytes")
    _require(type(raw) is bytes)
    _require(len(raw) <= 1_048_576, "too_large")
    return parse_bundle(parse_canonical(raw))


def _preflight_source_bundle(source_bundle_files):
    if type(source_bundle_files) is not tuple or len(source_bundle_files) != 18:
        return
    total = 0
    for pair, (_, cap) in zip(source_bundle_files, BUNDLE_LAYOUT, strict=True):
        if type(pair) is not tuple or len(pair) != 2 or type(pair[1]) is not bytes:
            return
        total += len(pair[1])
        if len(pair[1]) > cap or total > 524288:
            raise _fail("too_large")


def _source(candidate_bundle, source_bundle_files, provider_schema_bytes, profile):
    _profile(profile)
    _require(
        type(source_bundle_files) is tuple
        and type(provider_schema_bytes) is tuple
        and len(provider_schema_bytes) == 4
        and all(type(raw) is bytes for raw in provider_schema_bytes)
    )
    _preflight_source_bundle(source_bundle_files)
    validate_provider_source_bundle(source_bundle_files)
    raw = tuple(pair[1] for pair in source_bundle_files)
    geometry = parse_provider_geometry(raw[9]).as_dict()
    context = parse_provider_context(raw[16])
    provider_instance = parse_provider_instance(raw[11])
    original_instance = source_contracts.parse_instance(raw[1])
    _require(
        geometry["origin_profile"] == profile.as_dict()
        and geometry["instance_id"] == profile.instance_id
        and original_instance["origin_profile"] == profile.as_dict()
        and original_instance["platform"] == geometry["platform"]
        and original_instance["topology_id"] == geometry["topology_id"]
        and context["instance_id"] == profile.instance_id
        and context["origin_profile_digest"] == profile.digest
        and context["topology_id"] == geometry["topology_id"]
        and context["geometry_sha256"] == sha256(raw[9]).hexdigest()
        and context["context_id"] == provider_instance["context_id"]
    )
    bundle = _reparse_candidate(candidate_bundle)
    manifest = bundle.manifest.as_dict()
    descriptor = bundle.descriptor.as_dict()
    port = PORT_CONTRACTS[manifest["port_contract_version"]]
    _require(
        (
            port.port_contract_version,
            port.extension_kind,
            port.artifact_form,
            port.trust_tier,
        )
        == ("provider-port-v1", "provider", "oci_extension_service", "runtime_worker")
        and manifest["extension_kind"] == "provider"
        and manifest["artifact"]["artifact_form"] == "oci_extension_service"
    )
    provenance = next(
        leaf
        for kind, leaf in bundle.documents
        if kind == "provenance"
        and metadata_ref(kind, leaf) == manifest["source"]["provenance_ref"]
    )
    lineage = parse_provider_lineage(provenance)
    documents = {
        kind: parse_canonical(leaf)
        for kind, leaf in bundle.documents
        if kind != "license"
    }
    return raw, geometry, context, bundle, manifest, descriptor, lineage, documents


def _validate_slot_join(
    bundle,
    manifest,
    descriptor,
    lineage,
    documents,
    geometry,
    provider_schema_bytes,
    slot,
):
    validate_provider_descriptor_lineage(
        lineage,
        bundle.descriptor,
        instance_id=geometry["instance_id"],
        slot_number=slot["slot_number"],
        schema_bytes=provider_schema_bytes,
    )
    expected_broker = {
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
    _require(
        geometry["control"]
        == {"service_identity": "control", "uid": 20102, "gid": 20102}
        and [item["platform"] for item in descriptor["platforms"]]
        == ["linux/amd64", "linux/arm64"]
        and all(
            descriptor[name] == slot[name]
            for name in ("service_identity", "uid", "gid")
        )
        and descriptor["socket_mounts"] == [slot["socket_mount"]]
        and descriptor["named_volume_mounts"] == []
        and descriptor["broker_endpoint"] == expected_broker
        and descriptor["secret_needs"] == []
        and manifest["requirements"]["grant_ids"] == []
        and manifest["requirements"]["secret_needs"] == []
        and manifest["requirements"]["filesystem_needs"] == ["owned_scratch"]
        and documents["network_declaration"]
        == {
            "schema_version": "extension-network-declaration-v1",
            "network_mode": "none",
        }
        and documents["isolation_declaration"]
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
    _require(
        all(
            resources[name] <= slot["resource_budget"][name]
            for name in ("memory_bytes", "cpu_millicores", "pids_limit", "tmpfs_bytes")
        )
    )


def _joined_inputs(
    candidate_bundle,
    source_bundle_files,
    provider_schema_bytes,
    inventory_bytes,
    profile,
    slot_number=None,
):
    (
        raw,
        geometry,
        context,
        bundle,
        manifest,
        descriptor,
        lineage,
        documents,
    ) = _source(candidate_bundle, source_bundle_files, provider_schema_bytes, profile)
    if slot_number is None:
        matches = [
            slot
            for slot in geometry["slots"]
            if descriptor["service_identity"] == slot["service_identity"]
            and descriptor["uid"] == slot["uid"]
            and descriptor["gid"] == slot["gid"]
        ]
        _require(len(matches) == 1)
        slot = matches[0]
    else:
        _require(
            type(slot_number) is int and 1 <= slot_number <= len(geometry["slots"])
        )
        slot = geometry["slots"][slot_number - 1]
        _require(slot["slot_number"] == slot_number)
    _validate_slot_join(
        bundle,
        manifest,
        descriptor,
        lineage,
        documents,
        geometry,
        provider_schema_bytes,
        slot,
    )
    inventory = parse_provider_inventory(inventory_bytes)
    _require(
        inventory["instance_id"] == profile.instance_id
        and inventory["origin_profile_digest"] == profile.digest
        and inventory["topology_id"] == geometry["topology_id"]
        and inventory["topology_sha256"] == sha256(raw[2]).hexdigest()
        and manifest["extension_id"]
        not in {entry["extension_id"] for entry in inventory["installations"]}
    )
    for entry in inventory["installations"]:
        _require(entry["slot_id"] != slot["slot_number"])
        old_slot = geometry["slots"][entry["slot_id"] - 1]
        _require(entry["service_identity"] == old_slot["service_identity"])
    return (
        raw,
        geometry,
        context,
        bundle,
        manifest,
        descriptor,
        lineage,
        inventory,
        slot,
    )


def make_provider_request(
    *,
    candidate_bundle: CandidateBundle,
    source_bundle_files: tuple[tuple[str, bytes], ...],
    provider_schema_bytes: tuple[bytes, bytes, bytes, bytes],
    inventory_bytes: bytes,
    slot_number: int,
    profile: OriginProfile,
    request_id: str,
    nonce: bytes,
    actor_ref: dict,
    created_ms: int,
    ttl_seconds: int,
) -> bytes:
    try:
        _profile(profile)
        uuid_string(request_id)
        _require(type(nonce) is bytes and len(nonce) == 32)
        actor = EntityRef.from_dict(actor_ref)
        _require(actor.kind == "actor")
        created_at, expires_at = interval(created_ms, ttl_seconds)
        (
            raw,
            geometry,
            context,
            bundle,
            manifest,
            descriptor,
            lineage,
            inventory,
            _slot,
        ) = _joined_inputs(
            candidate_bundle,
            source_bundle_files,
            provider_schema_bytes,
            inventory_bytes,
            profile,
            slot_number,
        )
        selected = lineage.selected_platform(geometry["platform"])
        effect = {
            "schema_id": "deeptwin.extension-stage-request.v2",
            "extension_id": manifest["extension_id"],
            "manifest_digest": bundle.manifest.digest,
            "service_descriptor_digest": bundle.descriptor.digest,
            "selected_platform_entry": selected,
            "new_service_effect": {
                "service_identity": descriptor["service_identity"],
                "socket_mounts": descriptor["socket_mounts"],
                "named_volume_mounts": [],
                "network_policy_ref": descriptor["network_policy_ref"],
                "resource_profile_ref": descriptor["resource_profile_ref"],
            },
            "expected_installation_head": {"state": "absent"},
            "expected_next_installation_revision": 1,
            "stage_profile": "claude-text-transform-v1",
            "source_context": {
                "context_id": context["context_id"],
                "epoch": 1,
                "sha256": sha256(raw[16]).hexdigest(),
                "size_bytes": len(raw[16]),
            },
            "geometry": {
                "sha256": sha256(raw[9]).hexdigest(),
                "size_bytes": len(raw[9]),
            },
            "preserved_inventory": inventory,
            "preserved_inventory_sha256": sha256(inventory_bytes).hexdigest(),
        }
        value = {
            "schema": "deployment-request-v2",
            "domain": "deeptwin-deployment-request-v2",
            "request_id": request_id,
            "kind": "extension_stage",
            "request_nonce": b64(nonce),
            "instance_id": profile.instance_id,
            "origin_profile_digest": b64(bytes.fromhex(profile.digest)),
            "effect_payload": effect,
            "preconditions": {},
            "created_by": actor_ref,
            "created_at": created_at,
            "expires_at": expires_at,
        }
        value["request_digest"] = _request_digest(value)
        encoded = canonical_json(value)
        parse_provider_request(encoded, profile=profile)
        return encoded
    except DeploymentPrepareError:
        raise
    except _ORDINARY_ERRORS:
        raise _fail() from None


def validate_provider_request_sources(
    raw: bytes,
    *,
    candidate_bundle: CandidateBundle,
    source_bundle_files: tuple[tuple[str, bytes], ...],
    provider_schema_bytes: tuple[bytes, bytes, bytes, bytes],
    inventory_bytes: bytes,
    profile: OriginProfile,
) -> None:
    try:
        value = parse_provider_request(raw, profile=profile)
        nonce = parse_base64url_32(value["request_nonce"])
        created_ms = epoch_ms(value["created_at"])
        ttl_seconds = (epoch_ms(value["expires_at"]) - created_ms) // 1000
        joined = _joined_inputs(
            candidate_bundle,
            source_bundle_files,
            provider_schema_bytes,
            inventory_bytes,
            profile,
            None,
        )
        slot = joined[-1]
        expected = make_provider_request(
            candidate_bundle=candidate_bundle,
            source_bundle_files=source_bundle_files,
            provider_schema_bytes=provider_schema_bytes,
            inventory_bytes=inventory_bytes,
            slot_number=slot["slot_number"],
            profile=profile,
            request_id=value["request_id"],
            nonce=nonce,
            actor_ref=value["created_by"],
            created_ms=created_ms,
            ttl_seconds=ttl_seconds,
        )
        _require(hmac.compare_digest(raw, expected))
    except DeploymentPrepareError:
        raise
    except _ORDINARY_ERRORS:
        raise _fail() from None


def make_provider_cancellation(
    request_bytes: bytes, *, profile: OriginProfile, cancelled_ms: int
) -> bytes:
    try:
        request = parse_provider_request(request_bytes, profile=profile)
        created_ms = epoch_ms(request["created_at"])
        expires_ms = epoch_ms(request["expires_at"])
        _require(
            type(cancelled_ms) is int
            and 0 <= cancelled_ms <= MAX_MS
            and created_ms <= cancelled_ms < expires_ms
        )
        effect = request["effect_payload"]
        value = {
            "schema": "deployment-provider-cancellation-v1",
            "domain": "deeptwin-deployment-provider-cancellation-v1",
            "request_id": request["request_id"],
            "request_digest": request["request_digest"],
            "instance_id": request["instance_id"],
            "origin_profile_digest": request["origin_profile_digest"],
            "source_context_sha256": effect["source_context"]["sha256"],
            "preserved_inventory_sha256": effect["preserved_inventory_sha256"],
            "lifecycle_revision": 2,
            "cancelled_at": stamp(cancelled_ms),
        }
        encoded = canonical_json(value)
        parse_provider_cancellation(encoded, profile=profile)
        return encoded
    except DeploymentPrepareError:
        raise
    except _ORDINARY_ERRORS:
        raise _fail() from None


__all__ = [
    "DeploymentPrepareError",
    "make_provider_cancellation",
    "make_provider_request",
    "parse_provider_cancel",
    "parse_provider_cancellation",
    "parse_provider_inventory",
    "parse_provider_prepare",
    "parse_provider_request",
    "validate_provider_anchor_content",
    "validate_provider_request_sources",
]
