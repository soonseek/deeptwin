"""Fixed HTTP adapter for owner-recorded run approvals (human gates)."""

import re
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.run_approvals import PersistentRunApprovals, RunApprovalError
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PREFIX = "/api/v1/runs/"
_LOCAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
STATUS = {
    "invalid_input": 400,
    "unauthenticated": 401,
    "access_denied": 403,
    "not_found": 404,
    "conflict": 409,
    "too_large": 413,
    "unavailable": 503,
}


class ApprovalRouteError(ValueError):
    """Closed wire-level codes for the approval routes."""

    def __init__(self, code="invalid_input"):
        super().__init__(code)
        self.code = code


def _code(error) -> str:
    if isinstance(error, ApprovalRouteError):
        return error.code
    text = str(error)
    if text.startswith("invalid"):
        return "invalid_input"
    return text if text in STATUS else "unavailable"


def approval_error(error):
    code = _code(error)
    return JSONResponse(
        {
            "code": code,
            "message": "Approval request could not be admitted",
            "retryability": "not_retryable",
            "affected_refs": [],
            "correlation_id": str(uuid4()),
        },
        status_code=STATUS[code],
    )


def is_approval_path(path: str) -> bool:
    if not path.startswith(PREFIX):
        return False
    parts = path[len(PREFIX) :].split("/")
    return len(parts) >= 2 and parts[1] == "approvals"


def _segments(path: str):
    parts = path[len(PREFIX) :].split("/")
    try:
        run_id = uuid_string(parts[0])
    except (ValueError, TypeError):
        raise ApprovalRouteError() from None
    if parts[1] != "approvals":
        raise ApprovalRouteError()
    return run_id, parts[2:]


def preflight(scope, body, content_type):
    try:
        path, method = scope["path"], scope["method"]
        parse_query(scope.get("query_string", b""), allowed=())
        run_id, rest = _segments(path)
        if not rest:
            if method != "POST":
                raise ApprovalRouteError()
            if content_type.split(";", 1)[0] != "application/json":
                raise ApprovalRouteError()
            fields = ("command_id", "node_id", "approval_scope", "decision")
            value = parse_json_object(
                body,
                required=fields,
                field_types={key: str for key in fields},
                limits=WireLimits(
                    max_bytes=4096,
                    max_depth=2,
                    max_items=8,
                    max_members=4,
                    max_string_bytes=256,
                ),
            )
            if set(value) != set(fields):
                raise ApprovalRouteError()
            return {
                "schema_version": "run-approval-command-v1",
                "run_id": run_id,
                **value,
            }
        if method not in {"GET", "HEAD"} or len(rest) != 2 or body:
            raise ApprovalRouteError()
        if any(_LOCAL.fullmatch(part) is None for part in rest):
            raise ApprovalRouteError()
        return None
    except ApprovalRouteError:
        raise
    except (WireInputError, ValueError):
        raise ApprovalRouteError() from None


def approval_services(context):
    approvals = PersistentRunApprovals(context.domain_store, context.owner_authority)
    return ContributionServices(
        create_router(approvals=approvals, base_path=context.base_path),
        {"run-approvals.service": approvals},
    )


def create_router(*, approvals, base_path):
    router = APIRouter()
    root = base_path.rstrip("/")

    def links(run_id, node_id, scope):
        return {
            "self": f"{root}{PREFIX}{run_id}/approvals/{node_id}/{scope}",
            "events": f"{root}/api/v1/events",
        }

    @router.post(PREFIX + "{run_id}/approvals")
    async def record(request: Request, run_id: str):
        try:
            command = request.state.approval_payload
            value = await run_in_threadpool(
                approvals.record, request.state.authenticated_request, command
            )
            return JSONResponse(
                {
                    **value,
                    "links": links(
                        run_id, command["node_id"], command["approval_scope"]
                    ),
                },
                status_code=201,
            )
        except RunApprovalError as error:
            return approval_error(error)

    @router.api_route(
        PREFIX + "{run_id}/approvals/{node_id}/{approval_scope}",
        methods=["GET", "HEAD"],
    )
    async def read(request: Request, run_id: str, node_id: str, approval_scope: str):
        try:
            found = await run_in_threadpool(
                approvals.lookup, run_id, node_id, approval_scope
            )
            if found is None:
                raise ApprovalRouteError("not_found")
            value = {
                "run_id": found.run_id,
                "node_id": found.node_id,
                "approval_scope": found.approval_scope,
                "decision": found.decision,
                "command_id": found.command_id,
                "approval_ref": found.approval_ref.as_dict(),
                "actor_ref": found.actor_ref.as_dict(),
                "links": links(run_id, node_id, approval_scope),
            }
            return Response() if request.method == "HEAD" else JSONResponse(value)
        except (RunApprovalError, ApprovalRouteError) as error:
            return approval_error(error)

    return router
