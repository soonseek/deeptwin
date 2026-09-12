"""Explicit, isolated Codex API authentication and model-catalog boundary.

The default Codex subscription path remains owned by the official Codex App
Server.  This module never reads or mutates that managed login.  It opens only
an app-owned ``codex_api`` Keychain reference after its caller supplies an
explicit API-mode action and queries the fixed OpenAI Models API.  Binding that
assertion to an authenticated GUI command belongs to the command service.
Model execution belongs to later runtime integration and is intentionally not
inferred from a catalog row.
"""

from __future__ import annotations

from collections import OrderedDict
import base64
from dataclasses import dataclass, replace
from datetime import date
import hashlib
import json
import math
import re
import threading
import time
from typing import Any, Callable, Iterable

import httpx

from .keychain import (
    CredentialAccessDenied,
    CredentialError,
    CredentialNeedsUnlock,
    CredentialNotFound,
    CredentialRef,
    CredentialVault,
)


API_ORIGIN = "https://api.openai.com"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_ACCOUNT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_DATE = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])\Z")


@dataclass(frozen=True, slots=True)
class CodexAPITransportPolicy:
    origin: str = API_ORIGIN
    mode: str = "api"
    trust_env: bool = False
    follow_redirects: bool = False
    retries: int = 0


@dataclass(frozen=True, slots=True)
class CodexAPIFailure:
    category: str
    detail_code: str
    retry: str
    dispatch_effect: str
    request_id: str | None = None
    fallback_mode: None = None


class CodexAPIError(RuntimeError):
    """A sanitized API-mode failure with no provider body or key material."""

    def __init__(self, failure: CodexAPIFailure) -> None:
        self.failure = failure
        super().__init__(f"Codex API catalog failed: {failure.category}/{failure.detail_code}")

    def __repr__(self) -> str:
        return (
            f"CodexAPIError(category={self.failure.category!r}, "
            f"detail_code={self.failure.detail_code!r})"
        )


@dataclass(frozen=True, slots=True)
class CodexAPIBinding:
    credential_ref: CredentialRef
    project_id: str | None = None
    organization_id: str | None = None

    def __post_init__(self) -> None:
        if self.credential_ref.provider != "codex_api":
            raise ValueError("Codex API binding requires an isolated Codex API credential")
        for name, value in (
            ("project_id", self.project_id),
            ("organization_id", self.organization_id),
        ):
            if value is not None and not _ACCOUNT_ID.fullmatch(value):
                raise ValueError(f"Invalid {name}")

    @property
    def binding_id(self) -> str:
        return "codex-api-binding-" + _json_hash(
            {
                "provider": "codex",
                "mode": "api",
                "credential_ref": self.credential_ref.identifier,
                "project_id": self.project_id,
                "organization_id": self.organization_id,
            }
        )


@dataclass(frozen=True, slots=True)
class CodexAPICatalogModel:
    model_id: str
    owned_by: str
    created: int
    shutdown_date: str | None = None
    capabilities: tuple[str, ...] = ()
    execution_eligible: bool = False

    def digest_record(self) -> dict[str, Any]:
        return {
            "id": self.model_id,
            "owned_by": self.owned_by,
            "created": self.created,
            "shutdown_date": self.shutdown_date,
            "capabilities": self.capabilities,
            "execution_eligible": self.execution_eligible,
        }


@dataclass(frozen=True, slots=True)
class CodexAPICatalogSnapshot:
    provider: str
    mode: str
    binding_id: str
    catalog_id: str
    fetched_at_ms: int
    max_age_ms: int
    credential_generation: int
    binding_generation: int
    models: tuple[CodexAPICatalogModel, ...]


@dataclass(frozen=True, slots=True)
class CodexAPISelection:
    binding_id: str
    catalog_id: str
    model_id: str
    effort: str | None = None


class _ProtocolViolation(Exception):
    def __init__(self, detail_code: str) -> None:
        self.detail_code = detail_code
        super().__init__(detail_code)


@dataclass(frozen=True, slots=True)
class _IssuedCatalog:
    binding_id: str
    credential_ref: CredentialRef
    digest: str
    credential_generation: int
    binding_generation: int


def _json_hash(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _ProtocolViolation("duplicate_json_key")
        result[key] = value
    return result


def _strict_json(raw: bytes) -> Any:
    def reject_constant(_value: str) -> None:
        raise _ProtocolViolation("nonfinite_json_constant")

    try:
        return json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=reject_constant,
        )
    except _ProtocolViolation:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, RecursionError) as exc:
        raise _ProtocolViolation("invalid_catalog_json") from exc


def _secret_canaries(secret: str) -> tuple[tuple[str, int], ...]:
    """Build bounded, ephemeral canaries for common raw and fingerprint echoes.

    This deliberately does not claim to recognize every possible derivation.  It
    covers meaningful raw fragments plus the standard encodings and digest
    fingerprints that a provider field could reflect verbatim.
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
        values.extend((
            (digest.hex(), 12),
            (base64.b64encode(digest).decode("ascii").rstrip("="), 12),
            (base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="), 12),
        ))
    unique = {(value.casefold(), width) for value, width in values if value}
    return tuple(sorted(unique))


def _reflects_secret(value: str, canaries: tuple[tuple[str, int], ...]) -> bool:
    """Reject exact canaries or meaningful fragments without persisting them."""

    if not value:
        return False
    folded = value.casefold()
    for canary, fragment_size in canaries:
        if folded == canary:
            return True
        if len(canary) < fragment_size or len(folded) < fragment_size:
            continue
        for start in range(len(canary) - fragment_size + 1):
            if canary[start:start + fragment_size] in folded:
                return True
    return False


class CodexAPIAdapter:
    """Models-API boundary for a separately selected usage-billed mode."""

    def __init__(
        self,
        *,
        vault: CredentialVault,
        transport: httpx.BaseTransport | None = None,
        clock_ms: Callable[[], int] | None = None,
        monotonic_ms: Callable[[], int] | None = None,
        mode: str = "api",
        timeout_seconds: float = 30.0,
        catalog_max_age_ms: int = 15 * 60 * 1000,
        max_catalog_bytes: int = 2 * 1024 * 1024,
        max_catalog_models: int = 20_000,
        max_catalog_duration_ms: int = 120 * 1000,
    ) -> None:
        if mode != "api":
            raise ValueError("Codex API adapter is API-only; it cannot use subscription auth")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        for name, value in (
            ("catalog_max_age_ms", catalog_max_age_ms),
            ("max_catalog_bytes", max_catalog_bytes),
            ("max_catalog_models", max_catalog_models),
            ("max_catalog_duration_ms", max_catalog_duration_ms),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self._vault = vault
        self._transport = transport
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._monotonic_ms = monotonic_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self._timeout_seconds = float(timeout_seconds)
        self._catalog_max_age_ms = catalog_max_age_ms
        self._max_catalog_bytes = max_catalog_bytes
        self._max_catalog_models = max_catalog_models
        self._max_catalog_duration_ms = max_catalog_duration_ms
        self._issued: OrderedDict[str, _IssuedCatalog] = OrderedDict()
        self._states: dict[str, str] = {}
        self._binding_credentials: dict[str, CredentialRef] = {}
        self._credential_generations: dict[CredentialRef, int] = {}
        self._binding_generations: dict[str, int] = {}
        self._binding_request_epochs: dict[str, int] = {}
        self._lock = threading.RLock()
        self.transport_policy = CodexAPITransportPolicy()

    def connection_state(self, binding: CodexAPIBinding) -> str:
        if not isinstance(binding, CodexAPIBinding):
            raise TypeError("binding must be CodexAPIBinding")
        with self._lock:
            return self._states.get(binding.binding_id, "not_checked")

    def _headers(self, binding: CodexAPIBinding, secret: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {secret}",
            "Accept": "application/json",
            "User-Agent": "DeepTwin/codex-api-boundary",
        }
        if binding.project_id is not None:
            headers["OpenAI-Project"] = binding.project_id
        if binding.organization_id is not None:
            headers["OpenAI-Organization"] = binding.organization_id
        return headers

    def _read_bounded(self, chunks: Iterable[bytes], started_ms: int) -> bytes:
        result = bytearray()
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise _ProtocolViolation("catalog_chunk_type")
            if len(chunk) > self._max_catalog_bytes - len(result):
                raise _ProtocolViolation("catalog_byte_limit")
            if self._monotonic_ms() - started_ms > self._max_catalog_duration_ms:
                raise _ProtocolViolation("catalog_absolute_deadline")
            result.extend(chunk)
        if self._monotonic_ms() - started_ms > self._max_catalog_duration_ms:
            raise _ProtocolViolation("catalog_absolute_deadline")
        return bytes(result)

    @staticmethod
    def _parse_model(
        item: Any, secret_canaries: tuple[tuple[str, int], ...]
    ) -> CodexAPICatalogModel:
        if not isinstance(item, dict) or item.get("object") != "model":
            raise _ProtocolViolation("catalog_model_object")
        model_id = item.get("id")
        created = item.get("created")
        owned_by = item.get("owned_by")
        shutdown_date = item.get("shutdown_date")
        if not isinstance(model_id, str) or not _SAFE_ID.fullmatch(model_id):
            raise _ProtocolViolation("model_id")
        if type(created) is not int or created < 0 or created > 10_000_000_000:
            raise _ProtocolViolation("model_created")
        if not isinstance(owned_by, str) or not _SAFE_ID.fullmatch(owned_by):
            raise _ProtocolViolation("model_owner")
        if _reflects_secret(model_id, secret_canaries) or _reflects_secret(
            owned_by, secret_canaries
        ):
            raise _ProtocolViolation("catalog_secret_reflection")
        if shutdown_date is not None and (
            not isinstance(shutdown_date, str) or not _DATE.fullmatch(shutdown_date)
        ):
            raise _ProtocolViolation("model_shutdown_date")
        if shutdown_date is not None and _reflects_secret(
            shutdown_date, secret_canaries
        ):
            raise _ProtocolViolation("catalog_secret_reflection")
        if shutdown_date is not None:
            try:
                date.fromisoformat(shutdown_date)
            except ValueError as exc:
                raise _ProtocolViolation("model_shutdown_date") from exc
        # The Models endpoint's basic row is not a capability declaration.
        return CodexAPICatalogModel(model_id, owned_by, created, shutdown_date)

    def _parse_catalog(
        self, raw: bytes, secret_canaries: tuple[tuple[str, int], ...]
    ) -> tuple[CodexAPICatalogModel, ...]:
        payload = _strict_json(raw)
        if not isinstance(payload, dict) or payload.get("object") != "list":
            raise _ProtocolViolation("catalog_object")
        data = payload.get("data")
        if not isinstance(data, list):
            raise _ProtocolViolation("catalog_data")
        if len(data) > self._max_catalog_models:
            raise _ProtocolViolation("catalog_model_limit")
        models: list[CodexAPICatalogModel] = []
        seen: set[str] = set()
        for item in data:
            model = self._parse_model(item, secret_canaries)
            if model.model_id in seen:
                raise _ProtocolViolation("duplicate_model")
            seen.add(model.model_id)
            models.append(model)
        return tuple(models)

    @staticmethod
    def _catalog_digest(snapshot: CodexAPICatalogSnapshot) -> str:
        return "codex-api-catalog-" + _json_hash(
            {
                "provider": snapshot.provider,
                "mode": snapshot.mode,
                "binding_id": snapshot.binding_id,
                "fetched_at_ms": snapshot.fetched_at_ms,
                "max_age_ms": snapshot.max_age_ms,
                "credential_generation": snapshot.credential_generation,
                "binding_generation": snapshot.binding_generation,
                "models": [model.digest_record() for model in snapshot.models],
            }
        )

    def _begin_catalog_request(self, binding: CodexAPIBinding) -> tuple[int, int, int]:
        with self._lock:
            binding_id = binding.binding_id
            self._binding_credentials[binding_id] = binding.credential_ref
            request_epoch = self._binding_request_epochs.get(binding_id, 0) + 1
            self._binding_request_epochs[binding_id] = request_epoch
            return (
                self._credential_generations.get(binding.credential_ref, 0),
                self._binding_generations.get(binding_id, 0),
                request_epoch,
            )

    def _invalidate_binding(self, binding_id: str) -> None:
        with self._lock:
            self._binding_generations[binding_id] = (
                self._binding_generations.get(binding_id, 0) + 1
            )
            stale = [
                catalog_id
                for catalog_id, issued in self._issued.items()
                if issued.binding_id == binding_id
            ]
            for catalog_id in stale:
                self._issued.pop(catalog_id, None)
            self._states[binding_id] = "invalidated"

    def _invalidate_credential(
        self, credential_ref: CredentialRef, *, observed_binding_id: str | None = None
    ) -> None:
        with self._lock:
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
                for catalog_id, issued in self._issued.items()
                if issued.credential_ref == credential_ref
            ]
            for catalog_id in stale:
                self._issued.pop(catalog_id, None)
            for binding_id in affected:
                self._states[binding_id] = "invalidated"

    @staticmethod
    def _http_failure(response: httpx.Response) -> CodexAPIFailure:
        status = response.status_code
        # Provider-controlled request IDs are intentionally kept inside the
        # transport boundary.  Hashing an echoed API key would still create a
        # prohibited credential fingerprint in logs and exported failures.
        request_id = None
        if 300 <= status < 400:
            return CodexAPIFailure(
                "transport_policy", "redirect_refused", "never", "response_observed", request_id
            )
        if status == 401:
            category, detail, retry = "authentication", "api_key_rejected", "never"
        elif status == 403:
            category, detail, retry = "authorization", "api_access_forbidden", "never"
        elif status == 429:
            category, detail, retry = "rate_limit", "rate_limited", "caller_only"
        elif 500 <= status < 600:
            category, detail, retry = "provider_server", "provider_server_error", "caller_only"
        else:
            category, detail, retry = "http_error", "unexpected_http_status", "never"
        return CodexAPIFailure(category, detail, retry, "response_observed", request_id)

    @staticmethod
    def _credential_failure(error: CredentialError) -> CodexAPIFailure:
        if isinstance(error, CredentialNotFound):
            detail = "credential_missing"
        elif isinstance(error, CredentialNeedsUnlock):
            detail = "credential_needs_unlock"
        elif isinstance(error, CredentialAccessDenied):
            detail = "credential_access_blocked"
        else:
            detail = "credential_store_error"
        return CodexAPIFailure("credential", detail, "never", "not_sent")

    def fetch_catalog(
        self, binding: CodexAPIBinding, *, explicit_action: bool
    ) -> CodexAPICatalogSnapshot:
        if not isinstance(binding, CodexAPIBinding):
            raise TypeError("binding must be CodexAPIBinding")
        if explicit_action is not True:
            raise ValueError("Codex API catalog access requires an explicit API action")

        fetched_at = self._clock_ms()
        if type(fetched_at) is not int:
            raise ValueError("clock_ms must return an integer")
        started = self._monotonic_ms()
        if type(started) is not int:
            raise ValueError("monotonic_ms must return an integer")
        credential_generation, binding_generation, request_epoch = \
            self._begin_catalog_request(binding)
        response_observed = False
        request_started = False
        try:
            with self._vault.open(binding.credential_ref) as material:
                secret = material.reveal_text()
                secret_canaries = _secret_canaries(secret)
                headers = self._headers(binding, secret)
                timeout = httpx.Timeout(self._timeout_seconds)
                with httpx.Client(
                    base_url=API_ORIGIN,
                    headers=headers,
                    transport=self._transport,
                    timeout=timeout,
                    trust_env=False,
                    follow_redirects=False,
                ) as client:
                    request_started = True
                    with client.stream("GET", "/v1/models") as response:
                        response_observed = True
                        if response.status_code != 200:
                            failure = self._http_failure(response)
                            if response.status_code == 401:
                                self._invalidate_credential(
                                    binding.credential_ref,
                                    observed_binding_id=binding.binding_id,
                                )
                            elif response.status_code == 403:
                                self._invalidate_binding(binding.binding_id)
                            raise CodexAPIError(failure)
                        content_type = response.headers.get("content-type", "")
                        content_type = content_type.split(";", 1)[0].strip().lower()
                        if content_type != "application/json":
                            raise _ProtocolViolation("catalog_content_type")
                        raw = self._read_bounded(response.iter_bytes(), started)
                models = self._parse_catalog(raw, secret_canaries)
        except CodexAPIError:
            raise
        except CredentialError as exc:
            if isinstance(exc, CredentialNotFound):
                self._invalidate_credential(
                    binding.credential_ref, observed_binding_id=binding.binding_id
                )
            failure = self._credential_failure(exc)
            if response_observed:
                failure = replace(failure, dispatch_effect="response_observed")
            raise CodexAPIError(failure) from None
        except _ProtocolViolation as exc:
            raise CodexAPIError(
                CodexAPIFailure(
                    "catalog_protocol_error",
                    exc.detail_code,
                    "never",
                    "response_observed" if response_observed else "not_sent",
                )
            ) from None
        except (httpx.TimeoutException, httpx.TransportError):
            if response_observed:
                raise CodexAPIError(
                    CodexAPIFailure(
                        "catalog_response_error",
                        "catalog_response_read_failed",
                        "caller_only",
                        "response_observed",
                    )
                ) from None
            raise CodexAPIError(
                CodexAPIFailure(
                    "transport_unknown",
                    "transport_outcome_unknown",
                    "caller_only",
                    "unknown" if request_started else "not_sent",
                )
            ) from None
        except Exception:
            if response_observed:
                raise CodexAPIError(
                    CodexAPIFailure(
                        "catalog_response_error",
                        "catalog_response_read_failed",
                        "caller_only",
                        "response_observed",
                    )
                ) from None
            if request_started:
                raise CodexAPIError(
                    CodexAPIFailure(
                        "transport_unknown",
                        "transport_outcome_unknown",
                        "caller_only",
                        "unknown",
                    )
                ) from None
            raise CodexAPIError(
                CodexAPIFailure("local_failure", "catalog_local_failure", "never", "not_sent")
            ) from None

        snapshot = CodexAPICatalogSnapshot(
            provider="codex",
            mode="api",
            binding_id=binding.binding_id,
            catalog_id="",
            fetched_at_ms=fetched_at,
            max_age_ms=self._catalog_max_age_ms,
            credential_generation=credential_generation,
            binding_generation=binding_generation,
            models=models,
        )
        snapshot = replace(snapshot, catalog_id=self._catalog_digest(snapshot))
        digest = self._catalog_digest(snapshot)
        with self._lock:
            credential_changed = (
                self._credential_generations.get(binding.credential_ref, 0)
                != credential_generation
                or self._binding_generations.get(binding.binding_id, 0)
                != binding_generation
            )
            request_superseded = (
                self._binding_request_epochs.get(binding.binding_id, 0)
                != request_epoch
            )
            if credential_changed or request_superseded:
                raise CodexAPIError(
                    CodexAPIFailure(
                        "authentication",
                        ("credential_state_changed" if credential_changed
                         else "catalog_request_superseded"),
                        "never",
                        "response_observed",
                    )
                )
            stale = [
                catalog_id
                for catalog_id, issued in self._issued.items()
                if issued.binding_id == binding.binding_id
            ]
            for catalog_id in stale:
                self._issued.pop(catalog_id, None)
            self._issued[snapshot.catalog_id] = _IssuedCatalog(
                binding_id=binding.binding_id,
                credential_ref=binding.credential_ref,
                digest=digest,
                credential_generation=credential_generation,
                binding_generation=binding_generation,
            )
            self._issued.move_to_end(snapshot.catalog_id)
            while len(self._issued) > 64:
                self._issued.popitem(last=False)
            self._states[binding.binding_id] = "catalog_current"
        return snapshot

    def validate_selection(
        self,
        selection: CodexAPISelection,
        snapshot: CodexAPICatalogSnapshot,
        binding: CodexAPIBinding,
        *,
        explicit_action: bool,
        required_capabilities: Iterable[str] = (),
    ) -> CodexAPICatalogModel:
        if not all(
            isinstance(value, expected)
            for value, expected in (
                (selection, CodexAPISelection),
                (snapshot, CodexAPICatalogSnapshot),
                (binding, CodexAPIBinding),
            )
        ):
            raise TypeError("selection, snapshot and binding types are required")
        if explicit_action is not True:
            raise ValueError("Codex API model validation requires an explicit API action")
        if (
            selection.binding_id != binding.binding_id
            or snapshot.binding_id != binding.binding_id
        ):
            raise ValueError("Codex API model selection binding is stale or mismatched")
        if snapshot.provider != "codex" or snapshot.mode != "api":
            raise ValueError("Catalog is not from the Codex API mode")
        if selection.catalog_id != snapshot.catalog_id:
            raise ValueError("Codex API model selection catalog is stale or mismatched")
        digest = self._catalog_digest(snapshot)
        if snapshot.catalog_id != digest:
            raise ValueError("Codex API model catalog integrity check failed")
        expected_issue = _IssuedCatalog(
            binding_id=binding.binding_id,
            credential_ref=binding.credential_ref,
            digest=digest,
            credential_generation=snapshot.credential_generation,
            binding_generation=snapshot.binding_generation,
        )
        with self._lock:
            issued = self._issued.get(snapshot.catalog_id)
        if issued != expected_issue:
            raise ValueError("Codex API model catalog was not issued by this live connection")
        observed = self._clock_ms()
        if type(observed) is not int:
            raise ValueError("Invalid catalog validation clock")
        if (
            observed < snapshot.fetched_at_ms
            or observed > snapshot.fetched_at_ms + snapshot.max_age_ms
        ):
            raise ValueError("Codex API model catalog is stale")
        model = next(
            (
                candidate
                for candidate in snapshot.models
                if candidate.model_id == selection.model_id
            ),
            None,
        )
        if model is None:
            raise ValueError("Selected Codex API model is unavailable")
        capabilities = tuple(required_capabilities)
        if any(
            not isinstance(item, str) or not _SAFE_ID.fullmatch(item)
            for item in capabilities
        ):
            raise ValueError("Required capability identifier is invalid")
        if capabilities:
            raise ValueError("Selected model capability is unknown in the Models API catalog")
        if selection.effort is not None:
            if not isinstance(selection.effort, str) or not _SAFE_ID.fullmatch(
                selection.effort
            ):
                raise ValueError("Requested effort is invalid")
            raise ValueError("Requested effort capability is unknown in the Models API catalog")
        try:
            # Production rotation always creates a new opaque ref and removes
            # the old item.  Re-opening here prevents an old persisted binding
            # from retaining catalog authority after rotate/delete.
            with self._vault.open(binding.credential_ref):
                pass
        except CredentialError as exc:
            if isinstance(exc, CredentialNotFound):
                self._invalidate_credential(
                    binding.credential_ref, observed_binding_id=binding.binding_id
                )
            raise CodexAPIError(self._credential_failure(exc)) from None
        with self._lock:
            issued = self._issued.get(snapshot.catalog_id)
            if issued != expected_issue:
                raise ValueError(
                    "Codex API model catalog was invalidated during validation"
                )
            if (
                self._credential_generations.get(binding.credential_ref, 0)
                != snapshot.credential_generation
                or self._binding_generations.get(binding.binding_id, 0)
                != snapshot.binding_generation
            ):
                raise ValueError(
                    "Codex API model catalog authority changed during validation"
                )
            return model


__all__ = [
    "API_ORIGIN",
    "CodexAPIAdapter",
    "CodexAPIBinding",
    "CodexAPICatalogModel",
    "CodexAPICatalogSnapshot",
    "CodexAPIError",
    "CodexAPIFailure",
    "CodexAPISelection",
    "CodexAPITransportPolicy",
]
