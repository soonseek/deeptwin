"""Startup reconciliation of binding heads against retention, command and event records (T087).

Every binding command commits its binding revision, retention revisions, command record and
contract events in one SQLite transaction. A real process that dies in the middle of a supersession
(`os._exit` inside the transaction, just before its command record) leaves none of them, and the
next start reconciles the slot as consistent. Records outside that invariant (here: a revision
appended by the production `_append` with its retention and command record withheld) are reported
at startup with one `recovery.reconciled` event, shown by the slot inspection, and refused by the
dispatch resolver; nothing is repaired.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.domain.store import DomainStore
from app.extensions import binding_service
from app.extensions.binding_heads import BindingDispatchRefused, DurableBindingHeads
from app.extensions.binding_reconciliation import reconcile
from app.storage import Store
from app.tests.support import durable_binding
from app.tests.test_extension_bindings import _bind, _key, _ok, case  # noqa: F401 (fixture)
from app.tests.test_web_owner_integration import headers

ROOT = Path(__file__).resolve().parents[2]

CHILD = textwrap.dedent("""
    import json, os, sys
    from app.domain import extension_installation
    from app.domain.store import DomainStore
    from app.extensions.binding_service import PersistentExtensionBindings
    from app.storage import Store
    from app.tests.support import durable_binding

    installations = set()
    original = extension_installation.validate_installation_body
    extension_installation.validate_installation_body = (
        lambda body: None if body["id"] in installations else original(body))
    domain = DomainStore(Store(sys.argv[1]))
    domain.initialize_vault()
    qualification = durable_binding._put(domain, "validation_report", {"fixture": "qualification"})
    first = durable_binding.bind(domain, installations, qualification_ref=qualification.as_dict())
    print(json.dumps({"installations": sorted(installations), "qualification": qualification.as_dict(),
                      "digest": first.digest, "head": first.result["binding_head"]}), flush=True)
    writes = []
    original_put = PersistentExtensionBindings._put

    def counted_put(self, *args, **kwargs):
        writes.append(kwargs["content"]["schema_version"])
        return original_put(self, *args, **kwargs)

    def die(self, *args, **kwargs):
        # the supersession's revision, retention and both events are staged; the process dies
        # before the command record and the commit
        print(json.dumps({"staged": writes}), flush=True)
        os._exit(17)

    PersistentExtensionBindings._put = counted_put
    PersistentExtensionBindings._record_command = die
    durable_binding.bind(domain, installations, label="b", qualification_ref=qualification.as_dict())
    print("not reached", flush=True)
""")


def _admit(monkeypatch, ids):
    installations = durable_binding.admit_test_installations(monkeypatch)
    installations.update(ids)
    return installations


def test_a_process_that_dies_mid_supersession_leaves_nothing_and_reconciles_consistent(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    child = subprocess.run([sys.executable, "-c", CHILD, str(vault)], cwd=ROOT, capture_output=True, text=True,
                           timeout=120, env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert child.returncode == 17, child.stderr
    lines = [json.loads(line) for line in child.stdout.splitlines()]
    setup, staged = lines
    assert staged["staged"] == ["extension-binding-revision-v1", "extension-rollback-retention-revision-v1"]
    installations = _admit(monkeypatch, setup["installations"])
    domain = DomainStore(Store(vault))
    report = reconcile(domain, clock_ms=lambda: 1)
    assert (report["state"], report["checked_slots"], report["inconsistent_slots"]) == ("consistent", 1, {})
    heads = DurableBindingHeads(domain)
    history = heads.history(setup["digest"])
    assert [ref.version for ref, _content in history] == [1]  # the staged revision 2 was never committed
    with domain._connection() as db:
        kinds = db.execute("SELECT COUNT(*) FROM domain_records WHERE kind='extension_binding'").fetchone()[0]
        events = [row[0] for row in db.execute("SELECT event_type FROM api_event_envelopes ORDER BY sequence")]
    assert kinds == 2  # revision 1 and its command record only; no retention was committed
    assert events == ["extension.binding_activated"]
    # the next attempt starts from the committed head and stays consistent
    again = durable_binding.bind(domain, installations, label="b", qualification_ref=setup["qualification"])
    assert again.result["binding_head"]["revision"] == 2 and again.result["retained"] is not None
    assert reconcile(domain, clock_ms=lambda: 2)["state"] == "consistent"


def test_records_outside_the_invariant_are_reported_shown_and_refused(case, monkeypatch):
    installations = durable_binding.admit_test_installations(monkeypatch)
    service, domain = case.service, case.app.state.domain_store
    # the app's startup hook already ran over the empty vault
    assert service.reconciliation["state"] == "consistent" and service.reconciliation["checked_slots"] == 0
    a = case.resolver.qualification("ext-a", "a")
    key = _key(case)
    digest = key["binding_slot_key_digest"]
    first = _ok(case.post("bindings", _bind(key, a, None)))
    qualification = durable_binding._put(domain, "validation_report", {"fixture": "qualification"})
    # a supersession appended with its retention and its command record withheld
    record_command = binding_service.PersistentExtensionBindings._record_command
    monkeypatch.setattr(binding_service.PersistentExtensionBindings, "_record_command",
                        lambda self, *args, **kwargs: None)
    slot = (key["binding_slot_key"], digest, key["capability_selector"], key["target_scope"])
    broken = durable_binding.bind(domain, installations, extension_id="ext-a", label="broken", slot=slot,
                                  qualification_ref=qualification.as_dict(), retain_head=False)
    monkeypatch.setattr(binding_service.PersistentExtensionBindings, "_record_command", record_command)
    report = service.reconcile_startup()
    assert report["state"] == "inconsistent" and report["checked_slots"] == 1
    assert report["inconsistent_slots"] == {digest: [
        "revision 2: command record missing", "revision 2: displaced revision 1 not retained"]}
    events = case.client.get(case.profile.base_path + "api/v1/events", headers=headers(case.profile)).json()
    reconciled = [event for event in events["events"] if event["event_type"] == "recovery.reconciled"]
    assert [event["public_metadata"] for event in reconciled] == [{"recovered_count": 0, "unknown_count": 1}]
    read = _ok(case.get(f"bindings/{digest}"))
    assert read["reconciliation"] == {
        "state": "inconsistent", "findings": report["inconsistent_slots"][digest], "startup_state": "inconsistent",
        "startup_findings": report["inconsistent_slots"][digest], "dispatch": "refused"}
    listed = _ok(case.get("bindings"))
    assert listed["reconciliation"]["inconsistent_slot_digests"] == [digest]
    heads = DurableBindingHeads(domain)
    with pytest.raises(BindingDispatchRefused) as refused:
        heads.resolve(port="provider-port-v1", extension_id="ext-a",
                      installation_digest=broken.installation.sha256, qualification_ref=qualification.as_dict(),
                      binding_revision_ref=broken.ref, binding_slot_key=key["binding_slot_key"],
                      binding_slot_key_digest=digest)
    assert refused.value.reason == "binding_unavailable"
    assert first["binding_head"]["revision"] == 1
