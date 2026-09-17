"""Immutable domain envelopes. Actor provenance records do not grant authority."""

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import re

from .refs import (DomainContractError, EntityRef, canonical_json, parse_canonical,
                   positive_integer, uuid_string, ENTITY_KINDS)


SCHEMA_VERSION = "domain-v1"
PURPOSES = frozenset({"operational", "diagnosis", "inquiry_audit", "evaluation_development",
                      "evaluation_sealed", "release_evidence"})
BODY_FIELDS = frozenset({"schema_version", "kind", "id", "version", "created_at_utc",
                         "actor_ref", "parent_refs", "purpose", "access_policy_ref",
                         "retention_policy_ref", "content"})
ACTOR_ORIGINS = {"human": "local_session", "system": "host_service",
                 "provider": "model_output", "service_client": "service_credential",
                 "test_actor": "test_fixture"}
GENESIS_VERSION = "domain-genesis-v1"
BOOTSTRAP_VERSION = "domain-bootstrap-v1"
ROOT_KINDS = frozenset({"actor", "access_policy", "retention_policy"})


@dataclass(frozen=True, slots=True)
class Actor:
    id: str
    kind: str
    origin: str

    def __post_init__(self):
        uuid_string(self.id)
        if (type(self.kind) is not str or type(self.origin) is not str
                or ACTOR_ORIGINS.get(self.kind) != self.origin):
            raise DomainContractError("Invalid actor provenance")

    @classmethod
    def from_untrusted(cls, value):
        if (type(value) is not dict or set(value) != {"id", "kind", "origin"}
                or value["kind"] not in ("provider", "test_actor")):
            raise DomainContractError("Untrusted input cannot assert human/system origin")
        return cls(**value)


def _validate_timestamp(timestamp):
    if (type(timestamp) is not str
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", timestamp) is None):
        raise DomainContractError("Expected UTC timestamp with microseconds and Z")
    try:
        datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise DomainContractError("Invalid UTC timestamp") from exc


def _root_content(kind, identity):
    if kind == "actor":
        return {"id": identity, "kind": "system", "origin": "host_service"}
    if kind == "access_policy":
        return {"profile": "deny-by-default-v1"}
    if kind == "retention_policy":
        return {"core_mode": "manual_only", "cache_max_age_days": 14,
                "cache_max_bytes": 1_073_741_824, "diagnostics_max_age_days": 30,
                "diagnostics_max_bytes": 104_857_600}
    raise DomainContractError("Unregistered bootstrap kind")


def _validate_root(body):
    base = {"schema_version", "kind", "id", "version", "created_at_utc"}
    if body["schema_version"] == GENESIS_VERSION:
        if (set(body) != base | {"vault_id", "profile"} or body["kind"] != "vault_genesis"
                or body["vault_id"] != body["id"] or body["profile"] != "local-deny-by-default-v1"):
            raise DomainContractError("Invalid vault genesis")
    else:
        if (set(body) != base | {"genesis_ref", "content"}
                or type(body["kind"]) is not str or body["kind"] not in ROOT_KINDS
                or EntityRef.from_dict(body["genesis_ref"]).kind != "vault_genesis"
                or body["content"] != _root_content(body["kind"], body["id"])):
            raise DomainContractError("Invalid bootstrap root")
        # Comparing Python numbers alone would accept bool as an integer in policy fields.
        if canonical_json(body["content"]) != canonical_json(_root_content(body["kind"], body["id"])):
            raise DomainContractError("Invalid bootstrap payload types")
    uuid_string(body["id"])
    if type(body["version"]) is not int or body["version"] != 1:
        raise DomainContractError("Bootstrap is a one-time version1 record")
    _validate_timestamp(body["created_at_utc"])


def _validate_body(body):
    if type(body) is not dict:
        raise DomainContractError("Expected domain record object")
    if body.get("schema_version") in (GENESIS_VERSION, BOOTSTRAP_VERSION):
        _validate_root(body)
        return
    if set(body) != BODY_FIELDS or body["schema_version"] != SCHEMA_VERSION:
        raise DomainContractError("Expected exact domain-v1 content body")
    if (type(body["kind"]) is not str or body["kind"] not in ENTITY_KINDS
            or body["kind"] == "vault_genesis"):
        raise DomainContractError("Unregistered ordinary content kind")
    uuid_string(body["id"])
    positive_integer(body["version"])
    _validate_timestamp(body["created_at_utc"])
    if type(body["purpose"]) is not str or body["purpose"] not in PURPOSES:
        raise DomainContractError("Unregistered purpose")
    for name, kind in (("actor_ref", "actor"), ("access_policy_ref", "access_policy"),
                       ("retention_policy_ref", "retention_policy")):
        if EntityRef.from_dict(body[name]).kind != kind:
            raise DomainContractError("Wrong common reference kind")
    parents = body["parent_refs"]
    if type(parents) is not list or len(parents) > 256:
        raise DomainContractError("Expected bounded parent reference list")
    refs = [EntityRef.from_dict(value) for value in parents]
    if len(set(refs)) != len(refs):
        raise DomainContractError("Duplicate parents")
    if any(value.kind == body["kind"] and value.id == body["id"]
           and value.version >= body["version"] for value in refs):
        raise DomainContractError("Self/future version cannot be a parent")
    if type(body["content"]) is not dict:
        raise DomainContractError("Content must be a schema-owned object")
    if body["kind"] == "deployment_request":
        from .deployment_request import validate_anchor_body

        validate_anchor_body(body)
    if body["kind"] == "deployment_receipt":
        from .deployment_receipt import validate_receipt_body

        validate_receipt_body(body)
    if body["kind"] == "deployment_receipt_consumption":
        from .deployment_receipt import validate_consumption_body

        validate_consumption_body(body)
    if body["kind"] == "extension_installation":
        from .extension_installation import validate_installation_body

        validate_installation_body(body)
    if body["kind"] == "worker_response_capture":
        from .worker_response import validate_capture_content

        if body["version"] != 1:
            raise DomainContractError("Worker response capture requires version1")
        validate_capture_content(body["content"])


@dataclass(frozen=True, slots=True)
class ImmutableRecord:
    ref: EntityRef
    body_bytes: bytes = field(repr=False)

    def __post_init__(self):
        if type(self.ref) is not EntityRef:
            raise DomainContractError("Expected immutable reference")
        body = parse_canonical(self.body_bytes)
        _validate_body(body)
        actual = EntityRef(kind=body["kind"], id=body["id"], version=body["version"],
                           sha256=sha256(self.body_bytes).hexdigest())
        if actual != self.ref:
            raise DomainContractError("Record content/reference mismatch")

    @classmethod
    def genesis(cls, *, vault_id, created_at_utc):
        """Record format only. Store initialization must authenticate one-time installation."""
        return cls.from_bytes(canonical_json(dict(schema_version=GENESIS_VERSION,
            kind="vault_genesis", id=vault_id, version=1, vault_id=vault_id,
            created_at_utc=created_at_utc, profile="local-deny-by-default-v1")))

    @classmethod
    def bootstrap(cls, *, kind, id, genesis_ref, created_at_utc):
        if type(genesis_ref) is not EntityRef or genesis_ref.kind != "vault_genesis":
            raise DomainContractError("Bootstrap requires exact genesis ref")
        return cls.from_bytes(canonical_json(dict(schema_version=BOOTSTRAP_VERSION,
            kind=kind, id=id, version=1, created_at_utc=created_at_utc,
            genesis_ref=genesis_ref.as_dict(), content=_root_content(kind, id))))

    @classmethod
    def create(cls, *, kind, id, version, created_at_utc, actor_ref, parent_refs, purpose,
               access_policy_ref, retention_policy_ref, content):
        if (type(parent_refs) not in (tuple, list) or len(parent_refs) > 256
                or any(type(value) is not EntityRef for value in parent_refs)
                or any(type(value) is not EntityRef for value in
                       (actor_ref, access_policy_ref, retention_policy_ref))):
            raise DomainContractError("Header references must be exact EntityRefs")
        body = dict(schema_version=SCHEMA_VERSION, kind=kind, id=id, version=version,
                    created_at_utc=created_at_utc, actor_ref=actor_ref.as_dict(),
                    parent_refs=[value.as_dict() for value in parent_refs], purpose=purpose,
                    access_policy_ref=access_policy_ref.as_dict(),
                    retention_policy_ref=retention_policy_ref.as_dict(), content=content)
        return cls.from_bytes(canonical_json(body))

    @classmethod
    def from_bytes(cls, data, *, expected_ref=None):
        body = parse_canonical(data)
        _validate_body(body)
        actual = EntityRef(kind=body["kind"], id=body["id"], version=body["version"],
                           sha256=sha256(data).hexdigest())
        if expected_ref is not None and (type(expected_ref) is not EntityRef or expected_ref != actual):
            raise DomainContractError("Expected content reference mismatch")
        return cls(ref=actual, body_bytes=data)

    @property
    def body(self):
        # A detached copy: callers cannot mutate the hashed state through nested containers.
        return parse_canonical(self.body_bytes)

    def as_dict(self):
        return {"ref": self.ref.as_dict(), "body": self.body}


@dataclass(frozen=True, slots=True)
class RecordMetadata:
    """Replaceable observation state; never part of immutable content or approval hashes."""
    availability: str
    redaction_state: str

    def __post_init__(self):
        if (type(self.availability) is not str
                or self.availability not in ("present", "missing", "deleted", "corrupt")):
            raise DomainContractError("Invalid availability")
        if (type(self.redaction_state) is not str
                or self.redaction_state not in ("original", "redacted", "metadata_only")):
            raise DomainContractError("Invalid redaction observation")
