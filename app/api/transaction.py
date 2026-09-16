"""One-vault command transaction for authenticated, budgeted runtime dispatch.

This boundary commits the local command intent, current permission decision, budget
reservation, runtime send-intent barrier, canonical public event and durable receipt in
one SQLite write transaction.  The process-local dispatch capability is activated only
after that outer commit succeeds; an idempotent replay can never mint another permit.
"""

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
from threading import RLock

from .commands import (
    CommandConflict,
    CommandCorrupt,
    CommandEnvelope,
    CommandInvalid,
    CommandRegistry,
    _assert_command_schema,
    _complete_command,
    _existing_command,
    _insert_command_intent,
    _install_command_schema,
    _result,
)
from .session import AuthenticatedRequest
from .views import (
    EventPage,
    _append_event_in_transaction,
    _assert_event_schema,
    _at_epoch,
    _event_cursor_in_transaction,
    _install_event_schema,
    _read_events_in_transaction,
)
from ..domain.permissions import Grant, HostPolicy, PolicyGate, Principal
from ..domain.refs import (
    DomainContractError,
    EntityRef,
    MAX_INTEGER,
    ObjectRef,
    canonical_json,
    uuid_string,
)
from ..domain.schemas import Actor
from ..domain.store import DomainStore, _writer
from ..runtime.budgets import BudgetBook, BudgetDispatchRequest
from ..runtime.ledger import (
    AttemptSpec,
    CommandConflict as RuntimeCommandConflict,
    DispatchPermit,
    OwnerIdentity,
    RevisionConflict,
    RuntimeLedger,
)
from ..runtime.worker_dispatch import DispatchOutcome
from ..runtime.worker_coordinator import SelectedDispatchReadCapability
from ..workers import broker


@dataclass(frozen=True, slots=True)
class DispatchAuthorization:
    principal: Principal
    grants: tuple[Grant, ...]
    resource_ref: EntityRef
    action: str
    purpose: str
    episode_id: str | None

    def __post_init__(self):
        if type(self.principal) is not Principal:
            raise TypeError("Dispatch authorization requires an exact principal")
        if (type(self.grants) is not tuple or not self.grants
                or len(self.grants) > 512
                or any(type(grant) is not Grant for grant in self.grants)
                or len({grant.id for grant in self.grants}) != len(self.grants)):
            raise TypeError("Dispatch authorization requires bounded exact grants")
        if type(self.resource_ref) is not EntityRef:
            raise TypeError("Dispatch authorization requires an immutable resource")
        if type(self.action) is not str or type(self.purpose) is not str:
            raise TypeError("Dispatch authorization action and purpose must be text")
        if self.episode_id is not None:
            uuid_string(self.episode_id)


class RootTransactionFatal(CommandCorrupt):
    """Business rollback occurred but an observed root clock floor could not persist."""

    error_code = "root_clock_watermark_failed"

    def __init__(self):
        super().__init__(
            "Root command rolled back, but its atomic clock watermark recovery could "
            "not be completed; further dispatch must remain blocked"
        )


def _same_callable(left, right):
    """Match one trusted callable without accepting a lookalike wrapper.

    Accessing an instance method twice creates distinct bound-method objects, so
    object identity alone is too strict.  The owning instance and underlying
    function must nevertheless be the exact same objects.
    """
    if left is right:
        return True
    return (
        getattr(left, "__self__", None) is getattr(right, "__self__", None)
        and getattr(left, "__func__", None) is not None
        and getattr(left, "__func__", None) is getattr(right, "__func__", None)
    )


class RootCommandCoordinator:
    """Coordinate one authenticated local dispatch in the canonical vault."""

    def __init__(self, *, domain_store, permission_host, permission_gate,
                 budget_book, runtime_ledger, registry, authenticate_session,
                 command_clock, event_clock):
        if type(domain_store) is not DomainStore:
            raise TypeError("Root commands require the exact initialized DomainStore")
        if (type(permission_host) is not HostPolicy
                or type(permission_gate) is not PolicyGate
                or permission_gate._host is not permission_host):
            raise TypeError("Root commands require one exact persistent permission gate")
        if type(budget_book) is not BudgetBook:
            raise TypeError("Root commands require an exact BudgetBook")
        if type(runtime_ledger) is not RuntimeLedger:
            raise TypeError("Root commands require an exact RuntimeLedger")
        if type(registry) is not CommandRegistry:
            raise TypeError("Root commands require a trusted CommandRegistry")
        if not all(callable(item) for item in
                   (authenticate_session, command_clock, event_clock)):
            raise TypeError("Root commands require trusted session and clock integrations")
        if not _same_callable(
                authenticate_session, permission_host._authenticate_session):
            raise TypeError(
                "Root commands and permission authority require the same session authenticator"
            )
        self._domain = domain_store
        self._permission_host = permission_host
        self._permission_gate = permission_gate
        self._budget = budget_book
        self._ledger = runtime_ledger
        self._registry = registry
        self._authenticate_session = authenticate_session
        self._command_clock = command_clock
        self._event_clock = event_clock
        self._clock_lock = RLock()
        self._last_command_now = None
        self._last_event_now = None
        self._fatal_inhibited = False
        self.path = domain_store.path
        self.vault_id = domain_store.vault_id
        self._assert_component_bindings()
        with _writer(), self._domain._connection(write=True) as db:
            _install_command_schema(db)
            _install_event_schema(db, self.vault_id)

    def _assert_component_bindings(self):
        storage = self._permission_host._storage
        if (self._permission_gate._host is not self._permission_host
                or not _same_callable(
                    self._authenticate_session,
                    self._permission_host._authenticate_session,
                )
                or storage is None or storage.domain_store is not self._domain
                or storage.path != self.path or storage.vault_id != self.vault_id
                or self._permission_host.vault_id != self.vault_id):
            raise TypeError("Permission authority is not bound to this exact vault")
        if (self._ledger._domain is not self._domain
                or self._ledger.vault_id != self.vault_id
                or self._ledger._domain.path != self.path):
            raise TypeError("Runtime ledger is not bound to this exact vault")
        book_domain = self._budget._domain
        if (type(book_domain) is not DomainStore
                or self._budget.path != self.path or book_domain.path != self.path
                or book_domain.data_dir != self._domain.data_dir
                or book_domain.vault_id != self.vault_id):
            raise TypeError("Budget book is not bound to this exact vault")
        try:
            canonical = os.stat(self.path, follow_symlinks=False)
            budget = os.stat(self._budget.path, follow_symlinks=False)
        except OSError as exc:
            raise TypeError("Canonical vault path is unavailable") from exc
        if ((canonical.st_dev, canonical.st_ino) != (budget.st_dev, budget.st_ino)
                or canonical.st_nlink != 1):
            raise TypeError("Root components do not share one canonical database inode")

    def _persist_observed_clock_watermarks(
            self, *, permission_floor, runtime_floor, budget_session_id,
            budget_floor):
        """Atomically preserve every authority/deadline clock seen before rollback."""
        if (type(permission_floor) is not int
                or (runtime_floor is None) != (budget_floor is None)
                or (runtime_floor is None) != (budget_session_id is None)):
            raise CommandCorrupt("Root clock recovery inputs are incomplete")
        with _writer(), self._domain._connection(write=True) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            self._assert_transaction(db)
            self._permission_host._persist_clock_watermark_in_transaction(
                db, permission_floor
            )
            if runtime_floor is not None:
                self._ledger._persist_clock_watermark_in_transaction(db, runtime_floor)
                self._budget._persist_clock_watermark_in_transaction(
                    db, budget_session_id, budget_floor
                )
        return None

    def _now(self, source, *, event):
        try:
            value = source()
        except Exception as exc:
            raise CommandInvalid("Trusted root command clock failed") from exc
        if type(value) is not int or not 0 <= value <= MAX_INTEGER:
            raise CommandInvalid("Trusted root command clock is invalid")
        with self._clock_lock:
            previous = self._last_event_now if event else self._last_command_now
            if previous is not None and value < previous:
                raise CommandInvalid("Trusted root command clock moved backwards")
            if event:
                self._last_event_now = value
            else:
                self._last_command_now = value
        return value

    def _command_now(self):
        return self._now(self._command_clock, event=False)

    def _event_now(self):
        return self._now(self._event_clock, event=True)

    @staticmethod
    def _after_stage(_stage, _db):
        """Deterministic failure-injection seam; production implementation is inert."""

    def _authenticated_actor(self, request, *, read, db=None):
        if (type(request) is not AuthenticatedRequest
                or request.is_read is not read
                or (not read and not request.csrf_verified)):
            raise CommandInvalid("Authenticated local request required")
        from .session import authenticate_in_transaction
        actor = (self._authenticate_session(request.session) if db is None else
                 authenticate_in_transaction(self._authenticate_session, request.session, db))
        if (type(actor) is not Actor or actor != request.session.actor
                or actor.kind != "human"):
            raise CommandInvalid("Command actor is not an authenticated local human")
        return actor

    def _assert_transaction(self, db):
        if type(db) is not sqlite3.Connection or not db.in_transaction:
            raise CommandInvalid("Root command requires an active SQLite transaction")
        databases = list(db.execute("PRAGMA database_list"))
        settings = {
            name: db.execute(f"PRAGMA {name}").fetchone()[0]
            for name in ("journal_mode", "synchronous", "fullfsync",
                         "foreign_keys", "trusted_schema")
        }
        if (db.row_factory is not sqlite3.Row or len(databases) != 1
                or databases[0]["name"] != "main"
                or Path(os.path.abspath(databases[0]["file"])) != self.path):
            raise CommandInvalid("Root command connection is not the canonical vault")
        if (type(settings["journal_mode"]) is not str
                or settings["journal_mode"].casefold() != "wal"
                or settings["synchronous"] != 2
                or settings["fullfsync"] != 1
                or settings["foreign_keys"] != 1
                or settings["trusted_schema"] != 0):
            raise CommandInvalid("Root command connection is not hardened")
        vaults = list(db.execute("SELECT vault_id FROM domain_vault LIMIT 2"))
        if len(vaults) != 1 or vaults[0]["vault_id"] != self.vault_id:
            raise CommandInvalid("Root command vault identity changed")
        if (db.execute(
                "SELECT 1 FROM api_commands WHERE vault_id<>? LIMIT 1",
                (self.vault_id,),
        ).fetchone() is not None or db.execute(
                "SELECT 1 FROM api_event_streams WHERE vault_id<>? LIMIT 1",
                (self.vault_id,),
        ).fetchone() is not None or db.execute(
                "SELECT 1 FROM api_event_envelopes WHERE vault_id<>? LIMIT 1",
                (self.vault_id,),
        ).fetchone() is not None):
            raise CommandInvalid("Cross-vault API state is not accepted")
        _assert_command_schema(db)
        _assert_event_schema(db, self.vault_id)
        self._ledger._assert_dispatch_schema(db)
        BudgetBook._assert_transaction_schema(db)

    def _validate_dispatch_bindings(self, db, envelope, authorization,
                                    attempt_id, owner, budget_request,
                                    route_profile_ref):
        if type(authorization) is not DispatchAuthorization:
            raise TypeError("Exact DispatchAuthorization required")
        if type(owner) is not OwnerIdentity:
            raise TypeError("Exact OwnerIdentity required")
        if type(budget_request) is not BudgetDispatchRequest:
            raise TypeError("Exact BudgetDispatchRequest required")
        if (type(route_profile_ref) is not EntityRef
                or route_profile_ref.kind != "runtime_profile"):
            raise TypeError("Exact runtime profile route binding required")
        uuid_string(attempt_id)
        if (authorization.action != "read"
                or authorization.purpose != "operational"
                or envelope.command_type != "attempt.dispatch" or envelope.target is None
                or envelope.target.kind != "attempt" or envelope.target.id != attempt_id):
            raise CommandInvalid("Dispatch command authority or target is not operational read")
        selected = tuple(
            grant for grant in authorization.grants
            if grant.id == envelope.arguments["grant_id"]
        )
        request_hash = sha256(canonical_json(budget_request.as_dict())).hexdigest()
        if (len(selected) != 1
                or selected[0].ref != authorization.resource_ref
                or envelope.arguments["resource_sha256"] != authorization.resource_ref.sha256
                or envelope.arguments["budget_request_sha256"] != request_hash):
            raise CommandInvalid("Dispatch command arguments changed their trusted bindings")

        row = self._ledger._load_attempt(db, attempt_id)
        snapshot = self._ledger._attempt_snapshot(row)
        if (envelope.expected_revision != snapshot["revision"]
                or envelope.target_hash != snapshot["object_ref"]["content_hash"]):
            raise CommandConflict("Dispatch target revision or content hash is stale")
        try:
            spec = AttemptSpec.from_dict(snapshot["spec"])
        except (DomainContractError, TypeError, ValueError) as exc:
            raise CommandInvalid("Dispatch attempt specification is invalid") from exc
        if (spec.attempt_id != attempt_id
                or spec.owner != owner
                or spec.envelope_ref != authorization.resource_ref
                or spec.reservation_id != budget_request.request_id
                or spec.budget_policy_ref != budget_request.policy_ref
                or spec.profile_ref != route_profile_ref):
            raise CommandInvalid("Dispatch dependencies do not match the frozen attempt")
        return selected, spec

    def execute_budgeted_dispatch(self, value, *, request, authorization,
                                  attempt_id, owner, budget_request,
                                  route_profile_ref, deadline):
        if type(deadline) is not broker.Deadline:
            raise TypeError("Root dispatch requires an exact route deadline")
        deadline.require()
        with self._clock_lock:
            if self._fatal_inhibited:
                raise RootTransactionFatal()
        self._assert_component_bindings()
        actor = self._authenticated_actor(request, read=False)
        envelope = value if type(value) is CommandEnvelope else \
            CommandEnvelope.from_mapping(value, self._registry)
        envelope = CommandEnvelope.from_bytes(envelope.body_bytes, self._registry)
        permission_attempted = False
        committed = False
        staged_permit = None
        staged_read_capability = None
        receipt = None
        permission_floor = None
        runtime_floor = None
        budget_floor = None
        clock_capture_failed = False
        with _writer():
            try:
                with self._clock_lock:
                    if self._fatal_inhibited:
                        raise RootTransactionFatal()
                with self._domain._connection(write=True) as db:
                    db.execute("PRAGMA trusted_schema=OFF")
                    self._assert_transaction(db)
                    actor = self._authenticated_actor(request, read=False, db=db)
                    existing = _existing_command(
                        db, vault_id=self.vault_id, envelope=envelope,
                        actor=actor, session=request.session,
                    )
                    if existing is not None:
                        return DispatchOutcome(existing, None, True, None)

                    now = self._command_now()
                    _insert_command_intent(
                        db, vault_id=self.vault_id, envelope=envelope,
                        actor=actor, session=request.session, now=now,
                    )
                    self._after_stage("command_intent", db)
                    selected, spec = self._validate_dispatch_bindings(
                        db, envelope, authorization, attempt_id, owner,
                        budget_request, route_profile_ref,
                    )
                    deadline.require()

                    permission_attempted = True
                    try:
                        self._permission_gate._authorize_in_transaction(
                            db,
                            authorization.principal,
                            authorization.resource_ref,
                            action=authorization.action,
                            purpose=authorization.purpose,
                            grants=selected,
                            episode_id=authorization.episode_id,
                        )
                    finally:
                        try:
                            permission_floor = \
                                self._permission_host._observed_clock_floor()
                        except BaseException:
                            clock_capture_failed = True
                    if clock_capture_failed:
                        raise CommandCorrupt(
                            "Root permission clock observation could not be captured"
                        )
                    self._after_stage("permission_verified", db)
                    deadline.require()

                    try:
                        staged_permit = \
                            self._ledger._stage_budgeted_send_intent_in_transaction(
                                db,
                                envelope.command_id,
                                attempt_id,
                                owner,
                                expected_revision=envelope.expected_revision,
                                budget_book=self._budget,
                                budget_request=budget_request,
                                principal=authorization.principal,
                                grant=selected[0],
                            )
                    except (RevisionConflict, RuntimeCommandConflict) as exc:
                        raise CommandConflict("Runtime dispatch state changed") from exc
                    finally:
                        try:
                            runtime_floor = self._ledger._observed_clock_floor()
                            budget_floor = self._budget._observed_clock_floor()
                        except BaseException:
                            clock_capture_failed = True
                    if clock_capture_failed:
                        raise CommandCorrupt(
                            "Root runtime clock observation could not be captured"
                        )
                    if type(staged_permit) is not DispatchPermit:
                        raise CommandConflict("Runtime dispatch intent was not newly committed")
                    staged_read_capability = SelectedDispatchReadCapability(
                        permit_id=staged_permit.permit_id,
                        command_id=staged_permit.command_id,
                        principal=authorization.principal,
                        grant=selected[0],
                        resource_ref=authorization.resource_ref,
                        purpose=authorization.purpose,
                        episode_id=authorization.episode_id,
                    )
                    self._after_stage("budget_and_send_intent", db)
                    deadline.require(dispatch_effect="may_have_started")

                    runtime_result = self._ledger._command_replay(
                        db,
                        envelope.command_id,
                        "commit_budgeted_send_intent",
                        canonical_json({
                            "attempt_id": attempt_id,
                            "owner": owner.as_dict(),
                            "expected_revision": envelope.expected_revision,
                            "budget_request": budget_request.as_dict(),
                            "principal_id": authorization.principal.id,
                            "grant_id": selected[0].id,
                        }),
                    )
                    if (type(runtime_result) is not dict
                            or runtime_result.get("intent_committed") is not True
                            or runtime_result.get("permit_id") != staged_permit.permit_id):
                        raise CommandInvalid("Runtime dispatch receipt is inconsistent")
                    attempt_ref = ObjectRef(
                        "attempt", attempt_id, runtime_result["revision"],
                        self._ledger._attempt_snapshot(
                            self._ledger._load_attempt(db, attempt_id)
                        )["object_ref"]["content_hash"],
                    )
                    event_stamp = _at_epoch(self._event_now())
                    roots = self._domain._read_roots(db)
                    event = _append_event_in_transaction(
                        db,
                        vault_id=self.vault_id,
                        observed_at_utc=event_stamp,
                        recorded_at_utc=event_stamp,
                        actor_kind="system",
                        actor_ref=roots.actor,
                        event_type="attempt.dispatched",
                        object_refs=(attempt_ref,),
                        correlation_id=envelope.command_id,
                        causation_id=None,
                        status="pending",
                        error_code=None,
                        public_metadata={"attempt_no": spec.attempt_no},
                        private_evidence_refs=(),
                        retention_class="core",
                        policy_ref=roots.access_policy,
                    )
                    event_cursor = _event_cursor_in_transaction(
                        db, vault_id=self.vault_id, sequence=event.sequence,
                        event_types=("attempt.dispatched",),
                    )
                    self._after_stage("public_event", db)
                    deadline.require(dispatch_effect="may_have_started")

                    receipt = _result(envelope, {
                        "state": "pending",
                        "event_cursor": event_cursor,
                        "links": {
                            "self": f"/api/v1/commands/{envelope.command_id}",
                            "events": "/api/v1/events/attempt.dispatched",
                        },
                        "object_ref": attempt_ref.as_dict(),
                        "revision": runtime_result["revision"],
                    })
                    _complete_command(
                        db, vault_id=self.vault_id, envelope=envelope,
                        receipt=receipt, now=self._command_now(),
                    )
                    if _existing_command(
                            db, vault_id=self.vault_id, envelope=envelope,
                            actor=actor, session=request.session) != receipt:
                        raise CommandInvalid("Command receipt failed final verification")
                    self._after_stage("command_receipt", db)
                    deadline.require(dispatch_effect="may_have_started")

                # The database commit succeeded. Keep the process writer lock until the
                # corresponding one-shot capability is visible, so a duplicate request
                # cannot overtake activation.
                committed = True
                self._ledger._activate_dispatch_permit(
                    staged_permit, budget_book=self._budget
                )
                return DispatchOutcome(
                    receipt,
                    staged_permit,
                    False,
                    staged_read_capability,
                )
            except BaseException:
                if permission_attempted and not committed:
                    try:
                        if clock_capture_failed or permission_floor is None:
                            raise CommandCorrupt("Root clock observation could not be captured")
                        self._persist_observed_clock_watermarks(
                            permission_floor=permission_floor,
                            runtime_floor=runtime_floor,
                            budget_session_id=(
                                budget_request.session_id if runtime_floor is not None else None
                            ),
                            budget_floor=budget_floor,
                        )
                    except BaseException:
                        # Do not chain or retain raw exceptions: storage/provider errors can
                        # contain paths or secret-bearing canaries. Revoke every extant
                        # process-local capability before inhibiting further root dispatch.
                        self._ledger._inhibit_all_dispatch()
                        with self._clock_lock:
                            self._fatal_inhibited = True
                        raise RootTransactionFatal() from None
                raise

    def read_events(self, *, request, after_cursor=None, event_types=(), limit=100):
        """Return one authenticated public-event page from one consistent snapshot."""
        self._assert_component_bindings()
        self._authenticated_actor(request, read=True)
        with self._domain._connection() as db:
            page = _read_events_in_transaction(
                db, vault_id=self.vault_id, after_cursor=after_cursor,
                event_types=event_types, limit=limit,
            )
        # Do not release a projection if the bound session expired or was revoked
        # while the consistent SQLite snapshot was being materialized.
        self._authenticated_actor(request, read=True)
        if type(page) is not EventPage:  # pragma: no cover - internal invariant
            raise CommandInvalid("Public event reader returned an invalid page")
        return page
