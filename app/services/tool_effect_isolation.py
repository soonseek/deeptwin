"""Tool effect isolation for paired re-evaluation (US6, growth.md §5 and G-14).

A prior-work queue can contain items whose original run performed an external-effect
tool call — a send or a publication, recorded in the runtime ledger as a ToolCall.
Re-evaluating that item must never perform the effect again. The plan's
`tool_effect_policy` (an `observation_contract` record frozen with the plan) names,
per tool and version, the only boundary an isolated run may use:

- `replay`: the recorded call's settled result is handed back, bound to the exact
  digest of the original ToolCall record. The isolated call's declared inputs must
  be the recorded call's; a changed call cannot be answered by the old result.
- `isolated_sink`: the call is delivered to a sink inside the isolated run's own
  vault (the would-be inputs are kept there; nothing leaves).

Every boundary must carry the approval of exactly that boundary (a
`decision_record` whose content names the boundary's digest and `approved`).

An item is **not comparable** — with its stated reason, never a live send — when the
queue's claim about its past effect does not match the ledger (the ToolCall record
digest differs, the call is missing or not an external effect), when the policy
cannot be read or has no boundary for the tool, when the boundary is not approved,
when replay has no settled result to hand back, or when an isolated run calls a tool
in a way no boundary admits.

Structure: the paired runner never builds a dispatcher, an attempt transport, a
worker channel or a run-approval service for an isolated run. The only tool
capability an isolated run's handlers receive is the `IsolatedToolEffects` opened
here, and it has no path out of the isolated vault: it seals replayed results and
sink receipts as records of that vault and nothing else. (A gated external tool
graph cannot even be scheduled there: the scheduler refuses one without a
per-attempt approval transport.) This module does not import the extension
transport.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from ..domain.refs import DomainContractError, EntityRef, canonical_json
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, StorageError
from ..runtime.ledger import TOOL_APPROVAL_EFFECTS, RuntimeLedger, tool_inputs_digest

POLICY_SCHEMA = "tool-effect-policy-v1"
APPROVAL_SCHEMA = "tool-effect-boundary-approval-v1"
REPLAY_SCHEMA = "tool-effect-replay-v1"
SINK_SCHEMA = "tool-effect-sink-v1"
BOUNDARIES = frozenset({"replay", "isolated_sink"})
PAST_EFFECTS_KEY = "past_tool_effects"
MAX_BOUNDARIES = 32
MAX_PAST_EFFECTS = 8
MAX_CALLS_PER_RUN = 8
_STAMP = "1970-01-01T00:00:00.000000Z"
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_BINDING_KEYS = frozenset({"run_id", "attempt_id", "tool_call_id", "tool_call_sha256",
                           "tool_id", "version", "effect_class"})


class ToolEffectIsolationError(ValueError):
    """A policy, approval or binding cannot be built as presented."""


class NotComparable(Exception):
    """The item cannot be compared under the plan's tool effect policy; `reason` says why."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _digest(value) -> str:
    return sha256(canonical_json(value)).hexdigest()


def tool_call_record_digest(snapshot: dict) -> str:
    """The digest of one ToolCall record exactly as the ledger reads it back."""
    return _digest(snapshot)


def boundary_digest(boundary: dict) -> str:
    """The digest an approval of this boundary names (the boundary without its approval)."""
    return _digest({key: value for key, value in boundary.items() if key != "approval_ref"})


def _boundary(value) -> dict:
    if type(value) is not dict:
        raise ToolEffectIsolationError("a boundary is an object")
    kind = value.get("boundary")
    expected = {"tool_id", "version", "effect_class", "boundary"}
    if kind == "isolated_sink":
        expected.add("sink_id")
    if kind not in BOUNDARIES or set(value) - {"approval_ref"} != expected:
        raise ToolEffectIsolationError("a boundary names its tool, effect and one supported boundary")
    for name in expected - {"boundary"}:
        if type(value[name]) is not str or _TOKEN.fullmatch(value[name]) is None:
            raise ToolEffectIsolationError(f"boundary {name} is out of bounds")
    if value["effect_class"] not in TOOL_APPROVAL_EFFECTS:
        raise ToolEffectIsolationError("a boundary isolates an external or instance-critical effect")
    if "approval_ref" in value:
        try:
            approval = EntityRef.from_dict(value["approval_ref"])
        except (DomainContractError, TypeError) as exc:
            raise ToolEffectIsolationError("a boundary approval is an exact reference") from exc
        if approval.kind != "decision_record":
            raise ToolEffectIsolationError("a boundary approval is a decision record")
    return dict(value)


def policy_content(boundaries) -> dict:
    """The exact content of a tool effect policy record (validated)."""
    if type(boundaries) is not list or len(boundaries) > MAX_BOUNDARIES:
        raise ToolEffectIsolationError("the boundaries are out of bounds")
    checked = [_boundary(item) for item in boundaries]
    keys = [(item["tool_id"], item["version"]) for item in checked]
    if len(set(keys)) != len(keys):
        raise ToolEffectIsolationError("one boundary per tool and version")
    return {"schema_version": POLICY_SCHEMA, "boundaries": checked}


def approval_content(boundary: dict, decision: str) -> dict:
    """The exact content of one boundary approval decision."""
    if decision not in {"approved", "rejected"}:
        raise ToolEffectIsolationError("a boundary decision is approved or rejected")
    return {"schema_version": APPROVAL_SCHEMA, "boundary_sha256": boundary_digest(_boundary(boundary)),
            "decision": decision}


def _put(domain, kind, content, *, actor_ref, access_policy_ref, retention_policy_ref, created_at_utc):
    record = ImmutableRecord.create(
        kind=kind, id=str(uuid4()), version=1, created_at_utc=created_at_utc, actor_ref=actor_ref,
        parent_refs=(), purpose="operational", access_policy_ref=access_policy_ref,
        retention_policy_ref=retention_policy_ref, content=content)
    domain.put(record)
    return record.ref


def record_boundary_approval(domain_store, boundary, decision, **headers) -> EntityRef:
    """Record one decision on one isolation boundary (its actor is the record's actor)."""
    if type(domain_store) is not DomainStore:
        raise ToolEffectIsolationError("an exact domain store is required")
    return _put(domain_store, "decision_record", approval_content(boundary, decision), **headers)


def record_tool_effect_policy(domain_store, boundaries, **headers) -> EntityRef:
    """Record the policy a comparison plan freezes as its `tool_effect_policy`."""
    if type(domain_store) is not DomainStore:
        raise ToolEffectIsolationError("an exact domain store is required")
    return _put(domain_store, "observation_contract", policy_content(boundaries), **headers)


def recorded_effect_bindings(ledger, run_id) -> list[dict]:
    """The queue bindings of every external-effect ToolCall one original run recorded:
    the call's identities, tool, effect and the digest of its exact ledger record."""
    if type(ledger) is not RuntimeLedger:
        raise ToolEffectIsolationError("the exact runtime ledger of the original run is required")
    bindings = []
    for attempt in ledger.attempts_for_run(run_id):
        for call in ledger.tool_calls_for_attempt(attempt["spec"]["attempt_id"]):
            if call["effect_class"] not in TOOL_APPROVAL_EFFECTS:
                continue
            bindings.append({"run_id": run_id, "attempt_id": call["attempt_id"],
                             "tool_call_id": call["tool_call_id"],
                             "tool_call_sha256": tool_call_record_digest(call),
                             "tool_id": call["tool_id"], "version": call["version"],
                             "effect_class": call["effect_class"]})
    return bindings


@dataclass(frozen=True, slots=True)
class _Recorded:
    binding: dict
    state: str
    inputs_digest: str
    output: object  # the recorded reply output, or None when there is none to replay
    replay_gap: str | None  # why no result can be replayed, else None


class ToolEffectSource:
    """The caller's vault (where the plan's policy and its approvals live) and the
    runtime ledger of the original runs (where the past ToolCalls are recorded).
    Read only: nothing here writes to either."""

    __slots__ = ("_domain", "_ledger")

    def __init__(self):
        raise TypeError("Use ToolEffectSource.build")

    @classmethod
    def build(cls, *, domain_store, ledger):
        if type(domain_store) is not DomainStore:
            raise ToolEffectIsolationError("an exact domain store is required")
        if type(ledger) is not RuntimeLedger or ledger._domain is not domain_store:
            raise ToolEffectIsolationError("the original runs' ledger over the same store is required")
        source = object.__new__(cls)
        source._domain, source._ledger = domain_store, ledger
        return source

    def policy(self, plan):
        """{(tool_id, version): boundary} from the plan's frozen policy, or a reason."""
        try:
            content = self._domain.get(plan.tool_effect_policy).body["content"]
        except (StorageError, DomainContractError, KeyError):
            return None, "the plan's tool effect policy could not be read"
        if type(content) is not dict or content.get("schema_version") != POLICY_SCHEMA:
            return None, "the plan's tool effect policy is not a tool effect policy"
        try:
            checked = policy_content(content.get("boundaries"))
        except ToolEffectIsolationError as error:
            return None, f"the plan's tool effect policy is invalid ({error})"
        return {(item["tool_id"], item["version"]): item for item in checked["boundaries"]}, None

    def approved(self, boundary) -> str | None:
        """None when the boundary carries the approval of exactly itself, else why not."""
        label = f"{boundary['boundary']} boundary for {boundary['tool_id']} {boundary['version']}"
        if "approval_ref" not in boundary:
            return f"the {label} is not approved"
        try:
            record = self._domain.get(EntityRef.from_dict(boundary["approval_ref"]))
        except (StorageError, DomainContractError, KeyError, TypeError):
            return f"the approval of the {label} could not be read"
        content = record.body.get("content")
        if (type(content) is not dict or content.get("schema_version") != APPROVAL_SCHEMA
                or content.get("boundary_sha256") != boundary_digest(boundary)):
            return f"the approval does not name the {label}"
        if content.get("decision") != "approved":
            return f"the {label} was not approved (decision {content.get('decision')})"
        return None

    def recorded(self, binding) -> _Recorded:
        """The past call the queue item names, re-read from the ledger and checked
        against the item's binding (the record digest included)."""
        if type(binding) is not dict or set(binding) != _BINDING_KEYS:
            raise NotComparable("a past tool effect binding is malformed")
        for name in ("run_id", "attempt_id", "tool_call_id"):
            if type(binding[name]) is not str or _UUID.fullmatch(binding[name]) is None:
                raise NotComparable("a past tool effect binding is malformed")
        if type(binding["tool_call_sha256"]) is not str or _SHA.fullmatch(binding["tool_call_sha256"]) is None:
            raise NotComparable("a past tool effect binding is malformed")
        label = f"{binding['tool_id']} {binding['version']}"
        try:
            attempts = {item["spec"]["attempt_id"] for item in self._ledger.attempts_for_run(binding["run_id"])}
            calls = (self._ledger.tool_calls_for_attempt(binding["attempt_id"])
                     if binding["attempt_id"] in attempts else [])
        except (KeyError, ValueError, TypeError):
            calls = []
        found = [call for call in calls if call["tool_call_id"] == binding["tool_call_id"]]
        if len(found) != 1:
            raise NotComparable(f"the recorded {label} call is not in the original run's ledger")
        call = found[0]
        if tool_call_record_digest(call) != binding["tool_call_sha256"]:
            raise NotComparable(f"replay binding mismatch: the recorded {label} call's record digest "
                                "differs from the one the queue froze")
        if (call["tool_id"], call["version"], call["effect_class"]) != (
                binding["tool_id"], binding["version"], binding["effect_class"]):
            raise NotComparable(f"replay binding mismatch: the recorded call is not {label}")
        if call["effect_class"] not in TOOL_APPROVAL_EFFECTS:
            raise NotComparable(f"the recorded {label} call is not an external effect")
        output, gap = None, None
        if call["state"] != "succeeded" or call["result_ref"] is None:
            gap = f"the recorded {label} call has no settled result to replay (state {call['state']})"
        else:
            try:
                content = self._domain.get(EntityRef.from_dict(call["result_ref"])).body["content"]
            except (StorageError, DomainContractError, KeyError, TypeError):
                content = None
            if type(content) is not dict or "output" not in content:
                gap = f"the recorded {label} result could not be read"
            elif content.get("artifacts"):
                gap = f"the recorded {label} result carries artifacts; replay hands back no artifact"
            else:
                output = content["output"]
        return _Recorded(dict(binding), call["state"], tool_inputs_digest(call["artifact_inputs"]), output, gap)


@dataclass(frozen=True, slots=True)
class ItemEffects:
    """One queue item's verified past calls and the boundaries admitted for it."""

    boundaries: tuple  # ((tool_id, version), boundary) pairs, each approved
    recorded: tuple    # _Recorded values in the item's order
    unavailable: str | None = None  # why no call at all is admitted (no policy bound)
    refused: tuple = ()  # ((tool_id, version), why its boundary is not admitted)

    @property
    def past_effects(self) -> list[dict]:
        return [dict(item.binding) for item in self.recorded]

    def open(self, domain, side_label) -> IsolatedToolEffects:
        effects = object.__new__(IsolatedToolEffects)
        effects._domain = domain
        effects._side = side_label
        effects._item = self
        effects._used = set()
        effects._log = []
        effects._refusal = None
        return effects


def prepare_item_effects(source, plan, item, policy_cache) -> ItemEffects:
    """Verify one item's past effects against the ledger and the plan's policy before
    any isolated run; raises `NotComparable` with the reason when it cannot be compared."""

    past = item.get(PAST_EFFECTS_KEY, [])
    if type(past) is not list or len(past) > MAX_PAST_EFFECTS:
        raise NotComparable("the item's past tool effects are out of bounds")
    if source is None:
        if past:
            raise NotComparable("the item has past external effects and no isolation boundary is bound")
        return ItemEffects((), (), "no tool effect policy is bound to this round")
    if "policy" not in policy_cache:
        policy_cache["policy"] = source.policy(plan)
    policy, policy_gap = policy_cache["policy"]
    if policy is None:
        if past:
            raise NotComparable(policy_gap)
        return ItemEffects((), (), policy_gap)
    recorded = tuple(source.recorded(binding) for binding in past)
    admitted, refused = [], []
    for key, boundary in sorted(policy.items()):
        gap = source.approved(boundary)
        if gap is None:
            admitted.append((key, boundary))
            continue
        refused.append((key, gap))
        if any((item.binding["tool_id"], item.binding["version"]) == key for item in recorded):
            raise NotComparable(gap)
    allowed = dict(admitted)
    for entry in recorded:
        key = (entry.binding["tool_id"], entry.binding["version"])
        boundary = allowed.get(key)
        if boundary is None:
            raise NotComparable(f"no approved isolation boundary for {key[0]} {key[1]}")
        if boundary["effect_class"] != entry.binding["effect_class"]:
            raise NotComparable(f"the boundary for {key[0]} {key[1]} names another effect class")
        if boundary["boundary"] == "replay" and entry.replay_gap is not None:
            raise NotComparable(entry.replay_gap)
    return ItemEffects(tuple(admitted), recorded, None, tuple(refused))


def _declarations(inputs):
    if type(inputs) is not tuple or len(inputs) > 8:
        raise NotComparable("the isolated call's inputs are out of bounds")
    declared = []
    for index, value in enumerate(inputs):
        if (type(value) is not tuple or len(value) != 3 or type(value[0]) is not str
                or type(value[1]) is not str or type(value[2]) is not bytes):
            raise NotComparable("an isolated call input is (role, media type, bytes)")
        role, media_type, payload = value
        declared.append({"ordinal": index, "media_type": media_type, "declared_size": len(payload),
                         "sha256": sha256(payload).hexdigest(), "role": role})
    return declared


class IsolatedToolEffects:
    """The only tool capability of one isolated run: every call is answered by an
    approved boundary inside this run's vault, or refused (the item is then not
    comparable). There is no transport, channel or worker behind it."""

    __slots__ = ("_domain", "_item", "_log", "_refusal", "_side", "_used")

    def __init__(self):
        raise TypeError("Opened by the paired runner only")

    @property
    def refusal(self) -> str | None:
        return self._refusal

    @property
    def log(self) -> tuple:
        return tuple(dict(entry) for entry in self._log)

    def _refuse(self, reason):
        if self._refusal is None:
            self._refusal = reason
        raise NotComparable(reason)

    def invoke(self, tool_id, version, inputs) -> EntityRef:
        """One tool call of this isolated run; returns the record sealed in this vault."""
        if self._refusal is not None:
            raise NotComparable(self._refusal)
        if self._item.unavailable is not None:
            self._refuse(self._item.unavailable)
        if len(self._log) >= MAX_CALLS_PER_RUN:
            self._refuse("the isolated run made more tool calls than admitted")
        key = (tool_id, version)
        boundary = dict(self._item.boundaries).get(key)
        if boundary is None:
            self._refuse(dict(self._item.refused).get(key, f"no approved isolation boundary for {tool_id} {version}"))
        declared = _declarations(inputs)
        digest = tool_inputs_digest(declared)
        roots = self._domain.roots()
        headers = {"actor_ref": roots.actor, "access_policy_ref": roots.access_policy,
                   "retention_policy_ref": roots.retention_policy, "created_at_utc": _STAMP}
        entry = {"tool_id": tool_id, "version": version, "effect_class": boundary["effect_class"],
                 "boundary": boundary["boundary"], "inputs_digest": digest}
        if boundary["boundary"] == "replay":
            candidates = [index for index, item in enumerate(self._item.recorded)
                          if (item.binding["tool_id"], item.binding["version"]) == key and index not in self._used]
            if not candidates:
                self._refuse(f"no recorded {tool_id} {version} call is left to replay")
            index = candidates[0]
            recorded = self._item.recorded[index]
            if recorded.inputs_digest != digest:
                self._refuse(f"the isolated {tool_id} {version} call's inputs differ from the recorded "
                             "call; replaying its result would misstate the effect")
            self._used.add(index)
            content = {"schema_version": REPLAY_SCHEMA, "boundary": "replay", "tool_id": tool_id,
                       "version": version, "effect_class": boundary["effect_class"],
                       "replayed_tool_call_id": recorded.binding["tool_call_id"],
                       "replayed_tool_call_sha256": recorded.binding["tool_call_sha256"],
                       "inputs_digest": digest, "output": recorded.output}
            entry.update({"tool_call_id": recorded.binding["tool_call_id"],
                          "tool_call_sha256": recorded.binding["tool_call_sha256"]})
        else:
            blobs = []
            for value in inputs:  # the would-be inputs stay in this isolated vault only
                self._domain.put_blob(value[2], purpose="operational")
                blobs.append(sha256(value[2]).hexdigest())
            content = {"schema_version": SINK_SCHEMA, "boundary": "isolated_sink",
                       "sink_id": boundary["sink_id"], "tool_id": tool_id, "version": version,
                       "effect_class": boundary["effect_class"], "inputs": declared,
                       "inputs_digest": digest, "kept_input_sha256": blobs,
                       "delivered": "isolated_sink_only"}
            entry["sink_id"] = boundary["sink_id"]
        ref = _put(self._domain, "artifact", content, **headers)
        entry["record_sha256"] = ref.sha256
        self._log.append(entry)
        return ref


__all__ = [
    "APPROVAL_SCHEMA",
    "BOUNDARIES",
    "PAST_EFFECTS_KEY",
    "POLICY_SCHEMA",
    "IsolatedToolEffects",
    "ItemEffects",
    "NotComparable",
    "ToolEffectIsolationError",
    "ToolEffectSource",
    "approval_content",
    "boundary_digest",
    "policy_content",
    "prepare_item_effects",
    "record_boundary_approval",
    "record_tool_effect_policy",
    "recorded_effect_bindings",
    "tool_call_record_digest",
]
