"""Closed, nonsecret credential-v2 contracts; safe for control-plane imports."""
import base64
from datetime import datetime
from hashlib import sha256
import json
import re
from uuid import UUID

MAX_SECRET_BYTES = 65536
MAX_ENVELOPE_BYTES = 96 * 1024
METADATA_KEYS = {"command_id", "record_id", "record_version", "provider", "auth_mode", "created_at", "predecessor"}


class CredentialVaultError(RuntimeError):
    def __init__(self, code="credential_operation_rejected"):
        self.code = code
        super().__init__(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def strict_json(payload, limit):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result
    try:
        if type(payload) is not bytes or not 1 <= len(payload) <= limit:
            raise ValueError
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs)
        if canonical(value) != payload:
            raise ValueError
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise CredentialVaultError("invalid_encoding") from None


def uuid_value(value):
    try:
        if type(value) is not str or len(value) != 36:
            raise ValueError
        parsed = UUID(value)
        if str(parsed) != value or parsed.int == 0:
            raise ValueError
    except ValueError:
        raise CredentialVaultError("invalid_metadata") from None
    return value


def version_value(value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise CredentialVaultError("invalid_metadata")
    return value


def timestamp(value):
    try:
        if type(value) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z", value) is None:
            raise ValueError
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise CredentialVaultError("invalid_metadata") from None
    return value


def reference(value):
    if type(value) is not dict or set(value) != {"record_id", "record_version", "ciphertext_sha256"}:
        raise CredentialVaultError("invalid_metadata")
    uuid_value(value["record_id"])
    version_value(value["record_version"])
    if type(value["ciphertext_sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", value["ciphertext_sha256"]) is None:
        raise CredentialVaultError("invalid_metadata")
    return dict(value)


def metadata_value(value):
    if type(value) is not dict or set(value) != METADATA_KEYS:
        raise CredentialVaultError("invalid_metadata")
    for name in ("command_id", "record_id"):
        uuid_value(value[name])
    version_value(value["record_version"])
    timestamp(value["created_at"])
    if (value["provider"], value["auth_mode"]) not in (("claude", "api"), ("codex", "api")):
        raise CredentialVaultError("invalid_metadata")
    result = dict(value)
    if value["predecessor"] is not None:
        result["predecessor"] = reference(value["predecessor"])
    return result


def fingerprint(metadata):
    return sha256(canonical({"schema": "credential-op-v2", "op": "store_at", **metadata})).hexdigest()


def b64u(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def unb64u(value, minimum, maximum):
    try:
        if type(value) is not str or not minimum * 4 // 3 <= len(value) <= (maximum * 4 + 2) // 3:
            raise ValueError
        if re.fullmatch(r"[A-Za-z0-9_-]*", value) is None:
            raise ValueError
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if not minimum <= len(decoded) <= maximum or b64u(decoded) != value:
            raise ValueError
        return decoded
    except (ValueError, UnicodeError):
        raise CredentialVaultError("invalid_encoding") from None


def secret_value(value):
    try:
        if type(value) is not bytes or not 1 <= len(value) <= MAX_SECRET_BYTES:
            raise ValueError
        value.decode("utf-8")
        if any(byte < 32 or byte == 127 for byte in value):
            raise ValueError
        return value
    except (ValueError, UnicodeError):
        raise CredentialVaultError("invalid_secret") from None
