"""Presentation-independent command port shared by browser and optional clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
import re

from ..domain.events import EVENT_TYPES
from ..domain.refs import MAX_INTEGER, canonical_json, parse_canonical, uuid_string
from ..domain.schemas import Actor


_COMMAND_FIELDS = frozenset({
    "schema_version", "command_id", "command_type", "target_id", "expected_revision", "args",
})
_COMMAND_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\.[a-z][a-z0-9_]{0,63}")
COMMAND_DENIAL_REASONS = frozenset({
    "invalid_command", "invalid_principal", "unregistered_command", "deployment_only",
    "human_only", "scope", "deployment_authority", "engine_contract", "target_mismatch",
    "revision_mismatch", "event_unregistered", "transport", "principal_expired", "clock",
    "engine_failure",
})


class CommandServiceDenied(PermissionError):
    pass


@dataclass(frozen=True, slots=True, init=False)
class CanonicalClientCommand:
    command_id: str
    command_type: str
    target_id: str
    expected_revision: int
    _arguments: bytes = field(repr=False)

    def __new__(cls):
        raise TypeError("Use CanonicalClientCommand.from_mapping")

    @classmethod
    def from_mapping(cls, value):
        if type(value) is not dict or set(value) != _COMMAND_FIELDS:
            raise CommandServiceDenied("Client command must match its exact schema")
        if value["schema_version"] != "client-command-v1":
            raise CommandServiceDenied("Unsupported client command version")
        try:
            command_id = uuid_string(value["command_id"])
            target_id = uuid_string(value["target_id"])
        except (TypeError, ValueError) as exc:
            raise CommandServiceDenied("Client command identity is invalid") from exc
        name = value["command_type"]
        revision = value["expected_revision"]
        if type(name) is not str or _COMMAND_NAME.fullmatch(name) is None:
            raise CommandServiceDenied("Client command type is invalid")
        if type(revision) is not int or not 1 <= revision <= MAX_INTEGER:
            raise CommandServiceDenied("Client command revision is invalid")
        if type(value["args"]) is not dict:
            raise CommandServiceDenied("Client command arguments must be an object")
        try:
            arguments = canonical_json(value["args"])
        except ValueError as exc:
            raise CommandServiceDenied("Client command arguments are invalid") from exc
        result = object.__new__(cls)
        for field, item in (
            ("command_id", command_id), ("command_type", name), ("target_id", target_id),
            ("expected_revision", revision), ("_arguments", arguments),
        ):
            object.__setattr__(result, field, item)
        return result

    @property
    def arguments(self):
        return MappingProxyType(parse_canonical(self._arguments))

    def as_dict(self):
        return {
            "schema_version": "client-command-v1", "command_id": self.command_id,
            "command_type": self.command_type, "target_id": self.target_id,
            "expected_revision": self.expected_revision, "args": dict(self.arguments),
        }

    @property
    def body_bytes(self):
        return canonical_json(self.as_dict())


@dataclass(frozen=True, slots=True)
class CommandPrincipal:
    actor: Actor
    scopes: tuple[str, ...]
    expires_at: int
    human_authority: bool
    deployment_authority: bool

    def __post_init__(self):
        if (type(self.actor) is not Actor or type(self.scopes) is not tuple
                or type(self.expires_at) is not int or not 1 <= self.expires_at <= MAX_INTEGER
                or type(self.human_authority) is not bool
                or type(self.deployment_authority) is not bool
                or self.deployment_authority):
            raise CommandServiceDenied("Product command principal is invalid")
        if self.actor.kind == "human":
            if not self.human_authority or self.scopes:
                raise CommandServiceDenied("Human command principal is inconsistent")
        elif self.actor.kind == "service_client":
            if self.human_authority or not self.scopes:
                raise CommandServiceDenied("Service command principal is inconsistent")
        else:
            raise CommandServiceDenied("Actor kind cannot submit product commands")

    @classmethod
    def human(cls, actor, *, expires_at=MAX_INTEGER):
        if type(actor) is not Actor or actor.kind != "human":
            raise CommandServiceDenied("Authenticated human principal required")
        return cls(actor, (), expires_at, True, False)

    @classmethod
    def service_client(cls, *, client_id, scopes, expires_at):
        try:
            actor = Actor(uuid_string(client_id), "service_client", "service_credential")
        except (TypeError, ValueError) as exc:
            raise CommandServiceDenied("Service client principal is invalid") from exc
        if (type(scopes) not in (tuple, list) or not scopes
                or any(type(item) is not str for item in scopes)):
            raise CommandServiceDenied("Service client scopes are invalid")
        return cls(actor, tuple(scopes), expires_at, False, False)


def _deep_freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_deep_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True, init=False)
class CommandMutation:
    object_id: str
    revision: int
    event_type: str
    authority_class: str
    _projection: bytes = field(repr=False)

    def __init__(self, *, object_id, revision, event_type, authority_class, projection):
        object_id = uuid_string(object_id)
        if type(revision) is not int or not 1 <= revision <= MAX_INTEGER:
            raise ValueError("Mutation revision is invalid")
        if (type(event_type) is not str or _COMMAND_NAME.fullmatch(event_type) is None
                or authority_class not in {"ordinary_scoped", "human_only"}
                or type(projection) is not dict):
            raise ValueError("Mutation contract is invalid")
        encoded = canonical_json(projection)
        for name, value in (
            ("object_id", object_id), ("revision", revision), ("event_type", event_type),
            ("authority_class", authority_class), ("_projection", encoded),
        ):
            object.__setattr__(self, name, value)

    @property
    def projection(self):
        return _deep_freeze(parse_canonical(self._projection))

    def projection_copy(self):
        return parse_canonical(self._projection)


class CommandService:
    """Apply one policy before delegating to a trusted state/event engine."""

    def __init__(self, *, engine, policies, denial_sink, clock):
        if not callable(getattr(engine, "execute", None)):
            raise TypeError("Command engine must expose execute")
        if (type(policies) is not dict or not policies
                or any(type(name) is not str or _COMMAND_NAME.fullmatch(name) is None
                       or policy not in {"ordinary_scoped", "human_only", "deployment_only"}
                       for name, policy in policies.items())):
            raise TypeError("Command policies must be an exact trusted mapping")
        if not callable(denial_sink) or not callable(clock):
            raise TypeError("Command service requires a trusted denial sink and clock")
        self._engine = engine
        self._policies = policies.copy()
        self._denial_sink = denial_sink
        self._clock = clock
        self._last_now = None

    def _deny(self, reason_code, message):
        if reason_code not in COMMAND_DENIAL_REASONS:
            raise RuntimeError("Unregistered command denial reason")
        try:
            recorded = self._denial_sink(reason_code)
        except Exception:
            raise CommandServiceDenied("Command denial audit sink failed") from None
        if recorded is not True:
            raise CommandServiceDenied("Command denial audit sink failed")
        raise CommandServiceDenied(message)

    def _now(self):
        failed = False
        value = None
        try:
            value = self._clock()
        except Exception:
            failed = True
        if (failed or type(value) is not int or not 0 <= value <= MAX_INTEGER
                or (self._last_now is not None and value < self._last_now)):
            self._deny("clock", "Trusted command clock is unavailable")
        self._last_now = value
        return value

    def deny_delivery(self):
        """Record a delivery/authentication preflight denial without parsing a command."""
        self._deny("transport", "Command delivery preflight was denied")

    def submit_mapping(self, value, principal):
        try:
            command = CanonicalClientCommand.from_mapping(value)
        except CommandServiceDenied:
            self._deny("invalid_command", "Client command is invalid")
        return self.submit(command, principal)

    def submit(self, command, principal):
        if type(command) is not CanonicalClientCommand:
            self._deny("invalid_command", "Canonical command required")
        try:
            command = CanonicalClientCommand.from_mapping(parse_canonical(command.body_bytes))
        except (CommandServiceDenied, ValueError):
            self._deny("invalid_command", "Canonical command required")
        if type(principal) is not CommandPrincipal or type(principal.actor) is not Actor:
            self._deny("invalid_principal", "Authenticated command principal required")
        if self._now() >= principal.expires_at:
            self._deny("principal_expired", "Command principal has expired")
        try:
            policy = self._policies[command.command_type]
        except KeyError:
            self._deny("unregistered_command", "Command type is not registered")
        if policy == "deployment_only":
            self._deny("deployment_only", "Product clients have no deployment authority")
        if policy == "human_only":
            if not principal.human_authority or principal.actor.kind != "human":
                self._deny("human_only", "Command requires human authority")
        elif principal.actor.kind == "service_client" \
                and f"command:{command.command_type}" not in principal.scopes:
            self._deny("scope", "Command is outside the service client scope")
        if principal.deployment_authority:
            self._deny(
                "deployment_authority",
                "Product command principal cannot hold deployment authority",
            )
        engine_failed = False
        mutation = None
        try:
            mutation = self._engine.execute(command, principal)
        except Exception:
            engine_failed = True
        if engine_failed:
            self._deny("engine_failure", "Command engine failed")
        if type(mutation) is not CommandMutation or mutation.authority_class != policy:
            self._deny("engine_contract", "Command engine returned an invalid authority contract")
        if mutation.object_id != command.target_id:
            self._deny("target_mismatch", "Command engine returned a mutation for another target")
        if mutation.revision != command.expected_revision + 1:
            self._deny("revision_mismatch", "Command engine returned an invalid next revision")
        if mutation.event_type not in EVENT_TYPES:
            self._deny("event_unregistered", "Command engine returned an unregistered event type")
        return {
            "command_id": command.command_id,
            "object_id": mutation.object_id,
            "revision": mutation.revision,
            "event_type": mutation.event_type,
            "authority_class": mutation.authority_class,
            "actor_kind": principal.actor.kind,
            "projection": mutation.projection_copy(),
        }
