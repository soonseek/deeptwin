"""Fixed HTTP adapter for the owner's explicit readings of retained originals: the
`source-readings-v1` contribution (T023).

- `GET|HEAD /api/v1/source-readings/{work_id}`: every source of the work's latest revision
  with its original state and its latest reading's state (an excerpt, never the full text);
- `POST /api/v1/source-readings/{work_id}`: read one exact source now (`source-reading-command-v1`);
- `GET|HEAD /api/v1/source-readings/{work_id}/{source_id}`: the latest reading, its text.

The shared `/api/v1` preflight admits each body exactly before auth.
"""

import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.owner_auth import OwnerAuthError
from ..services.source_readings import (
    COMMAND_SCHEMA,
    SourceReadingError,
    SourceReadings,
)
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/source-readings"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404,
          "conflict": 409, "unavailable": 503, "reader_unavailable": 503, "capacity": 429}
_LIMITS = WireLimits(max_bytes=2_048, max_depth=3, max_items=8, max_members=4, max_string_bytes=128)
_REF = ("kind", "id", "version", "sha256")


def is_source_readings_path(path: str) -> bool:
    return path == PATH or path.startswith(PATH + "/")


def _body(raw: bytes) -> dict:
    value = parse_json_object(raw, required=("schema_version", "command_id", "source_ref"), limits=_LIMITS)
    if (value["schema_version"] != COMMAND_SCHEMA or type(value["source_ref"]) is not dict
            or set(value["source_ref"]) != set(_REF)):
        raise WireInputError("invalid_input")
    return value


def _route(path: str):
    rest = path[len(PATH) + 1:].split("/") if path.startswith(PATH + "/") else []
    try:
        if len(rest) not in {1, 2}:
            raise ValueError
        for part in rest:
            uuid_string(part)
    except (TypeError, ValueError):
        raise WireInputError("invalid_input") from None
    return rest


def preflight(scope, body):
    parse_query(scope.get("query_string", b""), allowed=())
    rest = _route(scope["path"])
    method = scope["method"]
    if len(rest) == 2 or method in {"GET", "HEAD"}:
        if method not in {"GET", "HEAD"} or body:
            raise WireInputError("invalid_input")
        return
    if method != "POST":
        raise WireInputError("invalid_input")
    _body(body)


def _error(code):
    body = {"code": code, "message": "Source reading request could not be admitted",
            "retryability": "retryable" if code == "reader_unavailable" else "not_retryable",
            "affected_refs": [], "correlation_id": str(uuid4())}
    if code == "reader_unavailable":
        body["reason"] = code  # the shell's closed partition reads it as a 503 with this reason
    return JSONResponse(body, status_code=STATUS.get(code, 503))


def reading_services(context, *, dependencies):
    if set(dependencies) != {"works.service"}:
        raise TypeError("Invalid source reading dependencies")
    service = SourceReadings(dependencies["works.service"], codec=context.document_codec)
    return ContributionServices(create_router(service=service), {"source-readings.service": service})


def create_router(*, service):
    router = APIRouter()

    async def call(function, *args, status=200):
        try:
            return JSONResponse(await run_in_threadpool(function, *args), status_code=status,
                                headers={"Cache-Control": "no-store"})
        except SourceReadingError as error:
            return _error(error.code)
        except OwnerAuthError as error:
            return _error(getattr(error, "code", "unauthenticated"))

    @router.api_route(PATH + "/{work_id}", methods=["GET", "HEAD"])
    async def listing(work_id: str, request: Request):
        return await call(service.list, request.state.authenticated_request, work_id)

    @router.post(PATH + "/{work_id}")
    async def read_now(work_id: str, request: Request):
        try:
            value = _body(await request.body())
        except (WireInputError, ValueError, json.JSONDecodeError):
            return _error("invalid_input")
        return await call(service.command, request.state.authenticated_request, work_id, value, status=201)

    @router.api_route(PATH + "/{work_id}/{source_id}", methods=["GET", "HEAD"])
    async def latest(work_id: str, source_id: str, request: Request):
        return await call(service.read, request.state.authenticated_request, work_id, source_id)

    return router
