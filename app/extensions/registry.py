"""In-memory pure lifecycle coordinator. T018 supplies the future process broker."""

from __future__ import annotations

from types import MappingProxyType

from ..domain.events import event_metadata
from ..domain.refs import MAX_INTEGER
from .contracts import (
    ExtensionBinding,
    ExtensionContractError,
    ExtensionInstallation,
    ExtensionManifest,
    ExtensionQualification,
    ExtensionScope,
    QUALIFICATION_RECHECK_TRIGGERS,
    RuntimeBoundaryUnavailable,
    advance_installation,
    capability_digest,
    compatible,
    digest_ref,
    digest_refs,
    id_ref,
    new_binding,
    new_installation,
    new_qualification,
    positive_revision,
    validate_registry_context,
    validate_results,
)


class ExtensionRegistry:
    """Trusted lifecycle registry; it deliberately has no artifact loader or import hook."""

    def __init__(self, *, framework_version, extension_api_version, schema_version, runtime_digest,
                 platform_digest, clock, evidence_verifier, authority_verifier):
        context = validate_registry_context(
            framework_version=framework_version,
            extension_api_version=extension_api_version,
            schema_version=schema_version,
            runtime_digest=runtime_digest,
            platform_digest=platform_digest,
        )
        (self.framework_version, self.extension_api_version,
         self.schema_version, self.runtime_digest, self.platform_digest) = context
        if not all(callable(getattr(evidence_verifier, name, None)) for name in
                   ("verify_installation", "verify_qualification", "verify_binding")):
            raise TypeError("Extension registry requires a trusted evidence verifier")
        if not callable(authority_verifier):
            raise TypeError("Extension registry requires a trusted authority verifier")
        if not callable(clock):
            raise TypeError("Extension registry requires a trusted clock")
        self._evidence_verifier = evidence_verifier
        self._authority_verifier = authority_verifier
        self._clock = clock
        self._last_now = None
        self._manifests = {}
        self._coordinates = {}
        self._installations = {}
        self._installation_histories = {}
        self._qualifications = {}
        self._bindings = {}
        self._events = []
        self._compatibility_events = set()
        self._invalidated_qualifications = {}
        self._invalidated_bindings = {}

    def _now(self):
        try:
            value = self._clock()
        except Exception as exc:
            raise ExtensionContractError("Trusted extension clock failed") from exc
        if type(value) is not int or not 0 <= value <= MAX_INTEGER:
            raise ExtensionContractError("Trusted extension clock is invalid")
        if self._last_now is not None and value < self._last_now:
            raise ExtensionContractError("Trusted extension clock moved backwards")
        self._last_now = value
        return value

    @property
    def events(self):
        return tuple({"event_type": item["event_type"], "public_metadata":
                      item["public_metadata"].copy()} for item in self._events)

    def _emit(self, event_type, installation, **extra):
        payload = {
            "extension_kind": installation.extension_kind,
            "trust_tier": installation.trust_tier,
            "revision": installation.revision,
            **extra,
        }
        self._events.append({
            "event_type": event_type,
            "public_metadata": event_metadata(event_type, payload),
        })

    def discover(self, manifest, *, installation_id, actor_id, installed_at_utc,
                 trust_tier, install_authority):
        if installation_id in self._installations:
            raise ExtensionContractError("Installation ID already exists")
        installation = new_installation(
            manifest=manifest, installation_id=installation_id, actor_id=actor_id,
            installed_at_utc=installed_at_utc, trust_tier=trust_tier,
            install_authority=install_authority,
        )
        coordinate = (manifest.extension_id, manifest.extension_version)
        previous = self._coordinates.get(coordinate)
        if previous is not None and previous != manifest.digest:
            raise ExtensionContractError("Extension version is already bound to different bytes")
        self._manifests[manifest.digest] = manifest
        self._coordinates[coordinate] = manifest.digest
        self._installations[installation_id] = installation
        self._installation_histories[installation_id] = [installation]
        self._emit("extension.discovered", installation)
        return installation

    def installation(self, installation_id):
        id_ref(installation_id, "installation_id")
        try:
            return self._installations[installation_id]
        except KeyError as exc:
            raise ExtensionContractError("Unknown extension installation") from exc

    def installation_history(self, installation_id):
        self.installation(installation_id)
        return tuple(self._installation_histories[installation_id])

    def _record(self, installation):
        history = self._installation_histories[installation.installation_id]
        if (not history or installation.revision != history[-1].revision + 1
                or installation.previous_record_digest != history[-1].digest):
            raise ExtensionContractError("Extension installation history is not contiguous")
        history.append(installation)
        self._installations[installation.installation_id] = installation
        return installation

    def _advance(self, installation_id, state, **evidence):
        current = self.installation(installation_id)
        changed = advance_installation(current, state, **evidence)
        self._record(changed)
        self._emit(f"extension.{state}", changed)
        return changed

    def _authority(self, request, action, installation):
        try:
            authority = self._authority_verifier(request, action, installation)
        except Exception as exc:
            raise ExtensionContractError("Extension action authority could not be verified") from exc
        if authority not in {"product_owner", "deployment_operator"}:
            raise ExtensionContractError("Extension action authority could not be verified")
        return authority

    def stage(self, installation_id, *, authority_request):
        current = self.installation(installation_id)
        authorized_by = self._authority(authority_request, "stage", current)
        if current.trust_tier == "definition_package":
            allowed = {"product_owner", "deployment_operator"}
            message = "Definition staging requires the product owner or deployment operator"
        else:
            allowed = {"deployment_operator"}
            message = "Executable staging requires the deployment operator"
        if authorized_by not in allowed:
            raise ExtensionContractError(message)
        return self._advance(installation_id, "staged")

    def verify(self, installation_id, *, verification_refs, scan_refs):
        installation = self.installation(installation_id)
        if installation.state != "staged":
            raise ExtensionContractError("Only a staged installation can be verified")
        verification = digest_refs(verification_refs, "verification refs", required=True)
        scans = digest_refs(scan_refs, "scan refs", required=True)
        manifest = self._manifests[installation.manifest_digest]
        try:
            trusted = self._evidence_verifier.verify_installation(
                manifest, installation, verification, scans,
            ) is True
        except Exception:
            trusted = False
        if not trusted:
            failed = advance_installation(
                installation, "failed",
                verification_refs=verification, scan_refs=scans,
            )
            self._record(failed)
            self._emit("extension.failed", failed)
            return failed
        return self._advance(installation_id, "verified",
                             verification_refs=verification, scan_refs=scans)

    def qualify(self, installation_id, *, qualification_id, platform_digest, results,
                failure_details, qualified_scope, evidence_refs, conformance_suite,
                conformance_version, observed_capabilities_digest, expires_at):
        installation = self.installation(installation_id)
        if installation.state != "verified":
            raise ExtensionContractError("Only a verified installation can be qualified")
        id_ref(qualification_id, "qualification_id")
        if qualification_id in self._qualifications:
            raise ExtensionContractError("Qualification ID already exists")
        if type(qualified_scope) is not ExtensionScope:
            raise ExtensionContractError("Qualification requires an exact scope")
        if (installation.trust_tier == "deployment_trusted"
                and any(getattr(qualified_scope, name) is not None
                        for name in ("environment_id", "work_id", "node_id", "purpose"))):
            raise ExtensionContractError("Instance-critical qualification must be instance-scoped")
        now = self._now()
        platform = digest_ref(platform_digest, "platform digest")
        if platform != self.platform_digest:
            raise ExtensionContractError("Qualification platform differs from the current platform")
        result_pairs = validate_results(results)
        manifest = self._manifests[installation.manifest_digest]
        is_compatible, reason = compatible(
            manifest, framework_version=self.framework_version,
            extension_api_version=self.extension_api_version,
            schema_version=self.schema_version,
        )
        if not is_compatible:
            result_pairs = tuple(
                (name, "failed" if name == "compatibility" else value)
                for name, value in result_pairs
            )
            if type(failure_details) is dict:
                failure_details = {
                    **failure_details,
                    "compatibility": f"incompatible_{reason}",
                }
        evidence = digest_refs(evidence_refs, "qualification evidence", required=True)
        declared_digest = capability_digest(manifest)
        observed_digest = digest_ref(
            observed_capabilities_digest, "observed capabilities digest",
        )
        common = {
            "qualification_id": qualification_id,
            "installation": installation,
            "platform_digest": platform,
            "runtime_digest": self.runtime_digest,
            "framework_version": self.framework_version,
            "extension_api_version": self.extension_api_version,
            "schema_version_bound": self.schema_version,
            "conformance_suite": conformance_suite,
            "conformance_version": conformance_version,
            "declared_capabilities_digest": declared_digest,
            "observed_capabilities_digest": observed_digest,
            "results": dict(result_pairs),
            "failure_details": failure_details,
            "evidence_refs": evidence,
            "qualified_scope": qualified_scope,
            "qualified_at": now,
            "expires_at": expires_at,
            "recheck_triggers": QUALIFICATION_RECHECK_TRIGGERS,
        }
        candidate = new_qualification(
            **common, evidence_verified=False, status="failed",
        )
        verification_context = MappingProxyType({
            key: value for key, value in candidate.as_dict().items()
            if key not in {"schema_version", "qualification_id", "status", "evidence_verified"}
        })
        try:
            evidence_verified = self._evidence_verifier.verify_qualification(
                manifest, installation, verification_context,
            ) is True
        except Exception:
            evidence_verified = False
        passed = (is_compatible and evidence_verified
                  and all(value == "passed" for _, value in result_pairs))
        qualification = new_qualification(
            **common, evidence_verified=evidence_verified,
            status="qualified" if passed else "failed",
        )
        self._qualifications[qualification_id] = qualification
        if passed:
            self._advance(installation_id, "qualified")
        else:
            failed = advance_installation(installation, "failed")
            self._record(failed)
            self._emit("extension.failed", failed)
            if not is_compatible:
                self._emit("extension.compatibility_failed", failed, reason_code=reason)
        return qualification

    def _current_qualification(self, installation, qualification_id):
        id_ref(qualification_id, "qualification_id")
        try:
            qualification = self._qualifications[qualification_id]
        except KeyError as exc:
            raise ExtensionContractError("Extension must be qualified and enabled") from exc
        if (qualification.installation_id != installation.installation_id
                or qualification.status != "qualified"):
            raise ExtensionContractError("Extension must be qualified and enabled")
        reason = self._invalidated_qualifications.get(qualification_id)
        history = self._installation_histories[installation.installation_id]
        if reason is None:
            qualified_record = next(
                (item for item in history if item.revision == qualification.installation_revision),
                None,
            )
            if (qualified_record is None
                    or qualified_record.digest != qualification.installation_record_digest):
                reason = "bytes"
            elif qualification.manifest_digest != installation.manifest_digest:
                reason = "bytes"
            elif qualification.artifact_digest != installation.artifact_digest:
                reason = "bytes"
            elif qualification.runtime_digest != self.runtime_digest:
                reason = "runtime"
            elif qualification.platform_digest != self.platform_digest:
                reason = "platform"
            elif qualification.framework_version != self.framework_version:
                reason = "framework"
            elif qualification.extension_api_version != self.extension_api_version:
                reason = "extension_api"
            elif qualification.schema_version_bound != self.schema_version:
                reason = "schema"
            elif qualification.declared_capabilities_digest != capability_digest(
                    self._manifests[installation.manifest_digest]):
                reason = "permission"
            elif self._now() >= qualification.expires_at:
                reason = "expired"
        if reason is not None:
            self._invalidated_qualifications[qualification_id] = reason
            key = (installation.installation_id, qualification_id, reason)
            if key not in self._compatibility_events:
                self._emit("extension.compatibility_failed", installation, reason_code=reason)
                self._compatibility_events.add(key)
            raise ExtensionContractError("Extension requires compatible requalification")
        return qualification

    def bind(self, installation_id, *, qualification_id, binding_id, scope, config_ref,
             credential_handle_refs=(), grant_refs=(), authority_request):
        installation = self.installation(installation_id)
        if installation.state != "qualified":
            raise ExtensionContractError("Extension must be qualified and enabled")
        authorized_by = self._authority(authority_request, "bind", installation)
        allowed = ({"deployment_operator"} if installation.trust_tier == "deployment_trusted"
                   else {"product_owner", "deployment_operator"})
        if authorized_by not in allowed:
            raise ExtensionContractError("Binding requires the product owner or deployment operator")
        qualification = self._current_qualification(installation, qualification_id)
        if type(scope) is not ExtensionScope or scope != qualification.qualified_scope:
            raise ExtensionContractError("Binding exceeds or differs from qualified scope")
        id_ref(binding_id, "binding_id")
        if binding_id in self._bindings:
            raise ExtensionContractError("Binding ID already exists")
        manifest = self._manifests[installation.manifest_digest]
        config = digest_ref(config_ref, "config ref")
        credentials = digest_refs(credential_handle_refs, "credential handle refs")
        grants = digest_refs(grant_refs, "grant refs")
        if credentials and not manifest.secret_needs:
            raise ExtensionContractError("Binding cannot add undeclared secret capabilities")
        if grants and not manifest.declared_grants:
            raise ExtensionContractError("Binding cannot add undeclared grants")
        if manifest.secret_needs and not credentials:
            raise ExtensionContractError("Binding is missing declared secret capabilities")
        if manifest.declared_grants and not grants:
            raise ExtensionContractError("Binding is missing declared grants")
        binding_context = self._binding_context(
            manifest=manifest, qualification=qualification, scope=scope,
            config_ref=config, credential_handle_refs=credentials, grant_refs=grants,
        )
        if not self._binding_references_verified(
                manifest, installation, qualification, binding_context):
            raise ExtensionContractError("Binding references were not authorized")
        # Build the exact next records before mutating registry state or emitting an event.
        # Invalid config/grant/credential input must leave a qualified installation retryable.
        enabled = advance_installation(installation, "enabled")
        binding = new_binding(
            binding_id=binding_id, installation=enabled, qualification=qualification,
            scope=scope, config_ref=config,
            credential_handle_refs=credentials, grant_refs=grants,
            enabled_revision=enabled.revision,
        )
        self._record(enabled)
        self._emit("extension.enabled", enabled)
        self._bindings[binding_id] = binding
        self._emit("extension.binding_changed", enabled)
        return binding

    @staticmethod
    def _binding_context(*, manifest, qualification, scope, config_ref,
                         credential_handle_refs, grant_refs):
        return MappingProxyType({
            "config_ref": config_ref,
            "credential_handle_refs": credential_handle_refs,
            "grant_refs": grant_refs,
            "declared_grants": manifest.declared_grants,
            "secret_needs": manifest.secret_needs,
            "scope": scope,
            "declared_capabilities_digest": qualification.declared_capabilities_digest,
            "observed_capabilities_digest": qualification.observed_capabilities_digest,
        })

    def _binding_references_verified(self, manifest, installation, qualification, context):
        try:
            return self._evidence_verifier.verify_binding(
                manifest, installation, qualification, context,
            ) is True
        except Exception:
            return False

    def binding(self, binding_id):
        id_ref(binding_id, "binding_id")
        try:
            binding = self._bindings[binding_id]
        except KeyError as exc:
            raise ExtensionContractError("Unknown extension binding") from exc
        installation = self.installation(binding.installation_id)
        if installation.state != "enabled" or binding.enabled_revision != installation.revision:
            raise ExtensionContractError("Extension binding is no longer enabled")
        if binding_id in self._invalidated_bindings:
            raise ExtensionContractError("Binding references require requalification")
        qualification = self._current_qualification(installation, binding.qualification_id)
        manifest = self._manifests[installation.manifest_digest]
        context = self._binding_context(
            manifest=manifest, qualification=qualification, scope=binding.scope,
            config_ref=binding.config_ref,
            credential_handle_refs=binding.credential_handle_refs,
            grant_refs=binding.grant_refs,
        )
        if not self._binding_references_verified(
                manifest, installation, qualification, context):
            self._invalidated_bindings[binding_id] = "permission"
            key = (installation.installation_id, binding.qualification_id,
                   "permission", binding.binding_id)
            if key not in self._compatibility_events:
                self._emit("extension.compatibility_failed", installation,
                           reason_code="permission")
                self._compatibility_events.add(key)
            raise ExtensionContractError("Binding references require requalification")
        return binding

    def observe_runtime(self, *, runtime_digest, platform_digest=None):
        runtime = digest_ref(runtime_digest, "runtime digest")
        platform = (self.platform_digest if platform_digest is None
                    else digest_ref(platform_digest, "platform digest"))
        if runtime != self.runtime_digest or platform != self.platform_digest:
            for qualification_id, qualification in self._qualifications.items():
                if qualification.status != "qualified":
                    continue
                if qualification.runtime_digest != runtime:
                    self._invalidated_qualifications.setdefault(qualification_id, "runtime")
                elif qualification.platform_digest != platform:
                    self._invalidated_qualifications.setdefault(qualification_id, "platform")
        self.runtime_digest = runtime
        self.platform_digest = platform

    def prepare_dispatch(self, binding_id):
        # Deliberately do not even resolve an artifact here: only T018's typed broker may do so.
        raise RuntimeBoundaryUnavailable(
            "Runtime extension dispatch is unavailable until the isolated broker is qualified"
        )

    def authorize_export(self, binding_id, *, target_confirmation_ref):
        binding = self.binding(binding_id)
        if binding.extension_kind != "export_sink":
            raise ExtensionContractError("Binding is not an export sink")
        if target_confirmation_ref is None:
            raise ExtensionContractError("Export requires a target-bound export confirmation")
        confirmation = digest_ref(target_confirmation_ref, "target confirmation ref")
        return {
            "binding_id": binding.binding_id,
            "target_confirmation_ref": confirmation,
            "dispatch_ready": False,
        }

    def suspend(self, installation_id, *, authority_request):
        installation = self.installation(installation_id)
        authorized_by = self._authority(authority_request, "suspend", installation)
        if (installation.trust_tier == "deployment_trusted"
                and authorized_by != "deployment_operator"):
            raise ExtensionContractError("Instance-critical action requires the deployment operator")
        return self._advance(installation_id, "suspended")

    def revoke(self, installation_id, *, authority_request):
        installation = self.installation(installation_id)
        authorized_by = self._authority(authority_request, "revoke", installation)
        if (installation.trust_tier == "deployment_trusted"
                and authorized_by != "deployment_operator"):
            raise ExtensionContractError("Instance-critical action requires the deployment operator")
        return self._advance(installation_id, "revoked")

    def remove(self, installation_id, *, authority_request):
        installation = self.installation(installation_id)
        authorized_by = self._authority(authority_request, "remove", installation)
        if (installation.trust_tier == "deployment_trusted"
                and authorized_by != "deployment_operator"):
            raise ExtensionContractError("Instance-critical action requires the deployment operator")
        manifest = self._manifests[installation.manifest_digest]
        if (manifest.uninstall_policy == "block_if_bound"
                and any(binding.installation_id == installation_id
                        for binding in self._bindings.values())):
            raise ExtensionContractError("Bound extension uninstall policy blocks removal")
        return self._advance(installation_id, "removed")
