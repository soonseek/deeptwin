"""Durable extension bindings, rollback retention and the owner's installation inventory (T087).

This is the service behind the `extension-bindings-v1` owner routes
(`app/api/extension_bindings.py`). It follows data-model §3.1 and contracts/api.md (Extensions):

- **Binding history/head.** A binding slot is keyed by the exact five-field `BindingSlotKeyV1`
  and its recomputed canonical digest; `extension_id` is the candidate value, never a key field.
  Every bind, supersession, disable and rollback appends one immutable
  `extension-binding-revision-v1` record (`app/domain/extension_binding.py`); the slot's head is
  its newest revision `{revision, binding_record_digest, state}`. Each command carries the exact
  expected current head (``null`` for an absent slot) and is refused ``binding_head_stale`` without
  any write when the head moved, so two candidates for one slot compete only through that CAS,
  while slots that differ in any key field (port version, scope, purpose, slot id or selector)
  coexist.
- **Rollback retention.** A supersession or disable atomically creates revision 1 `retained` for
  the exact displaced active binding revision. A rollback names a strict backward ancestor and its
  exact retained head, re-checks the target's qualification, consumes the retention (revision 2
  `consumed`) and appends a new active revision in the same transaction; the binding it displaces
  gets its own retained head. The owner-only release CAS-advances `retained → released` with the
  exact closed command/result of contracts/api.md without changing the binding or installation
  head or deleting history; a released target can no longer be rolled back.
- **Qualification.** The only durable qualification record this server has is the sealed
  provider-transport qualification (`provider-transport-qualification-record-v1`, a
  `validation_report`) over a matched verified-installation conformance run. A bind names it by
  exact ref; it must still be current (the shipped manifest digest and the run's
  verified-installation admission unchanged). No other port has a qualification record yet, so
  binding any other port is refused ``qualification_missing``.
- **Target scope.** `target_scope` is the closed `{instance_id, environment_id, work_id, node_id,
  purpose}` of this instance; `target_scope_fingerprint` is the canonical digest of that scope under
  `extension-binding-target-scope-v1` (this slice's definition; the contracts fix the key field but
  not its derivation). Only the provider selector family is admitted (its fields are fixed by the
  contracts); other families are refused ``selector_unsupported``.

Every mutation commits its records, the command replay record and its contract events in one
domain-store transaction: `extension.binding_{activated,superseded,disabled,rolled_back}` for the head
move and `extension.rollback_retention_{created,consumed,released}` for each retention revision
(`app/domain/events.py`; the exact slot/revision/retention records are the events' object refs). A command id is replay-safe:
the same id and request answers the committed result, another request under it is refused
``command_conflict``. Nothing here contacts a provider or deploys anything.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from ..domain import extension_binding as values
from ..domain.extension_binding import (
    BINDING_SCHEMA,
    COMMAND_SCHEMA,
    RETENTION_SCHEMA,
    BindingValueError,
    digest_of,
)
from ..domain.public_events import _append_event_in_transaction
from ..domain.refs import (
    DomainContractError,
    EntityRef,
    ObjectRef,
    canonical_json,
    parse_canonical,
    uuid_string,
)
from ..domain.schemas import ImmutableRecord
from ..domain.store import StorageError, _writer
from .port_contracts import PORT_CONTRACTS

SLOT_SCHEMA = "extension-binding-slot-v1"
SLOT_LIST_SCHEMA = "extension-binding-list-v1"
SLOT_KEY_SCHEMA = "extension-binding-slot-key-v1"
INSTALLATION_LIST_SCHEMA = "extension-installation-list-v1"
RESULT_SCHEMA = "extension-binding-command-result-v1"
MAX_RECORDS = 4096
MAX_SLOTS = 256
MAX_PAGE = 50
DEFAULT_PAGE = 20
QUALIFICATION_RECORD_SCHEMA = "provider-transport-qualification-record-v1"
CODES = (
    "invalid_input", "unauthenticated", "access_denied", "not_found", "binding_head_stale",
    "binding_unchanged", "retention_head_stale", "rollback_target_invalid", "retention_not_retained",
    "target_mismatch", "qualification_missing", "qualification_not_current", "extension_mismatch",
    "selector_mismatch", "selector_unsupported", "command_conflict", "capacity", "unavailable",
)
_BIND_FIELDS = frozenset({"command_id", "extension_id", "qualification_ref", "binding_slot_key",
                          "binding_slot_key_digest", "capability_selector", "target_scope",
                          "expected_current_binding_head"})
_DISABLE_FIELDS = frozenset({"command_id", "extension_id", "binding_slot_key", "binding_slot_key_digest",
                             "expected_current_binding_head"})
_ROLLBACK_FIELDS = frozenset({"command_id", "extension_id", "binding_slot_key", "binding_slot_key_digest",
                              "expected_current_binding_head", "target_binding_revision_ref",
                              "expected_retention_head"})
RELEASE_FIELDS = frozenset({"command_id", "extension_id", "binding_slot_key", "binding_slot_key_digest",
                            "expected_current_binding_head", "target_binding_revision_ref",
                            "target_installation_ref", "target_service_tuple", "expected_retention_head",
                            "reason"})
RELEASE_RESULT_FIELDS = ("command_id", "extension_id", "binding_slot_key", "binding_slot_key_digest",
                         "expected_current_binding_head", "target_binding_revision_ref",
                         "target_installation_ref", "target_service_tuple", "expected_retention_head",
                         "new_retention_revision", "new_retention_record_digest", "state")
BINDING_EVENTS = {"bind": "extension.binding_activated", "supersede": "extension.binding_superseded",
                  "disable": "extension.binding_disabled", "rollback": "extension.binding_rolled_back"}
RETENTION_EVENTS = {"retained": "extension.rollback_retention_created",
                    "released": "extension.rollback_retention_released",
                    "consumed": "extension.rollback_retention_consumed"}
_COMPOSE_FIELDS = frozenset({"port_contract_version", "binding_slot_id", "target_scope",
                             "capability_selector"})


class BindingError(ValueError):
    def __init__(self, code="invalid_input"):
        self.code = code if code in CODES else "unavailable"
        super().__init__(self.code)


def _require(condition, code="invalid_input"):
    if not condition:
        raise BindingError(code)


def _now():
    now = datetime.now(UTC)
    return now, now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z", int(now.timestamp() * 1000)


def release_warning(target, target_extension_id, head):
    """The server's exact warning the owner confirms before a release (shown verbatim)."""
    return (f"보존을 해제하면 바인딩 수정본 {target['revision']}({target_extension_id})으로는 더 이상 "
            f"롤백할 수 없습니다. 현재 바인딩(수정본 {head['revision']}, {head['state']})과 설치, "
            "모든 바인딩 이력은 바뀌지 않고 계속 보입니다.")


def _page(limit, after, *, pattern):
    if limit is None:
        limit = DEFAULT_PAGE
    else:
        _require(type(limit) is str and limit.isdecimal() and len(limit) <= 3)
        limit = int(limit)
    _require(1 <= limit <= MAX_PAGE)
    _require(after is None or (type(after) is str and pattern(after)))
    return limit, after


def _hex(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _uuid_ok(value):
    try:
        uuid_string(value)
        return True
    except (TypeError, ValueError, DomainContractError):
        return False


class PersistentExtensionBindings:
    """``transport`` is the composed :class:`PersistentTransportQualification` (its domain store,
    owner authentication and qualification evidence); ``instance_id`` the owner profile's id.
    ``resolver`` replaces the transport-qualification resolver (tests only)."""

    def __init__(self, transport, *, instance_id, resolver=None):
        from .provider_transport_qualification import PersistentTransportQualification

        if type(transport) is not PersistentTransportQualification:
            raise BindingError("unavailable")
        if type(instance_id) is not str or len(instance_id) != 32:
            raise BindingError("unavailable")
        self._transport = transport
        self._domain = transport._domain
        self._instance_id = instance_id
        self._resolver = resolver if resolver is not None else self._resolve_transport_qualification
        self._reconciliation = None

    # -- startup reconciliation -------------------------------------------------------------

    def reconcile_startup(self):
        """Check every slot's head against its retention, command and event records
        (`binding_reconciliation`). Every command commits in one transaction, so a crash in the
        middle of one leaves nothing of it; a finding means records outside that invariant. It is
        kept for the inspection, the dispatch resolver refuses that slot, and one
        `recovery.reconciled` event records the count. Nothing is repaired or re-derived."""
        from .binding_reconciliation import reconcile

        report = reconcile(self._domain, clock_ms=lambda: _now()[2])
        self._reconciliation = report
        if report["state"] != "consistent":
            _now_value, stamp, _ms = _now()
            with _writer(), self._domain._connection(write=True) as db:
                roots = self._domain._read_roots(db)
                _append_event_in_transaction(
                    db, vault_id=roots.genesis.id, recorded_at_utc=stamp, observed_at_utc=stamp,
                    actor_kind="system", actor_ref=roots.actor, event_type="recovery.reconciled",
                    object_refs=(), correlation_id=str(uuid4()), causation_id=None,
                    status="succeeded" if report["state"] == "inconsistent" else "unknown", error_code=None,
                    public_metadata={"recovered_count": 0,
                                     "unknown_count": len(report["inconsistent_slots"])},
                    private_evidence_refs=(), retention_class="core", policy_ref=roots.access_policy)
        return report

    @property
    def reconciliation(self):
        return self._reconciliation

    # -- authentication and storage -------------------------------------------------------

    def _authenticate(self, request, db, *, read):
        from .provider_conformance_contracts import ConformanceError

        try:
            return self._transport._conformance._authenticate(request, db, read=read)
        except ConformanceError as error:
            raise BindingError(error.code if error.code in CODES else "unavailable") from None

    def _versions(self, db, roots, record_id):
        rows = db.execute("SELECT version, sha256, purpose, body FROM domain_records WHERE vault_id=? "
                          "AND kind='extension_binding' AND id=? ORDER BY version",
                          (roots.genesis.id, record_id)).fetchall()
        result = []
        for index, row in enumerate(rows, start=1):
            ref = EntityRef("extension_binding", record_id, row["version"], row["sha256"])
            record = ImmutableRecord.from_bytes(row["body"], expected_ref=ref)
            _require(row["version"] == index and row["purpose"] == "operational", "unavailable")
            result.append((ref, record.body["content"]))
        return result

    def _slot_history(self, db, roots, slot_digest):
        history = self._versions(db, roots, values.slot_record_id(slot_digest))
        previous = None
        for ref, content in history:
            _require(content.get("schema_version") == BINDING_SCHEMA
                     and content["binding_slot_key_digest"] == slot_digest, "unavailable")
            if previous is not None:
                _require(content["previous_revision"] == {"revision": previous.version,
                                                     "binding_record_digest": previous.sha256}
                         and content["binding_slot_key"] == history[0][1]["binding_slot_key"], "unavailable")
            previous = ref
        return history

    @staticmethod
    def _head(history):
        if not history:
            return None
        ref, content = history[-1]
        return {"revision": ref.version, "binding_record_digest": ref.sha256, "state": content["state"]}

    def _retention(self, db, roots, slot_digest, target_digest):
        history = self._versions(db, roots, values.retention_record_id(slot_digest, target_digest))
        for _ref, content in history:
            _require(content.get("schema_version") == RETENTION_SCHEMA
                     and content["binding_slot_key_digest"] == slot_digest
                     and content["target_binding_revision"]["binding_record_digest"] == target_digest,
                     "unavailable")
        return history

    @staticmethod
    def _retention_head(history):
        if not history:
            return None
        ref, content = history[-1]
        return {"revision": ref.version, "retention_record_digest": ref.sha256, "state": content["state"]}

    def _slots(self, db, roots):
        """Every binding slot's history (bounded by the record capacity)."""
        rows = db.execute("SELECT id, body FROM domain_records WHERE vault_id=? AND kind='extension_binding' "
                          "AND version=1", (roots.genesis.id,)).fetchall()
        slots = {}
        for row in rows:
            content = parse_canonical(row["body"])["content"]
            if content.get("schema_version") == BINDING_SCHEMA:
                digest = content["binding_slot_key_digest"]
                slots[digest] = self._slot_history(db, roots, digest)
        _require(len(slots) <= MAX_SLOTS, "unavailable")
        return dict(sorted(slots.items()))

    def _put(self, db, roots, actor_ref, *, record_id, version, parents, content, stamp):
        record = ImmutableRecord.create(
            kind="extension_binding", id=record_id, version=version, created_at_utc=stamp,
            actor_ref=actor_ref, parent_refs=tuple(parents), purpose="operational",
            access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
            content=content)
        self._domain._put_in_transaction(db, record)
        return record.ref

    def _capacity(self, db, roots, extra):
        count = db.execute("SELECT COUNT(*) FROM domain_records WHERE vault_id=? AND kind='extension_binding'",
                           (roots.genesis.id,)).fetchone()[0]
        _require(count + extra <= MAX_RECORDS, "capacity")

    def _replayed(self, db, roots, action, command_id, request_sha256):
        history = self._versions(db, roots, values.command_record_id(command_id))
        if not history:
            return None
        content = history[0][1]
        _require(content.get("schema_version") == COMMAND_SCHEMA, "unavailable")
        _require(content["action"] == action and content["request_sha256"] == request_sha256,
                 "command_conflict")
        return parse_canonical(content["result_json"].encode())

    @staticmethod
    def _object(ref):
        return ObjectRef("extension_binding", ref.id, ref.version, ref.sha256)

    def _emit(self, db, roots, actor_ref, *, event_type, command_id, key, refs, metadata, stamp):
        contract = PORT_CONTRACTS[key["port_contract_version"]]
        _append_event_in_transaction(
            db, vault_id=roots.genesis.id, recorded_at_utc=stamp, observed_at_utc=stamp,
            actor_kind="human", actor_ref=actor_ref, event_type=event_type,
            object_refs=tuple(dict.fromkeys(self._object(ref) for ref in refs)), correlation_id=command_id,
            causation_id=None, status="succeeded", error_code=None,
            public_metadata={"extension_kind": contract.extension_kind, "trust_tier": contract.trust_tier,
                             "port_contract_version": key["port_contract_version"], "purpose": key["purpose"],
                             **metadata},
            private_evidence_refs=(), retention_class="core", policy_ref=roots.access_policy)

    def _binding_event(self, db, roots, actor_ref, *, command_id, key, action, ref, previous_ref, affected, stamp):
        """`extension.binding_{activated,superseded,disabled,rolled_back}` for one committed head move."""
        self._emit(db, roots, actor_ref, event_type=BINDING_EVENTS[action], command_id=command_id, key=key,
                   refs=[ref] + ([] if previous_ref is None else [previous_ref]),
                   metadata={"revision": ref.version,
                             "previous_revision": 0 if previous_ref is None else previous_ref.version,
                             "affected_environment_count": affected}, stamp=stamp)

    def _retention_event(self, db, roots, actor_ref, *, command_id, key, retention_ref, target_ref, head_ref,
                         previous_state, state, stamp):
        """`extension.rollback_retention_{created,released,consumed}` for one retention revision."""
        self._emit(db, roots, actor_ref, event_type=RETENTION_EVENTS[state], command_id=command_id, key=key,
                   refs=[retention_ref, target_ref, head_ref],
                   metadata={"retention_revision": retention_ref.version, "target_revision": target_ref.version,
                             "binding_revision": head_ref.version, "previous_state": previous_state,
                             "state": state}, stamp=stamp)

    # -- qualification --------------------------------------------------------------------

    def _resolve_transport_qualification(self, db, roots, qualification_ref):
        """The sealed provider-transport qualification named by exact ref, still current, and the
        verified installation it qualifies."""
        from .provider_conformance_contracts import ConformanceError
        from .provider_transport_qualification import TransportQualificationError

        ref = EntityRef.from_dict(qualification_ref)
        row = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind=? AND id=? AND version=?",
                         (roots.genesis.id, ref.kind, ref.id, ref.version)).fetchone()
        _require(ref.kind == "validation_report" and row is not None and row["sha256"] == ref.sha256,
                 "qualification_missing")
        content = self._domain._load(db, ref, roots)[0].body["content"]
        _require(content.get("schema_version") == QUALIFICATION_RECORD_SCHEMA, "qualification_missing")
        try:
            manifest = self._transport._manifest()
            evidence = content["installation_conformance"]
            current = self._transport._installation_evidence(db, evidence["command_id"])
        except (TransportQualificationError, ConformanceError):
            raise BindingError("qualification_not_current") from None
        _require(manifest.manifest_sha256 == content["manifest_sha256"] and current == evidence,
                 "qualification_not_current")
        verified = EntityRef.from_dict(evidence["verified_installation_ref"])
        staged = EntityRef.from_dict(evidence["staged_installation_ref"])
        installed = self._domain._load(db, verified, roots)[0].body["content"]
        anchor = self._domain._load(db, staged, roots)[0].body["content"]
        return {
            "qualification_ref": ref.as_dict(), "port_contract_version": "provider-port-v1",
            "provider_id": content["provider"], "extension_id": installed["extension_id"],
            "installation_ref": verified.as_dict(),
            "target_installation_ref": {"extension_id": installed["extension_id"],
                                        "revision": verified.version,
                                        "installation_record_digest": verified.sha256},
            "service_tuple": {name: anchor[name] for name in values.SERVICE_TUPLE_FIELDS},
        }

    def _qualified(self, db, roots, qualification_ref):
        try:
            resolved = self._resolver(db, roots, qualification_ref)
        except BindingError:
            raise
        except (DomainContractError, StorageError, KeyError, TypeError, ValueError):
            raise BindingError("qualification_missing") from None
        return resolved

    # -- values ---------------------------------------------------------------------------

    def _slot_values(self, key_value, key_digest, selector_value, scope_value, *, path_digest=None):
        try:
            key, digest = values.slot_key(key_value, key_digest)
            port = key["port_contract_version"]
            scope = values.target_scope(scope_value, instance_id=self._instance_id)
        except BindingValueError:
            raise BindingError("invalid_input") from None
        _require(path_digest is None or path_digest == digest)
        try:
            selector = values.capability_selector(port, selector_value)
        except BindingValueError:
            if values.SELECTOR_FAMILIES.get(port) is None:
                raise BindingError("selector_unsupported") from None
            raise BindingError("invalid_input") from None
        _require(digest_of(selector) == key["capability_selector_digest"]
                 and values.scope_fingerprint(scope) == key["target_scope_fingerprint"]
                 and scope["purpose"] == key["purpose"])
        return key, digest, selector, scope

    @staticmethod
    def _key_only(key_value, key_digest, path_digest):
        try:
            key, digest = values.slot_key(key_value, key_digest)
        except BindingValueError:
            raise BindingError("invalid_input") from None
        _require(digest == path_digest)
        return key, digest

    @staticmethod
    def _expected(value, *, allow_absent, states=values.BINDING_STATES):
        if value is None:
            _require(allow_absent)
            return None
        try:
            return values.binding_head(value, states=states)
        except BindingValueError:
            raise BindingError("invalid_input") from None

    @staticmethod
    def _command_id(payload):
        _require(_uuid_ok(payload.get("command_id")))
        return payload["command_id"]

    @staticmethod
    def _extension_id(value):
        try:
            return values._match(value, values._EXTENSION_ID)
        except BindingValueError:
            raise BindingError("invalid_input") from None

    # -- reads ----------------------------------------------------------------------------

    def compose_slot_key(self, request, payload):
        """The exact `BindingSlotKeyV1` and digest the server computes for a logical slot, and that
        slot's current head (no write). The target scope is given without `instance_id`: the
        server adds this instance's id, so the returned `target_scope` is the one a bind echoes."""
        _require(type(payload) is dict and set(payload) == _COMPOSE_FIELDS)
        port = payload["port_contract_version"]
        _require(type(port) is str and port in PORT_CONTRACTS)
        given = payload["target_scope"]
        _require(type(given) is dict and set(given) == {"environment_id", "work_id", "node_id", "purpose"})
        try:
            slot_id = values._match(payload["binding_slot_id"], values._NODE_ID)
            scope = values.target_scope({"instance_id": self._instance_id, **given}, instance_id=self._instance_id)
        except BindingValueError:
            raise BindingError("invalid_input") from None
        try:
            selector = values.capability_selector(port, payload["capability_selector"])
        except BindingValueError:
            if values.SELECTOR_FAMILIES.get(port) is None:
                raise BindingError("selector_unsupported") from None
            raise BindingError("invalid_input") from None
        key = {"port_contract_version": port, "target_scope_fingerprint": values.scope_fingerprint(scope),
               "purpose": scope["purpose"], "binding_slot_id": slot_id,
               "capability_selector_digest": digest_of(selector)}
        key, digest = values.slot_key(key)
        with _writer(), self._domain._connection(write=True) as db:
            self._authenticate(request, db, read=False)
            roots = self._domain._read_roots(db)
            head = self._head(self._slot_history(db, roots, digest))
        return {"schema_version": SLOT_KEY_SCHEMA, "binding_slot_key": key, "binding_slot_key_digest": digest,
                "capability_selector": selector, "capability_selector_digest": key["capability_selector_digest"],
                "target_scope": scope, "target_scope_fingerprint": key["target_scope_fingerprint"],
                "current_binding_head": head}

    @staticmethod
    def _revision_row(ref, content):
        return {"revision": ref.version, "binding_record_digest": ref.sha256, "record_ref": ref.as_dict(),
                "state": content["state"], "action": content["action"], "extension_id": content["extension_id"],
                "target_installation_ref": content["target_installation"],
                "installation_ref": content["installation_ref"], "service_tuple": content["service_tuple"],
                "qualification_ref": content["qualification_ref"], "previous_ref": content["previous_revision"],
                "supersedes_ref": content["supersedes_revision"], "rollback_of_ref": content["rollback_of_revision"],
                "command_id": content["command_id"], "recorded_at_ms": content["recorded_at_ms"]}

    def _qualification_current(self, db, roots, content):
        try:
            resolved = self._qualified(db, roots, content["qualification_ref"])
        except BindingError:
            return False
        return resolved["installation_ref"] == content["installation_ref"]

    def _slot_projection(self, db, roots, digest, history, slots):
        first = history[0][1]
        head = self._head(history)
        current = history[-1][1]
        key = first["binding_slot_key"]
        retentions = []
        for ref, content in history:
            if content["state"] != "active":
                continue
            retained = self._retention(db, roots, digest, ref.sha256)
            if not retained:
                continue
            state = self._retention_head(retained)
            target = {"revision": ref.version, "binding_record_digest": ref.sha256}
            retentions.append({
                "target_binding_revision_ref": target, "target_extension_id": content["extension_id"],
                "target_installation_ref": content["target_installation"],
                "target_service_tuple": content["service_tuple"], "retention_head": state,
                "history": [{"revision": r.version, "retention_record_digest": r.sha256, "state": c["state"],
                             "observed_current_binding_head": c["observed_current_binding_head"],
                             "reason": c["reason"], "command_id": c["command_id"],
                             "recorded_at_ms": c["recorded_at_ms"]} for r, c in retained],
                "rollback_available": state["state"] == "retained",
                "qualification_current": (state["state"] == "retained"
                                          and self._qualification_current(db, roots, content)),
                "release_warning": (release_warning(target, content["extension_id"], head)
                                    if state["state"] == "retained" else None),
            })
        coexisting = []
        for other, other_history in slots.items():
            other_key = other_history[0][1]["binding_slot_key"]
            if other == digest or any(other_key[name] != key[name] for name in
                                      ("port_contract_version", "target_scope_fingerprint", "purpose")):
                continue
            other_head = self._head(other_history)
            coexisting.append({"binding_slot_key_digest": other, "binding_slot_id": other_key["binding_slot_id"],
                               "capability_selector_digest": other_key["capability_selector_digest"],
                               "head": other_head, "extension_id": other_history[-1][1]["extension_id"]})
        holders = {}
        for ref, content in history:
            holders.setdefault(content["extension_id"], []).append(ref.version)
        return {
            "schema_version": SLOT_SCHEMA, "binding_slot_key": key, "binding_slot_key_digest": digest,
            "logical_slot": {"binding_slot_id": key["binding_slot_id"], "purpose": key["purpose"],
                             "port_contract_version": key["port_contract_version"]},
            "capability_selector": first["capability_selector"],
            "capability_selector_digest": key["capability_selector_digest"],
            "target_scope": first["target_scope"], "target_scope_fingerprint": key["target_scope_fingerprint"],
            "extension_kind": first["extension_kind"], "trust_tier": first["trust_tier"],
            "head": head,
            "current": {"extension_id": current["extension_id"], "state": current["state"],
                        "target_installation_ref": current["target_installation"],
                        "installation_ref": current["installation_ref"],
                        "qualification_ref": current["qualification_ref"],
                        "service_tuple": current["service_tuple"],
                        "qualification_current": self._qualification_current(db, roots, current)},
            "history": [self._revision_row(ref, content) for ref, content in history],
            "rollback_retentions": retentions,
            "coexisting_slots": coexisting,
            "competition": {"current_holder": current["extension_id"] if current["state"] == "active" else None,
                            "holders": [{"extension_id": name, "revisions": revisions}
                                        for name, revisions in holders.items()]},
            "affected_environments": self._affected(db, roots, digest, head, first),
            "reconciliation": self._slot_reconciliation(db, roots, digest, history),
            "links": {"self": f"/api/v1/extensions/bindings/{digest}"},
        }

    def _slot_reconciliation(self, db, roots, digest, history):
        from .binding_reconciliation import slot_findings

        findings = slot_findings(db, roots, digest, history)
        startup = self._reconciliation
        return {"state": "inconsistent" if findings else "consistent", "findings": findings,
                "startup_state": None if startup is None else startup["state"],
                "startup_findings": None if startup is None else startup["inconsistent_slots"].get(digest, []),
                "dispatch": "refused" if findings else "admitted_when_head_matches"}

    @staticmethod
    def _affected(db, roots, digest, head, first):
        from .binding_heads import BindingDispatchRefused, bound_environment_versions

        try:
            versions = bound_environment_versions(db, roots, digest, head)
        except BindingDispatchRefused:
            raise BindingError("unavailable") from None
        return {"target_environment_id": first["target_scope"]["environment_id"],
                "bound_environment_versions": versions,
                "needs_re_preparation": sorted({item["environment_id"] for item in versions
                                                if item["needs_re_preparation"]}),
                "basis": "environment_records_recorded_binding_revisions"}

    def slot(self, request, slot_digest):
        _require(_hex(slot_digest))
        with _writer(), self._domain._connection(write=True) as db:
            self._authenticate(request, db, read=True)
            roots = self._domain._read_roots(db)
            slots = self._slots(db, roots)
            _require(slot_digest in slots, "not_found")
            return self._slot_projection(db, roots, slot_digest, slots[slot_digest], slots)

    def bindings(self, request, *, limit=None, after=None):
        limit, after = _page(limit, after, pattern=_hex)
        with _writer(), self._domain._connection(write=True) as db:
            self._authenticate(request, db, read=True)
            roots = self._domain._read_roots(db)
            slots = self._slots(db, roots)
            ordered = [digest for digest in slots if after is None or digest > after]
            items = []
            for digest in ordered[:limit]:
                history = slots[digest]
                key = history[0][1]["binding_slot_key"]
                current = history[-1][1]
                retained = sum(
                    1 for ref, content in history if content["state"] == "active"
                    and (self._retention_head(self._retention(db, roots, digest, ref.sha256)) or {}
                         ).get("state") == "retained")
                items.append({
                    "binding_slot_key_digest": digest, "binding_slot_key": key,
                    "logical_slot": {"binding_slot_id": key["binding_slot_id"], "purpose": key["purpose"],
                                     "port_contract_version": key["port_contract_version"]},
                    "capability_selector": history[0][1]["capability_selector"],
                    "target_scope": history[0][1]["target_scope"], "head": self._head(history),
                    "extension_id": current["extension_id"], "trust_tier": current["trust_tier"],
                    "extension_kind": current["extension_kind"], "retained_rollback_count": retained,
                    "links": {"self": f"/api/v1/extensions/bindings/{digest}"}})
            more = len(ordered) > limit
        startup = self._reconciliation
        return {"schema_version": SLOT_LIST_SCHEMA, "limit": limit, "items": items,
                "next_after": items[-1]["binding_slot_key_digest"] if more else None,
                "reconciliation": None if startup is None else {
                    "state": startup["state"], "checked_slots": startup["checked_slots"],
                    "inconsistent_slot_digests": sorted(startup["inconsistent_slots"]),
                    "checked_at_ms": startup["checked_at_ms"]}}

    def installations(self, request, *, limit=None, after=None):
        """Every extension installation (staged revision 1, verified revision 2) with its trust
        tier from the port contract, service tuple, staging request/receipt and current bindings."""
        limit, after = _page(limit, after, pattern=_uuid_ok)
        with _writer(), self._domain._connection(write=True) as db:
            self._authenticate(request, db, read=True)
            roots = self._domain._read_roots(db)
            ids = [row[0] for row in db.execute(
                "SELECT DISTINCT id FROM domain_records WHERE vault_id=? AND kind='extension_installation' "
                "ORDER BY id", (roots.genesis.id,)).fetchall()]
            ordered = [value for value in ids if after is None or value > after]
            slots = self._slots(db, roots)
            items = [self._installation_row(db, roots, value, slots) for value in ordered[:limit]]
        return {"schema_version": INSTALLATION_LIST_SCHEMA, "limit": limit, "items": items,
                "next_after": items[-1]["installation_id"] if len(ordered) > limit else None}

    def _candidate_port(self, db, manifest_digest):
        try:
            row = db.execute("SELECT candidate_id FROM extension_candidate_index WHERE manifest_digest=? "
                             "ORDER BY candidate_id LIMIT 1", (manifest_digest,)).fetchone()
        except Exception:  # noqa: BLE001 - no candidate registry tables: no candidate link
            return None, None
        if row is None:
            return None, None
        from .candidate_records import load_candidate

        full = db.execute("SELECT * FROM extension_candidate_index WHERE candidate_id=?",
                          (row[0],)).fetchone()
        value = load_candidate(self._domain, db, full)[0]
        return row[0], value["manifest"]["port_contract_version"]

    def _installation_row(self, db, roots, installation_id, slots):
        rows = db.execute("SELECT version, sha256 FROM domain_records WHERE vault_id=? AND "
                          "kind='extension_installation' AND id=? ORDER BY version",
                          (roots.genesis.id, installation_id)).fetchall()
        refs = [EntityRef("extension_installation", installation_id, row[0], row[1]) for row in rows]
        _require(refs and refs[0].version == 1 and len(refs) <= 2, "unavailable")
        anchor = self._domain._load(db, refs[0], roots)[0].body["content"]
        verified = None
        if len(refs) == 2:
            verified = self._domain._load(db, refs[1], roots)[0].body["content"]
            _require(verified.get("previous_record_digest") == refs[0].sha256, "unavailable")
        provider = anchor.get("schema_version") == "extension-provider-installation-anchor-v1"
        candidate_id, candidate_port = self._candidate_port(db, anchor["manifest_digest"])
        port = "provider-port-v1" if provider else candidate_port
        contract = PORT_CONTRACTS.get(port)
        request_ref = anchor["request_ref"]
        head = refs[-1]
        bound = [digest for digest, history in slots.items()
                 if history[-1][1]["installation_ref"] == head.as_dict()]
        return {
            "installation_id": installation_id, "extension_id": anchor["extension_id"],
            "extension_version": None if verified is None else verified["extension_version"],
            "state": "verified" if verified is not None else "staged", "revision": head.version,
            "head_ref": head.as_dict(), "staged_installation_ref": refs[0].as_dict(),
            "verified_installation_ref": None if verified is None else refs[1].as_dict(),
            "target_installation_ref": {"extension_id": anchor["extension_id"], "revision": head.version,
                                        "installation_record_digest": head.sha256},
            "platform": anchor["platform"],
            "port_contract_version": port,
            "extension_kind": None if contract is None else contract.extension_kind,
            "trust_tier": None if contract is None else contract.trust_tier,
            "trust_tier_basis": None if contract is None else "port_contract",
            "service_tuple": {name: anchor[name] for name in values.SERVICE_TUPLE_FIELDS},
            "candidate_id": candidate_id,
            "staging": {
                "state": "receipt_consumed", "staging_authority": anchor["staging_authority"],
                "request_ref": request_ref, "receipt_ref": anchor["receipt_ref"],
                "consume_command_id": anchor["consume_command_id"], "installed_at": anchor["installed_at"],
                "request_link": ("/api/v1/deployment/provider-requests/" if provider
                                 else "/api/v1/deployment/requests/") + request_ref["id"]},
            "verified_at_ms": None if verified is None else verified["verified_at_ms"],
            "active_binding_slot_digests": bound,
        }

    # -- owner acts -----------------------------------------------------------------------

    def _result(self, action, command_id, extension_id, key, digest, head_before, revision_ref, content,
                retention=None, consumed=None, affected=()):
        return {"schema_version": RESULT_SCHEMA, "action": action, "command_id": command_id,
                "extension_id": extension_id, "binding_slot_key": key, "binding_slot_key_digest": digest,
                "expected_current_binding_head": head_before,
                "binding_head": {"revision": revision_ref.version, "binding_record_digest": revision_ref.sha256,
                                 "state": content["state"]},
                "environments_needing_re_preparation": affected,
                "binding_action": content["action"], "retained": retention, "consumed": consumed}

    def _append(self, db, roots, actor_ref, *, action, command_id, request_sha256, extension_id, key, digest,
                history, expected, fields, stamp, now_ms, retain_head=True, consume=None):
        """Append one binding revision over the exact expected head; create the retained head for a
        displaced active revision and consume a rollback target's retention, in this transaction."""
        head = self._head(history)
        new_revision = 1 if head is None else head["revision"] + 1
        previous = None if head is None else {"revision": head["revision"],
                                              "binding_record_digest": head["binding_record_digest"]}
        content = {"schema_version": BINDING_SCHEMA, "extension_id": extension_id, "revision": new_revision,
                   "binding_slot_key": key, "binding_slot_key_digest": digest,
                   "expected_previous_head": head, "previous_revision": previous,
                   "command_id": command_id, "recorded_at_ms": now_ms, **fields}
        parents = [EntityRef.from_dict(content["qualification_ref"])]
        if head is not None:
            parents.insert(0, history[-1][0])
        self._capacity(db, roots, 4)
        ref = self._put(db, roots, actor_ref, record_id=values.slot_record_id(digest), version=new_revision,
                        parents=parents, content=content, stamp=stamp)
        new_head = {"revision": new_revision, "binding_record_digest": ref.sha256, "state": content["state"]}
        affected = self._affected(db, roots, digest, new_head, content)["needs_re_preparation"]
        self._binding_event(db, roots, actor_ref, command_id=command_id, key=key, action=content["action"],
                            ref=ref, previous_ref=None if head is None else history[-1][0],
                            affected=len(affected), stamp=stamp)
        retained = None
        if head is not None and head["state"] == "active" and retain_head:
            displaced_ref, displaced = history[-1]
            retained_content = {
                "schema_version": RETENTION_SCHEMA, "binding_slot_key": key, "binding_slot_key_digest": digest,
                "target_binding_revision": previous, "target_extension_id": displaced["extension_id"],
                "target_installation": displaced["target_installation"],
                "target_service_tuple": displaced["service_tuple"], "state": "retained", "revision": 1,
                "expected_previous_retention_head": None, "previous_revision": None,
                "observed_current_binding_head": {"revision": new_revision, "binding_record_digest": ref.sha256,
                                                  "state": content["state"]},
                "reason": None, "command_id": command_id, "recorded_at_ms": now_ms}
            _require(not self._retention(db, roots, digest, displaced_ref.sha256), "unavailable")
            retention_ref = self._put(db, roots, actor_ref,
                                      record_id=values.retention_record_id(digest, displaced_ref.sha256),
                                      version=1, parents=[displaced_ref], content=retained_content, stamp=stamp)
            self._retention_event(db, roots, actor_ref, command_id=command_id, key=key,
                                  retention_ref=retention_ref, target_ref=displaced_ref, head_ref=ref,
                                  previous_state="absent", state="retained", stamp=stamp)
            retained = {"target_binding_revision_ref": previous,
                        "retention_head": {"revision": 1, "retention_record_digest": retention_ref.sha256,
                                           "state": "retained"}}
        consumed = None
        if consume is not None:
            target, target_ref, retention_history = consume
            prior_ref, prior = retention_history[-1]
            consumed_content = {
                **prior, "state": "consumed", "revision": 2,
                "expected_previous_retention_head": {"revision": 1, "retention_record_digest": prior_ref.sha256,
                                                     "state": "retained"},
                "previous_revision": {"revision": 1, "retention_record_digest": prior_ref.sha256},
                "observed_current_binding_head": {"revision": new_revision, "binding_record_digest": ref.sha256,
                                                  "state": "active"},
                "reason": None, "command_id": command_id, "recorded_at_ms": now_ms}
            consumed_ref = self._put(db, roots, actor_ref,
                                     record_id=values.retention_record_id(digest, target["binding_record_digest"]),
                                     version=2, parents=[prior_ref, target_ref], content=consumed_content,
                                     stamp=stamp)
            self._retention_event(db, roots, actor_ref, command_id=command_id, key=key,
                                  retention_ref=consumed_ref, target_ref=target_ref, head_ref=ref,
                                  previous_state="retained", state="consumed", stamp=stamp)
            consumed = {"target_binding_revision_ref": target,
                        "retention_head": {"revision": 2, "retention_record_digest": consumed_ref.sha256,
                                           "state": "consumed"}}
        result = self._result(action, command_id, extension_id, key, digest, expected, ref, content,
                              retained, consumed, affected=list(affected))
        self._record_command(db, roots, actor_ref, action=action, command_id=command_id,
                             request_sha256=request_sha256, result=result, parent=ref, stamp=stamp)
        return result

    def _record_command(self, db, roots, actor_ref, *, action, command_id, request_sha256, result, parent, stamp):
        self._put(db, roots, actor_ref, record_id=values.command_record_id(command_id), version=1,
                  parents=[parent], stamp=stamp,
                  content={"schema_version": COMMAND_SCHEMA, "command_id": command_id, "action": action,
                           "request_sha256": request_sha256, "result_json": canonical_json(result).decode()})

    @staticmethod
    def _request_sha(action, payload, *path):
        return sha256(canonical_json({"action": action, "path": list(path), "body": payload})).hexdigest()

    def bind(self, request, payload):
        """Activate (absent or disabled head) or supersede (active head) the exact slot with the
        named current qualification's verified installation."""
        _require(type(payload) is dict and set(payload) == _BIND_FIELDS)
        command_id = self._command_id(payload)
        extension_id = self._extension_id(payload["extension_id"])
        key, digest, selector, scope = self._slot_values(
            payload["binding_slot_key"], payload["binding_slot_key_digest"], payload["capability_selector"],
            payload["target_scope"])
        expected = self._expected(payload["expected_current_binding_head"], allow_absent=True)
        try:
            qualification_ref = EntityRef.from_dict(payload["qualification_ref"]).as_dict()
        except (TypeError, ValueError, DomainContractError):
            raise BindingError("invalid_input") from None
        request_sha256 = self._request_sha("bind", payload)
        _now_value, stamp, now_ms = _now()
        with _writer(), self._domain._connection(write=True) as db:
            _actor, actor_ref = self._authenticate(request, db, read=False)
            roots = self._domain._read_roots(db)
            replay = self._replayed(db, roots, "bind", command_id, request_sha256)
            if replay is not None:
                return replay
            history = self._slot_history(db, roots, digest)
            head = self._head(history)
            _require(head == expected, "binding_head_stale")
            if head is None:
                _require(len(self._slots(db, roots)) < MAX_SLOTS, "capacity")
            port = key["port_contract_version"]
            if values.SELECTOR_FAMILIES.get(port) is None:
                raise BindingError("selector_unsupported")
            resolved = self._qualified(db, roots, qualification_ref)
            _require(resolved["port_contract_version"] == port, "qualification_missing")
            _require(resolved["extension_id"] == extension_id, "extension_mismatch")
            _require(selector["provider_id"] == resolved["provider_id"], "selector_mismatch")
            if head is not None and head["state"] == "active":
                current = history[-1][1]
                _require(not (current["installation_ref"] == resolved["installation_ref"]
                              and current["qualification_ref"] == resolved["qualification_ref"]
                              and current["extension_id"] == extension_id), "binding_unchanged")
            contract = PORT_CONTRACTS[port]
            fields = {"state": "active",
                      "action": "supersede" if head is not None and head["state"] == "active" else "bind",
                      "port_contract_version": port, "extension_kind": contract.extension_kind,
                      "trust_tier": contract.trust_tier, "capability_selector": selector, "target_scope": scope,
                      "installation_ref": resolved["installation_ref"],
                      "target_installation": resolved["target_installation_ref"],
                      "service_tuple": resolved["service_tuple"], "qualification_ref": resolved["qualification_ref"],
                      "supersedes_revision": None if head is None or head["state"] != "active" else {
                          "revision": head["revision"], "binding_record_digest": head["binding_record_digest"]},
                      "rollback_of_revision": None}
            return self._append(db, roots, actor_ref, action="bind", command_id=command_id,
                                request_sha256=request_sha256, extension_id=extension_id, key=key, digest=digest,
                                history=history, expected=expected, fields=fields, stamp=stamp, now_ms=now_ms)

    def disable(self, request, slot_digest, payload):
        """Disable the exact active head of this slot; the displaced revision is retained."""
        _require(_hex(slot_digest) and type(payload) is dict and set(payload) == _DISABLE_FIELDS)
        command_id = self._command_id(payload)
        extension_id = self._extension_id(payload["extension_id"])
        key, digest = self._key_only(payload["binding_slot_key"], payload["binding_slot_key_digest"], slot_digest)
        expected = self._expected(payload["expected_current_binding_head"], allow_absent=False,
                                  states=("active",))
        request_sha256 = self._request_sha("disable", payload, slot_digest)
        _now_value, stamp, now_ms = _now()
        with _writer(), self._domain._connection(write=True) as db:
            _actor, actor_ref = self._authenticate(request, db, read=False)
            roots = self._domain._read_roots(db)
            replay = self._replayed(db, roots, "disable", command_id, request_sha256)
            if replay is not None:
                return replay
            history = self._slot_history(db, roots, digest)
            _require(history, "not_found")
            _require(self._head(history) == expected, "binding_head_stale")
            current = history[-1][1]
            _require(current["extension_id"] == extension_id, "extension_mismatch")
            fields = {name: current[name] for name in (
                "port_contract_version", "extension_kind", "trust_tier", "capability_selector", "target_scope",
                "installation_ref", "target_installation", "service_tuple", "qualification_ref")}
            fields.update(state="disabled", action="disable", supersedes_revision=None, rollback_of_revision=None)
            return self._append(db, roots, actor_ref, action="disable", command_id=command_id,
                                request_sha256=request_sha256, extension_id=extension_id, key=key, digest=digest,
                                history=history, expected=expected, fields=fields, stamp=stamp, now_ms=now_ms)

    def rollback(self, request, slot_digest, payload):
        """Re-activate an exact retained strict-ancestor revision after re-checking its qualification."""
        _require(_hex(slot_digest) and type(payload) is dict and set(payload) == _ROLLBACK_FIELDS)
        command_id = self._command_id(payload)
        extension_id = self._extension_id(payload["extension_id"])
        key, digest = self._key_only(payload["binding_slot_key"], payload["binding_slot_key_digest"], slot_digest)
        expected = self._expected(payload["expected_current_binding_head"], allow_absent=False)
        try:
            target = values.binding_ref(payload["target_binding_revision_ref"])
            expected_retention = values.retention_head(payload["expected_retention_head"], states=("retained",))
        except BindingValueError:
            raise BindingError("invalid_input") from None
        request_sha256 = self._request_sha("rollback", payload, slot_digest)
        _now_value, stamp, now_ms = _now()
        with _writer(), self._domain._connection(write=True) as db:
            _actor, actor_ref = self._authenticate(request, db, read=False)
            roots = self._domain._read_roots(db)
            replay = self._replayed(db, roots, "rollback", command_id, request_sha256)
            if replay is not None:
                return replay
            history = self._slot_history(db, roots, digest)
            _require(history, "not_found")
            head = self._head(history)
            _require(head == expected, "binding_head_stale")
            _require(target["revision"] < head["revision"], "rollback_target_invalid")
            target_ref, target_content = history[target["revision"] - 1]
            _require(target_ref.sha256 == target["binding_record_digest"]
                     and target_content["state"] == "active", "rollback_target_invalid")
            _require(target_content["extension_id"] == extension_id, "extension_mismatch")
            retention = self._retention(db, roots, digest, target_ref.sha256)
            state = self._retention_head(retention)
            _require(state is not None and state["state"] == "retained", "retention_not_retained")
            _require(state == expected_retention, "retention_head_stale")
            resolved = self._qualified(db, roots, target_content["qualification_ref"])
            _require(resolved["installation_ref"] == target_content["installation_ref"]
                     and resolved["service_tuple"] == target_content["service_tuple"],
                     "qualification_not_current")
            fields = {name: target_content[name] for name in (
                "port_contract_version", "extension_kind", "trust_tier", "capability_selector", "target_scope",
                "installation_ref", "target_installation", "service_tuple", "qualification_ref")}
            fields.update(state="active", action="rollback",
                          supersedes_revision=None if head["state"] != "active" else {
                              "revision": head["revision"], "binding_record_digest": head["binding_record_digest"]},
                          rollback_of_revision=target)
            return self._append(db, roots, actor_ref, action="rollback", command_id=command_id,
                                request_sha256=request_sha256, extension_id=extension_id, key=key, digest=digest,
                                history=history, expected=expected, fields=fields, stamp=stamp, now_ms=now_ms,
                                consume=(target, target_ref, retention))

    def release(self, request, slot_digest, target_digest, payload):
        """`ReleaseExtensionRollbackRetention` (owner only): CAS `retained → released` for an exact
        strict-ancestor target; the binding and installation heads and all history are unchanged."""
        _require(_hex(slot_digest) and _hex(target_digest) and type(payload) is dict
                 and set(payload) == RELEASE_FIELDS)
        command_id = self._command_id(payload)
        extension_id = self._extension_id(payload["extension_id"])
        key, digest = self._key_only(payload["binding_slot_key"], payload["binding_slot_key_digest"], slot_digest)
        expected = self._expected(payload["expected_current_binding_head"], allow_absent=False)
        try:
            target = values.binding_ref(payload["target_binding_revision_ref"])
            target_installation = values.installation_ref(payload["target_installation_ref"])
            target_tuple = values.service_tuple(payload["target_service_tuple"])
            expected_retention = values.retention_head(payload["expected_retention_head"], states=("retained",))
            reason = values.reason_text(payload["reason"])
        except BindingValueError:
            raise BindingError("invalid_input") from None
        _require(target["binding_record_digest"] == target_digest)
        request_sha256 = self._request_sha("release", payload, slot_digest, target_digest)
        _now_value, stamp, now_ms = _now()
        with _writer(), self._domain._connection(write=True) as db:
            _actor, actor_ref = self._authenticate(request, db, read=False)
            roots = self._domain._read_roots(db)
            replay = self._replayed(db, roots, "release", command_id, request_sha256)
            if replay is not None:
                return replay
            history = self._slot_history(db, roots, digest)
            _require(history, "not_found")
            head = self._head(history)
            _require(head == expected, "binding_head_stale")
            _require(target["revision"] < head["revision"], "rollback_target_invalid")
            target_ref, _target_content = history[target["revision"] - 1]
            _require(target_ref.sha256 == target_digest, "rollback_target_invalid")
            retention = self._retention(db, roots, digest, target_digest)
            state = self._retention_head(retention)
            _require(state is not None and state["state"] == "retained", "retention_not_retained")
            _require(state == expected_retention, "retention_head_stale")
            prior_ref, prior = retention[-1]
            _require(prior["target_extension_id"] == extension_id, "extension_mismatch")
            _require(prior["target_installation"] == target_installation
                     and prior["target_service_tuple"] == target_tuple, "target_mismatch")
            self._capacity(db, roots, 2)
            released = {**prior, "state": "released", "revision": 2,
                        "expected_previous_retention_head": state,
                        "previous_revision": {"revision": 1, "retention_record_digest": prior_ref.sha256},
                        "observed_current_binding_head": head, "reason": reason, "command_id": command_id,
                        "recorded_at_ms": now_ms}
            ref = self._put(db, roots, actor_ref, record_id=values.retention_record_id(digest, target_digest),
                            version=2, parents=[prior_ref, target_ref], content=released, stamp=stamp)
            self._retention_event(db, roots, actor_ref, command_id=command_id, key=key, retention_ref=ref,
                                  target_ref=target_ref, head_ref=history[-1][0], previous_state="retained",
                                  state="released", stamp=stamp)
            result = {"command_id": command_id, "extension_id": extension_id, "binding_slot_key": key,
                      "binding_slot_key_digest": digest, "expected_current_binding_head": expected,
                      "target_binding_revision_ref": target, "target_installation_ref": target_installation,
                      "target_service_tuple": target_tuple, "expected_retention_head": expected_retention,
                      "new_retention_revision": 2, "new_retention_record_digest": ref.sha256,
                      "state": "released"}
            self._record_command(db, roots, actor_ref, action="release", command_id=command_id,
                                 request_sha256=request_sha256, result=result, parent=ref, stamp=stamp)
            return result


def parse_json_body(raw, *, maximum):
    """A duplicate-free JSON object of at most ``maximum`` bytes."""
    _require(type(raw) is bytes and 1 <= len(raw) <= maximum)

    def unique(pairs):
        value = {}
        for name, item in pairs:
            _require(name not in value)
            value[name] = item
        return value

    def constant(_name):
        raise BindingError()

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise BindingError("invalid_input") from None
    _require(type(value) is dict)
    return value


__all__ = ["CODES", "RELEASE_FIELDS", "RELEASE_RESULT_FIELDS", "BindingError", "PersistentExtensionBindings",
           "parse_json_body", "release_warning"]
