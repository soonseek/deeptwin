"""Fixed HTTP adapter for the owner's design workspace: the `design-workspace-v1`
contribution (T037).

- `GET /api/v1/design-requests` lists the design requests this instance serves (persisted
  requests are rebuilt from their stored records first; what cannot be rebuilt is listed
  with its reason) and whether a request can be created here (`creation`).
- `POST /api/v1/design-requests` (T038) creates a design request from the owner's accepted
  work model, only where a qualified lens decision exists, or answers `not_designable`
  with the exact reason.
- `GET /api/v1/design-requests/{request_id}` reads one request's honest selection pool:
  presented candidates with their graphs and recorded verdicts, every exclusion with
  its reason, the real count, derived versions, and whether review and preparation
  are available (and why not).
- `POST …/derivations` selects, edits (with an instruction) or merges (two or more
  parents) into a new design version that requires re-review and inherits no verdict.
- `POST …/reviews` re-reviews one derived version, only through a configured critic.
- `POST …/preparations` attempts approval and environment preparation of one exact
  reviewed design, or answers the exact refusal.
- `POST …/generations` (T038) runs the design arc — bounded rounds of generation and
  criticism through the host's registered model turns — or answers
  `generation_unavailable` with the reason.
- `POST …/cancellations` (T038) asks a running generation to stop before its next
  model call.

The shared `/api/v1` preflight admits each body exactly before auth; commands are
CSRF-verified owner acts (the service re-checks the live session).
"""

import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.design_workspace import (
    CANCEL_SCHEMA,
    CREATE_SCHEMA,
    DERIVE_SCHEMA,
    GENERATE_SCHEMA,
    PREPARE_SCHEMA,
    REVIEW_SCHEMA,
    DesignWorkspaceError,
    PersistentDesignWorkspace,
)
from ..services.owner_auth import OwnerAuthError
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

ROOT = "/api/v1/design-requests"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404,
          "conflict": 409, "not_approvable": 409, "unavailable": 503, "review_unavailable": 503,
          "generation_unavailable": 503, "not_designable": 409, "not_restorable": 409}
_LIMITS = WireLimits(max_bytes=8_192, max_depth=3, max_items=16, max_members=8, max_string_bytes=4_096)
_COMMANDS = {
    "derivations": (DERIVE_SCHEMA, ("schema_version", "command_id", "action", "parent_candidate_ids",
                                    "instruction")),
    "reviews": (REVIEW_SCHEMA, ("schema_version", "command_id", "derivation_id")),
    "preparations": (PREPARE_SCHEMA, ("schema_version", "command_id", "candidate_id")),
    "generations": (GENERATE_SCHEMA, ("schema_version", "command_id", "max_rounds")),
    "cancellations": (CANCEL_SCHEMA, ("schema_version", "command_id")),
    "create": (CREATE_SCHEMA, ("schema_version", "command_id", "work_model_id")),
}
MESSAGES = {
    "not_designable": "A design request cannot be created for this work model",
    "not_restorable": "This design request cannot be rebuilt from its stored records",
    "review_unavailable": "Design review is not available",
    "not_approvable": "This design cannot be approved or prepared",
    "generation_unavailable": "Design generation is not available",
}


def is_design_workspace_path(path: str) -> bool:
    return path == ROOT or path.startswith(ROOT + "/")


def _body(kind: str, raw: bytes) -> dict:
    schema, fields = _COMMANDS[kind]
    value = parse_json_object(raw, required=fields, limits=_LIMITS)
    if set(value) != set(fields) or value["schema_version"] != schema:
        raise WireInputError("invalid_input")
    return value


def preflight(scope, body):
    parse_query(scope.get("query_string", b""), allowed=())
    path, method = scope["path"], scope["method"]
    parts = [] if path == ROOT else path[len(ROOT) + 1:].split("/")
    if len(parts) > 2:
        raise WireInputError("invalid_input")
    if parts:
        try:
            uuid_string(parts[0])
        except (TypeError, ValueError):
            raise WireInputError("invalid_input") from None
    if len(parts) == 2:
        if parts[1] not in _COMMANDS or parts[1] == "create" or method != "POST":
            raise WireInputError("invalid_input")
        _body(parts[1], body)
    elif not parts and method == "POST":
        _body("create", body)
    elif method not in {"GET", "HEAD"} or body:
        raise WireInputError("invalid_input")


def _error(code, reason=None):
    value = {"code": code, "message": MESSAGES.get(code, "Design workspace request could not be admitted"),
             "retryability": "not_retryable", "affected_refs": [], "correlation_id": str(uuid4())}
    if reason is not None:
        value["reason"] = reason
    return JSONResponse(value, status_code=STATUS.get(code, 503))


def design_workspace_services(context):
    service = PersistentDesignWorkspace(context.domain_store, context.owner_authority)
    return ContributionServices(create_router(service=service), {"design-workspace.service": service})


def create_router(*, service):
    router = APIRouter()

    async def call(function, *args, status_code=200, head=False):
        try:
            value = await run_in_threadpool(function, *args)
        except DesignWorkspaceError as error:
            return _error(error.code, error.reason)
        except OwnerAuthError as error:
            return _error(getattr(error, "code", "unauthenticated"))
        if head:
            return Response(headers={"Cache-Control": "no-store"})
        return JSONResponse(value, status_code=status_code, headers={"Cache-Control": "no-store"})

    @router.api_route(ROOT, methods=["GET", "HEAD"])
    async def listing(request: Request):
        return await call(service.list, request.state.authenticated_request, head=request.method == "HEAD")

    @router.post(ROOT)
    async def design_create(request: Request):
        try:
            value = _body("create", await request.body())
        except (WireInputError, ValueError, json.JSONDecodeError):
            return _error("invalid_input")
        return await call(service.create, request.state.authenticated_request, value, status_code=201)

    @router.api_route(ROOT + "/{request_id}", methods=["GET", "HEAD"])
    async def read(request_id: str, request: Request):
        return await call(service.read, request.state.authenticated_request, request_id,
                          head=request.method == "HEAD")

    def command(kind, function):
        async def handle(request_id: str, request: Request):
            try:
                value = _body(kind, await request.body())
            except (WireInputError, ValueError, json.JSONDecodeError):
                return _error("invalid_input")
            return await call(function, request.state.authenticated_request, request_id, value, status_code=201)

        handle.__name__ = f"design_{kind}"
        return handle

    router.post(ROOT + "/{request_id}/derivations")(command("derivations", service.derive))
    router.post(ROOT + "/{request_id}/reviews")(command("reviews", service.review))
    router.post(ROOT + "/{request_id}/preparations")(command("preparations", service.prepare))
    router.post(ROOT + "/{request_id}/generations")(command("generations", service.generate))
    router.post(ROOT + "/{request_id}/cancellations")(command("cancellations", service.cancel))
    return router
