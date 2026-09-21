"""Concrete exact-record projection for the conditional semantic consumer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from ..domain.refs import EntityRef, canonical_json
from ..domain.store import BlobRef, DomainStore
from ..workers.credential_contracts import fingerprint, metadata_value, reference
from .port_schema_generator import validate_port_payload
from .provider_semantic_contracts import ProviderSemanticError
from .provider_semantic_records import (require_model_operation_index,
                                        take_operation_owner_capability)
from ..workers.provider_semantic_codec import (CatalogTraversal, advance_catalog,
                                                encode_text_body, parse_model_page)


class ProviderSemanticAdmissionError(ProviderSemanticError):
    """A deliberate pre-send refusal with an exact canonical local category."""

    def __init__(self, failure_class, message):
        if failure_class not in {"permission_denied", "deadline_exceeded",
                                 "resource_exhausted", "unsupported_capability",
                                 "integrity_failed"}:
            raise ValueError("invalid semantic admission failure class")
        super().__init__(message)
        self.failure_class = failure_class


def _instant(value):
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise ProviderSemanticError("semantic evidence time is invalid") from None


def _effort_values(projection):
    capabilities = projection["capabilities"]
    if capabilities["state"] != "value":
        return []
    effort = capabilities["value"]["effort"]
    if not effort["supported"]:
        return []
    values = [name for name in ("high", "low", "max", "medium")
              if effort[name]["supported"]]
    if (effort["xhigh"]["state"] == "value"
            and effort["xhigh"]["value"]["supported"]):
        values.append("xhigh")
    return sorted(values, key=str.encode)


def _catalog_evidence(store, *, catalog_ref, catalog, config_ref, connection_ref,
                      text_policy_ref, text_policy, compatibility_set, now):
    """Rebuild the durable decision graph from retained source bytes."""
    if (catalog.get("schema_version") != "provider-semantic-catalog-v1"
            or catalog.get("connection_ref") != connection_ref.as_dict()
            or catalog.get("complete") is not True):
        raise ProviderSemanticError("selected catalog is not current complete evidence")
    if not _instant(catalog["fetched_at"]) <= now < _instant(catalog["expires_at"]):
        raise ProviderSemanticAdmissionError(
            "permission_denied", "selected catalog is not current complete evidence")
    operation_ref = EntityRef.from_dict(catalog["operation_ref"])
    operation = store.get(operation_ref).body["content"]
    if (operation.get("schema_version") != "provider-semantic-operation-v1"
            or operation.get("config_ref") != config_ref.as_dict()
            or operation.get("request", {}).get("operation") != "catalog"):
        raise ProviderSemanticError("selected catalog operation provenance is invalid")
    config = store.get(config_ref).body["content"]
    fetched, expires, policy_expiry = (_instant(catalog["fetched_at"]),
        _instant(catalog["expires_at"]), _instant(text_policy["valid_until"]))
    expected_expiry = min(policy_expiry, fetched + timedelta(
        seconds=config["config"]["port_config"]["catalog_ttl_seconds"]))
    if expires != expected_expiry:
        raise ProviderSemanticError("catalog expiry is not derived from admitted policy")
    scope = text_policy.get("scope_model_ids")
    admitted = ({canonical_json(item) for item in compatibility_set.get("observation_refs", [])}
                if compatibility_set.get("schema_version")
                == "provider-semantic-compatibility-set-v1"
                and compatibility_set.get("connection_ref") == connection_ref.as_dict()
                else set())
    request_policy_sha256 = sha256(canonical_json({
        "profile_id": "claude-api-text-semantic-v1", "api_version": "2023-06-01",
        "auth": "api-key", "effort": None, "tools": False, "cache": False,
        "thinking_override": None, "success_stop": "end_turn",
        "input_media_types": ["text/plain"], "max_inputs": 4, "max_output_blocks": 4,
        "max_output_tokens": 8192, "deadline_ms": 30000})).hexdigest()
    traversal, page_values, page_refs = CatalogTraversal(), [], []
    for index, item in enumerate(catalog["page_refs"]):
        page_ref = EntityRef.from_dict(item)
        page = store.get(page_ref).body["content"]
        raw = store.read_blob(BlobRef.from_dict(page["raw_blob"]), purpose="operational")
        parsed = parse_model_page(raw)
        after_id = None if index == 0 else page_values[-1][1].last_id
        if (page.get("schema_version") != "provider-semantic-page-v1"
                or page.get("operation_ref") != operation_ref.as_dict()
                or page.get("index") != index or page.get("after_id") != after_id
                or page.get("raw_sha256") != parsed.raw_sha256
                or page.get("raw_size") != parsed.raw_size
                or page.get("first_id") != parsed.first_id
                or page.get("last_id") != parsed.last_id
                or page.get("has_more") != parsed.has_more
                or page.get("model_ids") != [model.id for model in parsed.models]):
            raise ProviderSemanticError("retained catalog page projection is invalid")
        traversal = advance_catalog(traversal, parsed)
        page_refs.append(page_ref)
        page_values.append((page_ref, parsed))
    if not traversal.complete:
        raise ProviderSemanticError("retained catalog traversal is incomplete")

    rows, eligible, excluded, capability_by_model = [], [], [], {}
    catalog_rows = catalog.get("models")
    if type(catalog_rows) is not list or len(catalog_rows) != len(traversal.model_ids):
        raise ProviderSemanticError("catalog rows differ from retained pages")
    ordinal = 0
    for page_ref, page in page_values:
        for model_index, model in enumerate(page.models):
            row = catalog_rows[ordinal]
            capability_ref = EntityRef.from_dict(row["capability_evidence_ref"])
            capability = store.get(capability_ref).body["content"]
            projection = {"id": model.id, "display_name": model.display_name,
                "created_at": model.created_at, "capabilities": model.capabilities.as_dict(),
                "max_input_tokens": model.max_input_tokens.as_dict(),
                "max_tokens": model.max_tokens.as_dict()}
            if (capability.get("schema_version") != "provider-semantic-capability-v1"
                    or capability.get("operation_ref") != operation_ref.as_dict()
                    or capability.get("page_ref") != page_ref.as_dict()
                    or capability.get("model_index") != model_index
                    or capability.get("model_id") != model.id
                    or capability.get("text_policy_ref") != text_policy_ref.as_dict()
                    or capability.get("observed_at") != catalog["fetched_at"]
                    or capability.get("valid_until") != catalog["expires_at"]
                    or capability.get("projection") != projection):
                raise ProviderSemanticError("catalog capability provenance is invalid")
            compatibility_ref = capability["compatibility_ref"]
            compatible = False
            if compatibility_ref is not None:
                compatible = canonical_json(compatibility_ref) in admitted
                compatibility = store.get(EntityRef.from_dict(compatibility_ref)).body["content"]
                compatible = compatible and (
                    compatibility.get("schema_version") == "provider-semantic-compatibility-v1"
                    and compatibility.get("profile_id") == "claude-api-text-semantic-v1"
                    and compatibility.get("connection_ref") == connection_ref.as_dict()
                    and compatibility.get("model_id") == model.id
                    and compatibility.get("request_policy_sha256") == request_policy_sha256
                    and compatibility.get("outcome") == "complete_text"
                    and _instant(compatibility["observed_at"]) <= now
                    < _instant(compatibility["expires_at"])
                    and _instant(compatibility["expires_at"])
                    - _instant(compatibility["observed_at"]) <= timedelta(days=7))
            modalities = ["text"] if model.id in scope else []
            expected_row = {"model_id": model.id, "display_name": model.display_name,
                "modalities": modalities, "effort_values": _effort_values(projection),
                "capability_evidence_ref": capability_ref.as_dict()}
            if row != expected_row:
                raise ProviderSemanticError("catalog row differs from retained capability evidence")
            if projection["capabilities"]["state"] != "value":
                excluded.append({"model_id": model.id, "reason": "capability_unknown"})
            elif (projection["max_input_tokens"]["state"] != "value"
                    or projection["max_tokens"]["state"] != "value"):
                excluded.append({"model_id": model.id, "reason": "limits_unknown"})
            elif not modalities:
                excluded.append({"model_id": model.id, "reason": "text_scope_unproved"})
            elif not compatible:
                excluded.append({"model_id": model.id, "reason": "profile_unproved"})
            else:
                eligible.append(model.id)
            capability_by_model[model.id] = capability
            rows.append(expected_row)
            ordinal += 1
    if (catalog_rows != rows or catalog.get("eligible_model_ids") != eligible
            or catalog.get("excluded") != excluded):
        raise ProviderSemanticError("catalog eligibility differs from retained evidence")
    return capability_by_model


def validate_bound_handle(*, config, binding, connection_record, current_connection):
    if (type(config) is not dict or type(binding) is not dict or type(connection_record) is not dict
            or type(current_connection) is not dict):
        raise ProviderSemanticError("bound connection projection is malformed")
    handles = config.get("credential_handle_refs")
    if (type(handles) is not list or len(handles) != 1
            or binding.get("credential_handle_refs") != handles
            or connection_record.get("ref") != handles[0]):
        raise ProviderSemanticError("config and binding must select the exact sole handle")
    content = connection_record.get("content")
    required = {"schema_version", "locator", "revision_digest", "provider_id", "account_id",
                "credential_metadata", "credential_metadata_sha256", "credential_record"}
    if type(content) is not dict or set(content) != required \
            or content["schema_version"] != "provider-semantic-connection-v1":
        raise ProviderSemanticError("connection snapshot is not closed")
    metadata = metadata_value(content["credential_metadata"])
    record = reference(content["credential_record"])
    projection = {key: content[key] for key in
                  ("locator", "revision_digest", "provider_id", "account_id", "credential_metadata_sha256")}
    if (projection != current_connection or content["provider_id"] != "claude_api"
            or metadata["provider"] != "claude" or metadata["auth_mode"] != "api"
            or content["credential_metadata_sha256"] != fingerprint(metadata)
            or metadata["record_id"] != record["record_id"]
            or metadata["record_version"] != record["record_version"]):
        raise ProviderSemanticError("connection snapshot does not match current encrypted custody")
    return {"selected_handle_ref": handles[0], "connection_sha256": handles[0]["sha256"],
            "connection_pin": projection, "credential_metadata": metadata,
            "credential_record": record}


@dataclass(frozen=True, slots=True)
class ProviderSemanticAuthority:
    binding_record: dict
    current_connection: dict
    qualification_record: dict
    binding_head_record: dict
    actor_record: dict
    purpose_record: dict
    grant_records: dict
    artifact_records: dict
    selector_records: dict
    input_records: dict
    core_boot_id: str

    def __post_init__(self):
        try:
            boot = UUID(self.core_boot_id)
        except (TypeError, ValueError):
            raise ProviderSemanticError("semantic owner boot is invalid") from None
        if str(boot) != self.core_boot_id or boot.int == 0:
            raise ProviderSemanticError("semantic owner boot is invalid")
        for name in ("binding_record", "current_connection", "qualification_record",
                     "binding_head_record", "actor_record", "purpose_record", "grant_records",
                     "artifact_records", "selector_records", "input_records"):
            if type(getattr(self, name)) is not dict:
                raise ProviderSemanticError("trusted semantic authority projection is malformed")


@dataclass(frozen=True, slots=True)
class ProviderSemanticContext:
    config_ref: EntityRef
    operation_ref: EntityRef
    config: dict
    request: dict
    frozen_ref: EntityRef | None
    frozen_content: dict | None
    input_bytes: tuple[bytes, ...]
    connection: dict
    reservation_ref: EntityRef | None
    catalog_ref: EntityRef | None
    owner_core_boot_id: str
    worker_session_observation: tuple | None = None
    gateway_session_observation: tuple | None = None


class ProviderSemanticContextLoader:
    def __init__(self, store, *, config_ref, operation_ref, authority):
        if type(store) is not DomainStore or type(config_ref) is not EntityRef \
                or type(operation_ref) is not EntityRef or type(authority) is not ProviderSemanticAuthority:
            raise ProviderSemanticError("exact semantic context dependencies required")
        self._store, self._config_ref, self._operation_ref, self._authority = (
            store, config_ref, operation_ref, authority)
        self._owner_capability = take_operation_owner_capability(store, operation_ref)

    @property
    def operation_ref(self):
        return self._operation_ref

    def consume_owner_capability(self):
        capability, self._owner_capability = self._owner_capability, None
        return (capability is not None and capability.consume(
            self._store, self._operation_ref, self._authority.core_boot_id))

    def _operation_identity(self):
        """Resolve immutable joins before deciding who may close this operation."""
        config_record = self._store.get(self._config_ref).body["content"]
        operation = self._store.get(self._operation_ref).body["content"]
        if (config_record.get("schema_version") != "provider-semantic-config-v1"
                or operation.get("schema_version") != "provider-semantic-operation-v1"
                or operation.get("config_ref") != self._config_ref.as_dict()
                or operation.get("request_sha256")
                != sha256(canonical_json(operation.get("request"))).hexdigest()):
            raise ProviderSemanticError("historical semantic record does not join config")
        config, request = config_record["config"], operation["request"]
        identity = ("installation_digest", "qualification_ref", "binding_revision_ref")
        if (any(request.get(name) != config.get(name) for name in identity)
                or any(grant not in config["grant_refs"] for grant in request["grant_refs"])):
            raise ProviderSemanticError("historical semantic identity differs from config")
        if request["operation"] == "model_step":
            require_model_operation_index(self._store, self._operation_ref)
        return config, operation

    def authorize_historical_read(self):
        """Authorize immutable owner/purpose replay without obsolete send eligibility."""
        config, operation = self._operation_identity()
        request = operation["request"]
        if (self._authority.actor_record.get("ref") != request.get("actor_ref")
                or self._authority.actor_record.get("authenticated") is not True
                or self._authority.purpose_record.get("ref") != request.get("purpose_ref")
                or self._authority.purpose_record.get("active") is not True
                or self._authority.purpose_record.get("purpose")
                != config["binding_slot_key"]["purpose"]):
            raise ProviderSemanticError("historical semantic owner read is unauthorized")
        for grant_ref in request["grant_refs"]:
            grant = self._authority.grant_records.get(grant_ref["sha256"])
            if (type(grant) is not dict or grant.get("ref") != grant_ref
                    or grant.get("active") is not True
                    or grant.get("purpose_ref") != request["purpose_ref"]
                    or request["operation"] not in grant.get("allowed_operations", [])):
                raise ProviderSemanticError("historical semantic grant is unauthorized")
        return operation

    @staticmethod
    def _parsed_time(value):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            return None

    def _precheck_current_authority(self, config, request, now):
        """Classify only explicit current-authority refusals before the mixed validator."""
        if type(config) is not dict:
            return
        authority = self._authority
        qualification = authority.qualification_record
        qualification_expiry = self._parsed_time(
            qualification.get("expires_at") if type(qualification) is dict else None)
        if (type(qualification) is dict
                and qualification.get("ref") == config.get("qualification_ref")
                and qualification.get("installation_digest") == config.get("installation_digest")
                and qualification.get("port_contract_version") == "provider-port-v1"
                and qualification_expiry is not None
                and ((type(qualification.get("status")) is str
                      and qualification.get("status") != "qualified")
                     or qualification_expiry <= now)):
            raise ProviderSemanticAdmissionError(
                "permission_denied", "semantic qualification is not current")
        binding = authority.binding_record
        if (type(binding) is dict
                and binding.get("ref") == config.get("binding_revision_ref")
                and binding.get("extension_id") == config.get("extension_id")
                and binding.get("installation_digest") == config.get("installation_digest")
                and binding.get("port_contract_version") == "provider-port-v1"
                and type(binding.get("state")) is str
                and binding.get("state") != "active"):
            raise ProviderSemanticAdmissionError(
                "permission_denied", "semantic binding is not active")
        head = authority.binding_head_record
        if (type(head) is dict and type(head.get("state")) is str
                and head.get("binding_slot_key") == config.get("binding_slot_key")
                and head.get("binding_slot_key_digest") == config.get("binding_slot_key_digest")
                and (head.get("state") != "active"
                     or head.get("current_binding_revision_ref")
                     != config.get("binding_revision_ref"))):
            raise ProviderSemanticAdmissionError(
                "permission_denied", "semantic binding is not current")
        if type(request) is not dict:
            return
        actor = authority.actor_record
        if (type(actor) is dict and actor.get("ref") == request.get("actor_ref")
                and actor.get("actor_type") in {"system", "worker"}
                and actor.get("authenticated") is not True):
            raise ProviderSemanticAdmissionError(
                "permission_denied", "semantic actor is not authenticated")
        purpose = authority.purpose_record
        slot = config.get("binding_slot_key")
        if (type(purpose) is dict and purpose.get("ref") == request.get("purpose_ref")
                and type(slot) is dict and purpose.get("purpose") == slot.get("purpose")
                and type(purpose.get("active")) is bool
                and purpose.get("active") is not True):
            raise ProviderSemanticAdmissionError(
                "permission_denied", "semantic purpose is not active")
        grants = authority.grant_records
        if type(grants) is dict and type(request.get("grant_refs")) is list:
            for grant_ref in request["grant_refs"]:
                if type(grant_ref) is not dict or type(grant_ref.get("sha256")) is not str:
                    continue
                try:
                    EntityRef.from_dict(grant_ref)
                except (TypeError, ValueError):
                    continue
                grant = grants.get(grant_ref["sha256"])
                if grant is None:
                    raise ProviderSemanticAdmissionError(
                        "permission_denied", "semantic grant is unavailable")
                operations = grant.get("allowed_operations") if type(grant) is dict else None
                if (type(grant) is dict and grant.get("ref") == grant_ref
                        and type(operations) is list
                        and type(grant.get("active")) is bool
                        and (grant.get("active") is not True
                             or grant.get("purpose_ref") != request.get("purpose_ref")
                             or request.get("operation") not in operations)):
                    raise ProviderSemanticAdmissionError(
                        "permission_denied", "semantic grant is not current")
        deadline = self._parsed_time(request.get("deadline_at"))
        if deadline is not None and deadline <= now:
            raise ProviderSemanticAdmissionError(
                "deadline_exceeded", "semantic request deadline elapsed")

    def load(self, *, now_utc):
        try:
            now = datetime.strptime(now_utc, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            raise ProviderSemanticError("semantic validation time is invalid") from None
        config_record = self._store.get(self._config_ref)
        operation_record = self._store.get(self._operation_ref)
        config_content = config_record.body["content"]
        operation_content = operation_record.body["content"]
        if config_content.get("schema_version") != "provider-semantic-config-v1" \
                or operation_content.get("schema_version") != "provider-semantic-operation-v1" \
                or operation_content["config_ref"] != self._config_ref.as_dict():
            raise ProviderSemanticError("semantic context records do not join")
        config = config_content["config"]
        operation_request = operation_content["request"]
        self._precheck_current_authority(config, None, now)
        config_context = {"validated_at": now_utc,
            "qualification_record": self._authority.qualification_record,
            "binding_revision_record": self._authority.binding_record,
            "binding_head_record": self._authority.binding_head_record}
        validate_port_payload("provider-port-v1", "config", config, context=config_context)
        connection_ref = EntityRef.from_dict(config_content["connection_ref"])
        connection_record = self._store.get(connection_ref)
        connection_view = {"ref": connection_ref.as_dict(), "content": connection_record.body["content"]}
        connection_fields = ("locator", "revision_digest", "provider_id", "account_id",
                             "credential_metadata_sha256")
        connection_content = connection_view["content"]
        stable_current = ({name: connection_content.get(name) for name in connection_fields}
                          if type(connection_content) is dict else {})
        validate_bound_handle(config=config, binding=self._authority.binding_record,
            connection_record=connection_view, current_connection=stable_current)
        if self._authority.current_connection != stable_current:
            raise ProviderSemanticAdmissionError(
                "permission_denied", "semantic connection is not current")
        pin = validate_bound_handle(config=config, binding=self._authority.binding_record,
            connection_record=connection_view, current_connection=self._authority.current_connection)
        self._precheck_current_authority(config, operation_request, now)
        frozen_ref = None if operation_content["frozen_ref"] is None else EntityRef.from_dict(operation_content["frozen_ref"])
        frozen_content, inputs = None, ()
        if frozen_ref is not None:
            frozen_content = self._store.get(frozen_ref).body["content"]
            collected = []
            for item in frozen_content["artifact_input_bindings"]:
                artifact = self._store.get(EntityRef.from_dict(item["artifact_ref"]))
                blob = BlobRef.from_dict(artifact.body["content"]["blob_ref"])
                collected.append(self._store.read_blob(blob, purpose="operational"))
            inputs = tuple(collected)
        request_context = {"config": config, "accepted_at": now_utc,
            "actor_record": self._authority.actor_record,
            "purpose_record": self._authority.purpose_record,
            "grant_records": self._authority.grant_records,
            "artifact_records": self._authority.artifact_records,
            "selector_records": self._authority.selector_records,
            "input_records": self._authority.input_records}
        if frozen_ref is not None:
            request_context["frozen_record"] = {"ref": frozen_ref.as_dict(),
                "artifact_input_bindings": frozen_content["artifact_input_bindings"],
                "purpose_ref": frozen_content["purpose_ref"],
                "grant_refs": frozen_content["grant_refs"]}
        if operation_request.get("operation") == "model_step":
            selected = operation_request.get("input", {})
            if (selected.get("requested_modalities") != ["text"]
                    or selected.get("tool_definition_refs") != []
                    or selected.get("response_schema_ref") is not None
                    or selected.get("effort") is not None):
                raise ProviderSemanticAdmissionError(
                    "unsupported_capability", "model request is outside the selected profile")
        validate_port_payload("provider-port-v1", "request", operation_request,
                              context=request_context)
        reservation_ref = (None if operation_content["reservation_ref"] is None else
                           EntityRef.from_dict(operation_content["reservation_ref"]))
        catalog_ref = None
        catalog_epoch = operation_content["request"].get("input", {}).get("catalog_epoch")
        if operation_content["request"].get("operation") == "catalog" \
                and catalog_epoch is not None:
            try:
                catalog_ref = EntityRef.from_dict(catalog_epoch)
                catalog = self._store.get(catalog_ref).body["content"]
                catalog_operation_ref = EntityRef.from_dict(catalog["operation_ref"])
                catalog_operation = self._store.get(catalog_operation_ref).body["content"]
                catalog_config = self._store.get(EntityRef.from_dict(
                    catalog_operation["config_ref"])).body["content"]
            except (KeyError, TypeError, ValueError):
                raise ProviderSemanticError("catalog epoch does not resolve") from None
            if (catalog_ref.kind != "model_catalog"
                    or catalog.get("schema_version") != "provider-semantic-catalog-v1"
                    or catalog.get("connection_ref") != connection_ref.as_dict()
                    or catalog_operation.get("schema_version")
                    != "provider-semantic-operation-v1"
                    or catalog_operation.get("request", {}).get("operation") != "catalog"
                    or catalog_config.get("schema_version") != "provider-semantic-config-v1"
                    or catalog_config.get("connection_ref") != connection_ref.as_dict()):
                raise ProviderSemanticError(
                    "catalog epoch is not an existing same-connection semantic catalog")
            page_refs = catalog.get("page_refs")
            models = catalog.get("models")
            if type(page_refs) is not list or type(models) is not list:
                raise ProviderSemanticError("catalog epoch graph is malformed")
            for item in page_refs:
                page = self._store.get(EntityRef.from_dict(item)).body["content"]
                if (page.get("schema_version") != "provider-semantic-page-v1"
                        or page.get("operation_ref") != catalog_operation_ref.as_dict()):
                    raise ProviderSemanticError("catalog epoch page graph is malformed")
            for row in models:
                capability = self._store.get(EntityRef.from_dict(
                    row["capability_evidence_ref"])).body["content"]
                if (capability.get("schema_version")
                        != "provider-semantic-capability-v1"
                        or capability.get("operation_ref")
                        != catalog_operation_ref.as_dict()
                        or capability.get("model_id") != row.get("model_id")):
                    raise ProviderSemanticError("catalog epoch capability graph is malformed")
        if frozen_content is not None:
            require_model_operation_index(self._store, self._operation_ref)
            turn = frozen_content["turn"]
            if (operation_content["request"]["input"]["model_id"] != turn["model_id"]
                    or operation_content["request"]["artifact_inputs"]
                    != frozen_content["artifact_input_bindings"]):
                raise ProviderSemanticError("model request differs from frozen authority")
            catalog_ref = EntityRef.from_dict(turn["catalog_ref"])
            catalog = self._store.get(catalog_ref).body["content"]
            text_policy = self._store.get(EntityRef.from_dict(
                config_content["text_policy_ref"])).body["content"]
            text_policy_ref = EntityRef.from_dict(config_content["text_policy_ref"])
            compatibility_set = self._store.get(EntityRef.from_dict(
                config_content["compatibility_set_ref"])).body["content"]
            if (text_policy.get("schema_version") != "provider-semantic-text-policy-v1"
                    or compatibility_set.get("schema_version")
                    != "provider-semantic-compatibility-set-v1"
                    or compatibility_set.get("connection_ref") != connection_ref.as_dict()
                    or type(text_policy.get("scope_model_ids")) is not list):
                raise ProviderSemanticError("selected model evidence does not join config")
            if turn["model_id"] not in text_policy["scope_model_ids"]:
                raise ProviderSemanticAdmissionError(
                    "unsupported_capability", "selected model is outside reviewed text scope")
            if not (_instant(text_policy["retrieved_at"]) <= _instant(text_policy["reviewed_at"])
                    <= now < _instant(text_policy["valid_until"])
                    and _instant(text_policy["valid_until"])
                    - _instant(text_policy["reviewed_at"]) <= timedelta(days=7)):
                raise ProviderSemanticAdmissionError(
                    "permission_denied", "reviewed text policy is not current")
            policy_blob = BlobRef.from_dict(text_policy["source_blob"])
            if (sha256(self._store.read_blob(policy_blob, purpose="operational")).hexdigest()
                    != text_policy["source_sha256"]):
                raise ProviderSemanticError("reviewed text policy bytes changed")
            capabilities = _catalog_evidence(self._store, catalog_ref=catalog_ref,
                catalog=catalog, config_ref=self._config_ref, connection_ref=connection_ref,
                text_policy_ref=text_policy_ref, text_policy=text_policy,
                compatibility_set=compatibility_set, now=now)
            if turn["model_id"] not in catalog["eligible_model_ids"]:
                raise ProviderSemanticAdmissionError("unsupported_capability",
                    "selected model lacks complete eligible catalog evidence")
            selected_row = next((row for row in catalog["models"]
                                 if row["model_id"] == turn["model_id"]), None)
            if selected_row is None:
                raise ProviderSemanticError("eligible model row is missing")
            capability = capabilities[turn["model_id"]]
            admitted = {canonical_json(value) for value in compatibility_set["observation_refs"]}
            compatibility_ref = capability.get("compatibility_ref")
            if (capability.get("schema_version") != "provider-semantic-capability-v1"
                    or capability.get("model_id") != turn["model_id"]
                    or capability.get("text_policy_ref") != config_content["text_policy_ref"]
                    or _instant(capability["observed_at"]) > now
                    or not now < _instant(capability["valid_until"])
                    or compatibility_ref is None
                    or canonical_json(compatibility_ref) not in admitted):
                raise ProviderSemanticAdmissionError(
                    "permission_denied", "selected model capability is not current")
            compatibility = self._store.get(EntityRef.from_dict(compatibility_ref)).body["content"]
            if (compatibility.get("schema_version") != "provider-semantic-compatibility-v1"
                    or compatibility.get("connection_ref") != connection_ref.as_dict()
                    or compatibility.get("model_id") != turn["model_id"]
                    or not _instant(compatibility["observed_at"]) <= now
                    < _instant(compatibility["expires_at"])):
                raise ProviderSemanticAdmissionError(
                    "permission_denied", "selected model compatibility is not current")
            if reservation_ref is None:
                raise ProviderSemanticError("model operation lacks reviewed reservation")
            reservation = self._store.get(reservation_ref).body["content"]
            body_sha = sha256(encode_text_body(frozen_content, inputs)).hexdigest()
            max_input = capability["projection"]["max_input_tokens"]
            max_output = capability["projection"]["max_tokens"]
            budget = self._store.get(EntityRef.from_dict(turn["budget_ref"])).body["content"]
            if (max_input.get("state") != "value" or max_output.get("state") != "value"):
                raise ProviderSemanticAdmissionError(
                    "unsupported_capability", "selected model limits are not known")
            if (frozen_content["max_output_tokens"] > max_output["value"]
                    or reservation["input_upper_bound"] + reservation["max_output_tokens"]
                    > max_input["value"]):
                raise ProviderSemanticAdmissionError(
                    "resource_exhausted", "model request exceeds reviewed provider limits")
            if (reservation.get("schema_version") != "provider-semantic-reservation-v1"
                    or reservation.get("connection_ref") != connection_ref.as_dict()
                    or reservation.get("model_id") != turn["model_id"]
                    or turn.get("account_id") != pin["connection_pin"]["account_id"]
                    or reservation.get("proposal_sha256") != body_sha
                    or reservation.get("max_output_tokens") != frozen_content["max_output_tokens"]
                    or reservation.get("currency") != budget.get("policy", {}).get("currency")
                    or not _instant(reservation["effective_at"]) <= now
                    < _instant(reservation["expires_at"])
                    ):
                raise ProviderSemanticError("reviewed reservation does not bind this model request")
            self._store.read_blob(BlobRef.from_dict(reservation["method_blob"]),
                                  purpose="operational")
        return ProviderSemanticContext(self._config_ref, self._operation_ref, config,
            operation_content["request"], frozen_ref, frozen_content, inputs, pin,
            reservation_ref, catalog_ref, self._authority.core_boot_id)


__all__ = ["ProviderSemanticAdmissionError", "ProviderSemanticAuthority",
           "ProviderSemanticContext", "ProviderSemanticContextLoader", "validate_bound_handle"]
