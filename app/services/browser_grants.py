"""The owner's browser grants (T043; runtime.md §6 "Grants bind … tool/version,
source/target, action, … expiry/use count, byte limits and human/policy authority").

A browser grant is one immutable `grant` record per owner command: what the browser
tools may reach and what data may flow there —

- the tools it covers (`browser_navigate` / `browser_read` / `browser_screenshot` 1.0.0),
- the navigation sources (https URL prefixes) and the recipient hosts,
- the projection: the exact navigations permitted, and for each query parameter the
  owner-declared data source whose values may appear in it. The owner types the values
  once when creating the grant; the record keeps only their SHA-256 digests
  (`fetch_channel.value_digest`) — a request is admitted by digest comparison, and the
  grant list never shows a value back. A navigation with no parameters is pure
  navigation: no source data at all. No other data source exists: work content,
  diagnosis, alternatives and secrets are never declarable sources;
- per-session byte/request/redirect limits and lifetime, and the grant's own expiry.

It is authored by the owner's human actor with its `approval.decided(approved)` public
event in the same transaction; exact replay returns the same grant, any other body under
the same command conflicts. A stored row is grant evidence only with the writer's whole
discipline — the owner's actor, the identity derived from its command, the exact content
grammar and the decided event it names — re-checked on every read. The owner revokes a
grant with one sealed `decision_record` (`approval.decided(revoked)`); a revocation is
not undone. Past `expires_at_utc` a grant is no longer current, exactly as if revoked.

Dispatch (`browser_attempt_transport`) builds the fetch service's `BrowserGrant` only
from these records: the compiled tool binding's `grant_ref` must be the exact record, the
run's environment must resolve — through its prepared head to the owner's design
approval — to that same record as the approved `tool_permissions`
(`approved_tool_permissions`), and the record must still be current at every dispatch.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from ..domain.public_events import (
    _append_event_in_transaction,
    _assert_event_schema,
    _event_stream,
)
from ..domain.refs import (
    DomainContractError,
    EntityRef,
    ObjectRef,
    canonical_json,
    uuid_string,
)
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, _writer
from ..workers.fetch_channel import (
    BrowserGrant,
    DataSource,
    GrantProjection,
    ProjectionEntry,
    value_digest,
)
from .owner_auth import OwnerAuthError
from .run_approvals import (
    _authenticate_owner,
    _bound_pair,
    _owner_actor_ref,
    _stored_owner_actor_ref,
)

__all__ = [
    "COMMAND_SCHEMA",
    "GRANTABLE_TOOLS",
    "RECORD_SCHEMA",
    "REVOCATION_COMMAND_SCHEMA",
    "BrowserGrantError",
    "DispatchGrant",
    "PersistentBrowserGrants",
    "approved_tool_permissions",
    "grant_identity",
]

COMMAND_SCHEMA = "browser-grant-command-v1"
RECORD_SCHEMA = "browser-grant-v1"
REVOCATION_COMMAND_SCHEMA = "browser-grant-revocation-command-v1"
REVOCATION_SCHEMA = "browser-grant-revocation-v1"
GRANTABLE_TOOLS = ("browser_navigate", "browser_read", "browser_screenshot")
TOOL_VERSION = "1.0.0"
MAX_GRANT_SECONDS = 90 * 24 * 3600
MAX_LABEL = 120
LIMIT_KEYS = ("max_response_bytes", "max_total_bytes", "max_requests", "max_redirects", "ttl_ms")
CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "conflict", "unavailable",
                   "revoked", "expired", "tool_not_granted"})
_COMMAND_KEYS = frozenset({"schema_version", "command_id", "label", "tools", "sources", "recipients", "entries",
                           "data_sources", "limits", "expires_at_utc"})
_CONTENT_KEYS = frozenset({"schema_version", "command_id", "label", "tools", "grant", "expires_at_utc",
                           "decided_at_utc", "event_sequence"})
_REVOCATION_KEYS = frozenset({"schema_version", "command_id", "grant_ref", "revoked_at_utc", "event_sequence"})
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z")
_ISSUE_TOKEN = object()


class BrowserGrantError(ValueError):
    """Closed codes; storage detail never leaks."""

    def __init__(self, code="invalid_input"):
        if code not in CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (BrowserGrantError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage errors must not disclose detail
            raise BrowserGrantError("unavailable") from None

    return invoke


def grant_identity(command_id: str) -> str:
    uuid_string(command_id)
    return str(uuid5(NAMESPACE_URL, f"deeptwin:browser-grant:{command_id}"))


def revocation_identity(grant_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"deeptwin:browser-grant-revocation:{uuid_string(grant_id)}"))


def _stamp(now=None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _parse_stamp(value) -> datetime:
    if type(value) is not str or _STAMP.fullmatch(value) is None:
        raise ValueError("not a stamp")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _tools(value) -> list[str]:
    if (type(value) is not list or not 1 <= len(value) <= len(GRANTABLE_TOOLS)
            or value != sorted(set(value)) or not all(item in GRANTABLE_TOOLS for item in value)):
        raise BrowserGrantError("invalid_input")
    return value


def _label(value) -> str:
    if (type(value) is not str or not 1 <= len(value) <= MAX_LABEL or value.strip() != value
            or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)):
        raise BrowserGrantError("invalid_input")
    return value


def _grant_from_command(payload) -> BrowserGrant:
    """The fetch service's grant object from the owner's command: every value hashed."""

    try:
        if type(payload["sources"]) is not list or type(payload["recipients"]) is not list \
                or type(payload["entries"]) is not list or type(payload["data_sources"]) is not list:
            raise ValueError("lists")
        limits = payload["limits"]
        if type(limits) is not dict or set(limits) != set(LIMIT_KEYS):
            raise ValueError("limits")
        entries = []
        for item in payload["entries"]:
            if type(item) is not dict or set(item) != {"url", "parameters"} or type(item["parameters"]) is not list:
                raise ValueError("entry")
            parameters = []
            for parameter in item["parameters"]:
                if type(parameter) is not dict or set(parameter) != {"name", "source"}:
                    raise ValueError("parameter")
                parameters.append((parameter["name"], parameter["source"]))
            entries.append(ProjectionEntry(url=item["url"], parameters=tuple(parameters)))
        sources = []
        for item in payload["data_sources"]:
            if type(item) is not dict or set(item) != {"source_id", "values"} or type(item["values"]) is not list \
                    or not item["values"]:
                raise ValueError("data source")
            digests = tuple(sorted({value_digest(value) for value in item["values"]}))
            if len(digests) != len(item["values"]):
                raise ValueError("duplicate values")
            sources.append(DataSource(source_id=item["source_id"], value_sha256=digests))
        return BrowserGrant(sources=tuple(payload["sources"]), recipients=tuple(payload["recipients"]),
                            projection=GrantProjection(entries=tuple(entries), data_sources=tuple(sources)),
                            **{name: limits[name] for name in LIMIT_KEYS})
    except (KeyError, TypeError, ValueError):
        raise BrowserGrantError("invalid_input") from None


def _command(payload, now) -> dict:
    if type(payload) is not dict or set(payload) != _COMMAND_KEYS or payload["schema_version"] != COMMAND_SCHEMA:
        raise BrowserGrantError("invalid_input")
    try:
        command_id = uuid_string(payload["command_id"])
        expires = _parse_stamp(payload["expires_at_utc"])
    except (DomainContractError, TypeError, ValueError):
        raise BrowserGrantError("invalid_input") from None
    remaining = (expires - now).total_seconds()
    if not 0 < remaining <= MAX_GRANT_SECONDS:
        raise BrowserGrantError("invalid_input")
    return {"command_id": command_id, "label": _label(payload["label"]), "tools": _tools(payload["tools"]),
            "grant": _grant_from_command(payload).as_dict(), "expires_at_utc": payload["expires_at_utc"]}


def _parse_content(content) -> dict:
    """Re-validate stored content with the writer's grammar."""

    try:
        if (type(content) is not dict or set(content) != _CONTENT_KEYS or content["schema_version"] != RECORD_SCHEMA
                or type(content["event_sequence"]) is not int or content["event_sequence"] < 1):
            raise ValueError("content")
        uuid_string(content["command_id"])
        _parse_stamp(content["decided_at_utc"])
        _parse_stamp(content["expires_at_utc"])
        _label(content["label"])
        _tools(content["tools"])
        grant = BrowserGrant.from_mapping(content["grant"])
        if grant.as_dict() != content["grant"]:
            raise ValueError("grant is not canonical")
    except (BrowserGrantError, DomainContractError, TypeError, ValueError):
        raise BrowserGrantError("unavailable") from None
    return {**content, "browser_grant": grant}


def _event_decided(db, roots, sequence, command_id, decision) -> bool:
    event = db.execute(
        "SELECT event_type, envelope FROM api_event_envelopes WHERE vault_id=? AND sequence=?",
        (roots.genesis.id, sequence)).fetchone()
    if event is None or event["event_type"] != "approval.decided":
        return False
    envelope = json.loads(event["envelope"])
    return (envelope.get("correlation_id") == command_id
            and envelope.get("public_metadata") == {"decision": decision})


def _resolve(domain, db, roots, ref: EntityRef) -> dict:
    """The parsed content behind one exact browser grant reference — only a record with
    the writer's whole discipline; any other row is `unavailable` as grant evidence."""

    if type(ref) is not EntityRef or ref.kind != "grant" or ref.version != 1:
        raise BrowserGrantError("unavailable")
    try:
        body = domain._load(db, ref, roots)[0].body
    except Exception:  # noqa: BLE001 - an unresolvable grant is no grant evidence
        raise BrowserGrantError("not_found") from None
    owner = _stored_owner_actor_ref(db)
    if owner is None or owner != body["actor_ref"]:
        raise BrowserGrantError("unavailable")
    content = _parse_content(body["content"])
    if grant_identity(content["command_id"]) != ref.id \
            or not _event_decided(db, roots, content["event_sequence"], content["command_id"], "approved"):
        raise BrowserGrantError("unavailable")
    return content


def _revocation(domain, db, roots, grant_ref: EntityRef) -> dict | None:
    record_id = revocation_identity(grant_ref.id)
    row = db.execute(
        "SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind='decision_record' AND id=? "
        "ORDER BY version DESC LIMIT 1", (roots.genesis.id, record_id)).fetchone()
    if row is None:
        return None
    try:
        if row["version"] != 1:
            raise ValueError("version")
        body = domain._load(db, EntityRef("decision_record", record_id, 1, row["sha256"]), roots)[0].body
        content = body["content"]
        if (_stored_owner_actor_ref(db) != body["actor_ref"] or type(content) is not dict
                or set(content) != _REVOCATION_KEYS or content["schema_version"] != REVOCATION_SCHEMA
                or content["grant_ref"] != grant_ref.as_dict() or type(content["event_sequence"]) is not int):
            raise ValueError("revocation")
        uuid_string(content["command_id"])
        _parse_stamp(content["revoked_at_utc"])
        if not _event_decided(db, roots, content["event_sequence"], content["command_id"], "revoked"):
            raise ValueError("event")
    except Exception:  # noqa: BLE001 - a malformed revocation makes the grant unusable, never valid
        raise BrowserGrantError("unavailable") from None
    return {"command_id": content["command_id"], "revoked_at_utc": content["revoked_at_utc"]}


def _view(ref: EntityRef, content: dict, revocation, now) -> dict:
    grant = content["browser_grant"]
    if revocation is not None:
        state = "revoked"
    elif now >= _parse_stamp(content["expires_at_utc"]):
        state = "expired"
    else:
        state = "active"
    return {
        "grant_id": ref.id, "ref": ref.as_dict(), "command_id": content["command_id"], "label": content["label"],
        "tools": list(content["tools"]), "sources": list(grant.sources), "recipients": list(grant.recipients),
        "projection": {
            "entries": [entry.as_dict() for entry in grant.projection.entries],
            # the digests only: a declared value is never shown back
            "data_sources": [{"source_id": item.source_id, "value_count": len(item.value_sha256),
                              "value_sha256": list(item.value_sha256)} for item in grant.projection.data_sources],
        },
        "limits": {name: getattr(grant, name) for name in LIMIT_KEYS},
        "expires_at_utc": content["expires_at_utc"], "decided_at_utc": content["decided_at_utc"],
        "state": state, "revocation": revocation,
    }


@dataclass(frozen=True, slots=True, init=False)
class DispatchGrant:
    """A browser grant current at one dispatch, built only from its owner record."""

    ref: EntityRef
    tools: tuple[str, ...]
    grant: BrowserGrant
    expires_at_utc: str
    _issuer_token: object = field(repr=False, compare=False)


def is_issued_dispatch_grant(value) -> bool:
    return type(value) is DispatchGrant and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN


def _issue_dispatch(ref, content, now) -> DispatchGrant:
    grant = content["browser_grant"]
    remaining_ms = int((_parse_stamp(content["expires_at_utc"]) - now).total_seconds() * 1000)
    if remaining_ms < 1_000:
        raise BrowserGrantError("expired")
    value = object.__new__(DispatchGrant)
    fields = {"ref": ref, "tools": tuple(content["tools"]), "expires_at_utc": content["expires_at_utc"],
              # one session never outlives the grant it runs under
              "grant": BrowserGrant.from_mapping({**grant.as_dict(), "ttl_ms": min(grant.ttl_ms, remaining_ms)}),
              "_issuer_token": _ISSUE_TOKEN}
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


# --- the run's approved tool permissions ------------------------------------------------

def approved_tool_permissions(domain_store, environment_ref) -> EntityRef:
    """The `tool_permissions` grant reference the owner approved for the design a run's
    environment was prepared from: environment record → its prepared head record → the
    design approval that head consumed (its record identity and digest are the approval's
    own `approval_sha`). Anything else — an environment without that chain — has no
    approved tool permissions and authorizes no browser tool."""

    from .design_persistence import decode_design_refs

    if type(domain_store) is not DomainStore or type(environment_ref) is not EntityRef \
            or environment_ref.kind != "environment":
        raise BrowserGrantError("access_denied")
    try:
        environment = domain_store.get(environment_ref).body
        content = decode_design_refs(environment["content"])
        if content.get("schema_version") != "environment-record-v1" or content.get("status") != "prepared":
            raise ValueError("environment")
        approval_sha = content["approval_sha"]
        parents = environment["parent_refs"]
        if len(parents) != 1:
            raise ValueError("head")
        head = domain_store.get(EntityRef.from_dict(parents[0])).body
        head_content = head["content"]
        if head_content.get("design_kind") != "environment_head" \
                or decode_design_refs(head_content["design"])["version"]["approval_sha"] != approval_sha:
            raise ValueError("head content")
        approval_id = str(uuid5(NAMESPACE_URL, f"deeptwin:design-approval:{approval_sha}"))
        matches = [item for item in head["parent_refs"] if item["kind"] == "decision_record"
                   and item["id"] == approval_id and item["version"] == 1]
        if len(matches) != 1:
            raise ValueError("approval")
        approval_record = domain_store.get(EntityRef.from_dict(matches[0])).body["content"]
        if approval_record.get("design_kind") != "design_approval_record":
            raise ValueError("approval kind")
        approval = decode_design_refs(approval_record["design"])
        if (sha256(canonical_json(approval)).hexdigest() != approval_sha
                or approval.get("environment_id") != content["environment_id"]):
            raise ValueError("approval digest")
        permissions = EntityRef.from_dict(approval["tool_permissions_ref"])
        if permissions.kind != "grant":
            raise ValueError("permissions kind")
        return permissions
    except BrowserGrantError:
        raise
    except Exception:  # noqa: BLE001 - no chain, no approved tool permissions
        raise BrowserGrantError("access_denied") from None


class PersistentBrowserGrants:
    """Writes and reads the owner's browser grants over the exact bound store."""

    def __init__(self, domain_store, owner_authority, *, clock=None):
        self._domain, self._owner = _bound_pair(domain_store, owner_authority, BrowserGrantError)
        self._clock = clock or (lambda: datetime.now(UTC))

    def bound_to(self, domain_store) -> bool:
        return domain_store is self._domain

    # --- reads -------------------------------------------------------------------------

    def _existing(self, db, roots, grant_id: str):
        row = db.execute(
            "SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind='grant' AND id=? "
            "ORDER BY version DESC LIMIT 1", (roots.genesis.id, grant_id)).fetchone()
        if row is None:
            return None
        if row["version"] != 1:
            raise BrowserGrantError("unavailable")
        ref = EntityRef("grant", grant_id, 1, row["sha256"])
        return ref, _resolve(self._domain, db, roots, ref), _revocation(self._domain, db, roots, ref)

    @_closed
    def list(self, request) -> dict:
        now = self._clock()
        with self._domain._connection() as db:
            self._owner.authenticate_bound(request.session)
            roots = self._domain._read_roots(db)
            rows = list(db.execute(
                "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND kind='grant' ORDER BY id",
                (roots.genesis.id,)))
            grants = []
            for row in rows:
                if row["version"] != 1:
                    continue
                ref = EntityRef("grant", row["id"], 1, row["sha256"])
                try:
                    content = _resolve(self._domain, db, roots, ref)
                    revocation = _revocation(self._domain, db, roots, ref)
                except BrowserGrantError:
                    continue  # a `grant` record that is not the owner's browser grant is not listed
                grants.append(_view(ref, content, revocation, now))
        grants.sort(key=lambda item: (item["decided_at_utc"], item["grant_id"]), reverse=True)  # newest first
        return {"schema_version": "browser-grants-v1", "grants": grants}

    def for_dispatch(self, ref, *, tool_id: str, version: str) -> DispatchGrant:
        """The grant behind `ref` when it is current for this tool now: `revoked`,
        `expired` and `tool_not_granted` are refusals; anything that is no owner grant
        record is `unavailable` (or `not_found`)."""

        if version != TOOL_VERSION or tool_id not in GRANTABLE_TOOLS:
            raise BrowserGrantError("tool_not_granted")
        try:
            now = self._clock()
            with self._domain._connection() as db:
                roots = self._domain._read_roots(db)
                content = _resolve(self._domain, db, roots, ref)
                if _revocation(self._domain, db, roots, ref) is not None:
                    raise BrowserGrantError("revoked")
        except BrowserGrantError:
            raise
        except Exception:  # noqa: BLE001 - storage detail stays private
            raise BrowserGrantError("unavailable") from None
        if now >= _parse_stamp(content["expires_at_utc"]):
            raise BrowserGrantError("expired")
        if tool_id not in content["tools"]:
            raise BrowserGrantError("tool_not_granted")
        return _issue_dispatch(ref, content, now)

    # --- the commands ------------------------------------------------------------------

    @_closed
    def create(self, request, payload) -> dict:
        _authenticate_owner(self._owner, request)
        now = self._clock()
        command = _command(payload, now)
        grant_id = grant_identity(command["command_id"])
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            _assert_event_schema(db, roots.genesis.id)
            existing = self._existing(db, roots, grant_id)
            if existing is not None:
                ref, content, revocation = existing
                if any(content[name] != command[name] for name in ("label", "tools", "grant", "expires_at_utc")):
                    raise BrowserGrantError("conflict")
                return _view(ref, content, revocation, now)
            actor_ref = _owner_actor_ref(db, actor)
            stamp = _stamp(now)
            event_sequence = _event_stream(db, roots.genesis.id)["next_sequence"]
            record = ImmutableRecord.create(
                kind="grant", id=grant_id, version=1, created_at_utc=stamp, actor_ref=actor_ref, parent_refs=(),
                purpose="operational", access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy,
                content={"schema_version": RECORD_SCHEMA, "command_id": command["command_id"],
                         "label": command["label"], "tools": command["tools"], "grant": command["grant"],
                         "expires_at_utc": command["expires_at_utc"], "decided_at_utc": stamp,
                         "event_sequence": event_sequence})
            self._domain._put_in_transaction(db, record)
            event = _append_event_in_transaction(
                db, vault_id=roots.genesis.id, recorded_at_utc=stamp, observed_at_utc=stamp,
                actor_kind="human", actor_ref=actor_ref, event_type="approval.decided",
                object_refs=(ObjectRef(record.ref.kind, record.ref.id, record.ref.version, record.ref.sha256),),
                correlation_id=command["command_id"], causation_id=None, status="succeeded",
                error_code=None, public_metadata={"decision": "approved"}, private_evidence_refs=(),
                retention_class="core", policy_ref=roots.access_policy,
            )
            if event.sequence != event_sequence:
                raise BrowserGrantError("unavailable")
            return _view(record.ref, _resolve(self._domain, db, roots, record.ref), None, now)

    @_closed
    def revoke(self, request, grant_id, payload) -> dict:
        """The owner withdraws a grant: no later dispatch runs under it; what already ran
        is not undone."""

        _authenticate_owner(self._owner, request)
        try:
            grant_id = uuid_string(grant_id)
        except (TypeError, ValueError):
            raise BrowserGrantError("invalid_input") from None
        if (type(payload) is not dict or set(payload) != {"schema_version", "command_id"}
                or payload["schema_version"] != REVOCATION_COMMAND_SCHEMA):
            raise BrowserGrantError("invalid_input")
        try:
            command_id = uuid_string(payload["command_id"])
        except (TypeError, ValueError):
            raise BrowserGrantError("invalid_input") from None
        now = self._clock()
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            _assert_event_schema(db, roots.genesis.id)
            existing = self._existing(db, roots, grant_id)
            if existing is None:
                raise BrowserGrantError("not_found")
            ref, content, revocation = existing
            if revocation is not None:
                if revocation["command_id"] != command_id:
                    raise BrowserGrantError("conflict")
                return _view(ref, content, revocation, now)
            actor_ref = _owner_actor_ref(db, actor)
            stamp = _stamp(now)
            event_sequence = _event_stream(db, roots.genesis.id)["next_sequence"]
            record = ImmutableRecord.create(
                kind="decision_record", id=revocation_identity(grant_id), version=1, created_at_utc=stamp,
                actor_ref=actor_ref, parent_refs=(ref,), purpose="operational",
                access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                content={"schema_version": REVOCATION_SCHEMA, "command_id": command_id, "grant_ref": ref.as_dict(),
                         "revoked_at_utc": stamp, "event_sequence": event_sequence})
            self._domain._put_in_transaction(db, record)
            event = _append_event_in_transaction(
                db, vault_id=roots.genesis.id, recorded_at_utc=stamp, observed_at_utc=stamp,
                actor_kind="human", actor_ref=actor_ref, event_type="approval.decided",
                object_refs=(ObjectRef(record.ref.kind, record.ref.id, record.ref.version, record.ref.sha256),
                             ObjectRef(ref.kind, ref.id, ref.version, ref.sha256)),
                correlation_id=command_id, causation_id=None, status="succeeded",
                error_code=None, public_metadata={"decision": "revoked"}, private_evidence_refs=(),
                retention_class="core", policy_ref=roots.access_policy,
            )
            if event.sequence != event_sequence:
                raise BrowserGrantError("unavailable")
            return _view(ref, content, _revocation(self._domain, db, roots, ref), now)
