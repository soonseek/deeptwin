"""US3 whole-artifact handoffs: readiness, delivery, receipt, observed use.

A handoff binds the producer execution/attempt, the exact artifact refs,
the receiver execution/input slot and the schema check. Producer success is
readiness — it never waits on downstream receipt (no acknowledgment
deadlock), and a later handoff failure never retroactively erases producer
output. Delivery discloses the actually supplied spans and every
truncation; receipt is the receiver's separate acknowledgment; observed use
requires cited parts within the supplied spans — a filename or hash alone
is never full consumption. Availability, access, use and causal influence
are four different evidence levels: this module can prove at most "use",
and causal influence is never inferred from an edge (runtime.md §5, R06).
"""

import dataclasses

import pytest

from app.services.handoffs import (
    HandoffError,
    create_handoff,
    evidence_level,
    mark_ready,
    record_delivery,
    record_receipt,
    record_use,
)
from app.tests.test_alternatives import ref

PRODUCER_EXECUTION = "00000000-0000-4000-8000-00000000ce01"
RECEIVER_EXECUTION = "00000000-0000-4000-8000-00000000ce02"


def handoff_value(**overrides):
    value = {
        "handoff_id": "h-notes-to-writer",
        "producer_execution_id": PRODUCER_EXECUTION,
        "producer_attempt_index": 0,
        "artifact_refs": [ref("artifact", 1301), ref("artifact", 1302)],
        "receiver_execution_id": RECEIVER_EXECUTION,
        "receiver_input_slot": "notes-in",
        "schema_check_ref": ref("observation_contract", 1303),
    }
    value.update(overrides)
    return value


def delivered():
    handoff = mark_ready(
        create_handoff(handoff_value()),
        manifest_ref=ref("handoff", 1304),
    )
    return record_delivery(handoff, {
        "supplied_spans": [
            {"artifact_index": 0, "span": "pages:1-4"},
            {"artifact_index": 1, "span": "whole"},
        ],
        "truncations": ["1301의 5쪽 이후는 이번 요청에 포함되지 않았다"],
    })


def test_creation_binds_producer_receiver_and_exact_artifacts():
    handoff = create_handoff(handoff_value())
    assert handoff.status == "created"
    assert len(handoff.artifact_refs) == 2
    with pytest.raises(HandoffError):
        create_handoff(handoff_value(artifact_refs=[]))
    with pytest.raises(HandoffError):
        create_handoff(handoff_value(
            artifact_refs=[ref("artifact", 1301), ref("artifact", 1301)],
        ))
    with pytest.raises(HandoffError):
        create_handoff(handoff_value(producer_execution_id="not-a-uuid"))
    with pytest.raises(HandoffError):
        create_handoff({"unexpected": True})


def test_readiness_never_waits_on_receipt():
    handoff = create_handoff(handoff_value())
    ready = mark_ready(handoff, manifest_ref=ref("handoff", 1304))
    # producer success is complete at readiness — no downstream ack needed
    assert ready.producer_complete is True
    assert ready.status == "ready"
    with pytest.raises(HandoffError):
        # a receipt cannot precede delivery (no phantom acknowledgments)
        record_receipt(ready, receiver_ack_ref=ref("decision_record", 1305))


def test_delivery_discloses_spans_and_truncations():
    handoff = delivered()
    assert handoff.status == "delivered"
    assert handoff.truncations == (
        "1301의 5쪽 이후는 이번 요청에 포함되지 않았다",
    )
    with pytest.raises(HandoffError):
        record_delivery(handoff, {  # delivery can never repeat
            "supplied_spans": [{"artifact_index": 0, "span": "whole"}],
            "truncations": [],
        })
    bare = mark_ready(
        create_handoff(handoff_value()), manifest_ref=ref("handoff", 1304),
    )
    with pytest.raises(HandoffError):
        record_delivery(bare, {
            "supplied_spans": [{"artifact_index": 9, "span": "whole"}],
            "truncations": [],  # an index outside the bound artifacts
        })


def test_use_requires_cited_parts_within_supplied_spans():
    handoff = record_receipt(
        delivered(), receiver_ack_ref=ref("decision_record", 1305),
    )
    assert handoff.status == "received"
    with pytest.raises(HandoffError):
        # a filename or hash alone is never full consumption
        record_use(handoff, cited_parts=[])
    with pytest.raises(HandoffError):
        record_use(handoff, cited_parts=[
            {"artifact_index": 0, "span": "pages:9-12"},  # outside supplied
        ])
    used = record_use(handoff, cited_parts=[
        {"artifact_index": 0, "span": "pages:1-4"},
    ])
    assert used.status == "used"


def test_evidence_levels_are_distinct_and_never_causal():
    created = create_handoff(handoff_value())
    assert evidence_level(created) == "none"
    ready = mark_ready(created, manifest_ref=ref("handoff", 1304))
    assert evidence_level(ready) == "availability"
    handoff = delivered()
    assert evidence_level(handoff) == "availability"  # no receipt yet
    received = record_receipt(
        handoff, receiver_ack_ref=ref("decision_record", 1305),
    )
    assert evidence_level(received) == "access"
    used = record_use(received, cited_parts=[
        {"artifact_index": 1, "span": "whole"},
    ])
    assert evidence_level(used) == "use"
    # causal influence is a different proof entirely; nothing here mints it
    from app.services import handoffs

    assert not hasattr(handoffs, "record_causal_influence")


def test_values_are_issued_and_transitions_are_single_shot():
    handoff = delivered()
    with pytest.raises(TypeError):
        dataclasses.replace(handoff, status="used")
    with pytest.raises(HandoffError):
        mark_ready(handoff, manifest_ref=ref("handoff", 1304))
    with pytest.raises(HandoffError):
        record_use(handoff, cited_parts=[  # use before receipt
            {"artifact_index": 0, "span": "pages:1-4"},
        ])
    with pytest.raises(HandoffError):
        mark_ready(object(), manifest_ref=ref("handoff", 1304))
