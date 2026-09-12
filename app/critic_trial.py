"""Internal, explicitly controlled offline critic trials; no semantic scoring."""

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import Event, Lock, Thread
from time import monotonic

from .codex_critic import CodexCriticTransport
from .critic_audit import FrozenCall, Ledger, canonical, positive_seconds
from .critic_contract import (
    InputContractError, PreparedInput, ResponseContractError, parse_response, prepare_input,
)
from .generation_profiles import profile_for
from .model_catalog import ModelCatalog
from .model_selection import ModelSelection


@dataclass(frozen=True)
class RuntimeContext:
    data_dir: Path


def _validate_prepared(prepared):
    try:
        if type(prepared) is not PreparedInput:
            raise ValueError("exact PreparedInput required")
        rebuilt = prepare_input(prepared.purpose, json.loads(prepared.prompt)["input"])
        if prepared != rebuilt:
            raise ValueError("prepared fields differ")
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise InputContractError("invalid prepared critic input") from None


def _validate_selections(selections):
    if not isinstance(selections, ModelSelection) or not isinstance(selections.catalog, ModelCatalog):
        raise ValueError("ModelSelection and ModelCatalog are required")


def _current_selection(selections, work_id, version):
    _validate_selections(selections)
    with selections.store._connection() as db:
        return selections.for_request(db, work_id, version)


def freeze_call(prepared, selections, work_id, version, *, run_id, request_id,
                call_seconds, code_hashes) -> FrozenCall:
    _validate_prepared(prepared)
    seconds = positive_seconds(call_seconds)
    if (type(code_hashes) is not dict or not code_hashes
            or any(type(name) is not str or not name or type(digest) is not str
                   or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                   for name, digest in code_hashes.items())):
        raise ValueError("explicit code hashes must be nonempty names and lowercase SHA-256 values")
    selected = _current_selection(selections, work_id, version)
    profile = profile_for(prepared.purpose)
    # Constructor/property only: these declare code-owned configuration and do
    # not run preflight, discover storage, read accounts, or start a provider.
    runtime_profile = CodexCriticTransport(None, purpose=prepared.purpose).runtime_profile
    metadata = {
        "work_id": work_id, "selection_version": version, "call_seconds": seconds,
        "code_hashes": code_hashes,
        "instruction": {"purpose": profile.purpose.value, "version": profile.version,
                        "base_instructions": profile.base_instructions,
                        "developer_instructions": profile.developer_instructions,
                        "digest": profile.digest},
        "runtime_profile": runtime_profile,
        "runtime_evidence": "declared_not_preflight_confirmed", "actual_effort": None,
        "execution_backend": "offline-only",
    }
    return FrozenCall(request_id, run_id, prepared.purpose.value, prepared.candidate_id,
                      prepared.candidate_version, prepared.prompt,
                      canonical(json.loads(prepared.schema_json)),
                      canonical(json.loads(prepared.manifest_json)),
                      canonical(selected["selection"]), canonical(metadata))


class OfflineTransport:
    """Marker for trusted, controlled fixtures, not a hostile-Python sandbox."""

    def generate(self, prompt, schema, cancel_event, *, selection):
        raise NotImplementedError("supply a controlled offline test double")


@dataclass
class _Active:
    stop: Event = field(default_factory=Event)
    done: Event = field(default_factory=Event)
    deadline: float = 0
    result: object = None
    result_received: bool = False
    transport_error: bool = False
    audit_fault: bool = False


_TERMINAL = frozenset({"completed", "invalid", "cancelled", "timed_out", "interrupted"})


def _no_symlinks(path):
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("an absolute path without parent traversal is required")
    if any(component.is_symlink() for component in (path, *path.parents)):
        raise ValueError("runtime and audit paths must not contain symlinks")


class OfflineRunner:
    """One local daemon worker per call, using caller-supplied offline fixtures.

    Cancellation/deadlines stop local publication; they do not confirm remote
    termination. Quarantine lasts for this instance. Recovery is a separate
    explicit Ledger operation, only after a caller confirms old workers absent.
    """

    def __init__(self, ledger, runtime_root, selections):
        if not isinstance(ledger, Ledger):
            raise ValueError("an explicit Ledger is required")
        _validate_selections(selections)
        self.ledger, self.runtime_root, self.selections = ledger, Path(runtime_root), selections
        self._validate_paths()
        self._lock, self._active_lock = Lock(), Lock()
        self._active = {}
        self._quarantined = False

    def _validate_paths(self):
        audit = self.ledger.path.parent
        _no_symlinks(self.runtime_root)
        _no_symlinks(self.ledger.path)
        if (audit == self.runtime_root or audit in self.runtime_root.parents
                or self.runtime_root in audit.parents):
            raise ValueError("audit and runtime directories must be separate trees")

    def _quarantine(self, active=None):
        # The caller holds _active_lock; no nested acquisition or provider wait.
        self._quarantined = True
        if active is not None:
            active.stop.set()

    def cancel(self, request_id) -> bool:
        with self._active_lock:
            active = self._active.get(request_id)
            try:
                changed = self.ledger.cancel(request_id)
            except BaseException:
                # A shared-journal fault invalidates publication for every
                # active request, even when cancellation named another ID.
                for current in self._active.values():
                    current.audit_fault = True
                    self._quarantine(current)
                self._quarantine(active)
                raise
            if changed and active is not None:
                # The terminal cancellation has committed before any signal.
                self._quarantine(active)
            return changed

    def _validate_call(self, call, prepared):
        _validate_prepared(prepared)
        if (type(call) is not FrozenCall
                or (call.purpose, call.candidate_id, call.candidate_version, call.prompt,
                    call.schema_json, call.manifest_json)
                != (prepared.purpose.value, prepared.candidate_id, prepared.candidate_version,
                    prepared.prompt, canonical(json.loads(prepared.schema_json)),
                    canonical(json.loads(prepared.manifest_json)))):
            raise InputContractError("frozen call does not match prepared input")
        metadata = json.loads(call.metadata_json)
        if type(metadata) is not dict or metadata.get("execution_backend") != "offline-only":
            raise ValueError("only explicit offline-only calls are supported")
        seconds = positive_seconds(metadata.get("call_seconds"))
        selected = _current_selection(self.selections, metadata.get("work_id"), metadata.get("selection_version"))
        if canonical(selected["selection"]) != call.selection_json:
            raise ValueError("current selection differs from frozen selection")
        self._validate_paths()
        return seconds

    def _runtime_context(self, call):
        self._validate_paths()
        parent = self.runtime_root / call.run_id / call.purpose
        path = parent / call.request_id
        _no_symlinks(path)
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _no_symlinks(path)
        path.mkdir(mode=0o700, exist_ok=False)
        _no_symlinks(path)
        return RuntimeContext(path)

    @staticmethod
    def _stopped(active):
        return active.stop.is_set() or monotonic() >= active.deadline

    def _worker(self, call, active, factory):
        try:
            if self._stopped(active):
                return
            context = self._runtime_context(call)
            if self._stopped(active):
                return
            transport = factory(context)
            if not isinstance(transport, OfflineTransport):
                raise TypeError("a controlled OfflineTransport is required")
            if self._stopped(active):
                return
            active.result = transport.generate(call.prompt, json.loads(call.schema_json), active.stop,
                                               selection=json.loads(call.selection_json))
            active.result_received = True
        except Exception:
            active.transport_error = True
        finally:
            try:
                with self._active_lock:
                    if self._stopped(active):
                        active.result = None
                        try:
                            self.ledger.observe(call.request_id, "late_worker_finished", {
                                "result_received": active.result_received, "application": "discarded",
                                "remote_stop": "unconfirmed", "raw_retention": "not_retained_in_offline_runner",
                            })
                        except BaseException:
                            # No fabricated durable observation and no exception text in the journal.
                            active.audit_fault = True
                            self._quarantine(active)
            finally:
                active.done.set()

    @staticmethod
    def _classify(active, call, prepared):
        result = active.result
        if active.transport_error:
            return "invalid", {"reason": "transport_or_fixture_error", "score": None}
        selected_model = json.loads(call.selection_json)["model"]
        if (type(result) is not dict or set(result) != {"text", "model"}
                or type(result["text"]) is not str or result["model"] != selected_model):
            return "invalid", {"reason": "transport_contract_or_model_mismatch", "score": None}
        raw = result["text"]
        details = {"model": result["model"], "actual_effort": None, "semantic": "not_checked", "score": None}
        try:
            encoded = raw.encode("utf-8")
        except UnicodeEncodeError:
            details.update(output_contract="model_output_invalid", raw_omitted="invalid_unicode",
                           raw_sha256=None, raw_bytes=None)
            return "completed", details
        details.update(raw_sha256=sha256(encoded).hexdigest(), raw_bytes=len(encoded))
        if len(encoded) > 64000:
            details.update(output_contract="model_output_invalid", raw_omitted="exceeds_64000_bytes")
        else:
            details["raw_final"] = raw
            try:
                details["parsed"] = parse_response(prepared, raw)
                details["output_contract"] = "valid"
            except ResponseContractError:
                details["output_contract"] = "model_output_invalid"
        return "completed", details

    def _read_terminal(self, request_id, active):
        if active.audit_fault:
            raise RuntimeError("offline audit failure; inspect the durable journal before recovery")
        record = self.ledger.get(request_id)
        if record["state"] not in _TERMINAL:
            raise RuntimeError("offline audit has no committed terminal state")
        if record["state"] in {"cancelled", "timed_out"}:
            self._quarantine(active)
        return record

    def _timeout(self, call, active):
        self._quarantine(active)
        self.ledger.finish(call.request_id, "timed_out", {"score": None, "remote_stop": "unconfirmed"})
        return self._read_terminal(call.request_id, active)

    def run(self, call, prepared, transport_factory):
        with self._lock:
            with self._active_lock:
                if self._quarantined:
                    raise RuntimeError("offline runner is quarantined; old worker absence is unconfirmed")
            seconds = self._validate_call(call, prepared)
            active, reserving = None, True
            try:
                with self._active_lock:
                    # Validation may overlap a cancellation journal fault.
                    # Serialize this final gate, reserve, registration and intent.
                    if self._quarantined:
                        raise RuntimeError("offline runner is quarantined; dispatch stopped")
                    self.ledger.reserve(call)
                    reserving = False
                    active = _Active()
                    self._active[call.request_id] = active
                    if not self.ledger.begin(call.request_id):
                        return self._read_terminal(call.request_id, active)
                    remaining = self.ledger.remaining(call.run_id)
                    active.deadline = monotonic() + min(seconds, remaining)
                    if remaining <= 0:
                        return self._timeout(call, active)
                worker = Thread(target=lambda: self._worker(call, active, transport_factory), daemon=True)
                worker.start()
                while True:
                    with self._active_lock:
                        if active.audit_fault:
                            raise RuntimeError("offline audit failure; local publication stopped")
                        if active.stop.is_set():
                            return self._read_terminal(call.request_id, active)
                        if monotonic() >= active.deadline:
                            return self._timeout(call, active)
                        if active.done.is_set():
                            state, details = self._classify(active, call, prepared)
                            self.ledger.finish(call.request_id, state, details)
                            return self._read_terminal(call.request_id, active)
                    active.done.wait(0.01)
            except BaseException as exc:
                # Only reservation precondition ValueErrors are ordinary refusal.
                # Every other fault, including preparation/start/readback, stops
                # local publication and blocks this runner's subsequent dispatch.
                if not (reserving and isinstance(exc, ValueError)):
                    with self._active_lock:
                        self._quarantine(active)
                raise
            finally:
                with self._active_lock:
                    self._active.pop(call.request_id, None)
