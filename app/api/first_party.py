"""Common startup adapter for a fixed, build-installed dependency catalog.

The context freezes dependency identities, not the services' mutable durable state.
Exports are an immutable publication, not a service locator used by factories.
"""

import inspect
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from types import MappingProxyType

from fastapi import APIRouter

from ..domain.store import DomainStore
from ..runtime.worker_dispatch import WorkerDispatchServiceSlot
from ..services.owner_auth import PersistentOwnerAuthority
from .router_composition import (
    CompositionReceipt,
    FirstPartyRouteComposer,
    RouteCompositionError,
)
from .routes import ApiV1Components, create_router


def _names(values, *, environment=False):
    pattern = r"[A-Z][A-Z0-9_]*" if environment else r"[a-z][a-z0-9._-]*"
    if (
        type(values) is not tuple
        or len(values) > 64
        or any(
            type(value) is not str
            or len(value) > 128
            or re.fullmatch(pattern, value, flags=re.ASCII) is None
            for value in values
        )
        or len(set(values)) != len(values)
    ):
        raise RouteCompositionError("invalid installed names")


def _catalog(installed):
    if type(installed) is not tuple or not installed:
        raise RouteCompositionError("invalid application contributions")
    provided, keys, factories = set(), set(), set()
    for entry in installed:
        if type(entry) is not InstalledContribution:
            raise RouteCompositionError("invalid installed contribution")
        for names in (entry.requires, entry.provides):
            _names(names)
        _names(entry.startup_keys, environment=True)
        if (
            entry.factory_name in factories
            or not set(entry.requires) <= provided
            or provided.intersection(entry.provides)
            or keys.intersection(entry.startup_keys)
        ):
            raise RouteCompositionError("invalid dependency catalog")
        factories.add(entry.factory_name)
        provided.update(entry.provides)
        keys.update(entry.startup_keys)
        if len(keys) > 64:
            raise RouteCompositionError("too many startup keys")


@dataclass(frozen=True, slots=True)
class StartupInputs:
    values: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    invalid_keys: tuple[str, ...] = ()
    protected_roots: tuple[Path, ...] = ()

    def __post_init__(self):
        if not isinstance(self.values, Mapping):
            raise TypeError("invalid startup inputs")
        _names(tuple(self.values), environment=True)
        _names(self.invalid_keys, environment=True)
        if set(self.values).intersection(self.invalid_keys):
            raise ValueError("invalid startup inputs")
        try:
            if any(
                type(v) is not str or len(v.encode("utf-8")) > 256
                for v in self.values.values()
            ):
                raise ValueError("invalid startup inputs")
            if (
                type(self.protected_roots) is not tuple
                or len(self.protected_roots) > 64
                or any(
                    not isinstance(p, Path)
                    or not p.is_absolute()
                    or ".." in p.parts
                    or not 1 <= len(str(p).encode("utf-8")) <= 4096
                    for p in self.protected_roots
                )
            ):
                raise ValueError("invalid protected roots")
        except UnicodeError:
            raise ValueError("invalid startup inputs") from None
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        object.__setattr__(
            self, "protected_roots", tuple(dict.fromkeys(self.protected_roots))
        )


def build_startup_inputs(*, values, protected_roots):
    from .first_party_catalog import INSTALLED

    _catalog(INSTALLED)
    keys = tuple(key for entry in INSTALLED for key in entry.startup_keys)
    if values is not None and (
        not isinstance(values, Mapping) or any(key not in keys for key in values)
    ):
        raise ValueError("invalid startup configuration")
    source = os.environ if values is None else values
    accepted, invalid = {}, []
    for key in keys:
        try:
            value = source[key]
        except KeyError:
            continue
        try:
            valid = type(value) is str and len(value.encode("utf-8")) <= 256
        except UnicodeError:
            valid = False
        if valid:
            accepted[key] = value
        else:
            invalid.append(key)
    if type(protected_roots) is not tuple:
        raise ValueError("invalid protected roots")
    # Bound the final unique lexical tuple; do not resolve filesystem aliases.
    roots = tuple(dict.fromkeys(protected_roots))
    return StartupInputs(accepted, tuple(invalid), roots)


@dataclass(frozen=True, slots=True)
class ApplicationContext:
    components: ApiV1Components
    owner_authority: PersistentOwnerAuthority
    base_path: str
    runtime_dispatch_resolver: Callable | None = None
    worker_dispatch_slot: WorkerDispatchServiceSlot | None = None
    startup_inputs: StartupInputs = field(default_factory=StartupInputs)
    # the code-owned run executor (compilation authority + handler registry);
    # trusted host wiring, never page input; None leaves the run routes unavailable
    run_executor: object | None = None
    # the credential gateway attachment (ledger + frame-only client) the host opened
    # from the deployment's named endpoint; None composes the credential routes unbound
    credential_gateway: object | None = None
    # the backup-crypto worker client the host opened from the deployment's named
    # `cp-backup` endpoint; None composes the backup routes with an honest unavailable
    backup_worker: object | None = None

    def __post_init__(self):
        from ..workers.backup_crypto_client import BackupCryptoClient
        from .credential_wiring import CredentialAttachment

        if (
            type(self.components) is not ApiV1Components
            or type(self.startup_inputs) is not StartupInputs
            or type(self.owner_authority) is not PersistentOwnerAuthority
            or self.owner_authority._domain is not self.components.domain_store
            or self.base_path != self.owner_authority.profile.base_path
            or (
                self.runtime_dispatch_resolver is not None
                and not callable(self.runtime_dispatch_resolver)
            )
            or (
                self.run_executor is not None
                and not (callable(getattr(self.run_executor, "compile", None))
                         and callable(getattr(self.run_executor, "scheduler", None)))
            )
            or (
                self.credential_gateway is not None
                and type(self.credential_gateway) is not CredentialAttachment
            )
            or (
                self.backup_worker is not None
                and type(self.backup_worker) is not BackupCryptoClient
            )
        ):
            raise TypeError(
                "Application dependencies do not share the actual authority"
            )

    @property
    def domain_store(self) -> DomainStore:
        return self.components.domain_store


@dataclass(frozen=True, slots=True)
class ContributionServices:
    router: APIRouter
    exports: Mapping[str, object]
    owned_resources: tuple[object, ...] = ()

    def __post_init__(self):
        if type(self.owned_resources) is not tuple:
            raise TypeError("Owned resources must be a tuple")
        object.__setattr__(self, "exports", MappingProxyType(dict(self.exports)))


@dataclass(frozen=True, slots=True)
class InstalledContribution:
    descriptor_name: str
    factory_name: str
    factory: Callable[[ApplicationContext], ContributionServices]
    auth_policies: tuple[str, ...]
    scopes: tuple[str, ...]
    requires: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    startup_keys: tuple[str, ...] = ()
    startup_reconcile: Callable | None = None

    def __post_init__(self):
        if (
            type(self.auth_policies) is not tuple
            or type(self.scopes) is not tuple
            or not callable(self.factory)
            or (
                self.startup_reconcile is not None
                and not inspect.isfunction(self.startup_reconcile)
            )
        ):
            raise TypeError(
                "Installed declarations must be frozen with a concrete factory"
            )


class _ResourceOwner:
    def __init__(self):
        self.resources, self.identities = [], set()
        self.closed = False

    def adopt(self, resources):
        if type(resources) is not tuple:
            raise RouteCompositionError("invalid owned resources")
        invalid = False
        for resource in resources:
            if id(resource) in self.identities or not callable(
                getattr(resource, "close", None)
            ):
                invalid = True
                continue
            self.identities.add(id(resource))
            self.resources.append(resource)
        if invalid:
            raise RouteCompositionError("invalid owned resources")

    def close(self):
        active = sys.exception()
        if self.closed:
            return
        self.closed = True
        failed = False
        for resource in reversed(self.resources):
            try:
                resource.close()
            except BaseException:  # noqa: BLE001 - cleanup must attempt every owner
                failed = True
        self.resources.clear()
        if failed and active is None:
            raise RouteCompositionError("contribution cleanup failed") from None


@dataclass(frozen=True, slots=True)
class FirstPartyPublication:
    receipt: CompositionReceipt
    exports: Mapping[str, object]
    _owner: _ResourceOwner = field(repr=False)
    _activations: tuple = field(repr=False)
    _lock: object = field(default_factory=RLock, repr=False)
    _activated: bool = field(default=False, init=False, repr=False)

    def activate_startup(self):
        with self._lock:
            if self._owner.closed or self._activated:
                raise RouteCompositionError("startup activation is frozen")
            object.__setattr__(self, "_activated", True)
            try:
                for function, exports in self._activations:
                    if inspect.iscoroutinefunction(
                        function
                    ) or inspect.isasyncgenfunction(function):
                        raise RouteCompositionError("invalid startup activation")
                    value = function(exports)
                    if value is not None:
                        if inspect.iscoroutine(value):
                            value.close()
                        raise RouteCompositionError("invalid startup activation")
            except Exception:  # noqa: BLE001 - closed host activation diagnostics
                raise RouteCompositionError("startup activation failed") from None

    def close(self):
        with self._lock:
            self._owner.close()


def core_services(context):
    return ContributionServices(
        create_router(
            components=context.components,
            runtime_dispatch_resolver=context.runtime_dispatch_resolver,
            worker_dispatch_slot=context.worker_dispatch_slot,
            base_path=context.base_path,
        ),
        {},
    )


class FirstPartyApplicationComposer:
    """One startup attempt; no late registration, hooks or external loaders."""

    def __init__(self, *, context, descriptor_root, installed):
        if (
            type(context) is not ApplicationContext
            or type(installed) is not tuple
            or not installed
        ):
            raise RouteCompositionError("invalid application contributions")
        _catalog(installed)
        self._context, self._installed, self._root = context, installed, descriptor_root
        self._attempted = False

    def compose(self, app):
        if self._attempted:
            raise RouteCompositionError("application composition is frozen")
        self._attempted = True
        exports, called, activations = {}, set(), []
        owner = _ResourceOwner()

        def bind(entry):
            def build():
                if entry.factory_name in called:
                    raise RouteCompositionError("dependency factory reused")
                # The route composer visits descriptor_names in their fixed order.
                # Bind each file to its own factory, not merely a shared allowlist.
                if entry is not self._installed[len(called)]:
                    raise RouteCompositionError(
                        "descriptor dependency factory mismatch"
                    )
                called.add(entry.factory_name)
                if entry.requires:
                    dependencies = MappingProxyType(
                        {name: exports[name] for name in entry.requires}
                    )
                    services = entry.factory(self._context, dependencies=dependencies)
                else:
                    services = entry.factory(self._context)
                if type(services) is not ContributionServices:
                    raise RouteCompositionError("invalid contribution services")
                owner.adopt(services.owned_resources)
                if set(services.exports) != set(entry.provides):
                    raise RouteCompositionError(
                        "service exports differ from declaration"
                    )
                exports.update(services.exports)
                if entry.startup_reconcile is not None:
                    activations.append((entry.startup_reconcile, services.exports))
                return services.router

            return build

        composer = FirstPartyRouteComposer(
            descriptor_root=self._root,
            descriptor_names=tuple(entry.descriptor_name for entry in self._installed),
            factory_allowlist={
                entry.factory_name: bind(entry) for entry in self._installed
            },
            allowed_auth_policies=tuple(
                dict.fromkeys(
                    policy
                    for entry in self._installed
                    for policy in entry.auth_policies
                )
            ),
            allowed_scopes=tuple(
                dict.fromkeys(
                    scope for entry in self._installed for scope in entry.scopes
                )
            ),
        )
        try:
            receipt = composer.compose(app)
            return FirstPartyPublication(
                receipt, MappingProxyType(exports), owner, tuple(activations)
            )
        except BaseException:
            owner.close()
            raise


def compose_first_party(app, context):
    # Imported fixed code, never resolved from user configuration or descriptor text.
    from .first_party_catalog import INSTALLED

    return FirstPartyApplicationComposer(
        context=context,
        descriptor_root=Path(__file__).with_name("route_contributions"),
        installed=INSTALLED,
    ).compose(app)
