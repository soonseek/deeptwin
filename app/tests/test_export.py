"""US7 export: previewed scope, honest redaction, no circular hashes.

An export request names its exact scope and categories — hidden reasoning
and credentials are not selectable items, and raw originals are included
only by explicit selection. The manifest distinguishes the original source
hash from the exported bytes hash (source_sha256 exists only when raw
inclusion was explicit), keeps missing-evidence reasons distinct (redaction
vs non-selection vs real record gaps are never one error), uses restricted
relative paths only (no traversal, no absolute paths, no NUL), and never
re-exposes bodies, real paths or keys — a secret canary anywhere in the
manifest refuses the build. The receipt lives OUTSIDE the archive: the
manifest never contains the archive's own hash (no circular hash
structure), and the receipt binds manifest hash and bundle hash together
(operations.md ExportRequest/Manifest/Receipt; FR-028/029; T071).
"""

import dataclasses

import pytest

from app.operations.export import (
    EXPORT_CATEGORIES,
    ExportError,
    build_export_manifest,
    create_export_request,
    seal_export,
)
from app.tests.test_alternatives import ref

REQUEST_ID = "00000000-0000-4000-8000-00000000ex01".replace("x", "a")


def request_value(**overrides):
    value = {
        "request_id": REQUEST_ID,
        "scope": "environment:e-001/2026-09",
        "selected_categories": ["events", "artifacts_metadata"],
        "include_raw_refs": [],
        "redaction_policy_ref": ref("access_policy", 1801),
        "author_consent_ref": ref("run_consent", 1802),
        "created_at": "2026-09-13T13:00:00.000000Z",
    }
    value.update(overrides)
    return value


def item_value(**overrides):
    value = {
        "export_id": "x-0001",
        "kind": "event_log",
        "relative_path": "events/run-1.jsonl",
        "media_type": "application/jsonl",
        "size_bytes": 2_048,
        "export_sha256": "aa" * 32,
        "linked_export_ids": [],
        "content_mode": "metadata_only",
        "source_hash_included": False,
        "source_sha256": None,
        "license_or_share_basis": None,
    }
    value.update(overrides)
    return value


def missing_value(**overrides):
    value = {
        "export_ref": "x-0002",
        "reason": "not_selected",
        "affected_claims": ["도구 관찰 재현"],
        "recoverable_by_user": True,
    }
    value.update(overrides)
    return value


def test_hidden_reasoning_and_credentials_are_never_selectable():
    assert "hidden_reasoning" not in EXPORT_CATEGORIES
    assert "credentials" not in EXPORT_CATEGORIES
    request = create_export_request(request_value())
    assert request.selected_categories == ("artifacts_metadata", "events")
    with pytest.raises(ExportError):
        create_export_request(request_value(
            selected_categories=["events", "hidden_reasoning"],
        ))
    with pytest.raises(ExportError):
        create_export_request(request_value(selected_categories=[]))


def test_source_hash_exists_only_with_explicit_raw_inclusion():
    request = create_export_request(request_value(
        include_raw_refs=[ref("artifact", 1803)],
    ))
    manifest = build_export_manifest(request, [
        item_value(export_id="x-raw", content_mode="raw",
                   source_hash_included=True, source_sha256="bb" * 32),
        item_value(),
    ], [missing_value()], secret_canaries=[])
    raw_item = manifest.items[0]
    assert raw_item.source_sha256 == "bb" * 32
    with pytest.raises(ExportError):
        # a source hash without explicit inclusion re-exposes the original
        build_export_manifest(request, [
            item_value(source_sha256="bb" * 32),
        ], [], secret_canaries=[])
    with pytest.raises(ExportError):
        # raw content without any raw selection on the request
        build_export_manifest(
            create_export_request(request_value()),
            [item_value(content_mode="raw", source_hash_included=True,
                        source_sha256="bb" * 32)],
            [], secret_canaries=[],
        )


def test_missing_evidence_reasons_stay_distinct():
    request = create_export_request(request_value())
    manifest = build_export_manifest(request, [item_value()], [
        missing_value(reason="redacted"),
        missing_value(export_ref="x-0003", reason="not_recorded",
                      recoverable_by_user=False),
    ], secret_canaries=[])
    assert [entry.reason for entry in manifest.missing_evidence] == [
        "redacted", "not_recorded",
    ]
    with pytest.raises(ExportError):
        build_export_manifest(request, [item_value()], [
            missing_value(reason="somehow_gone"),
        ], secret_canaries=[])


@pytest.mark.parametrize("poison", [
    "/etc/passwd",
    "../outside.txt",
    "events/../../up.jsonl",
    "C:\\Windows\\evil",
    "events/a\x00b",
])
def test_archive_paths_are_restricted_relative_only(poison):
    request = create_export_request(request_value())
    with pytest.raises(ExportError):
        build_export_manifest(request, [
            item_value(relative_path=poison),
        ], [], secret_canaries=[])


def test_a_secret_canary_anywhere_refuses_the_build():
    request = create_export_request(request_value())
    with pytest.raises(ExportError):
        build_export_manifest(request, [
            item_value(relative_path="events/sk-SECRET123.jsonl"),
        ], [], secret_canaries=["sk-SECRET123"])
    with pytest.raises(ExportError):
        build_export_manifest(request, [item_value()], [
            missing_value(affected_claims=["sk-SECRET123 노출 여부"]),
        ], secret_canaries=["sk-SECRET123"])


def test_the_receipt_lives_outside_and_no_hash_is_circular():
    request = create_export_request(request_value())
    manifest = build_export_manifest(
        request, [item_value()], [], secret_canaries=[],
    )
    payload = manifest.as_dict()
    assert "bundle_sha256" not in str(payload)  # no self-referential hash
    receipt = seal_export(
        manifest, bundle_sha256="cc" * 32, size_bytes=10_000,
        completed_at="2026-09-13T13:30:00.000000Z",
        artifact_ref=ref("artifact", 1804),
    )
    assert receipt.manifest_sha256 == manifest.manifest_sha
    assert receipt.bundle_sha256 == "cc" * 32
    with pytest.raises(ExportError):
        seal_export(object(), bundle_sha256="cc" * 32, size_bytes=1,
                    completed_at="2026-09-13T13:30:00.000000Z",
                    artifact_ref=ref("artifact", 1804))


def test_values_are_issued_never_constructed():
    request = create_export_request(request_value())
    with pytest.raises(TypeError):
        dataclasses.replace(request, scope="everything")
    manifest = build_export_manifest(
        request, [item_value()], [], secret_canaries=[],
    )
    with pytest.raises(TypeError):
        dataclasses.replace(manifest, items=())
    with pytest.raises(ExportError):
        build_export_manifest(object(), [item_value()], [],
                              secret_canaries=[])
