"""Exact separately bounded envelope codec (the ciphertext field exceeds 64 KiB)."""
from .credential_contracts import (MAX_ENVELOPE_BYTES, CredentialVaultError, b64u,
    canonical, metadata_value, strict_json, unb64u, uuid_value, version_value, timestamp)

HEADER_KEYS = {"schema", "algorithm_id", "key_id", "vault_id", "record_id", "record_version", "provider", "auth_mode", "created_at"}


def header_for(metadata, manifest):
    metadata = metadata_value(metadata)
    return dict(schema="credential-record-v1", algorithm_id="xchacha20poly1305-ietf",
                key_id=manifest["key_id"], vault_id=manifest["vault_id"],
                **{k: metadata[k] for k in ("record_id", "record_version", "provider", "auth_mode", "created_at")})


def decode(payload):
    value = strict_json(payload, MAX_ENVELOPE_BYTES)
    if type(value) is not dict or set(value) != {"header", "nonce_b64u", "ciphertext_b64u"}:
        raise CredentialVaultError("invalid_envelope")
    header = value["header"]
    if type(header) is not dict or set(header) != HEADER_KEYS:
        raise CredentialVaultError("invalid_envelope")
    if header["schema"] != "credential-record-v1" or header["algorithm_id"] != "xchacha20poly1305-ietf":
        raise CredentialVaultError("invalid_envelope")
    for name in ("key_id", "vault_id", "record_id"):
        uuid_value(header[name])
    version_value(header["record_version"])
    timestamp(header["created_at"])
    if (header["provider"], header["auth_mode"]) not in (("claude", "api"), ("codex", "api")):
        raise CredentialVaultError("invalid_envelope")
    return header, unb64u(value["nonce_b64u"], 24, 24), unb64u(value["ciphertext_b64u"], 16, 65552)


def encode(header, nonce, ciphertext):
    payload = canonical(dict(header=header, nonce_b64u=b64u(nonce), ciphertext_b64u=b64u(ciphertext)))
    decode(payload)
    return payload
