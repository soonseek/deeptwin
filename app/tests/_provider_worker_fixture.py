"""Finite synthetic bytes and real temporary image files; no admission fixtures."""

import json
import os
from hashlib import sha256
from pathlib import Path
import pytest
import threading
from uuid import uuid4

PROFILE = "claude-text-transform-v1"
MODEL = "fixture-model"
ROLES = ("config", "request", "result", "error")
WORKER = b"synthetic measured image closure, not native qualification"


def encoded(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def schema_bytes():
    root = (
        Path(__file__).resolve().parents[2]
        / "schemas/v1/extensions/ports/provider-port-v1"
    )
    return tuple((root / (role + ".schema.json")).read_bytes() for role in ROLES)


def identity_mapping():
    return {
        "schema_version": "extension-build-identity-v2",
        "extension_id": "private-claude",
        "extension_version": "1.0.0",
        "platform": "linux/amd64",
        "port_contract_version": "provider-port-v1",
        "worker_profile": PROFILE,
        "inputs": {
            "schema_version": "extension-build-inputs-v1",
            **{
                name: {"sha256": "a" * 64, "size_bytes": 1}
                for name in ("source_bundle", "build_recipe", "dependency_input_set")
            },
        },
        "entrypoint": {"sha256": sha256(WORKER).hexdigest(), "size_bytes": len(WORKER)},
        "port_schemas": [
            {"role": role, "sha256": sha256(raw).hexdigest(), "size_bytes": len(raw)}
            for role, raw in zip(ROLES, schema_bytes(), strict=True)
        ],
    }


def text_plan(raw=b"hello"):
    return {
        "profile": PROFILE,
        "model_id": MODEL,
        "max_output_tokens": 32,
        "messages": [{"role": "user", "input_ordinals": [0]}],
        "inputs": [{"size": len(raw), "sha256": sha256(raw).hexdigest()}],
    }


def event(kind, **value):
    return (
        b"event: "
        + kind.encode()
        + b"\ndata: "
        + encoded({"type": kind, **value})
        + b"\n\n"
    )


def text_events(text="answer", model=MODEL, kind="text", stop="end_turn", usage=None):
    initial = {"input_tokens": 3, "output_tokens": 0}
    if usage is not None:
        initial.update(usage)
    block = {"type": kind}
    if kind == "text":
        block["text"] = ""
    result = [
        event(
            "message_start",
            message={
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "usage": initial,
            },
        ),
        event("content_block_start", index=0, content_block=block),
    ]
    if kind == "text":
        result.append(
            event(
                "content_block_delta",
                index=0,
                delta={"type": "text_delta", "text": text},
            )
        )
    result += [
        event("content_block_stop", index=0),
        event("message_delta", delta={"stop_reason": stop}, usage={"output_tokens": 4}),
        event("message_stop"),
    ]
    return result


def model_record(name="one", **fields):
    return {
        "type": "model",
        "id": name,
        "display_name": "Fixture",
        "created_at": "2026-01-01T00:00:00Z",
        **fields,
    }


def page(models=None, more=False):
    models = [model_record()] if models is None else models
    return encoded(
        {
            "data": models,
            "has_more": more,
            "first_id": models[0]["id"] if models else None,
            "last_id": models[-1]["id"] if models else None,
        }
    )


@pytest.fixture
def provider_tree(tmp_path_factory, monkeypatch):
    from app.deployment import mounts
    from app.workers import provider_metadata as pm

    root = tmp_path_factory.mktemp("provider-image") / "root"
    prefix = root / "opt/deeptwin-extension"
    paths = [
        (prefix / "bin/worker", WORKER, 0o555),
        (
            prefix / "identity/build-identity-v2.json",
            encoded(identity_mapping()),
            0o444,
        ),
    ]
    paths.extend(
        (prefix / f"ports/provider-port-v1/{role}.schema.json", raw, 0o444)
        for role, raw in zip(ROLES, schema_bytes(), strict=True)
    )
    for path, raw, mode in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(mode)
    for path in (
        root,
        root / "opt",
        prefix,
        prefix / "bin",
        prefix / "identity",
        prefix / "ports",
        prefix / "ports/provider-port-v1",
    ):
        path.chmod(0o755)
    info = root.stat()
    table = mounts.parse_mountinfo(
        f"1 1 {os.major(info.st_dev)}:{os.minor(info.st_dev)} / {root} ro - tmpfs tmpfs rw\n".encode()
    )
    monkeypatch.setattr(pm, "EXTENSION_ROOT", root)
    monkeypatch.setattr(pm, "EXTENSION_PREFIX", prefix)
    monkeypatch.setattr(pm, "_expected_owner", lambda: (os.getuid(), os.getgid()))
    monkeypatch.setattr(pm, "_native_platform", lambda: "linux/amd64")
    monkeypatch.setattr(pm, "_credentials", lambda: (22001, 22001, 22001, 22001))
    monkeypatch.setattr(pm, "_read_mountinfo", lambda: table)
    return {
        "root": root,
        "prefix": prefix,
        "worker": paths[0][0],
        "identity": paths[1][0],
        "schemas": tuple(p for p, _, _ in paths[2:]),
    }


def blob(raw, media="application/json"):
    return {
        "batch_id": str(uuid4()),
        "size": len(raw),
        "sha256": sha256(raw).hexdigest(),
        "media_type": media,
    }


class Requester:
    """Test-owned requester; real ExtensionConnection and artifact framing."""

    def __init__(self, root, spec):
        from app.workers import broker, listener

        self.deadline = broker.Deadline.after_ms(5000)
        self.connection = listener._connect_extension_authenticated(
            root,
            spec,
            requester_boot_id="test-control-" + "c" * 20,
            deadline=self.deadline,
        )
        self.seen = set()
        self.payload_bytes = 0

    def write(self, value, correlation=None, message_id=None):
        message_id = message_id or str(uuid4())
        raw = encoded(value)
        self.connection.write(
            message_id=message_id,
            correlation_id=correlation,
            message_type="extension-request-v1",
            payload=raw,
            deadline=self.deadline,
        )
        self.seen.add(message_id)
        return message_id

    def read(self, correlation):
        from app.workers.provider_messages import parse_control

        frame = self.connection.read(deadline=self.deadline)
        assert frame.envelope.message_type == "extension-result-v1"
        assert frame.envelope.correlation_id == correlation
        assert frame.envelope.message_id not in self.seen
        self.seen.add(frame.envelope.message_id)
        return frame.envelope.message_id, parse_control(frame.payload)

    def stream(self, announcing, descriptors, raws=None):
        from app.workers.artifact_stream import (
            ArtifactDescriptor,
            BytesSink,
            BytesSource,
            receive_batch,
            send_batch,
        )
        from app.workers.artifact_stream_transport import ConnectionStreamTransport

        entries = [
            ArtifactDescriptor(
                batch_id=item["batch_id"],
                request_id=announcing,
                ordinal=n,
                count=len(descriptors),
                media_type=item["media_type"],
                declared_size=item["size"],
                sha256=item["sha256"],
            )
            for n, item in enumerate(descriptors)
        ]
        transport = ConnectionStreamTransport(
            self.connection,
            message_type="extension-artifact-v1",
            correlation_id=announcing,
            deadline=self.deadline,
        )
        if raws is None:
            sinks = [BytesSink() for _ in entries]
            receive_batch(transport, entries, sinks)
            return [sink.value for sink in sinks]
        send_batch(transport, entries, [BytesSource(raw) for raw in raws])

    def start(self, operation="text", raw=b"hello"):
        self.operation = operation
        self.dialogue = str(uuid4())
        self.plan = (
            text_plan(raw)
            if operation == "text"
            else {"profile": PROFILE, "limit": 1000}
        )
        plan_raw = encoded(self.plan)
        description = blob(plan_raw)
        self.start_id = self.write(
            {
                "schema": "provider-transform-start-v1",
                "dialogue_id": self.dialogue,
                "operation": operation,
                "remaining_ms": 5000,
                "plan": description,
            }
        )
        assert self.read(self.start_id)[1]["phase"] == "plan"
        self.stream(self.start_id, [description], [plan_raw])
        assert self.read(self.start_id)[1]["phase"] == "inputs"
        batch = str(uuid4()) if operation == "text" else None
        inputs_id = self.write(
            {
                "schema": "provider-transform-inputs-v1",
                "dialogue_id": self.dialogue,
                "batch_id": batch,
            },
            self.start_id,
        )
        if batch is not None:
            self.stream(
                inputs_id,
                [
                    {
                        "batch_id": batch,
                        **self.plan["inputs"][0],
                        "media_type": "text/plain",
                    }
                ],
                [raw],
            )

    def projection(self):
        message_id, value = self.read(self.start_id)
        assert value["schema"] == "provider-transform-projection-v1"
        assert value["dialogue_id"] == self.dialogue
        raw = (
            None
            if value["body"] is None
            else self.stream(message_id, [value["body"]])[0]
        )
        return value, raw

    def response(self, raw=None, *, step=1, status="supplied"):
        description = (
            blob(
                raw,
                "text/event-stream" if self.operation == "text" else "application/json",
            )
            if raw is not None
            else None
        )
        mid = self.write(
            {
                "schema": "provider-transform-response-v1",
                "dialogue_id": self.dialogue,
                "step": step,
                "status": status,
                "body": description,
            },
            self.start_id,
        )
        if description is not None:
            self.stream(mid, [description], [raw])

    def final(self):
        from app.workers.provider_messages import parse_result

        mid, value = self.read(self.start_id)
        assert value["schema"] == "provider-transform-final-v1"
        assert value["dialogue_id"] == self.dialogue
        result = parse_result(self.stream(mid, [value["result"]])[0])
        assert result["input_digest"] == sha256(encoded(self.plan)).hexdigest()
        return result

    def close(self):
        self.connection.close()


def serving(service, side):
    from app.workers.broker import Deadline

    box = {}

    def run():
        side["worker_ident"] = threading.get_ident()
        try:
            box["served"] = service.serve_one(Deadline.after_ms(5000))
        except BaseException as error:
            box["error"] = error

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box
