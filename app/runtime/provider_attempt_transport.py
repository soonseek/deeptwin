"""Actual NodeAttemptDispatcher callable for the conditional provider semantic path."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import threading
import time
from uuid import uuid4

from ..domain.refs import EntityRef, canonical_json
from ..domain.store import DomainStore
from ..extensions.provider_semantic_context import (ProviderSemanticAdmissionError,
                                                     ProviderSemanticAuthority,
                                                     ProviderSemanticContextLoader,
                                                     durable_binding, validate_bound_handle)
from ..extensions.provider_semantic_contracts import (canonical_provider_error,
                                                       canonical_provider_result)
from ..extensions.port_schema_generator import validate_port_payload
from ..extensions.port_contracts import PORT_SCHEMA_IDS
from ..extensions.provider_semantic_records import (
    admit_operation, load_cancel_intent, load_operation, load_terminal,
    seal_cancel_operation_and_intent, seal_effect, seal_output, seal_response,
    seal_catalog_traversal, seal_page, seal_terminal, seal_usage,
)
from ..workers.provider_port_client import ProviderPortClient
from ..workers.provider_port_messages import ProviderProposal
from ..workers.provider_send_client import ProviderSendClient
from ..workers.provider_send_messages import prepare_message
from ..workers.provider_semantic_codec import (CatalogTraversal, advance_catalog,
                                                encode_text_body, normalize_text,
                                                parse_model_page,
                                                ProviderSemanticError)
from ..workers import broker
from .budgets import BudgetBook
from .ledger import ConsumedDispatchWindow, DispatchPermit, RuntimeLedger
from .node_attempts import AttemptDispatchRequest, AttemptTransportResult, attempt_identity


class _NotSentPage:
    """The observation of a model page the requester knows was not sent."""

    phase = "not_sent"
    body = b""


class _CatalogResponseFailure(RuntimeError):
    """The gateway returned an unsuccessful HTTP/read observation."""


class ProviderAttemptTransport:
    output_bytes_bound = 524_288

    def __init__(self, *, domain_store, ledger, budget_book, context_loader,
                 worker_client, send_client, operation_controller=None):
        if (type(domain_store) is not DomainStore or type(ledger) is not RuntimeLedger
                or type(budget_book) is not BudgetBook
                or type(context_loader) is not ProviderSemanticContextLoader
                or type(worker_client) is not ProviderPortClient
                or type(send_client) is not ProviderSendClient):
            raise TypeError("exact provider attempt dependencies required")
        if (operation_controller is not None
                and type(operation_controller) is not ProviderSemanticOperationController):
            raise TypeError("exact semantic operation controller required")
        self._domain, self._ledger, self._book = domain_store, ledger, budget_book
        self._context_loader, self._worker, self._send = context_loader, worker_client, send_client
        self._controller = operation_controller

    @staticmethod
    def _stamp():
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    @staticmethod
    def _port_stamp():
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @staticmethod
    def _deadline_end(request, *ends):
        try:
            wall_remaining = (datetime.fromisoformat(
                request["deadline_at"].replace("Z", "+00:00"))
                - datetime.now(timezone.utc)).total_seconds()
        except (KeyError, AttributeError, ValueError):
            raise ValueError("semantic request deadline is invalid") from None
        end = min((time.monotonic() + wall_remaining, *ends))
        if end <= time.monotonic():
            raise TimeoutError("semantic operation deadline elapsed")
        return float(end)

    @staticmethod
    def _authenticated_session(value, *, protocol_id, channel_id, sender):
        if (type(value) is not tuple or len(value) != 8
                or value[0] != protocol_id or value[1] != channel_id
                or type(value[2]) is not str or len(value[2]) != 64
                or value[5] != sender or value[6] != "control"):
            raise ValueError("authenticated provider channel observation is invalid")
        return value

    @staticmethod
    def _retained_attempt_result(retained):
        result = retained.body["content"]["result"]
        terminal = result["terminal"]
        if terminal == "failed":
            code = result["error"]["code"]
            local = result.get("effect", {}).get("effect_state") == "none"
            return AttemptTransportResult(
                "denied" if code == "permission_denied" else "failed",
                retained.ref, "unknown", "not_observed" if local else "failed",
                "permission_denied" if code == "permission_denied" else "validation_failed",
                None)
        outcome, finality, remote, reason = {
            "succeeded": ("succeeded", "provisional", "succeeded", "provider_terminal"),
            "cancelled": ("cancelled", "unknown", "not_observed", "cancel_requested"),
            "unknown": ("outcome_unknown", "unknown", "outcome_unknown", "transport_unknown"),
        }[terminal]
        return AttemptTransportResult(outcome, retained.ref, finality, remote, reason, None)

    @staticmethod
    def _pending_owner_unknown():
        """Retained source-less ownership is uncertainty, never proof of no send."""
        return AttemptTransportResult("outcome_unknown", None, "unknown", "not_observed",
                                      "transport_unknown", None)

    def _historical_model_replay(self, request):
        operation_ref = self._context_loader.operation_ref
        retained = load_terminal(self._domain, operation_ref)
        if retained is None:
            return None
        operation = self._context_loader.authorize_historical_read()
        frozen = self._domain.get(EntityRef.from_dict(operation["frozen_ref"])).body["content"]
        turn = frozen["turn"]
        attempt = self._ledger.get_attempt(request.attempt_id)["spec"]
        if (operation["request"]["operation"] != "model_step"
                or frozen["execution_envelope_ref"] != request.envelope_ref.as_dict()
                or turn["execution_id"] != request.execution_id
                or turn["node_id"] != request.node_id
                or attempt["attempt_id"] != request.attempt_id
                or attempt["execution_id"] != request.execution_id
                or attempt["attempt_no"] != turn["attempt_index"] + 1
                or attempt["envelope_ref"] != request.envelope_ref.as_dict()):
            raise ValueError("historical semantic result differs from dispatcher attempt")
        return self._retained_attempt_result(retained)

    def _model_subject(self, permit, request, window):
        """No current-send eligibility or terminal writes before exact subject joins."""
        self._ledger.assert_consumed_dispatch_window(window, permit=permit)
        _config, operation = self._context_loader._operation_identity()
        if operation["request"]["operation"] != "model_step" or operation["frozen_ref"] is None:
            raise ValueError("model attempt lacks frozen semantic call")
        frozen = self._domain.get(EntityRef.from_dict(operation["frozen_ref"])).body["content"]
        turn = frozen["turn"]
        attempt = self._ledger.get_attempt(request.attempt_id)["spec"]
        run = self._ledger.get_run(request.run_id)["spec"]
        execution = self._ledger.get_execution(request.execution_id)["spec"]
        if (frozen["execution_envelope_ref"] != request.envelope_ref.as_dict()
                or turn["execution_id"] != request.execution_id
                or turn["node_id"] != request.node_id
                or attempt["attempt_id"] != request.attempt_id
                or attempt["execution_id"] != request.execution_id
                or attempt["attempt_no"] != turn["attempt_index"] + 1
                or attempt["envelope_ref"] != request.envelope_ref.as_dict()
                or attempt["profile_ref"] != turn["runtime_profile_ref"]
                or attempt["budget_policy_ref"] != turn["budget_ref"]
                or execution["execution_id"] != turn["execution_id"]
                or execution["run_id"] != request.run_id
                or execution["node_id"] != turn["node_id"]
                or run["work_revision_ref"] != turn["work_ref"]
                or run["environment_ref"] != turn["environment_ref"]
                or run["consent_ref"] != turn["consent_ref"]
                or run["budget_policy_ref"] != turn["budget_ref"]):
            raise ValueError("dispatcher attempt differs from frozen semantic authority")
        return operation

    def _model_preflight(self, permit, request, window):
        context = self._context_loader.load(now_utc=self._stamp())
        reservation_content = self._domain.get(context.reservation_ref).body["content"]
        with self._book._connection(immediate=True) as db:
            actual_reservation, actual_policy, _, _ = \
                self._book._assert_dispatched_in_transaction(
                    db, permit.reservation_id, permit.budget_session_id)
        if (actual_reservation.request_id != permit.reservation_id
                or actual_reservation.session_id != permit.budget_session_id
                or actual_reservation.api_microunits
                != reservation_content["reserved_microunits"]
                or actual_policy.currency != reservation_content["currency"]):
            raise ValueError("reviewed reservation differs from dispatched budget allocation")
        admitted, replay = admit_operation(self._domain, config_ref=context.config_ref,
            request=context.request, core_boot_id=self._domain.get(context.operation_ref).body[
                "content"]["core_boot_id"], reservation_ref=context.reservation_ref,
            semantic_key=context.request["idempotency_key"], created_at_utc=self._stamp())
        if admitted != context.operation_ref:
            raise ValueError("semantic admission resolved another operation")
        return context, None

    def _local_failure(self, started_at, *, code="integrity_failed",
                       message_class="integrity", retry_class="never"):
        operation_ref = self._context_loader._operation_ref
        request = self._domain.get(operation_ref).body["content"]["request"]
        stamp, completed_at = self._stamp(), self._port_stamp()
        error = canonical_provider_error(request, code=code,
            message_class=message_class, retry_class=retry_class)
        effect = {"effect_class": "external_irreversible", "effect_state": "none",
                  "effect_receipt_ref": None, "remote_outcome": "not_applicable"}
        result = canonical_provider_result(request, terminal="failed", started_at=started_at,
            completed_at=completed_at, error=error, effect=effect)
        terminal = seal_terminal(self._domain, operation_ref=operation_ref, result=result,
                                 response_ref=None, created_at_utc=stamp)
        outcome, reason = ({"permission_denied": ("denied", "permission_denied")}.get(
            code, ("failed", "validation_failed")))
        return AttemptTransportResult(outcome, terminal, "unknown", "not_observed", reason, None)

    @staticmethod
    def _failure_mapping(category):
        return {
            "permission_denied": ("permission_denied", "permission", "human_action_required"),
            "deadline_exceeded": ("deadline_exceeded", "timeout", "never"),
            "resource_exhausted": ("resource_exhausted", "capacity", "never"),
            "unsupported_capability": ("unsupported_capability", "unsupported", "never"),
            "integrity_failed": ("integrity_failed", "integrity", "never"),
            "dependency_unavailable": ("dependency_unavailable", "dependency",
                                       "human_action_required"),
            "internal_failure": ("internal_failure", "internal", "never"),
        }.get(category, ("internal_failure", "internal", "never"))

    def _missing_gateway_unknown(self, context, started_at):
        stamp = self._stamp()
        error = canonical_provider_error(context.request, code="external_effect_unknown",
            message_class="external_outcome", retry_class="never")
        result = canonical_provider_result(context.request, terminal="unknown",
            started_at=started_at, completed_at=None, error=error,
            effect={"effect_class": "external_irreversible", "effect_state": "unknown",
                    "effect_receipt_ref": None, "remote_outcome": "unknown"})
        terminal = seal_terminal(self._domain, operation_ref=context.operation_ref,
            result=result, response_ref=None, created_at_utc=stamp)
        if self._controller is not None:
            self._controller.finish(context.operation_ref, terminal)
        return AttemptTransportResult("outcome_unknown", terminal, "unknown",
                                      "outcome_unknown", "transport_unknown", None)

    def _cancelled(self, context, started_at, *, response_ref=None, after_possible_write=False):
        stamp, completed_at = self._stamp(), self._port_stamp()
        error = canonical_provider_error(context.request, code="cancelled",
            message_class="cancelled", retry_class="never",
            evidence_ref=None if response_ref is None else response_ref.as_dict())
        effect = {"effect_class": "external_irreversible",
                  "effect_state": "unknown" if after_possible_write else "none",
                  "effect_receipt_ref": None,
                  "remote_outcome": "unconfirmed" if after_possible_write else "not_applicable"}
        result = canonical_provider_result(context.request, terminal="cancelled",
            started_at=started_at, completed_at=completed_at, error=error, effect=effect)
        terminal = seal_terminal(self._domain, operation_ref=context.operation_ref, result=result,
                                 response_ref=response_ref, created_at_utc=stamp)
        if self._controller is not None:
            self._controller.finish(context.operation_ref, terminal)
        return AttemptTransportResult("cancelled", terminal, "unknown", "not_observed",
                                      "cancel_requested", None)

    def _safe_cancel(self, exchange_id, reason):
        try:
            return self._send.cancel(exchange_id, reason)
        except Exception:
            # Cancellation is cleanup after a deliberate local decision.  A failed
            # cleanup must not replace that already-classified terminal.
            return None

    def __call__(self, permit, request, window):
        try:
            return self._dispatch_model(permit, request, window)
        finally:
            self._worker.abandon()

    def _dispatch_model(self, permit, request, window):
        if type(permit) is not DispatchPermit or type(request) is not AttemptDispatchRequest \
                or type(window) is not ConsumedDispatchWindow:
            raise TypeError("exact dispatcher values required")
        replay = self._historical_model_replay(request)
        if replay is not None:
            return replay
        operation = self._model_subject(permit, request, window)
        if not self._context_loader.consume_owner_capability():
            self._context_loader.authorize_historical_read()
            return self._pending_owner_unknown()
        started_at = self._port_stamp()
        operation_request = operation["request"]
        try:
            deadline_end = self._deadline_end(operation_request,
                                              window.deadline_end_monotonic)
        except TimeoutError:
            return self._local_failure(started_at, code="deadline_exceeded",
                message_class="timeout", retry_class="never")
        try:
            context, replay_result = self._model_preflight(permit, request, window)
        except ProviderSemanticAdmissionError as exc:
            code, message, retry = self._failure_mapping(exc.failure_class)
            return self._local_failure(started_at, code=code,
                message_class=message, retry_class=retry)
        except (ValueError, TypeError):
            return self._local_failure(started_at)
        except Exception:
            return self._local_failure(started_at, code="internal_failure",
                message_class="internal", retry_class="never")
        if replay_result is not None:
            return replay_result
        cancel_event, exchange = threading.Event(), {"id": None}
        if self._controller is not None:
            def forward_cancel(reason):
                current = exchange["id"]
                if current is not None:
                    self._send.cancel(current, reason)
            self._controller.register_live(context.operation_ref, cancel_event=cancel_event,
                forward_cancel=forward_cancel, attempt_id=request.attempt_id,
                execution_id=request.execution_id, envelope_ref=request.envelope_ref)
        try:
            proposal = self._worker.begin(context.request,
                operation_ref=context.operation_ref.as_dict(), config=context.config,
                frozen_content=context.frozen_content, input_bytes=context.input_bytes,
                deadline_end_monotonic=deadline_end)
            worker_session = self._authenticated_session(
                self._worker.authenticated_session_observation,
                protocol_id="deeptwin-extension-worker-v1",
                channel_id="task47-semantic-worker", sender="semantic-worker")
            context = replace(context, worker_session_observation=worker_session)
            expected_body = encode_text_body(context.frozen_content, context.input_bytes)
            if (proposal.request_id != context.request["request_id"]
                    or proposal.operation != "model_step" or proposal.endpoint != "messages"
                    or proposal.after_id is not None or proposal.body != expected_body
                    or proposal.request_sha256 != sha256(canonical_json(context.request)).hexdigest()):
                raise ValueError("worker proposal differs from the frozen semantic request")
        except (TimeoutError, broker.DeadlineExceeded):
            return self._local_failure(started_at, code="deadline_exceeded",
                message_class="timeout", retry_class="never")
        except (ValueError, TypeError):
            return self._local_failure(started_at)
        except Exception:
            return self._local_failure(started_at, code="internal_failure",
                message_class="internal", retry_class="never")
        remaining = min(30_000, int(max(0.0, deadline_end - time.monotonic()) * 1000))
        if remaining < 1:
            return self._local_failure(started_at, code="deadline_exceeded",
                message_class="timeout", retry_class="never")
        try:
            prepared = prepare_message(operation_ref=context.operation_ref.as_dict(),
                request_id=context.request["request_id"],
                request_sha256=sha256(canonical_json(context.request)).hexdigest(),
                selected_handle_ref=context.connection["selected_handle_ref"],
                connection_pin=context.connection["connection_pin"],
                credential_metadata=context.connection["credential_metadata"],
                credential_record=context.connection["credential_record"], endpoint=proposal.endpoint,
                after_id=proposal.after_id, body=proposal.body or b"", remaining_ms=remaining,
                deadline_at=context.request["deadline_at"],
                reservation_ref=(None if context.reservation_ref is None else
                                 context.reservation_ref.as_dict()))
            ready = self._send.prepare(prepared, deadline_end_monotonic=deadline_end)
        except Exception as exc:
            if isinstance(exc, (TimeoutError, broker.DeadlineExceeded)):
                return self._local_failure(started_at, code="deadline_exceeded",
                    message_class="timeout", retry_class="never")
            return self._local_failure(started_at, code="internal_failure",
                message_class="internal", retry_class="never")
        try:
            gateway_session = self._authenticated_session(
                self._send.authenticated_session_observation,
                protocol_id="credential-gateway-v1", channel_id="task47-provider-send",
                sender="credential-gateway")
            if gateway_session[2] == context.worker_session_observation[2]:
                raise ValueError("worker and gateway authenticated sessions are not distinct")
        except (ValueError, TypeError):
            self._safe_cancel(ready["exchange_id"], "policy_revoked")
            return self._local_failure(started_at)
        context = replace(context, gateway_session_observation=gateway_session)
        exchange["id"] = ready["exchange_id"]
        if cancel_event.is_set():
            self._safe_cancel(ready["exchange_id"], "user_requested")
            return self._cancelled(context, started_at)
        try:
            self._ledger.assert_consumed_dispatch_window(window, permit=permit)
            refreshed = replace(self._context_loader.load(now_utc=self._stamp()),
                worker_session_observation=context.worker_session_observation,
                gateway_session_observation=context.gateway_session_observation)
        except ProviderSemanticAdmissionError as exc:
            self._safe_cancel(ready["exchange_id"], "policy_revoked")
            code, message, retry = self._failure_mapping(exc.failure_class)
            return self._local_failure(started_at, code=code,
                message_class=message, retry_class=retry)
        except (TimeoutError, broker.DeadlineExceeded):
            self._safe_cancel(ready["exchange_id"], "deadline")
            return self._local_failure(started_at, code="deadline_exceeded",
                message_class="timeout", retry_class="never")
        except (ProviderSemanticError, ValueError, TypeError):
            self._safe_cancel(ready["exchange_id"], "policy_revoked")
            return self._local_failure(started_at)
        except Exception:
            self._safe_cancel(ready["exchange_id"], "shutdown")
            return self._local_failure(started_at, code="internal_failure",
                message_class="internal", retry_class="never")
        if refreshed != context:
            self._safe_cancel(ready["exchange_id"], "policy_revoked")
            return self._local_failure(started_at, code="permission_denied",
                message_class="permission", retry_class="human_action_required")
        if time.monotonic() >= deadline_end:
            self._safe_cancel(ready["exchange_id"], "deadline")
            return self._local_failure(started_at, code="deadline_exceeded",
                message_class="timeout", retry_class="never")
        try:
            lease = self._send.commit(ready["exchange_id"], ready["prepare_sha256"],
                                      permit.command_id)
            observed = self._send.exchange(lease)
        except Exception:
            return self._missing_gateway_unknown(context, started_at)
        stamp = self._stamp()
        try:
            if (observed.failure_class is not None or observed.status is None
                    or not 200 <= observed.status < 300):
                raise ValueError("provider response is not a selected success")
            core_normalized = normalize_text(observed.body, context.request["input"]["model_id"])
        except (ValueError, TypeError):
            response = seal_response(self._domain, operation_ref=context.operation_ref,
                exchange_id=observed.exchange_id,
                proposal_sha256=sha256(proposal.body or b"").hexdigest(),
                status=observed.status,
                raw=None if observed.phase == "not_sent" else observed.body,
                phase=observed.phase,
                observed_model=None, stop_reason=None,
                cancel_observed=observed.cancel_observed, created_at_utc=stamp,
                failure_class=observed.failure_class)
            if observed.cancel_observed:
                if observed.phase != "not_sent":
                    seal_effect(self._domain, operation_ref=context.operation_ref,
                        response_ref=response,
                        request_sha256=sha256(canonical_json(context.request)).hexdigest(),
                        effect_state="unknown", remote_outcome="unconfirmed",
                        created_at_utc=stamp)
                return self._cancelled(context, started_at, response_ref=response,
                    after_possible_write=observed.phase != "not_sent")
            if observed.phase == "not_sent":
                code, message_class, retry_class = self._failure_mapping(
                    observed.failure_class)
                error = canonical_provider_error(context.request,
                    code=code, message_class=message_class,
                    retry_class=retry_class, evidence_ref=response.as_dict())
                result = canonical_provider_result(context.request, terminal="failed",
                    started_at=started_at, completed_at=self._port_stamp(), error=error,
                    effect={"effect_class": "external_irreversible", "effect_state": "none",
                        "effect_receipt_ref": None, "remote_outcome": "not_applicable"})
                terminal = seal_terminal(self._domain, operation_ref=context.operation_ref,
                    result=result, response_ref=response, created_at_utc=stamp)
                if self._controller is not None:
                    self._controller.finish(context.operation_ref, terminal)
                outcome, reason = (("denied", "permission_denied")
                    if code == "permission_denied" else ("failed", "validation_failed"))
                return AttemptTransportResult(outcome, terminal, "unknown", "not_observed",
                                              reason, None)
            effect = seal_effect(self._domain, operation_ref=context.operation_ref,
                response_ref=response,
                request_sha256=sha256(canonical_json(context.request)).hexdigest(),
                effect_state="unknown", remote_outcome="unknown", created_at_utc=stamp)
            error = canonical_provider_error(context.request, code="external_effect_unknown",
                message_class="external_outcome", retry_class="never",
                evidence_ref=response.as_dict())
            result = canonical_provider_result(context.request, terminal="unknown",
                started_at=started_at, completed_at=None, error=error,
                effect={"effect_class": "external_irreversible", "effect_state": "unknown",
                    "effect_receipt_ref": effect.as_dict(), "remote_outcome": "unknown"})
            terminal = seal_terminal(self._domain, operation_ref=context.operation_ref,
                result=result, response_ref=response, created_at_utc=stamp)
            if self._controller is not None:
                self._controller.finish(context.operation_ref, terminal)
            return AttemptTransportResult("outcome_unknown", terminal, "unknown",
                "outcome_unknown", "transport_unknown", None)
        response = seal_response(self._domain, operation_ref=context.operation_ref,
            exchange_id=observed.exchange_id, proposal_sha256=sha256(proposal.body or b"").hexdigest(),
            status=observed.status, raw=observed.body, phase=observed.phase,
            observed_model=core_normalized.observed_model, stop_reason=core_normalized.stop_reason,
            cancel_observed=observed.cancel_observed, created_at_utc=stamp,
            failure_class=observed.failure_class)
        try:
            normalized = self._worker.observe(proposal, status=observed.status, raw=observed.body,
                                              exchange_id=observed.exchange_id)
            agrees = (normalized.request_id == context.request["request_id"]
                and normalized.operation == "model_step"
                and normalized.reason == core_normalized.reason
                and normalized.complete == (core_normalized.reason == "complete")
                and normalized.observed_model == core_normalized.observed_model
                and normalized.stop_reason == core_normalized.stop_reason
                and normalized.text_blocks == core_normalized.text_blocks
                and normalized.usage == core_normalized.usage)
        except Exception:
            agrees = False
        if not agrees:
            effect = seal_effect(self._domain, operation_ref=context.operation_ref,
                response_ref=response,
                request_sha256=sha256(canonical_json(context.request)).hexdigest(),
                effect_state="unknown", remote_outcome="unknown", created_at_utc=stamp)
            error = canonical_provider_error(context.request, code="external_effect_unknown",
                message_class="external_outcome", retry_class="never",
                evidence_ref=response.as_dict())
            result = canonical_provider_result(context.request, terminal="unknown",
                started_at=started_at, completed_at=None, error=error,
                effect={"effect_class": "external_irreversible", "effect_state": "unknown",
                    "effect_receipt_ref": effect.as_dict(), "remote_outcome": "unknown"})
            terminal = seal_terminal(self._domain, operation_ref=context.operation_ref,
                result=result, response_ref=response, created_at_utc=stamp)
            if self._controller is not None:
                self._controller.finish(context.operation_ref, terminal)
            return AttemptTransportResult("outcome_unknown", terminal, "unknown",
                                          "outcome_unknown", "transport_unknown", None)
        usage = seal_usage(self._domain, operation_ref=context.operation_ref, response_ref=response,
                           usage=core_normalized.usage, created_at_utc=stamp)
        effect = seal_effect(self._domain, operation_ref=context.operation_ref, response_ref=response,
            request_sha256=sha256(canonical_json(context.request)).hexdigest(), effect_state="committed",
            remote_outcome="confirmed", created_at_utc=stamp)
        outputs = tuple(seal_output(self._domain, operation_ref=context.operation_ref, ordinal=index,
                                    data=data, created_at_utc=stamp)
                        for index, data in enumerate(normalized.text_blocks))
        artifacts = [{"artifact_ref": ref.as_dict(), "role": "model_content",
                      "media_type": "text/plain", "content_digest": sha256(data).hexdigest(),
                      "byte_count": len(data), "omissions_ref": None}
                     for ref, data in zip(outputs, normalized.text_blocks, strict=True)]
        port_stamp = self._port_stamp()
        input_units = core_normalized.usage["input_tokens"]
        output_units = core_normalized.usage["output_tokens"]
        result = {"schema_id": PORT_SCHEMA_IDS[("provider-port-v1", "result")],
                  "schema_version": 1, "port_contract_version": "provider-port-v1",
                  "request_id": context.request["request_id"], "operation": "model_step",
                  "terminal": "succeeded", "started_at": started_at, "completed_at": port_stamp,
                  "extension_output": {}, "error": None, "artifacts": artifacts,
                  "output": {"provider_id": "claude_api", "model_id": normalized.observed_model,
                             "content_block_refs": [ref.as_dict() for ref in outputs],
                             "tool_proposal_refs": [], "usage_report_ref": usage.as_dict(),
                             "provider_response_ref": response.as_dict()},
                  "usage": {"input_units": (input_units["value"] if input_units["state"] == "value" else None),
                            "output_units": (output_units["value"] if output_units["state"] == "value" else None),
                            "billed_units": None,
                            "unit_name": "tokens", "provider_report_ref": usage.as_dict()},
                  "effect": {"effect_class": "external_irreversible", "effect_state": "committed",
                             "effect_receipt_ref": effect.as_dict(), "remote_outcome": "confirmed"}}
        terminal = seal_terminal(self._domain, operation_ref=context.operation_ref, result=result,
                                 response_ref=response, created_at_utc=stamp)
        if self._controller is not None:
            self._controller.finish(context.operation_ref, terminal)
        return AttemptTransportResult("succeeded", terminal, "provisional", "succeeded",
                                      "provider_terminal", None)

    def execute_catalog(self):
        """Run one admitted catalog through both authenticated ports and seal its graph."""
        historical = load_terminal(self._domain, self._context_loader.operation_ref)
        if historical is not None:
            operation = self._context_loader.authorize_historical_read()
            if operation["request"]["operation"] != "catalog":
                raise ValueError("semantic context is not a catalog operation")
            return historical.ref
        operation_ref = self._context_loader.operation_ref
        _config, operation = self._context_loader._operation_identity()
        request = operation["request"]
        if request["operation"] != "catalog" or operation["frozen_ref"] is not None:
            raise ValueError("semantic context is not a catalog operation")
        if not self._context_loader.consume_owner_capability():
            self._context_loader.authorize_historical_read()
            raise ValueError("catalog operation is already owned or unavailable")
        stamp, port_stamp = self._stamp(), self._port_stamp()
        try:
            context = self._context_loader.load(now_utc=stamp)
            if context.request["operation"] != "catalog" or context.frozen_content is not None:
                raise ValueError("semantic context is not a catalog operation")
            deadline_end = self._deadline_end(context.request)
        except Exception as exc:
            try:
                return self._seal_catalog_failure_values(operation_ref, request, port_stamp,
                    [], None, exc)
            finally:
                self._worker.abandon()
        admitted, replay = admit_operation(self._domain, config_ref=context.config_ref,
            request=context.request, core_boot_id=self._domain.get(context.operation_ref).body[
                "content"]["core_boot_id"], reservation_ref=None,
            semantic_key=context.request["idempotency_key"], created_at_utc=stamp)
        if admitted != context.operation_ref:
            raise ValueError("catalog admission resolved another operation")
        retained_pages, latest_observation = [], {"value": None}
        try:
            return self._execute_catalog_owned(context, stamp, port_stamp,
                                               retained_pages, latest_observation,
                                               deadline_end)
        except Exception as exc:
            return self._seal_catalog_failure(context, port_stamp, retained_pages,
                                              latest_observation["value"], exc)
        finally:
            self._worker.abandon()

    def _execute_catalog_owned(self, context, stamp, port_stamp, retained_pages,
                               latest_observation, deadline_end):
        proposal = self._worker.begin(context.request,
            operation_ref=context.operation_ref.as_dict(), config=context.config,
            deadline_end_monotonic=deadline_end)
        worker_session = self._authenticated_session(
            self._worker.authenticated_session_observation,
            protocol_id="deeptwin-extension-worker-v1",
            channel_id="task47-semantic-worker", sender="semantic-worker")
        context = replace(context, worker_session_observation=worker_session)
        traversal, raw_pages = CatalogTraversal(), []
        # every model page is bound to a budget reservation recorded before its send and
        # settled with its observed usage after (zero-cost, bounded; T090)
        from .gateway_send_budget import GatewayCatalogBudget

        budget = GatewayCatalogBudget(self._book)
        budget_session = budget.open("semantic-catalog:" + context.operation_ref.id)
        page_index = 0
        while True:
            remaining = int((deadline_end - time.monotonic()) * 1000)
            if remaining < 1:
                raise TimeoutError("catalog deadline elapsed")
            refreshed = self._context_loader.load(now_utc=self._stamp())
            if (refreshed.config != context.config or refreshed.request != context.request
                    or refreshed.connection != context.connection
                    or refreshed.binding_head != context.binding_head):
                raise ValueError("catalog authority changed between pages")
            # write-ahead: reserved and dispatched in one budget transaction before the
            # prepare frame exists; beyond the policy nothing is sent
            reservation = budget.reserve_page(budget_session, page_index)
            page_index += 1
            committing = False
            try:
                prepared = prepare_message(operation_ref=context.operation_ref.as_dict(),
                    request_id=context.request["request_id"],
                    request_sha256=sha256(canonical_json(context.request)).hexdigest(),
                    selected_handle_ref=context.connection["selected_handle_ref"],
                    connection_pin=context.connection["connection_pin"],
                    credential_metadata=context.connection["credential_metadata"],
                    credential_record=context.connection["credential_record"],
                    endpoint="models", after_id=proposal.after_id, body=b"",
                    remaining_ms=min(30_000, remaining),
                    deadline_at=context.request["deadline_at"],
                    reservation_ref=reservation.reservation_ref)
                ready = self._send.prepare(prepared, deadline_end_monotonic=deadline_end)
                gateway_session = self._authenticated_session(
                    self._send.authenticated_session_observation,
                    protocol_id="credential-gateway-v1", channel_id="task47-provider-send",
                    sender="credential-gateway")
                if gateway_session[2] == context.worker_session_observation[2]:
                    raise ValueError("worker and gateway authenticated sessions are not distinct")
                context = replace(context, gateway_session_observation=gateway_session)
                committing = True
                lease = self._send.commit(ready["exchange_id"], ready["prepare_sha256"],
                                          str(uuid4()))
                observed = self._send.exchange(lease)
            except BaseException as exc:
                phase = getattr(exc, "phase", None)
                budget.settle(reservation, observed=_NotSentPage(),
                              unknown=committing and phase != "not_sent")
                raise
            budget.settle(reservation, observed=observed)
            latest_observation["value"] = observed
            if (observed.failure_class is not None or observed.status is None
                    or not 200 <= observed.status < 300):
                raise _CatalogResponseFailure("catalog provider response is not successful")
            page = parse_model_page(observed.body)
            traversal = advance_catalog(traversal, page)
            raw_pages.append(observed.body)
            retained_pages.append((observed.body, page))
            worker_value = self._worker.observe(proposal, status=observed.status,
                raw=observed.body, exchange_id=observed.exchange_id)
            if not traversal.complete:
                if (type(worker_value) is not ProviderProposal
                        or worker_value.after_id != traversal.pages[-1].last_id
                        or worker_value.traversal != traversal):
                    raise ValueError("worker catalog continuation differs from retained pages")
                proposal = worker_value
                continue
            if (worker_value.traversal != traversal
                    or worker_value.model_ids != traversal.model_ids
                    or not worker_value.complete):
                raise ValueError("worker catalog final differs from retained pages")
            break
        config_content = self._domain.get(context.config_ref).body["content"]
        text_policy_ref = EntityRef.from_dict(config_content["text_policy_ref"])
        connection_ref = EntityRef.from_dict(config_content["connection_ref"])
        compatibility_set = self._domain.get(EntityRef.from_dict(
            config_content["compatibility_set_ref"])).body["content"]
        compatibility = {}
        for item in compatibility_set["observation_refs"]:
            ref = EntityRef.from_dict(item)
            value = self._domain.get(ref).body["content"]
            compatibility[value["model_id"]] = ref
        policy = self._domain.get(text_policy_ref).body["content"]
        fetched = datetime.fromisoformat(port_stamp.replace("Z", "+00:00"))
        policy_expiry = datetime.fromisoformat(policy["valid_until"].replace("Z", "+00:00"))
        expires = min(policy_expiry, fetched + timedelta(
            seconds=context.config["port_config"]["catalog_ttl_seconds"]))
        expires_at = expires.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        catalog_ref = seal_catalog_traversal(self._domain,
            operation_ref=context.operation_ref, connection_ref=connection_ref,
            text_policy_ref=text_policy_ref, compatibility_by_model=compatibility,
            traversal=traversal, raw_pages=tuple(raw_pages), fetched_at=port_stamp,
            expires_at=expires_at, created_at_utc=stamp)
        catalog = self._domain.get(catalog_ref).body["content"]
        result = canonical_provider_result(context.request, terminal="succeeded",
            started_at=port_stamp, completed_at=self._port_stamp(),
            output={"catalog_ref": catalog_ref.as_dict(), "complete": True,
                    "models": catalog["models"]})
        return seal_terminal(self._domain, operation_ref=context.operation_ref,
            result=result, response_ref=None, created_at_utc=self._stamp())

    def _seal_catalog_failure(self, context, started_at, retained_pages, observed, error):
        return self._seal_catalog_failure_values(context.operation_ref, context.request,
            started_at, retained_pages, observed, error)

    def _seal_catalog_failure_values(self, operation_ref, request, started_at,
                                     retained_pages, observed, error):
        for index, (raw, page) in enumerate(retained_pages):
            seal_page(self._domain, operation_ref=operation_ref, index=index,
                after_id=None if index == 0 else retained_pages[index - 1][1].last_id,
                raw=raw, first_id=page.first_id, last_id=page.last_id,
                has_more=page.has_more, model_ids=[model.id for model in page.models],
                created_at_utc=self._stamp())
        response = None
        if observed is not None:
            response = seal_response(self._domain, operation_ref=operation_ref,
                exchange_id=observed.exchange_id, proposal_sha256=sha256(b"").hexdigest(),
                status=observed.status,
                raw=None if observed.phase == "not_sent" else observed.body,
                phase=observed.phase,
                observed_model=None, stop_reason=None,
                cancel_observed=observed.cancel_observed, created_at_utc=self._stamp(),
                failure_class=observed.failure_class)
        if observed is not None and observed.failure_class is not None:
            code, message, retry = self._failure_mapping(observed.failure_class)
            port_code = None
        elif isinstance(error, ProviderSemanticAdmissionError):
            code, message, retry = self._failure_mapping(error.failure_class)
            port_code = None
        elif isinstance(error, (TimeoutError, broker.DeadlineExceeded)):
            code, port_code, message, retry = "deadline_exceeded", None, "timeout", "never"
        elif isinstance(error, broker.ProtocolViolation):
            code, port_code, message, retry = "integrity_failed", None, "integrity", "never"
        elif isinstance(error, (ProviderSemanticError, ValueError)):
            code, port_code, message, retry = ("port_specific_failure", "catalog_incomplete",
                                               "port_failure", "human_action_required")
        elif isinstance(error, _CatalogResponseFailure):
            code, port_code, message, retry = ("dependency_unavailable", None,
                                               "dependency", "human_action_required")
        else:
            code, port_code, message, retry = ("internal_failure", None,
                                               "internal", "never")
        canonical_error = canonical_provider_error(request, code=code,
            port_error_code=port_code, message_class=message, retry_class=retry,
            evidence_ref=None if response is None else response.as_dict())
        result = canonical_provider_result(request, terminal="failed",
            started_at=started_at, completed_at=self._port_stamp(), error=canonical_error)
        return seal_terminal(self._domain, operation_ref=operation_ref,
            result=result, response_ref=response, created_at_utc=self._stamp())


class ProviderSemanticOperationController:
    """Unregistered durable fresh-read and target-monotonic cancel consumer seam."""

    def __init__(self, domain_store, *, ledger, config_ref, core_boot_id, authority):
        if (type(domain_store) is not DomainStore or type(ledger) is not RuntimeLedger
                or type(authority) is not ProviderSemanticAuthority):
            raise TypeError("exact DomainStore and RuntimeLedger required")
        self._domain, self._ledger = domain_store, ledger
        self._config, self._boot, self._authority = config_ref, core_boot_id, authority
        self._guard = threading.Lock()
        self._live = {}

    @staticmethod
    def _key(ref):
        return (ref.kind, ref.id, ref.version, ref.sha256)

    def register_live(self, operation_ref, *, cancel_event, forward_cancel, attempt_id=None,
                      execution_id=None, envelope_ref=None):
        if type(cancel_event) is not threading.Event or not callable(forward_cancel):
            raise TypeError("exact live cancellation state required")
        with self._guard:
            if self._key(operation_ref) in self._live:
                raise ValueError("operation already has a live owner")
            self._live[self._key(operation_ref)] = {
                "lock": threading.Lock(), "state": "running", "terminal": None,
                "cancel_event": cancel_event, "forward": forward_cancel,
                "attempt_id": attempt_id, "execution_id": execution_id,
                "envelope_ref": envelope_ref}

    def finish(self, operation_ref, terminal_ref):
        with self._guard:
            live = self._live.get(self._key(operation_ref))
        if live is not None:
            with live["lock"]:
                live["state"], live["terminal"] = "terminal", terminal_ref

    def _live_state(self, target_ref):
        with self._guard:
            return self._live.get(self._key(target_ref))

    def _authorize_query(self, request, target_ref, observed_at, *, historical=False,
                         accepted_at=None):
        target = self._domain.get(target_ref).body["content"]
        config_record = self._domain.get(self._config).body["content"]
        if (target.get("schema_version") != "provider-semantic-operation-v1"
                or target.get("config_ref") != self._config.as_dict()
                or request.get("input", {}).get("operation_ref") != target_ref.as_dict()):
            raise ValueError("query target is not owned by this semantic config")
        config = config_record.get("config")
        if config_record.get("schema_version") != "provider-semantic-config-v1":
            raise ValueError("query config is not semantic")
        if not historical:
            binding_record, binding_head_record, _head = durable_binding(
                self._domain, self._authority, config)
            validate_port_payload("provider-port-v1", "config", config, context={
                "validated_at": observed_at,
                "qualification_record": self._authority.qualification_record,
                "binding_revision_record": binding_record,
                "binding_head_record": binding_head_record})
            connection_ref = EntityRef.from_dict(config_record["connection_ref"])
            connection = self._domain.get(connection_ref)
            validate_bound_handle(config=config, binding=binding_record,
                connection_record={"ref": connection_ref.as_dict(),
                    "content": connection.body["content"]},
                current_connection=self._authority.current_connection)
        trusted_inputs = dict(self._authority.input_records)
        trusted_inputs[target_ref.sha256] = {"ref": target_ref.as_dict(),
                                             "record_type": "operation"}
        validate_port_payload("provider-port-v1", "request", request, context={
            "config": config, "accepted_at": observed_at if accepted_at is None else accepted_at,
            "actor_record": self._authority.actor_record,
            "purpose_record": self._authority.purpose_record,
            "grant_records": self._authority.grant_records,
            "artifact_records": self._authority.artifact_records,
            "selector_records": self._authority.selector_records,
            "input_records": trusted_inputs})
        owner = target["request"]
        identity = ("installation_digest", "qualification_ref", "binding_revision_ref",
                    "purpose_ref", "actor_ref", "grant_refs")
        if any(owner.get(name) != request.get(name) for name in identity):
            raise ValueError("query caller is not the exact target owner")

    def _target_coordinates(self, target_ref, live):
        if (live is not None and type(live.get("attempt_id")) is str
                and type(live.get("execution_id")) is str
                and type(live.get("envelope_ref")) is EntityRef):
            return live["attempt_id"], live["execution_id"], live["envelope_ref"]
        try:
            record = self._domain.get(target_ref)
        except Exception:
            return None
        content = record.body["content"]
        if content["config_ref"] != self._config.as_dict() or content["request"]["operation"] != "model_step":
            return None
        frozen_ref = EntityRef.from_dict(content["frozen_ref"])
        frozen = self._domain.get(frozen_ref).body["content"]
        turn = frozen["turn"]
        execution = self._ledger.get_execution(turn["execution_id"])["spec"]
        loop_path = execution["loop_path"]
        loop_index = loop_path[-1] if loop_path else 0
        return (attempt_identity(execution["run_id"], turn["node_id"], loop_index,
                                 turn["attempt_index"]),
                turn["execution_id"], EntityRef.from_dict(frozen["execution_envelope_ref"]))

    def _accepted(self, target_ref, live):
        coordinates = self._target_coordinates(target_ref, live)
        if coordinates is None:
            return None
        return self._ledger.lookup_committed_result(*coordinates)

    @staticmethod
    def _acquire(lock, request):
        try:
            deadline = datetime.fromisoformat(request["deadline_at"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            raise ValueError("query deadline is malformed") from None
        remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0 or not lock.acquire(timeout=min(remaining, 30.0)):
            raise TimeoutError("query target mutex deadline elapsed")

    @staticmethod
    def _result(request, output, observed_at):
        return canonical_provider_result(request, terminal="succeeded", started_at=observed_at,
                                         completed_at=observed_at, output=output)

    def observe_status(self, request, *, semantic_key, observed_at, created_at_utc):
        target_ref = EntityRef.from_dict(request["input"]["operation_ref"])
        retained_operation = load_operation(self._domain, request["request_id"])
        self._authorize_query(request, target_ref, observed_at,
            historical=retained_operation is not None,
            accepted_at=(None if retained_operation is None else
                         retained_operation.body["created_at_utc"]))
        operation_ref, replay = admit_operation(self._domain, config_ref=self._config,
            request=request, core_boot_id=self._boot, reservation_ref=None,
            semantic_key=semantic_key, created_at_utc=created_at_utc)
        if replay:
            terminal = load_terminal(self._domain, operation_ref)
            if terminal is None:
                raise ValueError("retained status observation is unavailable")
            return terminal.body["content"]["result"]
        live = self._live_state(target_ref)
        lock = self._guard if live is None else live["lock"]
        self._acquire(lock, request)
        try:
            accepted = self._accepted(target_ref, live)
            if accepted is not None:
                observed_state = ("unknown" if accepted["outcome"] == "outcome_unknown"
                                  else accepted["outcome"])
                terminal_ref = accepted["result_ref"]
            elif live is None:
                observed_state, terminal_ref = "unknown", None
            else:
                observed_state, terminal_ref = "running", None
        finally:
            lock.release()
        result = self._result(request, {"observed_state": observed_state,
            "observed_at": observed_at,
            "terminal_result_ref": (None if terminal_ref is None else terminal_ref.as_dict()
                                    if type(terminal_ref) is EntityRef else terminal_ref)},
            observed_at)
        seal_terminal(self._domain, operation_ref=operation_ref, result=result,
                      response_ref=None, created_at_utc=created_at_utc)
        return result

    def cancel(self, request, *, semantic_key, observed_at, created_at_utc):
        reason_class = request["input"]["reason_class"]
        target_ref = EntityRef.from_dict(request["input"]["operation_ref"])
        existing = load_operation(self._domain, request["request_id"])
        self._authorize_query(request, target_ref, observed_at, historical=existing is not None,
            accepted_at=None if existing is None else existing.body["created_at_utc"])
        if existing is not None:
            if (existing.body["content"]["request"] != request
                    or existing.body["content"]["config_ref"] != self._config.as_dict()):
                raise ValueError("same cancel identity changed immutable input")
            terminal = load_terminal(self._domain, existing.ref)
            if terminal is None:
                raise ValueError("cancel acknowledgement unavailable after owner loss")
            return terminal.body["content"]["result"]
        live = self._live_state(target_ref)
        lock = self._guard if live is None else live["lock"]
        self._acquire(lock, request)
        try:
            if self._accepted(target_ref, live) is not None:
                operation_ref, _ = admit_operation(self._domain, config_ref=self._config,
                    request=request, core_boot_id=self._boot, reservation_ref=None,
                    semantic_key=semantic_key, created_at_utc=created_at_utc)
                state, forward = "already_terminal", None
            elif live is None:
                operation_ref, _ = admit_operation(self._domain, config_ref=self._config,
                    request=request, core_boot_id=self._boot, reservation_ref=None,
                    semantic_key=semantic_key, created_at_utc=created_at_utc)
                state, forward = "not_cancellable", None
            else:
                intent = load_cancel_intent(self._domain, target_ref)
                if intent is None:
                    operation_ref, _ = seal_cancel_operation_and_intent(self._domain,
                        config_ref=self._config, request=request, core_boot_id=self._boot,
                        target_operation_ref=target_ref, reason_class=reason_class,
                        created_at_utc=created_at_utc)
                    live["cancel_event"].set()
                    state, forward = "accepted", live["forward"]
                else:
                    operation_ref, _ = admit_operation(self._domain, config_ref=self._config,
                        request=request, core_boot_id=self._boot, reservation_ref=None,
                        semantic_key=semantic_key, created_at_utc=created_at_utc)
                    state = "accepted" if live["cancel_event"].is_set() else "not_cancellable"
                    forward = None
        finally:
            lock.release()
        if forward is not None:
            try:
                forward(reason_class)
            except Exception:
                pass
        result = self._result(request, {"cancel_state": state, "observed_at": observed_at},
                              observed_at)
        seal_terminal(self._domain, operation_ref=operation_ref, result=result,
                      response_ref=None, created_at_utc=created_at_utc)
        return result


__all__ = ["ProviderAttemptTransport", "ProviderSemanticOperationController"]
