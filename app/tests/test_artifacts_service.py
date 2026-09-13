"""US3 purpose-scoped artifacts: originals, derived previews, range reads.

An artifact is bytes plus MIME, digest, size, provenance, access purposes
and availability — a hash without bytes is `missing` and never counts as a
reproducible original. A preview is a DERIVED artifact with its own digest,
an explicit fidelity note and disclosed coverage (what it covers and what
it omits); deriving never touches the original, and the derived artifact
can never masquerade as it. Range reads are purpose-scoped: a purpose the
artifact was never granted refuses, a missing artifact refuses, and every
range is bounded by the real byte length (runtime.md §5, FR-015; T045
value slice — the browser viewers stay a separate UI concern).
"""

import dataclasses

import pytest

from app.services.artifacts import (
    ArtifactServiceError,
    derive_preview,
    derived_coverage,
    open_artifact_catalog,
    read_range,
    register_artifact,
)
from app.tests.test_alternatives import ref

ARTIFACT_ID = "00000000-0000-4000-8000-00000000aa01"


def artifact_value(**overrides):
    value = {
        "artifact_id": ARTIFACT_ID,
        "media_type": "application/pdf",
        "byte_length": 1_048_576,
        "sha256": "ee" * 32,
        "provenance_ref": ref("original_execution", 1601),
        "access_purposes": ["operation", "audit"],
        "availability": "available",
    }
    value.update(overrides)
    return value


def catalog():
    return register_artifact(open_artifact_catalog(), artifact_value())


def preview_value(**overrides):
    value = {
        "preview_id": "00000000-0000-4000-8000-00000000aa02",
        "media_type": "image/png",
        "byte_length": 65_536,
        "sha256": "ff" * 32,
        "fidelity_note": "1-4쪽을 144dpi로 렌더링; 주석 레이어는 제외",
        "covered": ["pages:1-4"],
        "omissions": ["pages:5-12", "annotations"],
    }
    value.update(overrides)
    return value


def test_a_hash_without_bytes_is_missing_never_an_original():
    state = register_artifact(open_artifact_catalog(), artifact_value(
        availability="missing",
    ))
    entry = state.entries[0]
    assert entry.availability == "missing"
    with pytest.raises(ArtifactServiceError):
        # missing bytes can never be range-read
        read_range(state, ARTIFACT_ID, purpose="operation",
                   start=0, length=100)
    with pytest.raises(ArtifactServiceError):
        register_artifact(open_artifact_catalog(), artifact_value(
            availability="probably_fine",
        ))
    with pytest.raises(ArtifactServiceError):
        register_artifact(catalog(), artifact_value())  # id registers once


def test_previews_are_derived_with_their_own_identity_and_coverage():
    state = derive_preview(catalog(), ARTIFACT_ID, preview_value())
    original = state.entries[0]
    derived = state.entries[1]
    assert original.sha256 == "ee" * 32  # the original is untouched
    assert derived.sha256 == "ff" * 32
    assert derived.derived_from == ARTIFACT_ID
    assert derived.fidelity_note.startswith("1-4쪽")
    coverage = derived_coverage(state, derived.artifact_id)
    assert coverage["covered"] == ("pages:1-4",)
    assert coverage["omissions"] == ("pages:5-12", "annotations")
    with pytest.raises(ArtifactServiceError):
        derive_preview(state, ARTIFACT_ID, preview_value(fidelity_note=""))
    with pytest.raises(ArtifactServiceError):
        # a preview of a missing original derives nothing
        derive_preview(
            register_artifact(open_artifact_catalog(), artifact_value(
                availability="missing",
            )),
            ARTIFACT_ID, preview_value(),
        )


def test_range_reads_are_purpose_scoped_and_bounded():
    state = catalog()
    descriptor = read_range(state, ARTIFACT_ID, purpose="operation",
                            start=1_000, length=4_096)
    assert descriptor.start == 1_000
    assert descriptor.length == 4_096
    assert descriptor.sha256 == "ee" * 32
    with pytest.raises(ArtifactServiceError):
        read_range(state, ARTIFACT_ID, purpose="tuning",  # never granted
                   start=0, length=100)
    with pytest.raises(ArtifactServiceError):
        read_range(state, ARTIFACT_ID, purpose="operation",
                   start=1_048_570, length=100)  # beyond the real length
    with pytest.raises(ArtifactServiceError):
        read_range(state, ARTIFACT_ID, purpose="operation",
                   start=-1, length=100)
    with pytest.raises(ArtifactServiceError):
        read_range(state, "00000000-0000-4000-8000-00000000aa99",
                   purpose="operation", start=0, length=100)


def test_derived_artifacts_never_masquerade_as_originals():
    state = derive_preview(catalog(), ARTIFACT_ID, preview_value())
    derived = state.entries[1]
    assert derived.is_original is False
    assert state.entries[0].is_original is True
    with pytest.raises(ArtifactServiceError):
        # a derived preview can never be re-registered as an original
        register_artifact(state, artifact_value(
            artifact_id=derived.artifact_id,
        ))
    with pytest.raises(ArtifactServiceError):
        derived_coverage(state, ARTIFACT_ID)  # originals have no coverage


def test_values_are_issued_never_constructed():
    state = catalog()
    with pytest.raises(TypeError):
        dataclasses.replace(state.entries[0], availability="available")
    with pytest.raises(TypeError):
        dataclasses.replace(state, entries=())
    with pytest.raises(ArtifactServiceError):
        register_artifact(object(), artifact_value())
    with pytest.raises(ArtifactServiceError):
        read_range(object(), ARTIFACT_ID, purpose="operation",
                   start=0, length=1)
