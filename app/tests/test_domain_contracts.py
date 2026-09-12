"""Domain-v1 invariants, independent of providers and native dependencies."""

from dataclasses import FrozenInstanceError
from hashlib import sha256
import tracemalloc

import pytest

from app.domain.refs import (
    DomainContractError, EntityRef, ObjectRef, canonical_json, decimal_string, parse_canonical,
)
from app.domain.schemas import Actor, ImmutableRecord, RecordMetadata


ID = "00000000-0000-4000-8000-000000000001"
ACTOR_ID = "00000000-0000-4000-8000-000000000002"
POLICY_ID = "00000000-0000-4000-8000-000000000003"


def ref(kind="access_policy", identity=POLICY_ID):
    return EntityRef(kind=kind, id=identity, version=1, sha256="a" * 64)


def record(**changes):
    fields = dict(kind="work_model", id=ID, version=1,
                  created_at_utc="2026-09-07T00:00:00.000000Z",
                  actor_ref=ref("actor", ACTOR_ID), parent_refs=(),
                  purpose="operational", access_policy_ref=ref(),
                  retention_policy_ref=ref("retention_policy"),
                  content={"title": "업무", "counts": [1, 2], "ratio": "0.25"})
    return ImmutableRecord.create(**(fields | changes))


def test_canonical_vector_preserves_unicode_and_key_order():
    expected = '{"a":"한국어","z":[1,true,null]}'.encode()
    assert canonical_json({"z": [1, True, None], "a": "한국어"}) == expected
    assert sha256(expected).hexdigest() == "3c397f0d921fdfa0d35034b5d6760b7488b7c5e70c960446f2422054c832a413"


def test_unicode_normalization_is_not_an_unrequested_edit():
    assert canonical_json({"text": "é"}) != canonical_json({"text": "e\u0301"})


@pytest.mark.parametrize("value", [b"9" * 5000, b"-" + b"9" * 5000], ids=["huge_positive", "huge_negative"])
def test_huge_json_integer_has_a_domain_error_before_interpreter_int_limit(value):
    with pytest.raises(DomainContractError):
        parse_canonical(value)


@pytest.mark.parametrize("value", [0.1, float("nan"), float("inf"), float("-inf"),
                                      {1: "not a JSON key"}, {"x": object()}, {"x": b"bytes"},
                                      {"x": "\ud800"}, 2 ** 63, -(2 ** 63)])
def test_canonical_rejects_ambiguous_or_unbounded_values(value):
    with pytest.raises(DomainContractError):
        canonical_json(value)


def test_canonical_rejects_cycles_depth_and_string_size_without_recursion_error():
    cycle = []
    cycle.append(cycle)
    nested = []
    for _ in range(34):
        nested = [nested]
    for value in (cycle, nested, "a" * 65_537):
        with pytest.raises(DomainContractError):
            canonical_json(value)


def test_oversized_string_is_rejected_before_allocating_full_encoded_copy():
    value = "a" * (8 * 1024 * 1024)
    tracemalloc.start()
    try:
        with pytest.raises(DomainContractError):
            canonical_json(value)
        _, peak = tracemalloc.get_traced_memory()
        assert peak < 1024 * 1024
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize("value", [True, False, 0, -1, "1", 1.0, 2 ** 63])
def test_ref_version_is_a_strict_positive_bounded_integer(value):
    with pytest.raises(DomainContractError):
        EntityRef(kind="artifact", id=ID, version=value, sha256="a" * 64)


@pytest.mark.parametrize("changes", [dict(id="not-a-uuid"), dict(id=ID.upper().replace("a", "A") + "x"),
                                        dict(kind="secret"), dict(sha256="A" * 64),
                                        dict(sha256="a" * 63), dict(extra=True)])
def test_ref_rejects_unregistered_or_malformed_envelopes(changes):
    with pytest.raises((DomainContractError, TypeError)):
        EntityRef(**(dict(kind="artifact", id=ID, version=1, sha256="a" * 64) | changes))


def test_entity_ref_is_frozen_and_strictly_roundtrips():
    value = ref()
    assert EntityRef.from_dict(value.as_dict()) == value
    with pytest.raises(FrozenInstanceError):
        value.version = 2
    with pytest.raises(DomainContractError):
        EntityRef.from_dict(value.as_dict() | {"vault": ID})


def test_navigation_locator_cannot_be_used_as_a_content_reference():
    locator = ObjectRef(kind="work", id=ID)
    with pytest.raises(DomainContractError):
        EntityRef.from_dict(locator.as_dict())
    with pytest.raises(DomainContractError):
        record(parent_refs=(locator,))


def test_locator_optional_version_and_hash_do_not_grant_entity_authority():
    locator = ObjectRef(kind="artifact", id=ID, version=2, content_hash="b" * 64)
    assert locator.as_dict() == dict(kind="artifact", id=ID, version=2, content_hash="b" * 64)
    with pytest.raises(DomainContractError):
        EntityRef.from_dict(locator.as_dict())
    with pytest.raises(DomainContractError):
        ObjectRef(kind="artifact", id=ID, version=True)


@pytest.mark.parametrize("value,expected", [("0", "0"), ("0.2500", "0.25"),
                                             ("100.00", "100"), ("-0.00", "0"),
                                             ("-10.5", "-10.5")])
def test_decimal_text_is_canonical_without_binary_floats(value, expected):
    assert decimal_string(value) == expected


@pytest.mark.parametrize("value", [True, 0.1, 1, "NaN", "Infinity", "1e2", " 1", "+1", "01", "1." , "9" * 129])
def test_decimal_rejects_implicit_conversion_and_unbounded_values(value):
    with pytest.raises(DomainContractError):
        decimal_string(value)


def test_body_digest_does_not_contain_its_envelope_or_mutable_metadata():
    value = record()
    body = value.body
    assert "ref" not in body and "sha256" not in body
    assert "availability" not in body and "redaction_state" not in body
    assert value.ref.sha256 == sha256(value.body_bytes).hexdigest()
    assert body["id"] == value.ref.id and body["version"] == value.ref.version
    assert ImmutableRecord.from_bytes(value.body_bytes, expected_ref=value.ref) == value


def test_record_defensively_freezes_input_and_returned_views():
    content = {"nested": [{"value": "original"}]}
    value = record(content=content)
    original = value.body_bytes
    content["nested"][0]["value"] = "outside mutation"
    value.body["content"]["nested"][0]["value"] = "view mutation"
    value.as_dict()["body"]["content"]["nested"].append("change")
    assert value.body_bytes == original
    with pytest.raises(FrozenInstanceError):
        value.body_bytes = b"{}"


def test_new_body_changes_hash_but_external_availability_does_not():
    original = record()
    modified = record(version=2, parent_refs=(original.ref,), content={"title": "다른 업무"})
    assert original.ref.sha256 != modified.ref.sha256
    metadata = RecordMetadata(availability="missing", redaction_state="original")
    assert metadata.availability == "missing" and original.ref == record().ref


@pytest.mark.parametrize("change", [dict(purpose="public"), dict(created_at_utc="yesterday"),
                                       dict(created_at_utc="2026-09-07T00:00:00+09:00"),
                                       dict(actor_ref=ref("artifact")),
                                       dict(access_policy_ref=ref("artifact")),
                                       dict(retention_policy_ref=ref("artifact")),
                                       dict(parent_refs=(ref(), ref())), dict(version=True)])
def test_record_common_header_rejects_invalid_or_ambiguous_fields(change):
    with pytest.raises(DomainContractError):
        record(**change)


def test_deserialization_checks_canonical_bytes_hash_and_self_identity():
    original = record()
    with pytest.raises(DomainContractError):
        ImmutableRecord.from_bytes(original.body_bytes + b" ", expected_ref=original.ref)
    changed = original.body | {"content": {"title": "tampered"}}
    with pytest.raises(DomainContractError):
        ImmutableRecord.from_bytes(canonical_json(changed), expected_ref=original.ref)
    for changed in (original.body | {"availability": "present"},
                    original.body | {"sha256": original.ref.sha256},
                    original.body | {"schema_version": "domain-v99"}):
        with pytest.raises(DomainContractError):
            ImmutableRecord.from_bytes(canonical_json(changed))
    with pytest.raises(DomainContractError):
        ImmutableRecord.from_bytes(b'{"kind":"artifact","kind":"work_model"}')


def test_actor_claim_is_not_authenticated_authority():
    actor = Actor(id=ACTOR_ID, kind="human", origin="local_session")
    assert actor.kind == "human"
    assert not hasattr(actor, "approve")
    # Domain records preserve provenance but do not turn an untrusted actor field into a session.
    with pytest.raises(DomainContractError):
        Actor.from_untrusted({"id": ACTOR_ID, "kind": "human", "origin": "local_session"})
    provider = Actor.from_untrusted({"id": ACTOR_ID, "kind": "provider", "origin": "model_output"})
    assert provider.kind == "provider"
    with pytest.raises(DomainContractError):
        Actor(id=ACTOR_ID, kind="human", origin="model_output")


def test_body_size_and_constructor_cannot_bypass_validation():
    with pytest.raises(DomainContractError):
        ImmutableRecord(ref=ref(), body_bytes=b"{}")
    with pytest.raises(DomainContractError):
        record(content={str(i): "x" * 65_536 for i in range(17)})


def test_fresh_vault_has_an_acyclic_real_hash_chain_without_placeholder_refs():
    timestamp = "2026-09-07T00:00:00.000000Z"
    genesis = ImmutableRecord.genesis(vault_id=ID, created_at_utc=timestamp)
    roots = [ImmutableRecord.bootstrap(kind=kind, id=identity, genesis_ref=genesis.ref,
                                      created_at_utc=timestamp)
             for kind, identity in (("actor", ACTOR_ID), ("access_policy", POLICY_ID),
                                    ("retention_policy", "00000000-0000-4000-8000-000000000004"))]
    assert genesis.body["vault_id"] == ID
    assert genesis.body["profile"] == "local-deny-by-default-v1"
    assert not {"actor_ref", "access_policy_ref", "retention_policy_ref"} & genesis.body.keys()
    known = {genesis.ref}
    for root in roots:
        assert EntityRef.from_dict(root.body["genesis_ref"]) in known
        assert root.ref.sha256 == sha256(root.body_bytes).hexdigest()
        known.add(root.ref)
    first = record(actor_ref=roots[0].ref, access_policy_ref=roots[1].ref,
                   retention_policy_ref=roots[2].ref)
    assert {EntityRef.from_dict(first.body[key]) for key in
            ("actor_ref", "access_policy_ref", "retention_policy_ref")} <= known


def test_bootstrap_cannot_encode_human_approval_or_select_arbitrary_policy():
    genesis = ImmutableRecord.genesis(vault_id=ID, created_at_utc="2026-09-07T00:00:00.000000Z")
    actor = ImmutableRecord.bootstrap(kind="actor", id=ACTOR_ID, genesis_ref=genesis.ref,
                                     created_at_utc="2026-09-07T00:00:00.000000Z")
    assert actor.body["content"] == {"id": ACTOR_ID, "kind": "system", "origin": "host_service"}
    bad = actor.body | {"content": {"id": ACTOR_ID, "kind": "human", "origin": "local_session"}}
    with pytest.raises(DomainContractError):
        ImmutableRecord.from_bytes(canonical_json(bad))
    for bad in (genesis.body | {"profile": "allow-all"}, genesis.body | {"version": 2},
                genesis.body | {"actor_ref": ref("actor", ACTOR_ID).as_dict()},
                genesis.body | {"vault_id": ACTOR_ID}):
        with pytest.raises(DomainContractError):
            ImmutableRecord.from_bytes(canonical_json(bad))
    with pytest.raises(DomainContractError):
        ImmutableRecord.bootstrap(kind="graph", id=POLICY_ID, genesis_ref=genesis.ref,
                                  created_at_utc="2026-09-07T00:00:00.000000Z")
    with pytest.raises(DomainContractError):
        record(kind="vault_genesis")
