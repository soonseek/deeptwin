"""Legacy local-development credential-store boundary for provider API keys.

Only opaque :class:`CredentialRef` values belong in application state.  The
historical macOS backend calls Security.framework in-process; it never shells out
to the ``security`` command and never uses environment variables for secrets.
ADR-009/ADR-012 do not use this backend for the web release: the production
credential implementation belongs in the isolated server-side vault/gateway.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import re
import threading
import uuid
from typing import Iterator, Protocol


_PROVIDER_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_IDENTIFIER_RE = re.compile(r"[0-9a-f]{32}\Z")
_ACCESS_GROUP_RE = re.compile(r"[A-Z0-9]{5,20}\.app\.deeptwin\.host\Z")
_SERVICE = "app.deeptwin.provider-key.v1"
_MAX_SECRET_BYTES = 16 * 1024


class CredentialError(RuntimeError):
    """A sanitized credential-store failure."""

    state = "blocked"


class CredentialNotFound(CredentialError):
    """The exact DeepTwin-owned credential reference does not exist."""

    state = "missing"


class CredentialNeedsUnlock(CredentialError):
    """Keychain interaction is unavailable while the credential store is locked."""

    state = "needs_unlock"


class CredentialAccessDenied(CredentialError):
    """The signed host lacks the required Keychain authority."""

    state = "blocked"


@dataclass(frozen=True, slots=True)
class CredentialRef:
    """Opaque, non-secret handle safe for persistence and audit records."""

    provider: str
    identifier: str

    def __post_init__(self) -> None:
        if not _PROVIDER_RE.fullmatch(self.provider):
            raise ValueError("Invalid credential provider")
        if not _IDENTIFIER_RE.fullmatch(self.identifier):
            raise ValueError("Invalid credential identifier")


class SecretMaterial:
    """Short-lived mutable secret buffer with a deliberately redacted repr."""

    __slots__ = ("_value", "_destroyed")

    def __init__(self, value: bytes) -> None:
        if not isinstance(value, bytes):
            raise TypeError("Secret material must be bytes")
        self._value = bytearray(value)
        self._destroyed = False

    def __repr__(self) -> str:
        return "<SecretMaterial redacted>"

    @property
    def destroyed(self) -> bool:
        return self._destroyed

    def reveal_text(self) -> str:
        if self._destroyed:
            raise CredentialError("Credential material is no longer available")
        invalid_encoding = False
        try:
            return bytes(self._value).decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            # Raise only after leaving the handler.  ``raise ... from None``
            # suppresses display but still leaves the original exception (and
            # therefore the secret bytes) reachable through ``__context__``.
            invalid_encoding = True
        if invalid_encoding:
            # The public exception traceback retains this frame.  Destroy the
            # buffer before raising so frame-local ``self`` cannot retain key
            # bytes for a crash reporter or diagnostic collector.
            self.destroy()
            raise CredentialError("Credential encoding is invalid")
        raise AssertionError("unreachable")

    def destroy(self) -> None:
        if not self._destroyed:
            for index in range(len(self._value)):
                self._value[index] = 0
            self._value.clear()
            self._destroyed = True

    def __enter__(self) -> SecretMaterial:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.destroy()


class CredentialVault(Protocol):
    def open(self, ref: CredentialRef) -> Iterator[SecretMaterial]: ...


def _secret_bytes(secret: str) -> bytes:
    if not isinstance(secret, str):
        secret = ""
        raise TypeError("Credential must be text")
    invalid_encoding = False
    try:
        value = secret.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        invalid_encoding = True
    secret = ""
    if invalid_encoding:
        raise ValueError("Credential encoding is invalid")
    if not value or len(value) > _MAX_SECRET_BYTES or b"\x00" in value:
        value = b""
        raise ValueError("Credential length or content is invalid")
    return value


def validate_credential_secret(secret: str) -> None:
    """Validate credential input before any durable staging side effect."""
    try:
        value = _secret_bytes(secret)
        del value
    finally:
        # Validation exceptions retain this frame in their traceback. Rebind
        # the immutable input before propagation so diagnostics cannot render it.
        secret = ""


class InMemoryCredentialVault:
    """Explicit test vault.  It is never selected as a production fallback."""

    def __init__(self) -> None:
        self._items: dict[CredentialRef, bytearray] = {}
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return f"<InMemoryCredentialVault items={len(self._items)}>"

    def store(self, provider: str, secret: str) -> CredentialRef:
        ref = CredentialRef(provider, uuid.uuid4().hex)
        try:
            return self.store_at(ref, secret)
        finally:
            # A downstream failure retains this forwarding frame in its
            # traceback. Rebind the immutable argument before propagation so
            # diagnostics cannot render credential material from frame locals.
            secret = ""

    def store_at(self, ref: CredentialRef, secret: str) -> CredentialRef:
        if type(ref) is not CredentialRef:
            raise TypeError("Exact credential reference required")
        try:
            raw = _secret_bytes(secret)
        finally:
            secret = ""
        with self._lock:
            if ref in self._items:
                raw = b""
                raise CredentialError("Credential reference already exists")
            self._items[ref] = bytearray(raw)
        raw = b""
        return ref

    def rotate(self, ref: CredentialRef, secret: str) -> CredentialRef:
        try:
            raw = _secret_bytes(secret)
        finally:
            secret = ""
        with self._lock:
            previous = self._items.pop(ref, None)
            if previous is None:
                raw = b""
                raise CredentialNotFound("Credential reference was not found")
            for index in range(len(previous)):
                previous[index] = 0
            replacement = CredentialRef(ref.provider, uuid.uuid4().hex)
            self._items[replacement] = bytearray(raw)
        raw = b""
        return replacement

    @contextmanager
    def open(self, ref: CredentialRef) -> Iterator[SecretMaterial]:
        with self._lock:
            stored = self._items.get(ref)
            if stored is None:
                raise CredentialNotFound("Credential reference was not found")
            material = SecretMaterial(bytes(stored))
        try:
            yield material
        finally:
            material.destroy()

    def delete(self, ref: CredentialRef) -> None:
        with self._lock:
            previous = self._items.pop(ref, None)
            if previous is None:
                raise CredentialNotFound("Credential reference was not found")
            for index in range(len(previous)):
                previous[index] = 0


class MacOSKeychainVault:
    """Historical DeepTwin-scoped generic-password records in macOS Keychain.

    ``security`` is injectable solely so tests can prove the exact query shape
    without touching a user's Keychain.  When omitted, Security.framework is
    imported lazily on first construction.  This adapter is retained for bounded
    pre-web tests and is not a web-release credential backend.
    """

    def __init__(self, *, access_group: str, security=None) -> None:
        if not isinstance(access_group, str) or not _ACCESS_GROUP_RE.fullmatch(access_group):
            raise ValueError("A signed host Keychain access group is required")
        if security is None:
            try:
                import Security as security_module
            except ImportError as exc:  # pragma: no cover - platform boundary
                raise CredentialError("macOS Keychain is unavailable") from exc
            security = security_module
        self._security = security
        self._access_group = access_group
        for required in ("kSecUseDataProtectionKeychain", "kSecAttrAccessGroup"):
            if not hasattr(self._security, required):
                raise CredentialError("Data-protection Keychain is unavailable")

    def __repr__(self) -> str:
        return "<MacOSKeychainVault service=app.deeptwin.provider-key.v1>"

    def _base_query(self, ref: CredentialRef) -> dict:
        return {
            self._security.kSecClass: self._security.kSecClassGenericPassword,
            self._security.kSecAttrService: _SERVICE,
            # Provider is part of the account key so a known opaque identifier
            # cannot be re-labelled to cross a provider boundary.
            self._security.kSecAttrAccount: f"{ref.provider}:{ref.identifier}",
            self._security.kSecUseDataProtectionKeychain: True,
            self._security.kSecAttrAccessGroup: self._access_group,
        }

    @staticmethod
    def _status(result) -> int:
        return int(result[0] if isinstance(result, tuple) else result)

    @staticmethod
    def _security_call(function, *args):
        try:
            return True, function(*args)
        except Exception:
            # Security/PyObjC exceptions may render the query dictionary, which
            # can contain kSecValueData during a store.  Return only a boolean;
            # the caller scrubs its query before creating a public exception,
            # so this frame and its arguments are absent from that traceback.
            return False, None

    def _check(self, result, operation: str, *, not_found=False) -> CredentialError | None:
        try:
            status = self._status(result)
        except Exception:
            return CredentialError(f"Keychain {operation} failed")
        if status == int(self._security.errSecSuccess):
            return None
        if not_found and status == int(self._security.errSecItemNotFound):
            return CredentialNotFound("Credential reference was not found")
        if status == int(getattr(self._security, "errSecInteractionNotAllowed", -25308)):
            return CredentialNeedsUnlock("Keychain needs to be unlocked")
        if status in {
            int(getattr(self._security, "errSecAuthFailed", -25293)),
            int(getattr(self._security, "errSecUserCanceled", -128)),
            int(getattr(self._security, "errSecMissingEntitlement", -34018)),
        }:
            return CredentialAccessDenied("Keychain access is blocked")
        return CredentialError(f"Keychain {operation} failed (status {status})")

    def store(self, provider: str, secret: str) -> CredentialRef:
        ref = CredentialRef(provider, uuid.uuid4().hex)
        try:
            return self.store_at(ref, secret)
        finally:
            # Security.framework failures retain this forwarding frame in the
            # public traceback even after store_at scrubs its own argument.
            secret = ""

    def store_at(self, ref: CredentialRef, secret: str) -> CredentialRef:
        if type(ref) is not CredentialRef:
            raise TypeError("Exact credential reference required")
        query = self._base_query(ref)
        try:
            raw = _secret_bytes(secret)
        finally:
            secret = ""
        query[self._security.kSecValueData] = raw
        raw = b""
        if hasattr(self._security, "kSecAttrSynchronizable"):
            query[self._security.kSecAttrSynchronizable] = False
        accessible = getattr(self._security, "kSecAttrAccessibleWhenUnlockedThisDeviceOnly", None)
        if accessible is not None and hasattr(self._security, "kSecAttrAccessible"):
            query[self._security.kSecAttrAccessible] = accessible
        succeeded, result = self._security_call(self._security.SecItemAdd, query, None)
        query.pop(self._security.kSecValueData, None)
        if not succeeded:
            raise CredentialError("Keychain store failed")
        error = self._check(result, "store")
        result = None
        if error is not None:
            raise error
        return ref

    def rotate(self, ref: CredentialRef, secret: str) -> CredentialRef:
        # A new opaque ref is essential: catalog bindings hash the ref, so key
        # rotation must invalidate every prior catalog and model selection.
        try:
            replacement = self.store(ref.provider, secret)
        finally:
            secret = ""
        try:
            self.delete(ref)
        except Exception:
            try:
                self.delete(replacement)
            except Exception:
                pass
            raise
        return replacement

    @contextmanager
    def open(self, ref: CredentialRef) -> Iterator[SecretMaterial]:
        query = self._base_query(ref)
        query[self._security.kSecReturnData] = True
        query[self._security.kSecMatchLimit] = self._security.kSecMatchLimitOne
        succeeded, result = self._security_call(self._security.SecItemCopyMatching, query, None)
        if not succeeded:
            raise CredentialError("Keychain read failed")
        error = self._check(result, "read", not_found=True)
        if error is not None:
            result = None
            raise error
        if not isinstance(result, tuple) or len(result) < 2:
            raise CredentialError("Keychain returned invalid credential material")
        invalid_material = False
        try:
            # PyObjC normally returns NSData, which supports the buffer protocol
            # but is not a Python ``bytes`` instance.
            raw = memoryview(result[1]).tobytes()
        except (TypeError, ValueError):
            invalid_material = True
        result = None
        if invalid_material:
            raise CredentialError("Keychain returned invalid credential material")
        if not raw or len(raw) > _MAX_SECRET_BYTES:
            raw = b""
            raise CredentialError("Keychain returned invalid credential material")
        material = SecretMaterial(raw)
        raw = b""
        try:
            yield material
        finally:
            material.destroy()

    def delete(self, ref: CredentialRef) -> None:
        succeeded, result = self._security_call(self._security.SecItemDelete, self._base_query(ref))
        if not succeeded:
            raise CredentialError("Keychain delete failed")
        error = self._check(result, "delete", not_found=True)
        result = None
        if error is not None:
            raise error
