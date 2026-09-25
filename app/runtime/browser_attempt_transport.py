"""The attempt transport of the browser tools (T043): a graph node's browser tool call
reaches the sandboxed browser worker through the dispatcher's one-shot permit.

`BrowserAttemptTransport` is the code-owned `CompiledToolTransport` for the three
first-suite browser tools (runtime.md §6: `browser.navigate`, `browser.read`,
`browser.screenshot`, as the ToolDefinitions `browser_navigate`, `browser_read`,
`browser_screenshot` 1.0.0). It is built for exactly one compiled node binding and one
typed `BrowserRequest` (the operation must be the bound tool's). Its grant is never
supplied in code: it is the owner's persisted browser grant record
(`app.services.browser_grants`) that the compiled binding's `grant_ref` names exactly,
current for the bound tool; the URL must lie under a granted source and be exactly one of
the grant's projection entries with only declared source values; the product's own origin
hosts are never recipients.

Per attempt, inside the consumed dispatch window, the authority is re-resolved before
anything is sent: the run's environment must resolve to the owner's design approval whose
approved `tool_permissions` is exactly that grant record, and the record must still be
current (not revoked, not expired). A refusal is a `denied` attempt (`permission_denied`)
with nothing sent. Then the ToolCall's write-ahead intent (also claimed by the dispatcher
with the send), one `BrowserClient.run` — grant registered with the fetch service, the
browser session, grant revoked and the fetch service's own accounting compared — and the
ToolCall settled from what control observed:

- a verified observation is sealed control-side as an immutable `artifact` record (the
  output — rendered text or the PNG — imported as registered content first) and is the
  attempt's `succeeded` result; the usage is one tool call and the bytes control measured;
- a grant, projection, DNS or redirect refusal is a `denied` attempt (`permission_denied`); a timeout
  is `timed_out` (`deadline`); an oversize, render, sandbox or fetch failure is `failed`;
  each with final usage (the call ran);
- no reachable worker is `definitely_not_sent`; a broken or contradictory exchange is an
  unknown outcome.

The effect class of every browser tool is `read`: a GET under an explicit grant, no
external effect approval. The control plane never imports the browser driver.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import EntityRef, canonical_json, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore
from ..services.browser_grants import (
    GRANTABLE_TOOLS,
    BrowserGrantError,
    PersistentBrowserGrants,
    approved_tool_permissions,
)
from ..workers.browser_channel import (
    MAX_OPERATION_MS,
    MIN_DEADLINE_MS,
    BrowserChannelError,
    BrowserClient,
    BrowserRequest,
)
from ..workers.fetch_channel import check_hostname, projection_values, source_admits
from .budgets import BudgetUsage
from .graph import CompiledToolTransport, resolve_compiled_tool_binding
from .ledger import (
    ConsumedDispatchWindow,
    DispatchPermit,
    LedgerError,
    RuntimeLedger,
    ToolCallSpec,
    ToolDispatchClaim,
    tool_call_identity,
)
from .node_attempts import AttemptDispatchRequest, AttemptTransportResult

__all__ = [
    "BROWSER_TOOLS",
    "OUTPUT_SCHEMA",
    "BrowserAttemptTransport",
    "BrowserToolsUnavailable",
    "BrowserToolset",
    "BrowserTransportError",
]

OUTPUT_SCHEMA = "browser-tool-output-v1"
# the mirrored ToolDefinitions: (tool id, version) -> the one operation it performs
BROWSER_TOOLS = MappingProxyType({
    ("browser_navigate", "1.0.0"): "navigate",
    ("browser_read", "1.0.0"): "read",
    ("browser_screenshot", "1.0.0"): "screenshot",
})
EFFECT_CLASS = "read"
MAX_SUMMARY_BYTES = 8_192
_WINDOW_MARGIN_MS = 6_000  # the client's connection deadline runs 5 s past the session's
CODES = frozenset({"transport_unavailable", "transport_deadline", "transport_invalid", "transport_mismatch",
                   "seal_failed"})
_EFFECTS = frozenset({"definitely_not_sent", "may_have_started", "outcome_unknown"})
_DENIED = frozenset({"grant_denied", "projection_denied", "dns_denied", "redirect_denied"})
if tuple(sorted(tool for tool, _version in BROWSER_TOOLS)) != GRANTABLE_TOOLS:  # pragma: no cover
    raise RuntimeError("the grantable browser tools are exactly the mirrored ToolDefinitions")
_FAILED = frozenset({"too_large", "render_failed", "fetch_failed", "sandbox_unavailable", "invalid_request"})


class BrowserTransportError(RuntimeError):
    """Closed error family with the dispatch effect control can vouch for."""

    __slots__ = ("code", "dispatch_effect")

    def __init__(self, code: str, *, dispatch_effect: str = "outcome_unknown") -> None:
        if code not in CODES or dispatch_effect not in _EFFECTS:
            raise ValueError("unknown transport error code")
        super().__init__(code)
        self.code = code
        self.dispatch_effect = dispatch_effect


def _tool_call_command(send_command_id) -> str:
    return str(uuid5(NAMESPACE_URL, f"deeptwin:command:tool-call:{send_command_id}"))


def sealed_artifact_identity(send_command_id) -> str:
    uuid_string(send_command_id)
    return str(uuid5(NAMESPACE_URL, f"deeptwin:artifact:browser:{send_command_id}"))


def _usage(output_bytes: int) -> BudgetUsage:
    return BudgetUsage.create(model_calls=0, tool_calls=1, node_visits=1, loop_rounds=0,
                              output_bytes=output_bytes, candidates=0, api_microunits=None)


class BrowserAttemptTransport(CompiledToolTransport):
    """Built only by `build`; one compiled browser tool binding, one request, and the
    owner's grant record that binding names."""

    __slots__ = ("_client", "_compiled", "_compiled_binding", "_domain", "_excluded", "_grants", "_ledger",
                 "_request")

    def __init__(self) -> None:
        raise TypeError("Use BrowserAttemptTransport.build")

    @staticmethod
    def _admits(dispatch, request, excluded) -> None:
        grant = dispatch.grant
        if not source_admits(grant.sources, request.url):
            raise ValueError("the url is outside the grant's sources")
        if projection_values(grant.projection, request.url) is None:
            raise ValueError("the url carries data the grant's projection does not permit")
        if any(host in excluded for host in grant.recipients):
            raise ValueError("the product's own origin is never a browser recipient")

    @classmethod
    def build(cls, *, domain_store, ledger, compiled, node_id, binding_id, client, request, grants,
              excluded_hosts=()):
        if type(domain_store) is not DomainStore:
            raise TypeError("Exact DomainStore required")
        if type(ledger) is not RuntimeLedger or ledger._domain is not domain_store:
            raise TypeError("invocation requires the exact ledger and its DomainStore")
        if type(client) is not BrowserClient:
            raise TypeError("an exact BrowserClient is required")
        if type(request) is not BrowserRequest:
            raise TypeError("an exact BrowserRequest is required")
        if type(grants) is not PersistentBrowserGrants or not grants.bound_to(domain_store):
            raise TypeError("the owner's browser grants over the same store are required")
        excluded = tuple(check_hostname(host) for host in excluded_hosts)
        binding = resolve_compiled_tool_binding(compiled, node_id, binding_id)
        key = (binding.tool_id, binding.version)
        if key not in BROWSER_TOOLS:
            raise ValueError("the bound tool is not a browser tool")
        if BROWSER_TOOLS[key] != request.op:
            raise ValueError("the request's operation is not the bound tool's")
        if binding.effect_class != EFFECT_CLASS:
            raise ValueError("a browser tool's definition must carry the read effect")
        try:
            # the grant is the owner's record the binding names, current for this tool
            dispatch = grants.for_dispatch(binding.grant_ref, tool_id=binding.tool_id, version=binding.version)
        except BrowserGrantError as error:
            raise ValueError(f"the bound grant is not a current owner browser grant ({error.code})") from None
        cls._admits(dispatch, request, excluded)
        transport = object.__new__(cls)
        transport._domain, transport._ledger, transport._client = domain_store, ledger, client
        transport._compiled, transport._compiled_binding = compiled, binding
        transport._request, transport._grants, transport._excluded = request, grants, excluded
        return transport

    def _current_grant(self, request):
        """The grant this attempt may run under, re-resolved now; None when the run's
        approved tool permissions are not exactly the bound grant record, or the record
        is no longer current (revoked, expired)."""

        binding = self._compiled_binding
        try:
            run = self._ledger.get_run(request.run_id)["spec"]
            approved = approved_tool_permissions(self._domain, EntityRef.from_dict(run["environment_ref"]))
            if approved != binding.grant_ref:
                return None
            dispatch = self._grants.for_dispatch(binding.grant_ref, tool_id=binding.tool_id,
                                                 version=binding.version)
            self._admits(dispatch, self._request, self._excluded)
        except (BrowserGrantError, ValueError, KeyError, TypeError, LedgerError):
            return None
        return dispatch.grant

    # --- the CompiledToolTransport coherence interface ----------------------------------

    @property
    def compiled_tool_binding(self):
        return self._compiled_binding

    def require_dispatch_ledger(self, ledger):
        if type(ledger) is not RuntimeLedger or ledger is not self._ledger or ledger._domain is not self._domain:
            raise ValueError("compiled invocation must share the exact dispatcher ledger/store")

    def require_compiled_context(self, compiled, node_id, ledger):
        self.require_dispatch_ledger(ledger)
        binding = self._compiled_binding
        if node_id != binding.node_id or resolve_compiled_tool_binding(compiled, node_id, binding.binding_id) != binding:
            raise ValueError("compiled tool binding disagrees with dispatch context")

    @property
    def per_attempt_approval(self) -> bool:
        return False  # a read tool carries no effect approval

    @property
    def effect_class(self) -> str:
        return self._compiled_binding.effect_class

    @property
    def output_bytes_bound(self) -> int:
        """The most output bytes control measures for one attempt: the sealed summary
        (bounded) and the operation's output bound."""
        return MAX_SUMMARY_BYTES + self._request.max_output_bytes

    def _spec(self, attempt_id) -> ToolCallSpec:
        binding = self._compiled_binding
        return ToolCallSpec(tool_call_id=tool_call_identity(attempt_id), attempt_id=attempt_id,
                            tool_id=binding.tool_id, version=binding.version, effect_class=self.effect_class,
                            artifact_inputs=(), approval_ref=None)

    def dispatch_claim(self, request, send_command_id):
        if type(request) is not AttemptDispatchRequest:
            raise TypeError("Exact AttemptDispatchRequest required")
        uuid_string(send_command_id)
        return ToolDispatchClaim(command_id=_tool_call_command(send_command_id), spec=self._spec(request.attempt_id))

    # --- one attempt ------------------------------------------------------------------

    def __call__(self, permit, request, window) -> AttemptTransportResult:
        if type(permit) is not DispatchPermit:
            raise TypeError("Exact DispatchPermit required")
        if type(request) is not AttemptDispatchRequest:
            raise TypeError("Exact AttemptDispatchRequest required")
        if type(window) is not ConsumedDispatchWindow or window.permit is not permit:
            raise TypeError("The consumed window of this exact permit is required")
        try:
            self._ledger.assert_consumed_dispatch_window(window, permit=permit)
            self.require_compiled_context(self._compiled, request.node_id, self._ledger)
            execution = self._ledger.get_execution(request.execution_id)["spec"]
            attempt = self._ledger.get_attempt(request.attempt_id)["spec"]
            if (request.tool_binding != self._compiled_binding or execution["run_id"] != request.run_id
                    or execution["node_id"] != request.node_id or attempt["execution_id"] != request.execution_id
                    or permit.attempt_id != request.attempt_id or permit.execution_id != request.execution_id
                    or permit.envelope_ref != request.envelope_ref or permit.profile_ref != request.profile_ref):
                raise ValueError("invocation binding mismatch")
        except (TypeError, ValueError, KeyError, LedgerError):
            raise BrowserTransportError("transport_mismatch", dispatch_effect="definitely_not_sent") from None
        remaining_ms = int((window.deadline_end_monotonic - time.monotonic()) * 1_000) - _WINDOW_MARGIN_MS
        if remaining_ms < MIN_DEADLINE_MS:
            raise BrowserTransportError("transport_deadline", dispatch_effect="definitely_not_sent")
        browser_request = BrowserRequest(
            op=self._request.op, url=self._request.url,
            deadline_ms=min(self._request.deadline_ms, remaining_ms, MAX_OPERATION_MS),
            max_text_bytes=self._request.max_text_bytes, width=self._request.width, height=self._request.height,
            max_png_bytes=self._request.max_png_bytes)
        spec = self._spec(request.attempt_id)
        grant = self._current_grant(request)
        try:
            self._ledger.record_tool_call(_tool_call_command(permit.command_id), spec)
        except Exception:  # noqa: BLE001 - the ledger's detail stays private
            raise BrowserTransportError("transport_invalid", dispatch_effect="definitely_not_sent") from None
        if grant is None:
            # no current owner grant for this run and tool: refused before anything is sent
            self._settle(permit, spec, "failed", None)
            return AttemptTransportResult(
                outcome="denied", result_ref=None, usage_finality="final", remote_terminal_observed="not_observed",
                reason_code="permission_denied",
                usage=BudgetUsage.create(model_calls=0, tool_calls=0, node_visits=1, loop_rounds=0, output_bytes=0,
                                         candidates=0, api_microunits=None))
        try:
            observation = self._client.run(browser_request, grant, excluded_hosts=self._excluded)
        except BrowserChannelError as error:
            return self._refused(permit, spec, error)
        except Exception:
            self._settle(permit, spec, "unknown", None)
            raise
        try:
            result_ref, measured = self._seal(permit, request, observation)
        except BrowserTransportError:
            self._settle(permit, spec, "unknown", None)
            raise
        self._settle(permit, spec, "succeeded", result_ref)
        return AttemptTransportResult(outcome="succeeded", result_ref=result_ref, usage_finality="final",
                                      remote_terminal_observed="succeeded", reason_code="provider_terminal",
                                      usage=_usage(measured))

    def _refused(self, permit, spec, error) -> AttemptTransportResult:
        code = error.code
        if not error.sent:
            self._settle(permit, spec, "failed", None)
            raise BrowserTransportError("transport_unavailable", dispatch_effect="definitely_not_sent") from None
        if code in _DENIED:
            outcome, reason = "denied", "permission_denied"
        elif code == "timeout":
            outcome, reason = "timed_out", "deadline"
        elif code in _FAILED:
            outcome, reason = "failed", "provider_terminal"
        else:  # transport_failed, malformed_result, unavailable after the send
            self._settle(permit, spec, "unknown", None)
            raise BrowserTransportError("transport_invalid") from None
        self._settle(permit, spec, "failed", None)
        return AttemptTransportResult(outcome=outcome, result_ref=None, usage_finality="final",
                                      remote_terminal_observed=outcome, reason_code=reason, usage=_usage(0))

    def _settle(self, permit, spec, outcome, result_ref) -> None:
        try:
            self._ledger.settle_tool_call(
                str(uuid5(NAMESPACE_URL, f"deeptwin:command:tool-call:{permit.command_id}:{outcome}")),
                spec.tool_call_id, outcome=outcome, result_ref=result_ref)
        except Exception:  # noqa: BLE001 - the ledger's detail stays private
            raise BrowserTransportError("transport_invalid") from None

    def _seal(self, permit, request, observation) -> tuple[EntityRef, int]:
        summary = observation.summary()
        encoded = canonical_json(summary)
        if len(encoded) > MAX_SUMMARY_BYTES or len(observation.output) > self._request.max_output_bytes:
            raise BrowserTransportError("transport_mismatch")
        try:
            roots = self._domain.roots()
            output = None
            if observation.media_type is not None:
                blob = self._domain.put_blob(observation.output, purpose="operational")
                if blob.sha256 != observation.output_sha256 or blob.size != len(observation.output):
                    raise ValueError("imported output diverged")
                output = {"media_type": observation.media_type, "blob": blob.as_dict()}
            binding = self._compiled_binding
            record = ImmutableRecord.create(
                kind="artifact", id=sealed_artifact_identity(permit.command_id), version=1,
                created_at_utc=datetime.fromtimestamp(time.time(), UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                actor_ref=roots.actor, parent_refs=(request.envelope_ref, binding.grant_ref), purpose="operational",
                access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                content={"schema_version": OUTPUT_SCHEMA, "tool_id": binding.tool_id, "version": binding.version,
                         "operation": observation.op, "attempt_id": request.attempt_id,
                         "execution_id": request.execution_id, "send_command_id": permit.command_id,
                         "observation": summary, "output": output})
            self._domain.put(record)
        except Exception:  # noqa: BLE001 - the store's detail stays private
            raise BrowserTransportError("seal_failed") from None
        return record.ref, len(encoded) + len(observation.output)


@dataclass(frozen=True, slots=True)
class BrowserToolsUnavailable:
    """The honest state when no browser worker is named: every build refuses."""

    reason: str = "no browser worker is attached to this deployment"

    available = False

    def transport_for(self, **_kwargs):
        raise BrowserChannelError("unavailable", sent=False)


class BrowserToolset:
    """The deployment's attached browser: builds a node's transport over one client and
    the owner's persisted browser grants (never a grant supplied in code)."""

    __slots__ = ("_client", "_excluded", "_grants")
    available = True

    def __init__(self, client: BrowserClient, *, grants: PersistentBrowserGrants, excluded_hosts=()):
        if type(client) is not BrowserClient:
            raise TypeError("an exact BrowserClient is required")
        if type(grants) is not PersistentBrowserGrants:
            raise TypeError("the owner's persisted browser grants are required")
        self._client, self._grants = client, grants
        self._excluded = tuple(check_hostname(host) for host in excluded_hosts)

    @property
    def client(self) -> BrowserClient:
        return self._client

    @property
    def grants(self) -> PersistentBrowserGrants:
        return self._grants

    def transport_for(self, *, domain_store, ledger, compiled, node_id, binding_id, request):
        return BrowserAttemptTransport.build(
            domain_store=domain_store, ledger=ledger, compiled=compiled, node_id=node_id, binding_id=binding_id,
            client=self._client, request=request, grants=self._grants, excluded_hosts=self._excluded)
