"""Fixed HTTP adapter for owner-started runs (the connected browser path)."""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.runs import (
    COMMAND_SCHEMA,
    RESUME_SCHEMA,
    PersistentRuns,
    RunServiceError,
)
from .first_party import ContributionServices
from .run_approvals import is_approval_path
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/runs"
STATUS = {
    "invalid_input": 400,
    "unauthenticated": 401,
    "access_denied": 403,
    "not_found": 404,
    "conflict": 409,
    "too_large": 413,
    "unavailable": 503,
}
_REF_FIELDS = ("kind", "id", "version", "sha256")
_CREATE_FIELDS = (
    "command_id", "graph_ref", "work_revision_ref", "environment_ref", "consent_ref",
    "budget_policy_ref",
)


class RunRouteError(ValueError):
    """Closed wire-level codes for the run routes."""

    def __init__(self, code="invalid_input"):
        super().__init__(code)
        self.code = code


def run_error(error):
    code = error.code if isinstance(error, RunRouteError | RunServiceError) else "unavailable"
    if code not in STATUS:
        code = "unavailable"
    return JSONResponse(
        {
            "code": code,
            "message": "Run request could not be admitted",
            "retryability": "not_retryable",
            "affected_refs": [],
            "correlation_id": str(uuid4()),
        },
        status_code=STATUS[code],
    )


def is_run_path(path: str) -> bool:
    """`/api/v1/runs`, `/api/v1/runs/{id}` and `/api/v1/runs/{id}/resume`; the
    approvals routes under the same prefix keep their own adapter."""

    if path == PATH:
        return True
    if not path.startswith(PATH + "/") or is_approval_path(path):
        return False
    parts = path[len(PATH) + 1:].split("/")
    return len(parts) == 1 or (len(parts) == 2 and parts[1] == "resume")


def _ref_shape(value):
    if type(value) is not dict or tuple(sorted(value)) != tuple(sorted(_REF_FIELDS)):
        raise RunRouteError()
    if (type(value["kind"]) is not str or type(value["id"]) is not str
            or type(value["version"]) is not int or type(value["sha256"]) is not str):
        raise RunRouteError()
    return value


def preflight(scope, body, content_type):
    try:
        path, method = scope["path"], scope["method"]
        parse_query(scope.get("query_string", b""), allowed=())
        if path == PATH:
            if method != "POST" or content_type.split(";", 1)[0] != "application/json":
                raise RunRouteError()
            value = parse_json_object(
                body,
                required=_CREATE_FIELDS,
                field_types={"command_id": str, **{name: dict for name in _CREATE_FIELDS[1:]}},
                limits=WireLimits(
                    max_bytes=4096, max_depth=3, max_items=32, max_members=8,
                    max_string_bytes=256,
                ),  # six members plus five four-field references
            )
            uuid_string(value["command_id"])
            for name in _CREATE_FIELDS[1:]:
                _ref_shape(value[name])
            return {"schema_version": COMMAND_SCHEMA, **value}
        parts = path[len(PATH) + 1:].split("/")
        run_id = uuid_string(parts[0])
        if len(parts) == 2:
            if method != "POST" or content_type.split(";", 1)[0] != "application/json":
                raise RunRouteError()
            value = parse_json_object(
                body, required=("command_id",), field_types={"command_id": str},
                limits=WireLimits(max_bytes=4096, max_depth=2, max_items=4, max_members=2,
                                  max_string_bytes=256),
            )
            uuid_string(value["command_id"])
            return {"schema_version": RESUME_SCHEMA, "run_id": run_id, **value}
        if method not in {"GET", "HEAD"} or body:
            raise RunRouteError()
        return None
    except RunRouteError:
        raise
    except (WireInputError, ValueError, TypeError):
        raise RunRouteError() from None


def run_services(context, *, dependencies):
    if set(dependencies) != {"run-approvals.service"}:
        raise TypeError("Invalid run dependencies")
    runs = PersistentRuns(
        context.domain_store, context.owner_authority,
        ledger=context.components.runtime_ledger, budget_book=context.components.budget_book,
        approvals=dependencies["run-approvals.service"], executor=context.run_executor,
    )
    return ContributionServices(
        create_router(runs=runs, base_path=context.base_path), {"runs.service": runs},
    )


def create_router(*, runs, base_path):
    router = APIRouter()

    @router.post(PATH)
    async def create(request: Request):
        try:
            value = await run_in_threadpool(
                runs.create, request.state.authenticated_request,
                request.state.run_payload, base_path=base_path,
            )
            return JSONResponse(value, status_code=201)
        except RunServiceError as error:
            return run_error(error)

    @router.post(PATH + "/{run_id}/resume")
    async def resume(request: Request, run_id: str):
        try:
            payload = request.state.run_payload
            value = await run_in_threadpool(
                runs.resume, request.state.authenticated_request, run_id,
                {"schema_version": payload["schema_version"], "command_id": payload["command_id"]},
                base_path=base_path,
            )
            return JSONResponse(value)
        except RunServiceError as error:
            return run_error(error)

    @router.api_route(PATH + "/{run_id}", methods=["GET", "HEAD"])
    async def read(request: Request, run_id: str):
        try:
            value = await run_in_threadpool(runs.read, run_id, base_path=base_path)
            # HEAD carries GET's headers; the boundary blanks the body
            return JSONResponse(value)
        except RunServiceError as error:
            return run_error(error)

    return router
