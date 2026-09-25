"""Owner-recovery port: trust set v2, `owner_recovery` request, detached recovery receipt and
`session-root-maintenance` (recovery port design §1–§4, approved 2026-09-24).

Every key is generated in-test (offline Ed25519); no real deployment material is read.
"""

import json
import os
import time
from hashlib import sha256
from pathlib import Path

import pytest

from app.deployment.receipt_contracts import ReceiptWireError, parse_trust_set
from app.deployment.recovery_contracts import (
    parse_recovery_receipt,
    parse_recovery_request,
    parse_trust_set_v2,
    verify_recovery_receipt,
    verify_trust_set_upgrade,
)
from app.deployment.recovery_schema_exports import RECOVERY_ADAPTER, STAGE_ADAPTER
from app.domain.refs import canonical_json, parse_canonical
from app.operations.session_root import (
    SessionRootError,
    advance_session_root,
    initialize_session_root,
    open_session_root,
)
from app.operations.setup import OriginProfile, derive_capability_verifier
from app.tests.recovery_fixture import (
    Recovery,
    Signer,
    b64,
    current_generation,
    receipt_for,
    request_for,
    trust_v2,
)
from app.tests.test_deployment_receipt_contracts import trust_value

ROOT = Path(__file__).resolve().parents[2]
OWNER = {"expected_uid": os.getuid(), "expected_gid": os.getgid()}


def profile():
    return OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=4193)


@pytest.fixture
def root(tmp_path):
    directory = tmp_path / "root"
    initialize_session_root(directory, profile=profile(), recovery_epoch=1, **OWNER)
    return directory


def materials(root_dir, *, signer=None, trust_signers=None, epoch=1, subject=None, **changes):
    subject = subject or profile()
    signer = signer or Signer()
    trust = trust_v2(subject, *(trust_signers or (signer,)))
    generation_id, digest = current_generation(root_dir, profile(), epoch)
    request = request_for(subject, epoch=epoch, generation_id=generation_id, manifest_sha256=digest)
    verifier = derive_capability_verifier(b64(os.urandom(32)))
    receipt = receipt_for(subject, request, signer, trust, new_verifier=verifier, **changes)
    return request, receipt, trust


def verify(request, receipt, trust, subject=None):
    return verify_recovery_receipt(receipt, request_bytes=request, trust_bytes=trust,
                                   profile=subject or profile())


def advance(root_dir, request, receipt, trust):
    return advance_session_root(root_dir, profile=profile(), receipt_bytes=receipt,
                                request_bytes=request, trust_bytes=trust, **OWNER)


def snapshot(directory):
    return {str(path.relative_to(directory)): path.read_bytes() if path.is_file() else None
            for path in sorted(directory.rglob("*"))}


# --- contracts -------------------------------------------------------------------------


def test_an_authentic_request_bound_receipt_verifies_over_its_canonical_preimage(root):
    request, receipt, trust = materials(root)
    verified = verify(request, receipt, trust)
    assert verified == parse_canonical(receipt)
    assert verified["new_epoch"] == 2 and verified["previous_epoch"] == 1
    assert parse_recovery_request(request, profile=profile())["kind"] == "owner_recovery"
    # the request never carries a capability or a verifier
    assert b"verifier" not in request and b"capability" not in request


def test_a_receipt_signed_by_a_key_outside_the_trust_set_is_refused(root):
    stranger = Signer()
    request, receipt, trust = materials(root, signer=stranger, trust_signers=(Signer(),))
    with pytest.raises(ReceiptWireError):
        verify(request, receipt, trust)


def test_a_trust_set_naming_the_key_id_with_another_public_key_is_refused(root):
    signer, impostor = Signer(), Signer()
    impostor.key_id = signer.key_id
    request, receipt, _ = materials(root, signer=signer)
    trust = trust_v2(profile(), impostor)
    receipt = receipt_for(profile(), request, signer, trust,
                          new_verifier=derive_capability_verifier(b64(os.urandom(32))))
    with pytest.raises(ReceiptWireError) as error:
        verify(request, receipt, trust)
    assert error.value.code == "receipt_signature_invalid"


def test_a_bad_signature_is_refused(root):
    request, receipt, trust = materials(root)
    value = parse_canonical(receipt)
    raw = bytearray(value["signature"].encode())
    raw[10] = ord("A") if raw[10] != ord("A") else ord("B")
    value["signature"] = raw.decode()
    with pytest.raises(ReceiptWireError) as error:
        verify(request, canonical_json(value), trust)
    assert error.value.code == "receipt_signature_invalid"
    unsigned_request, unsigned, unsigned_trust = materials(root, sign=False)
    with pytest.raises(ReceiptWireError):
        verify(unsigned_request, unsigned, unsigned_trust)


@pytest.mark.parametrize("damage", ["extra_field", "missing_field", "noncanonical", "kind", "adapter",
                                    "bool_epoch", "bad_hex"])
def test_a_schema_violation_is_refused_before_any_signature_check(root, damage):
    request, receipt, trust = materials(root)
    value = parse_canonical(receipt)
    if damage == "extra_field":
        value["note"] = "x"
    elif damage == "missing_field":
        del value["new_verifier_sha256"]
    elif damage == "kind":
        value["kind"] = "extension_stage"
    elif damage == "adapter":
        value["operator_adapter"] = STAGE_ADAPTER
    elif damage == "bool_epoch":
        value["new_epoch"] = True
    elif damage == "bad_hex":
        value["new_manifest_sha256"] = "G" * 64
    raw = canonical_json(value)
    if damage == "noncanonical":
        raw = json.dumps(value, indent=1).encode()
    with pytest.raises(ReceiptWireError):
        parse_recovery_receipt(raw)
    with pytest.raises(ReceiptWireError):
        verify(request, raw, trust)


def test_a_stage_only_key_never_signs_a_recovery(root):
    stage_only = Signer(adapters=(STAGE_ADAPTER,))
    request, receipt, trust = materials(root, signer=stage_only)
    assert parse_trust_set_v2(trust, profile=profile())["keys"][0]["adapter_ids"] == [STAGE_ADAPTER]
    with pytest.raises(ReceiptWireError):
        verify(request, receipt, trust)
    # the same key listed for recovery signs; a recovery-only key is fine as well
    recovery_only = Signer(adapters=(RECOVERY_ADAPTER,))
    verify(*materials(root, signer=recovery_only))


@pytest.mark.parametrize("which", ["instance", "origin"])
def test_cross_instance_and_cross_origin_receipts_are_refused(root, which):
    other = (OriginProfile.local(instance_id="3" * 32, path_id="2" * 32, port=4193) if which == "instance"
             else OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=4194))
    request, receipt, trust = materials(root)
    with pytest.raises(ReceiptWireError):
        verify(request, receipt, trust, other)
    # a request and receipt sealed for the other deployment do not verify here either
    foreign_request, foreign_receipt, foreign_trust = materials(root, subject=other)
    verify(foreign_request, foreign_receipt, foreign_trust, other)
    with pytest.raises(ReceiptWireError):
        verify(foreign_request, foreign_receipt, foreign_trust)


def test_a_receipt_bound_to_another_request_is_refused(root):
    _, receipt, trust = materials(root)
    other_request, _, _ = materials(root)
    with pytest.raises(ReceiptWireError):
        verify(other_request, receipt, trust)


@pytest.mark.parametrize("when", ["before_request", "after_expiry"])
def test_a_stale_receipt_outside_its_request_window_is_refused(root, when):
    signer = Signer()
    trust = trust_v2(profile(), signer)
    generation_id, digest = current_generation(root, profile(), 1)
    created = time.time_ns() // 1_000_000 - 3_600_000
    request = request_for(profile(), epoch=1, generation_id=generation_id, manifest_sha256=digest,
                          created_ms=created, ttl_seconds=600)
    completed = created - created % 1000 - 1 if when == "before_request" else created + 601_000
    receipt = receipt_for(profile(), request, signer, trust,
                          new_verifier=derive_capability_verifier(b64(os.urandom(32))), completed_ms=completed)
    with pytest.raises(ReceiptWireError):
        verify(request, receipt, trust)


def test_a_skipped_epoch_is_refused_at_parse_time(root):
    request, receipt, _ = materials(root)
    value = parse_canonical(request)
    value["effect_payload"]["target_recovery_epoch"] = 3
    value.pop("request_digest")
    value["request_digest"] = b64(sha256(canonical_json(value)).digest())
    with pytest.raises(ReceiptWireError):
        parse_recovery_request(canonical_json(value), profile=profile())
    skipped = parse_canonical(receipt)
    skipped["new_epoch"] = 3
    with pytest.raises(ReceiptWireError):
        parse_recovery_receipt(canonical_json(skipped))


def test_a_v1_trust_set_or_another_trust_set_never_verifies_a_recovery(root):
    request, receipt, _ = materials(root)
    with pytest.raises(ReceiptWireError):
        verify(request, receipt, canonical_json(trust_value(profile())))
    with pytest.raises(ReceiptWireError):
        verify(request, receipt, trust_v2(profile(), Signer()))


def test_trust_set_v2_is_v1_plus_exactly_the_recovery_adapter_and_v1_stays_unchanged(root):
    signer = Signer()
    wrong = [{"operator_adapter": STAGE_ADAPTER, "operator_version": "1.0.0",
              "deployment_profile_id": profile().deployment_profile_id}] * 2
    for adapters in (wrong, list(reversed(json.loads(trust_v2(profile(), signer))["adapters"]))):
        with pytest.raises(ReceiptWireError):
            parse_trust_set_v2(trust_v2(profile(), signer, adapters=adapters), profile=profile())
    unsorted = json.loads(trust_v2(profile(), signer))
    unsorted["keys"][0]["adapter_ids"].reverse()
    with pytest.raises(ReceiptWireError):
        parse_trust_set_v2(canonical_json(unsorted), profile=profile())
    # the v1 schema still admits only the stage adapter and its v1 schema id
    with pytest.raises(ReceiptWireError):
        parse_trust_set(trust_v2(profile(), signer), profile=profile())


def test_an_existing_v1_instance_upgrades_only_through_a_v2_binding_its_exact_v1_bytes():
    subject = profile()
    v1 = canonical_json(trust_value(subject))
    v1_key = trust_value(subject)["keys"][0]
    kept, recovery = Signer(), Signer()
    kept.key_id = v1_key["key_id"]

    def upgraded(previous, entries):
        value = json.loads(trust_v2(subject, recovery, previous=previous))
        value["keys"] = sorted([*entries, *value["keys"]], key=lambda item: item["key_id"])
        return canonical_json(value)

    stage_entry = {**v1_key, "adapter_ids": [STAGE_ADAPTER]}
    assert verify_trust_set_upgrade(v1, upgraded(v1, [stage_entry]), profile=subject)
    with pytest.raises(ReceiptWireError):  # binds other bytes
        verify_trust_set_upgrade(v1, upgraded(v1 + b" ", [stage_entry]), profile=subject)
    with pytest.raises(ReceiptWireError):  # drops the v1 key
        verify_trust_set_upgrade(v1, upgraded(v1, []), profile=subject)
    with pytest.raises(ReceiptWireError):  # swaps the v1 public key
        verify_trust_set_upgrade(v1, upgraded(v1, [{**stage_entry, "public_key": kept.entry()["public_key"]}]),
                                 profile=subject)


# --- session-root-maintenance ----------------------------------------------------------


def test_maintenance_advances_to_exactly_the_receipts_generation(root):
    request, receipt, trust = materials(root)
    genesis = snapshot(root)
    result = advance(root, request, receipt, trust)
    value = parse_canonical(receipt)
    assert result["recovery_epoch"] == 2 and result["state"] == "recovered"
    assert result["generation_id"] == value["new_generation_id"]
    assert result["parent_generation_id"] == value["previous_generation_id"]
    assert result["recovery_receipt_sha256"] == sha256(receipt).hexdigest()
    # the flat genesis is never rewritten; the new generation sits beside it
    after = snapshot(root)
    assert {name: after[name] for name in genesis} == genesis
    assert set(after) - set(genesis) == {"current", "generations", f"generations/{result['generation_id']}",
                                         *(f"generations/{result['generation_id']}/{name}" for name in (
                                             "root.key", "manifest.json", "recovery-request.json",
                                             "recovery-receipt.json"))}
    handle = open_session_root(root, profile=profile(), recovery_epoch=2, **OWNER)
    assert dict(handle.recovery) == {"request": request, "receipt": receipt}
    assert handle.receipt["recovery_epoch"] == 2
    handle.close()
    # the configuration still naming epoch 1 is a rollback: nothing serves
    with pytest.raises(SessionRootError):
        open_session_root(root, profile=profile(), recovery_epoch=1, **OWNER)
    with pytest.raises(SessionRootError):
        initialize_session_root(root, profile=profile(), recovery_epoch=1, **OWNER)


def test_rerunning_maintenance_over_the_advanced_state_is_a_verify_only_no_op(root):
    request, receipt, trust = materials(root)
    first = advance(root, request, receipt, trust)
    before = snapshot(root)
    assert advance(root, request, receipt, trust) == first
    assert snapshot(root) == before


def test_a_crash_before_the_pointer_moved_resumes_only_from_a_complete_generation(root, monkeypatch):
    request, receipt, trust = materials(root)
    real_rename = os.rename

    def crash(*args, **kwargs):
        raise OSError("interrupted")

    monkeypatch.setattr(os, "rename", crash)
    with pytest.raises(SessionRootError):
        advance(root, request, receipt, trust)
    monkeypatch.setattr(os, "rename", real_rename)
    # an interrupted advance is neither the flat genesis nor a complete layout: nothing
    # serves until maintenance is re-run and completes it
    with pytest.raises(SessionRootError):
        open_session_root(root, profile=profile(), recovery_epoch=1, **OWNER)
    assert advance(root, request, receipt, trust)["recovery_epoch"] == 2
    assert not (root / "current.next").exists()
    open_session_root(root, profile=profile(), recovery_epoch=2, **OWNER).close()


def test_an_incomplete_generation_is_never_repaired_or_replaced(root):
    request, receipt, trust = materials(root)
    new_id = parse_canonical(receipt)["new_generation_id"]
    (root / "generations" / new_id).mkdir(parents=True, mode=0o700)
    (root / "generations").chmod(0o700)
    before = snapshot(root)
    with pytest.raises(SessionRootError):
        advance(root, request, receipt, trust)
    assert snapshot(root) == before


def test_a_stray_generation_or_foreign_member_fails_closed(root):
    request, receipt, trust = materials(root)
    advance(root, request, receipt, trust)
    stray = root / "generations" / "00000000-0000-4000-8000-000000000000"
    stray.mkdir(mode=0o700)
    with pytest.raises(SessionRootError):
        open_session_root(root, profile=profile(), recovery_epoch=2, **OWNER)
    stray.rmdir()
    (root / "notes").write_bytes(b"x")
    with pytest.raises(SessionRootError):
        open_session_root(root, profile=profile(), recovery_epoch=2, **OWNER)


def test_a_stale_or_replayed_receipt_never_advances_a_later_generation(root):
    request, receipt, trust = materials(root)
    advance(root, request, receipt, trust)
    signer = Signer()
    next_request, next_receipt, next_trust = materials(root, signer=signer, epoch=2)
    assert advance(root, next_request, next_receipt, next_trust)["recovery_epoch"] == 3
    before = snapshot(root)
    # the first receipt names generation 1 as its previous: stale against epoch 3
    with pytest.raises(SessionRootError):
        advance(root, request, receipt, trust)
    assert snapshot(root) == before
    open_session_root(root, profile=profile(), recovery_epoch=3, **OWNER).close()


def test_a_receipt_for_another_previous_generation_or_a_skipped_epoch_is_refused(root, tmp_path):
    other = tmp_path / "other-root"
    initialize_session_root(other, profile=profile(), recovery_epoch=1, **OWNER)
    request, receipt, trust = materials(other)
    before = snapshot(root)
    with pytest.raises(SessionRootError):
        advance(root, request, receipt, trust)
    assert snapshot(root) == before
    # epoch 2 -> 3 materials (from an advanced copy) never apply to a root still at 1
    first = materials(other)
    advance(other, *first)
    skipped = materials(other, epoch=2)
    with pytest.raises(SessionRootError):
        advance(root, *skipped)
    assert snapshot(root) == before


def test_the_recovery_fixture_describes_one_complete_step(root):
    arguments = {"session_root_dir": root, **OWNER, "deployment_config": None}
    recovery = Recovery(profile(), arguments)
    assert recovery.arguments["deployment_config"]["recovery_epoch"] == 2
    assert recovery.advance()["recovery_epoch"] == 2


# --- schema exports --------------------------------------------------------------------


def test_recovery_schema_exports_are_exact_fresh_bytes_beside_unchanged_v1(tmp_path):
    from app.deployment import receipt_schema_exports, recovery_schema_exports

    recovery_schema_exports.write_schemas(tmp_path)
    for name, schema in recovery_schema_exports.exported_schemas().items():
        expected = (json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        assert (tmp_path / name).read_bytes() == expected
        assert (ROOT / "schemas/v2/deployment" / name).read_bytes() == expected
        assert schema["$id"].startswith("urn:deeptwin:schemas:v2:deployment:")
    assert set(receipt_schema_exports.exported_schemas()) == {
        "receipt-stage-v1.schema.json", "public-trust-set-v1.schema.json"}
