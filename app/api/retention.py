"""Fixed HTTP adapter for what this instance keeps and the owner's explicit cleanup: the
`retention-v1` contribution (T073; app/services/retention_cleanup.py).

- `GET /api/v1/retention`: per category what is kept, for how long, what is eligible for
  owner-initiated cleanup and what is never deleted and why, plus the eligible items and
  the cleanups already made.
- `POST /api/v1/retention/cleanup/preview`: the exact scope of a cleanup, with its digest.
- `POST /api/v1/retention/cleanup`: the cleanup, only with `confirmed: true` and that
  exact digest.

The shared `/api/v1` preflight admits every body exactly before auth (`preflight`).
"""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..services.retention_cleanup import (
    CONFIRM_SCHEMA,
    MAX_ITEMS,
    PREVIEW_SCHEMA,
    RetentionCleanup,
    RetentionServiceError,
)
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/retention"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404,
          "conflict": 409, "unavailable": 503}
_ITEMS = WireLimits(max_bytes=8192, max_depth=3, max_items=MAX_ITEMS + 8, max_members=8, max_string_bytes=128)
BODIES = {
    "preview": (("schema_version", "request_id", "item_ids", "reason_code"),
                {"schema_version": str, "request_id": str, "item_ids": list, "reason_code": str}, _ITEMS),
    "cleanup": (("schema_version", "request_id", "item_ids", "reason_code", "preview_sha256", "confirmed"),
                {"schema_version": str, "request_id": str, "item_ids": list, "reason_code": str,
                 "preview_sha256": str, "confirmed": bool}, _ITEMS),
}
SCHEMAS = {"preview": PREVIEW_SCHEMA, "cleanup": CONFIRM_SCHEMA}

__all__ = ["create_router", "is_retention_path", "preflight", "retention_services"]


def is_retention_path(path: str) -> bool:
    return path == PATH or path.startswith(PATH + "/")


def _body(raw: bytes, name: str) -> dict:
    required, types, limits = BODIES[name]
    value = parse_json_object(raw, required=required, field_types=types, limits=limits)
    if value["schema_version"] != SCHEMAS[name]:
        raise WireInputError("invalid_input")
    return value


def preflight(scope, body):
    path, method = scope["path"], scope["method"]
    parse_query(scope.get("query_string", b""), allowed=())
    if path == PATH and method in {"GET", "HEAD"}:
        if body:
            raise WireInputError("invalid_input")
        return
    if path == PATH + "/cleanup/preview" and method == "POST":
        _body(body, "preview")
        return
    if path == PATH + "/cleanup" and method == "POST":
        _body(body, "cleanup")
        return
    raise WireInputError("invalid_input")


def retention_error(error):
    code = error.code if isinstance(error, RetentionServiceError) else "invalid_input"
    value = {"code": code, "message": "retention request could not be admitted",
             "retryability": "retryable" if code == "conflict" else "not_retryable",
             "affected_refs": [], "correlation_id": str(uuid4())}
    return JSONResponse(value, status_code=STATUS.get(code, 503), headers={"Cache-Control": "no-store"})


def retention_services(context, *, dependencies):
    from .first_party import ContributionServices

    if set(dependencies) != {"backups.service", "works.service"}:
        raise TypeError("Invalid retention dependencies")
    service = RetentionCleanup(context.domain_store, context.owner_authority,
                               backups=dependencies["backups.service"], works=dependencies["works.service"])
    return ContributionServices(create_router(service=service), {"retention.service": service})


def create_router(*, service):
    router = APIRouter()
    headers = {"Cache-Control": "no-store"}

    async def call(method, *args):
        try:
            return JSONResponse(await run_in_threadpool(method, *args), headers=headers)
        except RetentionServiceError as error:
            return retention_error(error)

    @router.api_route(PATH, methods=["GET", "HEAD"])
    async def read(request: Request):
        return await call(service.state, request.state.authenticated_request)

    @router.post(PATH + "/cleanup/preview")
    async def preview(request: Request):
        try:
            value = _body(await request.body(), "preview")
        except (WireInputError, ValueError, json.JSONDecodeError):
            return retention_error(RetentionServiceError("invalid_input"))
        return await call(service.preview, request.state.authenticated_request, value)

    @router.post(PATH + "/cleanup")
    async def cleanup(request: Request):
        try:
            value = _body(await request.body(), "cleanup")
        except (WireInputError, ValueError, json.JSONDecodeError):
            return retention_error(RetentionServiceError("invalid_input"))
        return await call(service.cleanup, request.state.authenticated_request, value)

    return router
