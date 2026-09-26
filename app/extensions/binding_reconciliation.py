"""Reconciliation of durable binding heads against their retention, command and event records (T087).

A bind, supersession, disable, rollback or release commits every record it writes (binding
revision, rollback-retention revisions, the command replay record and the contract events) in one
SQLite transaction (`binding_service.PersistentExtensionBindings._append`/`release`). A crash in the
middle of a command therefore leaves either all of them or none. This module checks that invariant
against what is actually stored, at startup (`reconcile`) and for one slot at dispatch time
(`slot_findings`, records only):

- every binding revision has its command record, whose committed result names exactly that head;
- every revision that displaced an `active` head has the displaced revision's retention revision 1
  (`retained`) observing exactly that new head;
- every rollback revision consumed its target's retention (revision 2 `consumed`, observing it);
- every `released` retention revision has its `release` command record;
- (startup only) every revision has its contract event (`extension.binding_*`, or the earlier
  `extension.binding_changed` under the same command id) and every retention revision has its
  `extension.rollback_retention_*` event.

A slot with any finding is reported (never repaired: nothing can be re-derived without the owner's
act), shown by the slot inspection and refused by the dispatch resolver (`binding_unavailable`).
Nothing here writes, except the startup `recovery.reconciled` event when a finding exists.
"""

from __future__ import annotations

from ..domain import extension_binding as values
from ..domain.extension_binding import COMMAND_SCHEMA, RETENTION_SCHEMA
from ..domain.refs import DomainContractError, EntityRef, parse_canonical
from ..domain.schemas import ImmutableRecord
from ..domain.store import StorageError

REPORT_SCHEMA = "extension-binding-reconciliation-v1"
BINDING_EVENTS = {"bind": "extension.binding_activated", "supersede": "extension.binding_superseded",
                  "disable": "extension.binding_disabled", "rollback": "extension.binding_rolled_back"}
RETENTION_EVENTS = {"retained": "extension.rollback_retention_created",
                    "released": "extension.rollback_retention_released",
                    "consumed": "extension.rollback_retention_consumed"}
LEGACY_BINDING_EVENT = "extension.binding_changed"
MAX_EVENT_ROWS = 65_536


def _versions(db, roots, record_id):
    rows = db.execute("SELECT version, sha256, body FROM domain_records WHERE vault_id=? "
                      "AND kind='extension_binding' AND id=? ORDER BY version", (roots.genesis.id, record_id)).fetchall()
    result = []
    for row in rows:
        ref = EntityRef("extension_binding", record_id, row["version"], row["sha256"])
        try:
            result.append((ref, ImmutableRecord.from_bytes(row["body"], expected_ref=ref).body["content"]))
        except (DomainContractError, TypeError, ValueError):
            result.append((ref, None))
    return result


def _command(db, roots, command_id):
    history = _versions(db, roots, values.command_record_id(command_id))
    if len(history) != 1 or history[0][1] is None or history[0][1].get("schema_version") != COMMAND_SCHEMA:
        return None
    content = history[0][1]
    try:
        return content["action"], parse_canonical(content["result_json"].encode())
    except (DomainContractError, TypeError, ValueError):
        return None


def _head(ref, content):
    return {"revision": ref.version, "binding_record_digest": ref.sha256, "state": content["state"]}


def slot_findings(db, roots, digest, history):
    """Every broken record invariant of one slot (empty when consistent)."""
    findings = []
    retentions = {}
    for index, (ref, content) in enumerate(history):
        head = _head(ref, content)
        command = _command(db, roots, content["command_id"])
        expected_action = "bind" if content["action"] in ("bind", "supersede") else content["action"]
        if command is None:
            findings.append(f"revision {ref.version}: command record missing")
        elif (command[0] != expected_action or type(command[1]) is not dict
              or command[1].get("binding_head") != head):
            findings.append(f"revision {ref.version}: command record does not name this head")
        if index > 0 and history[index - 1][1]["state"] == "active":
            displaced_ref = history[index - 1][0]
            retained = retentions.setdefault(displaced_ref.sha256, _versions(
                db, roots, values.retention_record_id(digest, displaced_ref.sha256)))
            first = retained[0][1] if retained else None
            if (first is None or first.get("schema_version") != RETENTION_SCHEMA or first["state"] != "retained"
                    or first["observed_current_binding_head"] != head
                    or first["target_binding_revision"] != {"revision": displaced_ref.version,
                                                            "binding_record_digest": displaced_ref.sha256}):
                findings.append(f"revision {ref.version}: displaced revision {displaced_ref.version} not retained")
        if content["action"] == "rollback":
            target = content["rollback_of_revision"]
            consumed = retentions.setdefault(target["binding_record_digest"], _versions(
                db, roots, values.retention_record_id(digest, target["binding_record_digest"])))
            second = consumed[1][1] if len(consumed) > 1 else None
            if (second is None or second["state"] != "consumed" or second["observed_current_binding_head"]
                    != {"revision": ref.version, "binding_record_digest": ref.sha256, "state": "active"}
                    or second["command_id"] != content["command_id"]):
                findings.append(f"revision {ref.version}: rollback target {target['revision']} retention not consumed")
    for ref, content in history:
        if content["state"] != "active":
            continue
        retained = retentions.get(ref.sha256)
        if retained is None:
            retained = _versions(db, roots, values.retention_record_id(digest, ref.sha256))
        for retention_ref, retention in retained:
            if retention is None:
                findings.append(f"retention of revision {ref.version}: record unreadable")
            elif retention["state"] == "released":
                command = _command(db, roots, retention["command_id"])
                if (command is None or command[0] != "release" or type(command[1]) is not dict
                        or command[1].get("new_retention_record_digest") != retention_ref.sha256):
                    findings.append(f"retention of revision {ref.version}: release command record missing")
    return findings


def _events(db, roots):
    """Stored event object refs and correlation ids by type (none when the event tables are absent)."""
    if db.execute("SELECT name FROM sqlite_master WHERE name='api_event_envelopes'").fetchone() is None:
        return None
    wanted = (LEGACY_BINDING_EVENT, *BINDING_EVENTS.values(), *RETENTION_EVENTS.values())
    rows = db.execute("SELECT event_type, envelope FROM api_event_envelopes WHERE vault_id=? AND event_type IN "
                      f"({','.join('?' * len(wanted))}) LIMIT ?",
                      (roots.genesis.id, *wanted, MAX_EVENT_ROWS)).fetchall()
    seen = set()
    for row in rows:
        body = parse_canonical(bytes(row["envelope"]))
        for item in body["object_refs"]:
            seen.add((row["event_type"], item["id"], item.get("version"), item.get("content_hash")))
        seen.add((row["event_type"], "correlation", body["correlation_id"]))
    return seen


def event_findings(digest, history, retained_by_target, seen):
    findings = []
    slot_id = values.slot_record_id(digest)
    legacy = False
    for ref, content in history:
        if (BINDING_EVENTS[content["action"]], slot_id, ref.version, ref.sha256) in seen:
            continue
        if (LEGACY_BINDING_EVENT, "correlation", content["command_id"]) in seen:
            legacy = True  # written before the contract event names were registered
            continue
        findings.append(f"revision {ref.version}: event missing")
    if legacy:
        return findings
    for target_digest, retained in retained_by_target.items():
        record_id = values.retention_record_id(digest, target_digest)
        for retention_ref, retention in retained:
            if retention is not None and (RETENTION_EVENTS[retention["state"]], record_id, retention_ref.version,
                                          retention_ref.sha256) not in seen:
                findings.append(f"retention {retention_ref.version} of {target_digest[:12]}: event missing")
    return findings


def reconcile(store, *, clock_ms):
    """Check every slot; the report the startup hook keeps and the inspection shows."""
    from .binding_heads import BindingDispatchRefused, slot_histories

    report = {"schema_version": REPORT_SCHEMA, "checked_at_ms": clock_ms(), "checked_slots": 0,
              "inconsistent_slots": {}, "state": "consistent"}
    try:
        with store._connection() as db:
            roots = store._read_roots(db)
            slots = slot_histories(store, db, roots)
            seen = _events(db, roots)
            for digest, history in slots.items():
                findings = slot_findings(db, roots, digest, history)
                if seen is not None:
                    retained = {ref.sha256: _versions(db, roots, values.retention_record_id(digest, ref.sha256))
                                for ref, content in history if content["state"] == "active"}
                    findings += event_findings(digest, history, retained, seen)
                if findings:
                    report["inconsistent_slots"][digest] = findings
            report["checked_slots"] = len(slots)
    except (BindingDispatchRefused, DomainContractError, StorageError, KeyError, TypeError, ValueError,
            OSError):
        report["state"] = "unavailable"
        return report
    if report["inconsistent_slots"]:
        report["state"] = "inconsistent"
    return report


__all__ = ["REPORT_SCHEMA", "event_findings", "reconcile", "slot_findings"]
