"""Fixed HTTP adapter for the owner's browser grants: the `browser-grants-v1` route
contribution (T043; app/services/browser_grants.py).

- `GET|HEAD /api/v1/browser-grants`: every browser grant the owner created — recipients,
  sources, projection (entries and each data source's value count and digests, never a
  value), limits, expiry and state (`active` | `revoked` | `expired`).
- `POST /api/v1/browser-grants`: the owner creates one grant per command
  (`browser-grant-command-v1`).
- `POST /api/v1/browser-grants/{grant_id}/revoke`: the owner withdraws it.

The shared `/api/v1` preflight admits every body exactly before auth (`preflight`); the
boundary's browser-session policy verifies the session and, for a POST, the CSRF token.
"""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.browser_grants import (
    COMMAND_SCHEMA,
    REVOCATION_COMMAND_SCHEMA,
    BrowserGrantError,
    PersistentBrowserGrants,
)
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/browser-grants"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404,
          "conflict": 409, "unavailable": 503}
_CREATE_FIELDS = ("schema_version", "command_id", "label", "tools", "sources", "recipients", "entries",
                  "data_sources", "limits", "expires_at_utc")
_CREATE = (_CREATE_FIELDS,
           {"schema_version": str, "command_id": str, "label": str, "tools": list, "sources": list,
            "recipients": list, "entries": list, "data_sources": list, "limits": dict, "expires_at_utc": str},
           WireLimits(max_bytes=65_536, max_depth=6, max_items=1_024, max_members=16, max_string_bytes=2_048))
_REVOKE = (("schema_version", "command_id"), {"schema_version": str, "command_id": str},
           WireLimits(max_bytes=512, max_depth=2, max_items=8, max_members=4, max_string_bytes=64))

__all__ = ["browser_grant_services", "create_router", "is_browser_grants_path", "preflight"]


def is_browser_grants_path(path: str) -> bool:
    return path == PATH or path.startswith(PATH + "/")


def _body(raw: bytes, shape, schema) -> dict:
    required, types, limits = shape
    value = parse_json_object(raw, required=required, field_types=types, limits=limits)
    if value["schema_version"] != schema:
        raise WireInputError("invalid_input")
    uuid_string(value["command_id"])
    return value


def _revoke_target(path: str) -> str | None:
    parts = path[len(PATH) + 1:].split("/") if path.startswith(PATH + "/") else []
    if len(parts) == 2 and parts[1] == "revoke":
        return uuid_string(parts[0])
    return None


def preflight(scope, body):
    path, method = scope["path"], scope["method"]
    parse_query(scope.get("query_string", b""), allowed=())
    try:
        if path == PATH and method in {"GET", "HEAD"}:
            if body:
                raise WireInputError("invalid_input")
            return
        if path == PATH and method == "POST":
            _body(body, _CREATE, COMMAND_SCHEMA)
            return
        if method == "POST" and _revoke_target(path) is not None:
            _body(body, _REVOKE, REVOCATION_COMMAND_SCHEMA)
            return
    except (ValueError, TypeError) as error:
        raise WireInputError("invalid_input") from error
    raise WireInputError("invalid_input")


def grant_error(error):
    code = error.code if isinstance(error, BrowserGrantError) and error.code in STATUS else (
        "invalid_input" if not isinstance(error, BrowserGrantError) else "unavailable")
    value = {"code": code, "message": "browser grant request could not be admitted",
             "retryability": "retryable" if code == "conflict" else "not_retryable",
             "affected_refs": [], "correlation_id": str(uuid4())}
    return JSONResponse(value, status_code=STATUS[code], headers={"Cache-Control": "no-store"})


def browser_grant_services(context):
    from .first_party import ContributionServices

    service = PersistentBrowserGrants(context.domain_store, context.owner_authority)
    return ContributionServices(create_router(service=service), {"browser-grants.service": service})


def create_router(*, service):
    router = APIRouter()
    headers = {"Cache-Control": "no-store"}

    async def call(method, *args, status_code=200):
        try:
            return JSONResponse(await run_in_threadpool(method, *args), status_code=status_code, headers=headers)
        except BrowserGrantError as error:
            return grant_error(error)

    @router.api_route(PATH, methods=["GET", "HEAD"])
    async def read(request: Request):
        return await call(service.list, request.state.authenticated_request)

    @router.post(PATH)
    async def create(request: Request):
        try:
            value = _body(await request.body(), _CREATE, COMMAND_SCHEMA)
        except (WireInputError, ValueError, TypeError, json.JSONDecodeError):
            return grant_error(ValueError())
        return await call(service.create, request.state.authenticated_request, value, status_code=201)

    @router.post(PATH + "/{grant_id}/revoke")
    async def revoke(request: Request, grant_id: str):
        try:
            value = _body(await request.body(), _REVOKE, REVOCATION_COMMAND_SCHEMA)
        except (WireInputError, ValueError, TypeError, json.JSONDecodeError):
            return grant_error(ValueError())
        return await call(service.revoke, request.state.authenticated_request, grant_id, value)

    return router
