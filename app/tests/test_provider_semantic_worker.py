import json
from uuid import uuid4

from app.tests.test_provider_semantic_codec import page, valid_stream
from app.tests.support.provider_semantic_harness import (canonical_provider_request,
                                                         immutable_ref)
from app.workers.provider_port_client import ProviderPortClient
from app.workers.provider_port_service import ProviderPortService


def request(operation, input_value):
    artifacts = ([{"artifact_ref": immutable_ref("artifact", "6"), "selector_ref": None,
                   "declared_media_type": "text/plain", "role": "model_input"}]
                 if operation == "model_step" else [])
    return canonical_provider_request(operation, input_value, artifact_inputs=artifacts)


def test_actual_text_roundtrip_all_five_operations():
    client = ProviderPortClient(ProviderPortService())
    assert client.execute(request("capabilities", {}))["output"] == {
        "modalities": ["text"], "tool_calling": False, "usage_reporting": True,
        "cancellation": True}

    catalog_request = request("catalog", {"catalog_epoch": None})
    proposal = client.begin(catalog_request)
    assert proposal.endpoint == "models" and proposal.after_id is None and proposal.body is None
    catalog = client.observe(proposal, status=200, raw=page(["m1"]))
    assert catalog.operation == "catalog" and catalog.complete and catalog.model_ids == ("m1",)

    frozen = {"turn": {"model_id": "model-1"}, "max_output_tokens": 8,
              "messages": [{"role": "user", "input_ordinals": [0]}]}
    model_request = request("model_step", {"frozen_turn_ref": {"kind": "frozen_turn",
        "id": str(uuid4()), "version": 1, "sha256": "a" * 64}, "model_id": "model-1",
        "effort": None, "requested_modalities": ["text"], "tool_definition_refs": [],
        "response_schema_ref": None})
    model = client.begin(model_request, frozen_content=frozen, input_bytes=(b"hello",))
    assert json.loads(model.body) == {"model": "model-1", "max_tokens": 8,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        "stream": True}
    observed = client.observe(model, status=200, raw=valid_stream())
    assert observed.operation == "model_step" and observed.text_blocks == (b"hello",)

    target = {"kind": "validation_report", "id": str(uuid4()), "version": 1, "sha256": "b" * 64}
    query = {"operation_ref": target, "observed_state": "running",
             "observed_at": "2026-09-20T00:00:00.000Z", "terminal_result_ref": None}
    assert client.execute(request("status", {"operation_ref": target}), query_state=query)["output"]["observed_state"] == "running"
    assert client.execute(request("cancel", {"operation_ref": target, "reason_class": "user_requested"}),
                          query_state=query)["output"]["cancel_state"] == "accepted"


def test_worker_refuses_unsupported_model_step_before_any_proposal():
    client = ProviderPortClient(ProviderPortService())
    frozen = {"turn": {"model_id": "model-1"}, "max_output_tokens": 8,
              "messages": [{"role": "user", "input_ordinals": [0]}]}
    bad = request("model_step", {"model_id": "model-1", "effort": "high",
        "requested_modalities": ["text"], "tool_definition_refs": [], "response_schema_ref": None,
        "frozen_turn_ref": {"kind": "frozen_turn", "id": str(uuid4()), "version": 1,
                            "sha256": "a" * 64}})
    result = client.execute(bad, frozen_content=frozen, input_bytes=(b"hello",))
    assert result["terminal"] == "failed" and result["output"] == {}
