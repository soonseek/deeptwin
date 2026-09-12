"""TLS-only service-client bearer boundary with bounded independent rate buckets."""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from threading import RLock

from ..api.wire import WireInputError, parse_singleton_headers
from .service_clients import ServiceClientPrincipal

_NETWORK_PROFILES = frozenset({"portable_https", "dedicated_https"})
_RATE_KEY = re.compile(r"^[^\x00-\x20\x7f-\x9f]{1,256}$")
_SCOPE = re.compile(
    r"(?:command:[a-z][a-z0-9_]{0,63}\.[a-z][a-z0-9_]{0,63}|"
    r"(?:events|snapshot|artifact)\.read)"
)


class ServiceClientAuthDenied(PermissionError):
    """Non-reflective denial at the external service-client boundary."""


@dataclass(frozen=True, slots=True)
class AuthorizedServiceRequest:
    principal: ServiceClientPrincipal
    route_id: str


@dataclass(slots=True)
class _Bucket:
    tokens: int
    last_refill_ms: int
    last_seen_ms: int


@dataclass(frozen=True, slots=True)
class _Reservation:
    sequence: int
    source_key: str
    route_key: str


class IndependentTokenBuckets:
    """One bounded map each for client, trusted source and registered route."""

    _DIMENSIONS = ("client", "route", "source")

    def __init__(
        self,
        *,
        clock_ms,
        capacity: int,
        refill_interval_ms: int,
        max_keys_per_dimension: int,
        idle_ttl_ms: int,
    ) -> None:
        if not callable(clock_ms):
            raise TypeError("rate limiter requires a trusted clock")
        if any(
            type(value) is not int or value < 1
            for value in (
                capacity,
                refill_interval_ms,
                max_keys_per_dimension,
                idle_ttl_ms,
            )
        ):
            raise ValueError("rate limiter bounds must be positive integers")
        self._clock = clock_ms
        self._capacity = capacity
        self._refill_ms = refill_interval_ms
        self._max_keys = max_keys_per_dimension
        self._idle_ttl_ms = idle_ttl_ms
        self._buckets: dict[str, dict[str, _Bucket]] = {
            name: {} for name in self._DIMENSIONS
        }
        self._last_now: int | None = None
        self._lock = RLock()
        self._reservation_sequence = 0
        self._reservations: dict[int, _Reservation] = {}

    @staticmethod
    def _key(value: object) -> str:
        if type(value) is not str or _RATE_KEY.fullmatch(value) is None:
            raise ServiceClientAuthDenied("service client rate identity is invalid")
        return value

    def _now(self) -> int:
        try:
            value = self._clock()
        except Exception:  # noqa: BLE001 - sanitize the trusted-clock boundary
            raise ServiceClientAuthDenied("service client rate limit is unavailable") from None
        if type(value) is not int or value < 0:
            raise ServiceClientAuthDenied("service client rate limit is unavailable")
        if self._last_now is not None and value < self._last_now:
            raise ServiceClientAuthDenied("service client rate limit is unavailable")
        self._last_now = value
        return value

    def _prune(self, now: int) -> None:
        protected = {
            "source": {value.source_key for value in self._reservations.values()},
            "route": {value.route_key for value in self._reservations.values()},
            "client": set(),
        }
        for dimension, values in self._buckets.items():
            expired = [
                key
                for key, bucket in values.items()
                if key not in protected[dimension]
                and now - bucket.last_seen_ms >= self._idle_ttl_ms
            ]
            for key in expired:
                values.pop(key, None)

    def _available(self, bucket: _Bucket, now: int) -> tuple[int, int]:
        intervals = (now - bucket.last_refill_ms) // self._refill_ms
        if intervals < 1:
            return bucket.tokens, bucket.last_refill_ms
        return (
            min(self._capacity, bucket.tokens + intervals),
            bucket.last_refill_ms + intervals * self._refill_ms,
        )

    def source_route_available(self, *, source_key: str, route_key: str) -> bool:
        """Cheap pre-auth check; it never grants or consumes a token."""
        source_key = self._key(source_key)
        route_key = self._key(route_key)
        with self._lock:
            now = self._now()
            self._prune(now)
            for dimension, key in (("source", source_key), ("route", route_key)):
                values = self._buckets[dimension]
                bucket = values.get(key)
                if bucket is None:
                    if len(values) >= self._max_keys:
                        return False
                elif self._available(bucket, now)[0] < 1:
                    return False
            return True

    def reserve(self, *, source_key: str, route_key: str) -> _Reservation | None:
        """Atomically hold source and route capacity before credential verification."""
        source_key = self._key(source_key)
        route_key = self._key(route_key)
        with self._lock:
            now = self._now()
            self._prune(now)
            planned: dict[str, tuple[int, int]] = {}
            for dimension, key in (("source", source_key), ("route", route_key)):
                values = self._buckets[dimension]
                bucket = values.get(key)
                if bucket is None:
                    if len(values) >= self._max_keys:
                        return None
                    planned[dimension] = (self._capacity, now)
                else:
                    planned[dimension] = self._available(bucket, now)
                if planned[dimension][0] < 1:
                    return None
            for dimension, key in (("source", source_key), ("route", route_key)):
                tokens, last_refill = planned[dimension]
                self._buckets[dimension][key] = _Bucket(
                    tokens=tokens - 1,
                    last_refill_ms=last_refill,
                    last_seen_ms=now,
                )
            self._reservation_sequence += 1
            reservation = _Reservation(
                self._reservation_sequence, source_key, route_key,
            )
            self._reservations[reservation.sequence] = reservation
            return reservation

    def finalize(self, reservation: _Reservation, *, client_key: str) -> bool:
        """Commit a held request and consume its client dimension exactly once."""
        client_key = self._key(client_key)
        with self._lock:
            current = self._reservations.get(getattr(reservation, "sequence", None))
            if current is not reservation:
                raise ServiceClientAuthDenied("service client rate reservation is invalid")
            now = self._now()
            self._prune(now)
            values = self._buckets["client"]
            bucket = values.get(client_key)
            if bucket is None:
                if len(values) >= self._max_keys:
                    self._refund_locked(reservation, now)
                    self._reservations.pop(reservation.sequence)
                    return False
                tokens, last_refill = self._capacity, now
            else:
                tokens, last_refill = self._available(bucket, now)
            if tokens < 1:
                self._refund_locked(reservation, now)
                self._reservations.pop(reservation.sequence)
                return False
            values[client_key] = _Bucket(
                tokens=tokens - 1,
                last_refill_ms=last_refill,
                last_seen_ms=now,
            )
            self._reservations.pop(reservation.sequence)
            return True

    def _refund_locked(self, reservation: _Reservation, now: int) -> None:
        for dimension, key in (
            ("source", reservation.source_key),
            ("route", reservation.route_key),
        ):
            bucket = self._buckets[dimension].get(key)
            if bucket is None:
                raise ServiceClientAuthDenied("service client rate reservation is invalid")
            tokens, last_refill = self._available(bucket, now)
            self._buckets[dimension][key] = _Bucket(
                tokens=min(self._capacity, tokens + 1),
                last_refill_ms=last_refill,
                last_seen_ms=now,
            )

    def refund(self, reservation: _Reservation) -> None:
        """Release a hold exactly once when authentication was never attempted."""
        with self._lock:
            current = self._reservations.get(getattr(reservation, "sequence", None))
            if current is not reservation:
                raise ServiceClientAuthDenied("service client rate reservation is invalid")
            now = self._now()
            self._prune(now)
            self._refund_locked(reservation, now)
            self._reservations.pop(reservation.sequence)

    def consume(self, *, client_key: str, source_key: str, route_key: str) -> bool:
        keys = {
            "client": self._key(client_key),
            "source": self._key(source_key),
            "route": self._key(route_key),
        }
        with self._lock:
            now = self._now()
            self._prune(now)
            planned: dict[str, tuple[int, int]] = {}
            for dimension, key in keys.items():
                values = self._buckets[dimension]
                bucket = values.get(key)
                if bucket is None:
                    if len(values) >= self._max_keys:
                        return False
                    planned[dimension] = (self._capacity, now)
                else:
                    planned[dimension] = self._available(bucket, now)
                if planned[dimension][0] < 1:
                    return False
            for dimension, key in keys.items():
                tokens, last_refill = planned[dimension]
                self._buckets[dimension][key] = _Bucket(
                    tokens=tokens - 1,
                    last_refill_ms=last_refill,
                    last_seen_ms=now,
                )
            return True

    def snapshot_counts(self) -> dict[str, int]:
        with self._lock:
            return {name: len(values) for name, values in self._buckets.items()}


def _decode_bearer(value: str) -> str | None:
    if type(value) is not str or not value.startswith("Bearer ") or value.count(" ") != 1:
        return None
    secret = value[7:]
    if len(secret) != 49 or not secret.startswith("dt_sc_"):
        return None
    encoded = secret[6:]
    try:
        raw = base64.urlsafe_b64decode(encoded + "=")
        canonical = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    except (UnicodeError, ValueError):
        return None
    if len(raw) != 32 or canonical != encoded:
        return None
    return secret


class ServiceClientAuthenticator:
    """Authenticate one exact bearer and enforce network, scope and rate authority."""

    def __init__(self, *, registry, limiter: IndependentTokenBuckets) -> None:
        if not callable(getattr(registry, "authenticate", None)):
            raise TypeError("service client authenticator requires a registry")
        if type(limiter) is not IndependentTokenBuckets:
            raise TypeError("service client authenticator requires fixed token buckets")
        self._registry = registry
        self._limiter = limiter

    def authorize(
        self,
        raw_headers,
        *,
        tls: bool,
        network_profile: str,
        source_key: str,
        route_id: str,
        required_scope: str,
    ) -> AuthorizedServiceRequest:
        if (
            tls is not True
            or network_profile not in _NETWORK_PROFILES
            or type(route_id) is not str
            or _RATE_KEY.fullmatch(route_id) is None
            or type(required_scope) is not str
            or _SCOPE.fullmatch(required_scope) is None
        ):
            raw_headers = None
            raise ServiceClientAuthDenied("service client transport is invalid")
        try:
            parsed = parse_singleton_headers(
                raw_headers,
                names=("authorization", "cookie"),
                required=("authorization",),
                max_value_bytes=128,
            )
        except (TypeError, ValueError, WireInputError):
            raw_headers = None
            raise ServiceClientAuthDenied("service client headers are invalid") from None
        raw_headers = None
        if "cookie" in parsed:
            parsed = None
            raise ServiceClientAuthDenied("browser cookies cannot authenticate a service client")
        authorization = parsed["authorization"]
        parsed = None
        secret = _decode_bearer(authorization)
        authorization = None
        if secret is None:
            raise ServiceClientAuthDenied("service client bearer is invalid")
        secret_digest = hashlib.sha256(secret.encode("ascii")).hexdigest()
        try:
            reservation = self._limiter.reserve(
                source_key=source_key, route_key=route_id,
            )
        except ServiceClientAuthDenied:
            secret = None
            raise ServiceClientAuthDenied("service client rate limit is unavailable") from None
        if reservation is None:
            secret = None
            raise ServiceClientAuthDenied("service client rate limit exceeded")
        try:
            principal = self._registry.authenticate(
                secret, network_profile=network_profile,
            )
        except Exception:  # noqa: BLE001 - make registry/auth failures non-reflective
            secret = None
            self._limiter.finalize(
                reservation,
                client_key="invalid:" + secret_digest,
            )
            raise ServiceClientAuthDenied("service client authentication failed") from None
        secret = None
        if type(principal) is not ServiceClientPrincipal:
            self._limiter.finalize(
                reservation, client_key="invalid:" + secret_digest,
            )
            raise ServiceClientAuthDenied("service client authentication failed")
        try:
            admitted = self._limiter.finalize(
                reservation, client_key=principal.client_id,
            )
        except ServiceClientAuthDenied:
            try:
                self._limiter.finalize(
                    reservation, client_key="invalid:" + secret_digest,
                )
            except ServiceClientAuthDenied:
                pass
            raise ServiceClientAuthDenied("service client authentication failed") from None
        if not admitted:
            raise ServiceClientAuthDenied("service client rate limit exceeded")
        if required_scope not in principal.scopes:
            raise ServiceClientAuthDenied("service client scope denied")
        return AuthorizedServiceRequest(principal=principal, route_id=route_id)


__all__ = [
    "AuthorizedServiceRequest",
    "IndependentTokenBuckets",
    "ServiceClientAuthDenied",
    "ServiceClientAuthenticator",
]
