"""Pure text proposals and inert observations of control-supplied upstream bytes."""

from __future__ import annotations
from dataclasses import dataclass, field
from hashlib import sha256
from ..adapters.claude_protocol import ProtocolError, SSEDecoder
from . import provider_messages as wire


class UnsupportedProfile(ValueError):
    def __init__(self):
        super().__init__("unsupported provider profile")


def prepare_text(plan, input_bytes) -> bytes:
    wire.validate_plan(plan, "text")
    wire.require(
        type(input_bytes) in (tuple, list) and len(input_bytes) == len(plan["inputs"])
    )
    texts = []
    for entry, raw in zip(plan["inputs"], input_bytes, strict=True):
        wire.require(
            type(raw) is bytes
            and len(raw) == entry["size"]
            and sha256(raw).hexdigest() == entry["sha256"]
        )
        try:
            texts.append(raw.decode("utf-8"))
        except UnicodeError:
            raise wire.ProviderMessageError() from None
    body = {
        "model": plan["model_id"],
        "max_tokens": plan["max_output_tokens"],
        "stream": True,
        "messages": [],
    }
    for message in plan["messages"]:
        parts = [texts[n] for n in message["input_ordinals"]]
        if message["role"] == "system":
            body["system"] = "".join(parts)
        else:
            body["messages"].append(
                {
                    "role": message["role"],
                    "content": [{"type": "text", "text": text} for text in parts],
                }
            )
    try:
        return wire.encode_body(body)
    except wire.ProviderMessageError:
        # The plan and exact UTF8 inputs were validated; only encoded capacity remains.
        raise UnsupportedProfile() from None


@dataclass(frozen=True, slots=True)
class TextObservation:
    state: str
    reason: str
    _bytes: bytes = field(repr=False)

    def as_dict(self):
        return wire.decode_body(self._bytes)


@dataclass(frozen=True, slots=True)
class CatalogObservation:
    state: str
    reason: str
    _bytes: bytes = field(repr=False)

    def as_dict(self):
        return wire.decode_body(self._bytes)


class TextResponseAccumulator:
    """A bounded structural FSM; rejected content is discarded on arrival."""

    def __init__(self, requested_model):
        self.requested_model = wire.identifier(requested_model)
        self.observed_model = None
        self.usage = dict.fromkeys(wire.USAGE_KEYS)
        self.stop_reason = None
        self.started = self.stopped = self.deltas = False
        self.invalid = self.provider_error = False
        self.flags = set()
        self.active = None
        self.blocks = []
        self.count = self.text_bytes = self.events = 0

    def _flag(self, name):
        self.flags.add(name)
        self.blocks.clear()

    def _metadata(self, value):
        if value.get("refusal") is not None:
            self._flag("refusal")
        details = value.get("stop_details")
        if details is not None:
            self._flag(
                "refusal"
                if type(details) is dict and details.get("type") == "refusal"
                else "unsupported"
            )

    def _usage(self, value, *, delta=False):
        wire.require(type(value) is dict)
        if delta:
            wire.number(value.get("output_tokens"))
        newer = self.usage.copy()
        for key in wire.USAGE_KEYS:
            number = value.get(key)
            if number is not None:
                wire.number(number)
                wire.require(newer[key] is None or number >= newer[key])
                newer[key] = number
        # Atomic: no observation changes until every counter has validated.
        self.usage = newer

    def _text(self, text, *, start=False):
        wire.require(type(text) is str)
        self.text_bytes += len(text.encode("utf-8"))
        wire.require(self.text_bytes <= 524288)
        if not self.flags:
            if start:
                self.blocks.append(text)
            else:
                self.blocks[-1] += text

    def accept(self, event):
        if self.invalid:
            return
        try:
            self.events += 1
            wire.require(
                self.events <= 10000 and type(event) is tuple and len(event) == 2
            )
            name, value = event
            wire.bounded_json(
                value, depth=16, items=16384, members=256, string=262144, floats=True
            )
            wire.require(type(value) is dict and value.get("type") == name)
            if name == "ping":
                wire.require(value == {"type": "ping"})
                return
            wire.require(not self.provider_error and not self.stopped)
            if name == "error":
                wire.require(
                    type(value.get("error")) is dict
                    and type(value["error"].get("type")) is str
                )
                self.provider_error = True
                self.blocks.clear()
                return
            if name == "message_start":
                wire.require(not self.started)
                message = value.get("message")
                wire.require(
                    type(message) is dict
                    and message.get("role") == "assistant"
                    and message.get("type") == "message"
                )
                wire.require(message.get("content") == [])
                observed = wire.identifier(message.get("model"))
                self._usage(message.get("usage", {}))
                self.started = True
                self.observed_model = observed
                if observed != self.requested_model:
                    self._flag("model_mismatch")
                self._metadata(message)
                return
            wire.require(self.started)
            if name == "content_block_start":
                wire.require(self.active is None and not self.deltas)
                wire.require(wire.number(value.get("index"), 0, 31) == self.count)
                block = value.get("content_block")
                wire.require(type(block) is dict)
                kind = block.get("type")
                wire.require(
                    kind
                    in (
                        "text",
                        "tool_use",
                        "server_tool_use",
                        "thinking",
                        "redacted_thinking",
                        "refusal",
                        "fallback",
                    )
                )
                self.active = (kind, self.count)
                self.count += 1
                self._metadata(block)
                if kind == "text":
                    self._text(block.get("text"), start=True)
                else:
                    self._flag(
                        {"refusal": "refusal", "fallback": "model_mismatch"}.get(
                            kind, "unsupported"
                        )
                    )
            elif name == "content_block_delta":
                wire.require(self.active is not None and not self.deltas)
                kind, index = self.active
                wire.require(wire.number(value.get("index"), 0, 31) == index)
                delta = value.get("delta")
                wire.require(type(delta) is dict)
                allowed = {
                    "text": {"text_delta": "text"},
                    "tool_use": {"input_json_delta": "partial_json"},
                    "server_tool_use": {"input_json_delta": "partial_json"},
                    "thinking": {
                        "thinking_delta": "thinking",
                        "signature_delta": "signature",
                    },
                }.get(kind, {})
                dtype = delta.get("type")
                wire.require(type(dtype) is str and dtype in allowed)
                text = delta.get(allowed[dtype])
                wire.require(type(text) is str)
                self._metadata(delta)
                if kind == "text":
                    self._text(text)
                # Rejected delta strings die here: no assembly/parsing/tool dispatch.
            elif name == "content_block_stop":
                wire.require(self.active is not None and not self.deltas)
                wire.require(wire.number(value.get("index"), 0, 31) == self.active[1])
                self.active = None
            elif name == "message_delta":
                wire.require(self.active is None)
                delta = value.get("delta")
                wire.require(type(delta) is dict)
                stop = delta.get("stop_reason")
                if stop is not None:
                    wire.require(
                        stop in wire.STOPS
                        and (self.stop_reason is None or self.stop_reason == stop)
                    )
                self._usage(value.get("usage"), delta=True)
                if stop is not None:
                    self.stop_reason = stop
                    if stop == "refusal":
                        self._flag("refusal")
                    elif stop in ("tool_use", "pause_turn", "stop_sequence"):
                        self._flag("unsupported")
                    elif stop != "end_turn":
                        self._flag("truncated")
                self._metadata(delta)
                self.deltas = True
            elif name == "message_stop":
                wire.require(
                    self.active is None and self.deltas and self.stop_reason is not None
                )
                self.stopped = True
            else:
                raise wire.ProviderMessageError()
        except (
            wire.ProviderMessageError,
            UnicodeError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
        ):
            self.fail()

    def fail(self):
        self.invalid = True
        self.blocks.clear()

    def finish(self):
        if self.invalid or not (self.stopped or self.provider_error):
            state, reason = "invalid_response", "protocol_error"
        elif self.provider_error:
            state, reason = "non_success", "provider_error"
        else:
            reason = next(
                (
                    name
                    for name in (
                        "refusal",
                        "model_mismatch",
                        "unsupported",
                        "truncated",
                    )
                    if name in self.flags
                ),
                "complete",
            )
            state = (
                "parsed_complete"
                if reason == "complete"
                else "unsupported_profile"
                if reason == "unsupported"
                else "non_success"
            )
        observation = {
            "requested_model": self.requested_model,
            "observed_model": self.observed_model,
            "text_blocks": self.blocks if state == "parsed_complete" else [],
            "stop_reason": self.stop_reason,
            "usage_observed": self.usage.copy(),
            "usage_complete": self.usage.copy()
            if (
                self.stopped
                and not self.invalid
                and not self.provider_error
                and all(x is not None for x in self.usage.values())
            )
            else None,
        }
        try:
            raw = wire.encode_body(observation)
        except wire.ProviderMessageError:
            observation["text_blocks"] = []
            state, reason = "unsupported_profile", "unsupported"
            raw = wire.encode_body(observation)
        return TextObservation(state, reason, raw)


def parse_text_response(requested_model, chunks):
    accumulator = TextResponseAccumulator(requested_model)
    decoder = SSEDecoder()
    try:
        for chunk in chunks:
            for event in decoder.feed(chunk):
                if event is not None:
                    accumulator.accept(event)
                if accumulator.invalid:
                    return accumulator.finish()
        for event in decoder.finish():
            if event is not None:
                accumulator.accept(event)
    except (ProtocolError, ValueError, UnicodeError):
        accumulator.fail()
    return accumulator.finish()


class CatalogAccumulator:
    def __init__(self):
        self.digests = []
        self.models = []
        self.ids = set()
        self.cursors = set()
        self.total = 0
        self.complete = self.invalid = False

    def accept_page(self, raw):
        if self.invalid:
            return None
        try:
            wire.require(not self.complete and len(self.digests) < 20)
            wire.require(type(raw) is bytes and 0 < len(raw) <= wire.MAX_BLOB)
            self.total += len(raw)
            wire.require(self.total <= 4 * wire.MAX_BLOB)
            self.digests.append(sha256(raw).hexdigest())
            page = wire._decode(
                raw,
                cap=wire.MAX_BLOB,
                canonical=False,
                depth=16,
                items=16384,
                members=256,
                string=65536,
                floats=True,
            )
            wire.require(
                type(page) is dict
                and all(k in page for k in ("data", "has_more", "first_id", "last_id"))
            )
            data = page["data"]
            wire.require(type(data) is list and type(page["has_more"]) is bool)
            wire.require(len(self.models) + len(data) <= 1000)
            additions = []
            seen = self.ids.copy()
            for entry in data:
                wire.require(type(entry) is dict and entry.get("type") == "model")
                name = wire.identifier(entry.get("id"))
                wire.require(name not in seen)
                seen.add(name)
                wire.require("display_name" in entry and "created_at" in entry)
                wire.validate_model_fields(entry)
                additions.append(
                    {
                        key: entry.get(key)
                        for key in (
                            "id",
                            "display_name",
                            "created_at",
                            "max_input_tokens",
                            "max_tokens",
                            "capabilities",
                        )
                    }
                )
            if not data:
                wire.require(
                    page["first_id"] is None
                    and page["last_id"] is None
                    and not page["has_more"]
                )
            else:
                wire.require(
                    page["first_id"] == additions[0]["id"]
                    and page["last_id"] == additions[-1]["id"]
                )
            if page["has_more"]:
                cursor = page["last_id"]
                wire.require(cursor not in self.cursors and len(self.digests) < 20)
                self.cursors.add(cursor)
            else:
                cursor = None
            self.models.extend(additions)
            self.ids = seen
            self.complete = not page["has_more"]
            # Include full result overhead in the final cap; a prefix is never selectable.
            wire.encode_result(self._result("0" * 64, complete=True))
            return cursor
        except (
            wire.ProviderMessageError,
            ValueError,
            TypeError,
            UnicodeError,
            KeyError,
        ):
            self.invalid = True
            self.complete = False
            self.models.clear()
            return None

    def _result(self, input_digest, *, complete):
        return {
            "schema": "provider-transform-result-v1",
            "operation": "catalog",
            "state": "parsed_complete" if complete else "invalid_response",
            "reason": "complete" if complete else "catalog_incomplete",
            "input_digest": input_digest,
            "observation": {
                "page_digests": self.digests.copy(),
                "complete": complete,
                "models": self.models if complete else [],
            },
        }

    def finish(self):
        complete = self.complete and not self.invalid
        result = self._result("0" * 64, complete=complete)
        return CatalogObservation(
            result["state"], result["reason"], wire.encode_body(result["observation"])
        )


def result_bytes(operation, input_digest, observation):
    result = {
        "schema": "provider-transform-result-v1",
        "operation": operation,
        "state": observation.state,
        "reason": observation.reason,
        "input_digest": input_digest,
        "observation": observation.as_dict(),
    }
    try:
        return wire.encode_result(result)
    except wire.ProviderMessageError:
        if operation == "text":
            result["state"], result["reason"] = "unsupported_profile", "unsupported"
            result["observation"]["text_blocks"] = []
        else:
            result["state"], result["reason"] = "invalid_response", "catalog_incomplete"
            result["observation"]["models"] = []
            result["observation"]["complete"] = False
        return wire.encode_result(result)


def unsuccessful(
    operation, reason, requested_model=None, *, state="non_success", prior=None
):
    if operation == "text":
        value = (
            TextResponseAccumulator(requested_model).finish().as_dict()
            if prior is None
            else prior.as_dict()
        )
        value["text_blocks"] = []
        return TextObservation(state, reason, wire.encode_body(value))
    value = (
        {"page_digests": [], "complete": False, "models": []}
        if prior is None
        else prior.as_dict()
    )
    value["complete"], value["models"] = False, []
    return CatalogObservation(state, reason, wire.encode_body(value))
