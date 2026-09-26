"""Fixed HTTP adapter for the owner's inquiry over one observed difference: the
`inquiries-v1` contribution.

- `GET|HEAD /api/v1/inquiries/{difference_id}` — the inquiry, or `not_opened`.
- `POST /api/v1/inquiries/{difference_id}` — the owner opens it (questions frozen).
- `POST /api/v1/inquiries/{difference_id}/answers` — the owner's answer or skip.
- `POST /api/v1/inquiries/{difference_id}/evidence` — evidence the owner supplies.
- `POST /api/v1/inquiries/{difference_id}/judgments` — the owner's judgment on one hypothesis.
- `GET|HEAD /api/v1/inquiries/{difference_id}/audit` — who/what/when, model turns, owner inputs.

The shared `/api/v1` preflight admits each body exactly before auth.
"""

import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.difference_inquiries import (
    ANSWER_SCHEMA,
    EVIDENCE_SCHEMA,
    JUDGMENT_SCHEMA,
    OPEN_SCHEMA,
    InquiryServiceError,
    PersistentDifferenceInquiries,
)
from ..services.owner_auth import OwnerAuthError
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PREFIX = "/api/v1/inquiries/"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404,
          "conflict": 409, "hypotheses_required": 409, "not_opened": 409, "evidence_required": 422,
          "competitors_unexamined": 409, "already_judged": 409, "unavailable": 503,
          "provider_unavailable": 503, "model_output_invalid": 422}
_LIMITS = WireLimits(max_bytes=16_384, max_depth=3, max_items=32, max_members=8, max_string_bytes=8_192)
_BODIES = {
    "": (OPEN_SCHEMA, ("schema_version", "command_id", "model_choice_ref")),
    "answers": (ANSWER_SCHEMA, ("schema_version", "command_id", "question_id", "action", "text")),
    "evidence": (EVIDENCE_SCHEMA, ("schema_version", "command_id", "text", "sources")),
    "judgments": (JUDGMENT_SCHEMA, ("schema_version", "command_id", "hypothesis_id", "judgment",
                                    "evidence_ids", "note")),
}


def is_inquiries_path(path: str) -> bool:
    return path.startswith(PREFIX)


def _body(raw: bytes, action: str) -> dict:
    schema, fields = _BODIES[action]
    value = parse_json_object(raw, required=fields, limits=_LIMITS)
    if value["schema_version"] != schema:
        raise WireInputError("invalid_input")
    if action == "":
        ref = value["model_choice_ref"]
        if ref is not None and (type(ref) is not dict or set(ref) != {"kind", "id", "version", "sha256"}):
            raise WireInputError("invalid_input")
    return value


def _parts(path: str):
    parts = path[len(PREFIX):].split("/")
    if not 1 <= len(parts) <= 2 or (len(parts) == 2 and parts[1] not in {"answers", "evidence", "judgments", "audit"}):
        raise WireInputError("invalid_input")
    try:
        uuid_string(parts[0])
    except (TypeError, ValueError):
        raise WireInputError("invalid_input") from None
    return parts[0], (parts[1] if len(parts) == 2 else "")


def preflight(scope, body):
    parse_query(scope.get("query_string", b""), allowed=())
    _difference, action = _parts(scope["path"])
    method = scope["method"]
    if method in {"GET", "HEAD"}:
        if body or action not in {"", "audit"}:
            raise WireInputError("invalid_input")
    elif method == "POST":
        if action == "audit":
            raise WireInputError("invalid_input")
        _body(body, action)
    else:
        raise WireInputError("invalid_input")


def _error(code):
    # `reason` repeats the closed code: the browser session keeps only its own generic codes
    # (409 → conflict), and the panel needs the exact reason to say what is missing
    return JSONResponse({"code": code, "reason": code, "message": "Inquiry request could not be admitted",
                         "retryability": "not_retryable", "affected_refs": [],
                         "correlation_id": str(uuid4())}, status_code=STATUS.get(code, 503))


def inquiry_services(context, *, dependencies):
    from ..services.claude_run_executor import ClaudeRunExecutor

    if set(dependencies) != {"alternative-drafts.service", "hypotheses.service"}:
        raise TypeError("Invalid inquiry dependencies")
    executor = context.run_executor if type(context.run_executor) is ClaudeRunExecutor else None
    service = PersistentDifferenceInquiries(context.domain_store, context.owner_authority,
                                            dependencies["alternative-drafts.service"],
                                            dependencies["hypotheses.service"], executor,
                                            base_path=context.base_path)
    return ContributionServices(create_router(service=service), {"inquiries.service": service})


def create_router(*, service):
    router = APIRouter()

    async def call(function, *args):
        try:
            return JSONResponse(await run_in_threadpool(function, *args), headers={"Cache-Control": "no-store"})
        except InquiryServiceError as error:
            return _error(error.code)
        except OwnerAuthError as error:
            return _error(getattr(error, "code", "unauthenticated"))

    async def command(function, request, difference_id, action):
        try:
            value = _body(await request.body(), action)
        except (WireInputError, ValueError, json.JSONDecodeError):
            return _error("invalid_input")
        return await call(function, request.state.authenticated_request, difference_id, value)

    @router.api_route(PREFIX + "{difference_id}", methods=["GET", "HEAD"])
    async def read(difference_id: str, request: Request):
        return await call(service.read, request.state.authenticated_request, difference_id)

    @router.post(PREFIX + "{difference_id}")
    async def open_inquiry(difference_id: str, request: Request):
        return await command(service.open, request, difference_id, "")

    @router.post(PREFIX + "{difference_id}/answers")
    async def answer(difference_id: str, request: Request):
        return await command(service.answer, request, difference_id, "answers")

    @router.post(PREFIX + "{difference_id}/evidence")
    async def evidence(difference_id: str, request: Request):
        return await command(service.add_evidence, request, difference_id, "evidence")

    @router.post(PREFIX + "{difference_id}/judgments")
    async def judge(difference_id: str, request: Request):
        return await command(service.judge, request, difference_id, "judgments")

    @router.api_route(PREFIX + "{difference_id}/audit", methods=["GET", "HEAD"])
    async def audit(difference_id: str, request: Request):
        return await call(service.audit, request.state.authenticated_request, difference_id)

    return router
