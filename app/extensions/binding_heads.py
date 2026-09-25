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


__all__ = ["REASONS", "BindingDispatchRefused", "DurableBindingHeads", "head_of", "read_slot_history"]
