"""Pure T087 extension contracts; no extension code, network, or provider is run."""

from dataclasses import FrozenInstanceError
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator

from app.domain.events import EVENT_TYPES, event_metadata
from app.extensions import (
    EXTENSION_KINDS,
    ExtensionBinding,
    ExtensionContractError,
    ExtensionManifest,
    ExtensionRegistry,
    ExtensionScope,
    RuntimeBoundaryUnavailable,
    extension_schemas,
)


ROOT = Path(__file__).resolve().parents[2] / "schemas" / "v1" / "extensions"
REPOSITORY = Path(__file__).resolve().parents[2]
STAMP = "2026-09-08T00:00:00.000000Z"
HASH = "a" * 64
DEPLOY_AUTH = object()
OWNER_AUTH = object()
BROWSER_AUTH = object()
MODEL_AUTH = object()


def fixture_authority(request, action, installation):
    assert action in {"stage", "bind", "suspend", "revoke", "remove"}
    assert installation.installation_id
    if request is DEPLOY_AUTH:
        return "deployment_operator"
    if request is OWNER_AUTH:
        return "product_owner"
    return None


class FixtureVerifier:
    def verify_installation(self, manifest_value, installation, verification_refs, scan_refs):
        return (
            type(manifest_value) is ExtensionManifest
            and installation.manifest_digest == manifest_value.digest
            and verification_refs == ("d" * 64,)
            and scan_refs == ("e" * 64,)
        )

    def verify_qualification(self, manifest_value, installation, qualification_context):
        return (
            type(manifest_value) is ExtensionManifest
            and installation.state == "verified"
            and qualification_context["evidence_refs"] == ["1" * 64]
            and qualification_context["platform_digest"] == "f" * 64
            and qualification_context["conformance_suite"] == "deeptwin-extension-v1"
            and qualification_context["conformance_version"] == "1.0.0"
        )

    def verify_binding(self, manifest_value, installation, qualification, binding_context):
        return (
            type(manifest_value) is ExtensionManifest
            and installation.state in {"qualified", "enabled"}
            and qualification.status == "qualified"
            and binding_context["config_ref"] == "2" * 64
            and binding_context["declared_grants"] == manifest_value.declared_grants
            and binding_context["secret_needs"] == manifest_value.secret_needs
            and bool(binding_context["grant_refs"]) == bool(manifest_value.declared_grants)
            and bool(binding_context["credential_handle_refs"]) == bool(manifest_value.secret_needs)
        )


class RejectingVerifier:
    def verify_installation(self, *_args):
        return False

    def verify_qualification(self, *_args):
        return False

    def verify_binding(self, *_args):
        return False


class QualificationRejectingVerifier(FixtureVerifier):
    def verify_qualification(self, *_args):
        return False


class BindingRejectingVerifier(FixtureVerifier):
    def verify_binding(self, *_args):
        return False


class RevocableBindingVerifier(FixtureVerifier):
    active = True

    def verify_binding(self, *args):
        return self.active and super().verify_binding(*args)


def identifier():
    return str(uuid4())


def manifest(*, kind="tool", source_kind="third_party", artifact_digest=HASH,
             protocol="worker-json-v1", uninstall_policy="retain_records",
             declared_grants=(), secret_needs=()):
    artifact_type = "definition" if protocol == "definition-v1" else "package"
    return ExtensionManifest.from_mapping({
        "schema_version": "extension-manifest-v1",
        "extension_id": "org.example.safe-tool",
        "extension_version": "1.2.3",
        "extension_kind": kind,
        "artifact": {
            "type": artifact_type,
            "sha256": artifact_digest,
        },
        "source": {
            "kind": source_kind,
            "locator": "https://example.invalid/extensions/safe-tool/1.2.3",
            "provenance_sha256": "b" * 64,
        },
        "license_expression": "Apache-2.0",
        "compatibility": {
            "extension_api": "1.0.0",
            "framework_min": "0.1.0",
            "framework_max": "0.1.99",
            "schema_versions": ["domain-v1"],
        },
        "entrypoint": {
            "protocol": protocol,
            "name": "main",
        },
        "config_schema": {"type": "object", "additionalProperties": False},
        "input_schema": {"type": "object", "additionalProperties": False},
        "output_schema": {"type": "object", "additionalProperties": False},
        "declared_grants": list(declared_grants),
        "declared_resources": ["artifact"],
        "network_needs": [],
        "filesystem_needs": [],
        "secret_needs": list(secret_needs),
        "isolation_profile": "runtime-worker-v1",
        "migration_policy": "none",
        "uninstall_policy": uninstall_policy,
    })


def scope():
    return ExtensionScope.from_mapping({
        "instance_id": identifier(),
        "environment_id": identifier(),
        "work_id": identifier(),
        "node_id": identifier(),
        "purpose": "operational",
    })


def instance_scope():
    return ExtensionScope.from_mapping({
        "instance_id": identifier(),
        "environment_id": None,
        "work_id": None,
        "node_id": None,
        "purpose": None,
    })


def passing_results():
    return {
        "permission": "passed",
        "isolation": "passed",
        "egress": "passed",
        "secret": "passed",
        "compatibility": "passed",
    }


def qualification_parameters(results=None):
    results = passing_results() if results is None else results
    return {
        "platform_digest": "f" * 64,
        "results": results,
        "failure_details": {
            name: f"{outcome}_{name}"
            for name, outcome in results.items() if outcome != "passed"
        },
        "evidence_refs": ("1" * 64,),
        "conformance_suite": "deeptwin-extension-v1",
        "conformance_version": "1.0.0",
        "observed_capabilities_digest": "8" * 64,
        "expires_at": 2_000,
    }


def qualified_registry(value=None, *, trust_tier="runtime_worker",
                       authority="deployment_operator", clock=None, verifier=None):
    value = value or manifest()
    clock = [1_000] if clock is None else clock
    registry = ExtensionRegistry(
        framework_version="0.1.7",
        extension_api_version="1.0.0",
        schema_version="domain-v1",
        runtime_digest="c" * 64,
        platform_digest="f" * 64,
        clock=lambda: clock[0],
        evidence_verifier=FixtureVerifier() if verifier is None else verifier,
        authority_verifier=fixture_authority,
    )
    installation = registry.discover(
        value,
        installation_id=identifier(),
        actor_id=identifier(),
        installed_at_utc=STAMP,
        trust_tier=trust_tier,
        install_authority=authority,
    )
    installation = registry.stage(
        installation.installation_id, authority_request=DEPLOY_AUTH,
    )
    installation = registry.verify(
        installation.installation_id,
        verification_refs=("d" * 64,),
        scan_refs=("e" * 64,),
    )
    qualification = registry.qualify(
        installation.installation_id,
        qualification_id=identifier(),
        qualified_scope=scope(),
        **qualification_parameters(),
    )
    return registry, registry.installation(installation.installation_id), qualification


def test_manifest_is_exact_frozen_inert_data_and_supports_all_versioned_kinds():
    assert EXTENSION_KINDS == frozenset({
        "provider", "model_runtime", "tool", "artifact_codec", "lens", "evaluator",
        "storage", "credential_vault", "export_sink",
    })
    value = manifest()
    assert value.extension_kind == "tool"
    assert len(value.digest) == 64
    with pytest.raises(FrozenInstanceError):
        value.extension_kind = "provider"
    body = value.as_dict()
    body["unexpected"] = True
    with pytest.raises(ExtensionContractError, match="exact schema"):
        ExtensionManifest.from_mapping(body)
    with pytest.raises(ExtensionContractError):
        manifest(kind="model_catalog")
    assert not callable(value.entrypoint)
    private = value.as_dict()
    private["source"]["locator"] = "https://user:secret@example.invalid/private"
    private_value = ExtensionManifest.from_mapping(private)
    assert "user:secret" not in repr(private_value)


def test_lifecycle_records_cannot_be_minted_by_calling_public_dataclasses():
    from app.extensions import ExtensionInstallation, ExtensionQualification

    for record_type in (
        ExtensionManifest, ExtensionScope, ExtensionInstallation,
        ExtensionQualification, ExtensionBinding,
    ):
        with pytest.raises(TypeError):
            record_type()


def test_registry_requires_trusted_evidence_and_authority_verifiers():
    context = {
        "framework_version": "0.1.7",
        "extension_api_version": "1.0.0",
        "schema_version": "domain-v1",
        "runtime_digest": "c" * 64,
        "platform_digest": "f" * 64,
        "clock": lambda: 1_000,
    }
    with pytest.raises(TypeError, match="trusted evidence verifier"):
        ExtensionRegistry(
            **context, evidence_verifier=object(), authority_verifier=fixture_authority,
        )
    with pytest.raises(TypeError, match="trusted authority verifier"):
        ExtensionRegistry(
            **context, evidence_verifier=FixtureVerifier(), authority_verifier=None,
        )


def test_claimed_role_strings_are_not_action_authority_capabilities():
    registry = ExtensionRegistry(
        framework_version="0.1.7", extension_api_version="1.0.0",
        schema_version="domain-v1", runtime_digest="c" * 64,
        platform_digest="f" * 64, clock=lambda: 1_000,
        evidence_verifier=FixtureVerifier(), authority_verifier=fixture_authority,
    )
    item = registry.discover(
        manifest(), installation_id=identifier(), actor_id=identifier(),
        installed_at_utc=STAMP, trust_tier="runtime_worker",
        install_authority="deployment_operator",
    )
    with pytest.raises(ExtensionContractError, match="authority could not be verified"):
        registry.stage(item.installation_id, authority_request="deployment_operator")
    assert registry.installation(item.installation_id).state == "discovered"
    assert registry.stage(item.installation_id, authority_request=DEPLOY_AUTH).state == "staged"


def test_discovery_never_executes_or_enables_even_for_builtin_source():
    calls = []
    value = manifest(source_kind="built_in")
    registry = ExtensionRegistry(
        framework_version="0.1.7", extension_api_version="1.0.0",
        schema_version="domain-v1", runtime_digest="c" * 64,
        platform_digest="f" * 64, clock=lambda: 1_000,
        evidence_verifier=RejectingVerifier(),
        authority_verifier=fixture_authority,
    )
    discovered = registry.discover(
        value, installation_id=identifier(), actor_id=identifier(),
        installed_at_utc=STAMP, trust_tier="runtime_worker",
        install_authority="deployment_operator",
    )
    assert discovered.state == "discovered"
    assert calls == []
    with pytest.raises(ExtensionContractError, match="qualified and enabled"):
        registry.bind(
            discovered.installation_id,
            qualification_id=identifier(),
            binding_id=identifier(),
            scope=scope(),
            config_ref="2" * 64,
            authority_request=OWNER_AUTH,
        )
    with pytest.raises(RuntimeBoundaryUnavailable):
        registry.prepare_dispatch(identifier())


@pytest.mark.parametrize("kind", ["storage", "credential_vault"])
@pytest.mark.parametrize("authority", ["product_owner", "work", "model", "browser_import"])
def test_instance_critical_adapters_cannot_be_installed_from_product_or_work(kind, authority):
    registry = ExtensionRegistry(
        framework_version="0.1.7", extension_api_version="1.0.0",
        schema_version="domain-v1", runtime_digest="c" * 64,
        platform_digest="f" * 64, clock=lambda: 1_000,
        evidence_verifier=FixtureVerifier(),
        authority_verifier=fixture_authority,
    )
    value = manifest(kind=kind, source_kind="operator_deployment",
                     protocol="deployment-port-v1")
    with pytest.raises(ExtensionContractError, match="deployment operator"):
        registry.discover(
            value, installation_id=identifier(), actor_id=identifier(),
            installed_at_utc=STAMP, trust_tier="deployment_trusted",
            install_authority=authority,
        )


def test_instance_critical_adapter_requires_operator_action_and_instance_only_scope():
    registry = ExtensionRegistry(
        framework_version="0.1.7", extension_api_version="1.0.0",
        schema_version="domain-v1", runtime_digest="c" * 64,
        platform_digest="f" * 64, clock=lambda: 1_000,
        evidence_verifier=FixtureVerifier(), authority_verifier=fixture_authority,
    )
    item = registry.discover(
        manifest(kind="storage", source_kind="operator_deployment",
                 protocol="deployment-port-v1"),
        installation_id=identifier(), actor_id=identifier(), installed_at_utc=STAMP,
        trust_tier="deployment_trusted", install_authority="deployment_operator",
    )
    with pytest.raises(ExtensionContractError, match="deployment operator"):
        registry.stage(item.installation_id, authority_request=OWNER_AUTH)
    registry.stage(item.installation_id, authority_request=DEPLOY_AUTH)
    registry.verify(
        item.installation_id, verification_refs=("d" * 64,), scan_refs=("e" * 64,),
    )
    with pytest.raises(ExtensionContractError, match="instance-scoped"):
        registry.qualify(
            item.installation_id, qualification_id=identifier(), qualified_scope=scope(),
            **qualification_parameters(),
        )
    qualification = registry.qualify(
        item.installation_id, qualification_id=identifier(), qualified_scope=instance_scope(),
        **qualification_parameters(),
    )
    assert qualification.status == "qualified"


def test_trust_tiers_are_kind_and_source_bound():
    with pytest.raises(ExtensionContractError, match="trust tier"):
        qualified_registry(manifest(kind="tool"), trust_tier="deployment_trusted")
    with pytest.raises(ExtensionContractError, match="built-in provider"):
        qualified_registry(
            manifest(kind="provider", source_kind="third_party",
                     protocol="managed-provider-rpc-v1"),
            trust_tier="managed_provider_runner",
        )
    registry, installation, qualification = qualified_registry(
        manifest(kind="provider", source_kind="built_in",
                 protocol="managed-provider-rpc-v1"),
        trust_tier="managed_provider_runner",
    )
    assert installation.state == "qualified"
    assert qualification.status == "qualified"


def test_installation_revisions_form_an_immutable_digest_chain():
    registry, installation, qualification = qualified_registry()
    history = registry.installation_history(installation.installation_id)
    assert [item.state for item in history] == [
        "discovered", "staged", "verified", "qualified",
    ]
    assert [item.revision for item in history] == [1, 2, 3, 4]
    assert history[0].previous_record_digest is None
    for previous, current in zip(history, history[1:]):
        assert current.previous_record_digest == previous.digest
        assert current.previous_state == previous.state
    assert qualification.installation_revision == history[2].revision
    assert qualification.installation_record_digest == history[2].digest
    assert history[0].as_dict()["installed_artifact"] == {
        "type": "package", "sha256": HASH,
    }


def test_qualification_records_conformance_capabilities_expiry_and_recheck_triggers():
    _, _, qualification = qualified_registry()
    body = qualification.as_dict()
    assert body["conformance_suite"] == "deeptwin-extension-v1"
    assert body["conformance_version"] == "1.0.0"
    assert body["observed_capabilities_digest"] == "8" * 64
    assert len(body["declared_capabilities_digest"]) == 64
    assert body["failure_details"] == {}
    assert body["qualified_at"] == 1_000 and body["expires_at"] == 2_000
    assert body["recheck_triggers"] == [
        "artifact_change", "framework_change", "permission_change", "platform_change",
        "runtime_change", "schema_change", "expiry",
    ]


@pytest.mark.parametrize("field", [
    "permission", "isolation", "egress", "secret", "compatibility",
])
@pytest.mark.parametrize("outcome", ["failed", "unknown"])
def test_mandatory_failure_or_unknown_can_never_qualify(field, outcome):
    value = manifest()
    registry = ExtensionRegistry(
        framework_version="0.1.7", extension_api_version="1.0.0",
        schema_version="domain-v1", runtime_digest="c" * 64,
        platform_digest="f" * 64, clock=lambda: 1_000,
        evidence_verifier=FixtureVerifier(),
        authority_verifier=fixture_authority,
    )
    item = registry.discover(
        value, installation_id=identifier(), actor_id=identifier(),
        installed_at_utc=STAMP, trust_tier="runtime_worker",
        install_authority="deployment_operator",
    )
    registry.stage(item.installation_id, authority_request=DEPLOY_AUTH)
    registry.verify(item.installation_id, verification_refs=("d" * 64,), scan_refs=("e" * 64,))
    results = passing_results()
    results[field] = outcome
    qualification = registry.qualify(
        item.installation_id, qualification_id=identifier(), qualified_scope=scope(),
        **qualification_parameters(results),
    )
    assert qualification.status == "failed"
    assert registry.installation(item.installation_id).state == "failed"
    with pytest.raises(ExtensionContractError, match="qualified and enabled"):
        registry.bind(
            item.installation_id, qualification_id=qualification.qualification_id,
            binding_id=identifier(), scope=qualification.qualified_scope,
            config_ref="2" * 64,
            authority_request=OWNER_AUTH,
        )


def test_binding_requires_exact_qualification_scope_and_current_bytes_and_runtime():
    registry, installation, qualification = qualified_registry(
        manifest(declared_grants=("artifact.read",))
    )
    wrong = ExtensionScope.from_mapping({
        **qualification.qualified_scope.as_dict(),
        "work_id": identifier(),
    })
    with pytest.raises(ExtensionContractError, match="qualified scope"):
        registry.bind(
            installation.installation_id,
            qualification_id=qualification.qualification_id,
            binding_id=identifier(), scope=wrong, config_ref="2" * 64,
            authority_request=OWNER_AUTH,
        )
    binding = registry.bind(
        installation.installation_id,
        qualification_id=qualification.qualification_id,
        binding_id=identifier(), scope=qualification.qualified_scope,
        config_ref="2" * 64,
        credential_handle_refs=(), grant_refs=("3" * 64,),
        authority_request=OWNER_AUTH,
    )
    assert isinstance(binding, ExtensionBinding)
    assert binding.as_dict()["schema_version"] == "extension-binding-v1"
    assert qualification.as_dict()["schema_version_bound"] == "domain-v1"
    assert registry.installation(installation.installation_id).state == "enabled"

    registry.observe_runtime(runtime_digest="4" * 64)
    with pytest.raises(ExtensionContractError, match="requalification"):
        registry.binding(binding.binding_id)
    registry.observe_runtime(runtime_digest="c" * 64)
    with pytest.raises(ExtensionContractError, match="requalification"):
        registry.binding(binding.binding_id)
    with pytest.raises(RuntimeBoundaryUnavailable):
        registry.prepare_dispatch(binding.binding_id)


def test_platform_change_and_expiry_invalidate_qualification_without_mutating_state():
    platform_registry, installation, qualification = qualified_registry()
    platform_registry.observe_runtime(runtime_digest="c" * 64, platform_digest="9" * 64)
    with pytest.raises(ExtensionContractError, match="requalification"):
        platform_registry.bind(
            installation.installation_id, qualification_id=qualification.qualification_id,
            binding_id=identifier(), scope=qualification.qualified_scope,
            config_ref="2" * 64, authority_request=OWNER_AUTH,
        )
    assert platform_registry.events[-1]["public_metadata"]["reason_code"] == "platform"
    assert platform_registry.installation(installation.installation_id).state == "qualified"

    clock = [1_000]
    expiry_registry, expiry_installation, expiry_qualification = qualified_registry(clock=clock)
    clock[0] = 2_000
    with pytest.raises(ExtensionContractError, match="requalification"):
        expiry_registry.bind(
            expiry_installation.installation_id,
            qualification_id=expiry_qualification.qualification_id,
            binding_id=identifier(), scope=expiry_qualification.qualified_scope,
            config_ref="2" * 64, authority_request=OWNER_AUTH,
        )
    assert expiry_registry.events[-1]["public_metadata"]["reason_code"] == "expired"
    assert expiry_registry.installation(expiry_installation.installation_id).state == "qualified"


def test_qualification_expiry_cannot_be_effectively_permanent():
    value = manifest()
    registry = ExtensionRegistry(
        framework_version="0.1.7", extension_api_version="1.0.0",
        schema_version="domain-v1", runtime_digest="c" * 64,
        platform_digest="f" * 64, clock=lambda: 1_000,
        evidence_verifier=FixtureVerifier(), authority_verifier=fixture_authority,
    )
    item = registry.discover(
        value, installation_id=identifier(), actor_id=identifier(), installed_at_utc=STAMP,
        trust_tier="runtime_worker", install_authority="deployment_operator",
    )
    registry.stage(item.installation_id, authority_request=DEPLOY_AUTH)
    registry.verify(item.installation_id, verification_refs=("d" * 64,), scan_refs=("e" * 64,))
    parameters = qualification_parameters()
    parameters["expires_at"] = 1_000 + 604_801
    with pytest.raises(ExtensionContractError, match="within seven days"):
        registry.qualify(
            item.installation_id, qualification_id=identifier(), qualified_scope=scope(),
            **parameters,
        )


def test_invalid_binding_input_is_atomic_and_can_be_retried():
    registry, installation, qualification = qualified_registry()
    binding_id = identifier()
    events_before = registry.events
    with pytest.raises(ExtensionContractError, match="config ref"):
        registry.bind(
            installation.installation_id,
            qualification_id=qualification.qualification_id,
            binding_id=binding_id, scope=qualification.qualified_scope,
            config_ref="not-a-digest", authority_request=OWNER_AUTH,
        )
    assert registry.installation(installation.installation_id).state == "qualified"
    assert registry.events == events_before

    binding = registry.bind(
        installation.installation_id,
        qualification_id=qualification.qualification_id,
        binding_id=binding_id, scope=qualification.qualified_scope,
        config_ref="2" * 64, authority_request=OWNER_AUTH,
    )
    assert binding.binding_id == binding_id
    assert registry.installation(installation.installation_id).state == "enabled"


def test_binding_cannot_expand_declared_grants_or_secret_capabilities():
    registry, installation, qualification = qualified_registry()
    for extra in (
        {"grant_refs": ("3" * 64,)},
        {"credential_handle_refs": ("4" * 64,)},
    ):
        with pytest.raises(ExtensionContractError, match="undeclared"):
            registry.bind(
                installation.installation_id,
                qualification_id=qualification.qualification_id,
                binding_id=identifier(), scope=qualification.qualified_scope,
                config_ref="2" * 64, authority_request=OWNER_AUTH, **extra,
            )
    assert registry.installation(installation.installation_id).state == "qualified"

    declared = manifest(
        declared_grants=("artifact.read",), secret_needs=("provider.token",),
    )
    declared_registry, declared_installation, declared_qualification = qualified_registry(declared)
    with pytest.raises(ExtensionContractError, match="missing declared"):
        declared_registry.bind(
            declared_installation.installation_id,
            qualification_id=declared_qualification.qualification_id,
            binding_id=identifier(), scope=declared_qualification.qualified_scope,
            config_ref="2" * 64, authority_request=OWNER_AUTH,
        )
    binding = declared_registry.bind(
        declared_installation.installation_id,
        qualification_id=declared_qualification.qualification_id,
        binding_id=identifier(), scope=declared_qualification.qualified_scope,
        config_ref="2" * 64, grant_refs=("3" * 64,),
        credential_handle_refs=("4" * 64,), authority_request=OWNER_AUTH,
    )
    assert "3" * 64 not in repr(binding) and "4" * 64 not in repr(binding)


def test_claimed_binding_references_need_trusted_verifier_confirmation():
    registry, installation, qualification = qualified_registry(
        manifest(declared_grants=("artifact.read",)), verifier=BindingRejectingVerifier(),
    )
    with pytest.raises(ExtensionContractError, match="not authorized"):
        registry.bind(
            installation.installation_id, qualification_id=qualification.qualification_id,
            binding_id=identifier(), scope=qualification.qualified_scope,
            config_ref="2" * 64, grant_refs=("3" * 64,), authority_request=OWNER_AUTH,
        )
    assert registry.installation(installation.installation_id).state == "qualified"


def test_active_binding_rechecks_current_reference_authorization_and_capabilities():
    verifier = RevocableBindingVerifier()
    registry, installation, qualification = qualified_registry(
        manifest(declared_grants=("artifact.read",)), verifier=verifier,
    )
    binding = registry.bind(
        installation.installation_id, qualification_id=qualification.qualification_id,
        binding_id=identifier(), scope=qualification.qualified_scope,
        config_ref="2" * 64, grant_refs=("3" * 64,), authority_request=OWNER_AUTH,
    )
    assert registry.binding(binding.binding_id) == binding

    verifier.active = False
    with pytest.raises(ExtensionContractError, match="requalification"):
        registry.binding(binding.binding_id)
    assert registry.events[-1]["event_type"] == "extension.compatibility_failed"
    assert registry.events[-1]["public_metadata"]["reason_code"] == "permission"

    verifier.active = True
    with pytest.raises(ExtensionContractError, match="requalification"):
        registry.binding(binding.binding_id)


def test_export_binding_never_itself_authorizes_transmission():
    registry, installation, qualification = qualified_registry(manifest(kind="export_sink"))
    binding = registry.bind(
        installation.installation_id,
        qualification_id=qualification.qualification_id,
        binding_id=identifier(), scope=qualification.qualified_scope,
        config_ref="2" * 64,
        authority_request=OWNER_AUTH,
    )
    assert binding.transmit_authorized is False
    with pytest.raises(ExtensionContractError, match="target-bound export confirmation"):
        registry.authorize_export(binding.binding_id, target_confirmation_ref=None)
    descriptor = registry.authorize_export(
        binding.binding_id, target_confirmation_ref="5" * 64,
    )
    assert descriptor == {
        "binding_id": binding.binding_id,
        "target_confirmation_ref": "5" * 64,
        "dispatch_ready": False,
    }


def test_builtin_and_third_party_sources_emit_the_same_lifecycle_gates():
    sequences = []
    for source_kind in ("built_in", "third_party"):
        registry, installation, qualification = qualified_registry(
            manifest(source_kind=source_kind)
        )
        registry.bind(
            installation.installation_id,
            qualification_id=qualification.qualification_id,
            binding_id=identifier(), scope=qualification.qualified_scope,
            config_ref="2" * 64,
            authority_request=OWNER_AUTH,
        )
        sequences.append(tuple(event["event_type"] for event in registry.events))
    assert sequences[0] == sequences[1] == (
        "extension.discovered", "extension.staged", "extension.verified",
        "extension.qualified", "extension.enabled", "extension.binding_changed",
    )


def test_claimed_pass_results_cannot_self_qualify_without_trusted_evidence_verifier():
    registry = ExtensionRegistry(
        framework_version="0.1.7", extension_api_version="1.0.0",
        schema_version="domain-v1", runtime_digest="c" * 64,
        platform_digest="f" * 64, clock=lambda: 1_000,
        evidence_verifier=RejectingVerifier(),
        authority_verifier=fixture_authority,
    )
    item = registry.discover(
        manifest(), installation_id=identifier(), actor_id=identifier(),
        installed_at_utc=STAMP, trust_tier="runtime_worker",
        install_authority="deployment_operator",
    )
    registry.stage(item.installation_id, authority_request=DEPLOY_AUTH)
    failed = registry.verify(
        item.installation_id, verification_refs=("d" * 64,), scan_refs=("e" * 64,),
    )
    assert failed.state == "failed"
    assert failed.verification_refs == ("d" * 64,)
    assert failed.scan_refs == ("e" * 64,)
    assert failed.previous_record_digest == registry.installation_history(
        item.installation_id,
    )[-2].digest
    assert registry.events[-1]["event_type"] == "extension.failed"


def test_claimed_qualification_results_fail_when_evidence_verifier_rejects_them():
    registry = ExtensionRegistry(
        framework_version="0.1.7", extension_api_version="1.0.0",
        schema_version="domain-v1", runtime_digest="c" * 64,
        platform_digest="f" * 64, clock=lambda: 1_000,
        evidence_verifier=QualificationRejectingVerifier(),
        authority_verifier=fixture_authority,
    )
    item = registry.discover(
        manifest(), installation_id=identifier(), actor_id=identifier(),
        installed_at_utc=STAMP, trust_tier="runtime_worker",
        install_authority="deployment_operator",
    )
    registry.stage(item.installation_id, authority_request=DEPLOY_AUTH)
    verified = registry.verify(
        item.installation_id, verification_refs=("d" * 64,), scan_refs=("e" * 64,),
    )
    assert verified.state == "verified"
    qualification = registry.qualify(
        item.installation_id, qualification_id=identifier(), qualified_scope=scope(),
        **qualification_parameters(),
    )
    assert qualification.status == "failed"
    assert qualification.evidence_verified is False
    assert registry.installation(item.installation_id).state == "failed"


def test_untrusted_discovery_channel_cannot_stage_or_bind_a_definition():
    value = manifest(kind="lens", source_kind="third_party", protocol="definition-v1")
    registry = ExtensionRegistry(
        framework_version="0.1.7", extension_api_version="1.0.0",
        schema_version="domain-v1", runtime_digest="c" * 64,
        platform_digest="f" * 64, clock=lambda: 1_000,
        evidence_verifier=FixtureVerifier(),
        authority_verifier=fixture_authority,
    )
    item = registry.discover(
        value, installation_id=identifier(), actor_id=identifier(),
        installed_at_utc=STAMP, trust_tier="definition_package",
        install_authority="browser_import",
    )
    with pytest.raises(ExtensionContractError, match="authority could not be verified"):
        registry.stage(item.installation_id, authority_request=BROWSER_AUTH)
    registry.stage(item.installation_id, authority_request=OWNER_AUTH)
    registry.verify(item.installation_id, verification_refs=("d" * 64,), scan_refs=("e" * 64,))
    qualification = registry.qualify(
        item.installation_id, qualification_id=identifier(), qualified_scope=scope(),
        **qualification_parameters(),
    )
    with pytest.raises(ExtensionContractError, match="authority could not be verified"):
        registry.bind(
            item.installation_id, qualification_id=qualification.qualification_id,
            binding_id=identifier(), scope=qualification.qualified_scope,
            config_ref="2" * 64, authority_request=MODEL_AUTH,
        )


def test_same_extension_version_cannot_be_rebound_to_changed_manifest_bytes():
    registry = ExtensionRegistry(
        framework_version="0.1.7", extension_api_version="1.0.0",
        schema_version="domain-v1", runtime_digest="c" * 64,
        platform_digest="f" * 64, clock=lambda: 1_000,
        evidence_verifier=FixtureVerifier(),
        authority_verifier=fixture_authority,
    )
    first = manifest()
    registry.discover(
        first, installation_id=identifier(), actor_id=identifier(),
        installed_at_utc=STAMP, trust_tier="runtime_worker",
        install_authority="deployment_operator",
    )
    changed = manifest(artifact_digest="9" * 64)
    with pytest.raises(ExtensionContractError, match="version is already bound"):
        registry.discover(
            changed, installation_id=identifier(), actor_id=identifier(),
            installed_at_utc=STAMP, trust_tier="runtime_worker",
            install_authority="deployment_operator",
        )


def test_lifecycle_actions_require_verified_authority_and_respect_uninstall_policy():
    registry, installation, qualification = qualified_registry(
        manifest(uninstall_policy="block_if_bound")
    )
    registry.bind(
        installation.installation_id, qualification_id=qualification.qualification_id,
        binding_id=identifier(), scope=qualification.qualified_scope,
        config_ref="2" * 64, authority_request=OWNER_AUTH,
    )
    with pytest.raises(ExtensionContractError, match="authority could not be verified"):
        registry.suspend(installation.installation_id, authority_request=MODEL_AUTH)
    registry.suspend(installation.installation_id, authority_request=OWNER_AUTH)
    with pytest.raises(ExtensionContractError, match="authority could not be verified"):
        registry.remove(installation.installation_id, authority_request="product_owner")
    with pytest.raises(ExtensionContractError, match="uninstall policy blocks"):
        registry.remove(installation.installation_id, authority_request=OWNER_AUTH)

    retained, retained_installation, retained_qualification = qualified_registry()
    retained.bind(
        retained_installation.installation_id,
        qualification_id=retained_qualification.qualification_id,
        binding_id=identifier(), scope=retained_qualification.qualified_scope,
        config_ref="2" * 64, authority_request=OWNER_AUTH,
    )
    retained.suspend(retained_installation.installation_id, authority_request=OWNER_AUTH)
    removed = retained.remove(
        retained_installation.installation_id, authority_request=OWNER_AUTH,
    )
    assert removed.state == "removed"


def test_extension_events_are_registered_with_closed_public_metadata():
    expected = {
        "extension.discovered", "extension.staged", "extension.verified",
        "extension.qualified", "extension.enabled", "extension.suspended",
        "extension.failed", "extension.revoked", "extension.removed", "extension.binding_changed",
        "extension.compatibility_failed",
    }
    assert expected <= EVENT_TYPES
    payload = {
        "extension_kind": "tool", "trust_tier": "runtime_worker", "revision": 1,
    }
    assert event_metadata("extension.discovered", payload) == payload
    with pytest.raises(Exception):
        event_metadata("extension.discovered", {**payload, "locator": "private"})


def test_exported_extension_schemas_match_runtime_and_are_closed():
    schemas = extension_schemas()
    assert set(schemas) == {
        "manifest.schema.json", "installation.schema.json",
        "qualification.schema.json", "binding.schema.json",
    }
    for name, schema in schemas.items():
        assert schema == json.loads((ROOT / name).read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False


def test_exported_schemas_reject_core_invalid_isolation_and_scope_hierarchy():
    schemas = extension_schemas()
    invalid_manifest = manifest().as_dict()
    invalid_manifest["isolation_profile"] = "NOT VALID WITH SPACES"
    assert list(Draft202012Validator(
        schemas["manifest.schema.json"],
    ).iter_errors(invalid_manifest))

    _, _, qualification = qualified_registry()
    invalid_qualification = qualification.as_dict()
    invalid_qualification["qualified_scope"] = {
        **invalid_qualification["qualified_scope"],
        "environment_id": None,
        "work_id": identifier(),
    }
    assert list(Draft202012Validator(
        schemas["qualification.schema.json"],
    ).iter_errors(invalid_qualification))


def test_minimal_python_kit_builds_a_core_valid_manifest_without_importing_app():
    script = r'''
import json
from deeptwin_ext import build_manifest, canonical_manifest_bytes

value = build_manifest(
    extension_id="org.example.sdk-tool",
    extension_version="1.0.0",
    extension_kind="tool",
    artifact_type="package",
    artifact_sha256="6" * 64,
    source_kind="third_party",
    source_locator="https://example.invalid/sdk-tool",
    provenance_sha256="7" * 64,
    license_expression="MIT",
    entrypoint_protocol="worker-json-v1",
    entrypoint_name="main",
    isolation_profile="runtime-worker-v1",
)
assert canonical_manifest_bytes(value) == json.dumps(
    value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8")
print(json.dumps(value))
'''
    completed = subprocess.run(
        [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, "
         + repr(str(REPOSITORY / "sdk" / "python")) + ");" + script],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert ExtensionManifest.from_mapping(json.loads(completed.stdout)).extension_id == \
        "org.example.sdk-tool"
    for source in (REPOSITORY / "sdk" / "python" / "deeptwin_ext").glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "from app" not in text and "import app" not in text


def test_inert_examples_are_valid_manifests_and_import_has_no_side_effect(tmp_path):
    examples = REPOSITORY / "examples" / "extensions"
    manifests = sorted(examples.glob("*/manifest.json"))
    assert {path.parent.name for path in manifests} == {"code_free_lens", "pure_text_tool"}
    for path in manifests:
        value = ExtensionManifest.from_mapping(json.loads(path.read_text(encoding="utf-8")))
        assert value.digest
        provenance = path.parent / "provenance.json"
        assert sha256(provenance.read_bytes()).hexdigest() == value.provenance_sha256
        claim = json.loads(provenance.read_text(encoding="utf-8"))
        artifact = path.parent / claim["artifact_path"]
        assert sha256(artifact.read_bytes()).hexdigest() == value.artifact_sha256

    marker = tmp_path / "unexpected-side-effect"
    script = (
        "import importlib.util, pathlib;"
        f"p=pathlib.Path({str(examples / 'pure_text_tool' / 'handler.py')!r});"
        "s=importlib.util.spec_from_file_location('example_handler',p);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        f"assert not pathlib.Path({str(marker)!r}).exists();"
        "assert m.transform_text('Ab C') == 'AB C'"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script], cwd=tmp_path,
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
