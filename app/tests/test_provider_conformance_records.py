import pytest
from uuid import uuid4

from app.domain.refs import EntityRef
from app.domain.store import StorageError, _writer
from app.extensions.provider_conformance_contracts import ConformanceError, ConformanceSubject
from app.tests.provider_conformance_fixture import staged_conformance_app
from app.tests.provider_receipt_fixture import (
    install_receipt,
    provider_receipt_context,
    provider_worker,
    signed_receipt,
)


def test_private_prepare_delegate_resolves_actual_verified_stage_in_same_writer(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        with _writer(), staged.domain._connection(write=True) as db:
            subject = staged.prepare._provider_conformance_subject(db, staged.installation_ref)
        assert type(subject) is ConformanceSubject
        assert subject.installation_ref == staged.installation_ref
        assert subject.as_dict()["implemented_transforms"] == ["catalog", "text"]
        assert subject.uid > 0 and subject.gid > 0
        subject.as_dict()["implemented_transforms"].append("mutated")
        assert subject.as_dict()["implemented_transforms"] == ["catalog", "text"]


def test_private_prepare_delegate_requires_exact_active_domain_writer(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        with pytest.raises(StorageError):
            staged.prepare._provider_conformance_subject(None, staged.installation_ref)


def test_mixed_tool_and_provider_heads_select_only_exact_provider_installation(
        tmp_path, monkeypatch):
    with provider_receipt_context(tmp_path.resolve(), monkeypatch, legacy_staged=True,
                                  slot_id=2) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(actual.read_request,
                                               prepared["request_id"])["request"]
        receipt_digest = install_receipt(actual, signed_receipt(actual, request))
        selector = {"command_id": str(uuid4()), "request_digest": prepared["request_digest"],
                    "receipt_digest": receipt_digest, "expected_revision": 1}
        actual.service.import_provider_receipt(actual.request, prepared["request_id"], selector)
        consume = {**selector, "command_id": str(uuid4()), "expected_revision": 2}
        with provider_worker(actual, monkeypatch):
            accepted = actual.service.consume_provider_receipt(
                actual.request, prepared["request_id"], consume)
        provider_ref = EntityRef.from_dict(accepted["installation_ref"])
        with _writer(), actual.domain._connection(write=True) as db:
            journal = actual.service._journal(db)
            refs = [item["installation"]["ref"] for item in journal["requests"].values()
                    if item.get("installation") is not None]
            assert len(refs) == 2 and provider_ref in refs
            tool_ref = next(ref for ref in refs if ref != provider_ref)
            with pytest.raises(ConformanceError) as caught:
                actual.service._provider_conformance_subject(db, tool_ref)
            assert caught.value.code == "unavailable"
            subject = actual.service._provider_conformance_subject(db, provider_ref)
        assert subject.installation_ref == provider_ref
        assert subject.slot_id == 2
