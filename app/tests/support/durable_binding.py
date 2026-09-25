"""Test-only durable provider bindings for dispatch-path tests (T087).

The binding revision, retention, command and event records are written by the production
`PersistentExtensionBindings._append` (the same transaction the owner routes use); only the
owner authentication and the transport-qualification resolver are skipped. The staged/verified
`extension_installation` records a binding points at are admitted by a test-only validator (the
closed installation codecs are proven by their own suites), so a test that uses them must keep
``admit_test_installations(monkeypatch)`` active for its whole duration: every graph read of a
binding traverses to its installation.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.domain.extension_binding import digest_of, scope_fingerprint, slot_record_id
from app.domain.public_events import _install_event_schema
from app.domain.schemas import ImmutableRecord
from app.domain.store import _writer
from app.extensions.binding_service import PersistentExtensionBindings
from app.extensions.port_contracts import PORT_CONTRACTS

INSTANCE = "1" * 32
STAMP = "2026-09-25T00:00:00.000000Z"


def admit_test_installations(monkeypatch):
    from app.domain import extension_installation

    installations = set()
    original = extension_installation.validate_installation_body

    def validate(body):
        if body["id"] not in installations:
            original(body)

    monkeypatch.setattr(extension_installation, "validate_installation_body", validate)
    return installations


def service_tuple(label):
    return {"service_identity": f"provider-{label}", "manifest_digest": digest_of({"m": label}),
            "service_descriptor_digest": digest_of({"d": label}),
            "selected_platform_entry_digest": digest_of({"p": label}),
            "image_manifest_digest": "sha256:" + digest_of({"i": label})}


def _put(domain, kind, content, *, record_id=None, version=1, parents=()):
    roots = domain.roots()
    return domain.put(ImmutableRecord.create(
        kind=kind, id=record_id or str(uuid4()), version=version, created_at_utc=STAMP,
        actor_ref=roots.actor, parent_refs=tuple(parents), purpose="operational",
        access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
        content=content))


def verified_installation(domain, installations, *, extension_id, label):
    """A staged (revision 1) and verified (revision 2) test installation."""
    installation_id = str(uuid4())
    installations.add(installation_id)
    stand_in = {"schema_version": "test-deployment-stand-in-v1", "label": label}
    request = _put(domain, "validation_report", stand_in)
    receipt = _put(domain, "validation_report", {**stand_in, "receipt": True})
    tuple_value = service_tuple(label)
    staged = _put(domain, "extension_installation", {
        "schema_version": "extension-provider-installation-anchor-v1", "extension_id": extension_id,
        "platform": "linux/amd64", "staging_authority": "deployment-provider-receipt-v1",
        "request_ref": request.as_dict(), "receipt_ref": receipt.as_dict(),
        "consume_command_id": str(uuid4()), "installed_at": "2026-09-25T00:00:00.000Z", **tuple_value},
        record_id=installation_id)
    verified = _put(domain, "extension_installation", {
        "schema_version": "provider-installation-verified-v1", "extension_id": extension_id,
        "extension_version": "1.0.0", "previous_record_digest": staged.sha256, "verified_at_ms": 1},
        record_id=installation_id, version=2, parents=(staged,))
    return verified, tuple_value


def _writer_service(domain):
    service = object.__new__(PersistentExtensionBindings)
    service._domain = domain
    service._instance_id = INSTANCE
    return service


def slot_values(*, provider_id="claude_api", binding_slot_id="provider-primary", purpose="operational",
                environment_id=None):
    selector = {"selector_kind": "provider_role", "provider_id": provider_id, "auth_mode": "api",
                "account_binding_ref": None}
    scope = {"instance_id": INSTANCE, "environment_id": environment_id, "work_id": None, "node_id": None,
             "purpose": purpose}
    key = {"port_contract_version": "provider-port-v1", "target_scope_fingerprint": scope_fingerprint(scope),
           "purpose": purpose, "binding_slot_id": binding_slot_id,
           "capability_selector_digest": digest_of(selector)}
    return key, digest_of(key), selector, scope


def _commit(domain, digest, action, build):
    service = _writer_service(domain)
    with _writer(), domain._connection(write=True) as db:
        roots = domain._read_roots(db)
        _install_event_schema(db, roots.genesis.id)  # a bare test DomainStore has no event tables yet
        history = service._slot_history(db, roots, digest)
        head = service._head(history)
        extension_id, fields, consume = build(db, roots, service, history, head)
        given = fields.pop("_key", None)
        key = history[0][1]["binding_slot_key"] if history else given
        return service._append(db, roots, roots.actor, action=action, command_id=str(uuid4()),
                               request_sha256="0" * 64, extension_id=extension_id, key=key, digest=digest,
                               history=history, expected=head, fields=fields, stamp=STAMP,
                               now_ms=1_758_758_400_000, consume=consume)


def bind(domain, installations, *, qualification_ref, extension_id="claude-semantic-worker", label="a",
         slot=None, **slot_changes):
    """Bind (absent/disabled head) or supersede (active head) with a new verified installation."""
    key, digest, selector, scope = slot or slot_values(**slot_changes)
    verified, tuple_value = verified_installation(domain, installations, extension_id=extension_id,
                                                  label=label)

    def build(_db, _roots, _service, _history, head):
        contract = PORT_CONTRACTS["provider-port-v1"]
        supersede = head is not None and head["state"] == "active"
        return extension_id, {
            "_key": key, "state": "active", "action": "supersede" if supersede else "bind",
            "port_contract_version": "provider-port-v1", "extension_kind": contract.extension_kind,
            "trust_tier": contract.trust_tier, "capability_selector": selector, "target_scope": scope,
            "installation_ref": verified.as_dict(),
            "target_installation": {"extension_id": extension_id, "revision": 2,
                                    "installation_record_digest": verified.sha256},
            "service_tuple": tuple_value, "qualification_ref": dict(qualification_ref),
            "supersedes_revision": ({"revision": head["revision"],
                                     "binding_record_digest": head["binding_record_digest"]}
                                    if supersede else None),
            "rollback_of_revision": None}, None

    result = _commit(domain, digest, "bind", build)
    return SimpleNamespace(result=result, key=key, digest=digest, selector=selector, scope=scope,
                           installation=verified, ref=head_ref(result, digest))


def disable(domain, digest):
    def build(_db, _roots, _service, history, _head):
        current = history[-1][1]
        fields = {name: current[name] for name in (
            "port_contract_version", "extension_kind", "trust_tier", "capability_selector", "target_scope",
            "installation_ref", "target_installation", "service_tuple", "qualification_ref")}
        fields.update(state="disabled", action="disable", supersedes_revision=None, rollback_of_revision=None)
        return current["extension_id"], fields, None

    result = _commit(domain, digest, "disable", build)
    return SimpleNamespace(result=result, ref=head_ref(result, digest))


def rollback(domain, digest, target_revision):
    def build(db, roots, service, history, head):
        target_ref, target = history[target_revision - 1]
        retention = service._retention(db, roots, digest, target_ref.sha256)
        fields = {name: target[name] for name in (
            "port_contract_version", "extension_kind", "trust_tier", "capability_selector", "target_scope",
            "installation_ref", "target_installation", "service_tuple", "qualification_ref")}
        fields.update(state="active", action="rollback",
                      supersedes_revision=None if head["state"] != "active" else {
                          "revision": head["revision"], "binding_record_digest": head["binding_record_digest"]},
                      rollback_of_revision={"revision": target_ref.version,
                                            "binding_record_digest": target_ref.sha256})
        ref = {"revision": target_ref.version, "binding_record_digest": target_ref.sha256}
        return target["extension_id"], fields, (ref, target_ref, retention)

    result = _commit(domain, digest, "rollback", build)
    return SimpleNamespace(result=result, ref=head_ref(result, digest))


def head_ref(result, digest):
    head = result["binding_head"]
    return {"kind": "extension_binding", "id": slot_record_id(digest), "version": head["revision"],
            "sha256": head["binding_record_digest"]}


def config_identity(bound):
    """The `canonical_provider_config` identity fields that name this durable binding."""
    return {"installation_digest": bound.installation.sha256, "binding_revision_ref": bound.ref,
            "target_scope_fingerprint": bound.key["target_scope_fingerprint"],
            "capability_selector_digest": bound.key["capability_selector_digest"]}


def binding_refs(config_value):
    return {"grant_refs": config_value["grant_refs"],
            "credential_handle_refs": config_value["credential_handle_refs"]}
