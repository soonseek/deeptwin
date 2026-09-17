"""Task 25 slice 1b: closed worker-private stage probe messages
(contracts/extension-worker-probe.md §2/§2a).

Pure codecs over canonical strict JSON payload bytes: a request carries the
control side's retained request/receipt digests and a fresh 32-byte nonce;
a reply repeats them as correlation and self-reports the worker's build
identity digests, platform, uid/gid and its (possibly empty) registered
operations. Values are inert; nothing here observes, authenticates or
admits anything.
"""

import base64
import dataclasses
import json
import secrets

import pytest

from app.domain.refs import canonical_json
from app.extensions.port_contracts import PORT_CONTRACTS
from app.workers.extension_probe_messages import (
    ProbeComponent,
    ProbeMessageError,
    ProbeReply,
    ProbeRequest,
    ProbeRuntime,
    encode_probe_reply,
    encode_probe_request,
    parse_probe_reply,
    parse_probe_request,
)

REQUEST_SHA = "a" * 64
RECEIPT_SHA = "b" * 64
IDENTITY_SHA = "c" * 64
SCHEMA_SET_SHA = "d" * 64
NONCE = bytes(range(32))
NONCE_TEXT = base64.urlsafe_b64encode(NONCE).rstrip(b"=").decode()
SERVICE = "ext-0123456789abcdef0123456789abcdef-07"
TOOL_OPERATIONS = PORT_CONTRACTS["tool-port-v1"].operations


def request_bytes(**changes):
    value = {
        "schema_version": "extension-stage-probe-v1",
        "request_blob_sha256": REQUEST_SHA,
        "receipt_blob_sha256": RECEIPT_SHA,
        "challenge": NONCE_TEXT,
    }
    value.update(changes)
    return canonical_json({k: v for k, v in value.items() if v is not ...})


def reply_fields(**changes):
    value = {
        "request_blob_sha256": REQUEST_SHA,
        "receipt_blob_sha256": RECEIPT_SHA,
        "challenge": NONCE,
        "service_identity": SERVICE,
        "build_identity_digest": IDENTITY_SHA,
        "port_contract_version": "tool-port-v1",
        "port_schema_set_digest": SCHEMA_SET_SHA,
        "platform": "linux/arm64",
        "uid": 22007,
        "gid": 22007,
        "registered_operations": (),
    }
    value.update(changes)
    return value


def reply_bytes(**changes):
    value = {
        "schema_version": "extension-stage-probe-result-v1",
        "request_blob_sha256": REQUEST_SHA,
        "receipt_blob_sha256": RECEIPT_SHA,
        "challenge": NONCE_TEXT,
        "service_identity": SERVICE,
        "component": {
            "build_identity_digest": IDENTITY_SHA,
            "port_contract_version": "tool-port-v1",
            "port_schema_set_digest": SCHEMA_SET_SHA,
        },
        "runtime": {
            "platform": "linux/arm64",
            "uid": 22007,
            "gid": 22007,
            "registered_operations": [],
        },
    }
    for key, item in changes.items():
        if "." in key:
            outer, inner = key.split(".", 1)
            if item is ...:
                value[outer].pop(inner)
            else:
                value[outer][inner] = item
        elif item is ...:
            value.pop(key)
        else:
            value[key] = item
    return canonical_json(value)


def test_a_request_round_trips_byte_for_byte_and_is_an_inert_frozen_value():
    raw = encode_probe_request(
        request_blob_sha256=REQUEST_SHA,
        receipt_blob_sha256=RECEIPT_SHA,
        challenge=NONCE,
    )
    assert raw == request_bytes()
    assert len(raw) <= 1024
    request = parse_probe_request(raw)
    assert type(request) is ProbeRequest
    assert request == ProbeRequest(REQUEST_SHA, RECEIPT_SHA, NONCE)
    assert request.challenge == NONCE and type(request.challenge) is bytes
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.challenge = b"x" * 32
    # a fresh nonce produces a different, still canonical, request
    other = encode_probe_request(
        request_blob_sha256=REQUEST_SHA,
        receipt_blob_sha256=RECEIPT_SHA,
        challenge=secrets.token_bytes(32),
    )
    assert other != raw and parse_probe_request(other).challenge != NONCE


def test_a_reply_round_trips_and_reports_plain_scalars_only():
    raw = encode_probe_reply(**reply_fields())
    assert raw == reply_bytes()
    assert len(raw) <= 4096
    reply = parse_probe_reply(raw)
    assert type(reply) is ProbeReply
    assert (reply.request_blob_sha256, reply.receipt_blob_sha256) == (
        REQUEST_SHA,
        RECEIPT_SHA,
    )
    assert reply.challenge == NONCE
    assert reply.service_identity == SERVICE
    assert reply.component == ProbeComponent(
        IDENTITY_SHA, "tool-port-v1", SCHEMA_SET_SHA
    )
    assert reply.runtime == ProbeRuntime("linux/arm64", 22007, 22007, ())
    # the full registry, codepoint-sorted, and every subset are representable
    full = encode_probe_reply(
        **reply_fields(registered_operations=tuple(sorted(TOOL_OPERATIONS)))
    )
    assert parse_probe_reply(full).runtime.registered_operations == tuple(
        sorted(TOOL_OPERATIONS)
    )
    assert json.loads(full)["runtime"]["registered_operations"] == sorted(
        TOOL_OPERATIONS
    )
    some = encode_probe_reply(
        **reply_fields(registered_operations=("cancel", "status"))
    )
    assert parse_probe_reply(some).runtime.registered_operations == ("cancel", "status")
    assert (
        parse_probe_reply(
            encode_probe_reply(**reply_fields(platform="linux/amd64"))
        ).runtime.platform
        == "linux/amd64"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "extension-stage-probe-result-v1"},
        {"schema_version": ...},
        {"request_blob_sha256": "A" * 64},
        {"request_blob_sha256": "a" * 63},
        {"receipt_blob_sha256": ...},
        {"challenge": NONCE_TEXT + "="},  # padded
        {"challenge": NONCE_TEXT[:-1] + "B"},  # noncanonical trailing bits
        {"challenge": NONCE_TEXT[:-1]},
        {"challenge": NONCE_TEXT[:-2] + "+/"},  # standard alphabet characters
        {"challenge": 1},
        {"challenge": None},
        {"extra": True},
    ],
)
def test_requests_outside_the_grammar_are_refused_with_the_closed_error(changes):
    with pytest.raises(ProbeMessageError, match="invalid probe message"):
        parse_probe_request(request_bytes(**changes))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xef\xbb\xbf" + b"{}",
        b"{}",
        b"[]",
        b"null",
        b'{"schema_version":"extension-stage-probe-v1","request_blob_sha256":"'
        + b"a" * 64
        + b'","receipt_blob_sha256":"'
        + b"b" * 64
        + b'","challenge":"'
        + NONCE_TEXT.encode()
        + b'" }',  # whitespace
        json.dumps(
            json.loads(request_bytes()), indent=1
        ).encode(),  # non-canonical layout
        b'{"request_blob_sha256":"'
        + b"a" * 64
        + b'","schema_version":"extension-stage-probe-v1"}',
        request_bytes() + b"\n",
        request_bytes() * 2,
        b"x" * 1025,
        canonical_json(
            {
                "schema_version": "extension-stage-probe-v1",
                "request_blob_sha256": REQUEST_SHA,
                "receipt_blob_sha256": RECEIPT_SHA,
                "challenge": NONCE_TEXT,
                "pad": "x" * 2000,
            }
        ),
    ],
)
def test_noncanonical_or_oversized_request_bytes_are_refused(raw):
    with pytest.raises(ProbeMessageError, match="invalid probe message"):
        parse_probe_request(raw)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "extension-stage-probe-v1"},
        {"service_identity": "Ext-1"},
        {"service_identity": "x" * 65},
        {"service_identity": ...},
        {"component.port_contract_version": "provider-port-v1"},
        {"component.build_identity_digest": "z" * 64},
        {"component.port_schema_set_digest": ...},
        {"component.extra": 1},
        {"runtime.platform": "linux/386"},
        {"runtime.platform": "LINUX/AMD64"},
        {"runtime.uid": 0},
        {"runtime.gid": 2**32},
        {"runtime.uid": True},
        {"runtime.uid": "22007"},
        {"runtime.registered_operations": ["status", "cancel"]},  # not codepoint-sorted
        {"runtime.registered_operations": ["cancel", "cancel"]},  # not unique
        {
            "runtime.registered_operations": ["describe_tools", "probe"]
        },  # not a tool operation
        {"runtime.registered_operations": "cancel"},
        {"runtime.registered_operations": [None]},
        {"runtime.registered_operations": ...},
        {"runtime.note": "x"},
        {"component": {}},
        {"runtime": []},
        {"challenge": NONCE_TEXT + "="},
        {"extra": {}},
    ],
)
def test_replies_outside_the_grammar_are_refused_with_the_closed_error(changes):
    with pytest.raises(ProbeMessageError, match="invalid probe message"):
        parse_probe_reply(reply_bytes(**changes))


def test_reply_bytes_over_the_cap_or_noncanonical_are_refused():
    with pytest.raises(ProbeMessageError, match="invalid probe message"):
        parse_probe_reply(json.dumps(json.loads(reply_bytes()), indent=2).encode())
    with pytest.raises(ProbeMessageError, match="invalid probe message"):
        parse_probe_reply(reply_bytes() + b" ")
    with pytest.raises(ProbeMessageError, match="invalid probe message"):
        parse_probe_reply(b"{" + b" " * 4096 + b"}")
    with pytest.raises(ProbeMessageError, match="invalid probe message"):
        # a float where an integer is required (built as raw bytes: the
        # canonical encoder itself never emits floats)
        parse_probe_reply(reply_bytes().replace(b'"uid":22007', b'"uid":22007.0'))
    with pytest.raises(ProbeMessageError, match="invalid probe message"):
        parse_probe_reply(request_bytes())  # a request is not a reply
    with pytest.raises(ProbeMessageError, match="invalid probe message"):
        parse_probe_request(reply_bytes())


@pytest.mark.parametrize(
    "changes",
    [
        {"challenge": b"x" * 31},
        {"challenge": b"x" * 33},
        {"challenge": NONCE_TEXT},  # str, not the 32 raw bytes
        {"challenge": bytearray(NONCE)},
        {"request_blob_sha256": "A" * 64},
        {"service_identity": "Ext-1"},
        {"service_identity": ""},
        {"platform": "darwin/arm64"},
        {"uid": 0},
        {"gid": -1},
        {"registered_operations": ["cancel"]},  # a list, not a tuple
        {"registered_operations": ("status", "cancel")},
        {"registered_operations": ("invoke_tool", "invoke_tool")},
        {"port_contract_version": "tool-port-v2"},
        {"build_identity_digest": IDENTITY_SHA[:-1]},
    ],
)
def test_encoders_refuse_values_outside_the_grammar_before_encoding(changes):
    fields = reply_fields(**changes)
    with pytest.raises(ProbeMessageError, match="invalid probe message"):
        encode_probe_reply(**fields)
    if set(changes) <= {"challenge", "request_blob_sha256"}:
        with pytest.raises(ProbeMessageError, match="invalid probe message"):
            encode_probe_request(
                request_blob_sha256=fields["request_blob_sha256"],
                receipt_blob_sha256=fields["receipt_blob_sha256"],
                challenge=fields["challenge"],
            )


def test_encoders_take_no_objects_and_the_error_never_reflects_input():
    secret = "SUPERSECRETVALUE" + "0" * 48
    with pytest.raises(ProbeMessageError) as failure:
        encode_probe_request(
            request_blob_sha256=secret, receipt_blob_sha256=RECEIPT_SHA, challenge=NONCE
        )
    assert (
        secret not in str(failure.value)
        and str(failure.value) == "invalid probe message"
    )
    with pytest.raises(TypeError):
        encode_probe_reply(reply_fields())  # keyword-only, never a positional object
    with pytest.raises(ProbeMessageError):
        parse_probe_reply(reply_bytes().decode())  # bytes only


def test_the_urlsafe_alphabet_is_rendered_and_the_standard_one_refused():
    # review: bytes(range(32)) never reaches sextets 62/63, so a standard
    # alphabet encoder could pass the other cases by luck
    nonce = bytes([0xFB, 0xFF]) * 16
    raw = encode_probe_request(
        request_blob_sha256=REQUEST_SHA,
        receipt_blob_sha256=RECEIPT_SHA,
        challenge=nonce,
    )
    text = json.loads(raw)["challenge"]
    assert "-" in text and "_" in text and "+" not in text and "/" not in text
    assert text == base64.urlsafe_b64encode(nonce).rstrip(b"=").decode()
    assert parse_probe_request(raw).challenge == nonce
    standard = base64.b64encode(nonce).rstrip(b"=").decode()
    assert "+" in standard or "/" in standard
    with pytest.raises(ProbeMessageError, match="invalid probe message"):
        parse_probe_request(request_bytes(challenge=standard))
    for uid in (1, 2**32 - 1):
        assert (
            parse_probe_reply(encode_probe_reply(**reply_fields(uid=uid))).runtime.uid
            == uid
        )
    longest = "e" + "x" * 63
    assert (
        parse_probe_reply(
            encode_probe_reply(**reply_fields(service_identity=longest))
        ).service_identity
        == longest
    )


def test_values_never_print_their_nonce_or_digests_and_odd_objects_are_refused():
    request = parse_probe_request(request_bytes())
    reply = parse_probe_reply(reply_bytes())
    for shown in (repr(request), str(request), repr(reply), str(reply)):
        assert NONCE_TEXT not in shown and repr(NONCE) not in shown
        assert REQUEST_SHA not in shown and IDENTITY_SHA not in shown

    class Weird:
        def __eq__(self, other):
            raise RuntimeError("boom")

        __ne__ = __eq__
        __hash__ = object.__hash__

    for name in reply_fields():
        with pytest.raises(ProbeMessageError, match="invalid probe message"):
            encode_probe_reply(**reply_fields(**{name: Weird()}))
    import copy
    import pickle

    error = ProbeMessageError()
    assert (
        str(copy.copy(error))
        == str(pickle.loads(pickle.dumps(error)))
        == "invalid probe message"
    )


def test_the_module_imports_no_api_static_or_server_code():
    import subprocess
    import sys
    from pathlib import Path

    probe = (
        "import sys; import app.workers.extension_probe_messages; "
        "print(sorted(name for name in sys.modules "
        "if name == 'app.server' or name.startswith(('app.api', 'app.static'))))"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=Path(__file__).resolve().parents[2],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert completed.stdout.strip() == "[]"
