"""Fixed HTTP adapter for the actual inert candidate registry."""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..extensions.candidate_contracts import CandidateError, parse_bundle
from ..extensions.persistence import PersistentCandidateRegistry
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/extensions/candidates"
STATUS = {
    "invalid_input": 400,
    "unauthenticated": 401,
    "access_denied": 403,
    "not_found": 404,
    "conflict": 409,
    "too_large": 413,
    "capacity": 429,
    "unavailable": 503,
}


def candidate_services(context):
    registry = PersistentCandidateRegistry(
        context.domain_store, context.owner_authority
    )
    return ContributionServices(
        create_router(registry=registry, base_path=context.base_path),
        {"extension-candidates.registry": registry},
    )


def candidate_error(error):
    return JSONResponse(
        {
            "code": error.code,
            "message": "Candidate request could not be admitted",
            "retryability": "not_retryable",
            "affected_refs": [],
            "correlation_id": str(uuid4()),
        },
        status_code=STATUS[error.code],
    )


def preflight(scope, body, content_type):
    try:
        path, method = scope["path"], scope["method"]
        if path == PATH and method == "GET":
            # the bounded candidate list (extensions.candidates.list)
            parse_query(scope.get("query_string", b""), allowed=("limit", "after"), max_bytes=256)
            if body:
                raise CandidateError()
            return None
        parse_query(scope.get("query_string", b""), allowed=())
        if path == PATH:
            if method != "POST":
                raise CandidateError("invalid_input")
            if content_type.split(";", 1)[0] != "application/json":
                raise CandidateError()
            value = parse_json_object(
                body,
                required=("command_id", "manifest", "service_descriptor", "documents"),
                limits=WireLimits(max_bytes=1048576, max_depth=32, max_items=10000),
            )
            return parse_bundle(value).as_dict()
        if method not in {"GET", "HEAD"} or not path.startswith(PATH + "/"):
            raise CandidateError()
        uuid_string(path[len(PATH) + 1 :])
        if body:
            raise CandidateError()
        return None
    except CandidateError:
        raise
    except (WireInputError, ValueError):
        raise CandidateError() from None


def create_router(*, registry, base_path):
    router = APIRouter()

    def project(value):
        return {
            **value,
            "links": {
                key: base_path.rstrip("/") + link
                for key, link in value["links"].items()
            },
        }

    @router.post(PATH)
    async def register(request: Request):
        try:
            value = await run_in_threadpool(
                registry.register,
                request.state.authenticated_request,
                request.state.candidate_payload,
            )
            return JSONResponse(project(value), status_code=201)
        except CandidateError as error:
            return candidate_error(error)

    @router.get(PATH)
    async def page(request: Request):
        try:
            value = await run_in_threadpool(
                registry.page, request.state.authenticated_request,
                limit=request.query_params.get("limit"), after=request.query_params.get("after"),
            )
            return JSONResponse({**value, "items": [project(item) for item in value["items"]]})
        except CandidateError as error:
            return candidate_error(error)

    @router.api_route(PATH + "/{candidate_id}", methods=["GET", "HEAD"])
    async def read(request: Request, candidate_id: str):
        try:
            value = await run_in_threadpool(
                registry.read, request.state.authenticated_request, candidate_id
            )
            return (
                Response() if request.method == "HEAD" else JSONResponse(project(value))
            )
        except CandidateError as error:
            return candidate_error(error)

    return router
