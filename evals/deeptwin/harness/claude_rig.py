"""Claude API rig for Q01 trials: real catalog + selection + streaming turn.

``claude_rig`` builds the product ``ModelCatalog``/``ModelSelection`` pair whose
``('claude', 'api')`` source is a ``ClaudeAPIAdapter`` over an in-memory
credential vault, refreshes the catalog through that adapter, saves a work
selection that names the true model and effort, and returns a ``TrialConfig``
plus a ``(system, user) -> str`` turn that streams through the same adapter
and the same issued catalog snapshot.

``attested_turn`` (and ``make_turn(..., attested=True)``) is the release transport
(release-v6, audit 5 X1; release-v7): it returns an ``app.critic_trial.ProviderReply`` carrying
the model the provider's response message named, the provider request id (the
``request-id`` response header, as the adapter exposes it) and the response message
id, exactly as the product adapter parsed them from the provider response, never
from the selection. When the provider reported any of them missing it returns the
plain text, which the harness records as unattested (a release trial then cannot
pass). ``turn`` stays the calibration transport and returns text only.

Every turn declares how the rig was built (``turn.critic_transport``, audit 6 non-blocking
5): ``{"injected": false, "name": null}`` when ``transport`` is ``None`` (the product
adapter's own HTTP transport), else ``{"injected": true, "name": ...}`` with the given
``transport_name`` (or the injected object's type). The harness records it in every release
trial record and refuses dispatch when it differs from the manifest's
``run_identity.critic_transport``; a release manifest may name an injected transport only
when the design allows that named test double, and release-v7 allows none.

The secret is handed to the vault once and never retained, logged or written
by this module. A turn returns text only for a ``completed`` terminal and
raises ``TurnFailed`` otherwise. Every dispatched call appends one usage entry
(tokens, provider message id, stop reason, terminal state) to ``rig.usage``.
An optional ``guard`` object is consulted before (``before_call``) and after
(``after_call``) every call; it is how a caller enforces spend or deadline
limits.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.adapters.claude_api import (
    ClaudeAPIAdapter,
    ClaudeBinding,
    MessageTurn,
    ProviderStarted,
    ProviderTerminal,
    StreamLimits,
    TextDelta,
    UsageObserved,
)
from app.adapters.claude_api import (
    ModelSelection as AdapterSelection,
)
from app.adapters.keychain import InMemoryCredentialVault
from app.critic_trial import ProviderReply
from app.model_catalog import ModelCatalog
from app.model_selection import ModelSelection
from app.storage import Store

from .q01_harness import TrialConfig

PROVIDER, MODE = "claude", "api"
# The adapter's non-configurable per-call ceiling is 180 s; a plan may only lower it.
MAX_CALL_SECONDS = 180


class TurnFailed(RuntimeError):
    """A streamed call did not reach a completed terminal (no text is returned)."""

    def __init__(self, state: str, detail: str | None = None):
        super().__init__(f"call ended in state {state}" + (f" ({detail})" if detail else ""))
        self.state, self.detail = state, detail


class _RecordingSource:
    """Catalog source that delegates to the adapter and keeps the issued snapshot.

    The product catalog normalizes and stores the adapter snapshot but does not
    return it; streaming must present the exact issued snapshot back to the
    adapter, so the rig keeps the most recent one here.
    """

    def __init__(self, adapter: ClaudeAPIAdapter):
        self.adapter = adapter
        self.snapshot = None

    def connection_state(self, binding):
        return self.adapter.connection_state(binding)

    def fetch_catalog(self, binding, *, explicit_action):
        snapshot = self.adapter.fetch_catalog(binding, explicit_action=explicit_action)
        self.snapshot = snapshot
        return snapshot


@dataclass
class ClaudeRig:
    config: TrialConfig
    turn: Callable[[str, str], str]
    usage: list = field(default_factory=list)
    model_id: str = ""
    effort: str | None = None
    catalog: dict | None = None
    make_turn: Callable[..., Callable[[str, str], str]] | None = None
    attested_turn: Callable[[str, str], ProviderReply | str] | None = None
    critic_transport: dict | None = None

    def __repr__(self) -> str:  # never render adapter/vault internals
        return f"ClaudeRig(model_id={self.model_id!r}, effort={self.effort!r}, calls={len(self.usage)})"


def _listed_efforts(catalog: dict, model_id: str) -> list[str]:
    entry = next((item for item in catalog["models"] if item["model"] == model_id), None)
    if entry is None:
        raise ValueError("the requested model is not in the refreshed catalog")
    return [item["value"] for item in entry["reasoning_efforts"]]


def claude_rig(base_dir, *, secret: str, model_id: str, effort: str | None, transport=None,
               transport_name: str | None = None, max_tokens: int = 8192, call_seconds: int = MAX_CALL_SECONDS,
               harness_call_seconds: float | None = None, run_seconds: float = 3600.0,
               max_proposed_chains: int = 16, catalog_max_age_ms: int = 4 * 60 * 60 * 1000,
               guard=None, agent_id: str = "q01-critic") -> ClaudeRig:
    """Build a Claude API rig; ``base_dir`` holds the catalog/selection store only."""
    base = Path(base_dir)
    if not base.is_absolute():
        raise ValueError("an absolute base directory is required")
    if type(secret) is not str or not secret:
        raise ValueError("an API secret is required")
    if type(call_seconds) is not int or not 0 < call_seconds <= MAX_CALL_SECONDS:
        raise ValueError("call_seconds must be an integer within the adapter ceiling")
    harness_seconds = float(harness_call_seconds if harness_call_seconds is not None else call_seconds + 15)
    if harness_seconds <= call_seconds:
        # The adapter's own deadline must end the call before the harness abandons it.
        raise ValueError("the harness call deadline must exceed the adapter deadline")
    if transport is None:
        if transport_name is not None:
            raise ValueError("a transport name is only given with an injected transport")
        critic_transport = {"injected": False, "name": None}
    else:
        name = transport_name or f"{type(transport).__module__}.{type(transport).__qualname__}"
        if type(name) is not str or not name.strip():
            raise ValueError("an injected transport needs a name")
        critic_transport = {"injected": True, "name": name}
    vault = InMemoryCredentialVault()
    ref = vault.store(PROVIDER, secret)
    secret = ""
    binding = ClaudeBinding(credential_ref=ref)
    adapter = ClaudeAPIAdapter(vault=vault, transport=transport,
                               limits=StreamLimits(max_stream_duration_ms=call_seconds * 1000),
                               catalog_max_age_ms=catalog_max_age_ms,
                               # A long silent reasoning phase must not trip a shorter per-read timeout.
                               timeout_seconds=float(call_seconds))
    source = _RecordingSource(adapter)
    store = Store(base / "rig-store")
    catalog = ModelCatalog(store, None, api_sources={(PROVIDER, MODE): (source, binding)})
    snapshot = catalog.refresh(PROVIDER, MODE)
    issued = source.snapshot
    if issued is None or snapshot.get("source_catalog_id") != issued.catalog_id:
        raise RuntimeError("the refreshed catalog does not match the issued adapter snapshot")
    listed = _listed_efforts(snapshot, model_id)
    if effort is not None and effort not in listed:
        raise ValueError("the requested effort is not listed for this model in the refreshed catalog")
    selections = ModelSelection(store, catalog)
    work = store.create_work("Q01 calibration trial selection")
    choice = {"provider": PROVIDER, "mode": MODE, "model": model_id, "effort": effort,
              "catalog_id": snapshot["catalog_id"]}
    saved = selections.save(work["id"], 0, choice)
    config = TrialConfig(selections, work["id"], saved["version"], call_seconds=harness_seconds,
                         run_seconds=run_seconds, max_proposed_chains=max_proposed_chains)
    usage: list = []
    counter = iter(range(1, 1_000_000))
    lock = threading.Lock()

    def make_turn(*, model: str, effort: str | None, max_tokens: int, role: str, agent: str,
                  attested: bool = False):
        if model not in {item["model"] for item in snapshot["models"]}:
            raise ValueError("the requested model is not in the refreshed catalog")
        if effort is not None and effort not in _listed_efforts(snapshot, model):
            raise ValueError("the requested effort is not listed for this model")
        if type(max_tokens) is not int or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        selection = AdapterSelection(binding_id=binding.binding_id, catalog_id=issued.catalog_id,
                                     model_id=model, effort=effort)

        def turn(system: str, user: str) -> str:
            with lock:
                index = next(counter)
            call_id = f"{agent}-{index:05d}"
            entry = {"index": index, "role": role, "call_id": call_id, "model": model, "effort": effort,
                     "max_tokens": max_tokens, "system_bytes": len(system.encode("utf-8")),
                     "user_bytes": len(user.encode("utf-8")), "dispatched": False,
                     "provider_message_id": None, "observed_model": None, "request_id": None,
                     "input_tokens": None, "output_tokens": None, "cache_creation_input_tokens": None,
                     "cache_read_input_tokens": None, "usage_observed": False, "stop_reason": None,
                     "state": None, "failure": None}
            if guard is not None:
                guard.before_call(entry)  # may raise; nothing is sent
            request = MessageTurn(call_id=call_id, agent_id=agent, selection=selection, system=system,
                                  messages=({"role": "user", "content": user},), max_tokens=max_tokens)
            with lock:
                usage.append(entry)
            pieces = []
            terminal = None
            try:
                entry["dispatched"] = True
                for event in adapter.stream(request, issued, binding, explicit_action=True):
                    if isinstance(event, ProviderStarted):
                        entry.update(provider_message_id=event.provider_message_id,
                                     observed_model=event.observed_model, request_id=event.request_id)
                    elif isinstance(event, TextDelta):
                        pieces.append(event.text)
                    elif isinstance(event, UsageObserved):
                        entry.update(input_tokens=event.input_tokens, output_tokens=event.output_tokens,
                                     cache_creation_input_tokens=event.cache_creation_input_tokens,
                                     cache_read_input_tokens=event.cache_read_input_tokens,
                                     usage_observed=True)
                    elif isinstance(event, ProviderTerminal):
                        terminal = event
            except Exception as exc:  # noqa: BLE001 - adapter refusal before or during the stream
                entry["state"] = "refused"
                entry["failure"] = type(exc).__name__
                if entry["provider_message_id"] is None and not entry["usage_observed"]:
                    entry["dispatched"] = False if isinstance(exc, (ValueError, TypeError)) else "unknown"
                if guard is not None:
                    guard.after_call(entry)
                raise TurnFailed("refused", type(exc).__name__) from None
            if terminal is None:
                entry["state"] = "no_terminal"
            else:
                entry["state"], entry["stop_reason"] = terminal.state, terminal.stop_reason
                if terminal.failure is not None:
                    entry["failure"] = f"{terminal.failure.category}/{terminal.failure.detail_code}"
                    if terminal.failure.dispatch_effect == "not_sent":
                        entry["dispatched"] = False
            if guard is not None:
                guard.after_call(entry)  # may raise after a completed call
            if entry["state"] != "completed":
                raise TurnFailed(entry["state"], entry["failure"] or entry["stop_reason"])
            text = "".join(pieces)
            if not attested:
                return text
            if (entry["observed_model"] is None or entry["request_id"] is None
                    or entry["provider_message_id"] is None):
                # nothing the provider reported to attest: the harness records the call as unattested
                return text
            # served model, request id and message id exactly as the provider response reported them
            return ProviderReply(text=text, served_model=entry["observed_model"],
                                 provider_request_id=entry["request_id"],
                                 provider_message_id=entry["provider_message_id"])

        turn.critic_transport = dict(critic_transport)  # how this rig was built (audit 6, non-blocking 5)
        return turn

    turn = make_turn(model=model_id, effort=effort, max_tokens=max_tokens, role="critic", agent=agent_id)
    attested_turn = make_turn(model=model_id, effort=effort, max_tokens=max_tokens, role="critic", agent=agent_id,
                              attested=True)
    public_catalog = {"catalog_id": snapshot["catalog_id"], "source_catalog_id": snapshot["source_catalog_id"],
                      "fetched_at": snapshot["fetched_at"], "max_age_ms": snapshot["max_age_ms"],
                      "model": model_id, "listed_efforts": listed, "selection_version": saved["version"]}
    return ClaudeRig(config=config, turn=turn, usage=usage, model_id=model_id, effort=effort,
                     catalog=public_catalog, make_turn=make_turn, attested_turn=attested_turn,
                     critic_transport=dict(critic_transport))


__all__ = ["MAX_CALL_SECONDS", "ClaudeRig", "TurnFailed", "claude_rig"]
