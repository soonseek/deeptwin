"""Credential-free/network-free semantic worker engine for all five operations."""

from __future__ import annotations

from hashlib import sha256
import json
from uuid import uuid4

from ..domain.refs import EntityRef, canonical_json
from . import broker
from .artifact_stream import (ArtifactDescriptor, BytesSink, BytesSource, StreamLimits,
                              StreamCancelled, receive_batch, send_batch)
from .artifact_stream_transport import ConnectionStreamTransport
from .credential_channel import decode_op, encode_op
from ..extensions.provider_semantic_contracts import (ProviderSemanticError,
                                                       validate_canonical_port_shape)
from .provider_port_messages import ProviderObservation, ProviderProposal, request_digest, validate_request
from .provider_semantic_codec import CatalogTraversal, advance_catalog, encode_text_body, normalize_text, parse_model_page
from .semantic_connection import _owned_connection, _raw_connection

_REQUEST, _RESULT, _ARTIFACT = "extension-request-v1", "extension-result-v1", "extension-artifact-v1"
_STREAM_LIMITS = StreamLimits(max_artifact_bytes=1_048_576,
                              max_total_bytes=4 * 1_048_576, max_chunk_bytes=16_384)


def _control(payload):
    if type(payload) is not bytes or len(payload) > 16_384:
        raise ProviderSemanticError("semantic application control exceeds 16KiB")
    return decode_op(payload)


def _sequence(value, expected):
    return type(value) is int and value == expected


def _begin_authority(operation_ref, config):
    try:
        operation = EntityRef.from_dict(operation_ref)
    except (TypeError, ValueError):
        raise ProviderSemanticError("begin operation ref is not exact") from None
    if operation.as_dict() != operation_ref or operation.kind != "validation_report":
        raise ProviderSemanticError("begin operation ref is not exact")
    config_fields = {"schema_id", "schema_version", "port_contract_version", "extension_id",
        "installation_digest", "qualification_ref", "binding_revision_ref",
        "binding_slot_key", "binding_slot_key_digest", "extension_config", "grant_refs",
        "credential_handle_refs", "resource_limits", "port_config"}
    if type(config) is not dict or set(config) != config_fields:
        raise ProviderSemanticError("begin config projection is not closed")
    validate_canonical_port_shape("config", config)
    return operation


class SemanticFrameRouter:
    """Single-reader router for one authenticated worker dialogue wait boundary."""
    __slots__ = ("_service", "_connection", "_sock", "_codec", "_deadline", "_broker_id",
                 "_dialogue_id", "_operation_ref", "_core_seq", "_worker_seq")

    def __init__(self, service, connection, broker_id, dialogue_id, operation_ref,
                 *, core_seq=1, worker_seq=1):
        if (type(service) is not ProviderPortService
                or type(connection.deadline) is not broker.Deadline
                or type(dialogue_id) is not str):
            raise ProviderSemanticError("invalid semantic frame router")
        self._service, self._connection = service, connection
        self._sock = getattr(connection, "raw_socket", None)
        self._codec = getattr(connection, "raw_codec", None)
        self._deadline, self._broker_id, self._dialogue_id = (
            connection.deadline, broker_id, dialogue_id
        )
        self._operation_ref, self._core_seq, self._worker_seq = operation_ref, core_seq, worker_seq

    def _route(self, frame, *, allow_observation):
        if (frame.envelope.message_type != _REQUEST
                or frame.envelope.correlation_id != self._broker_id):
            raise ProviderSemanticError("dialogue frame is not bound")
        value = _control(frame.payload)
        if type(value) is not dict:
            raise ProviderSemanticError("dialogue message is malformed")
        common = (value.get("dialogue_id") == self._dialogue_id
                  and _sequence(value.get("seq"), self._core_seq)
                  and value.get("operation_ref") == self._operation_ref)
        if value.get("schema") == "provider-semantic-observation-v1":
            if (not allow_observation or not common or set(value) != {"schema", "dialogue_id",
                    "seq", "operation_ref", "request_sha256", "exchange_id", "status",
                    "http_status", "body_descriptor"}):
                raise ProviderSemanticError("observe control is not closed")
            self._core_seq += 1
            return frame, value
        if (value.get("schema") != "provider-semantic-control-v1"
                or not common or set(value) != {"schema", "dialogue_id", "seq",
                    "operation_ref", "request", "query_state"}):
            raise ProviderSemanticError("wait frame is neither observation nor control")
        self._core_seq += 1
        request = value["request"]
        if request.get("operation") not in {"status", "cancel"}:
            raise ProviderSemanticError("only status/cancel may enter an active dialogue")
        result = self._service.execute(request, query_state=value["query_state"])
        observation = ({"operation": "status",
            "observed_state": result["output"]["observed_state"],
            "terminal_result_ref": result["output"]["terminal_result_ref"]}
            if request["operation"] == "status" else
            {"operation": "cancel", "cancel_state": result["output"]["cancel_state"]})
        self._connection.write(message_id=str(uuid4()),
            correlation_id=self._broker_id, message_type=_RESULT,
            payload=encode_op({"schema": "provider-semantic-control-result-v1",
                "dialogue_id": self._dialogue_id, "seq": self._worker_seq,
                "operation_ref": self._operation_ref, "request_id": request["request_id"],
                "observation": observation}), deadline=self._deadline)
        self._worker_seq += 1
        return None if (request["operation"] == "cancel"
            and observation["cancel_state"] == "accepted") else False

    def next_observation(self):
        while True:
            routed = self._route(self._connection.read(),
                                 allow_observation=True)
            if routed is None or type(routed) is tuple:
                return routed

    def next_artifact(self):
        while True:
            frame = self._connection.read()
            if (frame.envelope.message_type == _ARTIFACT
                    and frame.envelope.correlation_id == self._broker_id):
                return frame.payload
            if self._route(frame, allow_observation=False) is None:
                raise StreamCancelled("semantic dialogue was cancelled during artifact transfer")

    def take_worker_seq(self):
        value = self._worker_seq
        self._worker_seq += 1
        return value


class _WorkerServiceStreamTransport:
    """Artifact adapter whose sole reader routes in-dialogue controls."""
    def __init__(self, router):
        self._router = router

    def send(self, payload):
        router = self._router
        router._connection.write(message_id=str(uuid4()),
            correlation_id=router._broker_id, message_type=_ARTIFACT,
            payload=payload, deadline=router._deadline)

    def receive(self):
        return self._router.next_artifact()


class ProviderPortService:
    @staticmethod
    def _descriptors(values, request_id):
        if type(values) is not list or len(values) > 4:
            raise ProviderSemanticError("artifact descriptors are out of bounds")
        result = []
        for index, value in enumerate(values):
            expected = {"batch_id", "request_id", "ordinal", "count", "media_type",
                        "declared_size", "sha256"}
            if (type(value) is not dict or set(value) != expected
                    or value["request_id"] != request_id or value["ordinal"] != index
                    or value["count"] != len(values)):
                raise ProviderSemanticError("artifact descriptor is not closed")
            result.append(ArtifactDescriptor(**value))
        return result

    @staticmethod
    def _description(raw, media_type, request_id, ordinal=0, count=1):
        return {"batch_id": str(uuid4()), "request_id": request_id, "ordinal": ordinal,
                "count": count, "declared_size": len(raw),
                "sha256": sha256(raw).hexdigest(), "media_type": media_type}

    def begin(self, request, *, frozen_content=None, input_bytes=(), traversal=None):
        validate_request(request)
        operation = request["operation"]
        if operation == "catalog":
            state = CatalogTraversal() if traversal is None else traversal
            after = state.pages[-1].last_id if state.pages else None
            return ProviderProposal(request["request_id"], operation, request_digest(request),
                                    "models", after, None, state)
        if operation == "model_step":
            fields = {"frozen_turn_ref", "model_id", "effort", "requested_modalities",
                      "tool_definition_refs", "response_schema_ref"}
            value = request["input"]
            if (set(value) != fields or value["effort"] is not None
                    or value["requested_modalities"] != ["text"] or value["tool_definition_refs"] != []
                    or value["response_schema_ref"] is not None or frozen_content is None
                    or frozen_content.get("turn", {}).get("model_id") != value["model_id"]):
                raise ProviderSemanticError("unsupported semantic model step")
            body = encode_text_body(frozen_content, tuple(input_bytes))
            return ProviderProposal(request["request_id"], operation, request_digest(request),
                                    "messages", None, body)
        raise ProviderSemanticError("operation has no upstream proposal")

    def observe(self, proposal, *, status, raw):
        if type(proposal) is not ProviderProposal or type(status) is not int or not 200 <= status < 300:
            raise ProviderSemanticError("upstream observation is unusable")
        if proposal.operation == "catalog":
            state = advance_catalog(proposal.traversal, parse_model_page(raw))
            return ProviderObservation(proposal.request_id, "catalog", "complete" if state.complete else "page",
                                       state.complete, model_ids=state.model_ids, traversal=state)
        text = normalize_text(raw, __import__("json").loads(proposal.body)["model"])
        return ProviderObservation(proposal.request_id, "model_step", text.reason, True,
            text.observed_model, text.stop_reason, text.text_blocks, text.usage)

    def execute(self, request, *, query_state=None):
        validate_request(request)
        operation = request["operation"]
        if operation == "capabilities":
            if request["input"] != {}:
                raise ProviderSemanticError()
            output = {"modalities": ["text"], "tool_calling": False,
                      "usage_reporting": True, "cancellation": True}
        elif operation == "status":
            if type(query_state) is not dict or query_state.get("operation_ref") != request["input"].get("operation_ref"):
                raise ProviderSemanticError()
            output = {name: query_state[name] for name in ("observed_state", "observed_at", "terminal_result_ref")}
        elif operation == "cancel":
            if type(query_state) is not dict or query_state.get("operation_ref") != request["input"].get("operation_ref"):
                raise ProviderSemanticError()
            output = {"cancel_state": "already_terminal" if query_state["observed_state"] in
                      {"succeeded", "failed", "cancelled"} else
                      ("accepted" if query_state["observed_state"] in {"pending", "running"} else "not_cancellable"),
                      "observed_at": query_state["observed_at"]}
        else:
            raise ProviderSemanticError("operation requires upstream dialogue")
        return {"request_id": request["request_id"], "operation": operation,
                "terminal": "succeeded", "output": output, "artifacts": []}

    def serve_authenticated(self, sock, codec, *, deadline):
        """Serve one closed worker dialogue over existing extension frame/stream grammar."""
        try:
            return self._serve_authenticated(sock, codec, deadline=deadline)
        except broker.TransportClosed:
            # An unfinished dialogue is abandoned when its authenticated core peer closes.
            return None
        except StreamCancelled:
            return None

    def _serve_authenticated(self, sock, codec, *, deadline):
        if type(codec) is not broker.FrameCodec or type(deadline) is not broker.Deadline:
            raise ProviderSemanticError("authenticated worker transport required")
        connection = _raw_connection(sock, codec, deadline, owns=False)
        return self._serve_connection(connection)

    def serve_connection(self, connection, *, deadline):
        """Consume one exact extension owner for one semantic dialogue."""

        from . import listener

        if type(connection) is not listener.ExtensionConnection:
            raise ProviderSemanticError("exact owned extension connection required")
        adapter = None
        try:
            adapter = _owned_connection(connection, deadline)
        except BaseException:
            try:
                connection.close()
            except BaseException:  # noqa: BLE001, S110 - preserve guard primary
                pass
            raise
        primary = None
        try:
            try:
                return self._serve_connection(adapter)
            except (broker.TransportClosed, StreamCancelled) as error:
                primary = error
                return None
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                adapter.close()
            except BaseException:
                if primary is None:
                    raise

    def _serve_connection(self, connection):
        deadline = connection.deadline
        first = connection.read()
        if first.envelope.message_type != _REQUEST or first.envelope.correlation_id is not None:
            raise ProviderSemanticError("worker frame is not bound")
        value = _control(first.payload)
        begin_fields = {"schema", "dialogue_id", "seq", "operation_ref", "config", "request",
                        "frozen_descriptor", "input_descriptors", "query_state"}
        if (type(value) is not dict or set(value) != begin_fields
                or value.get("schema") != "provider-semantic-begin-v1"
                or not _sequence(value["seq"], 0)):
            raise ProviderSemanticError("begin control is not closed")
        request = validate_request(value["request"])
        request_id, dialogue_id = request["request_id"], value["dialogue_id"]
        _begin_authority(value["operation_ref"], value["config"])
        router = SemanticFrameRouter(self, connection, first.envelope.message_id,
            dialogue_id, value["operation_ref"], worker_seq=0)
        stream = _WorkerServiceStreamTransport(router)
        frozen_content = None
        if value["frozen_descriptor"] is not None:
            descriptor = self._descriptors([value["frozen_descriptor"]], request_id)
            frozen_sink = BytesSink()
            receive_batch(stream, descriptor, [frozen_sink], limits=_STREAM_LIMITS)
            if len(frozen_sink.value) > 16_384:
                raise ProviderSemanticError("frozen worker projection exceeds 16KiB")
            try:
                frozen_content = json.loads(frozen_sink.value.decode("utf-8"))
            except (UnicodeError, ValueError):
                raise ProviderSemanticError("frozen worker projection is invalid") from None
        descriptors = self._descriptors(value["input_descriptors"], request_id)
        sinks = [BytesSink() for _ in descriptors]
        if descriptors:
            receive_batch(stream, descriptors, sinks, limits=_STREAM_LIMITS)
        if request["operation"] in {"capabilities", "status", "cancel"}:
            result = self.execute(request, query_state=value["query_state"])
            output = result["output"]
            observation = ({"operation": "capabilities", "output": output}
                if request["operation"] == "capabilities" else
                {"operation": "status", "observed_state": output["observed_state"],
                 "terminal_result_ref": output["terminal_result_ref"]}
                if request["operation"] == "status" else
                {"operation": "cancel", "cancel_state": output["cancel_state"]})
            self._send_final(connection, first.envelope.message_id, dialogue_id,
                0, value["operation_ref"], request_digest(request), request_id, observation, ())
            return
        proposal = self.begin(request, frozen_content=frozen_content,
                              input_bytes=tuple(sink.value for sink in sinks))
        while True:
            body = proposal.body
            description = (None if body is None else
                           self._description(body, "application/json", request_id))
            proposal_id = str(uuid4())
            connection.write(message_id=proposal_id, correlation_id=first.envelope.message_id,
                message_type=_RESULT, payload=encode_op({"schema": "provider-semantic-proposal-v1",
                    "dialogue_id": dialogue_id, "seq": router.take_worker_seq(),
                    "operation_ref": value["operation_ref"],
                    "request_sha256": proposal.request_sha256, "endpoint": proposal.endpoint,
                    "after_id": proposal.after_id, "body_descriptor": description}), deadline=deadline)
            if description is not None:
                send_batch(stream, self._descriptors([description], request_id),
                    [BytesSource(body)], limits=_STREAM_LIMITS)
            routed = router.next_observation()
            if routed is None:
                return
            observed_frame, observed_value = routed
            if observed_value["request_sha256"] != proposal.request_sha256:
                raise ProviderSemanticError("upstream observation request changed")
            raw_sink = BytesSink()
            if observed_value["body_descriptor"] is not None:
                raw_descriptor = self._descriptors([observed_value["body_descriptor"]], request_id)
                receive_batch(stream, raw_descriptor, [raw_sink], limits=_STREAM_LIMITS)
                raw = raw_sink.value
            else:
                raw = b""
            http_status = observed_value["http_status"]
            observation = self.observe(proposal, status=http_status, raw=raw)
            if observation.operation == "catalog" and not observation.complete:
                proposal = self.begin(request, traversal=observation.traversal)
                continue
            descriptions = [self._description(block, "text/plain", request_id, index,
                                               len(observation.text_blocks))
                            for index, block in enumerate(observation.text_blocks)]
            if observation.operation == "model_step":
                final = {"operation": "model_step", "reason": observation.reason,
                    "observed_model": observation.observed_model,
                    "stop_reason": observation.stop_reason, "text_descriptors": descriptions,
                    "usage": observation.usage}
            else:
                final = {"operation": "catalog", "complete": observation.complete,
                    "page_sha256s": [page.raw_sha256 for page in observation.traversal.pages],
                    "model_ids_sha256": sha256(canonical_json(
                        list(observation.model_ids))).hexdigest(),
                    "model_count": len(observation.model_ids),
                    "reason": "complete" if observation.complete else "catalog_incomplete"}
            self._send_final(connection, first.envelope.message_id, dialogue_id,
                router.take_worker_seq(), value["operation_ref"], proposal.request_sha256,
                request_id, final,
                observation.text_blocks, stream=stream)
            return

    def _send_final(self, connection, broker_id, dialogue_id, seq, operation_ref,
                    request_sha256, request_id, observation, text_blocks, *, stream=None):
        value = {"schema": "provider-semantic-worker-observation-v1",
                 "request_sha256": request_sha256, **observation}
        raw = canonical_json(value)
        if len(raw) > 65_536:
            raise ProviderSemanticError("worker observation exceeds 64KiB")
        descriptor = self._description(raw, "application/json", request_id)
        connection.write(message_id=str(uuid4()), correlation_id=broker_id,
            message_type=_RESULT, payload=encode_op({"schema": "provider-semantic-final-v1",
                "dialogue_id": dialogue_id, "seq": seq, "operation_ref": operation_ref,
                "request_sha256": request_sha256, "observation_descriptor": descriptor}),
            deadline=connection.deadline)
        stream = (ConnectionStreamTransport(connection, message_type=_ARTIFACT,
            correlation_id=broker_id, deadline=connection.deadline)
            if stream is None else stream)
        send_batch(stream, self._descriptors([descriptor], request_id),
            [BytesSource(raw)], limits=_STREAM_LIMITS)
        if text_blocks:
            descriptions = observation["text_descriptors"]
            send_batch(stream, self._descriptors(descriptions, request_id),
                [BytesSource(block) for block in text_blocks], limits=_STREAM_LIMITS)
        connection.checkpoint()


__all__ = ["ProviderPortService", "SemanticFrameRouter"]
