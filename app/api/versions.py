"""Fixed HTTP adapter for the owner's operating versions: the `versions-v1` route
contribution (US6, T066). `GET /api/v1/versions` reads the operating version, its
history and the candidates; `POST …/adopt|decisions|activate|rollback` are the
owner's explicit acts. `GET …/tool-effect-boundaries` lists the isolation boundaries
each persisted comparison plan needs with the owner's decision over each, and
`POST …/tool-effect-boundaries/decisions` records one approve / reject (G-14). The
shared `/api/v1` preflight admits each body exactly (`preflight`) before persistent
auth; the handler parses the same bytes again.
"""

import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..services.owner_decisions import PersistentOwnerDecisions
from ..services.promotion_approvals import PersistentPromotionApprovals
from ..services.tool_effect_approvals import PersistentToolEffectApprovals
from ..services.versions import PersistentVersions, VersionError
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/versions"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404,
          "conflict": 409, "unavailable": 503}
_REF = {"kind": str, "id": str, "version": int, "sha256": str}
COMMANDS = {
    "adopt": (("environment_ref",), {"environment_ref": dict}),
    "decisions": (("command_id", "decision", "validation_report_ref"),
                  {"command_id": str, "decision": str, "validation_report_ref": dict}),
    "activate": (("approval_ref", "expected_revision"), {"approval_ref": dict, "expected_revision": int}),
    "rollback": (("reason", "expected_revision"), {"reason": str, "expected_revision": int}),
    "tool-effect-boundaries/decisions": (
        ("command_id", "plan_record_ref", "tool_id", "version", "boundary_sha256", "decision"),
        {"command_id": str, "plan_record_ref": dict, "tool_id": str, "version": str,
         "boundary_sha256": str, "decision": str}),
}
BOUNDARIES = "tool-effect-boundaries"
_LIMITS = WireLimits(max_bytes=4096, max_depth=3, max_items=32, max_members=8, max_string_bytes=1024)


def is_versions_path(path: str) -> bool:
    return path == PATH or path.startswith(PATH + "/")


def _body(raw: bytes, command: str) -> dict:
    required, types = COMMANDS[command]
    value = parse_json_object(raw, required=required, field_types=types, limits=_LIMITS)
    for name in required:
        if name.endswith("_ref") and (type(value[name]) is not dict or set(value[name]) != set(_REF)
                                      or any(type(value[name][key]) is not kind for key, kind in _REF.items())):
            raise WireInputError("invalid_input")
    return value


def preflight(scope, body):
    """Exact admission before auth; raises for anything but the closed shapes."""

    path, method = scope["path"], scope["method"]
    parse_query(scope.get("query_string", b""), allowed=())
    if path in {PATH, f"{PATH}/{BOUNDARIES}"}:
        if method not in {"GET", "HEAD"} or body:
            raise WireInputError("invalid_input")
        return
    command = path[len(PATH) + 1:]
    if command not in COMMANDS or method != "POST":
        raise WireInputError("invalid_input")
    _body(body, command)


def version_error(error):
    code = error.code if isinstance(error, VersionError) else "invalid_input"
    return JSONResponse({"code": code, "message": "Version request could not be admitted",
                         "retryability": "not_retryable", "affected_refs": [],
                         "correlation_id": str(uuid4())}, status_code=STATUS.get(code, 503))


def version_services(context):
    approvals = PersistentPromotionApprovals(context.domain_store, context.owner_authority)
    versions = PersistentVersions(context.domain_store, context.owner_authority, approvals)
    boundaries = PersistentToolEffectApprovals(
        context.domain_store, context.owner_authority,
        PersistentOwnerDecisions(context.domain_store, context.owner_authority))
    return ContributionServices(create_router(versions=versions, boundaries=boundaries),
                                {"versions.service": versions})


def create_router(*, versions, boundaries):
    router = APIRouter()

    @router.api_route(PATH, methods=["GET", "HEAD"])
    async def read(request: Request):
        try:
            return JSONResponse(await run_in_threadpool(versions.read, request.state.authenticated_request))
        except VersionError as error:
            return version_error(error)

    @router.api_route(f"{PATH}/{BOUNDARIES}", methods=["GET", "HEAD"])
    async def read_boundaries(request: Request):
        try:
            return JSONResponse(await run_in_threadpool(boundaries.read, request.state.authenticated_request))
        except VersionError as error:
            return version_error(error)

    def command(name, service, method):
        async def handler(request: Request):
            try:
                value = _body(await request.body(), name)
            except (WireInputError, ValueError, json.JSONDecodeError):
                return version_error(VersionError("invalid_input"))
            try:
                return JSONResponse(await run_in_threadpool(
                    getattr(service, method), request.state.authenticated_request, value))
            except VersionError as error:
                return version_error(error)
        return handler

    for name, service, method in (("adopt", versions, "adopt"), ("decisions", versions, "decide"),
                                  ("activate", versions, "activate"), ("rollback", versions, "rollback"),
                                  (f"{BOUNDARIES}/decisions", boundaries, "decide")):
        router.add_api_route(f"{PATH}/{name}", command(name, service, method), methods=["POST"])
    return router
