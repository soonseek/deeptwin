"""T087 provider-transport manifest: the gateway binds sends only through a qualified one.

- The shipped Claude API manifest is canonical data; the gateway's binding (origin,
  methods, path prefixes, projected headers and values, auth header, byte bounds, each
  endpoint's method/path/query/cursor/response media type) is built from it alone.
- A binding without a manifest, a vault with no adopted qualification, or a manifest whose
  digest differs from the adopted qualification's refuses the send before any provider
  byte (the loopback mock provider records every request).
- The qualification act runs through the existing T087 installation and conformance path
  (a verified installation, the fixed provider-port suite matched 4/4 through the framed
  worker) plus the offline transport conformance of the manifest against a local mock
  provider, seals the record and publishes the gateway document; the document adopted by a
  real vault lets the manifest-built transport send.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef, canonical_json, parse_canonical
from app.tests.provider_installation_fixture import (
    installation_case,  # noqa: F401 - fixture
)
from app.tests.support.provider_semantic_harness import (
    connection_values,
    controlled_upstream,
    encrypted_credential,
)
from app.tests.support.transport_manifest import (
    loopback_binding,
    synthetic_qualification,
)
from app.tests.test_provider_send_gateway import prepared, prepared_catalog
from app.workers.credential_contracts import CredentialVaultError
from app.workers.provider_gateway import (
    CredentialedProviderTransport,
    GatewayError,
    ProviderBinding,
    claude_api_manifest_binding,
)
from app.workers.provider_send_messages import ProviderSendError
from app.workers.provider_send_service import ProviderSendService
from app.workers.provider_transport_manifest import (
    CLAUDE_API_MANIFEST,
    TransportManifestError,
    claude_api_manifest,
    claude_api_manifest_bytes,
    parse_qualification,
    parse_transport_manifest,
)


def manifest_value():
    return parse_canonical(claude_api_manifest_bytes())


def changed(**changes):
    value = manifest_value()
    for path, new in changes.items():
        target = value
        keys = path.split("__")
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = new
    return canonical_json(value)


def exchange(service, message):
    ready = service.prepare(message)
    return service.exchange(service.commit(ready["exchange_id"], ready["prepare_sha256"],
                                           str(uuid4())))


# ------------------------------------------------------------------ the manifest


def test_the_shipped_manifest_is_the_whole_request_surface():
    raw = CLAUDE_API_MANIFEST.read_bytes()
    manifest = parse_transport_manifest(raw)
    assert canonical_json(parse_canonical(raw)) == raw  # canonical bytes, digest = identity
    binding = claude_api_manifest_binding()
    assert binding.manifest_sha256 == manifest.manifest_sha256
    assert (binding.scheme, binding.host, binding.port) == ("https", manifest.host, 443)
    assert manifest.api_origin == "https://" + manifest.host
    assert binding.allowed_methods == tuple(manifest_value()["allowed_methods"])
    assert binding.allowed_path_prefixes == tuple(manifest_value()["allowed_path_prefixes"])
    assert dict(binding.request_headers) == manifest_value()["request_headers"]
    assert binding.auth_header == manifest_value()["auth_header"]
    assert (binding.max_request_bytes, binding.max_response_bytes) == (
        manifest_value()["max_request_bytes"], manifest_value()["max_response_bytes"])
    method, target, headers, media = binding.endpoint_request("messages", None)
    assert (method, target, media) == ("POST", "/v1/messages", "text/event-stream")
    assert headers == manifest_value()["request_headers"]
    method, target, _headers, media = binding.endpoint_request("models", "model/one")
    assert (method, target, media) == ("GET", "/v1/models?limit=100&after_id=model%2Fone",
                                       "application/json")
    with pytest.raises(GatewayError):
        binding.endpoint_request("messages", "cursor")  # no cursor on the message endpoint
    with pytest.raises(GatewayError):
        binding.endpoint_request("other", None)


def test_a_changed_manifest_is_a_different_binding():
    edited = parse_transport_manifest(changed(max_response_bytes=65_536))
    assert edited.manifest_sha256 != claude_api_manifest().manifest_sha256
    binding = ProviderBinding.from_manifest(edited)
    assert binding.max_response_bytes == 65_536
    projection = changed(request_headers={"anthropic-version": "2099-01-01",
                                          "content-type": "application/json"})
    other = ProviderBinding.from_manifest(parse_transport_manifest(projection))
    assert other.endpoint_request("models", None)[2]["anthropic-version"] == "2099-01-01"


@pytest.mark.parametrize("raw", [
    b" " + claude_api_manifest_bytes(),                               # not canonical
    changed(api_origin="http://api.example.com"),                     # not https
    changed(api_origin="https://api.example.com/v1"),                 # origin with a path
    changed(request_headers={"authorization": "x", "content-type": "application/json"}),
    changed(request_headers={"anthropic-version": "a\nb"}),           # header injection
    changed(auth_header="content-type"),                              # auth over a projection
    changed(endpoints__models__path="/v2/models"),                    # outside the prefixes
    changed(endpoints__models__method="DELETE"),
    changed(endpoints__messages__request_body="empty"),
    changed(endpoints__models__cursor_parameter=None),
    changed(endpoints__models__query=[["limit", "100"], ["after_id", "x"]]),
    changed(max_response_bytes=0),
    changed(extra=1),
    changed(schema_version="provider-transport-manifest-v2"),
])
def test_the_manifest_parser_fails_closed(raw):
    with pytest.raises(TransportManifestError):
        parse_transport_manifest(raw)


def test_the_qualification_document_is_closed_and_all_or_nothing():
    document = synthetic_qualification()
    assert parse_qualification(document) == document
    for mutate in (
        lambda value: value["installation_conformance"].update(matched_count=3),
        lambda value: value["transport_conformance"].update(completed_count=3),
        lambda value: value.update(extra=1),
        lambda value: value.update(manifest_sha256="x"),
        lambda value: value["installation_conformance"]["verified_installation_ref"].update(
            id=str(uuid4())),
        lambda value: value["installation_conformance"]["result_ref"].update(id=str(uuid4())),
    ):
        broken = synthetic_qualification()
        mutate(broken)
        with pytest.raises(TransportManifestError):
            parse_qualification(broken)


# ------------------------------------------------------------------ the gateway's refusals


def test_a_binding_without_a_manifest_never_sends(tmp_path):
    with controlled_upstream() as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        bare = ProviderBinding(provider="claude", scheme="http", host="127.0.0.1", port=port,
                               allowed_methods=("GET", "POST"), allowed_path_prefixes=("/v1",),
                               allowed_request_headers=("anthropic-version", "content-type"),
                               auth_header="x-api-key", max_request_bytes=1_048_576,
                               max_response_bytes=1_048_576, timeout_seconds=2)
        service = ProviderSendService(CredentialedProviderTransport(vault, bare))
        with pytest.raises(ProviderSendError) as refused:
            exchange(service, prepared_catalog(meta, record, handle, pin))
        assert (refused.value.failure_class, refused.value.phase) == (
            "unsupported_capability", "not_sent")
        assert captures == [] and vault.consumed_reservations() == []


def test_an_unqualified_vault_refuses_every_send(tmp_path):
    from app.tests.test_credential_custody import metadata
    from app.tests.test_credential_root import initialized
    from app.workers.credential_vault import CredentialVault

    with controlled_upstream() as (port, captures, _entered, _release), \
            CredentialVault(**initialized(tmp_path)) as vault:
        meta = metadata()
        receipt = vault.store_at(metadata=meta, secret=b"synthetic-manifest-key-0001")
        record = {key: receipt[key] for key in ("record_id", "record_version", "ciphertext_sha256")}
        vault.bind_head(provider="claude", revision=1, state="bound", record=record)
        assert vault.transports() == []
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, loopback_binding(port)))
        for message in (prepared_catalog(meta, record, handle, pin),
                        prepared(meta, record, handle, pin)):
            with pytest.raises(ProviderSendError) as refused:
                exchange(service, message)
            assert (refused.value.failure_class, refused.value.phase) == (
                "unsupported_capability", "not_sent")
        assert captures == [] and vault.consumed_reservations() == []


def test_a_manifest_changed_after_qualification_refuses_until_requalified(tmp_path):
    with controlled_upstream() as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        edited = parse_transport_manifest(changed(max_response_bytes=524_288))
        binding = ProviderBinding.from_manifest(edited, loopback_port=port)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding))
        # the vault's qualification names the shipped manifest's digest, not this one
        with pytest.raises(ProviderSendError) as refused:
            exchange(service, prepared_catalog(meta, record, handle, pin))
        assert (refused.value.failure_class, refused.value.phase) == (
            "unsupported_capability", "not_sent")
        assert captures == []
        # a binding field altered without a new manifest is not the manifest either
        forged = replace(loopback_binding(port), manifest_sha256="0" * 64)
        forged_service = ProviderSendService(CredentialedProviderTransport(vault, forged))
        with pytest.raises(ProviderSendError):
            exchange(forged_service, prepared_catalog(meta, record, handle, pin))
        assert captures == []
        # a later qualification of the edited manifest adopts it; the shipped one now refuses
        vault.bind_transport(qualification=synthetic_qualification(
            revision=2, manifest_sha256=edited.manifest_sha256))
        assert exchange(service, prepared_catalog(meta, record, handle, pin)).status == 200
        assert len(captures) == 1
        shipped = ProviderSendService(CredentialedProviderTransport(vault, loopback_binding(port)))
        with pytest.raises(ProviderSendError):
            exchange(shipped, prepared_catalog(meta, record, handle, pin))
        assert len(captures) == 1


def test_bind_transport_is_revision_monotone_idempotent_and_journal_validated(tmp_path):
    with encrypted_credential(tmp_path) as (vault, _meta, _record):
        (adopted,) = vault.transports()
        assert vault.bind_transport(qualification=adopted) == adopted  # identical replay
        stale = synthetic_qualification(revision=adopted["revision"])
        with pytest.raises(CredentialVaultError) as conflict:
            vault.bind_transport(qualification=stale)  # same revision, another body
        assert conflict.value.code == "conflict"
        newer = synthetic_qualification(revision=5)
        vault.bind_transport(qualification=newer)
        with pytest.raises(CredentialVaultError):
            vault.bind_transport(qualification=synthetic_qualification(revision=4))
        assert vault.transports() == [newer]
        with pytest.raises(CredentialVaultError) as invalid:
            broken = synthetic_qualification(revision=6)
            broken["transport_conformance"]["matched_count"] = 3
            vault.bind_transport(qualification=broken)
        assert invalid.value.code == "invalid_metadata"
        assert "bind_transport" in vault.capabilities()["operations"]


def test_a_journal_without_the_new_tables_gains_them(tmp_path):
    import sqlite3

    from app.tests.test_credential_root import initialized
    from app.workers.credential_vault import CredentialVault

    args = initialized(tmp_path)
    CredentialVault(**args).close()
    path = args["records_directory"] / "journal.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE transports")
        db.execute("DROP TABLE sends")
    with CredentialVault(**args) as vault:
        assert vault.transports() == [] and vault.consumed_reservations() == []


# ------------------------------------------------------------------ the qualification act


def test_the_manifest_is_qualified_through_installation_and_transport_conformance(
        installation_case, monkeypatch, tmp_path):
    from app.domain.store import _writer
    from app.extensions.provider_transport_qualification import (
        COMMAND_SCHEMA,
        PersistentTransportQualification,
        TransportQualificationError,
    )
    from app.tests.provider_conformance_fixture import (
        _retained_provider_conformance_worker,
    )
    from app.tests.test_provider_conformance_verified import verified_command

    case = installation_case
    published = []
    qualification = PersistentTransportQualification(
        case.b_service, publisher=lambda **kwargs: published.append(kwargs["qualification"]))
    manifest = claude_api_manifest()

    def command(conformance_command_id, digest=manifest.manifest_sha256):
        return {"schema_version": COMMAND_SCHEMA, "command_id": str(uuid4()),
                "conformance_command_id": conformance_command_id, "manifest_sha256": digest}

    # no conformance run yet
    with pytest.raises(TransportQualificationError) as missing:
        qualification.qualify(case.actual.request, command(str(uuid4())))
    assert missing.value.code == "not_found"
    verified = case.verification_service.execute(case.actual.request, case.packet)
    run = verified_command(case, verified)
    with _retained_provider_conformance_worker(case, monkeypatch):
        reply = case.b_service.execute(case.actual.request, run)
    assert reply["state"] == "matched"
    # the owner names the manifest digest; a different (changed) manifest is refused
    with pytest.raises(TransportQualificationError) as changed_manifest:
        qualification.qualify(case.actual.request, command(run["command_id"], "0" * 64))
    assert changed_manifest.value.code == "conflict" and published == []
    result = qualification.qualify(case.actual.request, command(run["command_id"]))
    document = result["qualification"]
    assert result["published"] is True and published == [document]
    assert parse_qualification(document) == document
    assert document["manifest_sha256"] == manifest.manifest_sha256
    installation = document["installation_conformance"]
    assert installation["command_id"] == run["command_id"]
    assert installation["verified_installation_ref"] == verified["verified_installation_ref"]
    assert installation["result_ref"] == reply["result_ref"]
    # the sealed record carries the manifest, both conformance results and its lineage
    record_ref = EntityRef.from_dict(document["qualification_ref"])
    with _writer(), case.domain._connection(write=True) as db:
        record = case.domain._load(db, record_ref, case.domain._read_roots(db))[0]
    content = record.body["content"]
    assert content["manifest"].encode() == claude_api_manifest_bytes()
    transport = parse_canonical(content["transport_conformance_result"].encode())
    assert (transport["completed_count"], transport["matched_count"]) == (4, 4)
    assert [row["vector_id"] for row in transport["vectors"]] == [
        "text-basic-v1", "text-refusal-v1", "catalog-two-pages-v1",
        "catalog-negative-capability-v1"]
    assert {EntityRef.from_dict(ref) for ref in record.body["parent_refs"]} == {
        EntityRef.from_dict(verified["verified_installation_ref"]),
        EntityRef.from_dict(reply["result_ref"])}
    # idempotent: the same run and manifest answer (and republish) the same document
    again = qualification.qualify(case.actual.request, command(run["command_id"]))
    assert again["qualification"] == document and published == [document, document]

    # the published document, adopted by a real gateway vault, qualifies the transport
    (tmp_path / "gateway").mkdir()
    with controlled_upstream() as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path / "gateway") as (vault, meta, record_value):
        vault.bind_transport(qualification=document)  # the real revision is later
        handle, pin, _, _ = connection_values(meta, record_value)
        service = ProviderSendService(CredentialedProviderTransport(vault, loopback_binding(port)))
        assert exchange(service, prepared_catalog(meta, record_value, handle, pin)).status == 200
        assert len(captures) == 1


def test_a_legacy_or_unmatched_conformance_run_does_not_qualify(installation_case, monkeypatch):
    from app.extensions.provider_transport_qualification import (
        COMMAND_SCHEMA,
        PersistentTransportQualification,
        TransportQualificationError,
    )
    from app.tests.provider_conformance_fixture import (
        _retained_provider_conformance_worker,
    )

    case = installation_case
    legacy = {"command_id": str(uuid4()), "installation_ref": case.stage_ref.as_dict()}
    with _retained_provider_conformance_worker(case, monkeypatch):
        reply = case.b_service.execute(case.actual.request, legacy)
    assert reply["schema_version"] == "provider-conformance-reply-v1"
    qualification = PersistentTransportQualification(case.b_service)
    with pytest.raises(TransportQualificationError) as refused:
        qualification.qualify(case.actual.request, {
            "schema_version": COMMAND_SCHEMA, "command_id": str(uuid4()),
            "conformance_command_id": legacy["command_id"],
            "manifest_sha256": claude_api_manifest().manifest_sha256})
    # only a matched run over a verified installation qualifies a transport
    assert refused.value.code == "conflict"


def test_the_offline_transport_conformance_detects_a_manifest_that_cannot_carry_the_vectors():
    from app.extensions.provider_transport_qualification import (
        run_transport_conformance,
    )

    result = parse_canonical(run_transport_conformance(claude_api_manifest()))
    assert (result["completed_count"], result["matched_count"]) == (4, 4)
    # a response bound below the vector bodies cannot carry the provider's answers
    small = parse_canonical(run_transport_conformance(
        parse_transport_manifest(changed(max_response_bytes=64))))
    assert small["matched_count"] < 4
    # a request bound below the message body cannot carry the requests
    tight = parse_canonical(run_transport_conformance(
        parse_transport_manifest(changed(max_request_bytes=8))))
    assert [row["matched"] for row in tight["vectors"]] == [False, False, True, True]
