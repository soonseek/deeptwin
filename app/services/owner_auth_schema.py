"""Portable nonsecret schema definitions for the first-owner backend slice."""
from ..domain.schema_exports import DRAFT, _hash, _object, _uuid


def owner_auth_schema():
    receipt = _object({
        "schema_version": {"const": "session-root-v1"},
        "generation_id": _uuid(), "key_id": _uuid(),
        "instance_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
        "origin_profile_digest": _hash(), "recovery_epoch": {"type": "integer", "const": 1},
        "created_at": {"type": "string", "format": "date-time", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"},
        "state": {"const": "initial_genesis"},
    })
    return {"$schema": DRAFT, "$id": "urn:deeptwin:schemas:v1:owner-auth-public",
        "title": "Nonsecret owner authentication and session-root receipt definitions",
        "$comment": "Schema data grants no authority. Private hashes, verifiers, session digests and root integrity tags are never exported as records.",
        "$defs": {
            "SessionRootReceipt": receipt,
            "BootstrapClaimState": {"type": "string", "enum": ["available", "consumed", "completed", "expired", "exhausted"]},
            "OwnerAccountState": {"type": "string", "enum": ["active", "disabled"]},
            "SetupGate": {"type": "string", "enum": ["owner_required", "ready", "setup_incomplete", "setup_unavailable"]},
            "PasswordProfile": {"type": "string", "const": "argon2id-v19-m65536-t3-p4-s16-h32"},
        }}
