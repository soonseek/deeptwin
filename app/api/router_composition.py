"""Frozen composition of build-installed first-party API route contributions."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from types import MappingProxyType

from fastapi import APIRouter

from .wire import WireInputError, WireLimits, parse_json_object

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_FACTORY = re.compile(r"^app\.api\.[a-z][a-z0-9_.]*:create_router$")
_ROUTE_PATH = re.compile(r"^/api/v1/[A-Za-z0-9_{}.-]+(?:/[A-Za-z0-9_{}.-]+)*$")
_METHOD_ORDER = ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT")
_METHODS = frozenset(_METHOD_ORDER)
_SCHEMA_VERSION = "deeptwin-first-party-route-contribution-v1"
_MAX_IDENTIFIER_LENGTH = 128
_MAX_FACTORY_LENGTH = 256
_MAX_ROUTE_PATH_LENGTH = 1_024
# The one descriptor policy under which a route also admits an exact TLS service-client
# bearer (contracts/api.md §1); every other policy is browser-session only.
SERVICE_BEARER_POLICY = "browser_session_or_service_bearer"
_TEMPLATE_SEGMENT = re.compile(r"^\{[a-z_][a-z0-9_]*\}$")


class RouteCompositionError(RuntimeError):
    """A descriptor/factory/route-set failed before route authority was installed."""


@dataclass(frozen=True, slots=True)
class RouteDeclaration:
    route_id: str
    methods: tuple[str, ...]
    path: str
    auth_policy: str
    required_scope: str


@dataclass(frozen=True, slots=True)
class RouteContribution:
    contribution_id: str
    factory: str
    routes: tuple[RouteDeclaration, ...]


@dataclass(frozen=True, slots=True)
class CompositionReceipt:
    contribution_ids: tuple[str, ...]
    route_ids: tuple[str, ...]
    route_count: int
    # every declared route in composition order; the web boundary reads each route's
    # declared auth policy/scope from here, never from request input
    routes: tuple[RouteDeclaration, ...] = ()

    def bearer_route(self, method: str, path: str) -> RouteDeclaration | None:
        """The declared bearer-admitting route for an exact method and routed path.

        Admits only when every declared route matching the pair admits a bearer under one
        scope, so a browser-only route can never be reached through an overlapping template.
        """
        matches = [route for route in self.routes
                   if method in route.methods and _path_matches(route.path, path)]
        if (not matches or any(route.auth_policy != SERVICE_BEARER_POLICY for route in matches)
                or len({route.required_scope for route in matches}) != 1):
            return None
        return matches[0]

    def bearer_scopes(self) -> tuple[str, ...]:
        return tuple(sorted({route.required_scope for route in self.routes
                             if route.auth_policy == SERVICE_BEARER_POLICY}))


def _path_matches(template: str, path: object) -> bool:
    if type(path) is not str:
        return False
    expected, actual = template.split("/"), path.split("/")
    if len(expected) != len(actual):
        return False
    for want, have in zip(expected, actual):
        if _TEMPLATE_SEGMENT.fullmatch(want):
            if not have:
                return False
        elif want != have:
            return False
    return True


def _closed_string_set(values: Sequence[str], *, label: str) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{label} must be a sequence")
    items = tuple(values)
    if not items or any(
        type(item) is not str
        or len(item) > _MAX_IDENTIFIER_LENGTH
        or not _IDENTIFIER.fullmatch(item)
        for item in items
    ):
        raise ValueError(f"invalid {label}")
    if len(set(items)) != len(items):
        raise ValueError(f"duplicate {label}")
    return frozenset(items)


def _valid_route_path(value: object) -> bool:
    return (
        type(value) is str
        and len(value) <= _MAX_ROUTE_PATH_LENGTH
        and _ROUTE_PATH.fullmatch(value) is not None
        and all(segment not in (".", "..") for segment in value.split("/")[3:])
    )


class FirstPartyRouteComposer:
    """Validate every fixed descriptor and factory, then mount one staged router exactly once."""

    def __init__(
        self,
        *,
        descriptor_root: Path,
        descriptor_names: Sequence[str],
        factory_allowlist: Mapping[str, Callable[[], APIRouter]],
        allowed_auth_policies: Sequence[str],
        allowed_scopes: Sequence[str],
        max_descriptor_bytes: int = 65_536,
    ) -> None:
        if not isinstance(descriptor_root, Path):
            raise TypeError("descriptor_root must be a Path")
        if isinstance(descriptor_names, (str, bytes)):
            raise TypeError("descriptor_names must be a sequence")
        names = tuple(descriptor_names)
        if not names or len(set(names)) != len(names):
            raise ValueError("descriptor names must be nonempty and unique")
        if any(
            type(name) is not str
            or Path(name).name != name
            or not name.endswith(".json")
            or len(name) > _MAX_IDENTIFIER_LENGTH + len(".json")
            or not _IDENTIFIER.fullmatch(name[:-5])
            for name in names
        ):
            raise ValueError("invalid descriptor name")
        if not isinstance(factory_allowlist, Mapping):
            raise TypeError("factory_allowlist must be a mapping")
        factories = dict(factory_allowlist)
        if any(
            type(name) is not str
            or len(name) > _MAX_FACTORY_LENGTH
            or not _FACTORY.fullmatch(name)
            or not callable(factory)
            for name, factory in factories.items()
        ):
            raise ValueError("invalid factory allowlist")
        if type(max_descriptor_bytes) is not int or max_descriptor_bytes < 1:
            raise ValueError("max_descriptor_bytes must be positive")
        self._root = descriptor_root
        self._names = names
        self._factories = MappingProxyType(factories)
        self._policies = _closed_string_set(allowed_auth_policies, label="auth policy")
        self._scopes = _closed_string_set(allowed_scopes, label="scope")
        self._max_bytes = max_descriptor_bytes
        self._receipt: CompositionReceipt | None = None
        self._compose_lock = RLock()

    def _descriptor_bytes(self, name: str) -> bytes:
        root_fd: int | None = None
        try:
            root_stat = os.lstat(self._root)
            if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
                raise RouteCompositionError("invalid descriptor root")
            root_fd = os.open(
                self._root,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            opened_root = os.fstat(root_fd)
            if (opened_root.st_dev, opened_root.st_ino) != (root_stat.st_dev, root_stat.st_ino):
                raise RouteCompositionError("descriptor root changed during validation")
            available = {
                entry for entry in os.listdir(root_fd) if entry.endswith(".json")
            }
            if available != set(self._names):
                raise RouteCompositionError("unexpected descriptor set")
            target_stat = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(target_stat.st_mode)
                or stat.S_ISLNK(target_stat.st_mode)
                or target_stat.st_nlink != 1
                or target_stat.st_size < 2
                or target_stat.st_size > self._max_bytes
            ):
                raise RouteCompositionError("invalid descriptor file")
            descriptor_fd = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_fd,
            )
            try:
                opened = os.fstat(descriptor_fd)
                stable_fields = (
                    "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns",
                )
                if any(
                    getattr(opened, field) != getattr(target_stat, field)
                    for field in stable_fields
                ):
                    raise RouteCompositionError("descriptor changed during validation")
                raw = os.read(descriptor_fd, self._max_bytes + 1)
                if len(raw) != target_stat.st_size:
                    raise RouteCompositionError("descriptor read was not exact")
                after_read = os.fstat(descriptor_fd)
                if any(
                    getattr(after_read, field) != getattr(opened, field)
                    for field in stable_fields
                ):
                    raise RouteCompositionError("descriptor changed during validation")
                return raw
            finally:
                os.close(descriptor_fd)
        except RouteCompositionError:
            raise
        except OSError:
            raise RouteCompositionError("descriptor unavailable") from None
        finally:
            if root_fd is not None:
                os.close(root_fd)

    def _parse_descriptor(self, raw: bytes) -> RouteContribution:
        try:
            value = parse_json_object(
                raw,
                required=("schema_version", "contribution_id", "factory", "routes"),
                field_types={
                    "schema_version": str,
                    "contribution_id": str,
                    "factory": str,
                    "routes": list,
                },
                limits=WireLimits(
                    max_bytes=self._max_bytes,
                    max_depth=5,
                    max_items=1_024,
                    max_members=8,
                    max_string_bytes=2_048,
                ),
            )
        except WireInputError:
            raise RouteCompositionError("invalid descriptor JSON") from None
        if (
            value["schema_version"] != _SCHEMA_VERSION
            or len(value["contribution_id"]) > _MAX_IDENTIFIER_LENGTH
            or not _IDENTIFIER.fullmatch(value["contribution_id"])
            or len(value["factory"]) > _MAX_FACTORY_LENGTH
            or not _FACTORY.fullmatch(value["factory"])
            or not 1 <= len(value["routes"]) <= 128
        ):
            raise RouteCompositionError("invalid descriptor identity")
        routes: list[RouteDeclaration] = []
        for route in value["routes"]:
            if type(route) is not dict or set(route) != {
                "route_id", "methods", "path", "auth_policy", "required_scope",
            }:
                raise RouteCompositionError("invalid route declaration")
            if (
                type(route["route_id"]) is not str
                or len(route["route_id"]) > _MAX_IDENTIFIER_LENGTH
                or not _IDENTIFIER.fullmatch(route["route_id"])
                or type(route["methods"]) is not list
                or not 1 <= len(route["methods"]) <= len(_METHODS)
                or any(type(method) is not str or method not in _METHODS for method in route["methods"])
                or route["methods"]
                != [method for method in _METHOD_ORDER if method in set(route["methods"])]
                or not _valid_route_path(route["path"])
                or type(route["auth_policy"]) is not str
                or len(route["auth_policy"]) > _MAX_IDENTIFIER_LENGTH
                or route["auth_policy"] not in self._policies
                or type(route["required_scope"]) is not str
                or len(route["required_scope"]) > _MAX_IDENTIFIER_LENGTH
                or route["required_scope"] not in self._scopes
            ):
                raise RouteCompositionError("invalid route declaration")
            routes.append(RouteDeclaration(
                route_id=route["route_id"],
                methods=tuple(route["methods"]),
                path=route["path"],
                auth_policy=route["auth_policy"],
                required_scope=route["required_scope"],
            ))
        return RouteContribution(value["contribution_id"], value["factory"], tuple(routes))

    @staticmethod
    def _route_pairs(routes: Sequence[object]) -> set[tuple[str, str]]:
        result: set[tuple[str, str]] = set()

        def walk(values: Sequence[object], prefix: str, ancestors: frozenset[int]) -> None:
            for route in values:
                route_path = getattr(route, "path", None)
                methods = getattr(route, "methods", None)
                if type(route_path) is str and isinstance(methods, (set, frozenset)):
                    for method in methods:
                        if type(method) is not str:
                            raise RouteCompositionError("factory returned an invalid method")
                        pair = (prefix + route_path, method)
                        if pair in result:
                            raise RouteCompositionError("factory returned duplicate routes")
                        result.add(pair)
                    continue

                # FastAPI keeps include_router() contributions as lazy _IncludedRouter
                # objects. Inspect only their public data shape; never execute or import them.
                original = getattr(route, "original_router", None)
                context = getattr(route, "include_context", None)
                included_prefix = getattr(context, "prefix", None)
                original_routes = getattr(original, "routes", None)
                identity = id(original)
                if (
                    not isinstance(original, APIRouter)
                    or not isinstance(original_routes, list)
                    or type(included_prefix) is not str
                    or (included_prefix and not included_prefix.startswith("/"))
                    or included_prefix.endswith("/")
                    or identity in ancestors
                ):
                    raise RouteCompositionError("factory returned an unsupported route")
                walk(original_routes, prefix + included_prefix, ancestors | {identity})

        walk(routes, "", frozenset())
        return result

    def compose(self, app: object) -> CompositionReceipt:
        with self._compose_lock:
            return self._compose_once(app)

    def _compose_once(self, app: object) -> CompositionReceipt:
        if self._receipt is not None:
            raise RouteCompositionError("route composition is frozen")
        if not callable(getattr(app, "include_router", None)) or not hasattr(app, "routes"):
            raise TypeError("app must expose a router composition surface")

        # Parse all files before calling any factory or touching the application.
        contributions = tuple(
            self._parse_descriptor(self._descriptor_bytes(name)) for name in self._names
        )
        contribution_ids = [value.contribution_id for value in contributions]
        route_ids = [route.route_id for value in contributions for route in value.routes]
        declared_pairs = [
            (route.path, method)
            for value in contributions for route in value.routes for method in route.methods
        ]
        if (
            len(set(contribution_ids)) != len(contribution_ids)
            or len(set(route_ids)) != len(route_ids)
            or len(set(declared_pairs)) != len(declared_pairs)
        ):
            raise RouteCompositionError("duplicate contribution or route")
        existing_pairs = self._route_pairs(app.routes)
        if existing_pairs & set(declared_pairs):
            raise RouteCompositionError("route collides with the application")
        if any(value.factory not in self._factories for value in contributions):
            raise RouteCompositionError("factory is not build-allowlisted")

        staged = APIRouter()
        for contribution in contributions:
            try:
                router = self._factories[contribution.factory]()
            except Exception:  # noqa: BLE001 - sanitize trusted factory failures at the seam
                raise RouteCompositionError("route factory failed") from None
            if type(router) is not APIRouter or router.on_startup or router.on_shutdown:
                raise RouteCompositionError("factory did not return a passive APIRouter")
            expected = {
                (route.path, method) for route in contribution.routes for method in route.methods
            }
            if self._route_pairs(router.routes) != expected:
                raise RouteCompositionError("factory routes do not match the descriptor")
            staged.include_router(router)

        before = tuple(app.routes)
        try:
            app.include_router(staged)
        except Exception:  # noqa: BLE001 - preserve atomicity for instrumented/future hosts
            # FastAPI route installation is ordinarily deterministic, but preserve the all-or-none
            # boundary if an instrumented or future host mutates then raises.
            router = getattr(app, "router", None)
            if router is not None and isinstance(getattr(router, "routes", None), list):
                router.routes[:] = before
            raise RouteCompositionError("route installation failed") from None
        self._receipt = CompositionReceipt(
            contribution_ids=tuple(contribution_ids),
            route_ids=tuple(route_ids),
            route_count=len(route_ids),
            routes=tuple(route for value in contributions for route in value.routes),
        )
        return self._receipt


__all__ = [
    "SERVICE_BEARER_POLICY",
    "CompositionReceipt",
    "FirstPartyRouteComposer",
    "RouteCompositionError",
    "RouteContribution",
    "RouteDeclaration",
]
