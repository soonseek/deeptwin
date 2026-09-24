"""The one budget-capped LIVE Claude call through the product's own path.

It runs only when the operator provides `DEEPTWIN_LIVE_ANTHROPIC_API_KEY`; otherwise it
is skipped, and it never runs in the ordinary suite. The owner authorized it with a
cap of at most 10 calls, 512 output tokens per call and $1 in total. This test makes:
- one catalog read (`GET /v1/models`, free)
- one Messages call with `max_output_tokens=64`, on `DEEPTWIN_LIVE_MODEL` (default
  `claude-opus-5`)

The key goes in through the owner's connection route (server memory only) exactly as
a browser would send it, and is never printed, stored or asserted on.
"""

import json
import os

import pytest

from app.domain.refs import EntityRef
from app.services.claude_run_executor import (
    OUTPUT_SCHEMA,
    ClaudeRunExecutor,
    LiveLimits,
)
from app.tests.test_claude_live_path import claude, live_graph, real_work, start
from app.tests.test_runs_api import owner_app
from app.tests.test_web_owner_integration import headers

KEY = os.environ.get("DEEPTWIN_LIVE_ANTHROPIC_API_KEY")
MODEL = os.environ.get("DEEPTWIN_LIVE_MODEL", "claude-opus-5")
EVIDENCE = os.environ.get("DEEPTWIN_LIVE_EVIDENCE_PATH")

pytestmark = pytest.mark.skipif(not KEY, reason="live call needs DEEPTWIN_LIVE_ANTHROPIC_API_KEY (owner-authorized)")


def test_one_budget_capped_live_call_through_the_product_path(tmp_path):
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=1, max_output_tokens=64))
    with owner_app(tmp_path, executor) as subject:
        stored = claude(subject, "key", {"secret": KEY})
        assert stored.status_code == 200 and stored.json()["key_present"] is True
        catalog = claude(subject, "catalog")
        assert catalog.status_code == 200, catalog.json()
        assert MODEL in catalog.json()["catalog"]["model_ids"], "the chosen model is not in the live catalog"
        chosen = claude(subject, "model-choice", {"model_id": MODEL})
        assert chosen.status_code == 200, chosen.json()
        _body, started = start(subject, live_graph(subject, chosen.json()["model_choice_ref"]), real_work(subject))
        assert started.status_code == 201, started.json()
        receipt = started.json()
        writer = dict(receipt["outcome"]["execution_ids"])["writer"]
        output = subject.domain.get(EntityRef.from_dict(dict(receipt["outcome"]["result_refs"])[writer]))
        content = output.body["content"]
        assert content["schema_version"] == OUTPUT_SCHEMA and content["output"]["state"] == "completed"
        usage = content["output"]["usage"]
        assert usage["output_tokens"] <= 64
        listed = subject.client.get(receipt["links"]["self"] + "/artifacts", headers=headers(subject.profile)).json()
        draft = next(item for item in listed["artifacts"] if item["role"] == "draft")
        text = subject.client.get(receipt["links"]["self"] + f"/artifacts/{draft['artifact_id']}/content",
                                  headers=headers(subject.profile)).content.decode("utf-8")
        assert text.strip()
        observed = {"model": MODEL, "observed_model": content["output"]["observed_model"],
                    "provider_message_id": content["output"]["provider_message_id"],
                    "stop_reason": content["output"]["stop_reason"], "usage": usage,
                    "output_chars": len(text), "output_excerpt": text[:200]}
        if EVIDENCE:
            with open(EVIDENCE, "w", encoding="utf-8") as handle:
                json.dump(observed, handle, ensure_ascii=False, indent=2)
        assert KEY not in json.dumps(observed)
