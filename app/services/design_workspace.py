"""The owner's design workspace over one persisted design request (T037; FR-005/FR-008/FR-009).

A design request's candidates, graphs and criticism are immutable records
(`design_persistence`). This service reads them back through the same gates that
issued them — every candidate is re-admitted by `accept_design_candidates` against
the exact issued request, every verdict is re-folded by `fold_candidate_criticism`
from its stored review and chains and must equal the stored verdict — and only then
assembles the honest selection pool (`assemble_selection_pool`): what is presented,
every exclusion with its reason, and the real count. Nothing is inferred from a
stored verdict's text alone.

Commands, each an explicit owner act on a CSRF-verified POST:

- **derive** (select / edit with an instruction / merge of two or more parents):
  `derive_design_version` issues the act and it persists as one immutable
  `design_derivation` record parented to its exact candidate records. Re-review is
  always required and no verdict, score or approval is inherited.
- **review**: runs the existing criticism driver (`run_candidate_criticism` +
  `persist_criticism_run`) over a derived version ONLY when the host configured a
  critic model turn for this request; otherwise it refuses as `review_unavailable`
  with the reason, and nothing is presented as a review. Only a `select` derivation
  has a graph to review; an edit or merge needs a generation turn that realizes the
  instruction or the merge, and none exists here — refused with that reason.
- **prepare**: attempts the human design approval and the environment preparation
  (`design_approval_subject` → owner decision → `record_design_approval` →
  `prepare_environment_version`, persisted through `design_store`). A passed verdict
  from a critic configuration that is not qualified is never approvable; the refusal
  is the environments module's own exact reason. No production critic is qualified
  (`critic_qualification.V3_VERIFYING_DESIGN_IDS` is empty), so in production this
  command always answers that refusal.

- **generate** (T038): runs the design arc for the request — one bounded generation
  call per round through the host's registered generation turn, every accepted
  candidate persisted and criticized through the registered critic turn, the pool
  re-assembled after each round — until three structurally different passed
  candidates are presented or the owner's round limit (1..3) is reached. A refused
  generation or criticism call is recorded as a refusal of that round, never as a
  candidate; a shortfall ends as the real count. Each run persists one
  `design_generation_run` record (outcome, rounds, model calls, refusals, the
  candidates it produced and those left unreviewed). Without both turns the command
  answers `generation_unavailable` with the reason.
- **cancel** (T038): the owner stops a running generation. It takes effect before the
  next model call: a call already sent is not recalled, what completed stays recorded,
  and a candidate whose criticism did not finish stays unreviewed (never presented).
- An **edit** derivation is re-reviewed through the same generation turn: one revision
  call (`run_candidate_generation(revision=...)`) realizes the owner's instruction on
  the exact parent graph, and the new candidate — parented to the derivation — is
  criticized from scratch. A merge still has no generation turn that realizes it.

- **create** (`POST /api/v1/design-requests`): the owner creates a design request from
  their accepted work model through the host's `DesignSource` (`design_requests`) — only
  where a qualified lens decision exists. The request and its basis (the lens evidence,
  the functional decision, the exact compilation authority) are persisted. Production
  configures no source (no lens is qualified), so the command answers `not_designable`
  with that exact reason, and the list says the same under `creation`.
- **restore**: a persisted request that is not being served is rebuilt from its stored,
  verified records by re-running every issuing gate (`design_requests.restore_request`);
  anything that does not resolve answers `not_restorable` with the exact reason (a
  request registered by host code with `open_request` and no stored basis stays
  unrestorable). A refused criticism answer is persisted as a
  `design_criticism_refusal` record on its candidate (raw answer, bounded, and the exact
  violation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
from threading import Event, RLock
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import DomainContractError, EntityRef, canonical_json, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, _writer
from .critic_qualification import (
    RELEASE_DESIGN_IDS,
    is_issued_critic_qualification,
    unknown_critic_qualification,
)
from .design import (
    DesignContractError,
    DesignGenerationRequest,
    accept_design_candidates,
)
from .design_criticism import DesignCriticismError, fold_candidate_criticism
from .design_live import DesignGenerationError, run_candidate_generation
from .design_persistence import (
    DesignPersistenceError,
    decode_design_refs,
    encode_design_refs,
    persist_criticism_run,
    persist_generation_result,
)
from .design_review import (
    DERIVATION_ACTIONS,
    SELECTION_POOL_SIZE,
    DesignReviewError,
    assemble_selection_pool,
    derive_design_version,
)
from .environments import (
    EnvironmentContractError,
    design_approval_subject,
    open_environment,
    prepare_environment_version,
    record_design_approval,
)
from .owner_auth import OwnerAuthError, PersistentOwnerAuthority
from .owner_decisions import OwnerDecisionError, PersistentOwnerDecisions
from .run_approvals import _authenticate_owner, _owner_actor_ref

__all__ = [
    "CANCEL_SCHEMA",
    "DERIVE_SCHEMA",
    "GENERATE_SCHEMA",
    "PREPARE_SCHEMA",
    "REVIEW_SCHEMA",
    "DesignWorkspaceError",
    "PersistentDesignWorkspace",
    "derived_candidate_id",
    "environment_id_for",
]

DERIVE_SCHEMA = "design-derivation-command-v1"
REVIEW_SCHEMA = "design-review-command-v1"
PREPARE_SCHEMA = "design-prepare-command-v1"
GENERATE_SCHEMA = "design-generation-command-v1"
CANCEL_SCHEMA = "design-generation-cancel-command-v1"
_RUN_SCHEMA = "design-generation-run-v1"
MAX_GENERATION_ROUNDS = 3
_DERIVATION_SCHEMA = "design-derivation-v1"
CREATE_SCHEMA = "design-request-create-command-v1"
CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "conflict",
                   "unavailable", "review_unavailable", "not_approvable", "generation_unavailable",
                   "not_designable", "not_restorable"})
_MAX_STORED = 256
_MAX_CHILDREN = 256
_MAX_REQUESTS = 64


class DesignWorkspaceError(ValueError):
    """A closed code, plus the exact reason for a refusal the owner must read."""

    def __init__(self, code="invalid_input", reason=None):
        if code not in CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code
        self.reason = reason


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (DesignWorkspaceError, OwnerAuthError):
            raise
        except OwnerDecisionError as error:
            raise DesignWorkspaceError("conflict" if str(error) == "conflict" else "unavailable") from None
        except Exception:  # noqa: BLE001 - storage detail never leaves the service
            raise DesignWorkspaceError("unavailable") from None

    return invoke


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def environment_id_for(request_id: str) -> str:
    """The one environment a request's designs are prepared into."""

    return str(uuid5(NAMESPACE_URL, f"deeptwin:design-environment:{request_id}"))


def derived_candidate_id(derivation_id: str) -> str:
    """The candidate identity a select derivation is re-reviewed as."""

    return str(uuid5(NAMESPACE_URL, f"deeptwin:design-derivation-candidate:{derivation_id}"))


def _derivation_id(command_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"deeptwin:design-derivation:{command_id}"))


def _run_id(command_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"deeptwin:design-generation-run:{command_id}"))


class _Cancelled(RuntimeError):
    """The owner cancelled before this model call was sent."""


class _Counted:
    """A model turn that counts the calls it sends and refuses to send once the owner
    has cancelled (a call already sent is never recalled)."""

    def __init__(self, turn, cancel: Event):
        self._turn = turn
        self._cancel = cancel
        self.calls = 0
        self.stopped = False

    def __call__(self, system, user):
        if self._cancel.is_set():
            self.stopped = True
            raise _Cancelled("cancelled by the owner")
        self.calls += 1
        return self._turn(system, user)


@dataclass(frozen=True, slots=True)
class _Registration:
    request: DesignGenerationRequest
    record_ref: EntityRef
    registry: object | None
    critic_qualification: object | None
    criticism_turn: object | None
    critic_model_id: str | None
    generation_turn: object | None = None
    generator_model_id: str | None = None


@dataclass(frozen=True, slots=True)
class _Loaded:
    candidate: object
    record_ref: EntityRef
    verdict: object | None
    critic: dict | None


class PersistentDesignWorkspace:
    def __init__(self, domain_store, owner_authority):
        if type(domain_store) is not DomainStore:
            raise TypeError("Exact DomainStore required")
        if type(owner_authority) is not PersistentOwnerAuthority or owner_authority._domain is not domain_store:
            raise TypeError("Owner authority must share the actual domain store")
        self._domain = domain_store
        self._owner = owner_authority
        self._decisions = PersistentOwnerDecisions(domain_store, owner_authority)
        self._lock = RLock()
        self._requests: dict[str, _Registration] = {}
        self._running: dict[str, Event] = {}
        self._source = None

    # --- the host's design source (trusted code only; never page input) -------------

    def configure_design_source(self, source):
        """Let the owner create design requests from a confirmed work model, and let
        persisted requests be rebuilt after a restart. Production configures none: no
        lens is qualified, so creation states that reason instead."""

        from .design_requests import DesignSource

        if source is not None and type(source) is not DesignSource:
            raise TypeError("A DesignSource is required")
        with self._lock:
            self._source = source

    def _work_models(self):
        from .work_models import PersistentWorkModels

        return PersistentWorkModels(self._domain, self._owner, None)

    def _register_from_source(self, request, source):
        return self.open_request(request, registry=source.registry, critic_qualification=source.critic_qualification,
                                 criticism_turn=source.criticism_turn, critic_model_id=source.critic_model_id,
                                 generation_turn=source.generation_turn, generator_model_id=source.generator_model_id)

    def _stored_request(self, request_id):
        """(record ref, stored request dict) of a persisted request, or None."""

        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            row = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind='decision_record' "
                             "AND id=? AND version=1", (roots.genesis.id, request_id)).fetchone()
            if row is None:
                return None
            ref = EntityRef("decision_record", request_id, 1, row["sha256"])
            content = self._domain._load(db, ref, roots)[0].body["content"]
        if type(content) is not dict or content.get("design_kind") != "design_generation_request":
            return None
        return ref, decode_design_refs(content["design"])

    def _restore(self, request_id):
        """Rebuild a persisted request from its stored, verified records and serve it."""

        from .design_requests import DesignRequestError, restore_request, stored_basis

        stored = self._stored_request(request_id)
        if stored is None:
            raise DesignWorkspaceError("not_found")
        ref, value = stored
        with self._lock:
            source = self._source
        try:
            request = restore_request(source, self._work_models(), value, stored_basis(self._domain, ref))
        except DesignRequestError as error:
            raise DesignWorkspaceError("not_restorable", error.reason) from None
        self._register_from_source(request, source)
        with self._lock:
            return self._requests[request_id]

    def _stored_basis_request_ids(self):
        """Request ids whose basis is persisted (a basis is parented to its work model)."""

        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            rows = db.execute(
                "SELECT DISTINCT e.source_id FROM domain_edges e WHERE e.vault_id=? AND e.source_kind='decision_record' "
                "AND e.target_kind='work_model' ORDER BY e.source_id LIMIT ?",
                (roots.genesis.id, _MAX_STORED)).fetchall()
            found = []
            for row in rows:
                record = db.execute("SELECT version, sha256 FROM domain_records WHERE vault_id=? AND "
                                    "kind='decision_record' AND id=? ORDER BY version DESC LIMIT 1",
                                    (roots.genesis.id, row["source_id"])).fetchone()
                loaded = self._domain._load(db, EntityRef("decision_record", row["source_id"], record["version"],
                                                          record["sha256"]), roots)[0]
                content = loaded.body.get("content")
                if type(content) is dict and content.get("design_kind") == "design_request_basis":
                    found.append(decode_design_refs(content["design"])["request_id"])
        return found

    def creation(self):
        from .design_requests import PRODUCTION_REASON

        with self._lock:
            source = self._source
        return {"available": source is not None, "reason": None if source is not None else PRODUCTION_REASON,
                "source": None if source is None else source.label}

    @_closed
    def create(self, request, payload) -> dict:
        """The owner creates a design request from their confirmed work model — only where
        a qualified lens decision exists; otherwise the exact reason is answered."""

        from .design_requests import (
            PRODUCTION_REASON,
            DesignRequestError,
            issue_request,
            persist_basis,
            request_id_for,
        )
        from .work_models import WorkModelServiceError

        _authenticate_owner(self._owner, request)
        command = self._command(payload, CREATE_SCHEMA, ("work_model_id",))
        try:
            work_model_id = uuid_string(command["work_model_id"])
        except (DomainContractError, TypeError, ValueError):
            raise DesignWorkspaceError("invalid_input") from None
        request_id = request_id_for(command["command_id"])
        if self._stored_request(request_id) is not None:  # an exact replay creates nothing
            registration = self._registration(request_id)
            return self._created(registration, work_model_id)
        work_models = self._work_models()
        try:
            target = work_models.confirmed_target(work_model_id)
        except WorkModelServiceError:
            raise DesignWorkspaceError("not_designable", "the owner has not accepted this work model; accept it "
                                                         "before a design request can be created") from None
        with self._lock:
            source = self._source
        if source is None:
            raise DesignWorkspaceError("not_designable", PRODUCTION_REASON)
        try:
            issued, basis = issue_request(source, target, request_id=request_id)
        except DesignRequestError as error:
            raise DesignWorkspaceError("not_designable", error.reason) from None
        headers = self._headers()
        from .design_persistence import persist_design_request

        record_ref = persist_design_request(self._domain, issued, **headers)
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            work_model_ref = work_models._record(db, roots, "work_model", work_model_id).ref
        persist_basis(self._domain, record_ref, work_model_ref, basis, actor_ref=headers["actor_ref"],
                      created_at_utc=headers["created_at_utc"])
        self._register_from_source(issued, source)
        return self._created(self._registration(request_id), work_model_id)

    @staticmethod
    def _created(registration, work_model_id):
        request = registration.request
        return {"schema_version": "design-request-v1", "request_id": request.request_id,
                "version": request.version, "requested_candidate_count": request.requested_candidate_count,
                "work_model_id": work_model_id, "design_disposition": request.design_disposition}

    # --- host registration (trusted code only; never page input) ------------------

    def open_request(self, request, *, registry=None, critic_qualification=None,
                     criticism_turn=None, critic_model_id=None, generation_turn=None,
                     generator_model_id=None):
        """Serve one issued request whose record is already persisted in this vault.
        A `generation_turn` (with its model identity) lets the owner run the design arc
        and re-review edits; it needs the critic turn too."""

        if type(request) is not DesignGenerationRequest:
            raise TypeError("A framework-issued design generation request is required")
        if critic_qualification is not None and not is_issued_critic_qualification(critic_qualification):
            raise TypeError("An issued critic qualification is required")
        if (criticism_turn is None) != (critic_model_id is None) or (
                criticism_turn is not None and (not callable(criticism_turn) or registry is None)):
            raise TypeError("A critic turn needs its model identity and the lens registry")
        if (generation_turn is None) != (generator_model_id is None) or (
                generation_turn is not None and (not callable(generation_turn) or criticism_turn is None)):
            raise TypeError("A generation turn needs its model identity and a critic turn")
        record = self._request_record(request)
        with self._lock:
            if request.request_id not in self._requests and len(self._requests) >= _MAX_REQUESTS:
                raise ValueError("Too many open design requests")
            self._requests[request.request_id] = _Registration(
                request, record, registry, critic_qualification, criticism_turn, critic_model_id,
                generation_turn, generator_model_id)
        return record

    def _request_record(self, request) -> EntityRef:
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            row = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind='decision_record' "
                             "AND id=? AND version=?", (roots.genesis.id, request.request_id,
                                                        request.version)).fetchone()
            if row is None:
                raise ValueError("The design request is not persisted in this vault")
            ref = EntityRef("decision_record", request.request_id, request.version, row["sha256"])
            content = self._domain._load(db, ref, roots)[0].body["content"]
        if (type(content) is not dict or content.get("design_kind") != "design_generation_request"
                or canonical_json(decode_design_refs(content["design"])) != canonical_json(request.as_dict())):
            raise ValueError("The persisted request is not this exact request")
        return ref

    def _registration(self, request_id) -> _Registration:
        try:
            uuid_string(request_id)
        except (DomainContractError, TypeError, ValueError):
            raise DesignWorkspaceError("not_found") from None
        with self._lock:
            found = self._requests.get(request_id)
        if found is None:
            # a persisted request is rebuilt from its stored, verified records, or refused
            return self._restore(request_id)
        return found

    # --- reading the persisted chain -----------------------------------------------

    def _children(self, db, roots, ref, kind, design_kind):
        rows = db.execute(
            "SELECT DISTINCT r.kind, r.id, r.version, r.sha256 FROM domain_edges e JOIN domain_records r "
            "ON r.vault_id=e.vault_id AND r.kind=e.source_kind AND r.id=e.source_id AND r.version=e.source_version "
            "WHERE e.vault_id=? AND e.target_kind=? AND e.target_id=? AND e.target_version=? "
            "AND e.target_sha256=? AND e.source_kind=? ORDER BY r.id, r.version LIMIT ?",
            (roots.genesis.id, ref.kind, ref.id, ref.version, ref.sha256, kind, _MAX_CHILDREN + 1)).fetchall()
        if len(rows) > _MAX_CHILDREN:
            raise DesignWorkspaceError("unavailable")
        found = []
        for row in rows:
            record = self._domain._load(db, EntityRef(row["kind"], row["id"], row["version"], row["sha256"]),
                                        roots)[0]
            content = record.body.get("content")
            if type(content) is dict and content.get("design_kind") == design_kind:
                found.append((record, decode_design_refs(content["design"])))
        return found

    def _restore_candidate(self, db, roots, request, record, stored):
        graphs = [EntityRef.from_dict(item) for item in record.body["parent_refs"] if item["kind"] == "graph"]
        if len(graphs) != 1:
            raise DesignWorkspaceError("unavailable")
        graph_content = self._domain._load(db, graphs[0], roots)[0].body["content"]
        if graph_content.get("design_kind") != "functional_graph":
            raise DesignWorkspaceError("unavailable")
        value = {name: stored[name] for name in ("schema_version", "candidate_id", "version",
                                                  "generation_request_ref", "parent_candidate_refs",
                                                  "generation_call_refs")}
        value["graph"] = decode_design_refs(graph_content["design"])
        try:
            candidate = accept_design_candidates(request, [value])[0]
        except DesignContractError:
            raise DesignWorkspaceError("unavailable") from None
        if canonical_json(candidate.as_dict()) != canonical_json(stored):
            raise DesignWorkspaceError("unavailable")
        return candidate

    def _restore_verdict(self, db, roots, request, candidate, record_ref):
        criticisms = self._children(db, roots, record_ref, "decision_record", "candidate_criticism")
        if not criticisms:
            return None, None
        if len(criticisms) != 1:
            raise DesignWorkspaceError("unavailable")
        _record, design = criticisms[0]
        try:
            verdict = fold_candidate_criticism(candidate, request, design["review"], design["chains"])
        except DesignCriticismError:
            raise DesignWorkspaceError("unavailable") from None
        if canonical_json(verdict.as_dict()) != canonical_json(design["verdict"]):
            # a stored verdict the fold does not reproduce is never shown as one
            raise DesignWorkspaceError("unavailable")
        calls = design.get("call_records") or []
        critic = {
            "source": "persisted_criticism",
            "model_ids": sorted({item["model_id"] for item in calls}),
            "profile_digests": sorted({item["profile_digest"] for item in calls}),
            "call_count": len(calls),
            "criticism_record_id": _record.ref.id,
        }
        return verdict, critic

    def _load(self, registration):
        request = registration.request
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            records = {}
            for call, _design in self._children(db, roots, registration.record_ref, "decision_record",
                                                "design_generation_call"):
                for record, stored in self._children(db, roots, call.ref, "design_candidate", "design_candidate"):
                    records[record.ref] = (record, stored)
            loaded = []
            for record, stored in sorted(records.values(), key=lambda item: (item[1]["candidate_id"],
                                                                              item[1]["version"])):
                candidate = self._restore_candidate(db, roots, request, record, stored)
                verdict, critic = self._restore_verdict(db, roots, request, candidate, record.ref)
                loaded.append(_Loaded(candidate, record.ref, verdict, critic))
            derivations = {}
            for item in loaded:
                for record, design in self._children(db, roots, item.record_ref, "decision_record",
                                                     "design_derivation"):
                    derivations[record.ref.id] = (record, design)
            derived = []
            for derivation_id in sorted(derivations):
                record, design = derivations[derivation_id]
                reviewed = None
                for child, stored in self._children(db, roots, record.ref, "design_candidate", "design_candidate"):
                    candidate = self._restore_candidate(db, roots, request, child, stored)
                    verdict, critic = self._restore_verdict(db, roots, request, candidate, child.ref)
                    reviewed = _Loaded(candidate, child.ref, verdict, critic)
                derived.append((record, design, reviewed))
        return loaded, derived

    def _qualification(self, registration, loaded):
        if registration.critic_qualification is not None:
            return registration.critic_qualification
        # no suite record names this critic configuration: never qualified
        configuration = sorted({(model, digest) for item in loaded if item.critic
                                for model in item.critic["model_ids"] for digest in item.critic["profile_digests"]})
        return unknown_critic_qualification(sha256(canonical_json(
            {"critic_configuration": [list(pair) for pair in configuration]})).hexdigest())

    # --- views ---------------------------------------------------------------------

    @staticmethod
    def _verdict_view(item):
        if item is None or item.verdict is None:
            return None
        return {"status": item.verdict.status, "reasons": list(item.verdict.reasons), **item.critic}

    def _candidate_view(self, item, presented):
        candidate = item.candidate
        return {
            "candidate_id": candidate.candidate_id,
            "version": candidate.version,
            "graph_ref": candidate.graph_ref.as_dict(),
            "graph": candidate.graph.as_dict(),
            "parent_candidate_ids": [ref.id for ref in candidate.parent_candidate_refs],
            "verdict": self._verdict_view(item),
            "presented": presented,
        }

    def _view(self, registration, preloaded=None):
        request = registration.request
        loaded, derived = self._load(registration) if preloaded is None else preloaded
        reviewed = [item for item in loaded if item.verdict is not None]
        excluded = [{"candidate_id": item.candidate.candidate_id, "reason": "unreviewed"}
                    for item in loaded if item.verdict is None]
        presented_ids, passed_count = [], 0
        if reviewed:
            pool = assemble_selection_pool(request, [(item.candidate, item.verdict) for item in reviewed])
            presented_ids = [candidate.candidate_id for candidate in pool.presented]
            excluded = [{"candidate_id": cid, "reason": reason} for cid, reason in pool.excluded] + excluded
            passed_count = pool.passed_count
        qualification = self._qualification(registration, loaded)
        review_reason = None if registration.criticism_turn is not None else "critic_model_not_configured"
        by_id = {item.candidate.candidate_id: item for item in loaded}
        return {
            "schema_version": "design-workspace-v1",
            "request": {
                "request_id": request.request_id, "version": request.version,
                "requested_candidate_count": request.requested_candidate_count,
                "design_disposition": request.design_disposition,
                "work_model_ref": request.work_target.work_model_ref.as_dict(),
            },
            "pool": {
                "pool_size": SELECTION_POOL_SIZE,
                "presented_candidate_ids": presented_ids,
                "presented_count": len(presented_ids),
                "passed_count": passed_count,
                "candidate_count": len(loaded),
                "excluded": excluded,
                "supplementation_available": len(presented_ids) < SELECTION_POOL_SIZE,
            },
            "candidates": [self._candidate_view(by_id[cid], cid in presented_ids)
                           for cid in presented_ids]
            + [self._candidate_view(item, False) for item in loaded
               if item.candidate.candidate_id not in presented_ids],
            "derivations": [self._derivation_view(record, design, item) for record, design, item in derived],
            "review": {"available": review_reason is None, "reason": review_reason,
                       "critic_model_id": registration.critic_model_id,
                       # an edit is realized by the generation turn; a merge has none yet
                       "realizes": (["select", "edit"] if registration.generation_turn is not None
                                    else ["select"])},
            "generation": self._generation_view(registration),
            "preparation": {
                "environment_id": environment_id_for(request.request_id),
                "critic_qualification": qualification.as_dict(),
                "approvable": qualification.status == "qualified",
                # a qualified record outside the release designs is a TEST-ACTOR simulation,
                # never a release qualification (decisions.md 2026-09-25)
                "simulated_qualification": (qualification.status == "qualified"
                                            and qualification.design_id not in RELEASE_DESIGN_IDS),
                "reason": None if qualification.status == "qualified"
                else f"the critic configuration is not qualified ({qualification.status}: {qualification.reason})",
            },
        }

    def _generation_view(self, registration):
        reason = ("generator_model_not_configured" if registration.generation_turn is None
                  else None)
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            runs = self._children(db, roots, registration.record_ref, "decision_record", "design_generation_run")
        with self._lock:
            running = self._running.get(registration.request.request_id)
        return {
            "available": reason is None, "reason": reason,
            "generator_model_id": registration.generator_model_id,
            "critic_model_id": registration.critic_model_id,
            "max_rounds": MAX_GENERATION_ROUNDS,
            "running": running is not None,
            "cancel_requested": running is not None and running.is_set(),
            "runs": sorted((self._run_view(record, design) for record, design in runs),
                           key=lambda item: item["started_at_utc"]),
        }

    @staticmethod
    def _run_view(record, design):
        return {"run_id": record.ref.id, **{name: design[name] for name in (
            "command_id", "max_rounds", "rounds", "outcome", "model_calls", "generator_model_id",
            "critic_model_id", "refusals", "candidate_ids", "unreviewed_candidate_ids", "presented_count",
            "started_at_utc", "ended_at_utc")}}

    def _derivation_view(self, record, design, reviewed):
        return {
            "derivation_id": record.ref.id,
            "action": design["action"],
            "parent_candidate_ids": list(design["parent_candidate_ids"]),
            "instruction": design["instruction"],
            "re_review_required": reviewed is None or reviewed.verdict is None,
            "inherited_verdict": None,
            "created_at_utc": record.body["created_at_utc"],
            "reviewed_candidate": None if reviewed is None else self._candidate_view(reviewed, False),
        }

    @_closed
    def list(self, request) -> dict:
        self._owner.authenticate_bound(request.session)
        unrestorable = []
        for request_id in self._stored_basis_request_ids():
            with self._lock:
                if request_id in self._requests:
                    continue
            try:
                self._restore(request_id)
            except DesignWorkspaceError as error:
                unrestorable.append({"request_id": request_id, "code": error.code, "reason": error.reason})
        with self._lock:
            registrations = sorted(self._requests.values(), key=lambda item: item.request.request_id)
        return {"requests": [{"request_id": item.request.request_id, "version": item.request.version,
                              "requested_candidate_count": item.request.requested_candidate_count}
                             for item in registrations],
                "unrestorable": unrestorable, "creation": self.creation()}

    @_closed
    def read(self, request, request_id: str) -> dict:
        self._owner.authenticate_bound(request.session)
        return self._view(self._registration(request_id))

    # --- commands ------------------------------------------------------------------

    @staticmethod
    def _command(payload, schema, fields):
        if type(payload) is not dict or set(payload) != {"schema_version", "command_id", *fields} \
                or payload["schema_version"] != schema:
            raise DesignWorkspaceError("invalid_input")
        try:
            uuid_string(payload["command_id"])
        except (DomainContractError, TypeError, ValueError):
            raise DesignWorkspaceError("invalid_input") from None
        return payload

    @_closed
    def derive(self, request, request_id: str, payload) -> dict:
        _authenticate_owner(self._owner, request)
        command = self._command(payload, DERIVE_SCHEMA, ("action", "parent_candidate_ids", "instruction"))
        registration = self._registration(request_id)
        action, parent_ids, instruction = command["action"], command["parent_candidate_ids"], command["instruction"]
        if (action not in DERIVATION_ACTIONS or type(parent_ids) is not list
                or any(type(item) is not str for item in parent_ids)
                or (instruction is not None and type(instruction) is not str)):
            raise DesignWorkspaceError("invalid_input")
        loaded, derived = self._load(registration)
        presented = set(self._view(registration, (loaded, derived))["pool"]["presented_candidate_ids"])
        by_id = {item.candidate.candidate_id: item for item in loaded}
        if any(item not in presented for item in parent_ids):
            # only what the pool presents (passed, structurally different) can be chosen
            raise DesignWorkspaceError("invalid_input", "only a presented candidate can be selected, edited or merged")
        parents = [by_id[item] for item in parent_ids]
        try:
            derived = derive_design_version(registration.request, action, [item.candidate for item in parents],
                                            instruction=instruction)
        except DesignReviewError as error:
            raise DesignWorkspaceError("invalid_input", str(error)) from None
        derivation_id = _derivation_id(command["command_id"])
        design = encode_design_refs({
            "schema_version": _DERIVATION_SCHEMA,
            "command_id": command["command_id"],
            "action": derived.action,
            "request_ref": derived.request_ref.as_dict(),
            "parent_refs": [ref.as_dict() for ref in derived.parent_refs],
            "parent_candidate_ids": list(parent_ids),
            "instruction": derived.instruction,
            "re_review_required": derived.re_review_required,
            "inherited_verdict": derived.inherited_verdict,
        })
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            existing = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind='decision_record' "
                                  "AND id=? AND version=1", (roots.genesis.id, derivation_id)).fetchone()
            if existing is not None:
                stored = self._domain._load(db, EntityRef("decision_record", derivation_id, 1, existing["sha256"]),
                                            roots)[0]
                if canonical_json(stored.body["content"].get("design")) != canonical_json(design):
                    raise DesignWorkspaceError("conflict")
                record = stored
            else:
                record = ImmutableRecord.create(
                    kind="decision_record", id=derivation_id, version=1, created_at_utc=_stamp(),
                    actor_ref=_owner_actor_ref(db, actor), parent_refs=tuple(item.record_ref for item in parents),
                    purpose="operational", access_policy_ref=roots.access_policy,
                    retention_policy_ref=roots.retention_policy,
                    content={"design_kind": "design_derivation", "design": design})
                self._domain._put_in_transaction(db, record)
        return self._derivation_view(record, decode_design_refs(design), None)

    @_closed
    def review(self, request, request_id: str, payload) -> dict:
        _authenticate_owner(self._owner, request)
        command = self._command(payload, REVIEW_SCHEMA, ("derivation_id",))
        registration = self._registration(request_id)
        _loaded, derived = self._load(registration)
        match = [entry for entry in derived if entry[0].ref.id == command["derivation_id"]]
        if not match:
            raise DesignWorkspaceError("not_found")
        record, design, reviewed = match[0]
        if reviewed is not None and reviewed.verdict is not None:
            return self._derivation_view(record, design, reviewed)  # already reviewed: never a second review
        if registration.criticism_turn is None:
            # no critic model turn is configured: nothing is reviewed, nothing is shown as a review
            raise DesignWorkspaceError("review_unavailable", "critic_model_not_configured")
        if design["action"] == "edit" and registration.generation_turn is not None:
            return self._review_edit(registration, record, design, reviewed)
        if design["action"] != "select":
            raise DesignWorkspaceError("review_unavailable", "derived_graph_not_generated")
        request_value = registration.request
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            parent_record = self._domain._load(db, EntityRef.from_dict(record.body["parent_refs"][0]), roots)[0]
            parent_stored = decode_design_refs(parent_record.body["content"]["design"])
            parent = self._restore_candidate(db, roots, request_value, parent_record, parent_stored)
            graph_ref = next(EntityRef.from_dict(item) for item in parent_record.body["parent_refs"]
                             if item["kind"] == "graph")
        candidate = accept_design_candidates(request_value, [{
            "schema_version": parent_stored["schema_version"],
            "candidate_id": derived_candidate_id(record.ref.id),
            "version": 1,
            "generation_request_ref": request_value.request_ref.as_dict(),
            "parent_candidate_refs": [parent.candidate_ref.as_dict()],
            "generation_call_refs": [ref.as_dict() for ref in parent.generation_call_refs],
            "graph": parent.graph.as_dict(),
        }])[0]
        headers = {"actor_ref": roots.actor, "access_policy_ref": roots.access_policy,
                   "retention_policy_ref": roots.retention_policy, "created_at_utc": _stamp()}
        if reviewed is None:
            candidate_record = ImmutableRecord.create(
                kind="design_candidate", id=candidate.candidate_id, version=1, parent_refs=(graph_ref, record.ref),
                purpose="operational", content={"design_kind": "design_candidate",
                                                "design": encode_design_refs(candidate.as_dict())}, **headers)
            candidate_ref = self._domain.put(candidate_record)
        else:
            candidate_ref = reviewed.record_ref
        try:
            self._criticize(registration, candidate, candidate_ref, registration.criticism_turn, headers)
        except (DesignCriticismError, DesignPersistenceError) as error:
            raise DesignWorkspaceError("review_unavailable", self._incomplete(error)) from None
        _loaded, derived = self._load(registration)
        record, design, reviewed = next(entry for entry in derived if entry[0].ref.id == record.ref.id)
        return self._derivation_view(record, design, reviewed)

    def _headers(self):
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
        return {"actor_ref": roots.actor, "access_policy_ref": roots.access_policy,
                "retention_policy_ref": roots.retention_policy, "created_at_utc": _stamp()}

    def _put(self, kind, identifier, parents, design_kind, design, headers):
        return self._domain.put(ImmutableRecord.create(
            kind=kind, id=identifier, version=1, parent_refs=tuple(parents), purpose="operational",
            content={"design_kind": design_kind, "design": encode_design_refs(design)}, **headers))

    def _criticize(self, registration, candidate, candidate_ref, turn, headers):
        from .design_criticism_live import CriticismStageRefused, run_candidate_criticism

        try:
            run = run_candidate_criticism(candidate, registration.request, registration.registry,
                                          model_turn=turn, model_id=registration.critic_model_id)
        except CriticismStageRefused as refused:
            # the model's refused answer and the exact rule it broke are persisted before
            # the refusal propagates: a contract failure stays diagnosable afterwards
            try:
                refused.record_id = self._put_refusal(candidate_ref, candidate, refused)
            except Exception:  # noqa: BLE001 - the refusal itself still propagates
                refused.record_id = None
            raise
        persist_criticism_run(self._domain, candidate_ref, candidate, registration.request,
                              registration.registry, run, **headers)

    def _put_refusal(self, candidate_ref, candidate, refused):
        design = {**refused.as_dict(), "candidate_id": candidate.candidate_id,
                  "candidate_version": candidate.version}
        record_id = str(uuid5(NAMESPACE_URL, f"deeptwin:design-criticism-refusal:{candidate_ref.id}:"
                                             f"{refused.response_sha256}"))
        with _writer(), self._domain._connection(write=True) as db:
            roots = self._domain._read_roots(db)
            existing = db.execute("SELECT 1 FROM domain_records WHERE vault_id=? AND kind='decision_record' "
                                  "AND id=?", (roots.genesis.id, record_id)).fetchone()
            if existing is None:
                self._domain._put_in_transaction(db, ImmutableRecord.create(
                    kind="decision_record", id=record_id, version=1, created_at_utc=_stamp(),
                    actor_ref=roots.actor, parent_refs=(candidate_ref,), purpose="operational",
                    access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                    content={"design_kind": "design_criticism_refusal", "design": encode_design_refs(design)}))
        return record_id

    @staticmethod
    def _incomplete(error):
        violation = getattr(error, "violation", None)
        return ("criticism_did_not_complete" if violation is None
                else f"criticism_did_not_complete: {str(error)[:200]}: {violation}"[:600])

    def criticism_refusals(self, request_id: str) -> list[dict]:
        """Every persisted refused criticism answer of this request's candidates, with the
        exact violation (host and test code only; the page reads the run's refusal text)."""

        registration = self._registration(request_id)
        loaded, derived = self._load(registration)
        refs = [item.record_ref for item in loaded] + [entry[2].record_ref for entry in derived
                                                        if entry[2] is not None]
        found = []
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            for ref in refs:
                for record, design in self._children(db, roots, ref, "decision_record", "design_criticism_refusal"):
                    found.append({"record_id": record.ref.id, **design})
        return found

    def _review_edit(self, registration, record, design, reviewed):
        """Realize the owner's edit instruction on the exact parent through one revision
        generation call, then criticize the new candidate from scratch."""

        request_value = registration.request
        headers = self._headers()
        if reviewed is None:
            with self._domain._connection() as db:
                roots = self._domain._read_roots(db)
                parent_record = self._domain._load(db, EntityRef.from_dict(record.body["parent_refs"][0]), roots)[0]
                parent_stored = decode_design_refs(parent_record.body["content"]["design"])
                parent = self._restore_candidate(db, roots, request_value, parent_record, parent_stored)
            try:
                result = run_candidate_generation(request_value, model_turn=registration.generation_turn,
                                                  model_id=registration.generator_model_id,
                                                  revision=(parent, design["instruction"]))
            except (DesignGenerationError, DesignContractError) as error:
                raise DesignWorkspaceError("review_unavailable",
                                           f"revision_not_generated: {str(error)[:300]}") from None
            candidate = result.candidates[0]
            # the revision call hangs off the derivation (not the request), so the pool never
            # counts it; the new candidate is the derivation's own
            call_ref = self._put("decision_record", result.call_record.call_id, (record.ref,),
                                 "design_generation_call", result.call_record.as_dict(), headers)
            graph_ref = self._put("graph", candidate.graph.graph_id, (call_ref,), "functional_graph",
                                  candidate.graph.as_dict(), headers)
            candidate_ref = self._put("design_candidate", candidate.candidate_id, (graph_ref, record.ref),
                                      "design_candidate", candidate.as_dict(), headers)
        else:
            candidate, candidate_ref = reviewed.candidate, reviewed.record_ref
        try:
            self._criticize(registration, candidate, candidate_ref, registration.criticism_turn, headers)
        except (DesignCriticismError, DesignPersistenceError) as error:
            raise DesignWorkspaceError("review_unavailable", self._incomplete(error)) from None
        _loaded, derived = self._load(registration)
        record, design, reviewed = next(entry for entry in derived if entry[0].ref.id == record.ref.id)
        return self._derivation_view(record, design, reviewed)

    @_closed
    def generate(self, request, request_id: str, payload) -> dict:
        """Run the design arc for this request: bounded rounds of real generation and
        criticism through the registered turns, until three are presented or the limit."""

        _authenticate_owner(self._owner, request)
        command = self._command(payload, GENERATE_SCHEMA, ("max_rounds",))
        registration = self._registration(request_id)
        max_rounds = command["max_rounds"]
        if type(max_rounds) is not int or not 1 <= max_rounds <= MAX_GENERATION_ROUNDS:
            raise DesignWorkspaceError("invalid_input")
        if registration.generation_turn is None:
            raise DesignWorkspaceError("generation_unavailable", "generator_model_not_configured")
        run_id = _run_id(command["command_id"])
        existing = self._stored_run(registration, run_id)
        if existing is not None:
            if existing["max_rounds"] != max_rounds:
                raise DesignWorkspaceError("conflict")
            return existing
        cancel = Event()
        with self._lock:
            if request_id in self._running:
                raise DesignWorkspaceError("conflict", "a generation is already running for this request")
            self._running[request_id] = cancel
        try:
            return self._run_arc(registration, command, run_id, max_rounds, cancel)
        finally:
            with self._lock:
                self._running.pop(request_id, None)

    def _stored_run(self, registration, run_id):
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            for record, design in self._children(db, roots, registration.record_ref, "decision_record",
                                                 "design_generation_run"):
                if record.ref.id == run_id:
                    return self._run_view(record, design)
        return None

    def _run_arc(self, registration, command, run_id, max_rounds, cancel):
        request_value = registration.request
        started = _stamp()
        generator = _Counted(registration.generation_turn, cancel)
        critic = _Counted(registration.criticism_turn, cancel)
        rounds, refusals, produced, unreviewed = 0, [], [], []
        cancelled = False
        presented = self._view(registration)["pool"]["presented_count"]
        while rounds < max_rounds and presented < SELECTION_POOL_SIZE and not cancelled:
            if cancel.is_set():
                cancelled = True
                break
            rounds += 1
            try:
                result = run_candidate_generation(request_value, model_turn=generator,
                                                  model_id=registration.generator_model_id)
            except (DesignGenerationError, DesignContractError) as error:
                if generator.stopped:
                    cancelled = True
                    rounds -= 1  # nothing was sent in this round
                    break
                refusals.append({"round": rounds, "stage": "generation", "reason": str(error)[:300]})
                continue
            headers = self._headers()
            persisted = persist_generation_result(self._domain, request_value, result, **headers)
            for candidate, record_ref in zip(result.candidates, persisted.candidate_record_refs, strict=True):
                produced.append(candidate.candidate_id)
                if cancelled or cancel.is_set():
                    cancelled = True
                    unreviewed.append(candidate.candidate_id)
                    continue
                try:
                    self._criticize(registration, candidate, record_ref, critic, headers)
                except (DesignCriticismError, DesignPersistenceError) as error:
                    unreviewed.append(candidate.candidate_id)
                    if critic.stopped:
                        cancelled = True
                        continue
                    refusal = {"round": rounds, "stage": "criticism", "candidate_id": candidate.candidate_id,
                               "reason": str(error)[:300]}
                    if getattr(error, "violation", None) is not None:
                        refusal.update(violation=error.violation, purpose=error.purpose,
                                       refusal_record_id=getattr(error, "record_id", None))
                    refusals.append(refusal)
            presented = self._view(registration)["pool"]["presented_count"]
        outcome = "cancelled" if cancelled else "filled" if presented >= SELECTION_POOL_SIZE else "shortfall"
        design = {
            "schema_version": _RUN_SCHEMA, "command_id": command["command_id"], "max_rounds": max_rounds,
            "rounds": rounds, "outcome": outcome, "model_calls": generator.calls + critic.calls,
            "generator_model_id": registration.generator_model_id,
            "critic_model_id": registration.critic_model_id, "refusals": refusals,
            "candidate_ids": produced, "unreviewed_candidate_ids": unreviewed, "presented_count": presented,
            "started_at_utc": started, "ended_at_utc": _stamp(),
        }
        self._put("decision_record", run_id, (registration.record_ref,), "design_generation_run", design,
                  self._headers())
        return self._stored_run(registration, run_id)

    @_closed
    def cancel(self, request, request_id: str, payload) -> dict:
        """The owner stops a running generation before its next model call."""

        _authenticate_owner(self._owner, request)
        self._command(payload, CANCEL_SCHEMA, ())
        self._registration(request_id)
        with self._lock:
            running = self._running.get(request_id)
            if running is not None:
                running.set()
        return {"schema_version": "design-generation-cancel-v1",
                "state": "cancel_requested" if running is not None else "not_running",
                "running": running is not None}

    def cancel_requested(self, request_id: str) -> bool:
        """Whether the owner has asked the running generation of this request to stop
        (host code and test-actor turns read it; never page input)."""

        with self._lock:
            running = self._running.get(request_id)
        return running is not None and running.is_set()

    @_closed
    def prepare(self, request, request_id: str, payload) -> dict:
        _authenticate_owner(self._owner, request)
        command = self._command(payload, PREPARE_SCHEMA, ("candidate_id",))
        registration = self._registration(request_id)
        loaded, derived = self._load(registration)
        target = next((item for item in loaded if item.candidate.candidate_id == command["candidate_id"]), None)
        if target is None:
            target = next((entry[2] for entry in derived if entry[2] is not None
                           and entry[2].candidate.candidate_id == command["candidate_id"]), None)
        if target is None:
            derivation = next((entry for entry in derived if entry[0].ref.id == command["candidate_id"]), None)
            if derivation is not None:
                raise DesignWorkspaceError("not_approvable", "re_review_required")
            raise DesignWorkspaceError("not_found")
        if target.verdict is None:
            raise DesignWorkspaceError("not_approvable", "unreviewed")
        graph = target.candidate.graph
        environment_id = environment_id_for(registration.request.request_id)
        value = {
            "environment": environment_id,
            "candidate": target.candidate,
            "verdict": target.verdict,
            "model_bindings": graph.model_bindings[0].model_choice_ref.as_dict() if graph.model_bindings else None,
            "tool_permissions": graph.tool_bindings[0].grant_ref.as_dict() if graph.tool_bindings else None,
            "observation_contract": graph.observation_contract_ref.as_dict(),
            "critic_qualification": self._qualification(registration, loaded),
        }
        try:
            subject = design_approval_subject(value)
        except EnvironmentContractError as error:
            # the environments module's own exact refusal (e.g. the critic is not qualified)
            raise DesignWorkspaceError("not_approvable", str(error)) from None
        decision = self._decisions.record(request, {
            "schema_version": "owner-decision-command-v1", "command_id": command["command_id"],
            "subject_kind": "design_approval", "subject": subject, "decision": "approve"})
        from .design_store import (
            DesignStoreError,
            persist_design_approval,
            persist_environment_head,
            persist_environment_record,
        )

        try:
            approval = record_design_approval({**value, "approval": decision})
            with self._domain._connection() as db:
                roots = self._domain._read_roots(db)
            headers = {"actor_ref": roots.actor, "access_policy_ref": roots.access_policy,
                       "retention_policy_ref": roots.retention_policy, "created_at_utc": decision.decided_at_utc}
            approval_ref = persist_design_approval(self._domain, approval, decisions=self._decisions, **headers)
            state, parent_ref = self._environment_head(environment_id)
            version, new_state = prepare_environment_version(
                state, approval, expected_head=state.head,
                extension_bindings=self._binding_revisions(environment_id))
            head_ref = persist_environment_head(self._domain, version, new_state, parent_ref=parent_ref,
                                                approval_ref=approval_ref, **headers)
            environment_ref = persist_environment_record(self._domain, version, head_ref=head_ref, **headers)
        except (EnvironmentContractError, DesignStoreError) as error:
            raise DesignWorkspaceError("not_approvable", str(error)) from None
        return {"status": "prepared", "environment_version": version.as_dict(),
                "environment_ref": environment_ref.as_dict(), "approval_ref": approval_ref.as_dict(),
                "activation": "not_activated"}

    def _binding_revisions(self, environment_id):
        """The durable extension binding heads this environment version is prepared with
        (`binding_heads.environment_binding_revisions`); a later binding change marks the
        version as needing re-preparation and changes nothing here."""
        from ..extensions.binding_heads import (
            BindingDispatchRefused,
            environment_binding_revisions,
        )

        try:
            return environment_binding_revisions(self._domain, environment_id)
        except BindingDispatchRefused:
            raise DesignWorkspaceError("not_approvable", "extension bindings are unavailable") from None

    def _environment_head(self, environment_id):
        from .design_store import resume_environment_state

        record_id = str(uuid5(NAMESPACE_URL, f"deeptwin:environment:{environment_id}"))
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            row = db.execute("SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind='decision_record' "
                             "AND id=? ORDER BY version DESC LIMIT 1", (roots.genesis.id, record_id)).fetchone()
        if row is None:
            return open_environment(environment_id), None
        ref = EntityRef("decision_record", record_id, row["version"], row["sha256"])
        return resume_environment_state(self._domain, ref), ref
