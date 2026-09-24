"""The owner's Claude API connection on the supported app (direct-adapter profile).

The owner enters an API key once. It lives only in this server process's memory
(`InMemoryCredentialVault`): it is never written to disk, the database, a log,
an event or a response, and a restart forgets it, so the owner enters it again.
Storing, reading state and forgetting the key make no provider call. The owner's
explicit catalog refresh reads `GET /v1/models` (free) through the official
adapter; choosing a model seals an owner-authored `model_choice` record naming a
model that the refreshed catalog actually listed. Generation happens only in the
run executor, under a run consent and its budget.

This is the direct-adapter profile: the key and the provider call share the
control-plane process. The release boundary (a separate credential gateway and
provider worker, T090/T087) is not this, and nothing here claims it is.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from functools import wraps
from uuid import NAMESPACE_URL, uuid5

from ..adapters.claude_api import (
    CatalogError,
    ClaudeAPIAdapter,
    ClaudeBinding,
    ModelSelection,
)
from ..adapters.keychain import InMemoryCredentialVault, validate_credential_secret
from ..domain.public_events import _append_event_in_transaction, _assert_event_schema
from ..domain.refs import EntityRef, ObjectRef
from ..domain.schemas import ImmutableRecord
from ..domain.store import _writer
from .owner_auth import OwnerAuthError
from .run_approvals import _authenticate_owner, _bound_pair, _owner_actor_ref

__all__ = ["CHOICE_SCHEMA", "ClaudeConnection", "ClaudeConnectionError"]

CHOICE_SCHEMA = "claude-model-choice-v1"
CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "conflict",
                   "unavailable", "provider_unavailable", "provider_rejected"})
MAX_CATALOG_MODELS = 200


class ClaudeConnectionError(ValueError):
    def __init__(self, code="invalid_input"):
        if code not in CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (ClaudeConnectionError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - provider and storage detail stays private
            raise ClaudeConnectionError("unavailable") from None

    return invoke


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


class ClaudeConnection:
    """One owner, one in-memory Claude key, one current catalog snapshot."""

    def __init__(self, domain_store, owner_authority, *, transport=None, clock_ms=None):
        self._domain, self._owner = _bound_pair(domain_store, owner_authority, ClaudeConnectionError)
        self._vault = InMemoryCredentialVault()
        self._adapter = ClaudeAPIAdapter(vault=self._vault, transport=transport, clock_ms=clock_ms)
        self._lock = threading.RLock()
        self._binding = None
        self._snapshot = None

    # --- state, read by the executor --------------------------------------------------

    def current(self):
        """(adapter, binding, snapshot) for generation, or provider_unavailable."""

        with self._lock:
            if self._binding is None or self._snapshot is None:
                raise ClaudeConnectionError("provider_unavailable")
            return self._adapter, self._binding, self._snapshot

    def model_selection(self, model_id: str) -> ModelSelection:
        adapter, binding, snapshot = self.current()
        del adapter
        return ModelSelection(binding_id=binding.binding_id, catalog_id=snapshot.catalog_id,
                              model_id=model_id)

    @_closed
    def state(self, request) -> dict:
        self._owner.authenticate_bound(request.session)
        with self._lock:
            snapshot = self._snapshot
            return {
                "provider": "claude", "mode": "api", "key_present": self._binding is not None,
                "key_storage": "server_memory_only",
                "catalog": None if snapshot is None else {
                    "model_ids": [model.id for model in snapshot.models][:MAX_CATALOG_MODELS],
                    "fetched_at_ms": snapshot.fetched_at_ms},
            }

    # --- the owner's commands ---------------------------------------------------------

    @_closed
    def store_key(self, request, secret) -> dict:
        _authenticate_owner(self._owner, request)
        if type(secret) is not str:
            raise ClaudeConnectionError("invalid_input")
        try:
            validate_credential_secret(secret)
        except (TypeError, ValueError):
            raise ClaudeConnectionError("invalid_input") from None
        with self._lock:
            if self._binding is not None:
                ref = self._vault.rotate(self._binding.credential_ref, secret)
            else:
                ref = self._vault.store("claude", secret)
            self._binding = ClaudeBinding(credential_ref=ref)
            self._snapshot = None  # a new key never inherits the previous catalog
        del secret
        return self.state(request)

    @_closed
    def forget_key(self, request) -> dict:
        _authenticate_owner(self._owner, request)
        with self._lock:
            if self._binding is not None:
                self._vault.delete(self._binding.credential_ref)
            self._binding = self._snapshot = None
        return self.state(request)

    @_closed
    def refresh_catalog(self, request) -> dict:
        """The owner's explicit catalog read: one `GET /v1/models` pass, no generation."""

        _authenticate_owner(self._owner, request)
        with self._lock:
            if self._binding is None:
                raise ClaudeConnectionError("provider_unavailable")
            try:
                snapshot = self._adapter.fetch_catalog(self._binding, explicit_action=True)
            except CatalogError as error:
                code = ("provider_rejected" if error.failure.category in {"authentication", "permission"}
                        else "provider_unavailable")
                raise ClaudeConnectionError(code) from None
            self._snapshot = snapshot
        return self.state(request)

    @_closed
    def choose_model(self, request, model_id) -> dict:
        """Seal the owner's model choice; the model must be in the refreshed catalog."""

        _authenticate_owner(self._owner, request)
        if type(model_id) is not str or not 1 <= len(model_id) <= 128:
            raise ClaudeConnectionError("invalid_input")
        with self._lock:
            if self._binding is None or self._snapshot is None:
                raise ClaudeConnectionError("provider_unavailable")
            listed = {model.id: model for model in self._snapshot.models}
            if model_id not in listed:
                raise ClaudeConnectionError("not_found")
            selected = self._adapter.validate_selection(
                ModelSelection(binding_id=self._binding.binding_id, catalog_id=self._snapshot.catalog_id,
                               model_id=model_id), self._snapshot, self._binding)
        record_id = str(uuid5(NAMESPACE_URL, f"deeptwin:claude-model-choice:{model_id}"))
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            _assert_event_schema(db, roots.genesis.id)
            existing = db.execute("SELECT version, sha256 FROM domain_records WHERE vault_id=? "
                                  "AND kind='model_choice' AND id=?", (roots.genesis.id, record_id)).fetchone()
            if existing is not None:
                ref = EntityRef("model_choice", record_id, existing["version"], existing["sha256"])
                return {**self.state(request), "model_choice_ref": ref.as_dict()}
            actor_ref = _owner_actor_ref(db, actor)
            stamp = _stamp()
            record = ImmutableRecord.create(
                kind="model_choice", id=record_id, version=1, created_at_utc=stamp, actor_ref=actor_ref,
                parent_refs=(), purpose="operational", access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy,
                content={"schema_version": CHOICE_SCHEMA, "provider": "claude", "mode": "api",
                         "model_id": model_id, "capabilities": ["text"],
                         "model_max_tokens": selected.max_tokens, "chosen_at_utc": stamp})
            self._domain._put_in_transaction(db, record)
            _append_event_in_transaction(
                db, vault_id=roots.genesis.id, recorded_at_utc=stamp, observed_at_utc=stamp,
                actor_kind="human", actor_ref=actor_ref, event_type="model.selected",
                object_refs=(ObjectRef(record.ref.kind, record.ref.id, record.ref.version, record.ref.sha256),),
                correlation_id=record_id, causation_id=None, status="succeeded", error_code=None,
                public_metadata={"provider": "claude", "auth_mode": "api", "revision": 1}, private_evidence_refs=(),
                retention_class="core", policy_ref=roots.access_policy)
        return {**self.state(request), "model_choice_ref": record.ref.as_dict()}
