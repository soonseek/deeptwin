"""Inert, immutable projection of the original finite transport geometry."""

from dataclasses import dataclass

from jsonschema import Draft202012Validator

from app.domain.wire import WireLimits, parse_json_object
from app.operations.setup import OriginProfile

from . import contracts as sources
from .provider_source_schema_exports import provider_geometry_schema

_SEAL = object()


class ProviderGeometryError(ValueError):
    def __init__(self):
        super().__init__("invalid provider geometry")


def _decode(raw):
    try:
        schema = provider_geometry_schema()
        value = parse_json_object(raw, required=schema["required"], limits=WireLimits(
            max_bytes=65536, max_depth=12, max_items=4096, max_members=32,
            max_string_bytes=1024, max_integer=2**40))
        if sources.encode(value) != raw or not Draft202012Validator(schema).is_valid(value):
            raise ProviderGeometryError()
        profile = OriginProfile.from_dict(value["origin_profile"])
        sources.uuid(value["topology_id"])
        if (value["instance_id"] != profile.instance_id
                or value["original_recipe"]["sha256"] != sources.digest(sources.encode(sources.RECIPE))
                or sources.encode(value["slots"]) != sources.encode([
                    sources.slot(profile.instance_id, n) for n in range(1, len(value["slots"]) + 1)])):
            raise ProviderGeometryError()
        return value
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, UnicodeError):
        raise ProviderGeometryError() from None


def _stored(value):
    try:
        if type(value) is not ProviderGeometry or value._seal is not _SEAL:
            raise ProviderGeometryError()
        raw = value._content_bytes
        _decode(raw)
        return raw
    except (AttributeError, TypeError, ValueError):
        raise ProviderGeometryError() from None


@dataclass(frozen=True, slots=True, init=False)
class ProviderGeometry:
    _content_bytes: bytes
    _seal: object

    def __new__(cls):
        raise TypeError("Use parse_provider_geometry or derive_provider_geometry")

    @property
    def content_bytes(self):
        return _stored(self)

    @property
    def digest(self):
        return sources.digest(_stored(self))

    def as_dict(self):
        return _decode(_stored(self))

    def slot(self, n):
        value = _decode(_stored(self))
        if type(n) is not int or not 1 <= n <= len(value["slots"]):
            raise ProviderGeometryError()
        return value["slots"][n - 1]


def parse_provider_geometry(raw) -> ProviderGeometry:
    _decode(raw)
    result = object.__new__(ProviderGeometry)
    object.__setattr__(result, "_content_bytes", raw)
    object.__setattr__(result, "_seal", _SEAL)
    return result


def derive_provider_geometry(*, original_recipe_bytes, original_instance_bytes,
                             original_topology_bytes) -> ProviderGeometry:
    try:
        sources.parse_recipe(original_recipe_bytes)
        instance = sources.parse_instance(original_instance_bytes)
        profile = OriginProfile.from_dict(instance["origin_profile"])
        topology = sources.parse_topology(original_topology_bytes, profile=profile,
                                          recipe_sha256=sources.digest(original_recipe_bytes),
                                          platform=instance["platform"])
        if (topology["topology_id"] != instance["topology_id"]
                or len(topology["slots"]) != instance["slot_capacity"]):
            raise ProviderGeometryError()
        return parse_provider_geometry(sources.encode({
            "schema_version": "provider-stage-geometry-v1",
            "original_recipe": {"sha256": sources.digest(original_recipe_bytes), "size_bytes": len(original_recipe_bytes)},
            "original_instance": {"sha256": sources.digest(original_instance_bytes), "size_bytes": len(original_instance_bytes)},
            "original_topology": {"sha256": sources.digest(original_topology_bytes), "size_bytes": len(original_topology_bytes)},
            "origin_profile": profile.as_dict(), "instance_id": profile.instance_id,
            "topology_id": instance["topology_id"], "topology_revision": 1,
            "platform": instance["platform"], "control": dict(sources.CONTROL),
            "slots": topology["slots"],
        }))
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, UnicodeError):
        raise ProviderGeometryError() from None


def validate_provider_geometry_sources(geometry, *, original_recipe_bytes,
                                       original_instance_bytes, original_topology_bytes) -> None:
    raw = _stored(geometry)
    expected = derive_provider_geometry(original_recipe_bytes=original_recipe_bytes,
                                        original_instance_bytes=original_instance_bytes,
                                        original_topology_bytes=original_topology_bytes)
    if raw != expected.content_bytes:
        raise ProviderGeometryError()
