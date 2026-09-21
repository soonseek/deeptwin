"""Inert provider-only v2 build declaration, never admission or lineage evidence."""

from dataclasses import dataclass
from hashlib import sha256
import re

from jsonschema import Draft202012Validator
from ..domain.refs import canonical_json, parse_canonical
from ..domain.wire import WireLimits, parse_json_object
from .provider_identity_schema_exports import provider_build_identity_schema

_ROLES = ("config", "request", "result", "error")
_FIELDS = (
    "schema_version",
    "extension_id",
    "extension_version",
    "platform",
    "port_contract_version",
    "worker_profile",
    "inputs",
    "entrypoint",
    "port_schemas",
)
_LIMITS = WireLimits(
    max_bytes=8192,
    max_depth=4,
    max_items=128,
    max_members=16,
    max_string_bytes=256,
    max_integer=2**40,
)


class ProviderIdentityError(ValueError):
    def __init__(self):
        super().__init__("invalid provider identity")


@dataclass(frozen=True, slots=True, init=False)
class ProviderBuildIdentity:
    content_bytes: bytes

    def __new__(cls):
        raise TypeError("Use parse_provider_build_identity")

    @property
    def digest(self):
        return sha256(self.content_bytes).hexdigest()

    @property
    def input_digest(self):
        return sha256(canonical_json(self.as_dict()["inputs"])).hexdigest()

    @property
    def schema_set_digest(self):
        return sha256(canonical_json(self.as_dict()["port_schemas"])).hexdigest()

    def as_dict(self):
        return parse_canonical(self.content_bytes)


def parse_provider_build_identity(raw):
    try:
        value = parse_json_object(raw, required=_FIELDS, limits=_LIMITS)
        if canonical_json(value) != raw or not Draft202012Validator(
            provider_build_identity_schema()
        ).is_valid(value):
            raise ProviderIdentityError()
        version = value["extension_version"]
        if not re.fullmatch(
            r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version
        ):
            raise ProviderIdentityError()
        if any(int(x) > 2**31 - 1 for x in version.split(".")):
            raise ProviderIdentityError()
        if (
            tuple(x["role"] for x in value["port_schemas"]) != _ROLES
            or sum(x["size_bytes"] for x in value["port_schemas"]) > 1048576
        ):
            raise ProviderIdentityError()
        result = object.__new__(ProviderBuildIdentity)
        object.__setattr__(result, "content_bytes", raw)
        return result
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, MemoryError):
        raise ProviderIdentityError() from None


def validate_provider_schema_bytes(identity, schema_bytes):
    try:
        if (
            type(identity) is not ProviderBuildIdentity
            or type(schema_bytes) is not tuple
            or len(schema_bytes) != 4
        ):
            raise ProviderIdentityError()
        value = parse_provider_build_identity(identity.content_bytes).as_dict()
        for role, declaration, raw in zip(
            _ROLES, value["port_schemas"], schema_bytes, strict=True
        ):
            if (
                type(raw) is not bytes
                or declaration["role"] != role
                or len(raw) != declaration["size_bytes"]
                or sha256(raw).hexdigest() != declaration["sha256"]
            ):
                raise ProviderIdentityError()
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeError,
        RecursionError,
        MemoryError,
    ):
        raise ProviderIdentityError() from None
