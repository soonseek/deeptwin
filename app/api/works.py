"""Fixed HTTP adapter for the intake's works: the `works-v1` route contribution.

`POST /api/v1/works` creates a work from the owner's explanation, `GET|HEAD
/api/v1/works/{work_id}` reads its latest revision, `POST …/{work_id}/revisions`
seals the next revision under an expected one. The boundary admits the wire
(bounded JSON, no query, exact methods) before persistent auth; the service
seals `work_revision` records.
"""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.works import (
    CREATE_SCHEMA,
    MAX_TEXT_BYTES,
    REVISE_SCHEMA,
    PersistentWorks,
    WorkServiceError,
)
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/works"
# the text's raw UTF-8 bound (the record's own string cap; an escaped-form client that
# sends `\\uXXXX` for every character reaches it sooner) plus the command's other members
MAX_BODY_BYTES = MAX_TEXT_BYTES + 1_920
STATUS = {
    "invalid_input": 400,
    "unauthenticated": 401,
    "access_denied": 403,
    "not_found": 404,
    "conflict": 409,
    "too_large": 413,
    "unavailable": 503,
}
_LIMITS = WireLimits(max_bytes=MAX_BODY_BYTES, max_depth=2, max_items=8, max_members=4,
                     max_string_bytes=MAX_TEXT_BYTES)


class WorkRouteError(ValueError):
    """Closed wire-level codes for the work routes."""

    def __init__(self, code="invalid_input"):
        super().__init__(code)
        self.code = code


def work_error(error):
    code = error.code if isinstance(error, WorkRouteError | WorkServiceError) else "unavailable"
    if code not in STATUS:
        code = "unavailable"
    return JSONResponse(
        {
            "code": code,
            "message": "Work request could not be admitted",
            "retryability": "not_retryable",
            "affected_refs": [],
            "correlation_id": str(uuid4()),
        },
        status_code=STATUS[code],
    )


def is_work_path(path: str) -> bool:
    return path == PATH or path.startswith(PATH + "/")


def preflight(scope, body, content_type):
    try:
        path, method = scope["path"], scope["method"]
        parse_query(scope.get("query_string", b""), allowed=())
        if path == PATH:
            if method != "POST" or content_type.split(";", 1)[0] != "application/json":
                raise WorkRouteError()
            value = parse_json_object(
                body, required=("schema_version", "command_id", "text"),
                field_types={"schema_version": str, "command_id": str, "text": str}, limits=_LIMITS,
            )
            if value["schema_version"] != CREATE_SCHEMA:
                raise WorkRouteError()
            uuid_string(value["command_id"])
            return value
        parts = path[len(PATH) + 1:].split("/")
        work_id = uuid_string(parts[0])
        if len(parts) == 2 and parts[1] == "revisions":
            if method != "POST" or content_type.split(";", 1)[0] != "application/json":
                raise WorkRouteError()
            value = parse_json_object(
                body, required=("schema_version", "command_id", "expected_revision", "text"),
                field_types={"schema_version": str, "command_id": str, "expected_revision": int, "text": str},
                limits=_LIMITS,
            )
            if value["schema_version"] != REVISE_SCHEMA:
                raise WorkRouteError()
            uuid_string(value["command_id"])
            return {"work_id": work_id, **value}
        if len(parts) != 1 or method not in {"GET", "HEAD"} or body:
            raise WorkRouteError()
        return None
    except WorkRouteError:
        raise
    except (WireInputError, ValueError, TypeError):
        raise WorkRouteError() from None


def work_services(context):
    works = PersistentWorks(context.domain_store, context.owner_authority)
    return ContributionServices(create_router(works=works), {"works.service": works})


def create_router(*, works):
    router = APIRouter()

    @router.post(PATH)
    async def create(request: Request):
        try:
            value = await run_in_threadpool(
                works.create, request.state.authenticated_request, request.state.work_payload,
            )
            return JSONResponse(value, status_code=201)
        except WorkServiceError as error:
            return work_error(error)

    @router.post(PATH + "/{work_id}/revisions")
    async def revise(request: Request, work_id: str):
        try:
            payload = request.state.work_payload
            value = await run_in_threadpool(
                works.revise, request.state.authenticated_request, work_id,
                {name: payload[name] for name in ("schema_version", "command_id", "expected_revision", "text")},
            )
            return JSONResponse(value, status_code=201)
        except WorkServiceError as error:
            return work_error(error)

    @router.api_route(PATH + "/{work_id}", methods=["GET", "HEAD"])
    async def read(request: Request, work_id: str):
        try:
            value = await run_in_threadpool(works.read, work_id)
            # HEAD carries GET's headers; the boundary blanks the body
            return JSONResponse(value)
        except WorkServiceError as error:
            return work_error(error)

    return router
