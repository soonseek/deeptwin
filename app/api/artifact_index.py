"""Fixed HTTP adapter for the owner's vault-wide artifact index: the `artifact-index-v1`
contribution (`GET|HEAD /api/v1/artifacts`, T045).

The index lists every run's artifacts (oldest run first, each run's in its own order),
one bounded page at a time, filtered by an exact run id and/or a declared media type
(`type/subtype` or `type/*`). Each entry carries its `run_id`, so the viewer opens it
through the run-scoped routes (metadata, original, range, preview, pages); the index
itself never reads a path, a filename or a caller-supplied reference.

Query: `run_id`, `media_type`, `cursor` (a decimal offset the previous page returned as
`next_cursor`), `limit` (1-100, default 25) — each at most once, nothing else.
"""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.owner_auth import OwnerAuthError
from ..services.run_artifacts import (
    _MEDIA_FILTER,
    DEFAULT_INDEX_LIMIT,
    MAX_INDEX_LIMIT,
    RunArtifactError,
)
from .first_party import ContributionServices
from .wire import WireInputError, parse_query

PATH = "/api/v1/artifacts"
QUERY = ("cursor", "limit", "media_type", "run_id")
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404,
          "unavailable": 503}
MAX_CURSOR_DIGITS = 9


def is_artifact_index_path(path: str) -> bool:
    return path == PATH or path.startswith(PATH + "/")


def _decimal(raw, *, low, high) -> int:
    if (not 1 <= len(raw) <= MAX_CURSOR_DIGITS or not raw.isascii() or not raw.isdecimal()
            or raw != str(int(raw)) or not low <= int(raw) <= high):
        raise WireInputError("invalid_input")
    return int(raw)


def options(raw_query: bytes) -> dict:
    """The closed query as service arguments (the boundary and the route share it)."""

    query = parse_query(raw_query, allowed=QUERY, max_bytes=1_024)
    value = {"run_id": None, "media_type": None, "cursor": 0, "limit": DEFAULT_INDEX_LIMIT}
    if "run_id" in query:
        try:
            value["run_id"] = uuid_string(query["run_id"])
        except (TypeError, ValueError):
            raise WireInputError("invalid_input") from None
    if "media_type" in query:
        if _MEDIA_FILTER.fullmatch(query["media_type"]) is None:
            raise WireInputError("invalid_input")
        value["media_type"] = query["media_type"]
    if "cursor" in query:
        value["cursor"] = _decimal(query["cursor"], low=0, high=10 ** MAX_CURSOR_DIGITS - 1)
    if "limit" in query:
        value["limit"] = _decimal(query["limit"], low=1, high=MAX_INDEX_LIMIT)
    return value


def preflight(scope, body):
    if scope["path"] != PATH or scope["method"] not in {"GET", "HEAD"} or body:
        raise WireInputError("invalid_input")
    options(scope.get("query_string", b""))


def _error(code):
    return JSONResponse({"code": code, "message": "Artifact index request could not be admitted",
                         "retryability": "not_retryable", "affected_refs": [],
                         "correlation_id": str(uuid4())}, status_code=STATUS.get(code, 503))


def artifact_index_services(context, *, dependencies):
    if set(dependencies) != {"run-artifacts.service"}:
        raise TypeError("Invalid artifact index dependencies")
    return ContributionServices(
        create_router(artifacts=dependencies["run-artifacts.service"], base_path=context.base_path), {})


def create_router(*, artifacts, base_path):
    router = APIRouter()

    @router.api_route(PATH, methods=["GET", "HEAD"])
    async def index(request: Request):
        try:
            value = options(request.scope.get("query_string", b""))
            return JSONResponse(await run_in_threadpool(
                artifacts.index, request.state.authenticated_request, base_path=base_path, **value),
                headers={"Cache-Control": "no-store"})
        except WireInputError:
            return _error("invalid_input")
        except RunArtifactError as error:
            return _error(error.code if error.code in STATUS else "unavailable")
        except OwnerAuthError as error:
            return _error(getattr(error, "code", "unauthenticated"))

    return router
