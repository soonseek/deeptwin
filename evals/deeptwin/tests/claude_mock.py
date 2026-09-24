"""Offline Claude API mock for Q01 rig/judge/calibration tests (no network).

Serves ``/v1/models`` and streamed ``/v1/messages`` through ``httpx2.MockTransport``
with the helpers of ``app/tests/test_claude_api.py``. Critic requests are answered
by a caller ``(system, user) -> str`` (e.g. ``q01_support.ScriptedCritic``); judge
requests (recognized by the judge system prompt) by a caller ``(payload) -> str``.
"""

from __future__ import annotations

import json

from app.tests.test_claude_api import (
    Spy,
    httpx2,
    message_delta,
    message_start,
    model,
    model_page,
    response,
    sse_event,
)
from evals.deeptwin.verifiers.claude_judge import SYSTEM_PROMPT as JUDGE_SYSTEM

PLAN_MODEL = "claude-opus-5"
SECRET = "sk-ant-api03-q01-offline-test-secret-never-real"
EFFORTS = {"supported": True, "low": {"supported": True}, "medium": {"supported": True},
           "high": {"supported": True}, "xhigh": {"supported": False}, "max": {"supported": False}}


def text_stream(text, *, model_id=PLAN_MODEL, message_id="msg_q01_1", input_tokens=7, output_tokens=5,
                reason="end_turn", thinking=None):
    events = [message_start(model_id=model_id, message_id=message_id, input_tokens=input_tokens,
                            output_tokens=1)]
    index = 0
    if thinking is not None:
        events += [
            ("content_block_start", {"type": "content_block_start", "index": 0,
                                     "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "thinking_delta", "thinking": thinking}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "signature_delta", "signature": "sig-opaque"}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ]
        index = 1
    events += [
        ("content_block_start", {"type": "content_block_start", "index": index,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": index,
                                 "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": index}),
        message_delta(reason, output_tokens=output_tokens),
        ("message_stop", {"type": "message_stop"}),
    ]
    return b"".join(sse_event(name, payload) for name, payload in events)


def default_judge(payload):
    return json.dumps({"verdict": "supported", "reason": "Offline mock judgement."})


class MockClaude:
    """Mock API: ``critic(system, user) -> str``, ``judge(payload) -> str``.

    ``usage(kind, system, user) -> (input_tokens, output_tokens)`` controls the
    reported usage; the default reports a small, byte-consistent usage.
    """

    def __init__(self, critic, *, judge=default_judge, usage=None, models=None, message_status=200,
                 stop_reason="end_turn", thinking=None):
        self.critic, self.judge = critic, judge
        self.usage = usage or (lambda kind, system, user: (len((system + user).encode()) // 4, 50))
        self.models = models or [model(PLAN_MODEL, capabilities={"effort": EFFORTS})]
        self.message_status, self.stop_reason, self.thinking = message_status, stop_reason, thinking
        self.bodies: list[dict] = []
        self.count = 0
        self.spy = Spy(self._respond)
        self.transport = httpx2.MockTransport(self.spy)

    def _respond(self, request, body):
        if request.url.path == "/v1/models":
            return response(request, payload=model_page(self.models))
        if request.url.path != "/v1/messages":
            raise AssertionError(f"unexpected endpoint {request.url.path}")
        payload = json.loads(body)
        self.bodies.append(payload)
        self.count += 1
        if self.message_status != 200:
            return response(request, status=self.message_status,
                            payload={"type": "error", "error": {"type": "api_error", "message": "mock"}})
        system, user = payload["system"], payload["messages"][0]["content"]
        kind = "judge" if system == JUDGE_SYSTEM else "critic"
        text = self.judge(json.loads(user)) if kind == "judge" else self.critic(system, user)
        input_tokens, output_tokens = self.usage(kind, system, user)
        stream = text_stream(text, model_id=payload["model"], message_id=f"msg_q01_{self.count}",
                             input_tokens=input_tokens, output_tokens=output_tokens, reason=self.stop_reason,
                             thinking=self.thinking)
        return response(request, body=stream, headers={"content-type": "text/event-stream"})

    def requests(self, kind=None):
        if kind is None:
            return list(self.bodies)
        return [b for b in self.bodies if (b["system"] == JUDGE_SYSTEM) == (kind == "judge")]
