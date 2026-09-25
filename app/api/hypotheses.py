"""Fixed HTTP adapter for competing explanations of an observed difference: the
`hypotheses-v1` contribution.

- `GET /api/v1/differences/{difference_id}/hypotheses` reads the difference's hypothesis
  set, or `not_generated` when the owner has not asked for one.
- `POST /api/v1/differences/{difference_id}/hypotheses` asks — explicitly, once per
  difference — for competing explanations through the owner's Claude connection.

The shared `/api/v1` preflight admits each body exactly before auth.
"""

import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.hypotheses import PROPOSE_SCHEMA, HypothesisServiceError, PersistentHypotheses
from ..services.owner_auth import OwnerAuthError
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PREFIX = "/api/v1/differences/"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404,
          "conflict": 409, "unavailable": 503, "provider_unavailable": 503, "model_output_invalid": 422}
_LIMITS = WireLimits(max_bytes=2_048, max_depth=3, max_items=16, max_members=8, max_string_bytes=256)
_FIELDS = ("schema_version", "command_id", "model_choice_ref")


def is_hypotheses_path(path: str) -> bool:
    return path.startswith(PREFIX)


def _body(raw: bytes) -> dict:
    value = parse_json_object(raw, required=_FIELDS, limits=_LIMITS)
    ref = value["model_choice_ref"]
    if (value["schema_version"] != PROPOSE_SCHEMA or type(ref) is not dict
            or set(ref) != {"kind", "id", "version", "sha256"}):
        raise WireInputError("invalid_input")
    return value


def preflight(scope, body):
    parse_query(scope.get("query_string", b""), allowed=())
    parts = scope["path"][len(PREFIX):].split("/")
    if len(parts) != 2 or parts[1] != "hypotheses":
        raise WireInputError("invalid_input")
    try:
        uuid_string(parts[0])
    except (TypeError, ValueError):
        raise WireInputError("invalid_input") from None
    method = scope["method"]
    if method in {"GET", "HEAD"}:
        if body:
            raise WireInputError("invalid_input")
    elif method == "POST":
        _body(body)
    else:
        raise WireInputError("invalid_input")


def _error(code):
    return JSONResponse({"code": code, "message": "Hypothesis request could not be admitted",
                         "retryability": "not_retryable", "affected_refs": [],
                         "correlation_id": str(uuid4())}, status_code=STATUS.get(code, 503))


def hypothesis_services(context, *, dependencies):
    from ..services.claude_run_executor import ClaudeRunExecutor

    if set(dependencies) != {"alternative-drafts.service"}:
        raise TypeError("Invalid hypothesis dependencies")
    executor = context.run_executor if type(context.run_executor) is ClaudeRunExecutor else None
    service = PersistentHypotheses(context.domain_store, context.owner_authority,
                                   dependencies["alternative-drafts.service"], executor,
                                   base_path=context.base_path)
    return ContributionServices(create_router(service=service), {"hypotheses.service": service})


def create_router(*, service):
    router = APIRouter()

    async def call(function, *args):
        try:
            return JSONResponse(await run_in_threadpool(function, *args), headers={"Cache-Control": "no-store"})
        except HypothesisServiceError as error:
            return _error(error.code)
        except OwnerAuthError as error:
            return _error(getattr(error, "code", "unauthenticated"))

    @router.api_route(PREFIX + "{difference_id}/hypotheses", methods=["GET", "HEAD"])
    async def read(difference_id: str, request: Request):
        return await call(service.read, request.state.authenticated_request, difference_id)

    @router.post(PREFIX + "{difference_id}/hypotheses")
    async def propose(difference_id: str, request: Request):
        try:
            value = _body(await request.body())
        except (WireInputError, ValueError, json.JSONDecodeError):
            return _error("invalid_input")
        return await call(service.propose, request.state.authenticated_request, difference_id, value)

    return router
