"""Sealing and exact rehydration for provider semantic evidence records."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import threading
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import EntityRef, canonical_json
from ..domain.schemas import ImmutableRecord
from ..domain.store import BlobRef, DomainStore, _writer
from .provider_semantic_contracts import (
    API_VERSION, MAX_INPUT_BYTES, PROFILE, ProviderSemanticError, identifier,
    semantic_record_id, semantic_request_key, validate_canonical_port_shape,
    validate_frozen_content,
)


_OWNER_LOCK = threading.Lock()
_OWNER_CAPABILITIES = {}


class _OperationOwnerCapability:
    __slots__ = ("vault_id", "operation_ref", "core_boot_id", "_consumed")

    def __init__(self, vault_id, operation_ref, core_boot_id):
        self.vault_id, self.operation_ref, self.core_boot_id = (
            vault_id, operation_ref, core_boot_id)
        self._consumed = False

    def consume(self, store, operation_ref, core_boot_id):
        with _OWNER_LOCK:
            if (self._consumed or store.vault_id != self.vault_id
                    or operation_ref != self.operation_ref
                    or core_boot_id != self.core_boot_id):
                return False
            self._consumed = True
            return True

    def __reduce__(self):
        raise TypeError("semantic owner capability is not serializable")


def _issue_owner_capability(store, operation_ref, core_boot_id):
    key = (store.vault_id, operation_ref.kind, operation_ref.id,
           operation_ref.version, operation_ref.sha256)
    with _OWNER_LOCK:
        if key in _OWNER_CAPABILITIES:
            raise ProviderSemanticError("semantic operation owner already issued")
        _OWNER_CAPABILITIES[key] = _OperationOwnerCapability(
            store.vault_id, operation_ref, core_boot_id)


def take_operation_owner_capability(store, operation_ref):
    key = (store.vault_id, operation_ref.kind, operation_ref.id,
           operation_ref.version, operation_ref.sha256)
    with _OWNER_LOCK:
        return _OWNER_CAPABILITIES.pop(key, None)


def _refs(value):
    found = set()
    def walk(item):
        if type(item) is dict:
            if set(item) == {"kind", "id", "version", "sha256"}:
                found.add(EntityRef.from_dict(item)); return
            if set(item) == {"vault_id", "purpose", "sha256", "size"}:
                return
            for child in item.values(): walk(child)
        elif type(item) is list:
            for child in item: walk(child)
    walk(value)
    return tuple(sorted(found, key=lambda ref: canonical_json(ref.as_dict())))


def _record(store, *, kind, tag, owner_uuid, ordinal=0, content, created_at_utc,
            parent_refs=None):
    if type(store) is not DomainStore:
        raise ProviderSemanticError("exact DomainStore required")
    roots = store.roots()
    value = {"schema_version": tag, **content}
    return ImmutableRecord.create(kind=kind,
        id=semantic_record_id(store.vault_id, tag, owner_uuid, ordinal), version=1,
        created_at_utc=created_at_utc, actor_ref=roots.actor,
        parent_refs=_refs(value) if parent_refs is None else parent_refs,
        purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy, content=value)


def _seal(store, **kwargs):
    record = _record(store, **kwargs)
    return store.put(record)


def _artifact_blob(record):
    content = record.body["content"]
    for name in ("blob_ref", "blob"):
        if type(content.get(name)) is dict:
            try: return BlobRef.from_dict(content[name])
            except ValueError: pass
    raise ProviderSemanticError("artifact has no exact blob")


def _semantic_content(store, value, tag, *, kind=None):
    try:
        ref = EntityRef.from_dict(value)
        record = store.get(ref)
    except (TypeError, ValueError, KeyError):
        raise ProviderSemanticError("terminal result graph is invalid") from None
    if ((kind is not None and record.body["kind"] != kind)
            or record.body["content"].get("schema_version") != tag):
        raise ProviderSemanticError("terminal result graph is invalid")
    return ref, record.body["content"]


def _validate_terminal_graph(store, operation_ref, result, response_ref):
    operation_ref, operation = _semantic_content(store, operation_ref.as_dict(),
        "provider-semantic-operation-v1", kind="validation_report")
    request = operation["request"]
    request_sha256 = sha256(canonical_json(request)).hexdigest()
    if (operation.get("request_sha256") != request_sha256
            or result.get("request_id") != request["request_id"]
            or result.get("operation") != request["operation"]):
        raise ProviderSemanticError("terminal result graph is invalid")

    response = None
    if response_ref is not None:
        response_ref, response = _semantic_content(store, response_ref.as_dict(),
            "provider-semantic-response-v1", kind="validation_report")
        if response["operation_ref"] != operation_ref.as_dict():
            raise ProviderSemanticError("terminal result graph is invalid")
        category = response["failure_class"]
        if category is not None:
            error = result.get("error")
            expected = {"permission_denied": "permission_denied",
                "deadline_exceeded": "deadline_exceeded",
                "resource_exhausted": "resource_exhausted",
                "unsupported_capability": "unsupported_capability",
                "integrity_failed": "integrity_failed",
                "dependency_unavailable": "dependency_unavailable",
                "cancelled": "cancelled", "internal_failure": "internal_failure"}[category]
            if request["operation"] == "model_step":
                if response["cancel_observed"]:
                    coherent = (result["terminal"] == "cancelled"
                                and error is not None and error["code"] == "cancelled")
                elif response["phase"] == "not_sent":
                    coherent = (result["terminal"] == "failed"
                                and error is not None and error["code"] == expected)
                else:
                    coherent = (result["terminal"] == "unknown" and error is not None
                                and error["code"] == "external_effect_unknown")
            else:
                coherent = (result["terminal"] == "failed" and error is not None
                            and error["code"] == expected)
            if not coherent:
                raise ProviderSemanticError("terminal result graph is invalid")

    output = result["output"]
    provider_response = output.get("provider_response_ref")
    if provider_response is not None:
        if response_ref is None or provider_response != response_ref.as_dict():
            raise ProviderSemanticError("terminal result graph is invalid")

    output_usage = output.get("usage_report_ref")
    canonical_usage = result["usage"].get("provider_report_ref")
    if output_usage != canonical_usage:
        raise ProviderSemanticError("terminal result graph is invalid")
    if output_usage is not None:
        usage_ref, usage = _semantic_content(store, output_usage,
            "provider-semantic-usage-v1", kind="validation_report")
        if (usage["operation_ref"] != operation_ref.as_dict() or response_ref is None
                or usage["response_ref"] != response_ref.as_dict()
                or canonical_usage != usage_ref.as_dict()):
            raise ProviderSemanticError("terminal result graph is invalid")

    effect_value = result["effect"]
    effect_receipt = effect_value.get("effect_receipt_ref")
    if effect_receipt is not None:
        effect_ref, effect = _semantic_content(store, effect_receipt,
            "provider-semantic-effect-v1", kind="validation_report")
        if (effect["operation_ref"] != operation_ref.as_dict() or response_ref is None
                or effect["response_ref"] != response_ref.as_dict()
                or effect["request_sha256"] != request_sha256
                or effect["effect_state"] != effect_value["effect_state"]
                or effect["remote_outcome"] != effect_value["remote_outcome"]
                or effect_receipt != effect_ref.as_dict()):
            raise ProviderSemanticError("terminal result graph is invalid")

    if request["operation"] == "model_step" and result["terminal"] == "succeeded":
        frozen_ref, frozen = _semantic_content(store, operation["frozen_ref"],
            "provider-semantic-frozen-v1", kind="frozen_turn")
        input_bytes = []
        for binding in frozen["artifact_input_bindings"]:
            artifact = store.get(EntityRef.from_dict(binding["artifact_ref"]))
            input_bytes.append(store.read_blob(_artifact_blob(artifact), purpose="operational"))
        from ..workers.provider_semantic_codec import encode_text_body
        expected_proposal_sha256 = sha256(encode_text_body(
            frozen, tuple(input_bytes))).hexdigest()
        if (output.get("provider_id") != "claude_api"
                or output.get("model_id") != request["input"]["model_id"]
                or response_ref is None or output_usage is None
                or response is None or response["failure_class"] is not None
                or response["phase"] != "terminal_observed"
                or type(response["status"]) is not int
                or not 200 <= response["status"] < 300
                or response["observed_model"] != output["model_id"]
                or response["stop_reason"] != "end_turn"
                or response["raw_blob"] is None
                or response["proposal_sha256"] != expected_proposal_sha256
                or request["input"]["frozen_turn_ref"] != frozen_ref.as_dict()):
            raise ProviderSemanticError("terminal result graph is invalid")
        content_refs = output.get("content_block_refs", [])
        expected_artifacts = []
        for ordinal, value in enumerate(content_refs):
            output_ref, content = _semantic_content(store, value,
                "provider-semantic-output-v1", kind="artifact")
            if (content["operation_ref"] != operation_ref.as_dict()
                    or content["ordinal"] != ordinal):
                raise ProviderSemanticError("terminal result graph is invalid")
            expected_artifacts.append({"artifact_ref": output_ref.as_dict(),
                "role": "model_content", "media_type": "text/plain",
                "content_digest": content["content_digest"],
                "byte_count": content["byte_count"], "omissions_ref": None})
        if result["artifacts"] != expected_artifacts:
            raise ProviderSemanticError("terminal result graph is invalid")
    elif request["operation"] == "catalog" and result["terminal"] == "succeeded":
        _, catalog = _semantic_content(store, output.get("catalog_ref"),
            "provider-semantic-catalog-v1", kind="model_catalog")
        if catalog["operation_ref"] != operation_ref.as_dict():
            raise ProviderSemanticError("terminal result graph is invalid")
    elif request["operation"] == "status" and result["terminal"] == "succeeded" \
            and output.get("terminal_result_ref") is not None:
        _, target_terminal = _semantic_content(store, output["terminal_result_ref"],
            "provider-semantic-terminal-v1", kind="validation_report")
        if target_terminal["operation_ref"] != request["input"]["operation_ref"]:
            raise ProviderSemanticError("terminal result graph is invalid")


def seal_frozen(store, *, command_id, content, created_at_utc):
    validate_frozen_content(content)
    total = 0
    for binding in content["artifact_input_bindings"]:
        record = store.get(EntityRef.from_dict(binding["artifact_ref"]))
        if record.body["kind"] != "artifact":
            raise ProviderSemanticError("input ref is not an artifact")
        blob = _artifact_blob(record)
        data = store.read_blob(blob, purpose="operational")
        try: data.decode("utf-8")
        except UnicodeDecodeError: raise ProviderSemanticError("input is not UTF-8") from None
        total += len(data)
    if total > MAX_INPUT_BYTES:
        raise ProviderSemanticError("aggregate input exceeds profile")
    return _seal(store, kind="frozen_turn", tag="provider-semantic-frozen-v1",
                 owner_uuid=command_id, content={k: v for k, v in content.items() if k != "schema_version"},
                 created_at_utc=created_at_utc)


def seal_operation(store, *, config_ref, request, core_boot_id, reservation_ref, created_at_utc):
    semantic_request_key(request)
    request_id = request["request_id"]
    input_value = request.get("input", {})
    frozen = input_value.get("frozen_turn_ref") if request.get("operation") == "model_step" else None
    envelope = None
    if frozen is not None:
        frozen_record = store.get(EntityRef.from_dict(frozen))
        envelope = frozen_record.body["content"]["execution_envelope_ref"]
    return _seal(store, kind="validation_report", tag="provider-semantic-operation-v1",
        owner_uuid=request_id, content={"request": request, "config_ref": config_ref.as_dict(),
        "request_sha256": sha256(canonical_json(request)).hexdigest(), "core_boot_id": core_boot_id,
        "frozen_ref": frozen, "envelope_ref": envelope,
        "reservation_ref": None if reservation_ref is None else reservation_ref.as_dict()},
        created_at_utc=created_at_utc)


def admit_operation(store, *, config_ref, request, core_boot_id, reservation_ref,
                    semantic_key, created_at_utc):
    """Admit one immutable request observation with the profile's narrow replay rules."""
    expected_key = semantic_request_key(request)
    if semantic_key != expected_key:
        raise ProviderSemanticError("caller semantic key is not canonical request identity")
    request_id = request["request_id"]
    existing = load_operation(store, request_id)
    if existing is not None:
        content = existing.body["content"]
        if (content["request"] != request
                or content["config_ref"] != config_ref.as_dict()):
            raise ProviderSemanticError("same request identity changed immutable input")
        if request.get("operation") == "model_step":
            _require_model_index(store, existing.ref, request, semantic_key)
        return existing.ref, True
    frozen = request.get("input", {}).get("frozen_turn_ref") \
        if request.get("operation") == "model_step" else None
    envelope = None
    if frozen is not None:
        envelope = store.get(EntityRef.from_dict(frozen)).body["content"]["execution_envelope_ref"]
    operation = _record(store, kind="validation_report", tag="provider-semantic-operation-v1",
        owner_uuid=request_id, content={"request": request, "config_ref": config_ref.as_dict(),
        "request_sha256": sha256(canonical_json(request)).hexdigest(), "core_boot_id": core_boot_id,
        "frozen_ref": frozen, "envelope_ref": envelope,
        "reservation_ref": None if reservation_ref is None else reservation_ref.as_dict()},
        created_at_utc=created_at_utc)
    model_step = request.get("operation") == "model_step"
    index = None
    if model_step:
        semantic_owner = str(uuid5(NAMESPACE_URL, semantic_key))
        retained_index = _load_by_owner(store, kind="validation_report",
            tag="provider-semantic-idempotency-v1", owner_uuid=semantic_owner)
        if retained_index is not None:
            raise ProviderSemanticError("model semantic key already has a durable owner")
        index = _record(store, kind="validation_report", tag="provider-semantic-idempotency-v1",
            owner_uuid=semantic_owner, content={"request_id": request_id,
            "request_sha256": sha256(canonical_json(request)).hexdigest(),
            "operation_ref": operation.ref.as_dict()}, created_at_utc=created_at_utc)
    inserted = False
    index_conflict = False
    with _writer(), store._connection(write=True) as db:
        roots = store._read_roots(db)
        operation_row = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? "
            "AND kind=? AND id=? AND version=?", (roots.genesis.id, operation.ref.kind,
            operation.ref.id, operation.ref.version)).fetchone()
        if operation_row is None:
            if index is not None:
                index_row = db.execute("SELECT 1 FROM domain_records WHERE vault_id=? "
                    "AND kind=? AND id=? AND version=?", (roots.genesis.id, index.ref.kind,
                    index.ref.id, index.ref.version)).fetchone()
                index_conflict = index_row is not None
            if not index_conflict:
                store._put_in_transaction(db, operation)
                if index is not None:
                    store._put_in_transaction(db, index)
                inserted = True
    if index_conflict:
        # Rehydrate through the checked public graph path before treating the durable
        # semantic-key row that won the writer race as authoritative.
        _load_by_owner(store, kind="validation_report",
            tag="provider-semantic-idempotency-v1", owner_uuid=semantic_owner)
        raise ProviderSemanticError("model semantic key already has a durable owner")
    if not inserted:
        retained = load_operation(store, request_id)
        if retained is None:  # pragma: no cover - checked writer disposition invariant
            raise ProviderSemanticError("semantic operation disposition was lost")
        content = retained.body["content"]
        if (content["request"] != request
                or content["config_ref"] != config_ref.as_dict()):
            raise ProviderSemanticError("same request identity changed immutable input")
        if model_step:
            _require_model_index(store, retained.ref, request, semantic_key)
        return retained.ref, True
    _issue_owner_capability(store, operation.ref, core_boot_id)
    return operation.ref, False


def _require_model_index(store, operation_ref, request, semantic_key=None):
    if request.get("operation") != "model_step":
        raise ProviderSemanticError("model index requested for non-model operation")
    expected_key = semantic_request_key(request)
    if semantic_key is not None and semantic_key != expected_key:
        raise ProviderSemanticError("model semantic key changed")
    owner = str(uuid5(NAMESPACE_URL, expected_key))
    index = _load_by_owner(store, kind="validation_report",
        tag="provider-semantic-idempotency-v1", owner_uuid=owner)
    digest = sha256(canonical_json(request)).hexdigest()
    if index is None:
        raise ProviderSemanticError("model operation lacks its semantic index")
    content = index.body["content"]
    if (content.get("request_id") != request["request_id"]
            or content.get("request_sha256") != digest
            or content.get("operation_ref") != operation_ref.as_dict()):
        raise ProviderSemanticError("model semantic index does not join operation")
    return index


def require_model_operation_index(store, operation_ref):
    operation = store.get(operation_ref).body["content"]
    if operation.get("schema_version") != "provider-semantic-operation-v1":
        raise ProviderSemanticError("wrong model operation record")
    return _require_model_index(store, operation_ref, operation["request"])


def load_operation(store, request_id):
    """Resolve the deterministic operation identity, then revalidate through DomainStore."""
    if type(store) is not DomainStore:
        raise ProviderSemanticError("exact DomainStore required")
    record_id = semantic_record_id(store.vault_id, "provider-semantic-operation-v1", request_id)
    with store._connection() as db:  # the store's checked, same-vault read transaction
        row = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind=? "
                         "AND id=? AND version=1",
                         (store.vault_id, "validation_report", record_id)).fetchone()
    if row is None:
        return None
    return store.get(EntityRef("validation_report", record_id, 1, row["sha256"]))


def _load_by_owner(store, *, kind, tag, owner_uuid, ordinal=0):
    record_id = semantic_record_id(store.vault_id, tag, owner_uuid, ordinal)
    with store._connection() as db:
        row = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind=? "
                         "AND id=? AND version=1", (store.vault_id, kind, record_id)).fetchone()
    if row is None:
        return None
    return store.get(EntityRef(kind, record_id, 1, row["sha256"]))


def load_terminal(store, operation_ref):
    record = _load_by_owner(store, kind="validation_report", tag="provider-semantic-terminal-v1",
                            owner_uuid=_operation_owner(store, operation_ref))
    if record is not None:
        content = record.body["content"]
        response = (None if content["response_ref"] is None
                    else EntityRef.from_dict(content["response_ref"]))
        _validate_terminal_graph(store, operation_ref, content["result"], response)
    return record


def load_cancel_intent(store, target_operation_ref):
    return _load_by_owner(store, kind="validation_report", tag="provider-semantic-cancel-intent-v1",
                          owner_uuid=_operation_owner(store, target_operation_ref))


def seal_cancel_intent(store, *, target_operation_ref, first_cancel_operation_ref,
                       first_request_sha256, reason_class, core_boot_id, created_at_utc):
    return _seal(store, kind="validation_report", tag="provider-semantic-cancel-intent-v1",
        owner_uuid=_operation_owner(store, target_operation_ref), content={
            "target_operation_ref": target_operation_ref.as_dict(),
            "first_cancel_operation_ref": first_cancel_operation_ref.as_dict(),
            "first_request_sha256": first_request_sha256, "reason_class": reason_class,
            "core_boot_id": core_boot_id}, created_at_utc=created_at_utc)


def seal_cancel_operation_and_intent(store, *, config_ref, request, core_boot_id,
                                     target_operation_ref, reason_class, created_at_utc):
    """Durably insert the first cancel operation and its target fence in one transaction."""
    if (request.get("operation") != "cancel"
            or request.get("input", {}).get("operation_ref") != target_operation_ref.as_dict()):
        raise ProviderSemanticError("cancel target does not match request")
    semantic_request_key(request)
    operation = _record(store, kind="validation_report", tag="provider-semantic-operation-v1",
        owner_uuid=request["request_id"], content={"request": request,
        "config_ref": config_ref.as_dict(),
        "request_sha256": sha256(canonical_json(request)).hexdigest(),
        "core_boot_id": core_boot_id, "frozen_ref": None, "envelope_ref": None,
        "reservation_ref": None}, created_at_utc=created_at_utc)
    intent = _record(store, kind="validation_report", tag="provider-semantic-cancel-intent-v1",
        owner_uuid=_operation_owner(store, target_operation_ref), content={
        "target_operation_ref": target_operation_ref.as_dict(),
        "first_cancel_operation_ref": operation.ref.as_dict(),
        "first_request_sha256": sha256(canonical_json(request)).hexdigest(),
        "reason_class": reason_class, "core_boot_id": core_boot_id},
        created_at_utc=created_at_utc)
    with _writer(), store._connection(write=True) as db:
        store._put_in_transaction(db, operation)
        store._put_in_transaction(db, intent)
    return operation.ref, intent.ref


def _operation_owner(store, operation_ref):
    record = store.get(operation_ref)
    if record.body["content"].get("schema_version") != "provider-semantic-operation-v1":
        raise ProviderSemanticError("wrong operation record")
    return record.body["content"]["request"]["request_id"]


def seal_page(store, *, operation_ref, index, after_id, raw, first_id, last_id,
              has_more, model_ids, created_at_utc):
    if (type(index) is not int or not 0 <= index < 20 or type(raw) is not bytes or not raw
            or type(has_more) is not bool or type(model_ids) not in (tuple, list)
            or len(model_ids) > 100):
        raise ProviderSemanticError("invalid retained catalog page")
    for value in model_ids:
        identifier(value)
    if after_id is not None: identifier(after_id)
    if first_id is not None: identifier(first_id)
    if last_id is not None: identifier(last_id)
    if ((not model_ids and (first_id is not None or last_id is not None or has_more))
            or (model_ids and (first_id != model_ids[0] or last_id != model_ids[-1]))):
        raise ProviderSemanticError("page cursor projection disagrees with rows")
    blob = store.put_blob(raw, purpose="operational")
    return _seal(store, kind="validation_report", tag="provider-semantic-page-v1",
        owner_uuid=_operation_owner(store, operation_ref), ordinal=index,
        content={"operation_ref": operation_ref.as_dict(), "index": index,
        "after_id": after_id, "raw_blob": blob.as_dict(), "raw_sha256": blob.sha256,
        "raw_size": blob.size, "first_id": first_id, "last_id": last_id,
        "has_more": has_more, "model_ids": list(model_ids)}, created_at_utc=created_at_utc)


def seal_capability(store, *, operation_ref, page_ref, global_ordinal, model_index,
                    model_id, text_policy_ref, compatibility_ref, observed_at,
                    valid_until, projection, created_at_utc):
    if (type(global_ordinal) is not int or not 0 <= global_ordinal < 256
            or type(model_index) is not int or not 0 <= model_index < 100
            or type(projection) is not dict or set(projection) != {"id", "display_name",
                "created_at", "capabilities", "max_input_tokens", "max_tokens"}
            or projection["id"] != model_id):
        raise ProviderSemanticError("invalid capability projection")
    identifier(model_id)
    return _seal(store, kind="validation_report", tag="provider-semantic-capability-v1",
        owner_uuid=_operation_owner(store, operation_ref), ordinal=global_ordinal,
        content={"operation_ref": operation_ref.as_dict(), "page_ref": page_ref.as_dict(),
        "model_index": model_index, "model_id": model_id,
        "text_policy_ref": text_policy_ref.as_dict(),
        "compatibility_ref": None if compatibility_ref is None else compatibility_ref.as_dict(),
        "observed_at": observed_at, "valid_until": valid_until, "projection": projection},
        created_at_utc=created_at_utc)


def seal_catalog(store, *, operation_ref, connection_ref, fetched_at, expires_at,
                 page_refs, complete, models, eligible_model_ids, excluded, created_at_utc):
    if (type(page_refs) not in (tuple, list) or not 1 <= len(page_refs) <= 20
            or type(complete) is not bool or type(models) is not list or len(models) > 256
            or type(eligible_model_ids) is not list or type(excluded) is not list
            or len(eligible_model_ids) + len(excluded) != len(models)):
        raise ProviderSemanticError("invalid durable catalog projection")
    model_ids = [row.get("model_id") for row in models if type(row) is dict]
    if (len(model_ids) != len(models) or len(model_ids) != len(set(model_ids))
            or model_ids != list(eligible_model_ids) + [item.get("model_id") for item in excluded]
            and set(model_ids) != set(eligible_model_ids) | {item.get("model_id") for item in excluded}):
        raise ProviderSemanticError("catalog eligibility does not partition rows")
    parents = tuple(sorted({operation_ref, connection_ref, *page_refs},
                           key=lambda ref: canonical_json(ref.as_dict())))
    return _seal(store, kind="model_catalog", tag="provider-semantic-catalog-v1",
        owner_uuid=_operation_owner(store, operation_ref), content={
        "operation_ref": operation_ref.as_dict(), "connection_ref": connection_ref.as_dict(),
        "fetched_at": fetched_at, "expires_at": expires_at,
        "page_refs": [ref.as_dict() for ref in page_refs], "complete": complete,
        "models": models, "eligible_model_ids": eligible_model_ids, "excluded": excluded},
        parent_refs=parents, created_at_utc=created_at_utc)


def seal_catalog_traversal(store, *, operation_ref, connection_ref, text_policy_ref,
                           compatibility_by_model, traversal, raw_pages, fetched_at,
                           expires_at, created_at_utc):
    """Reparse retained source pages and seal their exact bounded evidence graph."""
    from ..workers.provider_semantic_codec import CatalogTraversal, advance_catalog, parse_model_page
    if (type(traversal) is not CatalogTraversal or type(raw_pages) is not tuple
            or len(raw_pages) != len(traversal.pages) or not traversal.complete
            or type(compatibility_by_model) is not dict):
        raise ProviderSemanticError("incomplete catalog evidence")
    evidence = {}
    for ref, tag in ((connection_ref, "provider-semantic-connection-v1"),
                     (text_policy_ref, "provider-semantic-text-policy-v1")):
        evidence[tag] = store.get(ref).body["content"]
        if evidence[tag].get("schema_version") != tag:
            raise ProviderSemanticError("catalog evidence variant mismatch")
    policy = evidence["provider-semantic-text-policy-v1"]
    source_blob = BlobRef.from_dict(policy["source_blob"])
    scope = policy["scope_model_ids"]
    def instant(value):
        try: return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            raise ProviderSemanticError("invalid catalog evidence time") from None
    retrieved, reviewed, fetched, policy_expiry, catalog_expiry = map(instant, (
        policy["retrieved_at"], policy["reviewed_at"], fetched_at, policy["valid_until"],
        expires_at))
    if (policy.get("source_sha256") != source_blob.sha256
            or type(scope) is not list or not 1 <= len(scope) <= 256
            or scope != sorted(set(scope), key=lambda item: item.encode())
            or not retrieved <= reviewed <= fetched < policy_expiry
            or not fetched < catalog_expiry <= policy_expiry
            or policy_expiry - reviewed > timedelta(days=7)):
        raise ProviderSemanticError("invalid reviewed text policy")
    text_scope = set(scope)
    request_policy_sha256 = sha256(canonical_json({"profile_id": PROFILE,
        "api_version": API_VERSION, "auth": "api-key", "effort": None, "tools": False,
        "cache": False, "thinking_override": None, "success_stop": "end_turn",
        "input_media_types": ["text/plain"], "max_inputs": 4, "max_output_blocks": 4,
        "max_output_tokens": 8192, "deadline_ms": 30000})).hexdigest()
    operation = store.get(operation_ref).body["content"]
    if (operation.get("schema_version") != "provider-semantic-operation-v1"
            or operation["request"].get("operation") != "catalog"):
        raise ProviderSemanticError("catalog operation variant mismatch")
    config = store.get(EntityRef.from_dict(operation["config_ref"])).body["content"]
    if (config.get("schema_version") != "provider-semantic-config-v1"
            or config.get("connection_ref") != connection_ref.as_dict()
            or config.get("text_policy_ref") != text_policy_ref.as_dict()):
        raise ProviderSemanticError("catalog config evidence mismatch")
    ttl = config["config"]["port_config"]["catalog_ttl_seconds"]
    expected_catalog_expiry = min(policy_expiry, fetched + timedelta(seconds=ttl))
    if catalog_expiry != expected_catalog_expiry:
        raise ProviderSemanticError("catalog expiry is not derived from admitted config TTL")
    compatibility_set = store.get(EntityRef.from_dict(
        config["compatibility_set_ref"])).body["content"]
    admitted_compatibility = ({canonical_json(item) for item in
                              compatibility_set.get("observation_refs", [])}
                             if compatibility_set.get("schema_version")
                             == "provider-semantic-compatibility-set-v1"
                             and compatibility_set.get("connection_ref")
                             == connection_ref.as_dict() else set())
    if any(canonical_json(ref.as_dict()) not in admitted_compatibility
           for ref in compatibility_by_model.values()):
        raise ProviderSemanticError("catalog compatibility is absent from admitted set")
    rebuilt = CatalogTraversal()
    parsed_pages = []
    for raw in raw_pages:
        page = parse_model_page(raw)
        rebuilt = advance_catalog(rebuilt, page)
        parsed_pages.append(page)
    if rebuilt != traversal:
        raise ProviderSemanticError("retained raw pages disagree with traversal projection")
    page_refs, rows, eligible, excluded = [], [], [], []
    ordinal = 0
    for index, (raw, page) in enumerate(zip(raw_pages, parsed_pages, strict=True)):
        after_id = None if index == 0 else parsed_pages[index - 1].last_id
        page_ref = seal_page(store, operation_ref=operation_ref, index=index, after_id=after_id,
            raw=raw, first_id=page.first_id, last_id=page.last_id, has_more=page.has_more,
            model_ids=[model.id for model in page.models], created_at_utc=created_at_utc)
        page_refs.append(page_ref)
        for model_index, model in enumerate(page.models):
            projection = {"id": model.id, "display_name": model.display_name,
                "created_at": model.created_at, "capabilities": model.capabilities.as_dict(),
                "max_input_tokens": model.max_input_tokens.as_dict(),
                "max_tokens": model.max_tokens.as_dict()}
            compatibility = compatibility_by_model.get(model.id)
            if compatibility is not None:
                compatibility_content = store.get(compatibility).body["content"]
                if (compatibility_content.get("schema_version")
                        != "provider-semantic-compatibility-v1"
                        or compatibility_content.get("profile_id")
                        != "claude-api-text-semantic-v1"
                        or compatibility_content.get("connection_ref") != connection_ref.as_dict()
                        or compatibility_content.get("model_id") != model.id
                        or compatibility_content.get("request_policy_sha256")
                        != request_policy_sha256
                        or compatibility_content.get("outcome") != "complete_text"):
                    raise ProviderSemanticError("catalog compatibility evidence mismatch")
                observed = instant(compatibility_content["observed_at"])
                compatibility_expiry = instant(compatibility_content["expires_at"])
                if (not observed <= fetched < compatibility_expiry
                        or compatibility_expiry - observed > timedelta(days=7)):
                    raise ProviderSemanticError("expired catalog compatibility evidence")
            capability = seal_capability(store, operation_ref=operation_ref, page_ref=page_ref,
                global_ordinal=ordinal, model_index=model_index, model_id=model.id,
                text_policy_ref=text_policy_ref, compatibility_ref=compatibility,
                observed_at=fetched_at, valid_until=expires_at, projection=projection,
                created_at_utc=created_at_utc)
            effort = []
            if model.capabilities.state == "value":
                value = model.capabilities.value["effort"]
                if value["supported"]:
                    effort = [name for name in ("high", "low", "max", "medium")
                              if value[name]["supported"]]
                    if (value["xhigh"]["state"] == "value"
                            and value["xhigh"]["value"]["supported"]):
                        effort.append("xhigh")
                    effort.sort(key=lambda item: item.encode())
            in_text_scope = model.id in text_scope
            modalities = ["text"] if in_text_scope else []
            rows.append({"model_id": model.id, "display_name": model.display_name,
                "modalities": modalities, "effort_values": effort,
                "capability_evidence_ref": capability.as_dict()})
            if (model.capabilities.state != "value"):
                excluded.append({"model_id": model.id, "reason": "capability_unknown"})
            elif (model.max_input_tokens.state != "value" or model.max_tokens.state != "value"):
                excluded.append({"model_id": model.id, "reason": "limits_unknown"})
            elif not in_text_scope:
                excluded.append({"model_id": model.id, "reason": "text_scope_unproved"})
            elif compatibility is None:
                excluded.append({"model_id": model.id, "reason": "profile_unproved"})
            else:
                eligible.append(model.id)
            ordinal += 1
    return seal_catalog(store, operation_ref=operation_ref, connection_ref=connection_ref,
        fetched_at=fetched_at, expires_at=expires_at, page_refs=page_refs, complete=True,
        models=rows, eligible_model_ids=eligible, excluded=excluded,
        created_at_utc=created_at_utc)


def seal_response(store, *, operation_ref, exchange_id, proposal_sha256, status, raw, phase,
                  observed_model, stop_reason, cancel_observed, created_at_utc,
                  failure_class=None):
    blob = None if raw is None else store.put_blob(raw, purpose="operational")
    return _seal(store, kind="validation_report", tag="provider-semantic-response-v1",
        owner_uuid=_operation_owner(store, operation_ref), content={"operation_ref": operation_ref.as_dict(),
        "exchange_id": exchange_id, "proposal_sha256": proposal_sha256, "status": status,
        "raw_blob": None if blob is None else blob.as_dict(), "raw_sha256": None if blob is None else blob.sha256,
        "raw_size": 0 if blob is None else blob.size, "phase": phase, "observed_model": observed_model,
        "stop_reason": stop_reason, "cancel_observed": cancel_observed,
        "failure_class": failure_class}, created_at_utc=created_at_utc)


def seal_usage(store, *, operation_ref, response_ref, usage, created_at_utc):
    return _seal(store, kind="validation_report", tag="provider-semantic-usage-v1",
        owner_uuid=_operation_owner(store, operation_ref), content={"operation_ref": operation_ref.as_dict(),
        "response_ref": response_ref.as_dict(), **usage}, created_at_utc=created_at_utc)


def seal_effect(store, *, operation_ref, response_ref, request_sha256, effect_state,
                remote_outcome, created_at_utc):
    return _seal(store, kind="validation_report", tag="provider-semantic-effect-v1",
        owner_uuid=_operation_owner(store, operation_ref), content={"operation_ref": operation_ref.as_dict(),
        "response_ref": response_ref.as_dict(), "request_sha256": request_sha256,
        "effect_state": effect_state, "remote_outcome": remote_outcome,
        "source": "gateway_observation"}, created_at_utc=created_at_utc)


def seal_output(store, *, operation_ref, ordinal, data, created_at_utc):
    blob = store.put_blob(data, purpose="operational")
    return _seal(store, kind="artifact", tag="provider-semantic-output-v1",
        owner_uuid=_operation_owner(store, operation_ref), ordinal=ordinal,
        content={"operation_ref": operation_ref.as_dict(), "ordinal": ordinal, "blob_ref": blob.as_dict(),
                 "media_type": "text/plain", "content_digest": blob.sha256, "byte_count": blob.size},
        created_at_utc=created_at_utc)


def seal_terminal(store, *, operation_ref, result, response_ref, created_at_utc):
    operation = store.get(operation_ref).body["content"]
    validate_canonical_port_shape("result", result)
    if (result["request_id"] != operation["request"]["request_id"]
            or result["operation"] != operation["request"]["operation"]):
        raise ProviderSemanticError("terminal result does not match operation identity")
    _validate_terminal_graph(store, operation_ref, result, response_ref)
    return _seal(store, kind="validation_report", tag="provider-semantic-terminal-v1",
        owner_uuid=_operation_owner(store, operation_ref), content={"operation_ref": operation_ref.as_dict(),
        "result": result, "response_ref": None if response_ref is None else response_ref.as_dict()},
        created_at_utc=created_at_utc)


def load_semantic_record(store, ref):
    return store.get(ref)


__all__ = [name for name in globals() if name.startswith("seal_") or name.startswith("load_")]
