"""Fixed HTTP adapter for the owner's process feedback on a run: the `run-feedback-v1`
contribution (docs/ui/2026-09-26-product-ux-redesign.md §6).

- `GET|HEAD /api/v1/runs/{run_id}/feedback` reads the latest revision of every target (the
  run as a whole, or one node's exact visit and attempt) and the whole revision history.
- `POST /api/v1/runs/{run_id}/feedback` sets or clears one target's feedback — an optional
  mark (`ok` / `needs_attention`) and an optional memo, at least one of them for a set — as a
  new immutable revision (`process-feedback-command-v1`, `services/run_feedback.py`).

Owner browser session only (a bearer gets `401` before any parsing). A write is a
CSRF-verified same-origin command with its own command id. The path is admitted by the run
routes' shared preflight (`runs.is_run_path`, `runs.feedback_command`), which also bounds the
body (`runs.FEEDBACK_BODY_BYTES`). Feedback is never an alternative and is never counted as one.
"""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..services.owner_auth import OwnerAuthError
from ..services.run_feedback import PersistentRunFeedback, RunFeedbackError
from .first_party import ContributionServices

PATH = "/api/v1/runs/{run_id}/feedback"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404,
          "conflict": 409, "too_large": 413, "unavailable": 503}


def _error(code):
    code = code if code in STATUS else "unavailable"
    return JSONResponse({"code": code, "message": "Run feedback request could not be admitted",
                         "retryability": "not_retryable", "affected_refs": [],
                         "correlation_id": str(uuid4())}, status_code=STATUS[code])


def run_feedback_services(context, *, dependencies):
    if set(dependencies) != {"run-trace.service"}:
        raise TypeError("Invalid run feedback dependencies")
    feedback = PersistentRunFeedback(dependencies["run-trace.service"])
    return ContributionServices(create_router(feedback=feedback, base_path=context.base_path),
                                {"run-feedback.service": feedback})


def create_router(*, feedback, base_path):
    router = APIRouter()

    async def call(function, *args, status=200):
        try:
            value = await run_in_threadpool(function, *args, base_path=base_path)
            # HEAD carries GET's headers; the boundary blanks the body
            return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})
        except RunFeedbackError as error:
            return _error(error.code)
        except OwnerAuthError as error:
            return _error(getattr(error, "code", "unauthenticated"))

    @router.api_route(PATH, methods=["GET", "HEAD"])
    async def read(request: Request, run_id: str):
        return await call(feedback.read, request.state.authenticated_request, run_id)

    @router.post(PATH)
    async def record(request: Request, run_id: str):
        return await call(feedback.record, request.state.authenticated_request, run_id,
                          request.state.run_payload, status=201)

    return router
