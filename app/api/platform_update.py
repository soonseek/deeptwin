"""Fixed read-only HTTP adapter for the web-release update guidance: the
`platform-update-v1` contribution (T072; app/operations/recovery.py).

- `GET /api/v1/platform/update`: the current release, the pending update request and its
  lifecycle state, the backup the migration gate requires (and whether it still holds the
  live state), the last refusal and the operator's next steps.

The product can only read it. Preparing, backing up, migrating, cancelling and every
receipt stay with the stopped-control-plane operator tools
(`python -m app.operations.updates`, `python -m app.operations.recovery`); no route here
accepts an update or owner-recovery receipt from a browser.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..services.owner_auth import OwnerAuthError
from .first_party import ContributionServices
from .wire import WireInputError, parse_query

PATH = "/api/v1/platform/update"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "unavailable": 503}

__all__ = ["PlatformUpdateGuidance", "create_router", "is_platform_update_path", "platform_update_services",
           "preflight"]


def is_platform_update_path(path: str) -> bool:
    return path == PATH or path.startswith(PATH + "/")


def preflight(scope, body):
    parse_query(scope.get("query_string", b""), allowed=())
    if scope["path"] != PATH or scope["method"] not in {"GET", "HEAD"} or body:
        raise WireInputError("invalid_input")


class PlatformUpdateGuidance:
    """The owner's read of the update guidance; it never writes."""

    def __init__(self, domain_store, owner_authority):
        self._data_dir = Path(domain_store.data_dir)
        self._owner = owner_authority

    def state(self, request) -> dict:
        from ..operations.recovery import guidance_for

        self._owner.authenticate_bound(request.session)
        return guidance_for(self._data_dir)


def _error(code):
    return JSONResponse({"code": code, "message": "update guidance could not be read",
                         "retryability": "retryable" if code == "unavailable" else "not_retryable",
                         "affected_refs": [], "correlation_id": str(uuid4())},
                        status_code=STATUS.get(code, 503), headers={"Cache-Control": "no-store"})


def platform_update_services(context):
    service = PlatformUpdateGuidance(context.domain_store, context.owner_authority)
    return ContributionServices(create_router(service=service), {"platform-update.guidance": service})


def create_router(*, service):
    router = APIRouter()

    @router.api_route(PATH, methods=["GET", "HEAD"])
    async def read(request: Request):
        try:
            value = await run_in_threadpool(service.state, request.state.authenticated_request)
        except OwnerAuthError as error:
            return _error(getattr(error, "code", "unauthenticated"))
        except Exception:  # noqa: BLE001 - storage detail stays private
            return _error("unavailable")
        return JSONResponse(value, headers={"Cache-Control": "no-store"})

    return router
