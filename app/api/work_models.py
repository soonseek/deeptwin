"""Fixed HTTP adapter for the owner's common-work target: the `work-models-v1`
contribution.

- `POST /api/v1/work-models` drafts one work model from an exact work revision (work id and
  revision number; the server resolves the immutable record) with one
  explicit model turn over the owner's Claude connection (a replay never calls again).
- `GET /api/v1/work-models/{id}` reads a draft, its confirmation state and blocking
  unknowns.
- `POST /api/v1/work-models/{id}/confirm` records the owner's accepted/rejected decision
  over the exact draft they read.

The shared `/api/v1` preflight admits each body exactly before auth.
"""

import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.owner_auth import OwnerAuthError
from ..services.work_models import (
    CONFIRM_SCHEMA,
    DRAFT_SCHEMA,
    PersistentWorkModels,
    WorkModelServiceError,
)
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/work-models"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404,
          "conflict": 409, "unavailable": 503, "provider_unavailable": 503, "model_output_invalid": 422,
          "sources_required": 409}
_LIMITS = WireLimits(max_bytes=4_096, max_depth=3, max_items=32, max_members=8, max_string_bytes=256)
_REF = ("kind", "id", "version", "sha256")
BODIES = {
    "draft": (("schema_version", "command_id", "work_id", "revision", "model_choice_ref"), DRAFT_SCHEMA),
    "confirm": (("schema_version", "command_id", "work_model_ref", "decision"), CONFIRM_SCHEMA),
}


def is_work_models_path(path: str) -> bool:
    return path == PATH or path.startswith(PATH + "/")


def _body(raw: bytes, name: str) -> dict:
    fields, schema = BODIES[name]
    value = parse_json_object(raw, required=fields, limits=_LIMITS)
    if value["schema_version"] != schema:
        raise WireInputError("invalid_input")
    for key in fields:
        if key.endswith("_ref") and (type(value[key]) is not dict or set(value[key]) != set(_REF)):
            raise WireInputError("invalid_input")
    return value


def _route(path: str):
    """(`draft`|`read`|`confirm`, work model id) for an exact path, else invalid."""
    if path == PATH:
        return "draft", None
    rest = path[len(PATH) + 1:].split("/")
    try:
        uuid_string(rest[0])
    except (TypeError, ValueError):
        raise WireInputError("invalid_input") from None
    if len(rest) == 1:
        return "read", rest[0]
    if rest[1:] == ["confirm"]:
        return "confirm", rest[0]
    raise WireInputError("invalid_input")


def preflight(scope, body):
    parse_query(scope.get("query_string", b""), allowed=())
    name, _ = _route(scope["path"])
    method = scope["method"]
    if name == "read":
        if method not in {"GET", "HEAD"} or body:
            raise WireInputError("invalid_input")
        return
    if method != "POST":
        raise WireInputError("invalid_input")
    _body(body, name)


def _error(code):
    return JSONResponse({"code": code, "message": "Work model request could not be admitted",
                         "retryability": "not_retryable", "affected_refs": [],
                         "correlation_id": str(uuid4())}, status_code=STATUS.get(code, 503))


def work_model_services(context):
    from ..services.claude_run_executor import ClaudeRunExecutor

    executor = context.run_executor if type(context.run_executor) is ClaudeRunExecutor else None
    service = PersistentWorkModels(context.domain_store, context.owner_authority, executor)
    return ContributionServices(create_router(service=service), {"work-models.service": service})


def create_router(*, service):
    router = APIRouter()

    async def call(function, *args):
        try:
            return JSONResponse(await run_in_threadpool(function, *args), headers={"Cache-Control": "no-store"})
        except WorkModelServiceError as error:
            return _error(error.code)
        except OwnerAuthError as error:
            return _error(getattr(error, "code", "unauthenticated"))

    @router.post(PATH)
    async def draft(request: Request):
        try:
            value = _body(await request.body(), "draft")
        except (WireInputError, ValueError, json.JSONDecodeError):
            return _error("invalid_input")
        return await call(service.draft, request.state.authenticated_request, value)

    @router.api_route(PATH + "/{work_model_id}", methods=["GET", "HEAD"])
    async def read(work_model_id: str, request: Request):
        return await call(service.read, request.state.authenticated_request, work_model_id)

    @router.post(PATH + "/{work_model_id}/confirm")
    async def confirm(work_model_id: str, request: Request):
        try:
            value = _body(await request.body(), "confirm")
        except (WireInputError, ValueError, json.JSONDecodeError):
            return _error("invalid_input")
        return await call(service.confirm, request.state.authenticated_request, work_model_id, value)

    return router
