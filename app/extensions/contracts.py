"""Pure extension values. Parsing a value never imports or executes its artifact."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import re
from types import MappingProxyType

from ..domain.refs import MAX_INTEGER, canonical_json, parse_canonical, uuid_string


EXTENSION_KINDS = frozenset({
    "provider", "model_runtime", "tool", "artifact_codec", "lens", "evaluator",
    "storage", "credential_vault", "export_sink",
})
TRUST_TIERS = frozenset({
    "deployment_trusted", "runtime_worker", "definition_package", "managed_provider_runner",
})
INSTALL_AUTHORITIES = frozenset({
    "deployment_operator", "product_owner", "work", "model", "browser_import",
})
INSTALLATION_STATES = frozenset({
    "discovered", "staged", "verified", "qualified", "enabled", "failed", "suspended",
    "revoked", "removed",
})
QUALIFICATION_RESULTS = frozenset({"passed", "failed", "unknown"})
MANDATORY_QUALIFICATION_CHECKS = (
    "permission", "isolation", "egress", "secret", "compatibility",
)
QUALIFICATION_RECHECK_TRIGGERS = (
    "artifact_change", "framework_change", "permission_change", "platform_change",
    "runtime_change", "schema_change", "expiry",
)
MAX_QUALIFICATION_TTL_SECONDS = 604_800
_PURPOSES = frozenset({
    "operational", "diagnosis", "inquiry_audit", "evaluation_development",
    "evaluation_sealed", "release_evidence",
})
_HASH = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?")
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_FAILURE_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z")
_MANIFEST_FIELDS = frozenset({
    "schema_version", "extension_id", "extension_version", "extension_kind", "artifact",
    "source", "license_expression", "compatibility", "entrypoint", "config_schema",
    "input_schema", "output_schema", "declared_grants", "declared_resources", "network_needs",
    "filesystem_needs", "secret_needs", "isolation_profile", "migration_policy",
    "uninstall_policy",
})
_COMPATIBILITY_FIELDS = frozenset({
    "extension_api", "framework_min", "framework_max", "schema_versions",
})
_ARTIFACT_FIELDS = frozenset({"type", "sha256"})
_SOURCE_FIELDS = frozenset({"kind", "locator", "provenance_sha256"})
_ENTRYPOINT_FIELDS = frozenset({"protocol", "name"})
_SCOPE_FIELDS = frozenset({"instance_id", "environment_id", "work_id", "node_id", "purpose"})


class ExtensionContractError(ValueError):
    """Extension data or lifecycle state is invalid and grants no authority."""


class RuntimeBoundaryUnavailable(ExtensionContractError):
    """The pure SPI cannot dispatch before the separately qualified T018 broker exists."""


def _exact(value, fields, label):
    if type(value) is not dict or set(value) != fields:
        raise ExtensionContractError(f"{label} must match its exact schema")
    return value


def _text(value, label, maximum=512, *, pattern=None):
    if type(value) is not str or not value:
        raise ExtensionContractError(f"{label} must be bounded text")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ExtensionContractError(f"{label} contains invalid Unicode") from exc
    if size > maximum or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ExtensionContractError(f"{label} must be bounded text")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ExtensionContractError(f"{label} has an invalid format")
    return value


def _digest(value, label):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ExtensionContractError(f"{label} must be a lowercase SHA-256")
    return value


def _uuid(value, label):
    try:
        return uuid_string(value)
    except (TypeError, ValueError) as exc:
        raise ExtensionContractError(f"{label} must be a canonical UUID") from exc


def _version(value, label):
    return _text(value, label, 32, pattern=_VERSION)


def _version_tuple(value):
    match = _VERSION.fullmatch(value)
    if match is None:  # guarded at construction
        raise ExtensionContractError("Invalid version")
    return tuple(int(part) for part in match.groups())


def _timestamp(value, label):
    if type(value) is not str or _TIMESTAMP.fullmatch(value) is None:
        raise ExtensionContractError(f"{label} must be an exact UTC timestamp")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ExtensionContractError(f"{label} is not a calendar timestamp") from exc
    return value


def _strings(value, label, *, required=False, maximum=64):
    if type(value) not in (tuple, list) or len(value) > maximum:
        raise ExtensionContractError(f"{label} must be a bounded sequence")
    result = tuple(_text(item, label, 256) for item in value)
    if (required and not result) or len(set(result)) != len(result):
        raise ExtensionContractError(f"{label} must contain unique values")
    return result


def _digests(value, label, *, required=False):
    if type(value) not in (tuple, list) or len(value) > 256:
        raise ExtensionContractError(f"{label} must be a bounded sequence")
    result = tuple(_digest(item, label) for item in value)
    if (required and not result) or len(set(result)) != len(result):
        raise ExtensionContractError(f"{label} must contain unique references")
    return result


def _schema_bytes(value, label):
    if type(value) is not dict or value.get("type") not in {
        "object", "array", "string", "integer", "boolean", "null",
    }:
        raise ExtensionContractError(f"{label} must be a bounded JSON schema object")
    try:
        return canonical_json(value)
    except ValueError as exc:
        raise ExtensionContractError(f"{label} must be bounded canonical data") from exc


def _choice(value, choices, label):
    if type(value) is not str or value not in choices:
        raise ExtensionContractError(f"{label} is not registered")
    return value


@dataclass(frozen=True, slots=True, init=False)
class ExtensionManifest:
    schema_version: str
    extension_id: str
    extension_version: str
    extension_kind: str
    artifact_type: str
    artifact_sha256: str
    source_kind: str
    source_locator: str = field(repr=False)
    provenance_sha256: str
    license_expression: str
    extension_api: str
    framework_min: str
    framework_max: str
    schema_versions: tuple[str, ...]
    entrypoint_protocol: str
    entrypoint_name: str
    _config_schema: bytes
    _input_schema: bytes
    _output_schema: bytes
    declared_grants: tuple[str, ...]
    declared_resources: tuple[str, ...]
    network_needs: tuple[str, ...]
    filesystem_needs: tuple[str, ...]
    secret_needs: tuple[str, ...]
    isolation_profile: str
    migration_policy: str
    uninstall_policy: str
    _digest: str

    def __new__(cls):
        raise TypeError("Use ExtensionManifest.from_mapping")

    @classmethod
    def from_mapping(cls, value):
        value = _exact(value, _MANIFEST_FIELDS, "extension manifest")
        if value["schema_version"] != "extension-manifest-v1":
            raise ExtensionContractError("Unsupported extension manifest version")
        kind = _choice(value["extension_kind"], EXTENSION_KINDS, "extension kind")
        artifact = _exact(value["artifact"], _ARTIFACT_FIELDS, "artifact")
        artifact_type = _choice(artifact["type"], {"package", "image", "definition"},
                                "artifact type")
        source = _exact(value["source"], _SOURCE_FIELDS, "source")
        source_kind = _choice(source["kind"], {"built_in", "third_party", "operator_deployment"},
                              "source kind")
        compatibility = _exact(value["compatibility"], _COMPATIBILITY_FIELDS, "compatibility")
        framework_min = _version(compatibility["framework_min"], "framework_min")
        framework_max = _version(compatibility["framework_max"], "framework_max")
        if _version_tuple(framework_min) > _version_tuple(framework_max):
            raise ExtensionContractError("Framework compatibility range is reversed")
        entrypoint = _exact(value["entrypoint"], _ENTRYPOINT_FIELDS, "entrypoint")
        protocol = _choice(entrypoint["protocol"], {
            "definition-v1", "worker-json-v1", "managed-provider-rpc-v1", "deployment-port-v1",
        }, "entrypoint protocol")
        if (protocol == "definition-v1") != (artifact_type == "definition"):
            raise ExtensionContractError("Definition protocol and artifact type must agree")
        if protocol == "definition-v1" and kind not in {"lens", "evaluator"}:
            raise ExtensionContractError("Code-free definitions are limited to lens or evaluator kinds")
        if kind == "lens" and protocol != "definition-v1":
            raise ExtensionContractError("Lens extensions must be code-free definitions")
        if kind in {"storage", "credential_vault"} and protocol != "deployment-port-v1":
            raise ExtensionContractError("Instance-critical adapters require deployment port protocol")
        if protocol == "managed-provider-rpc-v1" and kind != "provider":
            raise ExtensionContractError("Managed provider protocol is provider-only")
        fields = dict(
            schema_version="extension-manifest-v1",
            extension_id=_text(value["extension_id"], "extension_id", 128, pattern=_IDENTIFIER),
            extension_version=_version(value["extension_version"], "extension_version"),
            extension_kind=kind,
            artifact_type=artifact_type,
            artifact_sha256=_digest(artifact["sha256"], "artifact digest"),
            source_kind=source_kind,
            source_locator=_text(source["locator"], "source locator", 2048),
            provenance_sha256=_digest(source["provenance_sha256"], "provenance digest"),
            license_expression=_text(value["license_expression"], "license expression", 256),
            extension_api=_version(compatibility["extension_api"], "extension_api"),
            framework_min=framework_min,
            framework_max=framework_max,
            schema_versions=_strings(compatibility["schema_versions"], "schema versions", required=True),
            entrypoint_protocol=protocol,
            entrypoint_name=_text(entrypoint["name"], "entrypoint name", 128, pattern=_IDENTIFIER),
            _config_schema=_schema_bytes(value["config_schema"], "config_schema"),
            _input_schema=_schema_bytes(value["input_schema"], "input_schema"),
            _output_schema=_schema_bytes(value["output_schema"], "output_schema"),
            declared_grants=_strings(value["declared_grants"], "declared grants"),
            declared_resources=_strings(value["declared_resources"], "declared resources"),
            network_needs=_strings(value["network_needs"], "network needs"),
            filesystem_needs=_strings(value["filesystem_needs"], "filesystem needs"),
            secret_needs=_strings(value["secret_needs"], "secret needs"),
            isolation_profile=_text(value["isolation_profile"], "isolation profile", 128,
                                    pattern=_IDENTIFIER),
            migration_policy=_choice(value["migration_policy"], {"none", "compatible", "required"},
                                     "migration policy"),
            uninstall_policy=_choice(value["uninstall_policy"], {"retain_records", "block_if_bound"},
                                     "uninstall policy"),
        )
        provisional = object.__new__(cls)
        for name, item in fields.items():
            object.__setattr__(provisional, name, item)
        object.__setattr__(provisional, "_digest", "")
        digest = sha256(canonical_json(provisional.as_dict())).hexdigest()
        object.__setattr__(provisional, "_digest", digest)
        return provisional

    @property
    def digest(self):
        return self._digest

    @property
    def entrypoint(self):
        return MappingProxyType({"protocol": self.entrypoint_protocol, "name": self.entrypoint_name})

    def as_dict(self):
        return {
            "schema_version": self.schema_version,
            "extension_id": self.extension_id,
            "extension_version": self.extension_version,
            "extension_kind": self.extension_kind,
            "artifact": {"type": self.artifact_type, "sha256": self.artifact_sha256},
            "source": {"kind": self.source_kind, "locator": self.source_locator,
                       "provenance_sha256": self.provenance_sha256},
            "license_expression": self.license_expression,
            "compatibility": {"extension_api": self.extension_api,
                              "framework_min": self.framework_min,
                              "framework_max": self.framework_max,
                              "schema_versions": list(self.schema_versions)},
            "entrypoint": {"protocol": self.entrypoint_protocol, "name": self.entrypoint_name},
            "config_schema": parse_canonical(self._config_schema),
            "input_schema": parse_canonical(self._input_schema),
            "output_schema": parse_canonical(self._output_schema),
            "declared_grants": list(self.declared_grants),
            "declared_resources": list(self.declared_resources),
            "network_needs": list(self.network_needs),
            "filesystem_needs": list(self.filesystem_needs),
            "secret_needs": list(self.secret_needs),
            "isolation_profile": self.isolation_profile,
            "migration_policy": self.migration_policy,
            "uninstall_policy": self.uninstall_policy,
        }


@dataclass(frozen=True, slots=True, init=False)
class ExtensionScope:
    instance_id: str
    environment_id: str | None
    work_id: str | None
    node_id: str | None
    purpose: str | None

    def __new__(cls):
        raise TypeError("Use ExtensionScope.from_mapping")

    @classmethod
    def from_mapping(cls, value):
        value = _exact(value, _SCOPE_FIELDS, "extension scope")
        result = object.__new__(cls)
        object.__setattr__(result, "instance_id", _uuid(value["instance_id"], "instance_id"))
        for name in ("environment_id", "work_id", "node_id"):
            item = value[name]
            object.__setattr__(result, name, None if item is None else _uuid(item, name))
        purpose = value["purpose"]
        if purpose is not None:
            purpose = _choice(purpose, _PURPOSES, "purpose")
        object.__setattr__(result, "purpose", purpose)
        if ((result.node_id is not None and (result.work_id is None or result.environment_id is None))
                or (result.work_id is not None and result.environment_id is None)):
            raise ExtensionContractError("Extension scope hierarchy is incomplete")
        return result

    def as_dict(self):
        return {name: getattr(self, name) for name in
                ("instance_id", "environment_id", "work_id", "node_id", "purpose")}


@dataclass(frozen=True, slots=True, init=False)
class ExtensionInstallation:
    installation_id: str
    manifest_digest: str
    artifact_type: str
    artifact_digest: str
    extension_kind: str
    trust_tier: str
    install_authority: str
    actor_id: str
    installed_at_utc: str
    state: str
    revision: int
    previous_state: str | None
    previous_record_digest: str | None
    verification_refs: tuple[str, ...]
    scan_refs: tuple[str, ...]

    def __new__(cls):
        raise TypeError("Installation records are registry-owned")

    def as_dict(self):
        return {
            "schema_version": "extension-installation-v1",
            "installation_id": self.installation_id,
            "manifest_digest": self.manifest_digest,
            "installed_artifact": {
                "type": self.artifact_type,
                "sha256": self.artifact_digest,
            },
            "extension_kind": self.extension_kind,
            "trust_tier": self.trust_tier,
            "install_authority": self.install_authority,
            "actor_id": self.actor_id,
            "installed_at_utc": self.installed_at_utc,
            "state": self.state,
            "revision": self.revision,
            "previous_state": self.previous_state,
            "previous_record_digest": self.previous_record_digest,
            "verification_refs": list(self.verification_refs),
            "scan_refs": list(self.scan_refs),
        }

    @property
    def digest(self):
        return sha256(canonical_json(self.as_dict())).hexdigest()


@dataclass(frozen=True, slots=True, init=False)
class ExtensionQualification:
    qualification_id: str
    installation_id: str
    installation_revision: int
    installation_record_digest: str
    manifest_digest: str
    artifact_digest: str
    platform_digest: str
    runtime_digest: str
    framework_version: str
    extension_api_version: str
    schema_version_bound: str
    conformance_suite: str
    conformance_version: str
    declared_capabilities_digest: str
    observed_capabilities_digest: str
    results: tuple[tuple[str, str], ...]
    failure_details: tuple[tuple[str, str], ...]
    evidence_refs: tuple[str, ...]
    qualified_scope: ExtensionScope
    evidence_verified: bool
    qualified_at: int
    expires_at: int
    recheck_triggers: tuple[str, ...]
    status: str

    def __new__(cls):
        raise TypeError("Qualification records are registry-owned")

    @property
    def result_map(self):
        return dict(self.results)

    def as_dict(self):
        return {
            "schema_version": "extension-qualification-v1",
            "qualification_id": self.qualification_id,
            "installation_id": self.installation_id,
            "installation_revision": self.installation_revision,
            "installation_record_digest": self.installation_record_digest,
            "manifest_digest": self.manifest_digest,
            "artifact_digest": self.artifact_digest,
            "platform_digest": self.platform_digest,
            "runtime_digest": self.runtime_digest,
            "framework_version": self.framework_version,
            "extension_api_version": self.extension_api_version,
            "schema_version_bound": self.schema_version_bound,
            "conformance_suite": self.conformance_suite,
            "conformance_version": self.conformance_version,
            "declared_capabilities_digest": self.declared_capabilities_digest,
            "observed_capabilities_digest": self.observed_capabilities_digest,
            "results": self.result_map,
            "failure_details": dict(self.failure_details),
            "evidence_refs": list(self.evidence_refs),
            "qualified_scope": self.qualified_scope.as_dict(),
            "evidence_verified": self.evidence_verified,
            "qualified_at": self.qualified_at,
            "expires_at": self.expires_at,
            "recheck_triggers": list(self.recheck_triggers),
            "status": self.status,
        }


@dataclass(frozen=True, slots=True, init=False)
class ExtensionBinding:
    binding_id: str
    installation_id: str
    qualification_id: str
    manifest_digest: str
    extension_kind: str
    trust_tier: str
    scope: ExtensionScope
    config_ref: str
    credential_handle_refs: tuple[str, ...] = field(repr=False)
    grant_refs: tuple[str, ...] = field(repr=False)
    enabled_revision: int
    transmit_authorized: bool = False

    def __new__(cls):
        raise TypeError("Binding records are registry-owned")

    def as_dict(self):
        return {
            "schema_version": "extension-binding-v1",
            "binding_id": self.binding_id,
            "installation_id": self.installation_id,
            "qualification_id": self.qualification_id,
            "manifest_digest": self.manifest_digest,
            "extension_kind": self.extension_kind,
            "trust_tier": self.trust_tier,
            "scope": self.scope.as_dict(),
            "config_ref": self.config_ref,
            "credential_handle_refs": list(self.credential_handle_refs),
            "grant_refs": list(self.grant_refs),
            "enabled_revision": self.enabled_revision,
            "transmit_authorized": self.transmit_authorized,
        }


def _frozen(kind, **fields):
    value = object.__new__(kind)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def validate_installation_inputs(*, manifest, installation_id, actor_id, installed_at_utc,
                                 trust_tier, install_authority):
    if type(manifest) is not ExtensionManifest:
        raise ExtensionContractError("Discovery requires an exact inert manifest")
    _uuid(installation_id, "installation_id")
    _uuid(actor_id, "actor_id")
    _timestamp(installed_at_utc, "installed_at_utc")
    _choice(trust_tier, TRUST_TIERS, "trust tier")
    _choice(install_authority, INSTALL_AUTHORITIES, "install authority")
    critical = manifest.extension_kind in {"storage", "credential_vault"}
    if critical and (trust_tier != "deployment_trusted" or install_authority != "deployment_operator"):
        raise ExtensionContractError("Instance-critical adapter requires the deployment operator")
    if not critical and trust_tier == "deployment_trusted":
        raise ExtensionContractError("Extension kind cannot use that trust tier")
    if trust_tier == "definition_package" and manifest.entrypoint_protocol != "definition-v1":
        raise ExtensionContractError("Definition trust tier requires a code-free definition")
    if manifest.entrypoint_protocol == "definition-v1" and trust_tier != "definition_package":
        raise ExtensionContractError("Code-free definition requires definition trust tier")
    if trust_tier == "managed_provider_runner":
        if manifest.extension_kind != "provider" or manifest.source_kind != "built_in":
            raise ExtensionContractError("Managed runner must be a built-in provider")
        if manifest.entrypoint_protocol != "managed-provider-rpc-v1":
            raise ExtensionContractError("Managed provider runner protocol mismatch")
    elif manifest.entrypoint_protocol == "managed-provider-rpc-v1":
        raise ExtensionContractError("Managed provider protocol requires its trust tier")
    if trust_tier in {"runtime_worker", "managed_provider_runner", "deployment_trusted"} \
            and install_authority != "deployment_operator":
        raise ExtensionContractError("Executable adapters require the deployment operator")


def new_installation(**values):
    validate_installation_inputs(**values)
    manifest = values["manifest"]
    return _frozen(ExtensionInstallation,
        installation_id=values["installation_id"], manifest_digest=manifest.digest,
        artifact_type=manifest.artifact_type, artifact_digest=manifest.artifact_sha256,
        extension_kind=manifest.extension_kind,
        trust_tier=values["trust_tier"], install_authority=values["install_authority"],
        actor_id=values["actor_id"], installed_at_utc=values["installed_at_utc"],
        state="discovered", revision=1, previous_state=None, previous_record_digest=None,
        verification_refs=(), scan_refs=(),
    )


def advance_installation(value, state, *, verification_refs=None, scan_refs=None):
    if type(value) is not ExtensionInstallation:
        raise ExtensionContractError("Expected exact installation")
    transitions = {
        "discovered": {"staged", "failed", "removed"},
        "staged": {"verified", "failed", "removed"},
        "verified": {"qualified", "failed", "removed"},
        "qualified": {"enabled", "suspended", "revoked", "removed"},
        "enabled": {"suspended", "revoked"},
        "suspended": {"enabled", "revoked", "removed"},
        "failed": {"removed"},
        "revoked": {"removed"},
        "removed": set(),
    }
    if state not in transitions[value.state]:
        raise ExtensionContractError("Invalid extension lifecycle transition")
    verify = value.verification_refs if verification_refs is None else _digests(
        verification_refs, "verification refs", required=state == "verified")
    scans = value.scan_refs if scan_refs is None else _digests(
        scan_refs, "scan refs", required=state == "verified")
    return _frozen(ExtensionInstallation,
        installation_id=value.installation_id, manifest_digest=value.manifest_digest,
        artifact_type=value.artifact_type, artifact_digest=value.artifact_digest,
        extension_kind=value.extension_kind,
        trust_tier=value.trust_tier, install_authority=value.install_authority,
        actor_id=value.actor_id, installed_at_utc=value.installed_at_utc,
        state=state, revision=value.revision + 1, previous_state=value.state,
        previous_record_digest=value.digest,
        verification_refs=verify, scan_refs=scans,
    )


def validate_results(value):
    value = _exact(value, frozenset(MANDATORY_QUALIFICATION_CHECKS), "qualification results")
    return tuple((name, _choice(value[name], QUALIFICATION_RESULTS, name))
                 for name in MANDATORY_QUALIFICATION_CHECKS)


def digest_ref(value, label):
    return _digest(value, label)


def id_ref(value, label):
    return _uuid(value, label)


def digest_refs(value, label, *, required=False):
    return _digests(value, label, required=required)


def capability_digest(manifest):
    if type(manifest) is not ExtensionManifest:
        raise ExtensionContractError("Capability digest requires an exact manifest")
    value = {
        "declared_grants": list(manifest.declared_grants),
        "declared_resources": list(manifest.declared_resources),
        "network_needs": list(manifest.network_needs),
        "filesystem_needs": list(manifest.filesystem_needs),
        "secret_needs": list(manifest.secret_needs),
        "isolation_profile": manifest.isolation_profile,
    }
    return sha256(canonical_json(value)).hexdigest()


def _failure_details(value, pairs):
    failed = {name for name, outcome in pairs if outcome != "passed"}
    if type(value) is not dict or set(value) != failed:
        raise ExtensionContractError("Failure details must exactly explain non-passing checks")
    return tuple(
        (name, _text(value[name], f"{name} failure code", 128, pattern=_FAILURE_CODE))
        for name in MANDATORY_QUALIFICATION_CHECKS if name in failed
    )


def _epoch(value, label, *, allow_zero=True):
    minimum = 0 if allow_zero else 1
    if type(value) is not int or not minimum <= value <= MAX_INTEGER:
        raise ExtensionContractError(f"{label} must be a bounded epoch second")
    return value


def new_qualification(*, qualification_id, installation, platform_digest, runtime_digest,
                      framework_version, extension_api_version, schema_version_bound,
                      conformance_suite, conformance_version, declared_capabilities_digest,
                      observed_capabilities_digest, results, failure_details, evidence_refs,
                      qualified_scope, evidence_verified, qualified_at, expires_at,
                      recheck_triggers, status):
    if type(installation) is not ExtensionInstallation or installation.state != "verified":
        raise ExtensionContractError("Qualification requires an exact verified installation")
    if type(qualified_scope) is not ExtensionScope:
        raise ExtensionContractError("Qualification requires an exact scope")
    status = _choice(status, {"qualified", "failed"}, "qualification status")
    pairs = validate_results(results) if type(results) is dict else tuple(results)
    if (len(pairs) != len(MANDATORY_QUALIFICATION_CHECKS)
            or tuple(name for name, _ in pairs) != MANDATORY_QUALIFICATION_CHECKS
            or any(value not in QUALIFICATION_RESULTS for _, value in pairs)):
        raise ExtensionContractError("Qualification results are not exact")
    if type(evidence_verified) is not bool:
        raise ExtensionContractError("Evidence verification state must be explicit")
    details = _failure_details(failure_details, pairs)
    qualified_time = _epoch(qualified_at, "qualified_at")
    expiry = _epoch(expires_at, "expires_at", allow_zero=False)
    if (expiry <= qualified_time
            or expiry - qualified_time > MAX_QUALIFICATION_TTL_SECONDS):
        raise ExtensionContractError("Qualification expiry must be within seven days")
    if type(recheck_triggers) not in (tuple, list):
        raise ExtensionContractError("Qualification recheck triggers are not exact")
    triggers = tuple(recheck_triggers)
    if triggers != QUALIFICATION_RECHECK_TRIGGERS:
        raise ExtensionContractError("Qualification recheck triggers are not exact")
    actually_passed = evidence_verified and all(value == "passed" for _, value in pairs)
    if (status == "qualified") != actually_passed:
        raise ExtensionContractError("Qualification status contradicts mandatory results")
    return _frozen(
        ExtensionQualification,
        qualification_id=id_ref(qualification_id, "qualification_id"),
        installation_id=installation.installation_id,
        installation_revision=positive_revision(installation.revision),
        installation_record_digest=installation.digest,
        manifest_digest=digest_ref(installation.manifest_digest, "manifest digest"),
        artifact_digest=digest_ref(installation.artifact_digest, "artifact digest"),
        platform_digest=digest_ref(platform_digest, "platform digest"),
        runtime_digest=digest_ref(runtime_digest, "runtime digest"),
        framework_version=_version(framework_version, "framework version"),
        extension_api_version=_version(extension_api_version, "extension API version"),
        schema_version_bound=_text(schema_version_bound, "schema version", 128),
        conformance_suite=_text(
            conformance_suite, "conformance suite", 128, pattern=_IDENTIFIER,
        ),
        conformance_version=_version(conformance_version, "conformance version"),
        declared_capabilities_digest=digest_ref(
            declared_capabilities_digest, "declared capabilities digest",
        ),
        observed_capabilities_digest=digest_ref(
            observed_capabilities_digest, "observed capabilities digest",
        ),
        results=pairs,
        failure_details=details,
        evidence_refs=digest_refs(evidence_refs, "qualification evidence", required=True),
        qualified_scope=qualified_scope,
        evidence_verified=evidence_verified,
        qualified_at=qualified_time,
        expires_at=expiry,
        recheck_triggers=triggers,
        status=status,
    )


def new_binding(*, binding_id, installation, qualification, scope, config_ref,
                credential_handle_refs, grant_refs, enabled_revision):
    if (type(installation) is not ExtensionInstallation or installation.state != "enabled"
            or type(qualification) is not ExtensionQualification
            or qualification.status != "qualified"
            or qualification.installation_id != installation.installation_id):
        raise ExtensionContractError("Binding requires matching enabled qualification")
    if type(scope) is not ExtensionScope or scope != qualification.qualified_scope:
        raise ExtensionContractError("Binding exceeds or differs from qualified scope")
    return _frozen(
        ExtensionBinding,
        binding_id=id_ref(binding_id, "binding_id"),
        installation_id=installation.installation_id,
        qualification_id=qualification.qualification_id,
        manifest_digest=installation.manifest_digest,
        extension_kind=installation.extension_kind,
        trust_tier=installation.trust_tier,
        scope=scope,
        config_ref=digest_ref(config_ref, "config ref"),
        credential_handle_refs=digest_refs(credential_handle_refs, "credential handle refs"),
        grant_refs=digest_refs(grant_refs, "grant refs"),
        enabled_revision=positive_revision(enabled_revision),
        transmit_authorized=False,
    )


def compatible(manifest, *, framework_version, extension_api_version, schema_version):
    framework = _version(framework_version, "framework version")
    extension_api = _version(extension_api_version, "extension API version")
    schema = _text(schema_version, "schema version", 128)
    if extension_api != manifest.extension_api:
        return False, "extension_api"
    if not _version_tuple(manifest.framework_min) <= _version_tuple(framework) <= \
            _version_tuple(manifest.framework_max):
        return False, "framework"
    if schema not in manifest.schema_versions:
        return False, "schema"
    return True, None


def validate_registry_context(*, framework_version, extension_api_version, schema_version,
                              runtime_digest, platform_digest):
    return (
        _version(framework_version, "framework version"),
        _version(extension_api_version, "extension API version"),
        _text(schema_version, "schema version", 128),
        _digest(runtime_digest, "runtime digest"),
        _digest(platform_digest, "platform digest"),
    )


def positive_revision(value):
    if type(value) is not int or not 1 <= value <= MAX_INTEGER:
        raise ExtensionContractError("Revision must be a bounded positive integer")
    return value
