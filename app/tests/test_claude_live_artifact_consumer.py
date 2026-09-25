"""T049 — the ONE owner-authorized LIVE Claude run where a model role consumes a
produced artifact, through the product's `ClaudeRunExecutor`.

Runs only when the operator provides `DEEPTWIN_LIVE_ANTHROPIC_API_KEY` (never in the
ordinary suite: the file name carries `_live_`). The owner authorized a hard cap of
USD 2.00 for this step. It makes:
- one catalog read (`GET /v1/models`, free);
- one Messages call: `LiveLimits(max_model_calls=1, max_output_tokens=200)`, low effort,
  no retry (the adapter's SDK retries are 0 and the executor never repeats a sent call),
  no fallback (the model is the owner's one catalog-listed choice).
The model is `DEEPTWIN_LIVE_MODEL` if the operator names one, else the first model the
live catalog lists; its identifier comes from the provider, never from this file.

Before the call the worst-case spend is bounded from the exact prompt size and the
output cap at a deliberately high ceiling rate, and the test refuses to send if that
bound exceeds the cap. The key goes in through the owner's connection route (server
memory only) and is never printed, stored or asserted on. Non-secret evidence goes to
`DEEPTWIN_LIVE_EVIDENCE_PATH` when set.
"""

import json
import os

import pytest

from app.domain.refs import EntityRef
from app.services.claude_run_executor import OUTPUT_SCHEMA, ClaudeRunExecutor, LiveLimits
from app.tests.support.runtime_e2e import TABLE_HANDLER, TABLE_ROWS, table_producer
from app.tests.test_claude_artifact_consumer import consumer_graph
from app.tests.test_claude_live_path import claude, real_work, start
from app.tests.test_runs_api import owner_app
from app.tests.test_web_owner_integration import headers

KEY = os.environ.get("DEEPTWIN_LIVE_ANTHROPIC_API_KEY")
MODEL = os.environ.get("DEEPTWIN_LIVE_MODEL")
EVIDENCE = os.environ.get("DEEPTWIN_LIVE_EVIDENCE_PATH")
CAP_USD = 2.00
MAX_OUTPUT_TOKENS = 200
# a ceiling above any listed per-token price, so the bound is never an underestimate
CEILING_INPUT_USD_PER_MTOK = 30.0
CEILING_OUTPUT_USD_PER_MTOK = 150.0

pytestmark = pytest.mark.skipif(not KEY, reason="live call needs DEEPTWIN_LIVE_ANTHROPIC_API_KEY (owner-authorized)")


def test_one_live_model_role_consumes_the_produced_table(tmp_path):
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=1, max_output_tokens=MAX_OUTPUT_TOKENS),
                                 producers={TABLE_HANDLER: table_producer})
    with owner_app(tmp_path, executor) as subject:
        stored = claude(subject, "key", {"secret": KEY})
        assert stored.status_code == 200 and stored.json()["key_present"] is True
        catalog = claude(subject, "catalog")
        assert catalog.status_code == 200, catalog.json()
        listed = catalog.json()["catalog"]["model_ids"]
        model = MODEL or listed[0]
        assert model in listed, "the chosen model is not in the live catalog"
        chosen = claude(subject, "model-choice", {"model_id": model})
        assert chosen.status_code == 200, chosen.json()
        # the spend bound before anything is sent: the table, the system text, the cap
        table_text = "\r\n".join(",".join(row) for row in TABLE_ROWS) + "\r\n"
        prompt_chars = len(table_text) + 600  # the executor's system instruction and role, generously
        bound = (prompt_chars * CEILING_INPUT_USD_PER_MTOK + MAX_OUTPUT_TOKENS * CEILING_OUTPUT_USD_PER_MTOK) / 1e6
        assert bound <= CAP_USD, bound  # one character is at least one token here: an overestimate
        _body, started = start(subject, consumer_graph(subject, chosen.json()["model_choice_ref"]),
                               real_work(subject, "표를 읽고 한 줄로 답해 주세요."))
        receipt = started.json()
        writer = dict(receipt.get("outcome", {}).get("execution_ids", [])).get("writer")
        observed = {"http_status": started.status_code, "phase": receipt.get("phase"), "chosen_model": model,
                    "spend_bound_usd": round(bound, 6)}
        if writer is not None:
            output = subject.domain.get(EntityRef.from_dict(dict(receipt["outcome"]["result_refs"])[writer]))
            content = output.body["content"]
            listed_artifacts = subject.client.get(receipt["links"]["self"] + "/artifacts",
                                                  headers=headers(subject.profile)).json()["artifacts"]
            table = next(item for item in listed_artifacts if item["role"] == "table")
            draft = next(item for item in listed_artifacts if item["role"] == "draft")
            text = subject.client.get(receipt["links"]["self"] + f"/artifacts/{draft['artifact_id']}/content",
                                      headers=headers(subject.profile)).content.decode("utf-8")
            observed.update({
                "schema": content["schema_version"], "state": content["output"]["state"],
                "observed_model": content["output"]["observed_model"],
                "provider_message_id": content["output"]["provider_message_id"],
                "request_id": content["output"]["request_id"], "stop_reason": content["output"]["stop_reason"],
                "usage": content["output"]["usage"], "table_sha256": table["sha256"],
                "output_descends_from_table": table["result_ref"] in output.body["parent_refs"],
                "output_chars": len(text), "output_excerpt": text[:300]})
        if EVIDENCE:
            with open(EVIDENCE, "w", encoding="utf-8") as handle:
                json.dump(observed, handle, ensure_ascii=False, indent=2)
        assert KEY not in json.dumps(observed)
        assert started.status_code == 201, observed
        assert observed["schema"] == OUTPUT_SCHEMA and observed["state"] == "completed", observed
        assert observed["output_descends_from_table"] is True
        assert observed["usage"]["output_tokens"] <= MAX_OUTPUT_TOKENS
