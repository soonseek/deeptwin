"""Credentialed provider transport for the dedicated gateway (T090).

The transport receives an opaque credential handle and resolves it only at send
time; the caller never sees the secret and never chooses a destination — the
connection is pinned to the exact bound origin, the path must sit under a bound
absolute prefix, and only projected request headers may cross. The auth header is
injected by the transport itself; caller-supplied auth, host, cookie, proxy or
framing headers are rejected before any network effect. Redirects are never
followed, and non-success responses are redacted: no provider error bytes and no
credential material ever appear in results or errors.
"""

from __future__ import annotations

import http.client
import re
from dataclasses import dataclass, field

from .credential_vault import CredentialVault, CredentialVaultError

_PROVIDER = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_HOST = re.compile(r"[a-z0-9]([a-z0-9.-]{0,253}[a-z0-9])?\Z")
_HEADER_NAME = re.compile(r"[a-z0-9-]{1,64}\Z")
_PATH = re.compile(r"/[A-Za-z0-9/_.-]{0,1023}\Z")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})
_FORBIDDEN_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "set-cookie", "host",
    "transfer-encoding", "content-encoding", "content-length", "connection",
    "upgrade", "te", "trailer", "keep-alive", "forwarded", "x-forwarded-for",
    "x-forwarded-host", "x-forwarded-proto",
})


class GatewayError(RuntimeError):
    """Sanitized gateway failure; never carries secrets or provider bytes."""


@dataclass(frozen=True, slots=True)
class ProviderBinding:
    """The exact, closed request surface one provider transport may use."""

    provider: str
    scheme: str
    host: str
    port: int
    allowed_methods: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    allowed_request_headers: tuple[str, ...]
    auth_header: str
    max_request_bytes: int
    max_response_bytes: int
    timeout_seconds: int

    def __post_init__(self) -> None:
        if (
            type(self.provider) is not str
            or _PROVIDER.fullmatch(self.provider) is None
            or self.scheme not in ("https", "http")
            or type(self.host) is not str
            or _HOST.fullmatch(self.host) is None
            or type(self.port) is not int
            or not 1 <= self.port <= 65_535
            or type(self.allowed_methods) is not tuple
            or not self.allowed_methods
            or any(method not in ("GET", "POST") for method in self.allowed_methods)
            or type(self.allowed_path_prefixes) is not tuple
            or not self.allowed_path_prefixes
            or any(
                type(prefix) is not str or _PATH.fullmatch(prefix) is None
                or ".." in prefix
                for prefix in self.allowed_path_prefixes
            )
            or type(self.allowed_request_headers) is not tuple
            or any(
                type(name) is not str or _HEADER_NAME.fullmatch(name) is None
                or name in _FORBIDDEN_HEADERS
                for name in self.allowed_request_headers
            )
            or type(self.auth_header) is not str
            or _HEADER_NAME.fullmatch(self.auth_header) is None
            or type(self.max_request_bytes) is not int
            or not 1 <= self.max_request_bytes <= 8 * 1024 * 1024
            or type(self.max_response_bytes) is not int
            or not 1 <= self.max_response_bytes <= 8 * 1024 * 1024
            or type(self.timeout_seconds) is not int
            or not 1 <= self.timeout_seconds <= 600
        ):
            raise GatewayError("provider binding is invalid")
        # Plain HTTP is a loopback-only test affordance; production is HTTPS.
        if self.scheme == "http" and self.host not in _LOOPBACK_HOSTS:
            raise GatewayError("plain http is loopback-only")


@dataclass(frozen=True, slots=True)
class GatewayResponse:
    status: int
    body: bytes = field(repr=False)


class CredentialedProviderTransport:
    """One provider's bounded, credentialed request path inside the gateway."""

    __slots__ = ("_binding", "_vault")

    def __init__(self, vault: CredentialVault, binding: ProviderBinding) -> None:
        if type(vault) is not CredentialVault or type(binding) is not ProviderBinding:
            raise GatewayError("an exact vault and provider binding are required")
        self._vault = vault
        self._binding = binding

    def __repr__(self) -> str:
        return (
            f"CredentialedProviderTransport(provider={self._binding.provider!r}, "
            f"origin={self._binding.scheme}://{self._binding.host}:{self._binding.port})"
        )

    def _validate(self, method: str, path: str, headers: dict, body: bytes) -> dict:
        binding = self._binding
        if method not in binding.allowed_methods:
            raise GatewayError("request method is not bound")
        if (
            type(path) is not str
            or _PATH.fullmatch(path) is None
            or ".." in path
            or path.startswith("//")
            or not any(
                path == prefix or path.startswith(prefix + "/")
                for prefix in binding.allowed_path_prefixes
            )
        ):
            raise GatewayError("request path is not bound")
        if type(headers) is not dict:
            raise GatewayError("request headers are not a projection")
        projected: dict[str, str] = {}
        for name, value in headers.items():
            if (
                type(name) is not str
                or type(value) is not str
                or _HEADER_NAME.fullmatch(name.lower()) is None
                or name.lower() in _FORBIDDEN_HEADERS
                or name.lower() == binding.auth_header
                or name.lower() not in binding.allowed_request_headers
                or any(ord(character) < 32 or ord(character) == 127
                       for character in value)
                or len(value) > 8_192
            ):
                raise GatewayError("a request header is outside the bound projection")
            projected[name.lower()] = value
        if type(body) is not bytes or len(body) > binding.max_request_bytes:
            raise GatewayError("request body exceeds the bound size")
        return projected

    def send(
        self,
        *,
        handle: str,
        method: str,
        path: str,
        headers: dict,
        body: bytes,
    ) -> GatewayResponse:
        binding = self._binding
        projected = self._validate(method, path, headers, body)
        try:
            record_provider = self._vault._record(handle)["provider"]
        except CredentialVaultError as exc:
            raise GatewayError("credential handle is not usable") from exc
        if record_provider != binding.provider:
            raise GatewayError("credential handle is bound to another provider")
        try:
            secret = self._vault.resolve_for_gateway(handle)
        except CredentialVaultError as exc:
            raise GatewayError("credential handle is not usable") from exc
        projected[binding.auth_header] = secret.decode("utf-8")

        connection_type = (
            http.client.HTTPSConnection
            if binding.scheme == "https" else http.client.HTTPConnection
        )
        connection = connection_type(
            binding.host, binding.port, timeout=binding.timeout_seconds
        )
        try:
            try:
                connection.request(method, path, body=body, headers=projected)
                response = connection.getresponse()
                payload = response.read(binding.max_response_bytes + 1)
                status = response.status
            except OSError as exc:
                raise GatewayError("provider transport failed") from exc
        finally:
            connection.close()
        if 300 <= status < 400:
            raise GatewayError("provider redirect is not followed")
        if not 200 <= status < 300:
            raise GatewayError(f"provider_status_{status // 100}xx")
        if len(payload) > binding.max_response_bytes:
            raise GatewayError("provider response exceeds the bound size")
        return GatewayResponse(status=status, body=payload)


__all__ = [
    "CredentialedProviderTransport",
    "GatewayError",
    "GatewayResponse",
    "ProviderBinding",
]
