"""Fixed HTTP adapter for the owner's run trace: the `run-trace-v1` contribution
(`GET|HEAD /api/v1/runs/{run_id}/trace`, docs/ui/2026-09-26-product-ux-redesign.md §7).

A read-only projection of what one run already recorded — visits, attempts, inputs,
outputs, hand-offs, tool calls, model calls, approvals and errors — with every value the
runtime did not record marked `not_recorded` (`services/run_traces.py`). Owner browser
session only; no query, no body. The path is admitted by the run routes' shared preflight
(`runs.is_run_path`)."""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..services.owner_auth import OwnerAuthError
from ..services.run_traces import PersistentRunTraces, RunTraceReadError
from .first_party import ContributionServices

PATH = "/api/v1/runs/{run_id}/trace"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404,
          "unavailable": 503}


def _error(code):
    code = code if code in STATUS else "unavailable"
    return JSONResponse({"code": code, "message": "Run trace request could not be admitted",
                         "retryability": "not_retryable", "affected_refs": [],
                         "correlation_id": str(uuid4())}, status_code=STATUS[code])


def run_trace_services(context, *, dependencies):
    if set(dependencies) != {"runs.service", "run-approvals.service"}:
        raise TypeError("Invalid run trace dependencies")
    traces = PersistentRunTraces(
        context.domain_store, context.owner_authority, runs=dependencies["runs.service"],
        approvals=dependencies["run-approvals.service"], ledger=context.components.runtime_ledger,
        budget_book=context.components.budget_book)
    return ContributionServices(create_router(traces=traces, base_path=context.base_path), {})


def create_router(*, traces, base_path):
    router = APIRouter()

    @router.api_route(PATH, methods=["GET", "HEAD"])
    async def trace(request: Request, run_id: str):
        try:
            value = await run_in_threadpool(traces.read, request.state.authenticated_request, run_id,
                                            base_path=base_path)
            # HEAD carries GET's headers; the boundary blanks the body
            return JSONResponse(value, headers={"Cache-Control": "no-store"})
        except RunTraceReadError as error:
            return _error(error.code)
        except OwnerAuthError as error:
            return _error(getattr(error, "code", "unauthenticated"))

    return router
