"""Credentialed provider transport for the dedicated gateway (T090).

The transport receives an opaque credential handle and resolves it only at send
time; the caller never sees the secret and never chooses a destination — the
connection is pinned to the exact bound origin, the path must sit under a bound
absolute prefix, and only projected request headers may cross. The auth header is
injected by the transport itself; caller-supplied auth, host, cookie, proxy or
framing headers are rejected before any network effect. Redirects are never
followed, and non-success responses are redacted: no provider error bytes and no
credential material ever appear in results or errors.

The send path (`exchange`) serves only a binding built from a provider-transport
manifest (`ProviderBinding.from_manifest`, T087): origin, methods, path prefixes, the
projected headers and their values, the injected auth header, the byte bounds and each
endpoint's method/path/query/cursor/response media type all come from the manifest's
exact bytes, and the vault delivers custody only while the gateway's adopted
qualification names that manifest's digest (`CredentialVault.delivery_for_exchange`).
"""

from __future__ import annotations

import http.client
import re
import socket
from dataclasses import dataclass, field

from .credential_vault import CredentialVault, CredentialVaultError
from .provider_transport_manifest import (
    FORBIDDEN_HEADERS,
    TransportManifest,
    TransportManifestError,
    endpoint_request,
    host_header,
)

_PROVIDER = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_HOST = re.compile(r"[a-z0-9]([a-z0-9.-]{0,253}[a-z0-9])?\Z")
_HEADER_NAME = re.compile(r"[a-z0-9-]{1,64}\Z")
_PATH = re.compile(r"/[A-Za-z0-9/_.-]{0,1023}\Z")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_FORBIDDEN_HEADERS = FORBIDDEN_HEADERS


class GatewayError(RuntimeError):
    """Sanitized gateway failure; never carries secrets or provider bytes."""
    def __init__(self, message, *, failure_class="internal_failure", status=None,
                 body=b"", phase=None, cancel_observed=False, media_type=None):
        super().__init__(message)
        allowed = {"permission_denied", "deadline_exceeded", "resource_exhausted",
            "unsupported_capability", "integrity_failed", "dependency_unavailable",
            "cancelled", "internal_failure"}
        if failure_class not in allowed:
            raise ValueError("invalid gateway failure class")
        self.failure_class, self.status, self.body = failure_class, status, body
        self.phase, self.cancel_observed = phase, cancel_observed
        self.media_type = media_type


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
    # Set only by `from_manifest`: the manifest digest the vault's adopted qualification
    # must name, the projected header values and the endpoint table of the send path.
    manifest_sha256: str | None = None
    request_headers: tuple = ()
    endpoints: tuple = ()

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
        if self.manifest_sha256 is None:
            if self.request_headers or self.endpoints:
                raise GatewayError("provider binding is invalid")
            return
        if (type(self.manifest_sha256) is not str or _HEX.fullmatch(self.manifest_sha256) is None
                or type(self.request_headers) is not tuple or type(self.endpoints) is not tuple
                or tuple(sorted(name for name, _ in self.request_headers))
                != tuple(sorted(self.allowed_request_headers))
                or sorted(endpoint.name for endpoint in self.endpoints) != ["messages", "models"]
                or any(endpoint.method not in self.allowed_methods
                       or not any(endpoint.path == prefix or endpoint.path.startswith(prefix + "/")
                                  for prefix in self.allowed_path_prefixes)
                       for endpoint in self.endpoints)):
            raise GatewayError("provider binding is invalid")

    @classmethod
    def from_manifest(cls, manifest: TransportManifest, *, loopback_port: int | None = None):
        """The binding of one parsed provider-transport manifest: every field is the
        manifest's. `loopback_port` replaces only the origin with plain HTTP on
        127.0.0.1 -- a test affordance for a local mock provider; the manifest digest (and
        therefore the qualification it needs) is unchanged, and the gateway process
        never passes it."""
        if type(manifest) is not TransportManifest:
            raise GatewayError("an exact parsed transport manifest is required")
        scheme, host, port = manifest.scheme, manifest.host, manifest.port
        if loopback_port is not None:
            scheme, host, port = "http", "127.0.0.1", loopback_port
        return cls(provider=manifest.provider, scheme=scheme, host=host, port=port,
                   allowed_methods=manifest.allowed_methods,
                   allowed_path_prefixes=manifest.allowed_path_prefixes,
                   allowed_request_headers=tuple(name for name, _ in manifest.request_headers),
                   auth_header=manifest.auth_header,
                   max_request_bytes=manifest.max_request_bytes,
                   max_response_bytes=manifest.max_response_bytes,
                   timeout_seconds=manifest.timeout_seconds,
                   manifest_sha256=manifest.manifest_sha256,
                   request_headers=manifest.request_headers,
                   endpoints=manifest.endpoints)

    def endpoint_request(self, endpoint: str, after_id: str | None):
        """(method, request target, projected headers, accepted response media type) of
        one send-dialogue endpoint, from the manifest; nothing is a code constant."""
        try:
            return endpoint_request(self.endpoints, self.request_headers, endpoint, after_id)
        except TransportManifestError:
            raise GatewayError("provider endpoint is not bound",
                               failure_class="unsupported_capability") from None

    def host_header(self) -> str:
        return host_header(self.scheme, self.host, self.port)


def claude_api_manifest_binding() -> ProviderBinding:
    """The gateway process's Claude API binding: built only from the shipped
    provider-transport manifest (`transport_manifests/claude-api-v1.json`). Sends through it
    are delivered only while the gateway's adopted qualification names this manifest's
    digest."""
    from .provider_transport_manifest import claude_api_manifest

    return ProviderBinding.from_manifest(claude_api_manifest())


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
            record_provider = self._vault.metadata(handle)["provider"]
        except CredentialVaultError as exc:
            raise GatewayError("credential handle is not usable") from exc
        if record_provider != binding.provider:
            raise GatewayError("credential handle is bound to another provider")
        try:
            secret = self._vault.resolve_for_gateway(handle)
        except CredentialVaultError as exc:
            raise GatewayError("credential handle is not usable") from exc
        try:
            auth_value = secret.decode("utf-8")
        except UnicodeDecodeError:
            raise GatewayError("credential is not header-safe") from None
        if any(ord(character) < 32 or ord(character) == 127
               for character in auth_value):
            # A control character can never be framed as a header value; fail
            # closed here so the secret can never surface in a framing error.
            raise GatewayError("credential is not header-safe")
        projected[binding.auth_header] = auth_value

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
            except (OSError, ValueError):
                # `from None`: a framing ValueError embeds the raw header value,
                # so the cause chain must be severed to keep errors secret-free.
                raise GatewayError("provider transport failed") from None
        finally:
            connection.close()
        if 300 <= status < 400:
            raise GatewayError("provider redirect is not followed")
        if not 200 <= status < 300:
            raise GatewayError(f"provider_status_{status // 100}xx")
        if len(payload) > binding.max_response_bytes:
            raise GatewayError("provider response exceeds the bound size")
        return GatewayResponse(status=status, body=payload)

    def exchange(self, *, lease):
        """Perform one lease-bound request; raw credential bytes stay in this scope."""
        from .provider_send_messages import GatewayExchangeLease, ProviderSendObservation, ProviderSendError

        if type(lease) is not GatewayExchangeLease:
            raise GatewayError("an exact exchange lease is required",
                               failure_class="integrity_failed")
        binding = self._binding
        if lease.cancel_event.is_set():
            raise GatewayError("provider exchange cancelled", failure_class="cancelled",
                               cancel_observed=True, phase="not_sent")
        if binding.manifest_sha256 is None:
            # only a manifest-built binding serves sends: no code-constant request surface
            raise GatewayError("provider binding has no transport manifest",
                               failure_class="unsupported_capability", phase="not_sent")
        if lease.transport_manifest_sha256 != binding.manifest_sha256:
            raise GatewayError("exchange lease names another transport manifest",
                               failure_class="integrity_failed", phase="not_sent")
        try:
            method, path, headers, expected_media = binding.endpoint_request(
                lease.endpoint, lease.after_id)
        except GatewayError:
            raise GatewayError("provider endpoint is not bound",
                               failure_class="unsupported_capability", phase="not_sent") from None
        # the query is built from the manifest's exact fixed query and cursor; the
        # historical path validator has no query surface
        validate_path = path.split("?", 1)[0]
        try:
            projected = self._validate(method, validate_path, headers, lease.body)
        except GatewayError:
            raise GatewayError("provider request projection is unsupported",
                               failure_class="unsupported_capability") from None
        connection_type = http.client.HTTPSConnection if binding.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(binding.host, binding.port,
                                     timeout=max(0.001, lease.deadline_monotonic - __import__("time").monotonic()))
        try:
            lease._issuer.register_connection(lease, connection)
        except ProviderSendError:
            raise GatewayError("provider exchange state changed",
                               failure_class="integrity_failed") from None
        phase = "not_sent"
        status, media, collected = None, None, bytearray()
        try:
            with self._vault.delivery_for_exchange(lease) as secret:
                try:
                    auth_value = secret.decode("utf-8")
                except UnicodeDecodeError:
                    raise GatewayError("credential is not header-safe",
                                       failure_class="integrity_failed") from None
                if any(ord(character) < 32 or ord(character) == 127 for character in auth_value):
                    raise GatewayError("credential is not header-safe",
                                       failure_class="integrity_failed")
                projected[binding.auth_header] = auth_value
                remaining = lease.deadline_monotonic - __import__("time").monotonic()
                if lease.cancel_event.is_set() or remaining <= 0:
                    failure = "cancelled" if lease.cancel_event.is_set() else "deadline_exceeded"
                    raise GatewayError("provider exchange stopped", failure_class=failure,
                        cancel_observed=lease.cancel_event.is_set(), phase="not_sent")
                connection.timeout = max(0.001, remaining)
                connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
                connection.putheader("host", binding.host_header())
                connection.putheader("content-length", str(len(lease.body)))
                for name, value in projected.items():
                    connection.putheader(name, value)
                if lease.cancel_event.is_set() \
                        or __import__("time").monotonic() >= lease.deadline_monotonic:
                    failure = "cancelled" if lease.cancel_event.is_set() else "deadline_exceeded"
                    raise GatewayError("provider exchange stopped", failure_class=failure,
                        cancel_observed=lease.cancel_event.is_set(), phase="not_sent")
                remaining = lease.deadline_monotonic - __import__("time").monotonic()
                connection.timeout = max(0.001, remaining)
                if connection.sock is not None:
                    connection.sock.settimeout(connection.timeout)
                try:
                    lease._issuer.mark_write(lease)
                except ProviderSendError:
                    raise GatewayError("provider exchange state changed",
                                       failure_class="integrity_failed") from None
                phase = "may_have_sent"
                try:
                    connection.endheaders()
                    if lease.body:
                        connection.send(lease.body)
                except (OSError, ValueError, socket.timeout, http.client.HTTPException):
                    raise GatewayError("provider transport failed",
                        failure_class="dependency_unavailable", phase=phase,
                        cancel_observed=lease.cancel_event.is_set()) from None
            # The response object may detach this socket from HTTPConnection as
            # soon as headers declare Connection: close.  Retain the exact owned
            # socket before getresponse so cancellation can shutdown the read.
            lease._issuer.bind_connection_socket(lease, connection, connection.sock)
            owned_socket = connection.sock
            if lease.cancel_event.is_set() or __import__("time").monotonic() >= lease.deadline_monotonic:
                failure = "cancelled" if lease.cancel_event.is_set() else "deadline_exceeded"
                raise GatewayError("provider exchange stopped", failure_class=failure,
                    cancel_observed=lease.cancel_event.is_set(), phase=phase)
            response = connection.getresponse()
            status = response.status
            media = response.getheader("content-type")
            content_encoding = response.getheader("content-encoding")
            while len(collected) <= binding.max_response_bytes:
                if lease.cancel_event.is_set():
                    raise GatewayError("provider exchange cancelled", failure_class="cancelled",
                        status=status, body=bytes(collected), phase=phase,
                        cancel_observed=True, media_type=media)
                remaining = lease.deadline_monotonic - __import__("time").monotonic()
                if remaining <= 0:
                    raise GatewayError("provider transport deadline elapsed",
                        failure_class="deadline_exceeded", status=status,
                        body=bytes(collected), phase=phase,
                        cancel_observed=lease.cancel_event.is_set(), media_type=media)
                connection.timeout = remaining
                if owned_socket is not None and owned_socket.fileno() >= 0:
                    owned_socket.settimeout(remaining)
                block = response.read1(min(16_384, binding.max_response_bytes + 1 - len(collected)))
                if not block:
                    break
                collected.extend(block)
            payload = bytes(collected)
            if lease.cancel_event.is_set():
                raise GatewayError("provider exchange cancelled", failure_class="cancelled",
                    status=status, body=payload, phase=phase, cancel_observed=True,
                    media_type=media)
        except GatewayError:
            raise
        except CredentialVaultError as exc:
            category = {
                "cancelled": "cancelled",
                "deadline_exceeded": "deadline_exceeded",
                "capacity_exhausted": "resource_exhausted",
                "provider_binding_unavailable": "permission_denied",
                "unknown_record": "permission_denied",
                "busy": "dependency_unavailable",
                "closed": "dependency_unavailable",
                "storage_failure": "dependency_unavailable",
                "transport_unqualified": "unsupported_capability",
                "reservation_refused": "resource_exhausted",
                "maintenance_required": "integrity_failed",
                "invalid_metadata": "integrity_failed",
                "record_identity_mismatch": "integrity_failed",
                "authentication_failed": "integrity_failed",
                "invalid_envelope": "integrity_failed",
                "invalid_encoding": "integrity_failed",
                "invalid_secret": "integrity_failed",
            }.get(exc.code, "internal_failure")
            raise GatewayError("provider custody rejected", failure_class=category,
                               phase=phase, cancel_observed=(lease.cancel_event.is_set()
                                   or category == "cancelled")) from None
        except ProviderSendError:
            raise GatewayError("provider exchange integrity failed",
                               failure_class="integrity_failed", phase=phase,
                               cancel_observed=lease.cancel_event.is_set()) from None
        except socket.timeout:
            raise GatewayError("provider transport deadline elapsed",
                failure_class="deadline_exceeded", status=status, body=bytes(collected),
                phase=phase, cancel_observed=lease.cancel_event.is_set(),
                media_type=media) from None
        except (OSError, ValueError, http.client.HTTPException):
            raise GatewayError("provider transport failed", failure_class="dependency_unavailable",
                status=status, body=bytes(collected), phase=phase,
                cancel_observed=lease.cancel_event.is_set(), media_type=media) from None
        finally:
            connection.close()
            lease._issuer.clear_connection(lease, connection)
        if len(payload) > binding.max_response_bytes:
            return ProviderSendObservation(lease.exchange_id, lease.prepare_sha256, status,
                payload[:binding.max_response_bytes], phase, lease.cancel_event.is_set(), media,
                "resource_exhausted")
        if not 200 <= status < 300:
            return ProviderSendObservation(lease.exchange_id, lease.prepare_sha256, status, payload,
                                           "terminal_observed", lease.cancel_event.is_set(), media,
                                           None)
        if (media is None or media.lower() not in {expected_media, expected_media + "; charset=utf-8"}
                or content_encoding is not None):
            return ProviderSendObservation(lease.exchange_id, lease.prepare_sha256, status, payload,
                "terminal_observed", lease.cancel_event.is_set(), media,
                "unsupported_capability")
        return ProviderSendObservation(lease.exchange_id, lease.prepare_sha256, status, payload,
                                       "terminal_observed", lease.cancel_event.is_set(), media, None)


__all__ = [
    "CredentialedProviderTransport",
    "GatewayError",
    "GatewayResponse",
    "ProviderBinding",
    "claude_api_manifest_binding",
]
