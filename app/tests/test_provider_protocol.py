"""Legacy pull-order characterization and private pure framing tests."""

import pytest


def legacy():
    from app.adapters.claude_api import ClaudeAPIAdapter, StreamLimits

    adapter = object.__new__(ClaudeAPIAdapter)
    adapter._limits = StreamLimits()
    adapter._monotonic_ms = lambda: 0
    return adapter


def test_legacy_event_precedes_later_error_in_same_chunk():
    from app.adapters.claude_api import _ProtocolViolation

    events = legacy()._iter_sse(
        iter([b"event: ping\n\nevent: bad\ndata: {\n\n"]),
        cancelled=lambda: False,
        deadline_started_ms=0,
    )
    assert next(events) == ("ping", {"type": "ping"})
    with pytest.raises(_ProtocolViolation) as caught:
        next(events)
    assert caught.value.detail_code == "invalid_event_json"


@pytest.mark.parametrize("gate", ["cancel", "deadline"])
def test_legacy_gate_between_events(gate):
    from app.adapters.claude_api import _CancellationObserved, _ProtocolViolation

    adapter = legacy()
    cancelled = [False]
    events = adapter._iter_sse(
        iter([b"event: ping\n\nevent: ping\n\n"]),
        cancelled=lambda: cancelled[0],
        deadline_started_ms=0,
    )
    assert next(events) == ("ping", {"type": "ping"})
    if gate == "cancel":
        cancelled[0] = True
    else:
        adapter._monotonic_ms = lambda: 999999
    with pytest.raises(
        _CancellationObserved if gate == "cancel" else _ProtocolViolation
    ):
        next(events)


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b": comment\n\n", "invalid_event_name"),
        (b"event: ping\nevent: ping\n\n", "duplicate_event_field"),
        (b"event: ping\nid: x\n\n", "unknown_sse_field"),
        (b'event: ping\ndata: {"x":1,"x":2}\n\n', "duplicate_json_key"),
        (b"event: ping\ndata: NaN\n\n", "nonfinite_json_constant"),
        (b"event: ping\n", "incomplete_sse"),
    ],
)
def test_legacy_failure_codes(raw, code):
    from app.adapters.claude_api import _ProtocolViolation

    with pytest.raises(_ProtocolViolation) as caught:
        list(
            legacy()._iter_sse(
                iter([raw]), cancelled=lambda: False, deadline_started_ms=0
            )
        )
    assert caught.value.detail_code == code


def test_legacy_split_utf8_crlf_and_finite_float():
    raw = 'event: sample\r\ndata: {"text":"한","number":1.25}\r\n\r\n'.encode()
    assert list(
        legacy()._iter_sse(
            iter(bytes([b]) for b in raw),
            cancelled=lambda: False,
            deadline_started_ms=0,
        )
    ) == [("sample", {"text": "한", "number": 1.25})]


def test_pure_decoder_lazy_steps_and_json():
    from app.adapters.claude_protocol import SSEDecoder, ProtocolError, decode_json

    assert decode_json(b'{"number":1.25}') == {"number": 1.25}
    decoder = SSEDecoder()
    steps = decoder.feed(b"event: ping\n\nevent: bad\ndata: {\n\n")
    assert next(step for step in steps if step is not None) == (
        "ping",
        {"type": "ping"},
    )
    with pytest.raises(ProtocolError):
        list(steps)


@pytest.mark.parametrize(
    ("kwargs", "raw", "code"),
    [
        ({"max_total_bytes": 10}, b"event: ping\n\n", "stream_limit"),
        ({"max_event_bytes": 10}, b"event: ping\n\n", "event_limit"),
        ({"max_events": 1}, b"event: ping\n\nevent: ping\n\n", "event_count_limit"),
        ({}, b'event: ping\ndata: {"x":NaN}\n\n', "nonfinite_json_constant"),
        ({}, b'event: ping\ndata: {"x":1,"x":2}\n\n', "duplicate_json_key"),
    ],
)
def test_pure_limits_and_duplicate_fields(kwargs, raw, code):
    from app.adapters.claude_protocol import SSEDecoder, ProtocolError

    with pytest.raises(ProtocolError) as caught:
        list(SSEDecoder(**kwargs).feed(raw))
    assert caught.value.detail_code == code


def test_worker_import_graph_has_no_provider_client_or_authority():
    import os
    import subprocess
    import sys

    script = """
import sys
import app.workers.provider_worker
import app.workers.provider_transform
for name in sys.modules:
    assert not name.startswith(('app.adapters.claude_api', 'app.adapters.keychain',
        'app.runtime', 'app.api', 'app.server', 'app.custody', 'app.gateway',
        'httpx', 'anthropic', 'keyring')), name
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr


def test_legacy_stream_limit_precedes_the_next_cancel_gate():
    from app.adapters.claude_api import StreamLimits, _ProtocolViolation

    adapter = legacy()
    adapter._limits = StreamLimits(max_total_stream_bytes=1)
    gates = []

    def cancelled():
        gates.append(True)
        return len(gates) >= 3

    with pytest.raises(_ProtocolViolation) as caught:
        list(
            adapter._iter_sse(
                iter([b"event: ping\n\n"]), cancelled=cancelled, deadline_started_ms=0
            )
        )
    assert caught.value.detail_code == "stream_limit" and len(gates) == 2


def test_legacy_keeps_exact_before_after_read_and_line_gate_count():
    gates = []

    def cancelled():
        gates.append(True)
        return False

    assert list(
        legacy()._iter_sse(
            iter([b"event: ping\n\n"]), cancelled=cancelled, deadline_started_ms=0
        )
    ) == [("ping", {"type": "ping"})]
    assert len(gates) == 6


@pytest.mark.parametrize(
    "raw", [b"1e999", b"-1e999", b'{"nested":[1e999]}', b'{"nested":[-1e999]}']
)
@pytest.mark.parametrize("consumer", ["pure", "legacy"])
def test_finite_spelled_overflow_is_nonfinite_for_every_json_consumer(raw, consumer):
    from app.adapters.claude_protocol import decode_json, ProtocolError
    from app.adapters.claude_api import _strict_json, _ProtocolViolation

    decoder, error = (
        (decode_json, ProtocolError)
        if consumer == "pure"
        else (_strict_json, _ProtocolViolation)
    )
    with pytest.raises(error) as caught:
        decoder(raw, detail_code="invalid_event_json")
    assert caught.value.detail_code == "nonfinite_json_constant"


def test_legacy_sse_yields_prior_event_then_overflow_error():
    from app.adapters.claude_api import _ProtocolViolation

    events = legacy()._iter_sse(
        iter([b'event: ping\n\nevent: sample\ndata: {"nested":[1e999]}\n\n']),
        cancelled=lambda: False,
        deadline_started_ms=0,
    )
    assert next(events) == ("ping", {"type": "ping"})
    with pytest.raises(_ProtocolViolation) as caught:
        next(events)
    assert caught.value.detail_code == "nonfinite_json_constant"


def test_large_finite_float_stays_valid_in_both_consumers():
    from app.adapters.claude_protocol import decode_json
    from app.adapters.claude_api import _strict_json

    for decoder in (decode_json, _strict_json):
        assert decoder(
            b'{"positive":1e308,"negative":-1e308}', detail_code="invalid_event_json"
        ) == {"positive": 1e308, "negative": -1e308}
