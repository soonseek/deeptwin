"""The owner's common-work target: a model-drafted work model and its human confirmation.

FR-003: an exact, confirmed common-work target precedes any design generation. A draft
comes from one explicit, owner-commanded model turn over the exact work revision's text
(`GenerationPurpose.WORK_UNDERSTANDING`). The model contributes only the work's meaning:
goals, deliverables, completion conditions, authorities, risks, unknowns and the
recommended shape with its rationale. The framework sets every identity and source
reference itself, admits the result only through `WorkModel.from_untrusted`, and seals it
as one immutable `work_model` record per command. A replayed command never calls again.

Confirmation is a separate owner act over one exact draft: `accepted` binds all six
dimensions (`confirm_work_model`) and seals the `work-model-confirmation-v1` decision;
`rejected` records the refusal. Either way `approval.decided` is emitted in the same
transaction. Nothing here designs, runs or approves an environment.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from functools import wraps
from uuid import NAMESPACE_URL, uuid5

from ..domain.public_events import _append_event_in_transaction
from ..domain.refs import EntityRef, ObjectRef, canonical_json, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, _writer
from ..generation_profiles import GenerationPurpose, profile_for
from .claude_connection import CHOICE_SCHEMA
from .design import (
    CONFIRMED_DIMENSIONS,
    WORK_MODEL_CONFIRMATION_SCHEMA_VERSION,
    WORK_MODEL_SCHEMA_VERSION,
    ConfirmedWorkTarget,
    WorkModelContractError,
    confirm_work_model,
)
from .design_persistence import decode_design_refs, encode_design_refs
from .owner_auth import OwnerAuthError, PersistentOwnerAuthority
from .run_approvals import _authenticate_owner, _owner_actor_ref

__all__ = ["PersistentWorkModels", "WorkModelServiceError"]

DRAFT_SCHEMA = "work-model-draft-command-v1"
CONFIRM_SCHEMA = "work-model-confirm-command-v1"
CONFIRMATION_RECORD_SCHEMA = "work-model-confirmation-record-v1"
MAX_OUTPUT_TOKENS = 8_000
MAX_RESPONSE_CHARS = 262_144
MAX_PROMPT_READING_CHARS = 120_000  # the owner's readings given to one understanding turn, in total
CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "conflict",
                   "unavailable", "provider_unavailable", "model_output_invalid", "sources_required"})

# The model writes only the work's meaning; the framework owns the rest.
_MODEL_FIELDS = ("goals", "deliverables", "completion_conditions", "authorities", "risks",
                 "unknowns", "suitability")
_OUTPUT_SCHEMA = (
    'Return exactly one JSON object {"work_model": {...}} and nothing else (no markdown, no '
    "commentary). The work_model has exactly these fields: goals (1-32 distinct strings); "
    "deliverables (1-64 of {deliverable_id, description, media_types (1-16 MIME types such as "
    "text/markdown or application/pdf), min_items, max_items, max_total_bytes}, with "
    "0 <= min_items <= max_items <= 1000); completion_conditions (1-64 distinct observable "
    "strings); authorities (0-128 of {authority_id, capability (a dotted lowercase id such as "
    "browser.read), scope, effect: read|write|external_effect|human_approval}); risks (0-128 "
    "of {risk_id, description, severity: low|medium|high|critical, mitigation_required "
    "(boolean)}); unknowns (0-128 of {unknown_id, question, impact: "
    "no_effect|design|authority|safety, status: resolved|acknowledged|blocking}); "
    "suitability {recommended_shape: single_agent|deterministic|multi_agent|human_only, "
    "rationale}. Identifiers are lowercase words joined by - or _ (for example "
    "final-script). State only what the work text supports; record anything it leaves open "
    "as an unknown instead of guessing, marking it blocking only when design cannot proceed "
    "without the answer. Write in the language of the work text."
)


class WorkModelServiceError(ValueError):
    """Closed codes; storage and provider detail never leak."""

    def __init__(self, code="invalid_input"):
        if code not in CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (WorkModelServiceError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage/provider errors must not disclose detail
            raise WorkModelServiceError("unavailable") from None

    return invoke


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _command(payload, schema, fields) -> dict:
    if (type(payload) is not dict or set(payload) != {"schema_version", "command_id", *fields}
            or payload["schema_version"] != schema):
        raise WorkModelServiceError("invalid_input")
    try:
        command_id = uuid_string(payload["command_id"])
    except (TypeError, ValueError):
        raise WorkModelServiceError("invalid_input") from None
    return {"command_id": command_id, **{name: payload[name] for name in fields}}


def _ref(value, kind) -> EntityRef:
    try:
        ref = EntityRef.from_dict(value)
    except Exception:  # noqa: BLE001 - any malformed ref is plain invalid input
        raise WorkModelServiceError("invalid_input") from None
    if ref.kind != kind:
        raise WorkModelServiceError("invalid_input")
    return ref


def render_work_model_prompt(text: str, sources=()) -> tuple[str, str]:
    """The deterministic (system, user) pair for one work-understanding turn.

    `sources` is given only when the owner read at least one retained original
    (source_readings.py): each source then appears with its reading state — `not_read`,
    `complete`, `partial` (with what was not read) or `unreadable` — and only the text the
    reading actually kept. Without any reading the prompt is the revision text alone."""

    profile = profile_for(GenerationPurpose.WORK_UNDERSTANDING)
    system = f"{profile.base_instructions}\n{profile.developer_instructions}\n{_OUTPUT_SCHEMA}"
    revision = {"text": text}
    if sources:
        revision["sources"] = list(sources)
        system += (" The work_revision.sources list names each retained original with its reading state; "
                   "use only the text given, and record anything a not_read, partial or unreadable "
                   "original leaves open as an unknown.")
    return system, canonical_json({"work_revision": revision}).decode("utf-8")


def admit_work_model(raw, *, work_model_id: str, work_revision_ref: EntityRef, source_refs):
    """Admit a model's answer as a work model the framework completes; any deviation is
    `model_output_invalid`, never a partially trusted draft."""

    try:
        if type(raw) is not str or not 1 <= len(raw) <= MAX_RESPONSE_CHARS:
            raise ValueError("unbounded")
        value = json.loads(raw)
        if type(value) is not dict or set(value) != {"work_model"}:
            raise ValueError("not the exact wrapper")
        authored = value["work_model"]
        if type(authored) is not dict or set(authored) != set(_MODEL_FIELDS):
            raise ValueError("not the exact authored field set")
        suitability = authored["suitability"]
        if type(suitability) is not dict or set(suitability) != {"recommended_shape", "rationale"}:
            raise ValueError("not the exact suitability")
        sources = [dict(item) for item in source_refs]
        return confirm_work_model({
            **authored,
            "schema_version": WORK_MODEL_SCHEMA_VERSION,
            "work_model_id": work_model_id,
            "version": 1,
            "work_revision_ref": work_revision_ref.as_dict(),
            "semantic_origin": "work_understanding",
            # the model reads the revision text only; its evidence is the revision's own
            # retained originals, which it can cite but never widen
            "suitability": {**suitability, "evidence_refs": sources},
            "source_refs": sources,
        }, None)
    except (ValueError, TypeError, KeyError, RecursionError, WorkModelContractError):
        raise WorkModelServiceError("model_output_invalid") from None


class PersistentWorkModels:
    """Owner-commanded drafts and confirmations over the actual domain store."""

    def __init__(self, domain_store, owner_authority, executor):
        if type(domain_store) is not DomainStore:
            raise TypeError("Exact DomainStore required")
        if type(owner_authority) is not PersistentOwnerAuthority or owner_authority._domain is not domain_store:
            raise TypeError("Owner authority must share the actual domain store")
        self._domain = domain_store
        self._owner = owner_authority
        self._executor = executor  # a bound ClaudeRunExecutor, or None: drafting unavailable

    # --- reads -------------------------------------------------------------

    def _record(self, db, roots, kind, record_id):
        row = db.execute("SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind=? AND id=? "
                         "ORDER BY version DESC LIMIT 1", (roots.genesis.id, kind, record_id)).fetchone()
        if row is None:
            return None
        return self._domain._load(db, EntityRef(kind, record_id, row["version"], row["sha256"]), roots)[0]

    def _confirmation_id(self, work_model_id):
        return str(uuid5(NAMESPACE_URL, f"deeptwin:work-model-confirmation:{work_model_id}"))

    def _view(self, db, roots, record):
        target = confirm_work_model(record.body["content"], None)
        decision = self._record(db, roots, "decision_record", self._confirmation_id(record.body["id"]))
        state = "unconfirmed" if decision is None else decision.body["content"]["decision"]
        return {
            "work_model_id": record.body["id"],
            "record_ref": record.ref.as_dict(),
            "work_model_ref": target.work_model_ref.as_dict(),
            "work_model": target.work_model.as_dict(),
            "state": "confirmed" if state == "accepted" else state,
            "confirmation_ref": None if decision is None or state != "accepted" else decision.ref.as_dict(),
            "blocking_unknown_ids": list(target.blocked_unknown_ids),
        }

    @_closed
    def read(self, request, work_model_id: str) -> dict:
        self._owner.authenticate_bound(request.session)
        try:
            uuid_string(work_model_id)
        except (TypeError, ValueError):
            raise WorkModelServiceError("not_found") from None
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            record = self._record(db, roots, "work_model", work_model_id)
            if record is None:
                raise WorkModelServiceError("not_found")
            return self._view(db, roots, record)

    def confirmed_target(self, work_model_id: str) -> ConfirmedWorkTarget:
        """The issued confirmed target for design generation, rebuilt from the sealed records."""

        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            record = self._record(db, roots, "work_model", work_model_id)
            decision = self._record(db, roots, "decision_record", self._confirmation_id(work_model_id))
            if record is None or decision is None or decision.body["content"]["decision"] != "accepted":
                raise WorkModelServiceError("conflict")
            return confirm_work_model(record.body["content"], decode_design_refs(decision.body["content"]["design"]))

    def _readings(self, source_refs):
        """The owner's latest reading of each source, for the prompt, and their refs (the
        draft's provenance). No reading at all → ((), ()): the revision text alone."""
        from .source_readings import latest_readings

        with self._domain._connection() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_readings_v1'"
                          ).fetchone() is None:
                return (), ()
            roots = self._domain._read_roots(db)
            records = latest_readings(self._domain, db, roots, source_refs)
            if all(record is None for record in records):
                return (), ()
            names = []
            for ref in source_refs:
                source = self._domain._load(db, EntityRef.from_dict(ref), roots)[0]
                names.append(source.body["content"].get("name"))
        entries, budget = [], MAX_PROMPT_READING_CHARS
        for name, record in zip(names, records, strict=True):
            if record is None:
                entries.append({"name": name, "reading_state": "not_read"})
                continue
            content = record.body["content"]
            text = content["text"][:budget]
            budget -= len(text)
            entry = {"name": name, "reading_state": content["state"], "reasons": content["reasons"], "text": text}
            if len(text) < len(content["text"]):
                entry["omitted_from_prompt_characters"] = len(content["text"]) - len(text)
            entries.append(entry)
        return tuple(entries), tuple(record.ref for record in records if record is not None)

    # --- commands ----------------------------------------------------------

    @_closed
    def draft(self, request, payload) -> dict:
        command = _command(payload, DRAFT_SCHEMA, ("work_id", "revision", "model_choice_ref"))
        choice_ref = _ref(command["model_choice_ref"], "model_choice")
        try:
            work_id = uuid_string(command["work_id"])
        except (TypeError, ValueError):
            raise WorkModelServiceError("invalid_input") from None
        if type(command["revision"]) is not int or not 1 <= command["revision"] <= 1_000_000:
            raise WorkModelServiceError("invalid_input")
        work_model_id = str(uuid5(NAMESPACE_URL, f"deeptwin:work-model:{command['command_id']}"))
        _authenticate_owner(self._owner, request)  # before any read or provider call
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            # a revision is immutable: (work, revision) names exactly one record
            row = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind='work_revision' "
                             "AND id=? AND version=?", (roots.genesis.id, work_id, command["revision"])).fetchone()
            if row is None:
                raise WorkModelServiceError("not_found")
            revision_ref = EntityRef("work_revision", work_id, command["revision"], row["sha256"])
            existing = self._record(db, roots, "work_model", work_model_id)
            if existing is not None:  # a replay never calls again
                if existing.body["content"]["work_revision_ref"] != revision_ref.as_dict():
                    raise WorkModelServiceError("conflict")
                return self._view(db, roots, existing)
        if self._executor is None:
            raise WorkModelServiceError("provider_unavailable")
        try:
            revision = self._domain.get(revision_ref)
            choice = self._domain.get(choice_ref)
        except Exception:  # noqa: BLE001 - an absent or mismatched ref is simply not found
            raise WorkModelServiceError("not_found") from None
        revision_content = revision.body["content"] if type(revision.body["content"]) is dict else {}
        text = revision_content.get("text")
        if type(text) is not str or not text.strip():
            raise WorkModelServiceError("invalid_input")
        # FR-003's work model is grounded in retained originals; a text-only revision has
        # none, and the framework never manufactures a source for it
        sources = revision_content.get("source_refs") or []
        if not sources:
            raise WorkModelServiceError("sources_required")
        content = choice.body["content"]
        if content.get("schema_version") != CHOICE_SCHEMA or content.get("provider") != "claude":
            raise WorkModelServiceError("invalid_input")
        readings, reading_refs = self._readings(sources)
        system, user = render_work_model_prompt(text, readings)
        started = time.monotonic()
        try:
            raw = self._executor.model_turn(content["model_id"], purpose="work_understanding",
                                            max_output_tokens=MAX_OUTPUT_TOKENS)(system, user)
        except Exception:  # noqa: BLE001 - the connection's own records keep the reason
            raise WorkModelServiceError("provider_unavailable") from None
        target = admit_work_model(raw, work_model_id=work_model_id, work_revision_ref=revision_ref,
                                  source_refs=sources)
        duration_ms = int((time.monotonic() - started) * 1000)
        with _writer(), self._domain._connection(write=True) as db:
            roots = self._domain._read_roots(db)
            actor = _authenticate_owner(self._owner, request, db)
            existing = self._record(db, roots, "work_model", work_model_id)
            if existing is not None:
                return self._view(db, roots, existing)
            actor_ref = _owner_actor_ref(db, actor)
            record = ImmutableRecord.create(
                kind="work_model", id=work_model_id, version=1, created_at_utc=_stamp(),
                actor_ref=roots.actor, parent_refs=(revision_ref, choice_ref, *reading_refs), purpose="operational",
                access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                content=target.work_model.as_dict())
            self._domain._put_in_transaction(db, record)
            self._event(db, roots, actor_ref, "understanding.completed", record.ref, command["command_id"],
                        {"revision": revision_ref.version, "duration_ms": duration_ms})
            return self._view(db, roots, record)

    @_closed
    def confirm(self, request, work_model_id: str, payload) -> dict:
        command = _command(payload, CONFIRM_SCHEMA, ("work_model_ref", "decision"))
        if command["decision"] not in ("accepted", "rejected"):
            raise WorkModelServiceError("invalid_input")
        supplied = _ref(command["work_model_ref"], "work_model")
        with _writer(), self._domain._connection(write=True) as db:
            roots = self._domain._read_roots(db)
            actor = _authenticate_owner(self._owner, request, db)
            record = self._record(db, roots, "work_model", work_model_id)
            if record is None:
                raise WorkModelServiceError("not_found")
            draft = confirm_work_model(record.body["content"], None)
            if supplied != draft.work_model_ref:
                raise WorkModelServiceError("conflict")  # the owner confirms only what they saw
            confirmation_id = self._confirmation_id(work_model_id)
            prior = self._record(db, roots, "decision_record", confirmation_id)
            if prior is not None:
                if prior.body["content"]["decision"] != command["decision"]:
                    raise WorkModelServiceError("conflict")  # one decision per draft
                return self._view(db, roots, record)
            actor_ref = _owner_actor_ref(db, actor)
            decision = {
                "schema_version": WORK_MODEL_CONFIRMATION_SCHEMA_VERSION,
                "confirmation_id": confirmation_id,
                "version": 1,
                "work_model_ref": draft.work_model_ref.as_dict(),
                "confirmed_dimensions": list(CONFIRMED_DIMENSIONS),
                "confirmed_by": actor_ref.as_dict(),
                "decision": command["decision"],
            }
            if command["decision"] == "accepted":
                confirm_work_model(record.body["content"], decision)  # binds all six or refuses
            # the confirmation names the work model by its design-space content ref, not
            # the stored record's hash, so it is kept in the design encoding (as every
            # design-space record is) and the stored record is its parent
            sealed = ImmutableRecord.create(
                kind="decision_record", id=confirmation_id, version=1, created_at_utc=_stamp(),
                actor_ref=actor_ref, parent_refs=(record.ref,), purpose="operational",
                access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                content={"schema_version": CONFIRMATION_RECORD_SCHEMA, "decision": command["decision"],
                         "design": encode_design_refs(decision)})
            self._domain._put_in_transaction(db, sealed)
            self._event(db, roots, actor_ref, "approval.decided", sealed.ref, command["command_id"],
                        {"decision": "approved" if command["decision"] == "accepted" else "rejected"})
            return self._view(db, roots, record)

    def _event(self, db, roots, actor_ref, kind, ref, command_id, metadata):
        stamp = _stamp()
        _append_event_in_transaction(db, vault_id=roots.genesis.id, recorded_at_utc=stamp,
            observed_at_utc=stamp, actor_kind="human", actor_ref=actor_ref, event_type=kind,
            object_refs=(ObjectRef(ref.kind, ref.id, ref.version, ref.sha256),),
            correlation_id=command_id, causation_id=None, status="succeeded",
            error_code=None, public_metadata=metadata, private_evidence_refs=(),
            retention_class="core", policy_ref=roots.access_policy)
