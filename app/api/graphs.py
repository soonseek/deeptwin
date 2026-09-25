"""Fixed HTTP adapter for reading one stored functional graph: the `graphs-v1`
contribution (`GET|HEAD /api/v1/graphs/{graph_id}/versions/{version}`)."""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.graphs import GraphServiceError, PersistentGraphs
from ..services.owner_auth import OwnerAuthError
from .first_party import ContributionServices
from .wire import WireInputError, parse_query

PREFIX = "/api/v1/graphs/"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404, "unavailable": 503}


def is_graphs_path(path: str) -> bool:
    return path.startswith(PREFIX)


def preflight(scope, body):
    parse_query(scope.get("query_string", b""), allowed=())
    parts = scope["path"][len(PREFIX):].split("/")
    if len(parts) != 3 or parts[1] != "versions" or not parts[2].isdecimal() or parts[2] != str(int(parts[2])):
        raise WireInputError("invalid_input")
    try:
        uuid_string(parts[0])
    except (TypeError, ValueError):
        raise WireInputError("invalid_input") from None
    if scope["method"] not in {"GET", "HEAD"} or body:
        raise WireInputError("invalid_input")


def _error(code):
    return JSONResponse({"code": code, "message": "Graph request could not be admitted",
                         "retryability": "not_retryable", "affected_refs": [],
                         "correlation_id": str(uuid4())}, status_code=STATUS.get(code, 503))


def graph_services(context):
    service = PersistentGraphs(context.domain_store, context.owner_authority)
    return ContributionServices(create_router(service=service), {"graphs.service": service})


def create_router(*, service):
    router = APIRouter()

    @router.api_route(PREFIX + "{graph_id}/versions/{version}", methods=["GET", "HEAD"])
    async def read(graph_id: str, version: str, request: Request):
        try:
            return JSONResponse(await run_in_threadpool(service.read, request.state.authenticated_request,
                                                        graph_id, version), headers={"Cache-Control": "no-store"})
        except GraphServiceError as error:
            return _error(error.code)
        except OwnerAuthError as error:
            return _error(getattr(error, "code", "unauthenticated"))

    return router
