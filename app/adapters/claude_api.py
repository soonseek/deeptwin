"""Claude direct-API boundary with strict catalogs and streamed events.

The adapter deliberately does not discover Claude Code/subscription state, retry
requests, dispatch tools, reserve budget, or write runtime state.  Those are
caller-owned boundaries.  It does provide enough typed facts for those layers to
make fail-closed decisions without exposing provider bodies or credentials.
"""

from __future__ import annotations

import base64
import binascii
from contextlib import contextmanager
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import json
import math
import re
import threading
import time
from types import MappingProxyType
from typing import Any, Callable, Iterator, Mapping, Sequence

# Provider packages are release extras, not application-import prerequisites.
# Keeping these imports optional lets the rest of DeepTwin start and present an
# actionable provider-setup state without installing anything implicitly.
try:  # pragma: no branch - each missing-package shape is exercised in a subprocess
    import anthropic
except ImportError:  # pragma: no cover - focused subprocess assertion
    anthropic = None  # type: ignore[assignment]
try:  # pragma: no branch - each missing-package shape is exercised in a subprocess
    import httpx2
except ImportError:  # pragma: no cover - focused subprocess assertion
    httpx2 = None  # type: ignore[assignment]

from .keychain import (
    CredentialAccessDenied,
    CredentialError,
    CredentialNeedsUnlock,
    CredentialNotFound,
    CredentialRef,
    CredentialVault,
)


API_ORIGIN = "https://api.anthropic.com"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_WORKSPACE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_TOOL_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,127}\Z")
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_STOP_REASONS = {
    "end_turn",
    "stop_sequence",
    "tool_use",
    "max_tokens",
    "model_context_window_exceeded",
    "refusal",
    "pause_turn",
}


@dataclass(frozen=True, slots=True)
class TransportPolicy:
    origin: str = API_ORIGIN
    mode: str = "api"
    trust_env: bool = False
    follow_redirects: bool = False
    sdk_max_retries: int = 0


@dataclass(frozen=True, slots=True)
class StreamLimits:
    max_catalog_pages: int = 20
    max_catalog_models: int = 20_000
    max_catalog_page_bytes: int = 2 * 1024 * 1024
    max_total_stream_bytes: int = 8 * 1024 * 1024
    max_event_bytes: int = 1024 * 1024
    max_events: int = 10_000
    max_blocks: int = 128
    max_text_bytes: int = 4 * 1024 * 1024
    max_tool_json_bytes: int = 256 * 1024
    max_request_bytes: int = 4 * 1024 * 1024
    max_catalog_duration_ms: int = 120 * 1000
    max_stream_duration_ms: int = 180 * 1000

    def __post_init__(self) -> None:
        release_ceilings = {
            "max_catalog_pages": 100,
            "max_catalog_models": 100_000,
            "max_catalog_page_bytes": 16 * 1024 * 1024,
            "max_total_stream_bytes": 64 * 1024 * 1024,
            "max_event_bytes": 4 * 1024 * 1024,
            "max_events": 100_000,
            "max_blocks": 1024,
            "max_text_bytes": 32 * 1024 * 1024,
            "max_tool_json_bytes": 4 * 1024 * 1024,
            "max_request_bytes": 32 * 1024 * 1024,
            "max_catalog_duration_ms": 10 * 60 * 1000,
            # The runtime contract fixes a per-model-call deadline of 180s.
            # A session's remaining deadline may only reduce this value.
            "max_stream_duration_ms": 180 * 1000,
        }
        for name in self.__slots__:
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
            if value > release_ceilings[name]:
                raise ValueError(f"{name} exceeds its non-configurable release ceiling")


@dataclass(frozen=True, slots=True)
class ClaudeBinding:
    credential_ref: CredentialRef
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        if self.credential_ref.provider != "claude":
            raise ValueError("Claude binding requires a Claude credential reference")
        if self.workspace_id is not None and not _WORKSPACE_ID.fullmatch(self.workspace_id):
            raise ValueError("Invalid Claude workspace identifier")

    @property
    def binding_id(self) -> str:
        body = {
            "provider": "claude",
            "mode": "api",
            "credential_ref": self.credential_ref.identifier,
            "workspace_id": self.workspace_id,
        }
        return "claude-binding-" + _sha256_json(body)


@dataclass(frozen=True, slots=True)
class CatalogModel:
    id: str
    display_name: str
    created_at: str
    max_input_tokens: int | None
    max_tokens: int | None
    _capabilities_json: str | None

    @property
    def capabilities(self) -> dict[str, Any] | None:
        if self._capabilities_json is None:
            return None
        return json.loads(self._capabilities_json)

    def digest_record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "created_at": self.created_at,
            "max_input_tokens": self.max_input_tokens,
            "max_tokens": self.max_tokens,
            "capabilities": self.capabilities,
        }


@dataclass(frozen=True, slots=True)
class ModelCatalogSnapshot:
    binding_id: str
    catalog_id: str
    fetched_at_ms: int
    max_age_ms: int
    credential_generation: int
    binding_generation: int
    request_epoch: int
    models: tuple[CatalogModel, ...]

    def with_catalog_id(self, catalog_id: str) -> ModelCatalogSnapshot:
        return replace(self, catalog_id=catalog_id)


@dataclass(frozen=True, slots=True)
class ModelSelection:
    binding_id: str
    catalog_id: str
    model_id: str
    effort: str | None = None
    thinking_type: str | None = None


@dataclass(frozen=True, slots=True)
class MessageTurn:
    call_id: str
    agent_id: str
    selection: ModelSelection
    system: str
    messages: Sequence[Mapping[str, Any]]
    tools: Sequence[Mapping[str, Any]] = ()
    max_tokens: int = 1024
    thinking_budget_tokens: int | None = None

    def __repr__(self) -> str:
        return (
            f"MessageTurn(call_id={self.call_id!r}, agent_id={self.agent_id!r}, "
            f"model_id={self.selection.model_id!r}, messages=<redacted>, tools={len(self.tools)})"
        )


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    category: str
    detail_code: str
    retry: str
    dispatch_effect: str
    retry_after_ms: int | None = None
    request_id: str | None = None


class CatalogError(RuntimeError):
    """Sanitized catalog failure; raw provider bodies are intentionally omitted."""

    def __init__(self, failure: ProviderFailure):
        self.failure = failure
        super().__init__(f"Claude catalog failed: {failure.category}/{failure.detail_code}")

    def __repr__(self) -> str:
        return f"CatalogError(category={self.failure.category!r}, detail_code={self.failure.detail_code!r})"


@dataclass(frozen=True, slots=True)
class ProviderStarted:
    call_id: str
    agent_id: str
    provider_message_id: str
    requested_model: str
    observed_model: str
    request_id: str | None
    requested_effort: str | None
    observed_effort: str | None


@dataclass(frozen=True, slots=True)
class TextDelta:
    call_id: str
    index: int
    text: str


@dataclass(frozen=True, slots=True)
class ToolRequested:
    call_id: str
    index: int
    tool_use_id: str
    name: str
    _input_json: str

    @property
    def input(self) -> dict[str, Any]:
        # A fresh tree on every access prevents mutation between authorization
        # and dispatch.  The dispatcher must still validate the actual tree.
        return json.loads(self._input_json)

    def __repr__(self) -> str:
        return (
            f"ToolRequested(call_id={self.call_id!r}, index={self.index}, "
            f"tool_use_id={self.tool_use_id!r}, name={self.name!r}, input=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class UsageObserved:
    call_id: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int


@dataclass(frozen=True, slots=True)
class ProviderTerminal:
    call_id: str
    state: str
    stop_reason: str | None
    usage_finality: str
    failure: ProviderFailure | None = None


@dataclass(frozen=True, slots=True)
class _PreparedTurn:
    kwargs: Mapping[str, Any]
    tool_names: frozenset[str]
    historical_tool_ids: frozenset[str]
    required_capabilities: tuple[str, ...]


@dataclass(slots=True)
class _Block:
    index: int
    kind: str
    tool_use_id: str | None = None
    tool_name: str | None = None
    partial_json: str = ""
    safe_text_tail: str = ""


@dataclass(frozen=True, slots=True)
class _IssuedCatalog:
    binding_id: str
    credential_ref: CredentialRef
    digest: str
    credential_generation: int
    binding_generation: int
    request_epoch: int


class _ProtocolViolation(Exception):
    def __init__(self, detail_code: str, *, category: str = "protocol_error"):
        self.detail_code = detail_code
        self.category = category
        super().__init__(detail_code)


class _CancellationObserved(Exception):
    pass


class _ProviderDependencyUnavailable(Exception):
    pass


class _ObservedProviderFailure(Exception):
    def __init__(self, failure: ProviderFailure):
        self.failure = failure
        super().__init__(failure.detail_code)


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _ProtocolViolation("duplicate_json_key")
        result[key] = value
    return result


def _strict_json(raw: bytes | str, *, detail_code: str) -> Any:
    def reject_constant(_value: str) -> None:
        raise _ProtocolViolation("nonfinite_json_constant")

    try:
        return json.loads(raw, object_pairs_hook=_strict_object, parse_constant=reject_constant)
    except _ProtocolViolation:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, RecursionError) as exc:
        raise _ProtocolViolation(detail_code) from exc


def _secret_canaries(secret: str) -> tuple[tuple[str, int], ...]:
    """Create ephemeral checks for raw key fragments and common fingerprints.

    These values exist only while the credential is open.  They are never put
    in adapter state, events, errors or catalog digests.
    """

    raw = secret.encode("utf-8", errors="strict")
    values: list[tuple[str, int]] = [
        (secret, 8),
        (raw.hex(), 12),
        (base64.b64encode(raw).decode("ascii").rstrip("="), 12),
        (base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="), 12),
    ]
    for algorithm in ("md5", "sha1", "sha224", "sha256", "sha384", "sha512"):
        digest = hashlib.new(algorithm, raw).digest()
        values.extend(
            (
                (digest.hex(), 12),
                (base64.b64encode(digest).decode("ascii").rstrip("="), 12),
                (base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="), 12),
            )
        )
    return tuple(sorted({(value.casefold(), width) for value, width in values if value}))


def _reflects_secret(value: str, canaries: tuple[tuple[str, int], ...]) -> bool:
    if not value:
        return False
    folded = value.casefold()
    for canary, fragment_size in canaries:
        if canary in folded:
            return True
        if len(canary) < fragment_size or len(folded) < fragment_size:
            continue
        for start in range(len(folded) - fragment_size + 1):
            if folded[start : start + fragment_size] in canary:
                return True
    return False


def _secret_overlap_width(canaries: tuple[tuple[str, int], ...]) -> int:
    return max((min(len(value), width) - 1 for value, width in canaries), default=0)


def _safe_nonnegative_int(value: Any, field: str, *, optional=False) -> int | None:
    if value is None and optional:
        return None
    if type(value) is not int or value < 0 or value > 1_000_000_000_000:
        raise _ProtocolViolation(f"invalid_{field}")
    return value


def _request_id(value: str | None) -> str | None:
    # A provider-controlled header can reflect the API key.  Hashing it would
    # still emit a prohibited stable key fingerprint, so it stays private to
    # the HTTP boundary until a separate safe correlation mapping exists.
    return None


class ClaudeAPIAdapter:
    """Official Claude Messages/Models API transport, without an agent loop."""

    def __init__(
        self,
        *,
        vault: CredentialVault,
        transport=None,
        clock_ms: Callable[[], int] | None = None,
        monotonic_ms: Callable[[], int] | None = None,
        limits: StreamLimits | None = None,
        mode: str = "api",
        catalog_max_age_ms: int = 15 * 60 * 1000,
        timeout_seconds: float = 60.0,
    ) -> None:
        if mode != "api":
            raise ValueError("Claude is API-only; subscription mode is not supported")
        if type(catalog_max_age_ms) is not int or catalog_max_age_ms <= 0:
            raise ValueError("catalog_max_age_ms must be positive")
        if catalog_max_age_ms > 24 * 60 * 60 * 1000:
            raise ValueError("catalog_max_age_ms exceeds its non-configurable release ceiling")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive")
        if float(timeout_seconds) > 180.0:
            raise ValueError("timeout_seconds exceeds its non-configurable release ceiling")
        self._vault = vault
        self._transport = transport
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._monotonic_ms = monotonic_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self._limits = limits or StreamLimits()
        self._catalog_max_age_ms = catalog_max_age_ms
        self._timeout_seconds = float(timeout_seconds)
        self._catalog_lock = threading.RLock()
        self._issued_catalogs: OrderedDict[str, _IssuedCatalog] = OrderedDict()
        self._binding_credentials: dict[str, CredentialRef] = {}
        self._credential_generations: dict[CredentialRef, int] = {}
        self._binding_generations: dict[str, int] = {}
        self._binding_request_epochs: dict[str, int] = {}
        self._binding_current_catalogs: dict[str, str] = {}
        self._connection_states: dict[str, str] = {}
        self.policy = TransportPolicy()

    def __repr__(self) -> str:
        return "<ClaudeAPIAdapter mode=api origin=https://api.anthropic.com>"

    def connection_state(self, binding: ClaudeBinding) -> str:
        if not isinstance(binding, ClaudeBinding):
            raise TypeError("binding must be ClaudeBinding")
        with self._catalog_lock:
            return self._connection_states.get(binding.binding_id, "not_checked")

    @contextmanager
    def _client(
        self,
        binding: ClaudeBinding,
        *,
        deadline_started_ms: int,
        operation_duration_ms: int,
        deadline_detail: str,
    ):
        # Check before opening the vault so a missing optional package never
        # causes credential material to be loaded merely to report setup state.
        if anthropic is None or httpx2 is None:
            raise _ProviderDependencyUnavailable("Claude API dependencies are unavailable")
        with self._vault.open(binding.credential_ref) as material:
            key = material.reveal_text()
            effective_timeout = min(
                self._timeout_seconds,
                self._remaining_timeout_seconds(
                    deadline_started_ms,
                    operation_duration_ms,
                    deadline_detail,
                ),
            )
            kwargs = {
                "base_url": API_ORIGIN,
                "timeout": effective_timeout,
                "trust_env": False,
                "follow_redirects": False,
            }
            if self._transport is not None:
                kwargs["transport"] = self._transport
            http_client = httpx2.Client(**kwargs)
            client = anthropic.Anthropic(
                api_key=key,
                base_url=API_ORIGIN,
                timeout=effective_timeout,
                max_retries=0,
                http_client=http_client,
                _strict_response_validation=True,
            )
            try:
                yield client, _secret_canaries(key)
            finally:
                try:
                    client.close()
                finally:
                    key = ""  # release the local reference; SecretMaterial is zeroed by its context.

    def _monotonic(self) -> int:
        value = self._monotonic_ms()
        if type(value) is not int or value < 0:
            raise _ProtocolViolation("invalid_monotonic_clock")
        return value

    def _check_deadline(self, started_at_ms: int, duration_ms: int, detail: str) -> None:
        now = self._monotonic()
        if now < started_at_ms:
            raise _ProtocolViolation("monotonic_clock_regressed")
        if now - started_at_ms >= duration_ms:
            raise _ProtocolViolation(detail, category="deadline")

    def _remaining_timeout_seconds(
        self,
        started_at_ms: int,
        duration_ms: int,
        detail: str,
    ) -> float:
        now = self._monotonic()
        if now < started_at_ms:
            raise _ProtocolViolation("monotonic_clock_regressed")
        remaining_ms = duration_ms - (now - started_at_ms)
        if remaining_ms <= 0:
            raise _ProtocolViolation(detail, category="deadline")
        return remaining_ms / 1000.0

    def _read_bounded(
        self,
        chunks: Iterator[bytes],
        limit: int,
        detail: str,
        *,
        started_at_ms: int | None = None,
        duration_ms: int | None = None,
    ) -> bytes:
        total = 0
        result = bytearray()
        for chunk in chunks:
            if started_at_ms is not None and duration_ms is not None:
                self._check_deadline(started_at_ms, duration_ms, "catalog_absolute_deadline_exceeded")
            total += len(chunk)
            if total > limit:
                raise _ProtocolViolation(detail)
            result.extend(chunk)
        return bytes(result)

    def _begin_catalog_request(self, binding: ClaudeBinding) -> tuple[int, int, int]:
        with self._catalog_lock:
            binding_id = binding.binding_id
            self._binding_credentials[binding_id] = binding.credential_ref
            request_epoch = self._binding_request_epochs.get(binding_id, 0) + 1
            self._binding_request_epochs[binding_id] = request_epoch
            self._connection_states[binding_id] = "checking"
            return (
                self._credential_generations.get(binding.credential_ref, 0),
                self._binding_generations.get(binding_id, 0),
                request_epoch,
            )

    def _invalidate_binding(
        self,
        binding_id: str,
        *,
        state: str = "invalidated",
        expected_request_epoch: int | None = None,
        expected_catalog_id: str | None = None,
    ) -> bool:
        with self._catalog_lock:
            if (
                expected_request_epoch is not None
                and self._binding_request_epochs.get(binding_id, 0) != expected_request_epoch
            ):
                return False
            if (
                expected_catalog_id is not None
                and self._binding_current_catalogs.get(binding_id) != expected_catalog_id
            ):
                return False
            self._binding_generations[binding_id] = self._binding_generations.get(binding_id, 0) + 1
            stale = [
                catalog_id
                for catalog_id, issued in self._issued_catalogs.items()
                if issued.binding_id == binding_id
            ]
            for catalog_id in stale:
                self._issued_catalogs.pop(catalog_id, None)
            self._binding_current_catalogs.pop(binding_id, None)
            self._connection_states[binding_id] = state
            return True

    def _invalidate_credential(
        self,
        credential_ref: CredentialRef,
        *,
        observed_binding_id: str | None = None,
        state: str = "invalidated",
        expected_request_epoch: int | None = None,
        expected_catalog_id: str | None = None,
    ) -> bool:
        with self._catalog_lock:
            if expected_request_epoch is not None:
                if observed_binding_id is None:
                    raise ValueError("A binding is required for conditional invalidation")
                if (
                    self._binding_request_epochs.get(observed_binding_id, 0)
                    != expected_request_epoch
                ):
                    return False
            if expected_catalog_id is not None:
                if observed_binding_id is None:
                    raise ValueError("A binding is required for conditional invalidation")
                if (
                    self._binding_current_catalogs.get(observed_binding_id)
                    != expected_catalog_id
                ):
                    return False
            self._credential_generations[credential_ref] = (
                self._credential_generations.get(credential_ref, 0) + 1
            )
            affected = {
                binding_id
                for binding_id, bound_ref in self._binding_credentials.items()
                if bound_ref == credential_ref
            }
            if observed_binding_id is not None:
                affected.add(observed_binding_id)
                self._binding_credentials[observed_binding_id] = credential_ref
            stale = [
                catalog_id
                for catalog_id, issued in self._issued_catalogs.items()
                if issued.credential_ref == credential_ref
            ]
            for catalog_id in stale:
                self._issued_catalogs.pop(catalog_id, None)
            for binding_id in affected:
                self._binding_current_catalogs.pop(binding_id, None)
                self._connection_states[binding_id] = state
            return True

    @staticmethod
    def _superseded_catalog_failure(dispatch_effect: str) -> ProviderFailure:
        return ProviderFailure(
            category="catalog_stale",
            detail_code="catalog_request_superseded",
            retry="never",
            dispatch_effect=dispatch_effect,
        )

    def _expected_issue(
        self,
        snapshot: ModelCatalogSnapshot,
        binding: ClaudeBinding,
    ) -> _IssuedCatalog:
        return _IssuedCatalog(
            binding_id=binding.binding_id,
            credential_ref=binding.credential_ref,
            digest=self._catalog_digest(snapshot),
            credential_generation=snapshot.credential_generation,
            binding_generation=snapshot.binding_generation,
            request_epoch=snapshot.request_epoch,
        )

    def _assert_catalog_authority_locked(
        self,
        snapshot: ModelCatalogSnapshot,
        binding: ClaudeBinding,
    ) -> None:
        expected = self._expected_issue(snapshot, binding)
        if self._issued_catalogs.get(snapshot.catalog_id) != expected:
            raise _ProtocolViolation("catalog_authority_changed", category="configuration_stale")
        if (
            self._credential_generations.get(binding.credential_ref, 0)
            != snapshot.credential_generation
            or self._binding_generations.get(binding.binding_id, 0)
            != snapshot.binding_generation
        ):
            raise _ProtocolViolation("catalog_authority_changed", category="configuration_stale")
        observed_at = self._clock_ms()
        if type(observed_at) is not int:
            raise _ProtocolViolation("invalid_catalog_clock", category="configuration_stale")
        if (
            observed_at < snapshot.fetched_at_ms
            or observed_at > snapshot.fetched_at_ms + snapshot.max_age_ms
        ):
            raise _ProtocolViolation("catalog_authority_changed", category="configuration_stale")

    def fetch_catalog(
        self,
        binding: ClaudeBinding,
        *,
        explicit_action: bool,
    ) -> ModelCatalogSnapshot:
        if explicit_action is not True:
            raise ValueError("Claude catalog access requires an explicit API action")
        if not isinstance(binding, ClaudeBinding):
            raise TypeError("binding must be ClaudeBinding")
        fetched_at = self._clock_ms()
        if type(fetched_at) is not int or fetched_at < 0:
            raise ValueError("Invalid catalog clock")
        models: list[CatalogModel] = []
        seen_models: set[str] = set()
        seen_cursors: set[str] = set()
        cursor: str | None = None
        deadline_started = self._monotonic()
        credential_generation, binding_generation, request_epoch = self._begin_catalog_request(binding)
        request_started = False
        response_observed = False
        catalog_error: ProviderFailure | None = None
        try:
            with self._client(
                binding,
                deadline_started_ms=deadline_started,
                operation_duration_ms=self._limits.max_catalog_duration_ms,
                deadline_detail="catalog_absolute_deadline_exceeded",
            ) as (client, secret_canaries):
                if binding.workspace_id is not None and _reflects_secret(
                    binding.workspace_id,
                    secret_canaries,
                ):
                    raise _ProtocolViolation("request_secret_reflection")
                for _page_number in range(self._limits.max_catalog_pages):
                    self._check_deadline(
                        deadline_started,
                        self._limits.max_catalog_duration_ms,
                        "catalog_absolute_deadline_exceeded",
                    )
                    kwargs: dict[str, Any] = {"limit": 1000}
                    if cursor is not None:
                        kwargs["after_id"] = cursor
                    if binding.workspace_id is not None:
                        kwargs["workspace_id"] = binding.workspace_id
                    kwargs["timeout"] = min(
                        self._timeout_seconds,
                        self._remaining_timeout_seconds(
                            deadline_started,
                            self._limits.max_catalog_duration_ms,
                            "catalog_absolute_deadline_exceeded",
                        ),
                    )
                    manager = client.models.with_streaming_response.list(**kwargs)
                    request_started = True
                    with manager as raw_response:
                        response_observed = True
                        content_type = raw_response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        if content_type != "application/json":
                            raise _ProtocolViolation("catalog_content_type")
                        raw = self._read_bounded(
                            raw_response.iter_bytes(),
                            self._limits.max_catalog_page_bytes,
                            "catalog page byte limit",
                            started_at_ms=deadline_started,
                            duration_ms=self._limits.max_catalog_duration_ms,
                        )
                    payload = _strict_json(raw, detail_code="invalid_catalog_json")
                    page, has_more, last_id = self._parse_catalog_page(
                        payload,
                        seen_models,
                        secret_canaries,
                    )
                    models.extend(page)
                    if len(models) > self._limits.max_catalog_models:
                        raise _ProtocolViolation("catalog_model_limit")
                    if not has_more:
                        break
                    if last_id is None:
                        raise _ProtocolViolation("catalog cursor missing")
                    if last_id in seen_cursors or last_id == cursor:
                        raise _ProtocolViolation("catalog cursor repeated")
                    seen_cursors.add(last_id)
                    cursor = last_id
                else:
                    raise _ProtocolViolation("catalog_page_limit")
        except _ProtocolViolation as exc:
            dispatch_effect = (
                "response_observed"
                if response_observed
                else ("unknown" if request_started else "not_sent")
            )
            failure = ProviderFailure(
                category=exc.category,
                detail_code=exc.detail_code.lower().replace(" ", "_"),
                retry="never",
                dispatch_effect=dispatch_effect,
            )
            applied = self._invalidate_binding(
                binding.binding_id,
                state="catalog_invalid",
                expected_request_epoch=request_epoch,
            )
            catalog_error = (
                failure
                if applied
                else self._superseded_catalog_failure(dispatch_effect)
            )
        except Exception as exc:
            dispatch_effect = (
                "response_observed"
                if response_observed
                else ("unknown" if request_started else "not_sent")
            )
            failure = self._normalize_exception(exc, dispatch_effect=dispatch_effect)
            if failure.category in {"authentication", "credential_missing"}:
                applied = self._invalidate_credential(
                    binding.credential_ref,
                    observed_binding_id=binding.binding_id,
                    state=failure.category,
                    expected_request_epoch=request_epoch,
                )
            else:
                applied = self._invalidate_binding(
                    binding.binding_id,
                    state=failure.category,
                    expected_request_epoch=request_epoch,
                )
            catalog_error = (
                failure
                if applied
                else self._superseded_catalog_failure(dispatch_effect)
            )

        if catalog_error is not None:
            raise CatalogError(catalog_error)

        snapshot = ModelCatalogSnapshot(
            binding_id=binding.binding_id,
            catalog_id="",
            fetched_at_ms=fetched_at,
            max_age_ms=self._catalog_max_age_ms,
            credential_generation=credential_generation,
            binding_generation=binding_generation,
            request_epoch=request_epoch,
            models=tuple(models),
        )
        snapshot = replace(snapshot, catalog_id=self._catalog_digest(snapshot))
        digest = self._catalog_digest(snapshot)
        with self._catalog_lock:
            credential_changed = (
                self._credential_generations.get(binding.credential_ref, 0)
                != credential_generation
                or self._binding_generations.get(binding.binding_id, 0)
                != binding_generation
            )
            request_superseded = self._binding_request_epochs.get(binding.binding_id, 0) != request_epoch
            if credential_changed or request_superseded:
                raise CatalogError(
                    ProviderFailure(
                        category="authentication" if credential_changed else "catalog_stale",
                        detail_code=(
                            "credential_state_changed"
                            if credential_changed
                            else "catalog_request_superseded"
                        ),
                        retry="never",
                        dispatch_effect="response_observed",
                    )
                )
            stale = [
                catalog_id
                for catalog_id, issued in self._issued_catalogs.items()
                if issued.binding_id == binding.binding_id
            ]
            for catalog_id in stale:
                self._issued_catalogs.pop(catalog_id, None)
            self._issued_catalogs[snapshot.catalog_id] = _IssuedCatalog(
                binding_id=binding.binding_id,
                credential_ref=binding.credential_ref,
                digest=digest,
                credential_generation=credential_generation,
                binding_generation=binding_generation,
                request_epoch=request_epoch,
            )
            self._issued_catalogs.move_to_end(snapshot.catalog_id)
            while len(self._issued_catalogs) > 64:
                self._issued_catalogs.popitem(last=False)
            self._binding_current_catalogs[binding.binding_id] = snapshot.catalog_id
            self._connection_states[binding.binding_id] = "catalog_current"
        return snapshot

    def _parse_catalog_page(
        self,
        payload: Any,
        seen_models: set[str],
        secret_canaries: tuple[tuple[str, int], ...],
    ) -> tuple[list[CatalogModel], bool, str | None]:
        if not isinstance(payload, dict):
            raise _ProtocolViolation("catalog_object_required")
        if "has_more" not in payload or type(payload["has_more"]) is not bool:
            raise _ProtocolViolation("catalog has_more missing or invalid")
        data = payload.get("data")
        if not isinstance(data, list):
            raise _ProtocolViolation("catalog_data_invalid")
        if any(not isinstance(item, dict) for item in data):
            raise _ProtocolViolation("catalog_model_invalid")
        first_id = payload.get("first_id")
        last_id = payload.get("last_id")
        if first_id is not None and not isinstance(first_id, str):
            raise _ProtocolViolation("catalog_first_id_invalid")
        if last_id is not None and not isinstance(last_id, str):
            raise _ProtocolViolation("catalog_last_id_invalid")
        if data:
            if first_id != data[0].get("id"):
                raise _ProtocolViolation("catalog first_id mismatch")
            if last_id != data[-1].get("id"):
                raise _ProtocolViolation("catalog last_id mismatch")
        elif first_id is not None or last_id is not None:
            raise _ProtocolViolation("empty_catalog_cursor_invalid")
        if payload["has_more"] and not data:
            raise _ProtocolViolation("has_more requires non-empty page")

        result: list[CatalogModel] = []
        for item in data:
            entry = self._parse_catalog_model(item, secret_canaries)
            if entry.id in seen_models:
                raise _ProtocolViolation("catalog cursor repeated a duplicate model")
            seen_models.add(entry.id)
            result.append(entry)
        return result, payload["has_more"], last_id

    def _parse_catalog_model(
        self,
        item: Any,
        secret_canaries: tuple[tuple[str, int], ...],
    ) -> CatalogModel:
        if not isinstance(item, dict) or item.get("type") != "model":
            raise _ProtocolViolation("catalog_model_invalid")
        model_id = item.get("id")
        display_name = item.get("display_name")
        created_at = item.get("created_at")
        if not isinstance(model_id, str) or not _SAFE_ID.fullmatch(model_id):
            raise _ProtocolViolation("catalog_model_id_invalid")
        if not isinstance(display_name, str) or not display_name or len(display_name.encode("utf-8")) > 512:
            raise _ProtocolViolation("catalog_display_name_invalid")
        if not isinstance(created_at, str) or len(created_at) > 64:
            raise _ProtocolViolation("catalog_created_at_invalid")
        try:
            parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if parsed_created_at.tzinfo is None:
                raise ValueError("timezone required")
        except ValueError as exc:
            raise _ProtocolViolation("catalog_created_at_invalid") from exc
        max_input = _safe_nonnegative_int(item.get("max_input_tokens"), "max_input_tokens", optional=True)
        max_output = _safe_nonnegative_int(item.get("max_tokens"), "max_tokens", optional=True)
        capabilities = item.get("capabilities")
        if capabilities is not None and not isinstance(capabilities, dict):
            raise _ProtocolViolation("catalog_capabilities_invalid")
        capabilities_json = None
        if capabilities is not None:
            try:
                capabilities_json = json.dumps(
                    capabilities, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
                )
            except (TypeError, ValueError, RecursionError) as exc:
                raise _ProtocolViolation("catalog_capabilities_invalid") from exc
            if len(capabilities_json.encode("utf-8")) > 64 * 1024:
                raise _ProtocolViolation("catalog_capabilities_limit")
        for public_value in (model_id, display_name, created_at, capabilities_json or ""):
            if _reflects_secret(public_value, secret_canaries):
                raise _ProtocolViolation("catalog_secret_reflection")
        return CatalogModel(
            id=model_id,
            display_name=display_name,
            created_at=created_at,
            max_input_tokens=max_input,
            max_tokens=max_output,
            _capabilities_json=capabilities_json,
        )

    @staticmethod
    def _catalog_digest(snapshot: ModelCatalogSnapshot) -> str:
        return "claude-catalog-" + _sha256_json(
            {
                "provider": "claude",
                "mode": "api",
                "binding_id": snapshot.binding_id,
                "fetched_at_ms": snapshot.fetched_at_ms,
                "max_age_ms": snapshot.max_age_ms,
                "credential_generation": snapshot.credential_generation,
                "binding_generation": snapshot.binding_generation,
                "request_epoch": snapshot.request_epoch,
                "models": [model.digest_record() for model in snapshot.models],
            }
        )

    def validate_selection(
        self,
        selection: ModelSelection,
        snapshot: ModelCatalogSnapshot,
        binding: ClaudeBinding,
        *,
        required_capabilities: Sequence[str] = (),
    ) -> CatalogModel:
        if not isinstance(selection, ModelSelection) or not isinstance(snapshot, ModelCatalogSnapshot):
            raise TypeError("selection and snapshot types are required")
        if not isinstance(binding, ClaudeBinding):
            raise TypeError("binding must be ClaudeBinding")
        if selection.binding_id != binding.binding_id or snapshot.binding_id != binding.binding_id:
            raise ValueError("Model selection binding is stale or mismatched")
        if selection.catalog_id != snapshot.catalog_id:
            raise ValueError("Model selection catalog is stale or mismatched")
        digest = self._catalog_digest(snapshot)
        if snapshot.catalog_id != digest:
            raise ValueError("Model catalog integrity check failed")
        expected_issue = self._expected_issue(snapshot, binding)
        with self._catalog_lock:
            issued = self._issued_catalogs.get(snapshot.catalog_id)
        if issued != expected_issue:
            raise ValueError("Model catalog was not issued by this live connection")
        observed_at = self._clock_ms()
        if type(observed_at) is not int:
            raise ValueError("Invalid catalog validation clock")
        if observed_at < snapshot.fetched_at_ms or observed_at > snapshot.fetched_at_ms + snapshot.max_age_ms:
            raise ValueError("Model catalog is stale")
        selected = next((model for model in snapshot.models if model.id == selection.model_id), None)
        if selected is None:
            raise ValueError("Selected model is unavailable")
        capabilities = selected.capabilities
        for capability in required_capabilities:
            if not isinstance(capability, str) or not _SAFE_ID.fullmatch(capability):
                raise ValueError("Invalid required capability")
            value = None if capabilities is None else capabilities.get(capability)
            supported = value is True or (isinstance(value, dict) and value.get("supported") is True)
            if not supported:
                raise ValueError("A required model capability is unknown or unsupported")
        if selection.effort is not None:
            if selection.effort not in {"low", "medium", "high", "xhigh", "max"}:
                raise ValueError("Requested effort is invalid")
            effort = None if capabilities is None else capabilities.get("effort")
            level = effort.get(selection.effort) if isinstance(effort, dict) else None
            if not (
                isinstance(effort, dict)
                and effort.get("supported") is True
                and isinstance(level, dict)
                and level.get("supported") is True
            ):
                raise ValueError("Requested effort capability is unknown or unsupported")
        if selection.thinking_type is not None:
            if selection.thinking_type not in {"adaptive", "enabled"}:
                raise ValueError("Requested thinking type is invalid")
            thinking = None if capabilities is None else capabilities.get("thinking")
            types = thinking.get("types") if isinstance(thinking, dict) else None
            selected_type = types.get(selection.thinking_type) if isinstance(types, dict) else None
            if not (
                isinstance(thinking, dict)
                and thinking.get("supported") is True
                and isinstance(selected_type, dict)
                and selected_type.get("supported") is True
            ):
                raise ValueError("Requested thinking capability is unknown or unsupported")
        credential_failure: ProviderFailure | None = None
        try:
            # Rotation/deletion creates a new ref and removes this item.  An
            # issued snapshot cannot outlive that exact credential binding.
            with self._vault.open(binding.credential_ref):
                pass
        except CredentialError as exc:
            if isinstance(exc, CredentialNotFound):
                self._invalidate_credential(
                    binding.credential_ref,
                    observed_binding_id=binding.binding_id,
                    state="credential_missing",
                )
            else:
                with self._catalog_lock:
                    self._connection_states[binding.binding_id] = exc.state
            credential_failure = self._normalize_exception(exc, dispatch_effect="not_sent")
        if credential_failure is not None:
            raise CatalogError(credential_failure)
        with self._catalog_lock:
            if self._issued_catalogs.get(snapshot.catalog_id) != expected_issue:
                raise ValueError("Model catalog was invalidated during validation")
            if (
                self._credential_generations.get(binding.credential_ref, 0)
                != snapshot.credential_generation
                or self._binding_generations.get(binding.binding_id, 0)
                != snapshot.binding_generation
            ):
                raise ValueError("Model catalog authority changed during validation")
        return selected

    def stream(
        self,
        turn: MessageTurn,
        snapshot: ModelCatalogSnapshot,
        binding: ClaudeBinding,
        *,
        explicit_action: bool,
        cancelled: Callable[[], bool] | None = None,
    ) -> Iterator[ProviderStarted | TextDelta | ToolRequested | UsageObserved | ProviderTerminal]:
        if explicit_action is not True:
            raise ValueError("Claude generation requires an explicit API action")
        deadline_started = self._monotonic()
        prepared = self._prepare_turn(turn)
        selected = self.validate_selection(
            turn.selection,
            snapshot,
            binding,
            required_capabilities=prepared.required_capabilities,
        )
        if selected.max_tokens is None:
            raise ValueError("Selected model output limit is unknown")
        if turn.max_tokens > selected.max_tokens:
            raise ValueError("Requested max_tokens exceeds the selected model limit")
        cancel_check = cancelled or (lambda: False)
        if not callable(cancel_check):
            raise TypeError("cancelled must be callable")
        return self._stream(
            turn,
            snapshot,
            binding,
            prepared,
            cancel_check,
            deadline_started,
        )

    def _prepare_turn(self, turn: MessageTurn) -> _PreparedTurn:
        if not _SAFE_ID.fullmatch(turn.call_id) or not _SAFE_ID.fullmatch(turn.agent_id):
            raise ValueError("Invalid call or agent identifier")
        if type(turn.max_tokens) is not int or not (1 <= turn.max_tokens <= 1_000_000):
            raise ValueError("max_tokens is invalid")
        if not isinstance(turn.system, str) or len(turn.system.encode("utf-8")) > self._limits.max_request_bytes:
            raise ValueError("System instruction is invalid or too large")
        tools, names = self._prepare_tools(turn.tools)
        messages, required_capabilities, historical_tool_ids = self._prepare_messages(
            turn.messages,
            names,
        )
        if turn.selection.thinking_type is not None or turn.thinking_budget_tokens is not None:
            # Thinking blocks must be retained byte-for-byte across turns.  This
            # initial adapter does not yet expose such blocks, so it must not
            # advertise a setting it cannot preserve.
            raise ValueError("Thinking mode is not supported by this bounded adapter")

        body_for_limit = {
            "model": turn.selection.model_id,
            "system": turn.system,
            "messages": messages,
            "tools": tools,
            "max_tokens": turn.max_tokens,
        }
        if turn.selection.effort is not None:
            body_for_limit["output_config"] = {"effort": turn.selection.effort}
        serialization_invalid = False
        encoded = b""
        try:
            encoded = json.dumps(
                body_for_limit, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError):
            serialization_invalid = True
        if serialization_invalid:
            # Do not retain the rejected request tree through an exception
            # cause/context.  The host's own structured validation record is
            # the only public diagnostic at this boundary.
            body_for_limit = {}
            messages = []
            tools = []
            names = set()
            required_capabilities = set()
            historical_tool_ids = set()
            turn = None  # type: ignore[assignment]
            raise ValueError("Message request must contain finite JSON values")
        if len(encoded) > self._limits.max_request_bytes:
            raise ValueError("Message request is too large")
        # Round-trip breaks references to mutable caller-owned containers.
        frozen = json.loads(encoded)
        kwargs: dict[str, Any] = {
            "model": frozen["model"],
            "system": frozen["system"],
            "messages": frozen["messages"],
            "max_tokens": frozen["max_tokens"],
            "stream": True,
        }
        if tools:
            kwargs["tools"] = frozen["tools"]
        if "output_config" in frozen:
            kwargs["output_config"] = frozen["output_config"]
        return _PreparedTurn(
            kwargs=MappingProxyType(kwargs),
            tool_names=frozenset(names),
            historical_tool_ids=frozenset(historical_tool_ids),
            required_capabilities=tuple(sorted(required_capabilities)),
        )

    @staticmethod
    def _prepare_tools(raw_tools: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], set[str]]:
        if not isinstance(raw_tools, (list, tuple)) or len(raw_tools) > 256:
            raise ValueError("Tools are invalid")
        tools: list[dict[str, Any]] = []
        names: set[str] = set()
        for tool in raw_tools:
            if not isinstance(tool, Mapping) or set(tool) != {"name", "description", "input_schema"}:
                raise ValueError("Only declared client-tool fields are allowed")
            name = tool["name"]
            if not isinstance(name, str) or not _TOOL_NAME.fullmatch(name) or name in names:
                raise ValueError("Tool name is invalid or duplicated")
            if not isinstance(tool["description"], str) or len(tool["description"].encode("utf-8")) > 4096:
                raise ValueError("Tool description is invalid")
            if not isinstance(tool["input_schema"], Mapping):
                raise ValueError("Tool input_schema is invalid")
            names.add(name)
            tools.append(
                {
                    "name": name,
                    "description": tool["description"],
                    "input_schema": dict(tool["input_schema"]),
                }
            )
        return tools, names

    def _prepare_source(self, source: Any, *, kind: str) -> dict[str, str]:
        if not isinstance(source, Mapping) or set(source) != {"type", "media_type", "data"}:
            raise ValueError(f"{kind.capitalize()} source fields are invalid")
        if source.get("type") != "base64":
            raise ValueError(f"{kind.capitalize()} source type is unsupported")
        media_type = source.get("media_type")
        allowed_media = (
            {"image/jpeg", "image/png", "image/gif", "image/webp"}
            if kind == "image"
            else {"application/pdf"}
        )
        if media_type not in allowed_media:
            raise ValueError(f"{kind.capitalize()} source media type is unsupported")
        data = source.get("data")
        if not isinstance(data, str):
            raise ValueError(f"{kind.capitalize()} source data is invalid")
        encoded = b""
        decoded = b""
        invalid_data = False
        try:
            encoded = data.encode("ascii", errors="strict")
            if not encoded or len(encoded) > self._limits.max_request_bytes:
                raise ValueError
            decoded = base64.b64decode(encoded, validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError):
            invalid_data = True
        if invalid_data:
            data = ""
            encoded = b""
            decoded = b""
            raise ValueError(f"{kind.capitalize()} source data is invalid")
        if not decoded or len(decoded) > self._limits.max_request_bytes:
            data = ""
            encoded = b""
            decoded = b""
            raise ValueError(f"{kind.capitalize()} source data is invalid")
        return {"type": "base64", "media_type": media_type, "data": data}

    def _prepare_tool_result_content(
        self,
        content: Any,
        required_capabilities: set[str],
    ) -> str | list[dict[str, Any]]:
        if isinstance(content, str):
            return content
        if not isinstance(content, (list, tuple)) or not content:
            raise ValueError("tool_result content is invalid")
        result: list[dict[str, Any]] = []
        for raw_part in content:
            if not isinstance(raw_part, Mapping):
                raise ValueError("tool_result content block is invalid")
            part = dict(raw_part)
            kind = part.get("type")
            if kind == "text":
                if set(part) != {"type", "text"} or not isinstance(part.get("text"), str):
                    raise ValueError("tool_result text block is invalid")
                result.append({"type": "text", "text": part["text"]})
            elif kind in {"image", "document"}:
                if set(part) != {"type", "source"}:
                    raise ValueError(f"tool_result {kind} block is invalid")
                result.append(
                    {
                        "type": kind,
                        "source": self._prepare_source(part.get("source"), kind=kind),
                    }
                )
                required_capabilities.add("image_input" if kind == "image" else "pdf_input")
            else:
                raise ValueError("Unsupported or server-managed tool_result content block")
        return result

    def _prepare_messages(
        self,
        raw_messages: Sequence[Mapping[str, Any]],
        declared_tools: set[str],
    ) -> tuple[list[dict[str, Any]], set[str], set[str]]:
        if not isinstance(raw_messages, (list, tuple)) or not raw_messages or len(raw_messages) > 1000:
            raise ValueError("Messages are invalid")
        messages: list[dict[str, Any]] = []
        required_capabilities: set[str] = set()
        pending_tool_ids: set[str] = set()
        historical_tool_ids: set[str] = set()
        for message in raw_messages:
            if not isinstance(message, Mapping) or set(message) != {"role", "content"}:
                raise ValueError("Message fields are invalid")
            role = message["role"]
            content = message["content"]
            if role not in {"user", "assistant"}:
                raise ValueError("Message role is invalid")
            if isinstance(content, str):
                if pending_tool_ids:
                    raise ValueError("Pending tool results are missing")
                messages.append({"role": role, "content": content})
                continue
            if not isinstance(content, (list, tuple)) or not content:
                raise ValueError("Message content blocks are invalid")

            blocks: list[dict[str, Any]] = []
            result_ids: set[str] = set()
            new_tool_ids: set[str] = set()
            saw_non_result = False
            for raw_block in content:
                if not isinstance(raw_block, Mapping):
                    raise ValueError("Message content block is invalid")
                block = dict(raw_block)
                kind = block.get("type")
                if kind == "tool_result":
                    if role != "user" or saw_non_result or not pending_tool_ids:
                        raise ValueError("Orphan or misordered tool_result is not allowed")
                    if "content" not in block or not set(block).issubset(
                        {"type", "tool_use_id", "content", "is_error"}
                    ):
                        raise ValueError("tool_result fields are invalid")
                    tool_id = block.get("tool_use_id")
                    if not isinstance(tool_id, str) or tool_id not in pending_tool_ids or tool_id in result_ids:
                        raise ValueError("tool_result ID is missing, duplicated, or mismatched")
                    if "is_error" in block and type(block["is_error"]) is not bool:
                        raise ValueError("tool_result is_error is invalid")
                    result_ids.add(tool_id)
                    normalized = {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": self._prepare_tool_result_content(
                            block["content"],
                            required_capabilities,
                        ),
                    }
                    if "is_error" in block:
                        normalized["is_error"] = block["is_error"]
                    block = normalized
                else:
                    saw_non_result = True
                    if kind == "text":
                        if set(block) != {"type", "text"} or not isinstance(block.get("text"), str):
                            raise ValueError("Text content block is invalid")
                    elif kind == "tool_use":
                        if role != "assistant" or set(block) != {"type", "id", "name", "input"}:
                            raise ValueError("Historical tool_use block is invalid")
                        tool_id = block.get("id")
                        tool_name = block.get("name")
                        if (
                            not isinstance(tool_id, str)
                            or not _SAFE_ID.fullmatch(tool_id)
                            or tool_id in new_tool_ids
                            or tool_id in historical_tool_ids
                            or tool_name not in declared_tools
                            or not isinstance(block.get("input"), Mapping)
                        ):
                            raise ValueError("Historical tool_use identity is invalid or duplicated")
                        new_tool_ids.add(tool_id)
                        historical_tool_ids.add(tool_id)
                        block = {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": tool_name,
                            "input": dict(block["input"]),
                        }
                    elif kind == "image":
                        if role != "user" or set(block) != {"type", "source"}:
                            raise ValueError("Image content block is invalid")
                        block = {
                            "type": "image",
                            "source": self._prepare_source(block.get("source"), kind="image"),
                        }
                        required_capabilities.add("image_input")
                    elif kind == "document":
                        if role != "user" or set(block) != {"type", "source"}:
                            raise ValueError("Document content block is invalid")
                        block = {
                            "type": "document",
                            "source": self._prepare_source(block.get("source"), kind="document"),
                        }
                        required_capabilities.add("pdf_input")
                    else:
                        raise ValueError("Unsupported or server-managed content block")
                blocks.append(block)

            if pending_tool_ids:
                if role != "user" or result_ids != pending_tool_ids:
                    raise ValueError("Tool results must exactly answer the preceding tool_use blocks")
                pending_tool_ids.clear()
            elif result_ids:
                raise ValueError("Orphan tool_result is not allowed")
            if new_tool_ids:
                if role != "assistant":
                    raise ValueError("tool_use must be in an assistant message")
                pending_tool_ids = new_tool_ids
            messages.append({"role": role, "content": blocks})
        if pending_tool_ids:
            raise ValueError("Pending tool results are missing")
        return messages, required_capabilities, historical_tool_ids

    @contextmanager
    def _authorized_message_response(
        self,
        *,
        client: Any,
        kwargs: Mapping[str, Any],
        snapshot: ModelCatalogSnapshot,
        binding: ClaudeBinding,
        cancelled: Callable[[], bool],
        deadline_started_ms: int,
        mark_request_started: Callable[[], None],
    ) -> Iterator[Any]:
        # Constructing this wrapper is local; the SDK performs the HTTP request
        # in ``__enter__``.  Serialize that precise boundary with catalog
        # invalidation so a previously observed 401/403 cannot race a new send.
        with self._catalog_lock:
            self._assert_catalog_authority_locked(snapshot, binding)
            self._check_deadline(
                deadline_started_ms,
                self._limits.max_stream_duration_ms,
                "absolute_deadline_exceeded",
            )
            try:
                is_cancelled = cancelled()
            except Exception:
                raise _ProtocolViolation("cancel_check_failed") from None
            if is_cancelled:
                raise _CancellationObserved()
            request_kwargs = dict(kwargs)
            request_kwargs["timeout"] = min(
                self._timeout_seconds,
                self._remaining_timeout_seconds(
                    deadline_started_ms,
                    self._limits.max_stream_duration_ms,
                    "absolute_deadline_exceeded",
                ),
            )
            manager = client.messages.with_streaming_response.create(**request_kwargs)
            mark_request_started()
            raw_response = manager.__enter__()
        try:
            yield raw_response
        except BaseException as exc:
            # The SDK response wrapper may close resources here, but it must
            # never suppress DeepTwin cancellation, deadline, or protocol
            # control signals.
            manager.__exit__(type(exc), exc, exc.__traceback__)
            raise
        else:
            manager.__exit__(None, None, None)

    @staticmethod
    def _safe_text_piece(
        block: _Block,
        text: str,
        secret_canaries: tuple[tuple[str, int], ...],
        *,
        final: bool = False,
    ) -> str:
        combined = block.safe_text_tail + text
        if _reflects_secret(combined, secret_canaries):
            raise _ProtocolViolation("provider_secret_reflection")
        keep = 0 if final else min(len(combined), _secret_overlap_width(secret_canaries))
        if keep:
            public, block.safe_text_tail = combined[:-keep], combined[-keep:]
        else:
            public, block.safe_text_tail = combined, ""
        return public

    def _stream(
        self,
        turn: MessageTurn,
        snapshot: ModelCatalogSnapshot,
        binding: ClaudeBinding,
        prepared: _PreparedTurn,
        cancelled: Callable[[], bool],
        deadline_started: int,
    ) -> Iterator[ProviderStarted | TextDelta | ToolRequested | UsageObserved | ProviderTerminal]:
        try:
            if cancelled():
                yield self._cancel_terminal(turn.call_id, sent=False)
                return
        except Exception:
            failure = ProviderFailure("adapter_error", "cancel_or_clock_check_failed", "never", "not_sent")
            yield ProviderTerminal(turn.call_id, "failed", None, "unknown", failure)
            return

        response_observed = False
        request_started = False
        request_id: str | None = None
        saw_start = False
        saw_delta = False
        saw_stop = False
        stop_reason: str | None = None
        active: _Block | None = None
        next_index = 0
        stopped_indexes: set[int] = set()
        seen_tool_ids: set[str] = set(prepared.historical_tool_ids)
        buffered_tools: list[ToolRequested] = []
        input_tokens = 0
        start_output_tokens = 0
        output_tokens = 0
        cache_creation = 0
        cache_read = 0
        text_bytes = 0

        try:
            with self._client(
                binding,
                deadline_started_ms=deadline_started,
                operation_duration_ms=self._limits.max_stream_duration_ms,
                deadline_detail="absolute_deadline_exceeded",
            ) as (client, secret_canaries):
                kwargs = dict(prepared.kwargs)
                if binding.workspace_id is not None:
                    kwargs["workspace_id"] = binding.workspace_id
                request_projection = json.dumps(
                    kwargs,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                if _reflects_secret(request_projection, secret_canaries):
                    raise _ProtocolViolation("request_secret_reflection")

                def mark_request_started() -> None:
                    nonlocal request_started
                    request_started = True

                with self._authorized_message_response(
                    client=client,
                    kwargs=kwargs,
                    snapshot=snapshot,
                    binding=binding,
                    cancelled=cancelled,
                    deadline_started_ms=deadline_started,
                    mark_request_started=mark_request_started,
                ) as raw_response:
                    response_observed = True
                    request_id = _request_id(raw_response.headers.get("request-id"))
                    content_type = raw_response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type != "text/event-stream":
                        raise _ProtocolViolation("stream_content_type")
                    for event_name, payload in self._iter_sse(
                        raw_response.iter_bytes(),
                        cancelled=cancelled,
                        deadline_started_ms=deadline_started,
                    ):
                        if cancelled():
                            raise _CancellationObserved()
                        if saw_stop:
                            raise _ProtocolViolation("event_after_message_stop")
                        if event_name == "ping":
                            continue
                        if event_name == "error":
                            raise _ObservedProviderFailure(
                                self._classify_stream_error(payload, raw_response.headers, request_id)
                            )
                        if event_name not in {
                            "message_start",
                            "content_block_start",
                            "content_block_delta",
                            "content_block_stop",
                            "message_delta",
                            "message_stop",
                        }:
                            raise _ProtocolViolation("unknown_event")
                        if not isinstance(payload, dict) or payload.get("type") != event_name:
                            raise _ProtocolViolation("event_type_mismatch")

                        if event_name == "message_start":
                            if saw_start or active is not None:
                                raise _ProtocolViolation("duplicate_message_start")
                            message = payload.get("message")
                            if not isinstance(message, dict):
                                raise _ProtocolViolation("invalid_message_start")
                            message_id = message.get("id")
                            observed_model = message.get("model")
                            if not isinstance(message_id, str) or not _SAFE_ID.fullmatch(message_id):
                                raise _ProtocolViolation("invalid_provider_message_id")
                            if not isinstance(observed_model, str) or _reflects_secret(
                                message_id,
                                secret_canaries,
                            ) or _reflects_secret(observed_model, secret_canaries):
                                raise _ProtocolViolation("provider_secret_reflection")
                            if observed_model != turn.selection.model_id:
                                raise _ProtocolViolation("observed_model_mismatch", category="model_mismatch")
                            if message.get("role") != "assistant" or message.get("type") != "message":
                                raise _ProtocolViolation("invalid_message_identity")
                            if message.get("content") not in ([], None) or message.get("stop_reason") is not None:
                                raise _ProtocolViolation("invalid_message_start_state")
                            usage = message.get("usage")
                            if not isinstance(usage, dict):
                                raise _ProtocolViolation("invalid_start_usage")
                            if usage.get("server_tool_use") not in (None, {}, {"web_search_requests": 0}):
                                raise _ProtocolViolation("server_tool_usage_not_allowed", category="profile_mismatch")
                            input_tokens = int(_safe_nonnegative_int(usage.get("input_tokens"), "input_tokens"))
                            start_output_tokens = int(
                                _safe_nonnegative_int(usage.get("output_tokens"), "output_tokens")
                            )
                            output_tokens = start_output_tokens
                            cache_creation = int(
                                _safe_nonnegative_int(
                                    usage.get("cache_creation_input_tokens", 0),
                                    "cache_creation_input_tokens",
                                )
                            )
                            cache_read = int(
                                _safe_nonnegative_int(
                                    usage.get("cache_read_input_tokens", 0),
                                    "cache_read_input_tokens",
                                )
                            )
                            saw_start = True
                            yield ProviderStarted(
                                call_id=turn.call_id,
                                agent_id=turn.agent_id,
                                provider_message_id=message_id,
                                requested_model=turn.selection.model_id,
                                observed_model=observed_model,
                                request_id=request_id,
                                requested_effort=turn.selection.effort,
                                # The current Messages stream does not report an
                                # applied effort level.  Never copy requested into
                                # observed merely to make the fields match.
                                observed_effort=None,
                            )
                            continue

                        if not saw_start:
                            raise _ProtocolViolation("event_before_message_start")
                        if event_name == "content_block_start":
                            if active is not None or saw_delta:
                                raise _ProtocolViolation("overlapping_or_late_content_block")
                            index = payload.get("index")
                            if type(index) is not int or index != next_index or index >= self._limits.max_blocks:
                                raise _ProtocolViolation("invalid_content_block_index")
                            block = payload.get("content_block")
                            if not isinstance(block, dict):
                                raise _ProtocolViolation("invalid_content_block")
                            kind = block.get("type")
                            if kind == "text":
                                initial = block.get("text")
                                if not isinstance(initial, str):
                                    raise _ProtocolViolation("invalid_text_block")
                                active = _Block(index=index, kind="text")
                                if initial:
                                    text_bytes += len(initial.encode("utf-8"))
                                    if text_bytes > self._limits.max_text_bytes:
                                        raise _ProtocolViolation("text_limit")
                                    public = self._safe_text_piece(active, initial, secret_canaries)
                                    if public:
                                        yield TextDelta(turn.call_id, index, public)
                            elif kind == "tool_use":
                                tool_id = block.get("id")
                                tool_name = block.get("name")
                                if not isinstance(tool_id, str) or not _SAFE_ID.fullmatch(tool_id) or tool_id in seen_tool_ids:
                                    raise _ProtocolViolation("invalid_or_duplicate_tool_id")
                                if tool_name not in prepared.tool_names:
                                    raise _ProtocolViolation("undeclared_tool")
                                if _reflects_secret(tool_id, secret_canaries) or _reflects_secret(
                                    tool_name,
                                    secret_canaries,
                                ):
                                    raise _ProtocolViolation("provider_secret_reflection")
                                if block.get("input") != {}:
                                    raise _ProtocolViolation("nonempty_tool_start_input")
                                seen_tool_ids.add(tool_id)
                                active = _Block(index=index, kind="tool_use", tool_use_id=tool_id, tool_name=tool_name)
                            elif isinstance(kind, str) and (
                                "server_tool" in kind or "web_" in kind or "code_execution" in kind or kind == "container_upload"
                            ):
                                raise _ProtocolViolation("server_tool_not_allowed", category="profile_mismatch")
                            else:
                                raise _ProtocolViolation("unsupported_content_block")
                            next_index += 1
                            continue

                        if event_name == "content_block_delta":
                            index = payload.get("index")
                            if active is None or index != active.index or index in stopped_indexes:
                                raise _ProtocolViolation("delta_for_inactive_block")
                            delta = payload.get("delta")
                            if not isinstance(delta, dict):
                                raise _ProtocolViolation("invalid_content_delta")
                            if active.kind == "text" and delta.get("type") == "text_delta":
                                text = delta.get("text")
                                if not isinstance(text, str):
                                    raise _ProtocolViolation("invalid_text_delta")
                                text_bytes += len(text.encode("utf-8"))
                                if text_bytes > self._limits.max_text_bytes:
                                    raise _ProtocolViolation("text_limit")
                                if text:
                                    public = self._safe_text_piece(active, text, secret_canaries)
                                    if public:
                                        yield TextDelta(turn.call_id, active.index, public)
                            elif active.kind == "tool_use" and delta.get("type") == "input_json_delta":
                                partial = delta.get("partial_json")
                                if not isinstance(partial, str):
                                    raise _ProtocolViolation("invalid_tool_json_delta")
                                if len((active.partial_json + partial).encode("utf-8")) > self._limits.max_tool_json_bytes:
                                    raise _ProtocolViolation("tool_json_limit")
                                active.partial_json += partial
                            else:
                                raise _ProtocolViolation("content_delta_type_mismatch")
                            continue

                        if event_name == "content_block_stop":
                            index = payload.get("index")
                            if active is None or index != active.index or index in stopped_indexes:
                                raise _ProtocolViolation("stop_for_inactive_block")
                            if active.kind == "text":
                                public = self._safe_text_piece(active, "", secret_canaries, final=True)
                                if public:
                                    yield TextDelta(turn.call_id, active.index, public)
                            elif active.kind == "tool_use":
                                tool_input = _strict_json(active.partial_json, detail_code="invalid_tool_json")
                                if not isinstance(tool_input, dict):
                                    raise _ProtocolViolation("tool_json_must_be_object")
                                input_json = json.dumps(
                                    tool_input,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                    allow_nan=False,
                                )
                                if _reflects_secret(input_json, secret_canaries):
                                    raise _ProtocolViolation("provider_secret_reflection")
                                buffered_tools.append(
                                    ToolRequested(
                                        call_id=turn.call_id,
                                        index=active.index,
                                        tool_use_id=active.tool_use_id or "",
                                        name=active.tool_name or "",
                                        _input_json=input_json,
                                    )
                                )
                            stopped_indexes.add(active.index)
                            active = None
                            continue

                        if event_name == "message_delta":
                            if saw_delta or active is not None:
                                raise _ProtocolViolation("invalid_message_delta_order")
                            delta = payload.get("delta")
                            usage = payload.get("usage")
                            if not isinstance(delta, dict) or not isinstance(usage, dict):
                                raise _ProtocolViolation("invalid_message_delta")
                            reason = delta.get("stop_reason")
                            if reason not in _STOP_REASONS:
                                raise _ProtocolViolation("unknown_stop_reason")
                            if usage.get("server_tool_use") not in (None, {}, {"web_search_requests": 0}):
                                raise _ProtocolViolation("server_tool_usage_not_allowed", category="profile_mismatch")
                            final_output_tokens = int(
                                _safe_nonnegative_int(usage.get("output_tokens"), "output_tokens")
                            )
                            if final_output_tokens < start_output_tokens:
                                raise _ProtocolViolation("usage_decreased")
                            output_tokens = final_output_tokens
                            if usage.get("input_tokens") is not None:
                                final_input_tokens = int(
                                    _safe_nonnegative_int(usage.get("input_tokens"), "input_tokens")
                                )
                                if final_input_tokens < input_tokens:
                                    raise _ProtocolViolation("usage_decreased")
                                input_tokens = final_input_tokens
                            if usage.get("cache_creation_input_tokens") is not None:
                                final_cache_creation = int(
                                    _safe_nonnegative_int(
                                        usage.get("cache_creation_input_tokens"), "cache_creation_input_tokens"
                                    )
                                )
                                if final_cache_creation < cache_creation:
                                    raise _ProtocolViolation("usage_decreased")
                                cache_creation = final_cache_creation
                            if usage.get("cache_read_input_tokens") is not None:
                                final_cache_read = int(
                                    _safe_nonnegative_int(
                                        usage.get("cache_read_input_tokens"), "cache_read_input_tokens"
                                    )
                                )
                                if final_cache_read < cache_read:
                                    raise _ProtocolViolation("usage_decreased")
                                cache_read = final_cache_read
                            stop_reason = reason
                            saw_delta = True
                            continue

                        if event_name == "message_stop":
                            if not saw_delta or active is not None:
                                raise _ProtocolViolation("invalid_message_stop_order")
                            saw_stop = True
                            continue

                        raise _ProtocolViolation("unknown_event")

            if not saw_stop:
                raise _ProtocolViolation("missing_message_stop")
            if stop_reason == "tool_use" and not buffered_tools:
                raise _ProtocolViolation("tool_stop_without_tool")
            if stop_reason != "tool_use" and buffered_tools:
                raise _ProtocolViolation("tool_block_without_tool_stop")
            for requested in buffered_tools:
                yield requested
            yield UsageObserved(turn.call_id, input_tokens, output_tokens, cache_creation, cache_read)
            yield self._success_terminal(turn.call_id, stop_reason)
        except _ObservedProviderFailure as exc:
            if exc.failure.category == "authentication":
                self._invalidate_credential(
                    binding.credential_ref,
                    observed_binding_id=binding.binding_id,
                    state="authentication",
                    expected_catalog_id=snapshot.catalog_id,
                )
            elif exc.failure.category == "permission":
                self._invalidate_binding(
                    binding.binding_id,
                    state="permission",
                    expected_catalog_id=snapshot.catalog_id,
                )
            yield ProviderTerminal(turn.call_id, "failed", stop_reason, "unknown", exc.failure)
        except _CancellationObserved:
            yield self._cancel_terminal(turn.call_id, sent=request_started, request_id=request_id)
        except _ProtocolViolation as exc:
            failure = ProviderFailure(
                category=exc.category,
                detail_code=exc.detail_code.lower().replace(" ", "_"),
                retry="never",
                dispatch_effect="unknown" if response_observed else "not_sent",
                request_id=request_id,
            )
            yield ProviderTerminal(turn.call_id, "failed", stop_reason, "unknown", failure)
        except Exception as exc:
            if self._exception_contains(exc, _CancellationObserved):
                failure = ProviderFailure(
                    "cancelled",
                    "cancel_cleanup_failed",
                    "never",
                    "unknown",
                    request_id=request_id,
                )
                yield ProviderTerminal(turn.call_id, "cancel_requested", stop_reason, "unknown", failure)
            else:
                failure = self._normalize_exception(
                    exc,
                    dispatch_effect=(
                        "response_observed"
                        if response_observed
                        else ("unknown" if request_started else "not_sent")
                    ),
                    request_id=request_id,
                )
                if failure.category in {"authentication", "credential_missing"}:
                    self._invalidate_credential(
                        binding.credential_ref,
                        observed_binding_id=binding.binding_id,
                        state=failure.category,
                        expected_catalog_id=snapshot.catalog_id,
                    )
                elif failure.category == "permission":
                    self._invalidate_binding(
                        binding.binding_id,
                        state="permission",
                        expected_catalog_id=snapshot.catalog_id,
                    )
                elif failure.category.startswith("credential_"):
                    with self._catalog_lock:
                        self._connection_states[binding.binding_id] = failure.category
                yield ProviderTerminal(turn.call_id, "failed", stop_reason, "unknown", failure)

    @staticmethod
    def _exception_contains(exc: BaseException, expected: type[BaseException]) -> bool:
        seen: set[int] = set()
        current: BaseException | None = exc
        while current is not None and id(current) not in seen:
            if isinstance(current, expected):
                return True
            seen.add(id(current))
            current = current.__cause__ or current.__context__
        return False

    @staticmethod
    def _retry_after_ms(headers: Mapping[str, str]) -> int | None:
        raw = headers.get("retry-after")
        try:
            seconds = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None
        if seconds is None or not math.isfinite(seconds) or not 0 <= seconds <= 86_400:
            return None
        return int(seconds * 1000)

    @classmethod
    def _classify_stream_error(
        cls,
        payload: Any,
        headers: Mapping[str, str],
        request_id: str | None,
    ) -> ProviderFailure:
        error = payload.get("error") if isinstance(payload, dict) else None
        error_type = error.get("type") if isinstance(error, dict) else None
        if not isinstance(error_type, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,99}", error_type):
            error_type = "unknown"
        spend_codes = {
            "billing_error",
            "credit_balance_too_low",
            "usage_limit_reached",
            "monthly_limit_exceeded",
            "spend_limit_exceeded",
        }
        if error_type == "authentication_error":
            category, detail, retry = "authentication", "stream_authentication", "never"
        elif error_type == "permission_error":
            category, detail, retry = "permission", "stream_permission", "never"
        elif error_type in spend_codes:
            category, detail, retry = "spend_cap", "stream_spend_cap", "never"
        elif error_type == "rate_limit_error":
            category, detail, retry = "rate_limit", "stream_rate_limit", "after_delay"
        elif error_type in {"overloaded_error", "api_error"}:
            category, detail, retry = "provider_unavailable", "stream_provider_unavailable", "controlled"
        else:
            category, detail, retry = "stream_error", "unknown_stream_error", "never"
        return ProviderFailure(
            category=category,
            detail_code=detail,
            retry=retry,
            dispatch_effect="response_observed",
            retry_after_ms=cls._retry_after_ms(headers) if retry == "after_delay" else None,
            request_id=request_id,
        )

    def _stream_control(
        self,
        *,
        cancelled: Callable[[], bool],
        deadline_started_ms: int,
    ) -> None:
        self._check_deadline(
            deadline_started_ms,
            self._limits.max_stream_duration_ms,
            "absolute_deadline_exceeded",
        )
        try:
            is_cancelled = cancelled()
        except Exception as exc:
            raise _ProtocolViolation("cancel_check_failed") from exc
        if is_cancelled:
            raise _CancellationObserved()

    def _iter_sse(
        self,
        chunks: Iterator[bytes],
        *,
        cancelled: Callable[[], bool],
        deadline_started_ms: int,
    ) -> Iterator[tuple[str, Any]]:
        buffer = bytearray()
        fields: list[bytes] = []
        total = 0
        event_bytes = 0
        event_count = 0
        iterator = iter(chunks)
        while True:
            self._stream_control(cancelled=cancelled, deadline_started_ms=deadline_started_ms)
            try:
                chunk = next(iterator)
            except StopIteration:
                break
            self._stream_control(cancelled=cancelled, deadline_started_ms=deadline_started_ms)
            total += len(chunk)
            if total > self._limits.max_total_stream_bytes:
                raise _ProtocolViolation("stream_limit")
            buffer.extend(chunk)
            while True:
                self._stream_control(cancelled=cancelled, deadline_started_ms=deadline_started_ms)
                newline = buffer.find(b"\n")
                if newline < 0:
                    if event_bytes + len(buffer) > self._limits.max_event_bytes:
                        raise _ProtocolViolation("event_limit")
                    break
                line = bytes(buffer[:newline])
                del buffer[: newline + 1]
                if line.endswith(b"\r"):
                    line = line[:-1]
                event_bytes += newline + 1
                if event_bytes > self._limits.max_event_bytes:
                    raise _ProtocolViolation("event_limit")
                if line:
                    fields.append(line)
                    continue
                if not fields:
                    event_bytes = 0
                    continue
                event_count += 1
                if event_count > self._limits.max_events:
                    raise _ProtocolViolation("event_count_limit")
                yield self._parse_sse_fields(fields)
                fields = []
                event_bytes = 0
        if buffer or fields:
            raise _ProtocolViolation("incomplete_sse")

    @staticmethod
    def _parse_sse_fields(lines: list[bytes]) -> tuple[str, Any]:
        event_name: str | None = None
        data_lines: list[bytes] = []
        for line in lines:
            if line.startswith(b":"):
                continue
            if b":" in line:
                field, value = line.split(b":", 1)
                if value.startswith(b" "):
                    value = value[1:]
            else:
                field, value = line, b""
            if field == b"event":
                if event_name is not None:
                    raise _ProtocolViolation("duplicate_event_field")
                try:
                    event_name = value.decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    raise _ProtocolViolation("invalid_utf8") from exc
            elif field == b"data":
                data_lines.append(value)
            else:
                raise _ProtocolViolation("unknown_sse_field")
        if event_name is None or not _SAFE_ID.fullmatch(event_name):
            raise _ProtocolViolation("invalid_event_name")
        raw_data = b"\n".join(data_lines)
        try:
            raw_data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise _ProtocolViolation("invalid_utf8") from exc
        if event_name == "ping" and not raw_data:
            return event_name, {"type": "ping"}
        return event_name, _strict_json(raw_data, detail_code="invalid_event_json")

    @staticmethod
    def _success_terminal(call_id: str, reason: str | None) -> ProviderTerminal:
        if reason in {"end_turn", "stop_sequence"}:
            return ProviderTerminal(call_id, "completed", reason, "known")
        if reason == "tool_use":
            return ProviderTerminal(call_id, "tool_required", reason, "known")
        if reason in {"max_tokens", "model_context_window_exceeded"}:
            return ProviderTerminal(call_id, "incomplete", reason, "known")
        if reason == "refusal":
            return ProviderTerminal(call_id, "refused", reason, "known")
        if reason == "pause_turn":
            failure = ProviderFailure(
                category="profile_mismatch",
                detail_code="server_continuation_not_allowed",
                retry="never",
                dispatch_effect="response_observed",
            )
            return ProviderTerminal(call_id, "failed", reason, "known", failure)
        failure = ProviderFailure("protocol_error", "missing_stop_reason", "controlled", "unknown")
        return ProviderTerminal(call_id, "failed", reason, "unknown", failure)

    @staticmethod
    def _cancel_terminal(call_id: str, *, sent: bool, request_id: str | None = None) -> ProviderTerminal:
        failure = ProviderFailure(
            category="cancelled",
            detail_code="cancel_requested" if sent else "cancelled_before_dispatch",
            retry="never",
            dispatch_effect="unknown" if sent else "not_sent",
            request_id=request_id,
        )
        return ProviderTerminal(
            call_id,
            "cancel_requested" if sent else "cancelled",
            None,
            "unknown",
            failure,
        )

    @classmethod
    def _normalize_exception(
        cls,
        exc: Exception,
        *,
        dispatch_effect: str,
        request_id: str | None = None,
    ) -> ProviderFailure:
        status = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        if response is not None:
            dispatch_effect = "response_observed"
        if request_id is None and response is not None:
            request_id = _request_id(response.headers.get("request-id"))
        body = getattr(exc, "body", None)
        error_type = None
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                candidate = error.get("type") or error.get("code")
                if isinstance(candidate, str) and len(candidate) <= 100:
                    error_type = candidate
        spend_codes = {
            "billing_error",
            "credit_balance_too_low",
            "usage_limit_reached",
            "monthly_limit_exceeded",
            "spend_limit_exceeded",
        }
        retry_after_ms = None
        if status == 401:
            category, detail, retry = "authentication", "http_401", "never"
        elif status == 403:
            category, detail, retry = "permission", "http_403", "never"
        elif status == 413:
            category, detail, retry = "request_too_large", "http_413", "never"
        elif status == 429 and error_type in spend_codes:
            category, detail, retry = "spend_cap", "spend_cap", "never"
        elif status == 429:
            category, detail, retry = "rate_limit", "http_429", "after_delay"
            if response is not None:
                raw_retry = response.headers.get("retry-after")
                try:
                    seconds = float(raw_retry) if raw_retry is not None else None
                except (TypeError, ValueError):
                    seconds = None
                if seconds is not None and 0 <= seconds <= 86_400:
                    retry_after_ms = int(seconds * 1000)
        elif isinstance(status, int) and 500 <= status <= 599:
            category, detail, retry = "provider_unavailable", f"http_{status}", "controlled"
        elif isinstance(status, int):
            category, detail, retry = "provider_error", f"http_{status}", "never"
        elif isinstance(exc, CredentialNotFound):
            category, detail, retry = "credential_missing", "credential_missing", "never"
            dispatch_effect = "not_sent"
        elif isinstance(exc, CredentialNeedsUnlock):
            category, detail, retry = "credential_needs_unlock", "needs_unlock", "never"
            dispatch_effect = "not_sent"
        elif isinstance(exc, CredentialAccessDenied):
            category, detail, retry = "credential_blocked", "blocked", "never"
            dispatch_effect = "not_sent"
        elif isinstance(exc, CredentialError):
            category, detail, retry = "credential_unavailable", "credential_unavailable", "never"
            dispatch_effect = "not_sent"
        elif isinstance(exc, _ProviderDependencyUnavailable):
            category, detail, retry = "dependency_unavailable", "claude_api_extra_missing", "never"
            dispatch_effect = "not_sent"
        elif httpx2 is not None and cls._exception_contains(exc, httpx2.DecodingError):
            category, detail, retry = "protocol_error", "response_decode_failed", "never"
            dispatch_effect = "response_observed"
        elif (
            (anthropic is not None and isinstance(exc, anthropic.APIConnectionError))
            or (
                httpx2 is not None
                and isinstance(exc, (httpx2.TimeoutException, httpx2.TransportError))
            )
        ):
            category, detail, retry = "transport_unknown", "transport_exception", "controlled"
            if dispatch_effect != "response_observed":
                dispatch_effect = "unknown"
        else:
            category, detail, retry = "adapter_error", "unexpected_exception", "never"
        return ProviderFailure(
            category=category,
            detail_code=detail,
            retry=retry,
            dispatch_effect=dispatch_effect,
            retry_after_ms=retry_after_ms,
            request_id=request_id,
        )
