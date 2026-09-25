"""Fixed HTTP adapter for the owner's run budgets: the `budget-policies-v1` contribution (T023).

- `GET|HEAD /api/v1/budget-policies`: the owner's budgets, newest first, with their exact refs;
- `POST /api/v1/budget-policies` (`budget-policy-command-v1`): seal one budget of exact limits.

The shared `/api/v1` preflight admits each body exactly before auth.
"""

import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..services.budget_policies import (
    COMMAND_SCHEMA,
    FIELDS,
    BudgetPolicyError,
    PersistentBudgetPolicies,
)
from ..services.owner_auth import OwnerAuthError
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/budget-policies"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "unavailable": 503}
_LIMITS = WireLimits(max_bytes=2_048, max_depth=2, max_items=32, max_members=16, max_string_bytes=64)


def is_budget_policies_path(path: str) -> bool:
    return path == PATH or path.startswith(PATH + "/")


def _body(raw: bytes) -> dict:
    value = parse_json_object(raw, required=("schema_version", "command_id", *FIELDS), limits=_LIMITS)
    if value["schema_version"] != COMMAND_SCHEMA:
        raise WireInputError("invalid_input")
    return value


def preflight(scope, body):
    parse_query(scope.get("query_string", b""), allowed=())
    if scope["path"] != PATH:
        raise WireInputError("invalid_input")
    if scope["method"] in {"GET", "HEAD"}:
        if body:
            raise WireInputError("invalid_input")
        return
    if scope["method"] != "POST":
        raise WireInputError("invalid_input")
    _body(body)


def _error(code):
    return JSONResponse({"code": code, "message": "Budget request could not be admitted",
                         "retryability": "not_retryable", "affected_refs": [], "correlation_id": str(uuid4())},
                        status_code=STATUS.get(code, 503))


def budget_services(context):
    service = PersistentBudgetPolicies(context.domain_store, context.owner_authority)
    return ContributionServices(create_router(service=service), {"budget-policies.service": service})


def create_router(*, service):
    router = APIRouter()

    async def call(function, *args, status=200):
        try:
            return JSONResponse(await run_in_threadpool(function, *args), status_code=status,
                                headers={"Cache-Control": "no-store"})
        except BudgetPolicyError as error:
            return _error(error.code)
        except OwnerAuthError as error:
            return _error(getattr(error, "code", "unauthenticated"))

    @router.api_route(PATH, methods=["GET", "HEAD"])
    async def listing(request: Request):
        return await call(service.list, request.state.authenticated_request)

    @router.post(PATH)
    async def create(request: Request):
        try:
            value = _body(await request.body())
        except (WireInputError, ValueError, json.JSONDecodeError):
            return _error("invalid_input")
        return await call(service.create, request.state.authenticated_request, value, status=201)

    return router
