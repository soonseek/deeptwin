"""Offline contracts for the explicitly selected Codex API billing mode."""

from dataclasses import replace
import hashlib
import inspect
import json
import threading

import httpx
import pytest

from app.adapters.codex_api import (
    API_ORIGIN,
    CodexAPIAdapter,
    CodexAPIBinding,
    CodexAPIError,
    CodexAPISelection,
)
from app.adapters.keychain import CredentialRef, InMemoryCredentialVault


MODEL = {
    "id": "gpt-6-astra",
    "object": "model",
    "created": 1_788_000_000,
    "owned_by": "openai",
}


def binding(ref, *, project="proj_deeptwin"):
    return CodexAPIBinding(credential_ref=ref, project_id=project)


def response(payload=None, *, status=200, headers=None):
    body = {"object": "list", "data": [MODEL]} if payload is None else payload
    return httpx.Response(
        status,
        headers={"content-type": "application/json", **(headers or {})},
        content=json.dumps(body).encode("utf-8"),
    )


class TrackingVault(InMemoryCredentialVault):
    def __init__(self):
        super().__init__()
        self.opens = 0

    def open(self, ref):
        self.opens += 1
        return super().open(ref)


def subject(handler, *, clock=None, vault=None, **kwargs):
    vault = vault or InMemoryCredentialVault()
    ref = vault.store("codex_api", "sk-test-codex-api-only")
    adapter = CodexAPIAdapter(
        vault=vault,
        transport=httpx.MockTransport(handler),
        clock_ms=clock or (lambda: 10_000),
        monotonic_ms=clock or (lambda: 10_000),
        **kwargs,
    )
    return adapter, vault, binding(ref)


def test_catalog_requires_an_explicit_api_action_before_key_or_http_access():
    vault = TrackingVault()
    calls = []
    adapter, _, api_binding = subject(
        lambda request: calls.append(request) or response(), vault=vault
    )
    with pytest.raises(ValueError, match="explicit"):
        adapter.fetch_catalog(api_binding, explicit_action=False)
    assert vault.opens == 0
    assert calls == []
    snapshot = adapter.fetch_catalog(api_binding, explicit_action=True)
    selection = CodexAPISelection(
        api_binding.binding_id, snapshot.catalog_id, MODEL["id"]
    )
    vault.opens = 0
    calls.clear()
    with pytest.raises(ValueError, match="explicit"):
        adapter.validate_selection(
            selection, snapshot, api_binding, explicit_action=False
        )
    assert vault.opens == 0
    assert calls == []


def test_fixed_api_origin_keychain_key_and_no_subscription_mutation():
    seen = []

    def handler(request):
        seen.append(request)
        return response()

    adapter, _, api_binding = subject(handler)
    snapshot = adapter.fetch_catalog(api_binding, explicit_action=True)
    assert len(seen) == 1
    request = seen[0]
    assert str(request.url) == f"{API_ORIGIN}/v1/models"
    assert request.headers["authorization"] == "Bearer sk-test-codex-api-only"
    assert request.headers["openai-project"] == "proj_deeptwin"
    assert adapter.transport_policy.mode == "api"
    assert adapter.transport_policy.trust_env is False
    assert adapter.transport_policy.follow_redirects is False
    assert adapter.transport_policy.retries == 0
    assert snapshot.provider == "codex" and snapshot.mode == "api"
    assert snapshot.binding_id == api_binding.binding_id
    assert "sk-test" not in repr(snapshot)


def test_subscription_or_other_provider_credentials_cannot_enter_api_binding():
    for provider in ("codex", "claude", "openai"):
        with pytest.raises(ValueError, match="Codex API"):
            binding(CredentialRef(provider, "a" * 32))
    with pytest.raises(ValueError, match="API-only"):
        CodexAPIAdapter(vault=InMemoryCredentialVault(), mode="subscription")


def test_catalog_is_account_observation_not_inferred_capability_or_execution_readiness():
    adapter, _, api_binding = subject(lambda request: response())
    snapshot = adapter.fetch_catalog(api_binding, explicit_action=True)
    model = snapshot.models[0]
    assert model.model_id == "gpt-6-astra"
    assert model.shutdown_date is None
    assert model.capabilities == ()
    assert model.execution_eligible is False
    selection = CodexAPISelection(
        binding_id=api_binding.binding_id,
        catalog_id=snapshot.catalog_id,
        model_id=model.model_id,
    )
    assert (
        adapter.validate_selection(
            selection, snapshot, api_binding, explicit_action=True
        )
        == model
    )
    with pytest.raises(ValueError, match="capability"):
        adapter.validate_selection(
            selection,
            snapshot,
            api_binding,
            explicit_action=True,
            required_capabilities=("image_input",),
        )


def test_key_rotation_and_snapshot_tampering_never_inherit_catalog_authority():
    adapter, vault, api_binding = subject(lambda request: response())
    snapshot = adapter.fetch_catalog(api_binding, explicit_action=True)
    selection = CodexAPISelection(api_binding.binding_id, snapshot.catalog_id, MODEL["id"])
    replacement = vault.rotate(api_binding.credential_ref, "sk-rotated")
    with pytest.raises((CodexAPIError, ValueError), match="credential|live connection"):
        adapter.validate_selection(
            selection, snapshot, api_binding, explicit_action=True
        )
    with pytest.raises(ValueError, match="binding"):
        adapter.validate_selection(
            selection, snapshot, binding(replacement), explicit_action=True
        )
    forged = replace(snapshot, fetched_at_ms=snapshot.fetched_at_ms + 1)
    with pytest.raises(ValueError, match="integrity"):
        adapter.validate_selection(
            selection, forged, api_binding, explicit_action=True
        )


def test_snapshot_from_another_adapter_is_not_accepted_even_when_self_hashes_match():
    adapter, vault, api_binding = subject(lambda request: response())
    snapshot = adapter.fetch_catalog(api_binding, explicit_action=True)
    other = CodexAPIAdapter(
        vault=vault,
        transport=httpx.MockTransport(lambda request: response()),
        clock_ms=lambda: 10_000,
        monotonic_ms=lambda: 10_000,
    )
    selection = CodexAPISelection(api_binding.binding_id, snapshot.catalog_id, MODEL["id"])
    with pytest.raises(ValueError, match="live connection"):
        other.validate_selection(
            selection, snapshot, api_binding, explicit_action=True
        )


def test_catalog_staleness_missing_model_and_unknown_effort_fail_before_generation():
    current_time = [10_000]
    adapter, _, api_binding = subject(
        lambda request: response(),
        clock=lambda: current_time[0],
        catalog_max_age_ms=100,
    )
    snapshot = adapter.fetch_catalog(api_binding, explicit_action=True)
    valid = CodexAPISelection(api_binding.binding_id, snapshot.catalog_id, MODEL["id"])
    current_time[0] = 10_101
    with pytest.raises(ValueError, match="stale"):
        adapter.validate_selection(
            valid, snapshot, api_binding, explicit_action=True
        )
    current_time[0] = 10_000
    missing = replace(valid, model_id="not-listed")
    with pytest.raises(ValueError, match="unavailable"):
        adapter.validate_selection(
            missing, snapshot, api_binding, explicit_action=True
        )
    effort = replace(valid, effort="high")
    with pytest.raises(ValueError, match="unknown"):
        adapter.validate_selection(
            effort, snapshot, api_binding, explicit_action=True
        )


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"object": "wrong", "data": []}, "catalog_object"),
        ({"object": "list", "data": "bad"}, "catalog_data"),
        ({"object": "list", "data": [MODEL, MODEL]}, "duplicate_model"),
        ({"object": "list", "data": [{**MODEL, "id": "bad id"}]}, "model_id"),
        ({"object": "list", "data": [{**MODEL, "created": True}]}, "model_created"),
        ({"object": "list", "data": [{**MODEL, "owned_by": "bad owner"}]}, "model_owner"),
        ({"object": "list", "data": [{**MODEL, "shutdown_date": "soon"}]}, "model_shutdown_date"),
        ({"object": "list", "data": [{**MODEL, "shutdown_date": "2026-02-31"}]}, "model_shutdown_date"),
    ],
)
def test_malformed_catalog_fails_closed(payload, detail):
    adapter, _, api_binding = subject(lambda request: response(payload))
    with pytest.raises(CodexAPIError) as raised:
        adapter.fetch_catalog(api_binding, explicit_action=True)
    assert raised.value.failure.detail_code == detail


def test_duplicate_json_keys_and_nonfinite_json_are_rejected():
    bodies = [
        b'{"object":"list","object":"list","data":[]}',
        b'{"object":"list","data":[],"value":NaN}',
    ]
    for raw in bodies:
        adapter, _, api_binding = subject(
            lambda request, raw=raw: httpx.Response(
                200, headers={"content-type": "application/json"}, content=raw
            )
        )
        with pytest.raises(CodexAPIError) as raised:
            adapter.fetch_catalog(api_binding, explicit_action=True)
        assert raised.value.failure.category == "catalog_protocol_error"


def test_redirect_wrong_content_type_and_oversize_are_not_followed_or_parsed():
    cases = [
        (httpx.Response(307, headers={"location": "https://evil.example/key"}), "redirect_refused"),
        (httpx.Response(200, headers={"content-type": "text/html"}, content=b"ok"), "catalog_content_type"),
        (httpx.Response(200, headers={"content-type": "application/json"}, content=b"x" * 1025), "catalog_byte_limit"),
    ]
    for outbound, expected in cases:
        adapter, _, api_binding = subject(lambda request, outbound=outbound: outbound, max_catalog_bytes=1024)
        with pytest.raises(CodexAPIError) as raised:
            adapter.fetch_catalog(api_binding, explicit_action=True)
        assert raised.value.failure.detail_code == expected


@pytest.mark.parametrize(
    ("status", "category", "retry", "effect"),
    [
        (401, "authentication", "never", "response_observed"),
        (403, "authorization", "never", "response_observed"),
        (429, "rate_limit", "caller_only", "response_observed"),
        (500, "provider_server", "caller_only", "response_observed"),
    ],
)
def test_http_failures_are_sanitized_and_never_auto_fallback(status, category, retry, effect):
    secret_echo = "sk-test-codex-api-only"
    adapter, _, api_binding = subject(
        lambda request: httpx.Response(
            status,
            headers={"content-type": "application/json", "x-request-id": secret_echo},
            content=(secret_echo + " raw provider body").encode(),
        )
    )
    with pytest.raises(CodexAPIError) as raised:
        adapter.fetch_catalog(api_binding, explicit_action=True)
    failure = raised.value.failure
    assert (failure.category, failure.retry, failure.dispatch_effect) == (category, retry, effect)
    assert failure.fallback_mode is None
    assert secret_echo not in repr(raised.value)
    assert secret_echo not in str(failure)
    assert failure.request_id is None
    assert hashlib.sha256(secret_echo.encode()).hexdigest() not in str(failure)


@pytest.mark.parametrize(
    ("field", "as_digest"),
    [("id", False), ("owned_by", False), ("id", True)],
)
def test_success_catalog_rejects_provider_fields_that_reflect_the_api_key(
    field, as_digest
):
    secret = "sk-test-codex-api-only"

    def reflected(request):
        echoed = request.headers["authorization"].removeprefix("Bearer ")
        reflected_value = (
            hashlib.sha256(echoed.encode()).hexdigest() if as_digest else echoed
        )
        return response(
            {"object": "list", "data": [{**MODEL, field: reflected_value}]}
        )

    adapter, _, api_binding = subject(reflected)
    with pytest.raises(CodexAPIError) as raised:
        adapter.fetch_catalog(api_binding, explicit_action=True)
    assert raised.value.failure.detail_code == "catalog_secret_reflection"
    assert secret not in repr(raised.value)
    assert secret not in str(raised.value.failure)


@pytest.mark.parametrize("field", ["id", "owned_by"])
@pytest.mark.parametrize(
    "reflected",
    [
        "sk-test-codex-api-onl",
        "k-test-codex-api-only",
        hashlib.sha256(b"sk-test-codex-api-only").hexdigest().upper(),
        hashlib.sha384(b"sk-test-codex-api-only").hexdigest(),
        hashlib.sha512(b"sk-test-codex-api-only").hexdigest(),
    ],
)
def test_catalog_rejects_meaningful_key_fragments_and_common_fingerprints(
    field, reflected
):
    adapter, _, api_binding = subject(
        lambda request: response(
            {"object": "list", "data": [{**MODEL, field: reflected}]}
        )
    )

    with pytest.raises(CodexAPIError) as raised:
        adapter.fetch_catalog(api_binding, explicit_action=True)

    assert raised.value.failure.detail_code == "catalog_secret_reflection"


def test_auth_failure_invalidates_previously_issued_snapshot():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return response(status=401) if calls == 2 else response()

    adapter, _, api_binding = subject(handler)
    snapshot = adapter.fetch_catalog(api_binding, explicit_action=True)
    selection = CodexAPISelection(api_binding.binding_id, snapshot.catalog_id, MODEL["id"])
    with pytest.raises(CodexAPIError):
        adapter.fetch_catalog(api_binding, explicit_action=True)
    with pytest.raises(ValueError, match="live connection"):
        adapter.validate_selection(
            selection, snapshot, api_binding, explicit_action=True
        )
    renewed = adapter.fetch_catalog(api_binding, explicit_action=True)
    assert renewed.catalog_id != snapshot.catalog_id
    renewed_selection = replace(selection, catalog_id=renewed.catalog_id)
    assert (
        adapter.validate_selection(
            renewed_selection, renewed, api_binding, explicit_action=True
        ).model_id
        == MODEL["id"]
    )


def test_401_invalidates_every_catalog_bound_to_the_same_credential_ref():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return response() if calls == 1 else response(status=401)

    vault = InMemoryCredentialVault()
    ref = vault.store("codex_api", "sk-same-key")
    adapter = CodexAPIAdapter(
        vault=vault,
        transport=httpx.MockTransport(handler),
        clock_ms=lambda: 10_000,
        monotonic_ms=lambda: 10_000,
    )
    first = binding(ref, project="proj_first")
    second = binding(ref, project="proj_second")
    snapshot = adapter.fetch_catalog(first, explicit_action=True)
    selection = CodexAPISelection(first.binding_id, snapshot.catalog_id, MODEL["id"])
    with pytest.raises(CodexAPIError):
        adapter.fetch_catalog(second, explicit_action=True)
    with pytest.raises(ValueError, match="live connection"):
        adapter.validate_selection(
            selection, snapshot, first, explicit_action=True
        )
    assert adapter.connection_state(first) == "invalidated"
    assert adapter.connection_state(second) == "invalidated"


def test_older_success_cannot_resurrect_catalog_after_later_401():
    entered = threading.Event()
    release = threading.Event()
    call_lock = threading.Lock()
    calls = 0
    body = json.dumps({"object": "list", "data": [MODEL]}).encode("utf-8")

    class BlockingStream(httpx.SyncByteStream):
        def __iter__(self):
            entered.set()
            assert release.wait(5)
            yield body

    def handler(request):
        nonlocal calls
        with call_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=BlockingStream(),
            )
        return response(status=401)

    adapter, _, api_binding = subject(handler)
    result = {}

    def fetch_older_success():
        try:
            result["snapshot"] = adapter.fetch_catalog(api_binding, explicit_action=True)
        except Exception as error:  # the exact sanitized failure is asserted below
            result["error"] = error

    worker = threading.Thread(target=fetch_older_success)
    worker.start()
    assert entered.wait(5)
    with pytest.raises(CodexAPIError):
        adapter.fetch_catalog(api_binding, explicit_action=True)
    release.set()
    worker.join(5)
    assert worker.is_alive() is False
    assert "snapshot" not in result
    assert isinstance(result.get("error"), CodexAPIError)
    assert result["error"].failure.detail_code == "credential_state_changed"
    assert adapter.connection_state(api_binding) == "invalidated"


def test_older_success_cannot_replace_a_newer_success_for_the_same_binding():
    entered = threading.Event()
    release = threading.Event()
    call_lock = threading.Lock()
    calls = 0
    old_model = {**MODEL, "id": "gpt-old"}
    new_model = {**MODEL, "id": "gpt-new"}
    old_body = json.dumps({"object": "list", "data": [old_model]}).encode()

    class BlockingStream(httpx.SyncByteStream):
        def __iter__(self):
            entered.set()
            assert release.wait(5)
            yield old_body

    def handler(request):
        nonlocal calls
        with call_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=BlockingStream(),
            )
        return response({"object": "list", "data": [new_model]})

    adapter, _, api_binding = subject(handler)
    older = {}

    def fetch_older():
        try:
            older["snapshot"] = adapter.fetch_catalog(
                api_binding, explicit_action=True
            )
        except Exception as error:
            older["error"] = error

    worker = threading.Thread(target=fetch_older)
    worker.start()
    assert entered.wait(5)
    newer = adapter.fetch_catalog(api_binding, explicit_action=True)
    release.set()
    worker.join(5)

    assert worker.is_alive() is False
    assert "snapshot" not in older
    assert isinstance(older.get("error"), CodexAPIError)
    assert older["error"].failure.detail_code == "catalog_request_superseded"
    selected = CodexAPISelection(
        api_binding.binding_id, newer.catalog_id, "gpt-new"
    )
    assert adapter.validate_selection(
        selected, newer, api_binding, explicit_action=True
    ).model_id == "gpt-new"


def test_successful_refresh_revokes_removed_models_from_the_prior_catalog():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        models = [MODEL] if calls == 1 else []
        return response({"object": "list", "data": models})

    adapter, _, api_binding = subject(handler)
    prior = adapter.fetch_catalog(api_binding, explicit_action=True)
    prior_selection = CodexAPISelection(
        api_binding.binding_id, prior.catalog_id, MODEL["id"]
    )
    current = adapter.fetch_catalog(api_binding, explicit_action=True)

    assert current.models == ()
    with pytest.raises(ValueError, match="live connection"):
        adapter.validate_selection(
            prior_selection, prior, api_binding, explicit_action=True
        )


def test_catalog_absolute_deadline_and_transport_unknown_are_distinct():
    ticks = iter((0, 0, 11))
    adapter, _, api_binding = subject(
        lambda request: response(), clock=lambda: next(ticks), max_catalog_duration_ms=10
    )
    with pytest.raises(CodexAPIError) as deadline:
        adapter.fetch_catalog(api_binding, explicit_action=True)
    assert deadline.value.failure.detail_code == "catalog_absolute_deadline"

    def broken(request):
        raise httpx.ReadTimeout("secret-shaped transport text")

    adapter, _, api_binding = subject(broken)
    with pytest.raises(CodexAPIError) as transport:
        adapter.fetch_catalog(api_binding, explicit_action=True)
    assert transport.value.failure.category == "transport_unknown"
    assert transport.value.failure.dispatch_effect == "unknown"


def test_catalog_validation_clock_is_not_publicly_caller_overridable():
    signature = inspect.signature(CodexAPIAdapter.validate_selection)
    assert "now_ms" not in signature.parameters


def test_response_decode_failure_never_claims_the_request_was_not_sent():
    adapter, _, api_binding = subject(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/json", "content-encoding": "gzip"},
            stream=httpx.ByteStream(b"not-a-gzip-stream"),
        )
    )
    with pytest.raises(CodexAPIError) as raised:
        adapter.fetch_catalog(api_binding, explicit_action=True)
    assert raised.value.failure.category == "catalog_response_error"
    assert raised.value.failure.detail_code == "catalog_response_read_failed"
    assert raised.value.failure.dispatch_effect == "response_observed"


def test_transport_side_decode_failure_is_unknown_instead_of_not_sent():
    adapter, _, api_binding = subject(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/json", "content-encoding": "gzip"},
            content=b"not-a-gzip-stream",
        )
    )
    with pytest.raises(CodexAPIError) as raised:
        adapter.fetch_catalog(api_binding, explicit_action=True)
    assert raised.value.failure.category == "transport_unknown"
    assert raised.value.failure.dispatch_effect == "unknown"


def test_no_catalog_request_occurs_during_construction_or_binding():
    calls = []
    adapter, _, api_binding = subject(lambda request: calls.append(request) or response())
    assert calls == []
    assert api_binding.binding_id.startswith("codex-api-binding-")
    assert adapter.connection_state(api_binding) == "not_checked"
    assert calls == []
