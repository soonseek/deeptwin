"""Fixed HTTP adapter for the owner's run consents: the `run-consents-v1` route
contribution. `POST /api/v1/run-consents` seals one consent per command over the
exact records a run will name; `GET|HEAD /api/v1/run-consents/{consent_id}` reads
it. The boundary admits the wire (bounded JSON, no query, exact methods) before
persistent auth; the service seals `run_consent` records.
"""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.run_consents import (
    COMMAND_SCHEMA,
    PersistentRunConsents,
    RunConsentError,
)
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/run-consents"
MAX_BODY_BYTES = 4096  # six members plus four four-field references
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
_FIELDS = ("schema_version", "command_id", "graph_ref", "work_revision_ref", "environment_ref",
           "budget_policy_ref")


class ConsentRouteError(ValueError):
    """Closed wire-level codes for the consent routes."""

    def __init__(self, code="invalid_input"):
        super().__init__(code)
        self.code = code


def consent_error(error):
    code = error.code if isinstance(error, ConsentRouteError | RunConsentError) else "unavailable"
    if code not in STATUS:
        code = "unavailable"
    return JSONResponse(
        {
            "code": code,
            "message": "Run consent request could not be admitted",
            "retryability": "not_retryable",
            "affected_refs": [],
            "correlation_id": str(uuid4()),
        },
        status_code=STATUS[code],
    )


def is_consent_path(path: str) -> bool:
    return path == PATH or path.startswith(PATH + "/")


def _ref_shape(value):
    if type(value) is not dict or tuple(sorted(value)) != tuple(sorted(_REF_FIELDS)):
        raise ConsentRouteError()
    if (type(value["kind"]) is not str or type(value["id"]) is not str
            or type(value["version"]) is not int or type(value["sha256"]) is not str):
        raise ConsentRouteError()
    return value


def preflight(scope, body, content_type):
    try:
        path, method = scope["path"], scope["method"]
        parse_query(scope.get("query_string", b""), allowed=())
        if path == PATH:
            if method != "POST" or content_type.split(";", 1)[0] != "application/json":
                raise ConsentRouteError()
            value = parse_json_object(
                body, required=_FIELDS,
                field_types={"schema_version": str, "command_id": str, **{name: dict for name in _FIELDS[2:]}},
                limits=WireLimits(max_bytes=MAX_BODY_BYTES, max_depth=3, max_items=32, max_members=8,
                                  max_string_bytes=256),
            )
            if value["schema_version"] != COMMAND_SCHEMA:
                raise ConsentRouteError()
            uuid_string(value["command_id"])
            for name in _FIELDS[2:]:
                _ref_shape(value[name])
            return value
        parts = path[len(PATH) + 1:].split("/")
        if len(parts) != 1 or method not in {"GET", "HEAD"} or body:
            raise ConsentRouteError()
        uuid_string(parts[0])
        return None
    except ConsentRouteError:
        raise
    except (WireInputError, ValueError, TypeError):
        raise ConsentRouteError() from None


def consent_services(context):
    consents = PersistentRunConsents(context.domain_store, context.owner_authority)
    return ContributionServices(create_router(consents=consents), {"run-consents.service": consents})


def create_router(*, consents):
    router = APIRouter()

    @router.post(PATH)
    async def record(request: Request):
        try:
            value = await run_in_threadpool(consents.record, request.state.authenticated_request,
                                            request.state.consent_payload)
            return JSONResponse(value, status_code=201)
        except RunConsentError as error:
            return consent_error(error)

    @router.api_route(PATH + "/{consent_id}", methods=["GET", "HEAD"])
    async def read(request: Request, consent_id: str):
        try:
            value = await run_in_threadpool(consents.read, request.state.authenticated_request, consent_id)
            return JSONResponse(value)  # HEAD carries GET's headers; the boundary blanks the body
        except RunConsentError as error:
            return consent_error(error)

    return router
