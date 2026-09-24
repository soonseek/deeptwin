from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

httpx2 = pytest.importorskip("httpx2", reason="Claude adapter contract tests use the locked provider test extra")
pytest.importorskip("anthropic", reason="Claude adapter contract tests use the locked provider test extra")

from app.adapters.claude_api import (
    API_ORIGIN,
    CatalogError,
    ClaudeAPIAdapter,
    ClaudeBinding,
    MessageTurn,
    ModelSelection,
    ProviderStarted,
    ProviderTerminal,
    StreamLimits,
    TextDelta,
    ToolRequested,
    UsageObserved,
)
from app.adapters.keychain import (
    CredentialAccessDenied,
    CredentialError,
    CredentialNeedsUnlock,
    CredentialRef,
    CredentialNotFound,
    InMemoryCredentialVault,
    MacOSKeychainVault,
    SecretMaterial,
)


MODEL_ID = "claude-test-20260907"
OTHER_MODEL_ID = "claude-other-20260907"
SECRET = "sk-ant-api03-test-only-never-real"


def model(model_id=MODEL_ID, *, capabilities=None):
    return {
        "type": "model",
        "id": model_id,
        "display_name": model_id,
        "created_at": "2026-09-01T00:00:00Z",
        "max_input_tokens": 200_000,
        "max_tokens": 32_000,
        "capabilities": capabilities,
    }


def model_page(data, *, has_more=False, first_id=None, last_id=None):
    if first_id is None and data:
        first_id = data[0]["id"]
    if last_id is None and data:
        last_id = data[-1]["id"]
    return {
        "data": data,
        "has_more": has_more,
        "first_id": first_id,
        "last_id": last_id,
    }


def sse_event(name, payload):
    return f"event: {name}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


def message_start(*, model_id=MODEL_ID, message_id="msg_test_1", input_tokens=7, output_tokens=1):
    return (
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": model_id,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_creation_input_tokens": 2,
                    "cache_read_input_tokens": 3,
                },
            },
        },
    )


def message_delta(reason="end_turn", *, output_tokens=5):
    return (
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": reason, "stop_sequence": None},
            "usage": {"output_tokens": output_tokens},
        },
    )


def complete_text_stream(text="hello", *, reason="end_turn", model_id=MODEL_ID):
    events = [
        message_start(model_id=model_id),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        message_delta(reason),
        ("message_stop", {"type": "message_stop"}),
    ]
    return b"".join(sse_event(name, payload) for name, payload in events)


class Spy:
    def __init__(self, responder):
        self.responder = responder
        self.requests = []
        self.lock = threading.Lock()

    def __call__(self, request):
        body = request.read()
        with self.lock:
            self.requests.append((request, body))
        return self.responder(request, body)


def response(request, *, status=200, payload=None, body=None, headers=None):
    if payload is not None:
        return httpx2.Response(status, json=payload, headers=headers, request=request)
    return httpx2.Response(status, content=body or b"", headers=headers, request=request)


def api_fixture(*, stream_body=None, pages=None, message_status=200, message_headers=None):
    pages = list(pages or [model_page([model()])])

    def responder(request, body):
        if request.url.path == "/v1/models":
            cursor = request.url.params.get("after_id")
            index = 0 if cursor is None else 1
            if index >= len(pages):
                index = len(pages) - 1
            return response(request, payload=pages[index])
        if request.url.path == "/v1/messages":
            return response(
                request,
                status=message_status,
                body=stream_body if stream_body is not None else complete_text_stream(),
                headers={"content-type": "text/event-stream", **(message_headers or {})},
            )
        raise AssertionError(f"unexpected endpoint {request.url.path}")

    spy = Spy(responder)
    return spy, httpx2.MockTransport(spy)


def configured(
    *,
    stream_body=None,
    pages=None,
    limits=None,
    message_status=200,
    message_headers=None,
    clock_ms=None,
):
    vault = InMemoryCredentialVault()
    ref = vault.store("claude", SECRET)
    binding = ClaudeBinding(credential_ref=ref, workspace_id="wrk_test")
    spy, transport = api_fixture(
        stream_body=stream_body,
        pages=pages,
        message_status=message_status,
        message_headers=message_headers,
    )
    adapter = ClaudeAPIAdapter(
        vault=vault,
        transport=transport,
        clock_ms=clock_ms or (lambda: 1_800_000_000_000),
        limits=limits or StreamLimits(),
    )
    return adapter, binding, spy, vault


def turn(snapshot, binding, *, model_id=MODEL_ID, tools=(), messages=None):
    return MessageTurn(
        call_id="call-1",
        agent_id="agent-1",
        selection=ModelSelection(
            binding_id=binding.binding_id,
            catalog_id=snapshot.catalog_id,
            model_id=model_id,
        ),
        system="Only use declared client tools.",
        messages=messages or ({"role": "user", "content": "hello"},),
        tools=tools,
        max_tokens=128,
    )


def fetch_and_stream(adapter, binding, **kwargs):
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    return snapshot, list(adapter.stream(turn(snapshot, binding, **kwargs), snapshot, binding, explicit_action=True))


def terminal(events):
    matches = [event for event in events if isinstance(event, ProviderTerminal)]
    assert len(matches) == 1
    return matches[0]


def traceback_locals_repr(error):
    rendered = []
    current = error.__traceback__
    while current is not None:
        rendered.append(repr(current.tb_frame.f_locals))
        current = current.tb_next
    return "\n".join(rendered)


def test_api_mode_is_explicit_and_construction_has_no_network_or_secret_read():
    class CountingVault(InMemoryCredentialVault):
        def __init__(self):
            super().__init__()
            self.loads = 0

        def open(self, ref):
            self.loads += 1
            return super().open(ref)

    vault = CountingVault()
    ref = vault.store("claude", SECRET)
    binding = ClaudeBinding(ref)
    spy, transport = api_fixture()

    adapter = ClaudeAPIAdapter(vault=vault, transport=transport)
    assert spy.requests == []
    assert vault.loads == 0
    assert adapter.policy.mode == "api"
    assert "subscription" not in repr(adapter).lower()

    with pytest.raises(ValueError, match="API-only"):
        ClaudeAPIAdapter(vault=vault, transport=transport, mode="subscription")
    assert spy.requests == []
    assert vault.loads == 0
    assert binding.binding_id


def test_catalog_and_generation_each_require_an_explicit_action_before_secret_or_network_access():
    class CountingVault(InMemoryCredentialVault):
        def __init__(self):
            super().__init__()
            self.loads = 0

        def open(self, ref):
            self.loads += 1
            return super().open(ref)

    vault = CountingVault()
    binding = ClaudeBinding(vault.store("claude", SECRET))
    spy, transport = api_fixture()
    adapter = ClaudeAPIAdapter(vault=vault, transport=transport)

    assert inspect.signature(adapter.fetch_catalog).parameters["explicit_action"].default \
        is inspect.Parameter.empty
    assert inspect.signature(adapter.stream).parameters["explicit_action"].default \
        is inspect.Parameter.empty
    with pytest.raises(ValueError, match="explicit"):
        adapter.fetch_catalog(binding, explicit_action=False)
    assert vault.loads == 0
    assert spy.requests == []

    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    before_loads = vault.loads
    before_requests = len(spy.requests)
    with pytest.raises(ValueError, match="explicit"):
        adapter.stream(
            turn(snapshot, binding),
            snapshot,
            binding,
            explicit_action=False,
        )
    assert vault.loads == before_loads
    assert len(spy.requests) == before_requests


def test_adapter_module_imports_without_optional_provider_packages_and_loads_no_secret():
    repo = Path(__file__).resolve().parents[2]
    script = f"""
import builtins
import sys
sys.path.insert(0, {str(repo)!r})
real_import = builtins.__import__
def deny_provider_packages(name, *args, **kwargs):
    if name.split('.', 1)[0] in {{'anthropic', 'httpx2'}}:
        raise ModuleNotFoundError(name)
    return real_import(name, *args, **kwargs)
builtins.__import__ = deny_provider_packages
from app.adapters.claude_api import ClaudeAPIAdapter, ClaudeBinding, CatalogError
from app.adapters.keychain import CredentialRef
class Vault:
    opens = 0
    def open(self, ref):
        self.opens += 1
        raise AssertionError('secret vault must not be opened')
vault = Vault()
adapter = ClaudeAPIAdapter(vault=vault)
binding = ClaudeBinding(CredentialRef('claude', '0' * 32))
try:
    adapter.fetch_catalog(binding, explicit_action=True)
except CatalogError as exc:
    assert exc.failure.category == 'dependency_unavailable'
    assert exc.failure.detail_code == 'claude_api_extra_missing'
    assert exc.failure.dispatch_effect == 'not_sent'
else:
    raise AssertionError('missing provider dependencies must fail closed')
assert vault.opens == 0
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_transport_is_fixed_no_proxy_no_redirect_and_sdk_retry_is_zero(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "https://attacker.invalid:8443")
    calls = 0

    def responder(request, body):
        nonlocal calls
        calls += 1
        assert str(request.url).startswith(API_ORIGIN + "/v1/models")
        if calls == 1:
            return response(request, status=503, payload={"type": "error", "error": {"type": "overloaded_error"}})
        raise AssertionError("hidden retry or redirect followed")

    vault = InMemoryCredentialVault()
    binding = ClaudeBinding(vault.store("claude", SECRET))
    adapter = ClaudeAPIAdapter(vault=vault, transport=httpx2.MockTransport(Spy(responder)))
    assert adapter.policy.origin == API_ORIGIN
    assert adapter.policy.trust_env is False
    assert adapter.policy.follow_redirects is False
    assert adapter.policy.sdk_max_retries == 0
    with pytest.raises(CatalogError) as caught:
        adapter.fetch_catalog(binding, explicit_action=True)
    assert caught.value.failure.category == "provider_unavailable"
    assert calls == 1


def test_redirect_is_not_followed_and_secret_never_appears_in_public_failure_or_repr():
    calls = 0

    def responder(request, body):
        nonlocal calls
        calls += 1
        return response(request, status=307, headers={"location": "https://attacker.invalid/steal"})

    vault = InMemoryCredentialVault()
    ref = vault.store("claude", SECRET)
    binding = ClaudeBinding(ref)
    adapter = ClaudeAPIAdapter(vault=vault, transport=httpx2.MockTransport(Spy(responder)))
    with pytest.raises(CatalogError) as caught:
        adapter.fetch_catalog(binding, explicit_action=True)
    public = repr(caught.value) + str(caught.value) + repr(adapter) + repr(vault) + repr(ref)
    assert SECRET not in public
    assert "attacker.invalid" not in public
    assert calls == 1


def test_catalog_pagination_is_bounded_exact_and_null_capabilities_stay_unknown():
    first = model(MODEL_ID, capabilities=None)
    second = model(OTHER_MODEL_ID, capabilities={"vision": {"supported": True}})
    pages = [
        model_page([first], has_more=True),
        model_page([second], has_more=False),
    ]
    adapter, binding, spy, _ = configured(pages=pages)
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)

    assert [entry.id for entry in snapshot.models] == [MODEL_ID, OTHER_MODEL_ID]
    assert snapshot.models[0].capabilities is None
    assert snapshot.models[1].capabilities == {"vision": {"supported": True}}
    model_requests = [item for item in spy.requests if item[0].url.path == "/v1/models"]
    assert len(model_requests) == 2
    assert model_requests[1][0].url.params["after_id"] == MODEL_ID
    assert all(item[0].headers["x-api-key"] == SECRET for item in model_requests)
    assert all(item[0].headers["anthropic-workspace-id"] == "wrk_test" for item in model_requests)


@pytest.mark.parametrize(
    "field,reflected",
    [
        ("id", SECRET),
        ("display_name", SECRET),
        ("capabilities", {"note": hashlib.sha256(SECRET.encode()).hexdigest()}),
        (
            "capabilities",
            {"note": base64.b64encode(SECRET.encode()).decode("ascii")},
        ),
    ],
)
def test_catalog_rejects_raw_key_fragments_and_common_key_fingerprints(field, reflected):
    reflected_model = model()
    reflected_model[field] = reflected
    adapter, binding, _, _ = configured(pages=[model_page([reflected_model])])

    with pytest.raises(CatalogError) as caught:
        adapter.fetch_catalog(binding, explicit_action=True)

    assert caught.value.failure.detail_code == "catalog_secret_reflection"
    assert SECRET not in repr(caught.value)


@pytest.mark.parametrize(
    "pages,match",
    [
        ([{"data": [model()], "first_id": MODEL_ID, "last_id": MODEL_ID}], "has_more"),
        ([model_page([], has_more=True)], "non-empty"),
        ([model_page([model()], has_more=True, last_id="wrong")], "last_id"),
        (
            [model_page([model()], has_more=True), model_page([model()], has_more=False)],
            "duplicate",
        ),
    ],
)
def test_catalog_rejects_incomplete_cursor_and_duplicate_pages(pages, match):
    adapter, binding, _, _ = configured(pages=pages)
    with pytest.raises(CatalogError, match=match):
        adapter.fetch_catalog(binding, explicit_action=True)


def test_catalog_rejects_page_cycles_and_total_response_limit():
    endless = [model_page([model()], has_more=True)]
    adapter, binding, _, _ = configured(pages=endless)
    with pytest.raises(CatalogError, match="cursor"):
        adapter.fetch_catalog(binding, explicit_action=True)

    huge = model_page([model()])
    huge["padding"] = "x" * 5000
    adapter, binding, _, _ = configured(
        pages=[huge], limits=StreamLimits(max_catalog_page_bytes=1024)
    )
    with pytest.raises(CatalogError, match="catalog_page"):
        adapter.fetch_catalog(binding, explicit_action=True)


def test_catalog_response_decode_failure_is_not_reported_as_not_sent():
    def responder(request, body):
        return response(
            request,
            body=b"not-a-gzip-stream",
            headers={"content-type": "application/json", "content-encoding": "gzip"},
        )

    vault = InMemoryCredentialVault()
    binding = ClaudeBinding(vault.store("claude", SECRET))
    adapter = ClaudeAPIAdapter(vault=vault, transport=httpx2.MockTransport(Spy(responder)))

    with pytest.raises(CatalogError) as caught:
        adapter.fetch_catalog(binding, explicit_action=True)

    assert caught.value.failure.dispatch_effect == "response_observed"


def test_catalog_failure_does_not_retain_raw_provider_exception_chain():
    def responder(request, body):
        raise RuntimeError(SECRET)

    vault = InMemoryCredentialVault()
    binding = ClaudeBinding(vault.store("claude", SECRET))
    adapter = ClaudeAPIAdapter(vault=vault, transport=httpx2.MockTransport(Spy(responder)))
    with pytest.raises(CatalogError) as caught:
        adapter.fetch_catalog(binding, explicit_action=True)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert SECRET not in repr(caught.value)


def test_stale_binding_missing_model_and_unknown_capability_fail_before_message_dispatch():
    clock = {"now": 1_800_000_000_000}
    adapter, binding, spy, vault = configured(clock_ms=lambda: clock["now"])
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    before = len(spy.requests)

    other_binding = ClaudeBinding(vault.store("claude", "sk-ant-other-test"))
    with pytest.raises(ValueError, match="binding"):
        adapter.stream(turn(snapshot, other_binding), snapshot, other_binding, explicit_action=True)
    with pytest.raises(ValueError, match="catalog"):
        adapter.stream(
            turn(snapshot, binding),
            snapshot.with_catalog_id("forged"),
            binding,
        explicit_action=True)
    with pytest.raises(ValueError, match="model"):
        adapter.stream(turn(snapshot, binding, model_id="missing"), snapshot, binding, explicit_action=True)
    with pytest.raises(ValueError, match="max_tokens"):
        adapter.stream(replace(turn(snapshot, binding), max_tokens=40_000), snapshot, binding, explicit_action=True)
    with pytest.raises(ValueError, match="capability"):
        adapter.validate_selection(
            turn(snapshot, binding).selection,
            snapshot,
            binding,
            required_capabilities=("vision",),
        )
    clock["now"] = snapshot.fetched_at_ms + snapshot.max_age_ms + 1
    with pytest.raises(ValueError, match="stale"):
        adapter.validate_selection(turn(snapshot, binding).selection, snapshot, binding)
    assert len(spy.requests) == before


def test_image_with_unknown_capability_and_orphan_tool_result_are_rejected_before_transmission():
    adapter, binding, spy, _ = configured()
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    before = len(spy.requests)
    image_turn = turn(
        snapshot,
        binding,
        messages=(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": "AA=="},
                    }
                ],
            },
        ),
    )
    with pytest.raises(ValueError, match="capability"):
        adapter.stream(image_turn, snapshot, binding, explicit_action=True)

    orphan = turn(
        snapshot,
        binding,
        messages=(
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_orphan", "content": "x"}],
            },
        ),
    )
    with pytest.raises(ValueError, match="Orphan"):
        adapter.stream(orphan, snapshot, binding, explicit_action=True)
    assert len(spy.requests) == before


def test_nested_tool_result_modalities_cannot_bypass_catalog_capability_checks():
    adapter, binding, spy, _ = configured()
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    before = len(spy.requests)
    request = turn(
        snapshot,
        binding,
        tools=({"name": "lookup", "description": "read", "input_schema": {"type": "object"}},),
        messages=(
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "toolu_prior", "name": "lookup", "input": {}}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_prior",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": "AA==",
                                },
                            }
                        ],
                    }
                ],
            },
        ),
    )

    with pytest.raises(ValueError, match="capability"):
        adapter.stream(request, snapshot, binding, explicit_action=True)
    assert len(spy.requests) == before


def test_provider_managed_or_url_multimodal_sources_are_rejected_before_transmission():
    capabilities = {"image_input": {"supported": True}}
    adapter, binding, spy, _ = configured(
        pages=[model_page([model(capabilities=capabilities)])]
    )
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    before = len(spy.requests)
    request = turn(
        snapshot,
        binding,
        messages=(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "url", "url": "https://attacker.invalid/ref"},
                    }
                ],
            },
        ),
    )

    with pytest.raises(ValueError, match="source"):
        adapter.stream(request, snapshot, binding, explicit_action=True)
    assert len(spy.requests) == before


def test_invalid_multimodal_input_does_not_retain_secret_text_in_exception_context():
    capabilities = {"image_input": {"supported": True}}
    adapter, binding, spy, _ = configured(
        pages=[model_page([model(capabilities=capabilities)])]
    )
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    invalid_data = SECRET + "\ud800"
    request = turn(
        snapshot,
        binding,
        messages=(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": invalid_data,
                        },
                    }
                ],
            },
        ),
    )
    before = len(spy.requests)
    with pytest.raises(ValueError) as caught:
        adapter.stream(
            request,
            snapshot,
            binding,
            explicit_action=True,
        )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert SECRET not in repr(caught.value)
    assert len(spy.requests) == before


def test_invalid_request_tree_does_not_retain_private_values_in_exception_chain():
    class PrivateValue:
        def __repr__(self):
            return SECRET

    adapter, binding, spy, _ = configured()
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    request = turn(
        snapshot,
        binding,
        tools=(
            {
                "name": "lookup",
                "description": "read",
                "input_schema": {"type": "object", "private": PrivateValue()},
            },
        ),
    )
    before = len(spy.requests)
    with pytest.raises(ValueError) as caught:
        adapter.stream(
            request,
            snapshot,
            binding,
            explicit_action=True,
        )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert SECRET not in repr(caught.value)
    assert len(spy.requests) == before


def test_workspace_prompt_and_tool_payload_cannot_contain_key_material():
    vault = InMemoryCredentialVault()
    ref = vault.store("claude", SECRET)
    spy, transport = api_fixture()
    adapter = ClaudeAPIAdapter(vault=vault, transport=transport)
    with pytest.raises(CatalogError) as caught:
        adapter.fetch_catalog(ClaudeBinding(ref, SECRET), explicit_action=True)
    assert caught.value.failure.detail_code == "request_secret_reflection"
    assert not spy.requests

    binding = ClaudeBinding(ref, "wrk_safe")
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    before = len([request for request, _ in spy.requests if request.url.path == "/v1/messages"])
    reflected_tool_value = hashlib.sha256(SECRET.encode()).hexdigest()
    request = replace(
        turn(
            snapshot,
            binding,
            tools=({"name": "lookup", "description": "read", "input_schema": {"type": "object"}},),
            messages=({"role": "user", "content": reflected_tool_value},),
        ),
        system=f"Never expose {SECRET}",
    )
    events = list(adapter.stream(request, snapshot, binding, explicit_action=True))
    assert terminal(events).failure.detail_code == "request_secret_reflection"
    assert len([request for request, _ in spy.requests if request.url.path == "/v1/messages"]) == before
    assert SECRET not in repr(events)


def test_duplicate_historical_tool_ids_are_rejected_before_transmission():
    adapter, binding, spy, _ = configured()
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    before = len(spy.requests)
    request = turn(
        snapshot,
        binding,
        tools=({"name": "lookup", "description": "read", "input_schema": {"type": "object"}},),
        messages=(
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "toolu_repeat", "name": "lookup", "input": {}}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_repeat", "content": "one"}],
            },
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "toolu_repeat", "name": "lookup", "input": {}}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_repeat", "content": "two"}],
            },
        ),
    )

    with pytest.raises(ValueError, match="duplicated"):
        adapter.stream(request, snapshot, binding, explicit_action=True)
    assert len(spy.requests) == before


def test_effort_is_catalog_checked_per_agent_and_observed_effort_remains_unknown():
    capabilities = {
        "effort": {
            "supported": True,
            "low": {"supported": True},
            "medium": {"supported": True},
            "high": {"supported": True},
            "xhigh": {"supported": False},
            "max": {"supported": False},
        }
    }
    adapter, binding, spy, _ = configured(
        pages=[model_page([model(capabilities=capabilities)])],
        stream_body=complete_text_stream(),
    )
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    selected = replace(turn(snapshot, binding).selection, effort="high")
    request = replace(turn(snapshot, binding), selection=selected)
    events = list(adapter.stream(request, snapshot, binding, explicit_action=True))
    started = next(event for event in events if isinstance(event, ProviderStarted))
    assert started.requested_effort == "high"
    assert started.observed_effort is None
    body = json.loads(next(body for request, body in spy.requests if request.url.path == "/v1/messages"))
    assert body["output_config"] == {"effort": "high"}

    unsupported = replace(request, selection=replace(selected, effort="max"))
    before = len(spy.requests)
    with pytest.raises(ValueError, match="effort capability"):
        adapter.stream(unsupported, snapshot, binding, explicit_action=True)
    assert len(spy.requests) == before


def test_key_rotation_invalidates_binding_and_missing_old_key_dispatches_nothing():
    adapter, binding, spy, vault = configured()
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    before = len(spy.requests)
    replacement = vault.rotate(binding.credential_ref, "sk-ant-api03-rotated-test")
    replacement_binding = ClaudeBinding(replacement, binding.workspace_id)
    with pytest.raises(ValueError, match="binding"):
        adapter.stream(turn(snapshot, replacement_binding), snapshot, replacement_binding, explicit_action=True)
    with pytest.raises(CatalogError) as caught:
        adapter.stream(turn(snapshot, binding), snapshot, binding, explicit_action=True)
    assert caught.value.failure.category == "credential_missing"
    assert caught.value.failure.dispatch_effect == "not_sent"
    assert len(spy.requests) == before


@pytest.mark.parametrize(
    "error,category,detail",
    [
        (CredentialNeedsUnlock("locked"), "credential_needs_unlock", "needs_unlock"),
        (CredentialAccessDenied("denied"), "credential_blocked", "blocked"),
    ],
)
def test_keychain_recovery_states_are_preserved_without_dispatch(error, category, detail):
    class FailingVault:
        opens = 0

        def open(self, ref):
            self.opens += 1
            raise error

    vault = FailingVault()
    binding = ClaudeBinding(CredentialRef("claude", "0" * 32))
    adapter = ClaudeAPIAdapter(vault=vault, transport=httpx2.MockTransport(lambda request: None))
    with pytest.raises(CatalogError) as caught:
        adapter.fetch_catalog(binding, explicit_action=True)
    assert caught.value.failure.category == category
    assert caught.value.failure.detail_code == detail
    assert caught.value.failure.dispatch_effect == "not_sent"
    assert vault.opens == 1


def test_text_stream_has_ordered_started_delta_cumulative_usage_and_terminal():
    adapter, binding, spy, _ = configured(stream_body=complete_text_stream("안녕"))
    snapshot, events = fetch_and_stream(adapter, binding)
    assert [type(event) for event in events] == [
        ProviderStarted,
        TextDelta,
        UsageObserved,
        ProviderTerminal,
    ]
    assert events[0].requested_model == MODEL_ID
    assert events[0].observed_model == MODEL_ID
    assert events[1].text == "안녕"
    assert events[2].input_tokens == 7
    assert events[2].output_tokens == 5
    assert events[2].cache_creation_input_tokens == 2
    assert events[2].cache_read_input_tokens == 3
    assert terminal(events).state == "completed"
    assert terminal(events).usage_finality == "known"
    message_requests = [request for request, _ in spy.requests if request.url.path == "/v1/messages"]
    assert len(message_requests) == 1
    assert message_requests[0].headers["x-api-key"] == SECRET
    assert snapshot.binding_id == binding.binding_id


def test_provider_request_id_is_only_exposed_as_an_opaque_non_reflecting_handle():
    adapter, binding, _, _ = configured(
        stream_body=complete_text_stream(),
        message_headers={"request-id": SECRET},
    )
    snapshot, events = fetch_and_stream(adapter, binding)
    started = next(event for event in events if isinstance(event, ProviderStarted))
    # A provider-controlled header may contain the key. Hashing it would still
    # disclose a forbidden stable fingerprint, so the public adapter drops it.
    assert started.request_id is None
    assert SECRET not in repr(events)


def test_provider_message_identity_and_text_cannot_reflect_key_material():
    body = b"".join(
        sse_event(name, payload)
        for name, payload in [
            message_start(message_id=SECRET),
            message_delta(),
            ("message_stop", {"type": "message_stop"}),
        ]
    )
    adapter, binding, _, _ = configured(stream_body=body)
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    events = list(adapter.stream(turn(snapshot, binding), snapshot, binding, explicit_action=True))
    assert not any(isinstance(event, ProviderStarted) for event in events)
    assert terminal(events).failure.detail_code == "provider_secret_reflection"
    assert SECRET not in repr(events)

    split = [SECRET[:5], SECRET[5:14], SECRET[14:]]
    events_body = [
        message_start(),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
    ]
    events_body.extend(
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": piece},
            },
        )
        for piece in split
    )
    events_body.extend(
        [
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            message_delta(),
            ("message_stop", {"type": "message_stop"}),
        ]
    )
    adapter, binding, _, _ = configured(
        stream_body=b"".join(sse_event(name, payload) for name, payload in events_body)
    )
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    events = list(adapter.stream(turn(snapshot, binding), snapshot, binding, explicit_action=True))
    assert terminal(events).failure.detail_code == "provider_secret_reflection"
    assert SECRET not in "".join(event.text for event in events if isinstance(event, TextDelta))
    assert SECRET not in repr(events)


def test_forged_but_self_hashed_catalog_is_not_an_authoritative_models_observation():
    adapter, binding, spy, _ = configured()
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    forged_model = replace(snapshot.models[0], id="forged-model")
    forged = replace(snapshot, models=(forged_model,), catalog_id="")
    forged = replace(forged, catalog_id=adapter._catalog_digest(forged))
    selection = ModelSelection(binding.binding_id, forged.catalog_id, forged_model.id)
    request = replace(turn(snapshot, binding), selection=selection)
    before = len(spy.requests)
    with pytest.raises(ValueError, match="not issued"):
        adapter.stream(request, forged, binding, explicit_action=True)
    assert len(spy.requests) == before


def test_authentication_failure_invalidates_catalog_before_any_repeat_transmission():
    adapter, binding, spy, _ = configured(message_status=401)
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    request = turn(snapshot, binding)
    end = terminal(list(adapter.stream(request, snapshot, binding, explicit_action=True)))
    assert end.failure.category == "authentication"
    before = len(spy.requests)
    with pytest.raises(ValueError, match="not issued"):
        adapter.stream(request, snapshot, binding, explicit_action=True)
    assert len(spy.requests) == before


def test_authentication_invalidates_all_catalogs_sharing_the_credential():
    vault = InMemoryCredentialVault()
    ref = vault.store("claude", SECRET)
    first_binding = ClaudeBinding(ref, "wrk_first")
    second_binding = ClaudeBinding(ref, "wrk_second")
    spy, transport = api_fixture(message_status=401)
    ticks = iter(range(1_800_000_000_000, 1_800_000_000_100))
    adapter = ClaudeAPIAdapter(vault=vault, transport=transport, clock_ms=lambda: next(ticks))
    first = adapter.fetch_catalog(first_binding, explicit_action=True)
    second = adapter.fetch_catalog(second_binding, explicit_action=True)

    assert terminal(list(adapter.stream(turn(first, first_binding), first, first_binding, explicit_action=True))).failure.category == "authentication"
    message_count = len([request for request, _ in spy.requests if request.url.path == "/v1/messages"])
    try:
        list(adapter.stream(turn(second, second_binding), second, second_binding, explicit_action=True))
    except (CatalogError, ValueError):
        pass
    assert len([request for request, _ in spy.requests if request.url.path == "/v1/messages"]) == message_count


def test_permission_failure_invalidates_only_the_exact_workspace_binding():
    vault = InMemoryCredentialVault()
    ref = vault.store("claude", SECRET)
    denied_binding = ClaudeBinding(ref, "wrk_denied")
    allowed_binding = ClaudeBinding(ref, "wrk_allowed")
    denied_once = False

    def responder(request, body):
        nonlocal denied_once
        if request.url.path == "/v1/models":
            return response(request, payload=model_page([model()]))
        if request.headers.get("anthropic-workspace-id") == "wrk_denied" and not denied_once:
            denied_once = True
            return response(
                request,
                status=403,
                payload={"type": "error", "error": {"type": "permission_error"}},
            )
        return response(
            request,
            body=complete_text_stream(),
            headers={"content-type": "text/event-stream"},
        )

    spy = Spy(responder)
    adapter = ClaudeAPIAdapter(vault=vault, transport=httpx2.MockTransport(spy))
    denied = adapter.fetch_catalog(denied_binding, explicit_action=True)
    allowed = adapter.fetch_catalog(allowed_binding, explicit_action=True)
    assert terminal(
        list(adapter.stream(turn(denied, denied_binding), denied, denied_binding, explicit_action=True))
    ).failure.category == "permission"
    assert terminal(
        list(adapter.stream(turn(allowed, allowed_binding), allowed, allowed_binding, explicit_action=True))
    ).state == "completed"
    assert len([request for request, _ in spy.requests if request.url.path == "/v1/messages"]) == 2


def test_failed_auth_refresh_invalidates_prior_catalog_before_message_dispatch():
    vault = InMemoryCredentialVault()
    binding = ClaudeBinding(vault.store("claude", SECRET))
    catalog_calls = 0

    def responder(request, body):
        nonlocal catalog_calls
        if request.url.path == "/v1/models":
            catalog_calls += 1
            if catalog_calls == 1:
                return response(request, payload=model_page([model()]))
            return response(
                request,
                status=401,
                payload={"type": "error", "error": {"type": "authentication_error"}},
            )
        if request.url.path == "/v1/messages":
            return response(
                request,
                body=complete_text_stream(),
                headers={"content-type": "text/event-stream"},
            )
        raise AssertionError(request.url)

    spy = Spy(responder)
    adapter = ClaudeAPIAdapter(vault=vault, transport=httpx2.MockTransport(spy))
    prior = adapter.fetch_catalog(binding, explicit_action=True)
    with pytest.raises(CatalogError) as caught:
        adapter.fetch_catalog(binding, explicit_action=True)
    assert caught.value.failure.category == "authentication"
    before = len([request for request, _ in spy.requests if request.url.path == "/v1/messages"])
    try:
        list(adapter.stream(turn(prior, binding), prior, binding, explicit_action=True))
    except (CatalogError, ValueError):
        pass
    assert len([request for request, _ in spy.requests if request.url.path == "/v1/messages"]) == before


def test_lazy_stream_rechecks_catalog_authority_after_auth_invalidation():
    vault = InMemoryCredentialVault()
    binding = ClaudeBinding(vault.store("claude", SECRET))
    message_calls = 0

    def responder(request, body):
        nonlocal message_calls
        if request.url.path == "/v1/models":
            return response(request, payload=model_page([model()]))
        message_calls += 1
        if message_calls == 1:
            return response(
                request,
                status=401,
                payload={"type": "error", "error": {"type": "authentication_error"}},
            )
        return response(
            request,
            body=complete_text_stream(),
            headers={"content-type": "text/event-stream"},
        )

    adapter = ClaudeAPIAdapter(vault=vault, transport=httpx2.MockTransport(Spy(responder)))
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    delayed = adapter.stream(turn(snapshot, binding), snapshot, binding, explicit_action=True)
    assert terminal(list(adapter.stream(turn(snapshot, binding), snapshot, binding, explicit_action=True))).failure.category == "authentication"
    late_events = list(delayed)
    assert message_calls == 1
    assert terminal(late_events).failure.detail_code == "catalog_authority_changed"


def test_late_catalog_success_cannot_resurrect_after_newer_auth_failure():
    vault = InMemoryCredentialVault()
    binding = ClaudeBinding(vault.store("claude", SECRET))
    older_entered = threading.Event()
    release_older = threading.Event()
    request_count = 0
    request_lock = threading.Lock()

    def responder(request, body):
        nonlocal request_count
        with request_lock:
            request_count += 1
            current = request_count
        if current == 1:
            older_entered.set()
            assert release_older.wait(5)
            return response(request, payload=model_page([model()]))
        return response(
            request,
            status=401,
            payload={"type": "error", "error": {"type": "authentication_error"}},
        )

    adapter = ClaudeAPIAdapter(vault=vault, transport=httpx2.MockTransport(Spy(responder)))
    result: dict[str, object] = {}

    def fetch_older():
        try:
            result["snapshot"] = adapter.fetch_catalog(binding, explicit_action=True)
        except Exception as exc:  # assertion below checks the sanitized type
            result["error"] = exc

    thread = threading.Thread(target=fetch_older)
    thread.start()
    assert older_entered.wait(5)
    with pytest.raises(CatalogError) as newer:
        adapter.fetch_catalog(binding, explicit_action=True)
    assert newer.value.failure.category == "authentication"
    release_older.set()
    thread.join(5)
    assert not thread.is_alive()
    assert "snapshot" not in result
    assert isinstance(result.get("error"), CatalogError)


@pytest.mark.parametrize("older_status", [401, 503])
def test_late_catalog_failure_cannot_invalidate_a_newer_success(older_status):
    vault = InMemoryCredentialVault()
    binding = ClaudeBinding(vault.store("claude", SECRET))
    older_entered = threading.Event()
    release_older = threading.Event()
    request_count = 0
    request_lock = threading.Lock()

    def responder(request, body):
        nonlocal request_count
        if request.url.path == "/v1/messages":
            return response(
                request,
                body=complete_text_stream(),
                headers={"content-type": "text/event-stream"},
            )
        with request_lock:
            request_count += 1
            current = request_count
        if current == 1:
            older_entered.set()
            assert release_older.wait(5)
            return response(
                request,
                status=older_status,
                payload={"type": "error", "error": {"type": "test_error"}},
            )
        return response(request, payload=model_page([model()]))

    spy = Spy(responder)
    adapter = ClaudeAPIAdapter(vault=vault, transport=httpx2.MockTransport(spy))
    result: dict[str, object] = {}

    def fetch_older():
        try:
            result["snapshot"] = adapter.fetch_catalog(binding, explicit_action=True)
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=fetch_older)
    thread.start()
    assert older_entered.wait(5)
    current = adapter.fetch_catalog(binding, explicit_action=True)
    release_older.set()
    thread.join(5)

    assert not thread.is_alive()
    assert "snapshot" not in result
    assert isinstance(result.get("error"), CatalogError)
    assert result["error"].failure.category == "catalog_stale"
    assert adapter.connection_state(binding) == "catalog_current"
    assert terminal(
        list(
            adapter.stream(
                turn(current, binding),
                current,
                binding,
                explicit_action=True,
            )
        )
    ).state == "completed"


@pytest.mark.parametrize(
    "error_type,category",
    [("authentication_error", "authentication"), ("permission_error", "permission")],
)
def test_late_stream_auth_event_cannot_invalidate_a_newer_catalog_success(
    error_type,
    category,
):
    vault = InMemoryCredentialVault()
    binding = ClaudeBinding(vault.store("claude", SECRET), "wrk_ordered")
    stream_entered = threading.Event()
    release_stream = threading.Event()
    message_count = 0

    class DelayedErrorStream(httpx2.SyncByteStream):
        def __iter__(self):
            name, payload = message_start()
            yield sse_event(name, payload)
            stream_entered.set()
            assert release_stream.wait(5)
            yield sse_event(
                "error",
                {"type": "error", "error": {"type": error_type}},
            )

    def responder(request, body):
        nonlocal message_count
        if request.url.path == "/v1/models":
            return response(request, payload=model_page([model()]))
        message_count += 1
        if message_count == 1:
            return httpx2.Response(
                200,
                stream=DelayedErrorStream(),
                headers={"content-type": "text/event-stream"},
                request=request,
            )
        return response(
            request,
            body=complete_text_stream(),
            headers={"content-type": "text/event-stream"},
        )

    adapter = ClaudeAPIAdapter(
        vault=vault,
        transport=httpx2.MockTransport(Spy(responder)),
    )
    older = adapter.fetch_catalog(binding, explicit_action=True)
    result: dict[str, object] = {}

    def stream_older():
        result["events"] = list(
            adapter.stream(
                turn(older, binding),
                older,
                binding,
                explicit_action=True,
            )
        )

    thread = threading.Thread(target=stream_older)
    thread.start()
    assert stream_entered.wait(5)
    current = adapter.fetch_catalog(binding, explicit_action=True)
    release_stream.set()
    thread.join(5)

    assert not thread.is_alive()
    assert terminal(result["events"]).failure.category == category
    assert adapter.connection_state(binding) == "catalog_current"
    assert terminal(
        list(
            adapter.stream(
                turn(current, binding),
                current,
                binding,
                explicit_action=True,
            )
        )
    ).state == "completed"


def test_catalog_validation_clock_is_adapter_owned():
    assert "now_ms" not in inspect.signature(ClaudeAPIAdapter.validate_selection).parameters


def tool_stream(partials, *, tool_id="toolu_1", tool_name="lookup", reason="tool_use"):
    events = [
        message_start(),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": tool_id, "name": tool_name, "input": {}},
            },
        ),
    ]
    events.extend(
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": piece},
            },
        )
        for piece in partials
    )
    events.extend(
        [
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            message_delta(reason),
            ("message_stop", {"type": "message_stop"}),
        ]
    )
    return b"".join(sse_event(name, payload) for name, payload in events)


def test_tool_request_is_emitted_only_after_complete_strict_json_and_never_dispatched_here():
    adapter, binding, _, _ = configured(stream_body=tool_stream(['{"q":', '"value"}']))
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    request = turn(
        snapshot,
        binding,
        tools=({"name": "lookup", "description": "read", "input_schema": {"type": "object"}},),
    )
    iterator = adapter.stream(request, snapshot, binding, explicit_action=True)
    first = next(iterator)
    assert isinstance(first, ProviderStarted)
    second = next(iterator)
    assert isinstance(second, ToolRequested)
    assert second.tool_use_id == "toolu_1"
    assert second.name == "lookup"
    assert second.input == {"q": "value"}
    mutated = second.input
    mutated["q"] = "../../changed-after-validation"
    assert second.input == {"q": "value"}
    assert "value" not in repr(second)
    rest = list(iterator)
    assert isinstance(rest[0], UsageObserved)
    assert terminal(rest).state == "tool_required"


def test_provider_tool_identity_cannot_reflect_key_fingerprints():
    reflected = hashlib.sha256(SECRET.encode()).hexdigest()
    adapter, binding, _, _ = configured(
        stream_body=tool_stream(["{}"], tool_id=reflected)
    )
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    request = turn(
        snapshot,
        binding,
        tools=({"name": "lookup", "description": "read", "input_schema": {"type": "object"}},),
    )
    events = list(adapter.stream(request, snapshot, binding, explicit_action=True))
    assert not any(isinstance(event, ToolRequested) for event in events)
    assert terminal(events).failure.detail_code == "provider_secret_reflection"
    assert SECRET not in repr(events)


def test_provider_tool_arguments_cannot_reflect_key_material_across_deltas():
    pieces = ['{"token":"', SECRET[:11], SECRET[11:], '"}']
    adapter, binding, _, _ = configured(stream_body=tool_stream(pieces))
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    request = turn(
        snapshot,
        binding,
        tools=({"name": "lookup", "description": "read", "input_schema": {"type": "object"}},),
    )
    events = list(adapter.stream(request, snapshot, binding, explicit_action=True))
    assert not any(isinstance(event, ToolRequested) for event in events)
    assert terminal(events).failure.detail_code == "provider_secret_reflection"
    assert SECRET not in repr(events)


@pytest.mark.parametrize(
    "body,tools,reason",
    [
        (tool_stream(['{"x":1,"x":2}']), ({"name": "lookup", "description": "d", "input_schema": {}},), "duplicate JSON"),
        (tool_stream(['{"x":NaN}']), ({"name": "lookup", "description": "d", "input_schema": {}},), "nonfinite JSON"),
        (tool_stream(['{"x":']), ({"name": "lookup", "description": "d", "input_schema": {}},), "tool JSON"),
        (tool_stream(['{}'], tool_name="undeclared"), ({"name": "lookup", "description": "d", "input_schema": {}},), "undeclared"),
    ],
)
def test_malformed_or_undeclared_tool_never_becomes_a_tool_request(body, tools, reason):
    adapter, binding, _, _ = configured(stream_body=body)
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    events = list(adapter.stream(turn(snapshot, binding, tools=tools), snapshot, binding, explicit_action=True))
    assert not any(isinstance(event, ToolRequested) for event in events)
    assert terminal(events).state == "failed"
    assert terminal(events).failure.category == "protocol_error"
    assert reason.lower().replace(" ", "_") in terminal(events).failure.detail_code.lower()


def test_server_tool_block_and_actual_model_fallback_fail_closed():
    server_events = [
        message_start(),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {}},
            },
        ),
    ]
    body = b"".join(sse_event(name, payload) for name, payload in server_events)
    adapter, binding, _, _ = configured(stream_body=body)
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    events = list(adapter.stream(turn(snapshot, binding), snapshot, binding, explicit_action=True))
    assert terminal(events).state == "failed"
    assert terminal(events).failure.detail_code == "server_tool_not_allowed"

    adapter, binding, _, _ = configured(stream_body=complete_text_stream(model_id=OTHER_MODEL_ID))
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    events = list(adapter.stream(turn(snapshot, binding), snapshot, binding, explicit_action=True))
    assert terminal(events).failure.detail_code == "observed_model_mismatch"


def test_decreasing_cumulative_usage_is_not_accepted_as_known_or_completed():
    events = [
        message_start(output_tokens=100),
        (
            "content_block_start",
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        message_delta("end_turn", output_tokens=1),
        ("message_stop", {"type": "message_stop"}),
    ]
    body = b"".join(sse_event(name, payload) for name, payload in events)
    adapter, binding, _, _ = configured(stream_body=body)
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    observed = list(adapter.stream(turn(snapshot, binding), snapshot, binding, explicit_action=True))
    assert not any(isinstance(event, UsageObserved) for event in observed)
    assert terminal(observed).state == "failed"
    assert terminal(observed).usage_finality == "unknown"
    assert terminal(observed).failure.detail_code == "usage_decreased"


@pytest.mark.parametrize(
    "body,limits,detail",
    [
        (complete_text_stream()[:-3], StreamLimits(), "incomplete_sse"),
        (b"event: message_start\ndata: \xff\n\n", StreamLimits(), "invalid_utf8"),
        (complete_text_stream("x" * 300), StreamLimits(max_text_bytes=32), "text_limit"),
        (complete_text_stream(), StreamLimits(max_total_stream_bytes=32), "stream_limit"),
        (sse_event("future_execution_authority", {"type": "future_execution_authority"}), StreamLimits(), "unknown_event"),
    ],
)
def test_eof_utf8_unknown_and_byte_limits_surface_unknown_terminal(body, limits, detail):
    adapter, binding, _, _ = configured(stream_body=body, limits=limits)
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    events = list(adapter.stream(turn(snapshot, binding), snapshot, binding, explicit_action=True))
    end = terminal(events)
    assert end.state == "failed"
    assert end.usage_finality == "unknown"
    assert end.failure.detail_code == detail
    assert end.failure.retry == "never"


@pytest.mark.parametrize(
    "reason,state,finality",
    [
        ("end_turn", "completed", "known"),
        ("stop_sequence", "completed", "known"),
        ("tool_use", "tool_required", "known"),
        ("max_tokens", "incomplete", "known"),
        ("model_context_window_exceeded", "incomplete", "known"),
        ("refusal", "refused", "known"),
        ("pause_turn", "failed", "known"),
    ],
)
def test_stop_reasons_are_not_misreported_as_work_success(reason, state, finality):
    if reason == "tool_use":
        body = tool_stream(["{}"])
        tools = ({"name": "lookup", "description": "d", "input_schema": {}},)
    else:
        body = complete_text_stream(reason=reason)
        tools = ()
    adapter, binding, _, _ = configured(stream_body=body)
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    events = list(adapter.stream(turn(snapshot, binding, tools=tools), snapshot, binding, explicit_action=True))
    assert terminal(events).state == state
    assert terminal(events).usage_finality == finality
    if reason == "pause_turn":
        assert terminal(events).failure.detail_code == "server_continuation_not_allowed"


def test_stream_error_event_is_sanitized_and_no_hidden_retry_occurs():
    stream = sse_event("error", {"type": "error", "error": {"type": "overloaded_error", "message": SECRET}})
    adapter, binding, spy, _ = configured(stream_body=stream)
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    events = list(adapter.stream(turn(snapshot, binding), snapshot, binding, explicit_action=True))
    end = terminal(events)
    assert end.state == "failed"
    assert end.failure.category == "provider_unavailable"
    assert end.failure.retry == "controlled"
    assert SECRET not in repr(end)
    assert len([item for item in spy.requests if item[0].url.path == "/v1/messages"]) == 1


@pytest.mark.parametrize(
    "error_type,category,retry",
    [
        ("authentication_error", "authentication", "never"),
        ("permission_error", "permission", "never"),
        ("rate_limit_error", "rate_limit", "after_delay"),
        ("spend_limit_exceeded", "spend_cap", "never"),
        ("unknown_future_error", "stream_error", "never"),
    ],
)
def test_stream_error_type_is_classified_without_reflecting_provider_body(error_type, category, retry):
    body = sse_event("error", {"type": "error", "error": {"type": error_type, "message": SECRET}})
    adapter, binding, _, _ = configured(stream_body=body, message_headers={"retry-after": "3"})
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    end = terminal(list(adapter.stream(turn(snapshot, binding), snapshot, binding, explicit_action=True)))
    assert end.failure.category == category
    assert end.failure.retry == retry
    assert SECRET not in repr(end)


@pytest.mark.parametrize(
    "status,payload,headers,category,retry",
    [
        (401, {"type": "error", "error": {"type": "authentication_error"}}, {}, "authentication", "never"),
        (403, {"type": "error", "error": {"type": "permission_error"}}, {}, "permission", "never"),
        (429, {"type": "error", "error": {"type": "rate_limit_error"}}, {"retry-after": "2"}, "rate_limit", "after_delay"),
        (429, {"type": "error", "error": {"type": "spend_limit_exceeded"}}, {}, "spend_cap", "never"),
        (503, {"type": "error", "error": {"type": "overloaded_error"}}, {}, "provider_unavailable", "controlled"),
    ],
)
def test_http_failures_have_caller_owned_retry_classification(status, payload, headers, category, retry):
    calls = 0

    def responder(request, body):
        nonlocal calls
        calls += 1
        return response(request, status=status, payload=payload, headers=headers)

    vault = InMemoryCredentialVault()
    binding = ClaudeBinding(vault.store("claude", SECRET))
    adapter = ClaudeAPIAdapter(vault=vault, transport=httpx2.MockTransport(Spy(responder)))
    with pytest.raises(CatalogError) as caught:
        adapter.fetch_catalog(binding, explicit_action=True)
    assert caught.value.failure.category == category
    assert caught.value.failure.retry == retry
    assert calls == 1


def test_transport_exception_is_sanitized_and_dispatch_effect_is_unknown():
    calls = 0

    def responder(request):
        nonlocal calls
        calls += 1
        raise httpx2.ReadTimeout(f"timeout with {SECRET}", request=request)

    vault = InMemoryCredentialVault()
    binding = ClaudeBinding(vault.store("claude", SECRET))
    adapter = ClaudeAPIAdapter(vault=vault, transport=httpx2.MockTransport(responder))
    with pytest.raises(CatalogError) as caught:
        adapter.fetch_catalog(binding, explicit_action=True)
    assert caught.value.failure.category == "transport_unknown"
    assert caught.value.failure.dispatch_effect == "unknown"
    assert SECRET not in repr(caught.value)
    assert calls == 1


def test_cancellation_before_dispatch_makes_no_request_and_midstream_is_unknown():
    adapter, binding, spy, _ = configured()
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    before = len(spy.requests)
    events = list(adapter.stream(turn(snapshot, binding), snapshot, binding, cancelled=lambda: True, explicit_action=True))
    assert len(spy.requests) == before
    assert terminal(events).state == "cancelled"
    assert terminal(events).failure.dispatch_effect == "not_sent"

    checks = 0

    def cancel_after_start():
        nonlocal checks
        checks += 1
        return checks >= 4

    events = list(adapter.stream(turn(snapshot, binding), snapshot, binding, cancelled=cancel_after_start, explicit_action=True))
    assert terminal(events).state == "cancel_requested"
    assert terminal(events).usage_finality == "unknown"
    assert terminal(events).failure.dispatch_effect == "unknown"


@pytest.mark.parametrize("close_gate", ["cancel", "deadline"])
def test_cancel_or_deadline_closed_during_credential_preflight_prevents_dispatch(close_gate):
    control = {"armed": False, "cancelled": False, "monotonic": 0}

    class ClosingVault(InMemoryCredentialVault):
        @contextmanager
        def open(self, ref):
            with super().open(ref) as material:
                if control["armed"]:
                    if close_gate == "cancel":
                        control["cancelled"] = True
                    else:
                        control["monotonic"] = 2
                yield material

    vault = ClosingVault()
    binding = ClaudeBinding(vault.store("claude", SECRET))
    spy, transport = api_fixture()
    adapter = ClaudeAPIAdapter(
        vault=vault,
        transport=transport,
        monotonic_ms=lambda: control["monotonic"],
        limits=StreamLimits(max_stream_duration_ms=1),
    )
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    control["armed"] = True
    before = len([request for request, _ in spy.requests if request.url.path == "/v1/messages"])
    events = list(
        adapter.stream(
            turn(snapshot, binding),
            snapshot,
            binding,
            cancelled=lambda: control["cancelled"],
        explicit_action=True)
    )

    assert len([request for request, _ in spy.requests if request.url.path == "/v1/messages"]) == before
    if close_gate == "cancel":
        assert terminal(events).state == "cancelled"
    else:
        assert terminal(events).failure.detail_code == "absolute_deadline_exceeded"
        assert terminal(events).failure.dispatch_effect == "not_sent"


class CloseFailTransport(httpx2.BaseTransport):
    def __init__(self, handler):
        self.handler = handler
        self.fail_close = False

    def handle_request(self, request):
        return self.handler(request)

    def close(self):
        if self.fail_close:
            raise RuntimeError("injected close failure")


def test_cancel_and_context_close_failure_still_emit_exactly_one_terminal():
    spy, ordinary = api_fixture()
    transport = CloseFailTransport(ordinary.handle_request)
    vault = InMemoryCredentialVault()
    binding = ClaudeBinding(vault.store("claude", SECRET))
    adapter = ClaudeAPIAdapter(vault=vault, transport=transport, clock_ms=lambda: 1_800_000_000_000)
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    transport.fail_close = True
    checks = 0

    def cancel_after_start():
        nonlocal checks
        checks += 1
        return checks >= 4

    events = list(adapter.stream(turn(snapshot, binding), snapshot, binding, cancelled=cancel_after_start, explicit_action=True))
    terminals = [event for event in events if isinstance(event, ProviderTerminal)]
    assert len(terminals) == 1
    assert terminals[0].state == "cancel_requested"
    assert terminals[0].failure.detail_code == "cancel_cleanup_failed"


@pytest.mark.parametrize("timeout", [True, float("nan"), float("inf"), -1.0])
def test_timeout_must_be_finite_positive_number(timeout):
    vault = InMemoryCredentialVault()
    with pytest.raises(ValueError, match="timeout"):
        ClaudeAPIAdapter(vault=vault, timeout_seconds=timeout)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_catalog_pages": 101},
        {"max_catalog_models": 100_001},
        {"max_catalog_page_bytes": 16 * 1024 * 1024 + 1},
        {"max_total_stream_bytes": 64 * 1024 * 1024 + 1},
        {"max_event_bytes": 4 * 1024 * 1024 + 1},
        {"max_events": 100_001},
        {"max_blocks": 1025},
        {"max_text_bytes": 32 * 1024 * 1024 + 1},
        {"max_tool_json_bytes": 4 * 1024 * 1024 + 1},
        {"max_request_bytes": 32 * 1024 * 1024 + 1},
        {"max_catalog_duration_ms": 10 * 60 * 1000 + 1},
        {"max_stream_duration_ms": 180 * 1000 + 1},
    ],
)
def test_stream_limits_have_non_configurable_release_ceilings(kwargs):
    with pytest.raises(ValueError, match="release ceiling"):
        StreamLimits(**kwargs)


def test_transport_timeout_and_catalog_age_have_release_ceilings():
    vault = InMemoryCredentialVault()
    with pytest.raises(ValueError, match="timeout_seconds"):
        ClaudeAPIAdapter(vault=vault, timeout_seconds=181)
    with pytest.raises(ValueError, match="catalog_max_age_ms"):
        ClaudeAPIAdapter(vault=vault, catalog_max_age_ms=24 * 60 * 60 * 1000 + 1)


def test_absolute_stream_deadline_stops_slow_drip_even_without_socket_inactivity_timeout():
    tick = 0

    def monotonic_ms():
        nonlocal tick
        tick += 10
        return tick

    adapter, binding, _, vault = configured(
        stream_body=complete_text_stream(),
        limits=StreamLimits(max_stream_duration_ms=1),
    )
    # Rebuild with the same fake transport and a deliberately advancing monotonic clock.
    spy, transport = api_fixture(stream_body=complete_text_stream())
    adapter = ClaudeAPIAdapter(
        vault=vault,
        transport=transport,
        clock_ms=lambda: 1_800_000_000_000,
        monotonic_ms=monotonic_ms,
        limits=StreamLimits(max_stream_duration_ms=1),
    )
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    observed = list(adapter.stream(turn(snapshot, binding), snapshot, binding, explicit_action=True))
    assert terminal(observed).state == "failed"
    assert terminal(observed).failure.category == "deadline"
    assert terminal(observed).failure.detail_code == "absolute_deadline_exceeded"
    assert terminal(observed).usage_finality == "unknown"


def test_agent_requests_do_not_share_models_tools_or_history():
    captured = []

    def run(model_id, tool_name, text):
        def responder(request, body):
            if request.url.path == "/v1/models":
                return response(request, payload=model_page([model(model_id)]))
            captured.append(json.loads(body))
            return response(
                request,
                body=complete_text_stream(model_id=model_id),
                headers={"content-type": "text/event-stream"},
            )

        vault = InMemoryCredentialVault()
        binding = ClaudeBinding(vault.store("claude", SECRET))
        adapter = ClaudeAPIAdapter(vault=vault, transport=httpx2.MockTransport(Spy(responder)))
        snapshot = adapter.fetch_catalog(binding, explicit_action=True)
        request = turn(
            snapshot,
            binding,
            model_id=model_id,
            tools=({"name": tool_name, "description": "d", "input_schema": {}},),
            messages=({"role": "user", "content": text},),
        )
        assert terminal(list(adapter.stream(request, snapshot, binding, explicit_action=True))).state == "completed"

    threads = [
        threading.Thread(target=run, args=(MODEL_ID, "tool_a", "history-a")),
        threading.Thread(target=run, args=(OTHER_MODEL_ID, "tool_b", "history-b")),
    ]
    for item in threads:
        item.start()
    for item in threads:
        item.join()

    by_model = {item["model"]: item for item in captured}
    assert by_model[MODEL_ID]["messages"][0]["content"] == "history-a"
    assert by_model[MODEL_ID]["tools"][0]["name"] == "tool_a"
    assert by_model[OTHER_MODEL_ID]["messages"][0]["content"] == "history-b"
    assert by_model[OTHER_MODEL_ID]["tools"][0]["name"] == "tool_b"


class FakeSecurity:
    kSecClass = "class"
    kSecClassGenericPassword = "generic"
    kSecAttrService = "service"
    kSecAttrAccount = "account"
    kSecValueData = "value"
    kSecReturnData = "return_data"
    kSecMatchLimit = "limit"
    kSecMatchLimitOne = "one"
    kSecAttrSynchronizable = "sync"
    kSecAttrAccessible = "accessible"
    kSecAttrAccessibleWhenUnlockedThisDeviceOnly = "device_only"
    kSecUseDataProtectionKeychain = "data_protection"
    kSecAttrAccessGroup = "access_group"
    errSecSuccess = 0
    errSecItemNotFound = -25300
    errSecDuplicateItem = -25299
    errSecInteractionNotAllowed = -25308
    errSecAuthFailed = -25293
    errSecMissingEntitlement = -34018

    def __init__(self):
        self.items = {}
        self.queries = []

    def SecItemAdd(self, query, result):
        self.queries.append(dict(query))
        key = (query[self.kSecAttrService], query[self.kSecAttrAccount])
        if key in self.items:
            return self.errSecDuplicateItem, None
        self.items[key] = bytes(query[self.kSecValueData])
        return self.errSecSuccess, None

    def SecItemCopyMatching(self, query, result):
        self.queries.append(dict(query))
        key = (query[self.kSecAttrService], query[self.kSecAttrAccount])
        if key not in self.items:
            return self.errSecItemNotFound, None
        return self.errSecSuccess, self.items[key]

    def SecItemUpdate(self, query, attrs):
        self.queries.append(dict(query))
        key = (query[self.kSecAttrService], query[self.kSecAttrAccount])
        if key not in self.items:
            return self.errSecItemNotFound
        self.items[key] = bytes(attrs[self.kSecValueData])
        return self.errSecSuccess

    def SecItemDelete(self, query):
        self.queries.append(dict(query))
        key = (query[self.kSecAttrService], query[self.kSecAttrAccount])
        if key not in self.items:
            return self.errSecItemNotFound
        del self.items[key]
        return self.errSecSuccess


def test_macos_keychain_backend_uses_owned_service_and_returns_only_opaque_ref():
    security = FakeSecurity()
    vault = MacOSKeychainVault(security=security, access_group="TESTTEAM.app.deeptwin.host")
    ref = vault.store("claude", SECRET)
    assert SECRET not in repr(ref) + repr(vault)
    assert len(security.items) == 1
    (service, account), raw = next(iter(security.items.items()))
    assert service == "app.deeptwin.provider-key.v1"
    assert account == f"claude:{ref.identifier}"
    assert raw == SECRET.encode()
    assert security.queries[0][security.kSecUseDataProtectionKeychain] is True
    assert security.queries[0][security.kSecAttrAccessGroup] == "TESTTEAM.app.deeptwin.host"

    with vault.open(ref) as material:
        assert material.reveal_text() == SECRET
        assert repr(material) == "<SecretMaterial redacted>"
    assert material.destroyed is True

    replaced = vault.rotate(ref, "sk-ant-api03-replaced")
    assert replaced != ref
    with pytest.raises(CredentialNotFound):
        with vault.open(ref):
            pass
    with vault.open(replaced) as material:
        assert material.reveal_text() == "sk-ant-api03-replaced"
    vault.delete(replaced)
    with pytest.raises(CredentialNotFound):
        with vault.open(replaced):
            pass

    other_ref = vault.store("codex", "codex-test-secret")
    forged = CredentialRef("claude", other_ref.identifier)
    with pytest.raises(CredentialNotFound):
        with vault.open(forged):
            pass


def test_macos_keychain_requires_host_access_group_and_maps_locked_or_denied_state():
    security = FakeSecurity()
    with pytest.raises(ValueError, match="access group"):
        MacOSKeychainVault(security=security, access_group="")

    vault = MacOSKeychainVault(security=security, access_group="TESTTEAM.app.deeptwin.host")
    ref = vault.store("claude", SECRET)

    original_copy = security.SecItemCopyMatching

    def locked(query, result):
        return security.errSecInteractionNotAllowed, None

    security.SecItemCopyMatching = locked
    with pytest.raises(Exception) as caught:
        with vault.open(ref):
            pass
    assert getattr(caught.value, "state", None) == "needs_unlock"

    def denied(query, result):
        return security.errSecMissingEntitlement, None

    security.SecItemCopyMatching = denied
    with pytest.raises(Exception) as caught:
        with vault.open(ref):
            pass
    assert getattr(caught.value, "state", None) == "blocked"
    security.SecItemCopyMatching = original_copy


def test_keychain_implementation_never_passes_secrets_through_argv_or_environment():
    source = inspect.getsource(__import__("app.adapters.keychain", fromlist=["*"]))
    assert "subprocess" not in source
    assert "os.environ" not in source
    assert "popen(" not in source.lower()
    assert "run([" not in source.lower()


def test_invalid_secret_encoding_does_not_survive_in_public_exception_chains():
    raw_secret = b"sk-ant-api03-chain-canary-\xff-tail"
    material = SecretMaterial(raw_secret)
    with pytest.raises(CredentialError) as caught:
        material.reveal_text()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "chain-canary" not in repr(caught.value)


def test_keychain_framework_exceptions_are_sanitized_without_raw_context():
    security = FakeSecurity()

    def fail_add(query, result):
        raise RuntimeError(SECRET)

    security.SecItemAdd = fail_add
    vault = MacOSKeychainVault(security=security, access_group="TESTTEAM.app.deeptwin.host")
    with pytest.raises(CredentialError) as caught:
        vault.store("claude", SECRET)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert SECRET not in repr(caught.value)
    assert SECRET not in traceback_locals_repr(caught.value)

    invalid_text = "sk-ant-api03-chain-canary-\ud800-tail"
    vault = InMemoryCredentialVault()
    with pytest.raises(ValueError) as caught:
        vault.store("claude", invalid_text)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "chain-canary" not in repr(caught.value)


def test_keychain_error_results_do_not_leave_returned_secret_bytes_in_traceback_frames():
    security = FakeSecurity()
    vault = MacOSKeychainVault(security=security, access_group="TESTTEAM.app.deeptwin.host")
    ref = vault.store("claude", SECRET)

    def poisoned_denial(query, result):
        return security.errSecAuthFailed, SECRET.encode()

    security.SecItemCopyMatching = poisoned_denial
    with pytest.raises(CredentialAccessDenied) as caught:
        with vault.open(ref):
            pass
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert SECRET not in repr(caught.value)
    assert SECRET not in traceback_locals_repr(caught.value)


def thinking_then_text_stream(text="answer", *, thinking="", signature="sig-opaque"):
    events = [
        message_start(),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "thinking_delta", "thinking": thinking}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "signature_delta", "signature": signature}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("content_block_start", {"type": "content_block_start", "index": 1,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1,
                                 "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        message_delta("end_turn"),
        ("message_stop", {"type": "message_stop"}),
    ]
    return b"".join(sse_event(name, payload) for name, payload in events)


def test_a_default_thinking_block_in_a_toolless_turn_is_consumed_and_never_surfaced():
    adapter, binding, _, _ = configured(stream_body=thinking_then_text_stream("answer", thinking="private reasoning"))
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    events = list(adapter.stream(turn(snapshot, binding), snapshot, binding, explicit_action=True))
    assert terminal(events).state == "completed"
    texts = [event for event in events if isinstance(event, TextDelta)]
    assert [(event.index, event.text) for event in texts] == [(1, "answer")]
    assert "private reasoning" not in repr(events) and "sig-opaque" not in repr(events)


def test_a_thinking_block_in_a_tool_turn_stays_unsupported():
    adapter, binding, _, _ = configured(stream_body=thinking_then_text_stream())
    snapshot = adapter.fetch_catalog(binding, explicit_action=True)
    tools = ({"name": "lookup", "description": "read", "input_schema": {"type": "object"}},)
    events = list(adapter.stream(turn(snapshot, binding, tools=tools), snapshot, binding, explicit_action=True))
    assert terminal(events).state == "failed"
    assert terminal(events).failure.detail_code == "unsupported_content_block"
