"""Dispatch-time resolution of an extension binding from its durable slot head (T087).

A port dispatch (today only the provider semantic path; no other port has a dispatcher) names
one binding revision in its config: `binding_revision_ref`, `binding_slot_key`,
`binding_slot_key_digest`, `extension_id`, `installation_digest` and `qualification_ref`. At
every dispatch-time load the dispatcher resolves that revision here from the durable
`extension-binding-revision-v1` history (`app/domain/extension_binding.py`) that the owner's
binding service writes, never from a caller-supplied binding record:

- the slot's history is read by the slot record id derived from the recomputed key digest, each
  version re-validated as an immutable record and its backward `previous_revision` chain checked;
- the head (newest revision) must be `active` and be exactly the config's revision ref;
- the head's extension, installation digest, qualification ref, port and slot key must equal
  the config's;
- otherwise the dispatch is refused with the reason the head gives: the slot is absent, the
  named revision is not in the history, or the head moved past it by a `disable`, a
  `supersede`/`bind` or a `rollback` (an older revision re-activated as a new revision).

The returned `head` is part of the dispatcher's context, so a head change between the build of
a send and its commit is seen by the dispatcher's pre-commit re-load (which re-resolves here and
refuses) before any effect. Nothing here writes.
"""

from __future__ import annotations

from ..domain import extension_binding as values
from ..domain.extension_binding import BINDING_SCHEMA, BindingValueError
from ..domain.refs import DomainContractError, EntityRef
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, StorageError

MAX_SLOTS = 256
MAX_ENVIRONMENT_RECORDS = 4096
REASONS = ("binding_slot_absent", "binding_revision_unknown", "binding_disabled",
           "binding_superseded", "binding_rolled_back", "binding_mismatch", "binding_unavailable")
MAX_HISTORY = 4096


class BindingDispatchRefused(ValueError):
    """The durable head does not admit the config's binding revision (no effect happened)."""

    def __init__(self, reason):
        self.reason = reason if reason in REASONS else "binding_unavailable"
        super().__init__(self.reason)


def _refuse(reason):
    raise BindingDispatchRefused(reason)


def read_slot_history(store, db, roots, slot_digest):
    """Every revision of one slot as `(EntityRef, content)`, validated and backward-linked."""
    record_id = values.slot_record_id(slot_digest)
    rows = db.execute("SELECT version, sha256, purpose, body FROM domain_records WHERE vault_id=? "
                      "AND kind='extension_binding' AND id=? ORDER BY version LIMIT ?",
                      (roots.genesis.id, record_id, MAX_HISTORY + 1)).fetchall()
    if len(rows) > MAX_HISTORY:
        _refuse("binding_unavailable")
    history, previous = [], None
    for index, row in enumerate(rows, start=1):
        ref = EntityRef("extension_binding", record_id, row["version"], row["sha256"])
        try:
            content = ImmutableRecord.from_bytes(row["body"], expected_ref=ref).body["content"]
        except (DomainContractError, ValueError, TypeError):
            _refuse("binding_unavailable")
        if (row["version"] != index or row["purpose"] != "operational"
                or content.get("schema_version") != BINDING_SCHEMA
                or content["binding_slot_key_digest"] != slot_digest
                or (previous is not None and content["previous_revision"]
                    != {"revision": previous.version, "binding_record_digest": previous.sha256})):
            _refuse("binding_unavailable")
        history.append((ref, content))
        previous = ref
    return history


def head_of(history):
    if not history:
        return None
    ref, content = history[-1]
    return {"revision": ref.version, "binding_record_digest": ref.sha256, "state": content["state"]}


class DurableBindingHeads:
    """Read-only resolver over one :class:`DomainStore` (the dispatcher's own store)."""

    def __init__(self, store):
        if type(store) is not DomainStore:
            raise TypeError("exact DomainStore required")
        self._store = store

    @property
    def store(self):
        return self._store

    def history(self, slot_digest):
        with self._store._connection() as db:
            roots = self._store._read_roots(db)
            return read_slot_history(self._store, db, roots, slot_digest)

    def resolve(self, *, port, extension_id, installation_digest, qualification_ref,
                binding_revision_ref, binding_slot_key, binding_slot_key_digest):
        """The durable active head that is exactly the named revision, as the projections the port
        config validator reads, plus the head itself."""
        try:
            key, digest = values.slot_key(binding_slot_key, binding_slot_key_digest, port=port)
            named = EntityRef.from_dict(binding_revision_ref)
        except (BindingValueError, DomainContractError, TypeError, ValueError):
            _refuse("binding_mismatch")
        if named.kind != "extension_binding" or named.id != values.slot_record_id(digest):
            _refuse("binding_revision_unknown")
        try:
            history = self.history(digest)
        except StorageError:
            _refuse("binding_unavailable")
        if not history:
            _refuse("binding_slot_absent")
        if (named.version > len(history)
                or history[named.version - 1][0].sha256 != named.sha256):
            _refuse("binding_revision_unknown")
        head_ref, current = history[-1]
        if head_ref != named:
            if current["state"] == "disabled":
                _refuse("binding_disabled")
            if current["action"] == "rollback":
                _refuse("binding_rolled_back")
            _refuse("binding_superseded")
        if current["state"] != "active":
            _refuse("binding_disabled")
        if (current["extension_id"] != extension_id
                or current["installation_ref"]["sha256"] != installation_digest
                or current["qualification_ref"] != qualification_ref
                or current["port_contract_version"] != port
                or current["binding_slot_key"] != key):
            _refuse("binding_mismatch")
        head = head_of(history)
        binding_record = {
            "ref": head_ref.as_dict(), "state": current["state"], "extension_id": current["extension_id"],
            "installation_digest": current["installation_ref"]["sha256"],
            "qualification_ref": current["qualification_ref"],
            "port_contract_version": current["port_contract_version"],
            "binding_slot_key": current["binding_slot_key"], "binding_slot_key_digest": digest}
        head_record = {"state": current["state"], "current_binding_revision_ref": head_ref.as_dict(),
                       "binding_slot_key": current["binding_slot_key"], "binding_slot_key_digest": digest}
        return {"binding_record": binding_record, "binding_head_record": head_record, "head": head}

    def resolve_config(self, port, config):
        """`resolve` over the exact fields of a port config."""
        if type(config) is not dict:
            _refuse("binding_mismatch")
        try:
            return self.resolve(port=port, extension_id=config["extension_id"],
                                installation_digest=config["installation_digest"],
                                qualification_ref=config["qualification_ref"],
                                binding_revision_ref=config["binding_revision_ref"],
                                binding_slot_key=config["binding_slot_key"],
                                binding_slot_key_digest=config["binding_slot_key_digest"])
        except KeyError:
            _refuse("binding_mismatch")


def slot_histories(store, db, roots):
    """Every binding slot's validated history, keyed by slot digest (bounded)."""
    from ..domain.refs import parse_canonical

    rows = db.execute("SELECT body FROM domain_records WHERE vault_id=? AND kind='extension_binding' "
                      "AND version=1", (roots.genesis.id,)).fetchall()
    slots = {}
    for row in rows:
        content = parse_canonical(row["body"])["content"]
        if content.get("schema_version") == BINDING_SCHEMA:
            digest = content["binding_slot_key_digest"]
            slots[digest] = read_slot_history(store, db, roots, digest)
    if len(slots) > MAX_SLOTS:
        _refuse("binding_unavailable")
    return dict(sorted(slots.items()))


def environment_binding_revisions(store, environment_id):
    """The active binding revisions an environment version is prepared with: every slot whose
    durable head is `active` and whose target scope is this environment or instance-wide
    (`environment_id: null`), as `{binding_slot_key_digest, revision, binding_record_digest}`
    sorted by slot."""
    if type(store) is not DomainStore:
        raise TypeError("exact DomainStore required")
    with store._connection() as db:
        roots = store._read_roots(db)
        slots = slot_histories(store, db, roots)
    result = []
    for digest, history in slots.items():
        ref, content = history[-1]
        if content["state"] == "active" and content["target_scope"]["environment_id"] in (None, environment_id):
            result.append({"binding_slot_key_digest": digest, "revision": ref.version,
                           "binding_record_digest": ref.sha256})
    return result


def bound_environment_versions(db, roots, slot_digest, head):
    """Every prepared environment version that recorded a revision of this slot, and whether the
    environment's latest prepared version needs re-preparation against ``head`` (the slot's
    current head): it does when the revision it recorded is no longer the active head. This is
    state only; nothing is re-prepared or promoted here."""
    from ..domain.refs import parse_canonical
    from ..services.design_persistence import decode_design_refs

    rows = db.execute("SELECT id, version, sha256, body FROM domain_records WHERE vault_id=? "
                      "AND kind='environment' ORDER BY id, version LIMIT ?",
                      (roots.genesis.id, MAX_ENVIRONMENT_RECORDS + 1)).fetchall()
    if len(rows) > MAX_ENVIRONMENT_RECORDS:
        _refuse("binding_unavailable")
    latest, found = {}, []
    for row in rows:
        latest[row["id"]] = max(latest.get(row["id"], 0), row["version"])
        try:
            content = decode_design_refs(parse_canonical(row["body"])["content"])
        except (DomainContractError, KeyError, TypeError, ValueError):
            _refuse("binding_unavailable")
        if type(content) is not dict or content.get("schema_version") != "environment-record-v2":
            continue
        for item in content.get("extension_binding_revisions", ()):
            if item.get("binding_slot_key_digest") == slot_digest:
                found.append((row, content, item))
    result = []
    for row, content, item in found:
        current = (head is not None and head["state"] == "active" and head["revision"] == item["revision"]
                   and head["binding_record_digest"] == item["binding_record_digest"])
        is_latest = latest[row["id"]] == row["version"]
        result.append({
            "environment_id": content["environment_id"], "environment_version": content["version"],
            "environment_record": {"kind": "environment", "id": row["id"], "version": row["version"],
                                   "sha256": row["sha256"]},
            "binding_revision": item["revision"], "binding_record_digest": item["binding_record_digest"],
            "latest_prepared": is_latest, "uses_current_head": current,
            "needs_re_preparation": is_latest and not current})
    return result


__all__ = ["MAX_SLOTS", "REASONS", "BindingDispatchRefused", "DurableBindingHeads", "bound_environment_versions",
           "environment_binding_revisions", "head_of", "read_slot_history", "slot_histories"]
