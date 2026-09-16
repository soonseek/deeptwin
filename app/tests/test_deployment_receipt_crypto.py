"""Public-only Ed25519 verification and signed receipt fixture conformance."""

import importlib
import json
import subprocess
import sys
from base64 import urlsafe_b64decode, urlsafe_b64encode
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from app.domain.refs import canonical_json
from app.operations.setup import OriginProfile
from app.tests.deployment_receipt_session_fixture import (
    NODE_HELPER,
    OwnedReceiptSession,
    node_runtime,
)
from app.tests.deployment_source_fixture import profile as make_profile
from app.tests.test_deployment_prepare_contracts import matching_bundle

RFC8032 = [
    (
        "test-1",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        (
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555"
            "fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        ),
    ),
    (
        "test-2",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        (
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
            "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
        ),
    ),
    (
        "test-3",
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        (
            "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
            "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"
        ),
    ),
    (
        "test-1024-message-is-1023-bytes",
        "278117fc144c72340f67d0f2316e8386ceffbf2b2428c9c51fef7c597f1d426e",
        (
            "08b8b2b733424243760fe426a4b54908632110a66c2f6591eabd3345e3e4eb98"
        "fa6e264bf09efe12ee50f8f54e9f77b1e355f6c50544e23fb1433ddf73be84d8"
        "79de7c0046dc4996d9e773f4bc9efe5738829adb26c81b37c93a1b270b20329d"
        "658675fc6ea534e0810a4432826bf58c941efb65d57a338bbd2e26640f89ffbc"
        "1a858efcb8550ee3a5e1998bd177e93a7363c344fe6b199ee5d02e82d522c4fe"
        "ba15452f80288a821a579116ec6dad2b3b310da903401aa62100ab5d1a36553e"
        "06203b33890cc9b832f79ef80560ccb9a39ce767967ed628c6ad573cb116dbef"
        "efd75499da96bd68a8a97b928a8bbc103b6621fcde2beca1231d206be6cd9ec7"
        "aff6f6c94fcd7204ed3455c68c83f4a41da4af2b74ef5c53f1d8ac70bdcb7ed1"
        "85ce81bd84359d44254d95629e9855a94a7c1958d1f8ada5d0532ed8a5aa3fb2"
        "d17ba70eb6248e594e1a2297acbbb39d502f1a8c6eb6f1ce22b3de1a1f40cc24"
        "554119a831a9aad6079cad88425de6bde1a9187ebb6092cf67bf2b13fd65f270"
        "88d78b7e883c8759d2c4f5c65adb7553878ad575f9fad878e80a0c9ba63bcbcc"
        "2732e69485bbc9c90bfbd62481d9089beccf80cfe2df16a2cf65bd92dd597b07"
        "07e0917af48bbb75fed413d238f5555a7a569d80c3414a8d0859dc65a46128ba"
        "b27af87a71314f318c782b23ebfe808b82b0ce26401d2e22f04d83d1255dc51a"
        "ddd3b75a2b1ae0784504df543af8969be3ea7082ff7fc9888c144da2af58429e"
        "c96031dbcad3dad9af0dcbaaaf268cb8fcffead94f3c7ca495e056a9b47acdb7"
        "51fb73e666c6c655ade8297297d07ad1ba5e43f1bca32301651339e22904cc8c"
        "42f58c30c04aafdb038dda0847dd988dcda6f3bfd15c4b4c4525004aa06eeff8"
        "ca61783aacec57fb3d1f92b0fe2fd1a85f6724517b65e614ad6808d6f6ee34df"
        "f7310fdc82aebfd904b01e1dc54b2927094b2db68d6f903b68401adebf5a7e08"
        "d78ff4ef5d63653a65040cf9bfd4aca7984a74d37145986780fc0b16ac451649"
        "de6188a7dbdf191f64b5fc5e2ab47b57f7f7276cd419c17a3ca8e1b939ae49e4"
        "88acba6b965610b5480109c8b17b80e1b7b750dfc7598d5d5011fd2dcc5600a3"
        "2ef5b52a1ecc820e308aa342721aac0943bf6686b64b2579376504ccc493d97e"
        "6aed3fb0f9cd71a43dd497f01f17c0e2cb3797aa2a2f256656168e6c496afc5f"
        "b93246f6b1116398a346f1a641f3b041e989f7914f90cc2c7fff357876e506b5"
        "0d334ba77c225bc307ba537152f3f1610e4eafe595f6d9d90d11faa933a15ef1"
        "369546868a7f3a45a96768d40fd9d03412c091c6315cf4fde7cb68606937380d"
        "b2eaaa707b4c4185c32eddcdd306705e4dc1ffc872eeee475a64dfac86aba41c"
            "0618983f8741c5ef68d3a101e8a3b8cac60c905c15fc910840b94c00a0b9d0"
        ),
        (
            "0aab4c900501b3e24d7cdf4663326a3a87df5e4843b2cbdb67cbf6e460fec350"
            "aa5371b1508f9f4528ecea23c436d94b5e8fcd4f681e30a6ac00a9704a188a03"
        ),
    ),
    (
        "test-sha-abc-message-is-digest",
        "ec172b93ad5e563bf4932c70e1245034c35467ef2efd4d64ebf819683467e2bf",
        (
            "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
            "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f"
        ),
        (
            "dc2a4459e7369633a52b1bf277839a00201009a3efbf3ecb69bea2186c26b589"
            "09351fc9ac90b3ecfdfbc7c66431e0303dca179c138ac17ad9bef1177331a704"
        ),
    ),
]


def implementation():
    try:
        return importlib.import_module("app.deployment.receipt_crypto")
    except ModuleNotFoundError:
        pytest.fail("Deployment receipt crypto implementation is missing")


@pytest.mark.parametrize("_name,key_hex,message_hex,signature_hex", RFC8032)
def test_all_five_rfc8032_pure_ed25519_public_vectors(
    _name, key_hex, message_hex, signature_hex
):
    module = implementation()
    message = bytes.fromhex(message_hex)
    verified = module.verify_detached(
        bytes.fromhex(key_hex), message, bytes.fromhex(signature_hex)
    )
    assert type(verified) is bytes and verified == message
    if _name.startswith("test-1024"):
        assert len(message) == 1023


@pytest.mark.parametrize("target", ["message", "signature"])
def test_actual_bad_signature_has_distinct_safe_error(target):
    module = implementation()
    _, key_hex, message_hex, signature_hex = RFC8032[2]
    message, signature = bytearray.fromhex(message_hex), bytearray.fromhex(signature_hex)
    (message if target == "message" else signature)[0] ^= 1
    with pytest.raises(
        module.ReceiptWireError, match="^receipt_signature_invalid$"
    ) as error:
        module.verify_detached(bytes.fromhex(key_hex), bytes(message), bytes(signature))
    assert error.value.code == "receipt_signature_invalid"


@pytest.mark.parametrize(
    "key,message,signature",
    [
        ("not-bytes", b"", b"s" * 64),
        (b"k" * 31, b"", b"s" * 64),
        (b"k" * 33, b"", b"s" * 64),
        (b"k" * 32, "not-bytes", b"s" * 64),
        (b"k" * 32, b"", bytearray(b"s" * 64)),
        (b"k" * 32, b"", b"s" * 63),
        (b"k" * 32, b"", b"s" * 65),
    ],
)
def test_malformed_input_is_not_misclassified_as_bad_signature(
    key, message, signature
):
    module = implementation()
    with pytest.raises(module.ReceiptWireError, match="^receipt_invalid$") as error:
        module.verify_detached(key, message, signature)
    assert error.value.code == "receipt_invalid"


@pytest.mark.parametrize("kind", ["scalar_l", "small_order_key", "small_order_r"])
def test_scalar_and_point_rejection_corpus(kind):
    module = implementation()
    _, key_hex, message_hex, signature_hex = RFC8032[1]
    key = bytes.fromhex(key_hex)
    message = bytes.fromhex(message_hex)
    signature = bytearray.fromhex(signature_hex)
    if kind == "scalar_l":
        order = 2**252 + 27742317777372353535851937790883648493
        signature[32:] = order.to_bytes(32, "little")
    elif kind == "small_order_key":
        key = b"\0" * 32
    else:
        signature[:32] = b"\0" * 32
    with pytest.raises(
        module.ReceiptWireError, match="^receipt_signature_invalid$"
    ):
        module.verify_detached(key, message, bytes(signature))


def test_returned_provider_message_is_compared_not_tested_for_truthiness(monkeypatch):
    module = implementation()

    class WrongVerifyKey:
        def __init__(self, _key):
            pass

        def verify(self, _message, _signature):
            return b"wrong-but-truthy"

    monkeypatch.setattr(module, "VerifyKey", WrongVerifyKey)
    with pytest.raises(module.ReceiptWireError, match="^receipt_invalid$"):
        module.verify_detached(b"k" * 32, b"expected", b"s" * 64)


def test_arbitrary_provider_programming_failure_is_not_hidden(monkeypatch):
    module = implementation()

    class BrokenVerifyKey:
        def __init__(self, _key):
            raise RuntimeError("provider-programming-canary")

    monkeypatch.setattr(module, "VerifyKey", BrokenVerifyKey)
    with pytest.raises(RuntimeError, match="provider-programming-canary"):
        module.verify_detached(b"k" * 32, b"expected", b"s" * 64)


def test_structure_only_import_does_not_load_nacl_and_missing_library_never_passes():
    code = r'''
import builtins
import sys
real_import = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == "nacl" or name.startswith("nacl."):
        raise ModuleNotFoundError("blocked nacl")
    return real_import(name, *args, **kwargs)
builtins.__import__ = blocked
import app.deployment.receipt_contracts
assert not any(name == "nacl" or name.startswith("nacl.") for name in sys.modules)
try:
    import app.deployment.receipt_crypto
except ModuleNotFoundError:
    raise SystemExit(0)
raise SystemExit(9)
'''
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=".",
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/deployment-receipt-ed25519-v1.json"


def test_missing_node_runtime_is_an_explicit_prerequisite_failure():
    with pytest.raises(pytest.fail.Exception, match="Node.js prerequisite missing"):
        node_runtime(environ={}, which=lambda _name: None)


def fixture():
    return json.loads(FIXTURE_PATH.read_bytes())


def decode(value):
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))


def encode(value):
    return urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def verify_case(case):
    module = importlib.import_module("app.deployment.receipt_contracts")
    origin = OriginProfile.from_dict(case["profile"])
    return module.verify_receipt(
        case["receipt_utf8"].encode(),
        request_bytes=case["request_utf8"].encode(),
        trust_bytes=case["trust_utf8"].encode(),
        trust_sha256=case["trust_sha256"],
        profile=origin,
    )


def test_static_fixture_is_public_only_and_node_independently_verifies_preimages():
    value = fixture()
    assert value["schema"] == "deployment-receipt-ed25519-fixture-v1"
    assert value["algorithm"] == "Ed25519"
    assert len(value["cases"]) == 11
    serialized = FIXTURE_PATH.read_text(encoding="utf-8").lower()
    assert "private" not in serialized and "secret" not in serialized and "seed" not in serialized
    result = subprocess.run(
        [node_runtime(), NODE_HELPER, "--verify"],
        input=FIXTURE_PATH.read_bytes(),
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0 and result.stdout == b"" and result.stderr == b""


def test_no_argument_generator_emits_only_public_self_verifying_fixture():
    generated = subprocess.run(
        [node_runtime(), NODE_HELPER], capture_output=True, timeout=10, check=False
    )
    assert generated.returncode == 0 and generated.stderr == b""
    text = generated.stdout.decode("utf-8")
    assert "private" not in text.lower() and "secret" not in text.lower()
    assert len(json.loads(text)["cases"]) == 11
    checked = subprocess.run(
        [node_runtime(), NODE_HELPER, "--verify"],
        input=generated.stdout,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert checked.returncode == 0 and checked.stdout == checked.stderr == b""


@pytest.mark.parametrize(
    "name",
    [
        "valid_succeeded_present",
        "valid_failed_absent",
        "valid_failed_unknown",
        "valid_unknown_unknown",
    ],
)
def test_signed_fixture_happy_paths_return_fresh_parsed_receipt(name):
    contracts = importlib.import_module("app.deployment.receipt_contracts")
    case = next(entry for entry in fixture()["cases"] if entry["name"] == name)
    verified = verify_case(case)
    assert verified == contracts.parse_receipt(case["receipt_utf8"].encode())
    assert canonical_json(verified) == case["receipt_utf8"].encode()


@pytest.mark.parametrize(
    "name,want_type",
    [
        ("invalid_cross_request", "_ReceiptRequestMismatch"),
        ("invalid_tuple", "_ReceiptRequestMismatch"),
        ("invalid_profile", "ReceiptWireError"),
        ("invalid_key_adapter", "ReceiptWireError"),
        ("invalid_time", "ReceiptWireError"),
        ("invalid_expiry", "ReceiptWireError"),
        ("invalid_fact", "ReceiptWireError"),
    ],
)
def test_validly_signed_invalid_cases_preserve_private_relation_partition(
    name, want_type
):
    contracts = importlib.import_module("app.deployment.receipt_contracts")
    case = next(entry for entry in fixture()["cases"] if entry["name"] == name)
    with pytest.raises(contracts.ReceiptWireError, match="^receipt_invalid$") as error:
        verify_case(case)
    assert type(error.value).__name__ == want_type
    assert error.value.code == "receipt_invalid"


def test_forged_mismatch_is_signature_invalid_before_request_classification():
    contracts = importlib.import_module("app.deployment.receipt_contracts")
    case = fixture()["cases"][0]
    receipt = json.loads(case["receipt_utf8"])
    receipt["request_nonce"] = encode(b"x" * 32)
    forged = {**case, "receipt_utf8": canonical_json(receipt).decode()}
    with pytest.raises(
        contracts.ReceiptWireError, match="^receipt_signature_invalid$"
    ) as error:
        verify_case(forged)
    assert type(error.value) is contracts.ReceiptWireError


UNSIGNED_FIELDS = [
    "schema",
    "domain",
    "request_id",
    "request_digest",
    "request_nonce",
    "kind",
    "instance_id",
    "origin_profile_digest",
    "deployment_profile_id",
    "operator_adapter",
    "operator_version",
    "effect_result",
    "started_at",
    "completed_at",
    "outcome",
    "failure_class",
    "claimed_facts",
    "verified_facts",
    "unverified_facts",
    "key_id",
    "trust_set_digest",
    "trust_class",
]


def mutate_field(receipt, field):
    replacements = {
        "schema": "deployment-receipt-v2",
        "domain": "deeptwin-deployment-receipt-v2",
        "request_id": "22345678-1234-4234-8234-123456789abc",
        "request_digest": encode(b"x" * 32),
        "request_nonce": encode(b"x" * 32),
        "kind": "extension_update",
        "instance_id": "2" * 32,
        "origin_profile_digest": encode(b"x" * 32),
        "deployment_profile_id": "portable-compose-v1",
        "operator_adapter": "future-adapter",
        "operator_version": "1.0.1",
        "started_at": "2023-11-14T22:13:20.500Z",
        "completed_at": "2023-11-14T22:13:24.000Z",
        "outcome": "failed",
        "failure_class": "effect_failed",
        "claimed_facts": ["image_identity"],
        "verified_facts": ["image_identity"],
        "unverified_facts": ["image_identity"],
        "key_id": "22345678-1234-4234-8234-123456789abc",
        "trust_set_digest": encode(b"x" * 32),
        "trust_class": "runtime_worker",
    }
    if field == "effect_result":
        receipt[field]["new_service"]["reachable_after_effect"] = False
    else:
        receipt[field] = replacements[field]


@pytest.mark.parametrize("field", UNSIGNED_FIELDS)
def test_each_unsigned_receipt_field_is_covered_by_signature_or_intrinsic_checks(field):
    contracts = importlib.import_module("app.deployment.receipt_contracts")
    case = deepcopy(fixture()["cases"][0])
    receipt = json.loads(case["receipt_utf8"])
    mutate_field(receipt, field)
    case["receipt_utf8"] = canonical_json(receipt).decode()
    with pytest.raises(contracts.ReceiptWireError):
        verify_case(case)


@pytest.mark.parametrize(
    "change",
    ["pin_type", "pin_upper", "pin_wrong", "trust_bytes", "key", "request", "profile"],
)
def test_actual_request_trust_pin_key_and_profile_are_reparsed_and_checked(change):
    contracts = importlib.import_module("app.deployment.receipt_contracts")
    case = deepcopy(fixture()["cases"][0])
    origin = OriginProfile.from_dict(case["profile"])
    raw = case["receipt_utf8"].encode()
    request_bytes = case["request_utf8"].encode()
    trust_bytes = case["trust_utf8"].encode()
    pin = case["trust_sha256"]
    if change == "pin_type":
        pin = b"x" * 64
    elif change == "pin_upper":
        pin = pin.upper()
    elif change == "pin_wrong":
        pin = "0" * 64
    elif change == "trust_bytes":
        trust = json.loads(trust_bytes)
        trust["keys"].append(deepcopy(trust["keys"][0]))
        trust_bytes = canonical_json(trust)
        pin = sha256(trust_bytes).hexdigest()
    elif change == "key":
        trust = json.loads(trust_bytes)
        trust["keys"][0]["public_key"] = encode(b"x" * 32)
        trust_bytes = canonical_json(trust)
        pin = sha256(trust_bytes).hexdigest()
    elif change == "request":
        request_bytes = json.loads(request_bytes)
    else:
        origin = make_profile(portable=True)
    with pytest.raises(contracts.ReceiptWireError, match="^receipt_invalid$"):
        contracts.verify_receipt(
            raw,
            request_bytes=request_bytes,
            trust_bytes=trust_bytes,
            trust_sha256=pin,
            profile=origin,
        )


def test_pure_verification_is_independent_of_current_host_clock():
    case = fixture()["cases"][0]
    assert case["receipt_utf8"].find("2023-11-14") != -1
    assert verify_case(case)["outcome"] == "succeeded"


def actual_request(
    origin,
    *,
    ordinal,
    request_id=None,
    actor_id="87654321-4321-4321-8321-cba987654321",
    manifest_digest=None,
):
    from app.deployment.prepare_contracts import make_request

    bundle, topology, slot = matching_bundle()
    request = make_request(
        bundle=bundle,
        topology=topology,
        slot=slot,
        profile=origin,
        request_id=request_id or str(uuid4()),
        nonce=bytes([ordinal]) * 32,
        actor_ref={
            "kind": "actor",
            "id": actor_id,
            "version": 1,
            "sha256": "7" * 64,
        },
        created_ms=1700000000000 + ordinal * 10000,
        ttl_seconds=60,
    )
    if manifest_digest is not None:
        request["effect_payload"]["manifest_digest"] = manifest_digest
        unsigned = {
            key: value for key, value in request.items() if key != "request_digest"
        }
        request["request_digest"] = encode(sha256(canonical_json(unsigned)).digest())
    request_bytes = canonical_json(request)
    from app.deployment.prepare_contracts import parse_request

    assert parse_request(request_bytes, profile=origin) == request
    return request_bytes


def session_case(origin, request_bytes, case_name):
    with OwnedReceiptSession(origin) as session:
        response = session.case(request_bytes, case_name=case_name)
        return session.trust_bytes, decode(response["receipt_b64"])


@pytest.mark.parametrize(
    "case_name",
    [
        pytest.param("invalid_cross_request", id="ordinal-9-nonce"),
        pytest.param("invalid_tuple", id="all-f-manifest"),
    ],
)
def test_session_invalid_mutations_are_unequal_for_actual_collision_requests(case_name):
    contracts = importlib.import_module("app.deployment.receipt_contracts")
    origin = make_profile()
    if case_name == "invalid_cross_request":
        request_bytes = actual_request(origin, ordinal=9)
    else:
        request_bytes = actual_request(
            origin, ordinal=1, manifest_digest="f" * 64
        )
    trust_bytes, receipt_bytes = session_case(origin, request_bytes, case_name)
    with pytest.raises(contracts.ReceiptWireError, match="^receipt_invalid$") as error:
        contracts.verify_receipt(
            receipt_bytes,
            request_bytes=request_bytes,
            trust_bytes=trust_bytes,
            trust_sha256=sha256(trust_bytes).hexdigest(),
            profile=origin,
        )
    assert type(error.value).__name__ == "_ReceiptRequestMismatch"


@pytest.mark.parametrize(
    "origin,request_id,actor_id",
    [
        pytest.param(
            make_profile(),
            "12345678-1234-4234-8234-123456789abc",
            "87654321-4321-4321-8321-cba987654321",
            id="ordinary-local",
        ),
        pytest.param(
            make_profile(portable=True),
            "12345678-1234-4234-8234-123456789abc",
            "87654321-4321-4321-8321-cba987654321",
            id="ordinary-portable",
        ),
        pytest.param(
            OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=80),
            "00000000-0000-0000-0000-000000000001",
            "ffffffff-ffff-ffff-ffff-ffffffffffff",
            id="default-http-port-and-general-canonical-uuids",
        ),
    ],
)
def test_session_accepts_actual_profiles_and_canonical_nonnil_request_uuids(
    origin, request_id, actor_id
):
    contracts = importlib.import_module("app.deployment.receipt_contracts")
    request_bytes = actual_request(
        origin,
        ordinal=1,
        request_id=request_id,
        actor_id=actor_id,
    )
    trust_bytes, receipt_bytes = session_case(
        origin, request_bytes, "valid_succeeded_present"
    )
    assert contracts.verify_receipt(
        receipt_bytes,
        request_bytes=request_bytes,
        trust_bytes=trust_bytes,
        trust_sha256=sha256(trust_bytes).hexdigest(),
        profile=origin,
    )["request_id"] == request_id


def test_signed_full_id_grammar_identity_reaches_private_request_mismatch():
    contracts = importlib.import_module("app.deployment.receipt_contracts")
    origin = make_profile()
    request_bytes = actual_request(origin, ordinal=1)
    trust_bytes, receipt_bytes = session_case(
        origin, request_bytes, "invalid_service_identity"
    )
    with pytest.raises(contracts.ReceiptWireError, match="^receipt_invalid$") as error:
        contracts.verify_receipt(
            receipt_bytes,
            request_bytes=request_bytes,
            trust_bytes=trust_bytes,
            trust_sha256=sha256(trust_bytes).hexdigest(),
            profile=origin,
        )
    assert type(error.value).__name__ == "_ReceiptRequestMismatch"


def test_session_reuses_one_ephemeral_public_trust_set_for_two_actual_requests():
    contracts = importlib.import_module("app.deployment.receipt_contracts")
    origin = make_profile()
    with OwnedReceiptSession(origin) as session:
        trust_bytes = session.trust_bytes
        pin = sha256(trust_bytes).hexdigest()
        contracts.parse_trust_set(trust_bytes, profile=origin)
        outputs = []
        for ordinal, case_name in (
            (1, "valid_succeeded_present"),
            (2, "valid_failed_absent"),
        ):
            request_bytes = actual_request(origin, ordinal=ordinal)
            response = session.case(request_bytes, case_name=case_name)
            assert set(response) == {"receipt_b64", "unsigned_preimage_b64"}
            receipt_bytes = decode(response["receipt_b64"])
            preimage = decode(response["unsigned_preimage_b64"])
            receipt = contracts.verify_receipt(
                receipt_bytes,
                request_bytes=request_bytes,
                trust_bytes=trust_bytes,
                trust_sha256=pin,
                profile=origin,
            )
            unsigned = {key: value for key, value in receipt.items() if key != "signature"}
            assert canonical_json(unsigned) == preimage
            outputs.append((request_bytes, receipt))
        assert outputs[0][0] != outputs[1][0]
        assert outputs[0][1]["key_id"] == outputs[1][1]["key_id"]
        assert outputs[0][1]["trust_set_digest"] == outputs[1][1]["trust_set_digest"]


@pytest.mark.parametrize(
    "frames",
    [
        [{"op": "case", "request_b64": "AA", "case": "valid_succeeded_present"}],
        [{"op": "init", "profile": {**make_profile().as_dict(), "unknown": True}}],
        [{"op": "future", "profile": make_profile().as_dict()}],
        [
            {"op": "init", "profile": make_profile().as_dict()},
            {"op": "init", "profile": make_profile().as_dict()},
        ],
    ],
)
def test_session_rejects_ordering_unknown_fields_and_ops(frames):
    raw = "".join(json.dumps(frame, separators=(",", ":")) + "\n" for frame in frames)
    result = subprocess.run(
        [node_runtime(), NODE_HELPER, "--session"],
        input=raw,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 1 and result.stderr == "receipt_fixture_invalid\n"


@pytest.mark.parametrize("kind", ["frame", "request", "count"])
def test_session_enforces_frame_request_and_case_count_bounds(kind):
    origin = make_profile()
    init = json.dumps({"op": "init", "profile": origin.as_dict()}, separators=(",", ":")) + "\n"
    request = actual_request(origin, ordinal=1)
    case = json.dumps(
        {
            "op": "case",
            "request_b64": encode(request),
            "case": "valid_succeeded_present",
        },
        separators=(",", ":"),
    ) + "\n"
    if kind == "frame":
        raw = "x" * 131073 + "\n"
    elif kind == "request":
        oversized = encode(b"x" * 65537)
        raw = init + json.dumps(
            {"op": "case", "request_b64": oversized, "case": "valid_succeeded_present"},
            separators=(",", ":"),
        ) + "\n"
    else:
        raw = init + case * 65
    result = subprocess.run(
        [node_runtime(), NODE_HELPER, "--session"],
        input=raw,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 1 and result.stderr == "receipt_fixture_invalid\n"
    if kind == "count":
        assert len(result.stdout.splitlines()) == 65


def test_session_eof_releases_owned_child_without_signal():
    origin = make_profile()
    raw = json.dumps({"op": "init", "profile": origin.as_dict()}, separators=(",", ":")) + "\n"
    result = subprocess.run(
        [node_runtime(), NODE_HELPER, "--session"],
        input=raw,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0 and len(result.stdout.splitlines()) == 1
    assert result.stderr == ""


def test_session_rejects_unterminated_partial_frame_and_extra_arguments():
    origin = make_profile()
    partial = json.dumps({"op": "init", "profile": origin.as_dict()}, separators=(",", ":"))
    result = subprocess.run(
        [node_runtime(), NODE_HELPER, "--session"],
        input=partial,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 1 and result.stderr == "receipt_fixture_invalid\n"
    extra = subprocess.run(
        [node_runtime(), NODE_HELPER, "--session", "external-key"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert extra.returncode == 1 and extra.stderr == "receipt_fixture_invalid\n"
