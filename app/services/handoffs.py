"""Whole-artifact handoffs: readiness, delivery, receipt, use (US3, T046).

A handoff binds the producer execution/attempt, the exact artifact refs,
the receiver execution/input slot and the schema check. Producer success is
complete at readiness — it never waits on downstream receipt, so there is
no producer/consumer acknowledgment deadlock, and a later failure never
retroactively erases producer output. Delivery discloses the actually
supplied spans and every truncation; receipt is the receiver's separate
acknowledgment; observed use requires cited parts within the supplied
spans — a filename or hash alone is never full consumption (cited parts
must echo a supplied span exactly; spans are opaque here, so subset claims
belong to a structured-span layer). Availability,
access, use and causal influence are four different evidence levels: this
module proves at most "use" and mints no causal claim (runtime.md §5, R06).
Values are issued, never constructed; each transition applies exactly once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain.refs import DomainContractError, EntityRef

STATUSES = ("created", "ready", "delivered", "received", "used")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_ISSUE_TOKEN = object()


class HandoffError(ValueError):
    """A handoff creation or transition is invalid."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _ref(value, kind, label):
    try:
        result = EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise HandoffError(f"invalid {label} reference") from exc
    if result.kind != kind:
        raise HandoffError(f"invalid {label} reference kind")
    return result


def _text(value, label, maximum=128):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        raise HandoffError(f"{label} is out of bounds")
    return value


@dataclass(frozen=True, slots=True, init=False)
class Handoff:
    """One handoff's bound identity and separated evidence states."""

    handoff_id: str
    producer_execution_id: str
    producer_attempt_index: int
    artifact_refs: tuple[EntityRef, ...]
    receiver_execution_id: str
    receiver_input_slot: str
    schema_check_ref: EntityRef
    status: str
    producer_complete: bool
    manifest_ref: EntityRef | None
    # (artifact_index, span) pairs actually supplied at delivery
    supplied_spans: tuple[tuple[int, str], ...]
    truncations: tuple[str, ...]
    receiver_ack_ref: EntityRef | None
    cited_parts: tuple[tuple[int, str], ...]
    _issuer_token: object = field(repr=False, compare=False)


def _require(handoff) -> None:
    if (
        type(handoff) is not Handoff
        or getattr(handoff, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise HandoffError("a framework-issued handoff is required")


def _reissue(handoff: Handoff, **changes) -> Handoff:
    fields = {
        name: getattr(handoff, name)
        for name in Handoff.__slots__
        if name != "_issuer_token"
    }
    fields.update(changes)
    return _issue(Handoff, _issuer_token=_ISSUE_TOKEN, **fields)


def create_handoff(value) -> Handoff:
    """Bind one handoff exactly; nothing is delivered or consumed yet."""

    if type(value) is not dict or set(value) != {
        "handoff_id", "producer_execution_id", "producer_attempt_index",
        "artifact_refs", "receiver_execution_id", "receiver_input_slot",
        "schema_check_ref",
    }:
        raise HandoffError("expected the exact handoff object")
    for name in ("producer_execution_id", "receiver_execution_id"):
        item = value[name]
        if type(item) is not str or _UUID.fullmatch(item) is None:
            raise HandoffError(f"{name} is not a canonical UUID")
    attempt = value["producer_attempt_index"]
    if type(attempt) is not int or not 0 <= attempt <= 1_000:
        raise HandoffError("producer attempt index is out of bounds")
    refs_value = value["artifact_refs"]
    if type(refs_value) is not list or not 1 <= len(refs_value) <= 64:
        raise HandoffError("a handoff binds a bounded nonempty artifact list")
    refs = tuple(_ref(item, "artifact", "artifact") for item in refs_value)
    if len(set(refs)) != len(refs):
        raise HandoffError("a handoff never binds the same artifact twice")
    return _issue(
        Handoff,
        handoff_id=_text(value["handoff_id"], "handoff id"),
        producer_execution_id=value["producer_execution_id"],
        producer_attempt_index=attempt,
        artifact_refs=refs,
        receiver_execution_id=value["receiver_execution_id"],
        receiver_input_slot=_text(
            value["receiver_input_slot"], "receiver input slot",
        ),
        schema_check_ref=_ref(
            value["schema_check_ref"], "observation_contract", "schema check",
        ),
        status="created",
        producer_complete=False,
        manifest_ref=None,
        supplied_spans=(),
        truncations=(),
        receiver_ack_ref=None,
        cited_parts=(),
        _issuer_token=_ISSUE_TOKEN,
    )


def mark_ready(handoff, *, manifest_ref) -> Handoff:
    """Producer success: complete at readiness, never waiting on receipt."""

    _require(handoff)
    if handoff.status != "created":
        raise HandoffError("readiness applies exactly once")
    return _reissue(
        handoff,
        status="ready",
        producer_complete=True,
        manifest_ref=_ref(manifest_ref, "handoff", "manifest"),
    )


def _spans(value, label, bound) -> tuple[tuple[int, str], ...]:
    if type(value) is not list or not 1 <= len(value) <= 128:
        raise HandoffError(f"{label} are out of bounds")
    parsed = []
    for item in value:
        if type(item) is not dict or set(item) != {"artifact_index", "span"}:
            raise HandoffError(f"a {label} entry is malformed")
        index = item["artifact_index"]
        if type(index) is not int or not 0 <= index < bound:
            # Spans bind the exact artifacts of THIS handoff.
            raise HandoffError(f"a {label} entry is outside the bound artifacts")
        parsed.append((index, _text(item["span"], f"{label} span", 256)))
    return tuple(parsed)


def record_delivery(handoff, value) -> Handoff:
    """Record what was actually supplied — spans and truncations, explicitly."""

    _require(handoff)
    if handoff.status != "ready":
        raise HandoffError("delivery follows readiness exactly once")
    if type(value) is not dict or set(value) != {
        "supplied_spans", "truncations",
    }:
        raise HandoffError("expected the exact delivery object")
    truncations_value = value["truncations"]
    if type(truncations_value) is not list or len(truncations_value) > 32:
        raise HandoffError("truncations are out of bounds")
    truncations = []
    for item in truncations_value:
        if type(item) is not dict or set(item) != {"artifact_index", "note"}:
            raise HandoffError("a truncation entry is malformed")
        index = item["artifact_index"]
        if type(index) is not int or not 0 <= index < len(handoff.artifact_refs):
            raise HandoffError("a truncation entry is outside the bound artifacts")
        truncations.append((index, _text(item["note"], "truncation note", 1_024)))
    spans = _spans(
        value["supplied_spans"], "supplied span", len(handoff.artifact_refs),
    )
    covered = {index for index, _span in spans} | {
        index for index, _note in truncations
    }
    if covered != set(range(len(handoff.artifact_refs))):
        # Every bound artifact is either actually supplied or explicitly
        # truncated — nothing vanishes silently (runtime §5).
        raise HandoffError(
            "every bound artifact must be supplied or explicitly truncated"
        )
    return _reissue(
        handoff,
        status="delivered",
        supplied_spans=spans,
        truncations=tuple(truncations),
    )


def record_receipt(handoff, *, receiver_ack_ref) -> Handoff:
    """The receiver's separate acknowledgment; never inferred."""

    _require(handoff)
    if handoff.status != "delivered":
        raise HandoffError("a receipt follows delivery exactly once")
    return _reissue(
        handoff,
        status="received",
        receiver_ack_ref=_ref(
            receiver_ack_ref, "decision_record", "receiver acknowledgment",
        ),
    )


def record_use(handoff, *, cited_parts) -> Handoff:
    """Observed use: cited parts within the supplied spans, never a filename."""

    _require(handoff)
    if handoff.status != "received":
        raise HandoffError("use follows receipt exactly once")
    parts = _spans(cited_parts, "cited part", len(handoff.artifact_refs))
    supplied = set(handoff.supplied_spans)
    for part in parts:
        if part not in supplied:
            # Only what was actually supplied can have been used.
            raise HandoffError("a cited part is outside the supplied spans")
    return _reissue(handoff, status="used", cited_parts=parts)


def evidence_level(handoff) -> str:
    """The highest PROVEN level; causal influence is never minted here."""

    _require(handoff)
    return {
        "created": "none",
        "ready": "availability",
        "delivered": "availability",
        "received": "access",
        "used": "use",
    }[handoff.status]


__all__ = [
    "STATUSES",
    "Handoff",
    "HandoffError",
    "create_handoff",
    "evidence_level",
    "mark_ready",
    "record_delivery",
    "record_receipt",
    "record_use",
]
