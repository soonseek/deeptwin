"""Dispatch-time binding resolution from the durable slot head (T087).

The provider semantic dispatch reads its binding revision and slot head from the durable
`extension-binding-revision-v1` history (`app/extensions/binding_heads.py`), never from an injected
record. Here the history is written by the real owner routes (`test_extension_bindings.case`: real
`create_app`, owner cookie/CSRF, the test qualification resolver) and by the production
`_append` over a bare store (`app/tests/support/durable_binding.py`) for the races. The full
dispatcher path (head moved between the send's build and its commit) is driven in
`test_provider_semantic_vertical.py` (`binding_*` phases).
"""

from __future__ import annotations

import threading
from uuid import uuid4

import pytest

from app.domain.extension_binding import slot_record_id
from app.domain.store import DomainStore
from app.extensions.binding_heads import BindingDispatchRefused, DurableBindingHeads
from app.extensions.provider_semantic_context import ProviderSemanticAuthority
from app.extensions.provider_semantic_contracts import ProviderSemanticError
from app.storage import Store
from app.tests.support import durable_binding
from app.tests.test_extension_bindings import _bind, _key, _ok, _slot_body, case  # noqa: F401 (fixture)


def _ref(digest, head):
    return {"kind": "extension_binding", "id": slot_record_id(digest), "version": head["revision"],
            "sha256": head["binding_record_digest"]}


def _fields(key, qualification, head):
    return {"port": "provider-port-v1", "extension_id": qualification["extension_id"],
            "installation_digest": qualification["installation_ref"]["sha256"],
            "qualification_ref": qualification["qualification_ref"],
            "binding_revision_ref": _ref(key["binding_slot_key_digest"], head),
            "binding_slot_key": key["binding_slot_key"],
            "binding_slot_key_digest": key["binding_slot_key_digest"]}


def _refused(heads, reason, **fields):
    with pytest.raises(BindingDispatchRefused) as raised:
        heads.resolve(**fields)
    assert raised.value.reason == reason


def test_dispatch_reads_the_route_written_head_and_refuses_every_moved_head(case):
    a = case.resolver.qualification("ext-a", "a")
    b = case.resolver.qualification("ext-b", "b")
    key = _key(case)
    digest = key["binding_slot_key_digest"]
    heads = DurableBindingHeads(case.app.state.domain_store)
    first = _ok(case.post("bindings", _bind(key, a, None)))
    rev1 = _fields(key, a, first["binding_head"])
    resolved = heads.resolve(**rev1)
    assert resolved["head"] == first["binding_head"]
    assert resolved["binding_record"]["state"] == "active"
    assert resolved["binding_record"]["ref"] == rev1["binding_revision_ref"]
    assert resolved["binding_head_record"]["current_binding_revision_ref"] == rev1["binding_revision_ref"]
    # a config that does not join the durable revision is refused, whatever it claims
    _refused(heads, "binding_mismatch", **{**rev1, "extension_id": "ext-b"})
    _refused(heads, "binding_mismatch", **{**rev1, "installation_digest": "0" * 64})
    _refused(heads, "binding_mismatch", **{**rev1, "qualification_ref": b["qualification_ref"]})
    _refused(heads, "binding_mismatch", **{**rev1, "binding_slot_key_digest": "0" * 64})
    _refused(heads, "binding_revision_unknown",
             **{**rev1, "binding_revision_ref": {**rev1["binding_revision_ref"], "sha256": "0" * 64}})
    _refused(heads, "binding_revision_unknown",
             **{**rev1, "binding_revision_ref": {**rev1["binding_revision_ref"], "version": 9}})
    _refused(heads, "binding_revision_unknown",
             **{**rev1, "binding_revision_ref": {**rev1["binding_revision_ref"], "kind": "validation_report"}})
    sibling = _key(case, slot_id="other-provider")
    _refused(heads, "binding_slot_absent", **{
        **rev1, "binding_slot_key": sibling["binding_slot_key"],
        "binding_slot_key_digest": sibling["binding_slot_key_digest"],
        "binding_revision_ref": {**rev1["binding_revision_ref"],
                                 "id": slot_record_id(sibling["binding_slot_key_digest"])}})

    second = _ok(case.post("bindings", _bind(key, b, first["binding_head"])))
    rev2 = _fields(key, b, second["binding_head"])
    _refused(heads, "binding_superseded", **rev1)
    assert heads.resolve(**rev2)["head"] == second["binding_head"]

    third = _ok(case.post(f"bindings/{digest}/disable", _slot_body(key, "ext-b", second["binding_head"])))
    _refused(heads, "binding_disabled", **rev2)
    _refused(heads, "binding_disabled", **_fields(key, b, third["binding_head"]))
    _refused(heads, "binding_disabled", **rev1)

    slot = _ok(case.get(f"bindings/{digest}"))
    retained = next(item for item in slot["rollback_retentions"]
                    if item["target_binding_revision_ref"]["revision"] == 1)
    fourth = _ok(case.post(f"bindings/{digest}/rollback", _slot_body(
        key, "ext-a", third["binding_head"], target_binding_revision_ref=retained["target_binding_revision_ref"],
        expected_retention_head=retained["retention_head"])))
    # the rolled-back-to revision is re-activated as a new revision; the old ref stays refused
    _refused(heads, "binding_rolled_back", **rev1)
    _refused(heads, "binding_rolled_back", **rev2)
    assert heads.resolve(**_fields(key, a, fourth["binding_head"]))["head"] == fourth["binding_head"]


def test_the_semantic_authority_cannot_carry_a_binding_record():
    base = dict(current_connection={}, qualification_record={}, actor_record={}, purpose_record={},
                grant_records={}, artifact_records={}, selector_records={}, input_records={},
                core_boot_id=str(uuid4()))
    ProviderSemanticAuthority(binding_refs={"grant_refs": [], "credential_handle_refs": []}, **base)
    injected = {"grant_refs": [], "credential_handle_refs": [], "state": "active",
                "ref": {"kind": "extension_binding"}}
    with pytest.raises(ProviderSemanticError, match="only grant and handle refs"):
        ProviderSemanticAuthority(binding_refs=injected, **base)
    with pytest.raises(TypeError):
        ProviderSemanticAuthority(binding_record={}, binding_head_record={}, **base)


@pytest.mark.parametrize("move", ["disable", "supersede", "rollback"])
def test_a_concurrent_head_move_is_never_admitted_after_it_commits(tmp_path, monkeypatch, move):
    installations = durable_binding.admit_test_installations(monkeypatch)
    domain = DomainStore(Store(tmp_path / "vault"))
    domain.initialize_vault()
    qualification = durable_binding._put(domain, "validation_report", {"fixture": "qualification"})
    bound = durable_binding.bind(domain, installations, qualification_ref=qualification.as_dict())
    if move == "rollback":
        bound = durable_binding.bind(domain, installations, label="b",
                                     qualification_ref=qualification.as_dict())
    heads = DurableBindingHeads(domain)
    fields = {"port": "provider-port-v1", "extension_id": "claude-semantic-worker",
              "installation_digest": bound.installation.sha256, "qualification_ref": qualification.as_dict(),
              "binding_revision_ref": bound.ref, "binding_slot_key": bound.key,
              "binding_slot_key_digest": bound.digest}
    committed, stop, outcomes, errors = threading.Event(), threading.Event(), [], []

    def dispatcher():
        try:
            while not stop.is_set():
                after = committed.is_set()  # observed before the read begins
                try:
                    heads.resolve(**fields)
                    outcomes.append((after, "admitted"))
                except BindingDispatchRefused as refused:
                    outcomes.append((after, refused.reason))
        except BaseException as error:  # noqa: BLE001 - reported below
            errors.append(error)

    threads = [threading.Thread(target=dispatcher) for _ in range(3)]
    for thread in threads:
        thread.start()
    try:
        while len(outcomes) < 30:
            threading.Event().wait(0.001)
        if move == "disable":
            durable_binding.disable(domain, bound.digest)
        elif move == "supersede":
            durable_binding.bind(domain, installations, label="c", qualification_ref=qualification.as_dict())
        else:
            durable_binding.rollback(domain, bound.digest, 1)
        committed.set()
        seen = len(outcomes)
        while len(outcomes) < seen + 30:
            threading.Event().wait(0.001)
    finally:
        stop.set()
        for thread in threads:
            thread.join(10)
    assert errors == []
    reason = {"disable": "binding_disabled", "supersede": "binding_superseded",
              "rollback": "binding_rolled_back"}[move]
    before = {outcome for after, outcome in outcomes if not after}
    after = {outcome for after, outcome in outcomes if after}
    assert "admitted" in before and before <= {"admitted", reason}
    assert after == {reason}
