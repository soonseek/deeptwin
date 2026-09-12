"""Authenticated versioned HTTP projections over the canonical local vault.

This module is deliberately a delivery boundary.  It initializes the local domain,
permission, budget, runtime and command/event journals, but it owns no provider or tool
dispatcher.  A production app with no trusted runtime resolver therefore remains
fail-closed: a syntactically valid dispatch command receives an explicit dependency
error before any command, reservation, event, or process-local permit is created.
"""

import json
import sqlite3
import time
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ..domain.permissions import (
    AccessDenied,
    CorruptPolicy,
    HostPolicy,
    PolicyGate,
    create_persistent_policy,
)
from ..domain.refs import DomainContractError, EntityRef, positive_integer, uuid_string
from ..domain.store import (
    AlreadyInitialized,
    CorruptRecord,
    DomainStore,
    StorageError,
    UninitializedVault,
    _writer,
)
from ..runtime.budgets import (
    BudgetBook,
    BudgetDispatchRequest,
    BudgetError,
    CorruptBudget,
)
from ..runtime.ledger import (
    PHASES,
    CorruptLedger,
    LedgerError,
    OwnerIdentity,
    RuntimeLedger,
)
from ..runtime.worker_dispatch import (
    DispatchAcceptance,
    DispatchOutcome,
    WorkerDispatchBusy,
    WorkerDispatchService,
    WorkerDispatchServiceSlot,
    WorkerDispatchUnavailable,
    _inhibit_runtime_dispatch,
)
from ..workers import broker
from .commands import (
    ArgField,
    CommandConflict,
    CommandCorrupt,
    CommandDefinition,
    CommandEnvelope,
    CommandInvalid,
    CommandOutcomeUnknown,
    CommandRegistry,
    _existing_command,
)
from .session import AuthenticatedRequest, RequestDenied
from .transaction import (
    DispatchAuthorization,
    RootCommandCoordinator,
    RootTransactionFatal,
)
from .views import (
    CursorMismatch,
    EventCorrupt,
    EventInvalid,
    _assert_event_schema,
    _cursor_for,
    _event_stream,
    _filter,
    render_sse,
)

MAX_SNAPSHOT_ITEMS = 10_000
MAX_QUERY_BYTES = 8_192
MAX_COMMAND_ROUTE_MS = 30_000
RETRYABLE = "retryable"
NOT_RETRYABLE = "not_retryable"


class ApiInputError(ValueError):
    pass


class ApiDependencyUnavailable(RuntimeError):
    pass


class ApiNotFound(LookupError):
    pass


class ApiCommittedDispatchUnknown(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedDispatch:
    """Exact trusted values a host runtime must resolve outside browser input."""

    authorization: DispatchAuthorization
    attempt_id: str
    owner: OwnerIdentity
    budget_request: BudgetDispatchRequest
    route_profile_ref: EntityRef

    def __post_init__(self):
        if (type(self.authorization) is not DispatchAuthorization
                or type(self.owner) is not OwnerIdentity
                or type(self.budget_request) is not BudgetDispatchRequest
                or type(self.route_profile_ref) is not EntityRef
                or self.route_profile_ref.kind != "runtime_profile"):
            raise TypeError("Runtime resolver returned an invalid dispatch context")
        uuid_string(self.attempt_id)


@dataclass(frozen=True, slots=True)
class ApiV1Components:
    domain_store: DomainStore
    permission_host: HostPolicy
    permission_gate: PolicyGate
    budget_book: BudgetBook
    runtime_ledger: RuntimeLedger
    root_commands: RootCommandCoordinator

    def __post_init__(self):
        if (type(self.domain_store) is not DomainStore
                or type(self.permission_host) is not HostPolicy
                or type(self.permission_gate) is not PolicyGate
                or type(self.budget_book) is not BudgetBook
                or type(self.runtime_ledger) is not RuntimeLedger
                or type(self.root_commands) is not RootCommandCoordinator
                or self.permission_gate._host is not self.permission_host
                or self.root_commands._domain is not self.domain_store
                or self.root_commands._permission_host is not self.permission_host
                or self.root_commands._permission_gate is not self.permission_gate
                or self.root_commands._budget is not self.budget_book
                or self.root_commands._ledger is not self.runtime_ledger):
            raise TypeError("Versioned API components do not share one root authority")


def command_registry():
    """Trusted command vocabulary; browser content cannot add command kinds."""
    return CommandRegistry((
        CommandDefinition(
            "attempt.dispatch",
            target_kind="attempt",
            revision="required",
            target_hash="required",
            arguments=(
                ArgField("grant_id", "uuid"),
                ArgField("resource_sha256", "sha256"),
                ArgField("budget_request_sha256", "sha256"),
            ),
        ),
    ))


def _epoch_seconds():
    return time.time_ns() // 1_000_000_000


def _epoch_milliseconds():
    return time.time_ns() // 1_000_000


def initialize_api_v1(legacy_store, sessions):
    """Install/reopen additive state in the exact existing intake database."""
    domain = DomainStore(legacy_store)
    try:
        domain.roots()
    except UninitializedVault:
        try:
            domain.initialize_vault()
        except AlreadyInitialized:
            # A second process may have completed the single atomic bootstrap.
            domain.roots()

    permission_host, permission_gate = create_persistent_policy(
        domain,
        authenticate_session=sessions.authenticate_bound,
        # A projection is never accepted merely because the server was started.
        # A later reviewed compiler integration must supply its semantic verifier.
        verify_projection=lambda _projection: False,
        clock=_epoch_seconds,
    )
    budget = BudgetBook(legacy_store, clock=_epoch_seconds)
    runtime = RuntimeLedger(domain, clock_ms=_epoch_milliseconds)
    root = RootCommandCoordinator(
        domain_store=domain,
        permission_host=permission_host,
        permission_gate=permission_gate,
        budget_book=budget,
        runtime_ledger=runtime,
        registry=command_registry(),
        authenticate_session=sessions.authenticate_bound,
        command_clock=_epoch_milliseconds,
        event_clock=_epoch_seconds,
    )
    return ApiV1Components(
        domain, permission_host, permission_gate, budget, runtime, root,
    )


def api_error(*, status, code, message, retryability=NOT_RETRYABLE):
    """Create the fixed public error schema without reflecting exception text."""
    return JSONResponse(
        {
            "code": code,
            "message": message,
            "retryability": retryability,
            "affected_refs": [],
            "correlation_id": str(uuid4()),
        },
        status_code=status,
    )


def _json_object_without_duplicate_keys(raw):
    def exact_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ApiInputError("Duplicate JSON field")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=exact_object)
    except (ApiInputError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ApiInputError("Invalid JSON command") from exc
    if type(value) is not dict:
        raise ApiInputError("Command body must be an object")
    return value


async def _command_envelope(request, registry):
    if request.query_params:
        raise ApiInputError("Command query fields are not accepted")
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise ApiInputError("Command content type must be JSON")
    raw = await request.body()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiInputError("Command body is not UTF-8") from exc
    try:
        return CommandEnvelope.from_mapping(
            _json_object_without_duplicate_keys(text), registry
        )
    except (CommandInvalid, DomainContractError, TypeError, ValueError) as exc:
        raise ApiInputError("Command envelope is invalid") from exc


def _authenticated(request, *, read):
    value = request.scope.get("state", {}).get("authenticated_request")
    if (type(value) is not AuthenticatedRequest or value.is_read is not read
            or (not read and not value.csrf_verified)):
        raise RequestDenied("Authenticated local request required")
    return value


def _header_singleton(request, name):
    expected = name.casefold().encode("ascii")
    values = []
    for raw_name, raw_value in request.scope.get("headers", ()):
        if raw_name.lower() != expected:
            continue
        try:
            values.append(raw_value.decode("ascii"))
        except UnicodeDecodeError as exc:
            raise ApiInputError("Event cursor header is invalid") from exc
    if len(values) > 1:
        raise ApiInputError("Event cursor header is duplicated")
    return values[0] if values else None


def _event_options(request, *, path_event_type=None):
    pairs = list(request.query_params.multi_items())
    if (sum(len(key) + len(value) for key, value in pairs) > MAX_QUERY_BYTES
            or any(key not in {"cursor", "event_type", "limit"} for key, _ in pairs)):
        raise ApiInputError("Event query is invalid")
    cursors = [value for key, value in pairs if key == "cursor"]
    limits = [value for key, value in pairs if key == "limit"]
    event_types = tuple(value for key, value in pairs if key == "event_type")
    if path_event_type is not None:
        if event_types:
            raise ApiInputError("Event filter is duplicated")
        event_types = (path_event_type,)
    header_cursor = _header_singleton(request, "last-event-id")
    if len(cursors) > 1 or len(limits) > 1 or (cursors and header_cursor is not None):
        raise ApiInputError("Event cursor or limit is duplicated")
    cursor = cursors[0] if cursors else header_cursor
    raw_limit = limits[0] if limits else "100"
    if (not raw_limit.isascii() or not raw_limit.isdecimal()
            or raw_limit != str(int(raw_limit)) or not 1 <= int(raw_limit) <= 100):
        raise ApiInputError("Event limit is invalid")
    try:
        # Validate the filter here so a route error never reflects the supplied value.
        _filter(event_types)
    except EventInvalid as exc:
        raise ApiInputError("Event filter is invalid") from exc
    return cursor, event_types, int(raw_limit)


def _page_body(page):
    return {
        "events": [event.as_dict() for event in page.events],
        "next_cursor": page.next_cursor,
        "snapshot_required": page.snapshot_required,
        "gap": None if page.gap is None else page.gap.as_dict(),
        "links": {"snapshot": "/api/v1/snapshot"},
    }


def _snapshot(root, request):
    """Materialize public state and its tail cursor in one SQLite read snapshot."""
    root._assert_component_bindings()
    root._authenticated_actor(request, read=True)
    with root._domain._connection() as db:
        _assert_event_schema(db, root.vault_id)
        counts = {
            "works": db.execute("SELECT count(*) FROM works").fetchone()[0],
            "runs": db.execute(
                "SELECT count(*) FROM runtime_runs WHERE vault_id=?", (root.vault_id,)
            ).fetchone()[0],
            "attempts": db.execute(
                "SELECT count(*) FROM runtime_attempts WHERE vault_id=?", (root.vault_id,)
            ).fetchone()[0],
        }
        if (any(type(value) is not int or not 0 <= value <= MAX_SNAPSHOT_ITEMS
                for value in counts.values())):
            raise ApiDependencyUnavailable("Public snapshot item bound exceeded")
        work_rows = list(db.execute(
                "SELECT works.id,works.revision,count(files.id) AS file_count "
                "FROM works LEFT JOIN files ON files.work_id=works.id "
                "GROUP BY works.id,works.revision ORDER BY works.rowid"
            ))
        run_rows = list(db.execute(
            "SELECT id,phase,revision FROM runtime_runs WHERE vault_id=? ORDER BY rowid",
            (root.vault_id,),
        ))
        attempt_rows = list(db.execute(
            "SELECT id,phase,revision FROM runtime_attempts WHERE vault_id=? ORDER BY rowid",
            (root.vault_id,),
        ))
        if (len(work_rows) != counts["works"] or len(run_rows) != counts["runs"]
                or len(attempt_rows) != counts["attempts"]):
            raise EventCorrupt("Public snapshot count changed within its read")
        try:
            for row in work_rows:
                uuid_string(row["id"])
                positive_integer(row["revision"])
                if (type(row["file_count"]) is not int
                        or not 0 <= row["file_count"] <= 20):
                    raise DomainContractError("Invalid public file count")
            for row in run_rows:
                uuid_string(row["id"])
                positive_integer(row["revision"])
                if row["phase"] != "created":
                    raise DomainContractError("Invalid public run phase")
            for row in attempt_rows:
                uuid_string(row["id"])
                positive_integer(row["revision"])
                if row["phase"] not in PHASES:
                    raise DomainContractError("Invalid public attempt phase")
        except (DomainContractError, TypeError, KeyError) as exc:
            raise EventCorrupt("Stored public snapshot state is invalid") from exc
        works = [
            {"id": row["id"], "revision": row["revision"], "file_count": row["file_count"]}
            for row in work_rows
        ]
        runs = [
            {"id": row["id"], "phase": row["phase"], "revision": row["revision"]}
            for row in run_rows
        ]
        attempts = [
            {"id": row["id"], "phase": row["phase"], "revision": row["revision"]}
            for row in attempt_rows
        ]
        stream = _event_stream(db, root.vault_id)
        _, filter_hash = _filter(())
        cursor = _cursor_for(
            root.vault_id, stream, stream["next_sequence"] - 1, filter_hash
        )
        value = {
            "snapshot_version": "public-snapshot-v1",
            "event_cursor": cursor,
            "state": {"works": works, "runs": runs, "attempts": attempts},
            "links": {"events": "/api/v1/events"},
        }
    root._authenticated_actor(request, read=True)
    return value


def _stored_command_receipt(root, envelope, request, *, synchronize=False):
    """Read an exact durable replay without resolving or minting dispatch authority."""
    def read_once():
        root._assert_component_bindings()
        actor = root._authenticated_actor(request, read=False)
        with root._domain._connection() as db:
            db.execute("PRAGMA trusted_schema=OFF")
            root._assert_transaction(db)
            receipt = _existing_command(
                db,
                vault_id=root.vault_id,
                envelope=envelope,
                actor=actor,
                session=request.session,
            )
        # A session expiring or being revoked during the read cannot receive its receipt.
        root._authenticated_actor(request, read=False)
        return receipt

    if synchronize:
        # Wait behind any in-process root writer before the resolver-failure recheck.
        # This closes the race where the first read precedes another request's commit,
        # while retaining SQLite as the durable truth and performing no mutation here.
        with _writer():
            return read_once()
    return read_once()


def _receipt_response(receipt):
    return JSONResponse(
        receipt,
        status_code=202 if receipt.get("state") == "pending" else 200,
    )


def _stored_command_status(root, command_id, request):
    """Read one same-actor, same-session command and current transport projection."""
    try:
        uuid_string(command_id)
    except (DomainContractError, TypeError, ValueError):
        raise ApiNotFound() from None
    root._assert_component_bindings()
    actor = root._authenticated_actor(request, read=True)
    with root._domain._connection() as db:
        db.execute("PRAGMA trusted_schema=OFF")
        root._assert_transaction(db)
        row = db.execute(
            "SELECT * FROM api_commands WHERE vault_id=? AND command_id=?",
            (root.vault_id, command_id),
        ).fetchone()
        if (
            row is None
            or row["actor_id"] != actor.id
            or row["session_id"] != request.session.session_id
        ):
            raise ApiNotFound()
        try:
            envelope = CommandEnvelope.from_bytes(bytes(row["payload"]), root._registry)
        except (CommandInvalid, DomainContractError, TypeError, ValueError) as exc:
            raise CommandCorrupt("Stored command payload is corrupt") from exc
        receipt = _existing_command(
            db,
            vault_id=root.vault_id,
            envelope=envelope,
            actor=actor,
            session=request.session,
        )
        if receipt is None:
            raise CommandOutcomeUnknown("Command outcome is not durable")
    if envelope.target is None or envelope.target.kind != "attempt":
        raise CommandCorrupt("Stored dispatch target is invalid")
    transport = root._ledger.dispatch_status(command_id)
    attempt = transport["attempt"]
    if attempt["spec"]["attempt_id"] != envelope.target.id:
        raise CommandCorrupt("Stored command target binding changed")
    root._authenticated_actor(request, read=True)
    return {
        "command_id": command_id,
        "state": transport["state"],
        "object_ref": attempt["object_ref"],
        "revision": attempt["revision"],
        "dispatch": transport["dispatch"],
        "event_cursor": receipt["event_cursor"],
        "links": receipt["links"].copy(),
    }


def _reserve_execute_and_handoff(root, dispatcher, envelope, authenticated,
                                 resolved, deadline):
    """Own capacity, root commit, and handoff in one synchronous boundary."""
    reservation = None

    def release_reservation():
        nonlocal reservation
        if reservation is None:
            return True
        current = reservation
        try:
            # Bypass an accidentally shadowed public instance method.  This helper
            # owns the reservation until exact acceptance or exact release.
            WorkerDispatchService.release(dispatcher, current)
        except BaseException:  # noqa: BLE001 - cleanup covers task/process cancellation
            try:
                if type(dispatcher) is not WorkerDispatchService:
                    return False
                with dispatcher._condition:
                    if dispatcher._held(current):
                        dispatcher._reservations.pop(current._slot_token)
                        dispatcher._occupied[current.profile_ref] -= 1
                        dispatcher._condition.notify_all()
                    released = not dispatcher._held(current)
            except BaseException:  # noqa: BLE001 - inspect only the exact local holder
                return False
            if not released:
                return False
        reservation = None
        return True

    def inhibit_dispatch():
        return _inhibit_runtime_dispatch(root._ledger)

    try:
        deadline.require()
        reservation = dispatcher.reserve(
            envelope.command_id,
            resolved.route_profile_ref,
            deadline=deadline,
        )
        deadline.require()
    except BaseException:
        # A duplicate may have committed while this helper waited for its exact
        # dispatcher or writer boundary.  Recheck while this same synchronous
        # owner still controls any reservation it acquired.
        try:
            replay = _stored_command_receipt(
                root,
                envelope,
                authenticated,
                synchronize=True,
            )
        except BaseException:
            release_reservation()
            raise
        if replay is not None:
            if not release_reservation():
                inhibit_dispatch()
                raise WorkerDispatchUnavailable() from None
            return DispatchOutcome(replay, None, True, None)
        if not release_reservation():
            inhibit_dispatch()
            raise WorkerDispatchUnavailable() from None
        raise

    try:
        outcome = root.execute_budgeted_dispatch(
            envelope,
            request=authenticated,
            authorization=resolved.authorization,
            attempt_id=resolved.attempt_id,
            owner=resolved.owner,
            budget_request=resolved.budget_request,
            route_profile_ref=resolved.route_profile_ref,
            deadline=deadline,
        )
    except BaseException:
        try:
            committed_receipt = _stored_command_receipt(
                root,
                envelope,
                authenticated,
                synchronize=True,
            )
        except BaseException:  # noqa: BLE001 - unreadable commit truth is unknown
            # The root may have committed before capability activation failed.
            # When the synchronized durable truth cannot be read, the only
            # honest result is unknown and process-wide dispatch inhibition.
            release_reservation()
            inhibit_dispatch()
            raise ApiCommittedDispatchUnknown() from None
        if committed_receipt is not None:
            release_reservation()
            inhibit_dispatch()
            raise ApiCommittedDispatchUnknown() from None
        if not release_reservation():
            inhibit_dispatch()
            raise WorkerDispatchUnavailable() from None
        raise
    if type(outcome) is not DispatchOutcome:
        release_reservation()
        inhibit_dispatch()
        raise ApiCommittedDispatchUnknown() from None
    if outcome.replayed:
        if not release_reservation():
            inhibit_dispatch()
            raise WorkerDispatchUnavailable() from None
        return outcome
    try:
        bound_accept = getattr(dispatcher, "accept", None)
        if (
            getattr(bound_accept, "__self__", None) is not dispatcher
            or getattr(bound_accept, "__func__", None)
            is not WorkerDispatchService.accept
        ):
            raise WorkerDispatchUnavailable()
        acceptance = WorkerDispatchService.accept(
            dispatcher,
            reservation,
            outcome,
            deadline=deadline,
        )
        if (
            type(acceptance) is not DispatchAcceptance
            or acceptance.command_id != outcome.permit.command_id
            or acceptance.permit_id != outcome.permit.permit_id
            or acceptance.profile_ref != reservation.profile_ref
            or acceptance.deadline is not deadline
        ):
            raise WorkerDispatchUnavailable()
        bound_claim = getattr(dispatcher, "claim_acceptance", None)
        if (
            getattr(bound_claim, "__self__", None) is not dispatcher
            or getattr(bound_claim, "__func__", None)
            is not WorkerDispatchService.claim_acceptance
        ):
            raise WorkerDispatchUnavailable()
        claimed = WorkerDispatchService.claim_acceptance(
            dispatcher,
            acceptance,
            reservation,
            outcome,
            deadline=deadline,
        )
        with dispatcher._condition:
            registration_consumed = (
                reservation._slot_token not in dispatcher._issued_acceptances
            )
        if (
            claimed is not acceptance
            or not registration_consumed
            or not DispatchAcceptance._is_claimed_for(
                acceptance,
                service_token=dispatcher._service_token,
                slot_token=reservation._slot_token,
                permit=outcome.permit,
                deadline=deadline,
            )
        ):
            raise WorkerDispatchUnavailable()
    except BaseException:  # noqa: BLE001 - handoff crash after commit is unknown
        # An unverifiable queue transfer is process-wide unknown even if a worker
        # raced ahead.  Purging the permit prevents a silent no-op from retaining
        # external-send authority.
        try:
            WorkerDispatchService.quarantine(dispatcher, reservation, outcome)
        except BaseException:  # noqa: BLE001 - fallback still purges global authority
            release_reservation()
        inhibit_dispatch()
        raise ApiCommittedDispatchUnknown() from None
    # accept() consumed the exact reservation into the bounded worker queue.
    reservation = None
    return outcome


def _head_response(*, cursor, snapshot_required=False,
                   media_type="application/json"):
    return Response(
        status_code=200,
        media_type=media_type,
        headers={
            "X-DeepTwin-Event-Cursor": cursor,
            "X-DeepTwin-Snapshot-Required": (
                "true" if snapshot_required else "false"
            ),
        },
    )


def _known_failure(exc):
    if isinstance(exc, (ApiInputError, CommandInvalid, EventInvalid, CursorMismatch)):
        return 400, "invalid_input", "요청 형식이나 커서를 확인해 주세요.", NOT_RETRYABLE
    if isinstance(exc, (ApiNotFound, KeyError)):
        return 404, "not_found", "요청한 API 대상을 찾지 못했습니다.", NOT_RETRYABLE
    if isinstance(exc, RequestDenied):
        return 401, "unauthenticated", "브라우저 세션이 만료됐습니다. DeepTwin 인스턴스에서 다시 열어 주세요.", NOT_RETRYABLE
    if isinstance(exc, AccessDenied):
        return 403, "access_denied", "현재 권한이나 동의로는 이 작업을 수행할 수 없습니다.", NOT_RETRYABLE
    if isinstance(exc, CommandConflict):
        return 409, "stale_state", "대상 상태가 변경되었습니다. 최신 상태를 확인해 주세요.", NOT_RETRYABLE
    if isinstance(exc, CommandOutcomeUnknown):
        return 409, "outcome_unknown", "이 명령의 외부 결과를 먼저 확인해야 합니다.", NOT_RETRYABLE
    if isinstance(exc, ApiCommittedDispatchUnknown):
        return 409, "outcome_unknown", "명령은 기록됐지만 작업자 전달 결과를 확인해야 합니다.", NOT_RETRYABLE
    if isinstance(exc, BudgetError) and not isinstance(exc, CorruptBudget):
        return 429, "budget_exhausted", "설정된 실행 한도 때문에 요청을 시작하지 않았습니다.", NOT_RETRYABLE
    if isinstance(exc, (WorkerDispatchBusy, broker.BrokerBusy)):
        return 429, "dispatch_busy", "실행 대기열이 가득 찼습니다. 잠시 후 다시 시도해 주세요.", RETRYABLE
    if isinstance(exc, (
            ApiDependencyUnavailable, RootTransactionFatal,
            WorkerDispatchUnavailable, broker.BrokerError)):
        return 503, "dependency_unavailable", "실행 준비 정보가 없어 요청을 시작하지 않았습니다.", NOT_RETRYABLE
    if isinstance(exc, (
            CommandCorrupt, EventCorrupt, CorruptPolicy, CorruptBudget, CorruptLedger,
            CorruptRecord, StorageError, LedgerError, sqlite3.Error, OSError)):
        return 503, "storage_failed", "로컬 상태를 안전하게 확인하지 못했습니다.", RETRYABLE
    return 503, "dependency_unavailable", "필요한 로컬 구성 요소를 사용할 수 없습니다.", RETRYABLE


def _failure(exc):
    status, code, message, retryability = _known_failure(exc)
    return api_error(
        status=status, code=code, message=message, retryability=retryability,
    )


def install_api_v1(app, *, components, runtime_dispatch_resolver=None,
                   worker_dispatch_slot=None):
    """Attach delivery routes.

    ``runtime_dispatch_resolver`` is trusted host wiring, never page/model input. It must
    only resolve already-frozen local capabilities and must not mutate state or perform an
    external action; the root coordinator remains the sole mutation/permit boundary.
    """
    if type(components) is not ApiV1Components:
        raise TypeError("Versioned API requires exact initialized components")
    if runtime_dispatch_resolver is not None and not callable(runtime_dispatch_resolver):
        raise TypeError("Runtime dispatch resolver must be a trusted callable")
    if worker_dispatch_slot is not None and type(
            worker_dispatch_slot) is not WorkerDispatchServiceSlot:
        raise TypeError("Worker dispatcher slot must be an exact managed binding")
    root = components.root_commands
    registry = root._registry

    @app.api_route("/api/v1/events", methods=["GET", "HEAD"])
    def events_v1(request: Request):
        try:
            authenticated = _authenticated(request, read=True)
            cursor, event_types, limit = _event_options(request)
            page = root.read_events(
                request=authenticated,
                after_cursor=cursor,
                event_types=event_types,
                limit=limit,
            )
            if request.method == "HEAD":
                return _head_response(
                    cursor=page.next_cursor,
                    snapshot_required=page.snapshot_required,
                )
            return _page_body(page)
        except Exception as exc:  # noqa: BLE001 - sanitize the public delivery boundary
            return _failure(exc)

    @app.api_route("/api/v1/events/stream", methods=["GET", "HEAD"])
    def event_stream_v1(request: Request):
        try:
            authenticated = _authenticated(request, read=True)
            cursor, event_types, limit = _event_options(request)
            page = root.read_events(
                request=authenticated,
                after_cursor=cursor,
                event_types=event_types,
                limit=limit,
            )
            if request.method == "HEAD":
                return _head_response(
                    cursor=page.next_cursor,
                    snapshot_required=page.snapshot_required,
                    media_type="text/event-stream",
                )
            return Response(
                render_sse(page),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "X-DeepTwin-Event-Cursor": page.next_cursor,
                },
            )
        except Exception as exc:  # noqa: BLE001 - sanitize the public delivery boundary
            return _failure(exc)

    @app.api_route("/api/v1/events/{event_type}", methods=["GET", "HEAD"])
    def events_by_type_v1(event_type: str, request: Request):
        """Path-filtered JSON surface used by durable command receipt links."""
        try:
            authenticated = _authenticated(request, read=True)
            cursor, event_types, limit = _event_options(
                request, path_event_type=event_type,
            )
            page = root.read_events(
                request=authenticated,
                after_cursor=cursor,
                event_types=event_types,
                limit=limit,
            )
            if request.method == "HEAD":
                return _head_response(
                    cursor=page.next_cursor,
                    snapshot_required=page.snapshot_required,
                )
            return _page_body(page)
        except Exception as exc:  # noqa: BLE001 - sanitize the public delivery boundary
            return _failure(exc)

    @app.api_route("/api/v1/snapshot", methods=["GET", "HEAD"])
    def snapshot_v1(request: Request):
        try:
            if request.query_params:
                raise ApiInputError("Snapshot query fields are not accepted")
            authenticated = _authenticated(request, read=True)
            snapshot = _snapshot(root, authenticated)
            if request.method == "HEAD":
                return _head_response(cursor=snapshot["event_cursor"])
            return snapshot
        except Exception as exc:  # noqa: BLE001 - sanitize the public delivery boundary
            return _failure(exc)

    @app.api_route("/api/v1/commands/{command_id}", methods=["GET", "HEAD"])
    def command_status_v1(command_id: str, request: Request):
        try:
            if request.query_params:
                raise ApiInputError("Command status query fields are not accepted")
            authenticated = _authenticated(request, read=True)
            status = _stored_command_status(root, command_id, authenticated)
            if request.method == "HEAD":
                return Response(
                    status_code=200,
                    media_type="application/json",
                    headers={
                        "X-DeepTwin-Command-State": status["state"],
                        "X-DeepTwin-Dispatch-State": status["dispatch"]["state"],
                    },
                )
            return status
        except Exception as exc:  # noqa: BLE001 - sanitize the public delivery boundary
            return _failure(exc)

    @app.post("/api/v1/commands")
    async def commands_v1(request: Request):
        try:
            deadline = broker.Deadline.after_ms(MAX_COMMAND_ROUTE_MS)
            authenticated = _authenticated(request, read=False)
            envelope = await _command_envelope(request, registry)
            deadline.require()
            replay = await run_in_threadpool(
                _stored_command_receipt, root, envelope, authenticated,
            )
            deadline.require()
            if replay is not None:
                return _receipt_response(replay)
            if runtime_dispatch_resolver is None:
                replay = await run_in_threadpool(
                    _stored_command_receipt,
                    root,
                    envelope,
                    authenticated,
                    synchronize=True,
                )
                if replay is not None:
                    return _receipt_response(replay)
                raise ApiDependencyUnavailable("No trusted runtime dispatch resolver")
            try:
                resolved = await run_in_threadpool(
                    runtime_dispatch_resolver, envelope, authenticated,
                    deadline=deadline,
                )
            except Exception:
                # Another local request may have committed the same command while this
                # resolver failed.  A fresh read can return only its exact same-session
                # receipt; mismatch and unknown-outcome states still fail closed.
                replay = await run_in_threadpool(
                    _stored_command_receipt, root, envelope, authenticated,
                    synchronize=True,
                )
                if replay is not None:
                    return _receipt_response(replay)
                raise
            if type(resolved) is not ResolvedDispatch:
                replay = await run_in_threadpool(
                    _stored_command_receipt, root, envelope, authenticated,
                    synchronize=True,
                )
                if replay is not None:
                    return _receipt_response(replay)
                raise ApiDependencyUnavailable("Runtime dispatch context unavailable")
            try:
                deadline.require()
                if worker_dispatch_slot is None:
                    raise ApiDependencyUnavailable("No managed worker dispatcher")
                worker_dispatch_service = worker_dispatch_slot.current()
            except Exception:
                replay = await run_in_threadpool(
                    _stored_command_receipt,
                    root,
                    envelope,
                    authenticated,
                    synchronize=True,
                )
                if replay is not None:
                    return _receipt_response(replay)
                raise
            outcome = await run_in_threadpool(
                _reserve_execute_and_handoff,
                root,
                worker_dispatch_service,
                envelope,
                authenticated,
                resolved,
                deadline,
            )
            return _receipt_response(outcome.receipt)
        except Exception as exc:  # noqa: BLE001 - sanitize the public delivery boundary
            return _failure(exc)
