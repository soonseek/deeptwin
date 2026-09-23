"""Tool dispatcher boundary: closed registry, grants, effects, replay
(US3, T047 core slice; runtime.md §6, FR-014/FR-032).

The dispatcher, not the model, maps tool ids to code: an unregistered tool
or an unknown version is unsupported — never interpreted from anything a
model or extension outputs — and nothing outside :func:`register_tool` can
add a tool or widen its declared argument profile. Tool arguments carry no
artifact or selector refs (the ordered artifact-input bindings are the sole
byte-input authority) and no host paths. The required grant must match the
definition exactly; the ports contract's external family of effects (external
and instance-critical) requires an explicit effect approval; the declared
replay policy is authoritative — a
`replay="never"` request never re-dispatches, a dedup tool returns its original
envelope; and an unknown external outcome holds the request, blocking every
retry until a real reconciliation records the final outcome. Values are
issued, never constructed; the registry is an immutable value, so
single-writer transactions belong to the storage layer.

An admitted envelope is also the only key to a tool's side channels.
`open_in_scope` opens a file under one of the tool's declared filesystem scopes
from an already-open scope directory, one component at a time with
`O_NOFOLLOW` (no absolute, empty, `.` or `..` component, no symlink at any
depth, no hardlinked or non-regular target), so a path swapped for a symlink
mid-walk refuses instead of escaping; writes create exclusively.
`admit_network` lets a request reach only an exact host the tool declared,
and the fetch itself then goes through the egress broker's frozen policy
(public addresses only, pinned resolution, revalidated redirects).
`admit_tool_result` bounds a result by the tool's byte cap, refuses active
renderable content (HTML, SVG, script) outright and sniffs every declared
document format through the document adapter, so a tool can never hand a
renderer something other than what it declared.
"""

from __future__ import annotations

import errno
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field

from ..domain.refs import DomainContractError, EntityRef
from ..extensions import port_contracts
from .egress import EgressBrokerError, EgressPolicy, broker_fetch
from .gateway import carries_host_path

# the effect vocabulary is the ports contract's closed set (extension-ports.md `effect-class`;
# runtime.md §6), the one set the ledger's ToolCall and the extension transport's gate share;
# this boundary's earlier four names (read/write/external/irreversible) are refused — a
# legacy `external` never stated reversibility, and a second spelling would shadow the set
EFFECT_CLASSES = port_contracts.EFFECT_CLASSES
# the ports' external family (X): external and instance-critical effects need an explicit approval
APPROVAL_EFFECTS = frozenset(
    name for name, family in port_contracts.EFFECT_FAMILIES.items() if family == "X"
)
IDEMPOTENCY = frozenset({"idempotent", "dedup_by_request", "none"})
REPLAY_POLICIES = frozenset({"safe", "requires_confirmation", "never"})
OUTCOMES = frozenset({"succeeded", "failed", "unknown"})
_ARGUMENT_TYPES = {"str": str, "int": int, "bool": bool}
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ISSUE_TOKEN = object()


class ToolBoundaryError(ValueError):
    """A registration, dispatch or outcome record is invalid."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _ref(value, kind, label):
    try:
        result = EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise ToolBoundaryError(f"invalid {label} reference") from exc
    if result.kind != kind:
        raise ToolBoundaryError(f"invalid {label} reference kind")
    return result


def _text(value, label, maximum=128):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        raise ToolBoundaryError(f"{label} is out of bounds")
    return value


@dataclass(frozen=True, slots=True, init=False)
class ToolDefinition:
    """One registered tool; the dispatcher maps its id to code, not the model."""

    tool_id: str
    version: int
    argument_keys: tuple[tuple[str, str], ...]
    result_schema_id: str
    effect_class: str
    required_grant: EntityRef
    filesystem_scopes: tuple[str, ...]
    network_scopes: tuple[str, ...]
    timeout_seconds: int
    max_result_bytes: int
    idempotency: str
    replay: str
    implementation_sha256: str
    qualification_ref: EntityRef


@dataclass(frozen=True, slots=True, init=False)
class DispatchEnvelope:
    """The framework-owned fact of one admitted dispatch."""

    request_id: str
    tool_id: str
    version: int
    effect_class: str
    arguments: tuple[tuple[str, object], ...]
    artifact_inputs: tuple[EntityRef, ...]
    grant_ref: EntityRef
    effect_approval_ref: EntityRef | None
    deadline_seconds: int
    _issuer_token: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True, init=False)
class ToolRegistry:
    """The closed registry plus every dispatched request's outcome state."""

    definitions: tuple[ToolDefinition, ...]
    # (request_id, tool_id, version, outcome|None, envelope)
    dispatched: tuple[tuple[str, str, int, str | None, DispatchEnvelope], ...]
    _issuer_token: object = field(repr=False, compare=False)


def _require_registry(value) -> None:
    if (
        type(value) is not ToolRegistry
        or getattr(value, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise ToolBoundaryError("a framework-issued tool registry is required")


def open_tool_registry() -> ToolRegistry:
    return _issue(
        ToolRegistry, definitions=(), dispatched=(),
        _issuer_token=_ISSUE_TOKEN,
    )


def register_tool(registry, value) -> ToolRegistry:
    """Register one tool exactly once; nothing else ever adds a tool."""

    _require_registry(registry)
    if type(value) is not dict or set(value) != {
        "tool_id", "version", "argument_keys", "result_schema_id",
        "effect_class", "required_grant", "filesystem_scopes",
        "network_scopes", "timeout_seconds", "max_result_bytes",
        "idempotency", "replay", "implementation_sha256",
        "qualification_ref",
    }:
        raise ToolBoundaryError("expected the exact tool definition object")
    tool_id = _text(value["tool_id"], "tool id")
    version = value["version"]
    if type(version) is not int or not 1 <= version <= 1_000_000:
        raise ToolBoundaryError("tool version is out of bounds")
    if any(
        item.tool_id == tool_id and item.version == version
        for item in registry.definitions
    ):
        raise ToolBoundaryError("a tool id/version registers exactly once")
    effect_class = value["effect_class"]
    if type(effect_class) is not str or effect_class not in EFFECT_CLASSES:
        raise ToolBoundaryError("unknown tool effect class")
    if value["idempotency"] not in IDEMPOTENCY:
        raise ToolBoundaryError("unknown idempotency behavior")
    if value["replay"] not in REPLAY_POLICIES:
        raise ToolBoundaryError("unknown replay policy")
    sha = value["implementation_sha256"]
    if type(sha) is not str or _SHA256.fullmatch(sha) is None:
        raise ToolBoundaryError("implementation hash is invalid")
    keys_value = value["argument_keys"]
    if (
        type(keys_value) is not dict or len(keys_value) > 32
        or any(
            type(name) is not str
            or not 1 <= len(name.encode("utf-8")) <= 128
            or kind not in _ARGUMENT_TYPES
            for name, kind in keys_value.items()
        )
        or any(name.endswith(("_ref", "_refs")) for name in keys_value)
    ):
        raise ToolBoundaryError("argument keys are out of bounds")
    for label, scopes, bound in (
        ("filesystem scope", value["filesystem_scopes"], 16),
        ("network scope", value["network_scopes"], 16),
    ):
        if type(scopes) is not list or len(scopes) > bound or any(
            type(item) is not str
            or (label == "filesystem scope" and carries_host_path(item))
            for item in scopes
        ):
            raise ToolBoundaryError(f"{label}s are out of bounds")
    timeout = value["timeout_seconds"]
    if type(timeout) is not int or not 1 <= timeout <= 3_600:
        raise ToolBoundaryError("the timeout is out of bounds")
    max_bytes = value["max_result_bytes"]
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1_073_741_824:
        raise ToolBoundaryError("the result byte cap is out of bounds")
    tool = _issue(
        ToolDefinition,
        tool_id=tool_id,
        version=version,
        argument_keys=tuple(sorted(keys_value.items())),
        result_schema_id=_text(value["result_schema_id"], "result schema id"),
        effect_class=effect_class,
        required_grant=_ref(value["required_grant"], "grant", "required grant"),
        filesystem_scopes=tuple(value["filesystem_scopes"]),
        network_scopes=tuple(value["network_scopes"]),
        timeout_seconds=timeout,
        max_result_bytes=max_bytes,
        idempotency=value["idempotency"],
        replay=value["replay"],
        implementation_sha256=sha,
        qualification_ref=_ref(
            value["qualification_ref"], "extension_qualification",
            "qualification",
        ),
    )
    return _issue(
        ToolRegistry,
        definitions=(*registry.definitions, tool),
        dispatched=registry.dispatched,
        _issuer_token=_ISSUE_TOKEN,
    )


def _validate_arguments(tool: ToolDefinition, arguments) -> tuple:
    if type(arguments) is not dict:
        raise ToolBoundaryError("tool arguments must be an object")
    declared = dict(tool.argument_keys)
    if set(arguments) != set(declared):
        # Nothing widens the declared input profile at dispatch time.
        raise ToolBoundaryError(
            "arguments must match the declared keys exactly"
        )
    parsed = []
    for name in sorted(arguments):
        item = arguments[name]
        expected = _ARGUMENT_TYPES[declared[name]]
        if type(item) is not expected:
            raise ToolBoundaryError(f"argument {name!r} has the wrong type")
        if type(item) is str:
            if len(item.encode("utf-8")) > 4_096:
                raise ToolBoundaryError(f"argument {name!r} is out of bounds")
            if carries_host_path(item):
                # An argument never smuggles a host path into authority.
                raise ToolBoundaryError(f"argument {name!r} carries a host path")
        parsed.append((name, item))
    return tuple(parsed)


def dispatch_tool(registry, value):
    """Admit one dispatch against the closed registry, or refuse."""

    _require_registry(registry)
    if type(value) is not dict or set(value) != {
        "tool_id", "version", "request_id", "arguments", "grant_ref",
        "effect_approval_ref", "artifact_inputs",
    }:
        raise ToolBoundaryError("expected the exact dispatch request object")
    tool = next(
        (
            item for item in registry.definitions
            if item.tool_id == value["tool_id"]
            and item.version == value["version"]
        ),
        None,
    )
    if tool is None:
        # Absent or mismatched: unsupported, never interpreted.
        raise ToolBoundaryError("the requested tool/version is unsupported")
    request_id = value["request_id"]
    if type(request_id) is not str or _UUID.fullmatch(request_id) is None:
        raise ToolBoundaryError("request id is not a canonical UUID")
    arguments = _validate_arguments(tool, value["arguments"])
    grant = _ref(value["grant_ref"], "grant", "grant")
    if grant != tool.required_grant:
        raise ToolBoundaryError("the grant does not match this tool")
    approval = value["effect_approval_ref"]
    parsed_approval = None
    if tool.effect_class in APPROVAL_EFFECTS:
        if approval is None:
            raise ToolBoundaryError(
                f"a {tool.effect_class} effect requires an explicit approval"
            )
        parsed_approval = _ref(approval, "action_approval", "effect approval")
    elif approval is not None:
        raise ToolBoundaryError(
            "this effect class carries no approval requirement"
        )
    previous = next(
        (item for item in registry.dispatched if item[0] == request_id),
        None,
    )
    if previous is not None:
        stored = previous[4]
        if previous[3] == "unknown":
            # An unknown external outcome holds the request entirely.
            raise ToolBoundaryError(
                "this request's outcome is unknown; reconcile before retry"
            )
        if (
            stored.tool_id != tool.tool_id
            or stored.version != tool.version
            or stored.arguments != arguments
            or stored.grant_ref != grant
            or stored.effect_approval_ref != parsed_approval
        ):
            # A reused request id must BE the same request: anything else
            # is laundering a different act under an old identity.
            raise ToolBoundaryError(
                "the reused request id does not match its original dispatch"
            )
        if tool.idempotency == "dedup_by_request":
            return stored, registry
        raise ToolBoundaryError(
            "this request was already dispatched and never replays"
        )
    inputs_value = value["artifact_inputs"]
    if type(inputs_value) is not list or len(inputs_value) > 64:
        raise ToolBoundaryError("artifact inputs are out of bounds")
    inputs = tuple(
        _ref(item, "artifact", "artifact input") for item in inputs_value
    )
    envelope = _issue(
        DispatchEnvelope,
        request_id=request_id,
        tool_id=tool.tool_id,
        version=tool.version,
        effect_class=tool.effect_class,
        arguments=arguments,
        artifact_inputs=inputs,
        grant_ref=grant,
        effect_approval_ref=parsed_approval,
        deadline_seconds=tool.timeout_seconds,
        _issuer_token=_ISSUE_TOKEN,
    )
    return envelope, _issue(
        ToolRegistry,
        definitions=registry.definitions,
        dispatched=(
            *registry.dispatched,
            (request_id, tool.tool_id, tool.version, None, envelope),
        ),
        _issuer_token=_ISSUE_TOKEN,
    )


def record_outcome(registry, request_id, outcome) -> ToolRegistry:
    """Record one final (or unknown) outcome; final outcomes never change."""

    _require_registry(registry)
    if outcome not in OUTCOMES:
        raise ToolBoundaryError("unknown dispatch outcome")
    entries = []
    touched = False
    for entry in registry.dispatched:
        if entry[0] == request_id:
            if entry[3] is not None and entry[3] != "unknown":
                raise ToolBoundaryError("a final outcome never changes")
            if outcome == "unknown" and port_contracts.EFFECT_FAMILIES[entry[4].effect_class] == "N":
                # the ports forbid an unknown effect for the N family: nothing external
                # could be in doubt, so nothing is held
                raise ToolBoundaryError("a no-effect or read tool has no unknown outcome")
            entry = (entry[0], entry[1], entry[2], outcome, entry[4])
            touched = True
        entries.append(entry)
    if not touched:
        raise ToolBoundaryError("unknown request id")
    return _issue(
        ToolRegistry,
        definitions=registry.definitions,
        dispatched=tuple(entries),
        _issuer_token=_ISSUE_TOKEN,
    )


def _admitted(registry, envelope) -> ToolDefinition:
    _require_registry(registry)
    if (
        type(envelope) is not DispatchEnvelope
        or getattr(envelope, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise ToolBoundaryError("a framework-issued dispatch envelope is required")
    entry = next((item for item in registry.dispatched if item[0] == envelope.request_id), None)
    if entry is None or entry[4] is not envelope or entry[3] is not None:
        # only a dispatch still in flight reaches its side channels
        raise ToolBoundaryError("the envelope is not an in-flight dispatch of this registry")
    return next(item for item in registry.definitions
                if item.tool_id == envelope.tool_id and item.version == envelope.version)


_MAX_COMPONENTS = 32
_COMPONENT = re.compile(r"[^/\x00]{1,255}\Z")


def _components(relative) -> list[str]:
    if type(relative) is not str or not 1 <= len(relative.encode("utf-8")) <= 1_024:
        raise ToolBoundaryError("the scoped path is out of bounds")
    if relative.startswith("/") or carries_host_path(relative):
        raise ToolBoundaryError("the scoped path is not relative to its scope")
    parts = relative.split("/")
    if len(parts) > _MAX_COMPONENTS or any(
            part in {"", ".", ".."} or _COMPONENT.fullmatch(part) is None for part in parts):
        raise ToolBoundaryError("the scoped path has an empty, dot or invalid component")
    return parts


def open_in_scope(registry, envelope, scope, scope_fd, relative, *, write=False, _between=None):
    """A descriptor for one file beneath a declared scope, or a refusal.

    `scope_fd` is the directory the worker opened for `scope`; nothing here
    resolves a host path. `_between` is a test seam called between components.
    """

    tool = _admitted(registry, envelope)
    if type(scope) is not str or scope not in tool.filesystem_scopes:
        raise ToolBoundaryError("the tool declared no such filesystem scope")
    if write and tool.effect_class not in _WRITING_EFFECTS:
        raise ToolBoundaryError("a read-only tool cannot write in its scope")
    parts = _components(relative)
    try:
        if not stat.S_ISDIR(os.fstat(scope_fd).st_mode):
            raise ToolBoundaryError("the scope descriptor is not a directory")
    except (OSError, TypeError):
        raise ToolBoundaryError("the scope descriptor is not open") from None
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    current = scope_fd
    opened = []
    try:
        for part in parts[:-1]:
            if _between is not None:
                _between(part)
            current = os.open(part, directory_flags, dir_fd=current)
            opened.append(current)
        if _between is not None:
            _between(parts[-1])
        if write:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            descriptor = os.open(parts[-1], flags, 0o600, dir_fd=current)
        else:
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
            descriptor = os.open(parts[-1], flags, dir_fd=current)
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR, errno.EMLINK}:
            raise ToolBoundaryError("a symlink or non-directory lies on the scoped path") from None
        if error.errno == errno.EEXIST:
            raise ToolBoundaryError("a scoped write never replaces an existing file") from None
        raise ToolBoundaryError("the scoped path cannot be opened") from None
    finally:
        for item in opened:
            os.close(item)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(descriptor)
        # a hardlink could alias a file outside the scope; devices and fifos never read
        raise ToolBoundaryError("the scoped target is not a single-link regular file")
    if not write and info.st_size > tool.max_result_bytes:
        os.close(descriptor)
        raise ToolBoundaryError("the scoped file exceeds the tool's byte cap")
    return descriptor


def admit_network(registry, envelope, policy, method, url, *, resolver, transport, headers=None):
    """A brokered fetch to an exact host the tool declared, or a refusal."""

    from urllib.parse import urlsplit

    tool = _admitted(registry, envelope)
    if not tool.network_scopes:
        raise ToolBoundaryError("the tool declared no network scope")
    if type(policy) is not EgressPolicy:
        raise ToolBoundaryError("a frozen egress policy is required")
    try:
        host = (urlsplit(url).hostname or "") if type(url) is str else ""
    except ValueError:
        host = ""
    if host not in tool.network_scopes:
        raise ToolBoundaryError("the host is outside the tool's declared network scope")
    try:
        return broker_fetch(policy, method, url, resolver=resolver, transport=transport,
                            headers=headers)
    except EgressBrokerError as error:
        raise ToolBoundaryError(f"egress refused: {error}") from None


# active content a renderer would execute: never admitted as a tool result
ACTIVE_MEDIA = frozenset({
    "text/html", "application/xhtml+xml", "image/svg+xml", "application/javascript",
    "text/javascript", "application/x-shockwave-flash", "application/xml", "text/xml",
})
_SNIFFED = {
    "application/pdf": "pdf", "image/png": "png", "text/csv": "csv",
    "application/json": "json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}
_PLAIN = frozenset({"text/plain", "text/markdown"})
_WRITING_EFFECTS = frozenset(
    name for name, family in port_contracts.EFFECT_FAMILIES.items() if family != "N"
)


def admit_tool_result(registry, envelope, media_type, data: bytes) -> str:
    """Admit one result for rendering: bounded, declared, sniffed; else refuse."""

    from ..adapters.documents import DocumentToolError, validate_format

    tool = _admitted(registry, envelope)
    if type(data) is not bytes or len(data) > tool.max_result_bytes:
        raise ToolBoundaryError("the result exceeds the tool's byte cap")
    if type(media_type) is not str or media_type.split(";")[0].strip().lower() in ACTIVE_MEDIA:
        raise ToolBoundaryError("active renderable content is never admitted")
    if media_type in _PLAIN:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise ToolBoundaryError("the text result is not UTF-8") from None
        if b"\x00" in data:
            raise ToolBoundaryError("the text result carries binary content")
        return media_type
    declared = _SNIFFED.get(media_type)
    if declared is None:
        raise ToolBoundaryError("the result media type is not renderable here")
    with tempfile.TemporaryDirectory(prefix="tool-result-") as scratch:
        path = os.path.join(scratch, "result")
        with open(path, "xb") as handle:
            handle.write(data)
        try:
            if validate_format(path, declared) is not True:
                raise ToolBoundaryError("the result bytes are not the declared format")
        except DocumentToolError:
            raise ToolBoundaryError("the result bytes are not the declared format") from None
    return media_type


__all__ = [
    "ACTIVE_MEDIA",
    "APPROVAL_EFFECTS",
    "EFFECT_CLASSES",
    "IDEMPOTENCY",
    "OUTCOMES",
    "REPLAY_POLICIES",
    "DispatchEnvelope",
    "ToolBoundaryError",
    "ToolDefinition",
    "ToolRegistry",
    "admit_network",
    "admit_tool_result",
    "dispatch_tool",
    "open_in_scope",
    "open_tool_registry",
    "record_outcome",
    "register_tool",
]
