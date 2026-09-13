"""Regression tests for the operations-batch adversarial audit (2026-09-13).

F1 the canary scan walks decoded field values, so secrets containing
quotes, backslashes or newlines refuse the build; F2 tombstones carry the
contract's mandatory fields (deleted_at, deletion_request_id, reason_code)
and the validated actor evidence; F3 duplicate ids never inflate a
deletion preview; F5 the manifest carries the contract's full header
(bundle_id, created_at, app_release, export_policy_ref,
pseudonym_map_scope, reproduction_limits); F6 relative paths and export
ids are unique within a manifest; F7 tab/CR-prefixed formulas are escaped
in safe mode; F8 format validation is bounded against hostile files;
F9/F13 control characters are refused at input time consistently
(including NUL inside JSON strings); F10 linked ids are bounded and
canaries type-checked; F12 the reopened title is verified.
"""

import json
import zipfile

import pytest

from app.adapters.documents import (
    DocumentToolError,
    render_csv,
    render_docx,
    render_json,
    validate_format,
)
from app.operations.export import (
    ExportError,
    build_export_manifest,
    create_export_request,
    seal_export,
)
from app.operations.retention import (
    RetentionError,
    delete_items,
    preview_deletion,
)
from app.tests.test_alternatives import ref
from app.tests.test_document_tools import docx_spec
from app.tests.test_export import item_value, missing_value, request_value
from app.tests.test_retention import ACTOR, NOW, ledger

DELETE_REQUEST = "00000000-0000-4000-8000-00000000de01"


def actor():
    return {
        "actor_id": ACTOR, "authenticated": True,
        "evidence": ref("action_approval", 1703),
    }


def manifest_kwargs(**overrides):
    value = {
        "secret_canaries": [],
        "created_at": "2026-09-13T16:00:00.000000Z",
        "app_release": "0.1.0-dev",
        "pseudonym_map_scope": "bundle-local",
        "reproduction_limits": ["로컬 STT 원음은 포함되지 않는다"],
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize("canary", [
    'pw"quote',
    "line1\nline2",
    "back\\slash",
    "-----BEGIN PRIVATE KEY-----\nabc",
])
def test_f1_escape_carrying_canaries_still_refuse(canary):
    request = create_export_request(request_value(
        scope=f"environment:{canary}:2026-09",
    ))
    with pytest.raises(ExportError):
        build_export_manifest(
            request, [item_value()], [],
            **manifest_kwargs(secret_canaries=[canary]),
        )


def test_f2_tombstones_carry_the_mandated_fields_and_evidence():
    state = ledger()
    preview = preview_deletion(state, ["cache-preview"])
    deleted = delete_items(
        state, preview, actor=actor(),
        deleted_at=NOW, deletion_request_id=DELETE_REQUEST,
        reason_code="user_requested",
    )
    tombstone = deleted.tombstones[0]
    assert tombstone.deleted_at == NOW
    assert tombstone.deletion_request_id == DELETE_REQUEST
    assert tombstone.reason_code == "user_requested"
    assert tombstone.evidence_ref.as_dict() == ref("action_approval", 1703)
    with pytest.raises(RetentionError):
        delete_items(
            state, preview_deletion(state, ["diag-log"]), actor=actor(),
            deleted_at=NOW, deletion_request_id=DELETE_REQUEST,
            reason_code="vibes",
        )


def test_f3_duplicate_ids_never_inflate_a_preview():
    state = ledger()
    with pytest.raises(RetentionError):
        preview_deletion(state, ["cache-preview", "cache-preview"])


def test_f5_the_manifest_carries_the_full_contract_header():
    request = create_export_request(request_value())
    manifest = build_export_manifest(
        request, [item_value()], [], **manifest_kwargs(),
    )
    payload = manifest.as_dict()
    for name in ("bundle_id", "created_at", "app_release",
                 "export_policy_ref", "pseudonym_map_scope",
                 "reproduction_limits", "checksum_algorithm"):
        assert name in payload, name
    assert payload["export_policy_ref"] == ref("access_policy", 1801)
    receipt = seal_export(
        manifest, bundle_sha256="cc" * 32, size_bytes=10,
        completed_at="2026-09-13T16:30:00.000000Z",
        artifact_ref=ref("artifact", 1804),
    )
    assert receipt.bundle_id == payload["bundle_id"]


def test_f6_paths_and_export_ids_are_unique_within_a_manifest():
    request = create_export_request(request_value())
    with pytest.raises(ExportError):
        build_export_manifest(request, [
            item_value(export_id="x-1"),
            item_value(export_id="x-2"),  # same relative_path
        ], [], **manifest_kwargs())
    with pytest.raises(ExportError):
        build_export_manifest(request, [
            item_value(export_id="x-1"),
            item_value(export_id="x-1",
                       relative_path="events/other.jsonl"),
        ], [], **manifest_kwargs())


def test_f7_tab_and_cr_prefixed_formulas_are_escaped(tmp_path):
    report = render_csv(
        [["\t=2+5+cmd|' /C calc'!A0", "\r=HYPERLINK(1)"]],
        tmp_path / "safe.csv", safe_spreadsheet=True,
    )
    assert len(report.transformations) == 2


def test_f8_format_validation_is_bounded(tmp_path):
    bomb = tmp_path / "bomb.docx"
    with zipfile.ZipFile(bomb, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w/>")
        for index in range(20_000):
            archive.writestr(f"word/junk{index}.xml", "x")
    with pytest.raises(DocumentToolError):
        validate_format(bomb, "docx")
    big = tmp_path / "big.csv"
    big.write_bytes(b"a" * (64 * 1024 * 1024 + 1))
    with pytest.raises(DocumentToolError):
        validate_format(big, "csv")


def test_f9_control_characters_are_refused_at_input_time(tmp_path):
    with pytest.raises(DocumentToolError):
        render_docx(docx_spec(paragraphs=["bad\x0bchar"]),
                    tmp_path / "a.docx")
    with pytest.raises(DocumentToolError):
        render_docx(docx_spec(
            tables=[{"rows": [["ok", "bad\rcell"]]}],
        ), tmp_path / "b.docx")


def test_f13_json_nul_is_refused_like_everywhere_else(tmp_path):
    with pytest.raises(DocumentToolError):
        render_json({"x": "a\x00b"}, tmp_path / "bad.json")
    nul_json = tmp_path / "nul.json"
    nul_json.write_text(json.dumps({"x": "a\x00b"}), encoding="utf-8")
    with pytest.raises(DocumentToolError):
        validate_format(nul_json, "json")


def test_f10_linked_ids_bounded_and_canaries_typed():
    request = create_export_request(request_value())
    with pytest.raises(ExportError):
        build_export_manifest(request, [
            item_value(linked_export_ids=["x" * 300_000]),
        ], [], **manifest_kwargs())
    with pytest.raises(ExportError):
        build_export_manifest(request, [
            item_value(linked_export_ids=[""]),
        ], [], **manifest_kwargs())
    with pytest.raises(ExportError):
        build_export_manifest(
            request, [item_value()], [],
            **manifest_kwargs(secret_canaries=[b"bytes"]),
        )
    assert missing_value is not None


def test_f12_the_reopened_title_is_verified(tmp_path):
    report = render_docx(docx_spec(), tmp_path / "titled.docx")
    assert report.title_verified is True
