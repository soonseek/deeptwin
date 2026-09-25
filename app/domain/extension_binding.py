"""Closed `extension_binding` record contents (T087; data-model §3.1 ExtensionBindingRevision/Head
and ExtensionRollbackRetentionRevision/Head, contracts/api.md Extensions).

Three content shapes share the `extension_binding` domain kind:

- `extension-binding-revision-v1`: one immutable binding revision. The record id is derived from
  the exact `BindingSlotKeyV1` digest (`slot_record_id`) and the record version is the binding
  revision, so a slot's history is the record's versions and its head is the newest version.
  `binding_record_digest` is that version's record SHA-256.
- `extension-rollback-retention-revision-v1`: one immutable rollback-retention revision for one
  displaced binding revision; id from slot digest + target binding record digest
  (`retention_record_id`), version = retention revision (1 `retained`, 2 `released`|`consumed`).
- `extension-binding-command-record-v1`: the replay record of one owner command id.

Only these three schema versions are validated here; any other `extension_binding` content is
left to its own owner (the deployment first-only guard treats every row of this kind as present).
Valid structure grants no binding authority: the binding service re-derives every value.
"""

from __future__ import annotations

import re
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from .refs import DomainContractError, EntityRef, canonical_json, uuid_string

BINDING_SCHEMA = "extension-binding-revision-v1"
RETENTION_SCHEMA = "extension-rollback-retention-revision-v1"
COMMAND_SCHEMA = "extension-binding-command-record-v1"
SCOPE_SCHEMA = "extension-binding-target-scope-v1"
SCHEMAS = frozenset({BINDING_SCHEMA, RETENTION_SCHEMA, COMMAND_SCHEMA})
BINDING_STATES = ("active", "disabled")
BINDING_ACTIONS = ("bind", "supersede", "disable", "rollback")
RETENTION_STATES = ("retained", "released", "consumed")
COMMAND_ACTIONS = ("bind", "disable", "rollback", "release")
SCOPE_PURPOSES = frozenset({
    "operational", "diagnosis", "inquiry_audit", "evaluation_development",
    "evaluation_sealed", "release_evidence",
})
SERVICE_TUPLE_FIELDS = ("service_identity", "manifest_digest", "service_descriptor_digest",
                        "selected_platform_entry_digest", "image_manifest_digest")
MAX_REASON_BYTES = 500
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_INSTANCE = re.compile(r"[0-9a-f]{32}\Z")
_EXTENSION_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?\Z")
_NODE_ID = re.compile(r"[a-z][a-z0-9._:-]{0,127}\Z")
_PROVIDER_ID = re.compile(r"[a-z][a-z0-9._:-]{0,127}\Z")
_BROKER = re.compile(r"[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TEXT = re.compile(r"[^\x00-\x1f\x7f]+\Z")


class BindingValueError(ValueError):
    """A binding value is outside its closed shape (the service maps this to invalid_input)."""


def _fail(message="binding value is not exact"):
    raise BindingValueError(message)


def _exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        _fail()
    return value


def _int(value, minimum=1, maximum=2**53 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail()
    return value


def _hex(value):
    if type(value) is not str or _HEX.fullmatch(value) is None:
        _fail()
    return value


def _match(value, pattern, maximum=128):
    if type(value) is not str or len(value) > maximum or pattern.fullmatch(value) is None:
        _fail()
    return value


def _uuid(value):
    try:
        return uuid_string(value)
    except (TypeError, ValueError, DomainContractError):
        _fail()


def digest_of(value):
    return sha256(canonical_json(value)).hexdigest()


def slot_key(value, digest=None, *, port=None):
    """The exact five-field `BindingSlotKeyV1` and its recomputed digest (never a projection)."""
    from ..extensions.port_contracts import BindingSlotKeyV1, PortContractError

    try:
        key = BindingSlotKeyV1.from_mapping(value, expected_port_contract_version=port,
                                            expected_digest=digest)
    except (PortContractError, TypeError):
        _fail("binding slot key is not an exact BindingSlotKeyV1")
    return key.as_dict(), key.digest


def target_scope(value, *, instance_id=None):
    """The closed binding target scope; its fingerprint is the slot key's
    `target_scope_fingerprint` (`scope_fingerprint`)."""
    value = _exact(value, ("instance_id", "environment_id", "work_id", "node_id", "purpose"))
    _match(value["instance_id"], _INSTANCE, 32)
    if instance_id is not None and value["instance_id"] != instance_id:
        _fail("binding scope names another instance")
    for name in ("environment_id", "work_id"):
        if value[name] is not None:
            _uuid(value[name])
    if value["node_id"] is not None:
        _match(value["node_id"], _NODE_ID)
    if type(value["purpose"]) is not str or value["purpose"] not in SCOPE_PURPOSES:
        _fail()
    if ((value["node_id"] is not None and (value["work_id"] is None or value["environment_id"] is None))
            or (value["work_id"] is not None and value["environment_id"] is None)):
        _fail("binding scope hierarchy is incomplete")
    return dict(value)


def scope_fingerprint(scope):
    return digest_of({"schema_version": SCOPE_SCHEMA, **scope})


def _optional_ref(value):
    if value is None:
        return None
    try:
        return EntityRef.from_dict(value).as_dict()
    except (TypeError, ValueError, DomainContractError):
        _fail()


# contracts: data-model.md "Binding slots and capability selectors"; the provider family's
# `auth_mode` is the provider port config's only value (`auth_mode:api`). Other families' field
# types are not fixed by the contracts yet, so their selectors are not admitted here.
SELECTOR_FAMILIES = {"provider-port-v1": "provider_role"}


def capability_selector(port, value):
    if SELECTOR_FAMILIES.get(port) != "provider_role":
        _fail("selector family is not admitted for this port")
    value = _exact(value, ("selector_kind", "provider_id", "auth_mode", "account_binding_ref"))
    if value["selector_kind"] != "provider_role" or value["auth_mode"] != "api":
        _fail()
    return {"selector_kind": "provider_role",
            "provider_id": _match(value["provider_id"], _PROVIDER_ID),
            "auth_mode": "api", "account_binding_ref": _optional_ref(value["account_binding_ref"])}


def binding_head(value, *, states=BINDING_STATES):
    value = _exact(value, ("revision", "binding_record_digest", "state"))
    if value["state"] not in states:
        _fail()
    return {"revision": _int(value["revision"]), "binding_record_digest": _hex(value["binding_record_digest"]),
            "state": value["state"]}


def binding_ref(value):
    value = _exact(value, ("revision", "binding_record_digest"))
    return {"revision": _int(value["revision"]), "binding_record_digest": _hex(value["binding_record_digest"])}


def retention_head(value, *, states=RETENTION_STATES):
    value = _exact(value, ("revision", "retention_record_digest", "state"))
    if value["state"] not in states:
        _fail()
    return {"revision": _int(value["revision"]), "retention_record_digest": _hex(value["retention_record_digest"]),
            "state": value["state"]}


def installation_ref(value):
    """`{extension_id,revision,installation_record_digest}` (an already committed installation)."""
    value = _exact(value, ("extension_id", "revision", "installation_record_digest"))
    return {"extension_id": _match(value["extension_id"], _EXTENSION_ID),
            "revision": _int(value["revision"]),
            "installation_record_digest": _hex(value["installation_record_digest"])}


def service_tuple(value):
    value = _exact(value, SERVICE_TUPLE_FIELDS)
    return {"service_identity": _match(value["service_identity"], _BROKER, 64),
            "manifest_digest": _hex(value["manifest_digest"]),
            "service_descriptor_digest": _hex(value["service_descriptor_digest"]),
            "selected_platform_entry_digest": _hex(value["selected_platform_entry_digest"]),
            "image_manifest_digest": _match(value["image_manifest_digest"], _IMAGE, 71)}


def reason_text(value):
    if (type(value) is not str or not value or len(value.encode("utf-8")) > MAX_REASON_BYTES
            or _TEXT.fullmatch(value) is None or value != value.strip()):
        _fail()
    return value


def slot_record_id(slot_digest):
    return str(uuid5(NAMESPACE_URL, f"deeptwin:extension-binding-slot:{_hex(slot_digest)}"))


def retention_record_id(slot_digest, target_binding_record_digest):
    return str(uuid5(NAMESPACE_URL, "deeptwin:extension-rollback-retention:"
                     f"{_hex(slot_digest)}:{_hex(target_binding_record_digest)}"))


def command_record_id(command_id):
    return str(uuid5(NAMESPACE_URL, f"deeptwin:extension-binding-command:{_uuid(command_id)}"))


_BINDING_FIELDS = (
    "schema_version", "extension_id", "revision", "state", "action", "port_contract_version",
    "extension_kind", "trust_tier", "binding_slot_key", "binding_slot_key_digest",
    "capability_selector", "target_scope", "installation_ref", "target_installation",
    "service_tuple", "qualification_ref", "expected_previous_head", "previous_revision",
    "supersedes_revision", "rollback_of_revision", "command_id", "recorded_at_ms",
)
_RETENTION_FIELDS = (
    "schema_version", "binding_slot_key", "binding_slot_key_digest", "target_binding_revision",
    "target_extension_id", "target_installation", "target_service_tuple", "state", "revision",
    "expected_previous_retention_head", "previous_revision", "observed_current_binding_head",
    "reason", "command_id", "recorded_at_ms",
)
_COMMAND_FIELDS = ("schema_version", "command_id", "action", "request_sha256", "result_json")


def validate_binding_content(content, *, record_id, version):
    """Closed structural check of a binding revision; nothing about current authority."""
    from ..extensions.port_contracts import PORT_CONTRACTS

    _exact(content, _BINDING_FIELDS)
    key, digest = slot_key(content["binding_slot_key"], content["binding_slot_key_digest"])
    port = key["port_contract_version"]
    contract = PORT_CONTRACTS[port]
    if (content["port_contract_version"] != port or content["extension_kind"] != contract.extension_kind
            or content["trust_tier"] != contract.trust_tier
            or record_id != slot_record_id(digest) or content["revision"] != version
            or content["state"] not in BINDING_STATES or content["action"] not in BINDING_ACTIONS
            or (content["state"] == "disabled") != (content["action"] == "disable")):
        _fail()
    _match(content["extension_id"], _EXTENSION_ID)
    selector = capability_selector(port, content["capability_selector"])
    scope = target_scope(content["target_scope"])
    if (selector != content["capability_selector"] or digest_of(selector) != key["capability_selector_digest"]
            or scope_fingerprint(scope) != key["target_scope_fingerprint"] or scope["purpose"] != key["purpose"]):
        _fail()
    installed = EntityRef.from_dict(content["installation_ref"])
    target = installation_ref(content["target_installation"])
    if (installed.kind != "extension_installation" or installed.version != 2
            or target != {"extension_id": content["extension_id"], "revision": installed.version,
                          "installation_record_digest": installed.sha256}):
        _fail()
    service_tuple(content["service_tuple"])
    if EntityRef.from_dict(content["qualification_ref"]).kind != "validation_report":
        _fail()
    revision = content["revision"]
    expected, previous = content["expected_previous_head"], content["previous_revision"]
    if (revision == 1) != (expected is None) or (expected is None) != (previous is None):
        _fail()
    if expected is not None:
        expected = binding_head(expected)
        if (binding_ref(previous) != {"revision": expected["revision"],
                                      "binding_record_digest": expected["binding_record_digest"]}
                or expected["revision"] != revision - 1):
            _fail()
    supersedes = content["supersedes_revision"]
    if supersedes is not None and (expected is None or expected["state"] != "active"
                                   or binding_ref(supersedes) != previous):
        _fail()
    action = content["action"]
    if ((action == "supersede" and supersedes is None)
            or (action in ("bind", "disable") and supersedes is not None)
            or (action == "bind" and expected is not None and expected["state"] != "disabled")
            or (action == "disable" and (expected is None or expected["state"] != "active"))):
        _fail()
    rollback = content["rollback_of_revision"]
    if (rollback is None) != (action != "rollback"):
        _fail()
    # a rollback target is a strict backward ancestor of the head it displaced
    if rollback is not None and binding_ref(rollback)["revision"] > revision - 2:
        _fail()
    _uuid(content["command_id"])
    _int(content["recorded_at_ms"], 0, 253402300799999)


def validate_retention_content(content, *, record_id, version):
    _exact(content, _RETENTION_FIELDS)
    _key, digest = slot_key(content["binding_slot_key"], content["binding_slot_key_digest"])
    target = binding_ref(content["target_binding_revision"])
    if (record_id != retention_record_id(digest, target["binding_record_digest"])
            or content["revision"] != version or content["state"] not in RETENTION_STATES
            or (version == 1) != (content["state"] == "retained") or version > 2):
        _fail()
    _match(content["target_extension_id"], _EXTENSION_ID)
    installed = installation_ref(content["target_installation"])
    if installed["extension_id"] != content["target_extension_id"]:
        _fail()
    service_tuple(content["target_service_tuple"])
    expected, previous = content["expected_previous_retention_head"], content["previous_revision"]
    if (version == 1) != (expected is None) or (expected is None) != (previous is None):
        _fail()
    if expected is not None:
        expected = retention_head(expected, states=("retained",))
        previous = _exact(previous, ("revision", "retention_record_digest"))
        if previous != {"revision": expected["revision"],
                        "retention_record_digest": expected["retention_record_digest"]}:
            _fail()
    observed = binding_head(content["observed_current_binding_head"])
    if observed["revision"] <= target["revision"]:
        _fail()
    if content["state"] == "released":
        reason_text(content["reason"])
    elif content["reason"] is not None:
        _fail()
    _uuid(content["command_id"])
    _int(content["recorded_at_ms"], 0, 253402300799999)


def validate_command_content(content, *, record_id):
    _exact(content, _COMMAND_FIELDS)
    if (record_id != command_record_id(content["command_id"])
            or content["action"] not in COMMAND_ACTIONS or type(content["result_json"]) is not str
            or len(content["result_json"]) > 32768):
        _fail()
    _hex(content["request_sha256"])


def validate_body(body):
    """Hook for `domain.schemas`: only this module's three content schemas are checked."""
    content = body["content"]
    schema = content.get("schema_version")
    if schema not in SCHEMAS:
        return
    try:
        if len(canonical_json(body)) > 65_536 or body["purpose"] != "operational":
            _fail()
        if schema == BINDING_SCHEMA:
            validate_binding_content(content, record_id=body["id"], version=body["version"])
        elif schema == RETENTION_SCHEMA:
            validate_retention_content(content, record_id=body["id"], version=body["version"])
        else:
            if body["version"] != 1:
                _fail()
            validate_command_content(content, record_id=body["id"])
    except (BindingValueError, DomainContractError, KeyError, TypeError, ValueError, RecursionError):
        raise DomainContractError("Invalid extension binding content") from None
