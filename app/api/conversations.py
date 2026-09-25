"""Fixed HTTP adapter for the supported factory's shared conversation: the
`conversations-v1` contribution (T023, FR-009).

- `GET|HEAD /api/v1/conversations/{work_id}`: the work's messages in order and its
  referenced-object proposals with their state (an open challenge shows its phrase to the
  session it was issued to; the token is never shown again);
- `POST …/messages` (`conversation-message-command-v1`): an owner message bound to the
  current revision and exact same-work references — ordinary words, never authority;
- `POST …/proposals` (`conversation-proposal-command-v1`): a command over one record the
  message named; opens a challenge for this session;
- `POST …/challenges` (`conversation-challenge-command-v1`): a fresh challenge;
- `POST …/approvals` (`conversation-approval-command-v1`): the challenge answered by button
  (`text: null`) or by the exact phrase in the conversation, then run once.

Every body is closed: an actor, authority, origin or approval field is not a member and
fails the wire before auth. The shared `/api/v1` preflight admits each body exactly.
"""

import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.conversation import (
    SUPPORTED_APPROVAL_COMMAND,
    SUPPORTED_CHALLENGE_COMMAND,
    SUPPORTED_MAX_TEXT_BYTES,
    SUPPORTED_MESSAGE_COMMAND,
    SUPPORTED_PROPOSAL_COMMAND,
    PersistentConversation,
    SupportedConversationError,
)
from ..services.owner_auth import OwnerAuthError
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/conversations"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404,
          "conflict": 409, "approval_ambiguous": 409, "unavailable": 503, "capacity": 429}
_LIMITS = WireLimits(max_bytes=SUPPORTED_MAX_TEXT_BYTES + 4_096, max_depth=4, max_items=128, max_members=8,
                     max_string_bytes=SUPPORTED_MAX_TEXT_BYTES)
_REF = {"kind", "id", "version", "sha256"}
BODIES = {
    "messages": (("schema_version", "command_id", "expected_revision", "text", "references"),
                 SUPPORTED_MESSAGE_COMMAND),
    "proposals": (("schema_version", "command_id", "message_id", "command_kind", "target_ref"),
                  SUPPORTED_PROPOSAL_COMMAND),
    "challenges": (("schema_version", "command_id", "proposal_id"), SUPPORTED_CHALLENGE_COMMAND),
    "approvals": (("schema_version", "command_id", "proposal_id", "challenge_id", "token", "route", "text"),
                  SUPPORTED_APPROVAL_COMMAND),
}


def is_conversations_path(path: str) -> bool:
    return path == PATH or path.startswith(PATH + "/")


def _body(raw: bytes, name: str) -> dict:
    fields, schema = BODIES[name]
    value = parse_json_object(raw, required=fields, limits=_LIMITS)
    if value["schema_version"] != schema:
        raise WireInputError("invalid_input")
    refs = value.get("references", []) if name == "messages" else [value["target_ref"]] if name == "proposals" else []
    if type(refs) is not list or any(type(item) is not dict or set(item) != _REF for item in refs):
        raise WireInputError("invalid_input")
    return value


def _route(path: str):
    rest = path[len(PATH) + 1:].split("/") if path.startswith(PATH + "/") else []
    try:
        if not 1 <= len(rest) <= 2:
            raise ValueError
        uuid_string(rest[0])
    except (TypeError, ValueError):
        raise WireInputError("invalid_input") from None
    if len(rest) == 2 and rest[1] not in BODIES:
        raise WireInputError("invalid_input")
    return rest


def preflight(scope, body):
    parse_query(scope.get("query_string", b""), allowed=())
    rest = _route(scope["path"])
    method = scope["method"]
    if len(rest) == 1:
        if method not in {"GET", "HEAD"} or body:
            raise WireInputError("invalid_input")
        return
    if method != "POST":
        raise WireInputError("invalid_input")
    _body(body, rest[1])


def _error(code):
    body = {"code": code, "message": "Conversation request could not be admitted",
            "retryability": "not_retryable", "affected_refs": [], "correlation_id": str(uuid4())}
    if code == "approval_ambiguous":
        body["reason"] = code  # the shell's closed partition reads it as a 409 conflict with this reason
    return JSONResponse(body, status_code=STATUS.get(code, 503))


def conversation_services(context, *, dependencies):
    if set(dependencies) != {"works.service", "work-models.service"}:
        raise TypeError("Invalid conversation dependencies")
    service = PersistentConversation(dependencies["works.service"], dependencies["work-models.service"])
    return ContributionServices(create_router(service=service), {"conversations.service": service})


def create_router(*, service):
    router = APIRouter()
    commands = {"messages": service.post_message, "proposals": service.propose,
                "challenges": service.reissue, "approvals": service.approve}

    async def call(function, *args, status=200):
        try:
            return JSONResponse(await run_in_threadpool(function, *args), status_code=status,
                                headers={"Cache-Control": "no-store"})
        except SupportedConversationError as error:
            return _error(error.code)
        except OwnerAuthError as error:
            return _error(getattr(error, "code", "unauthenticated"))

    @router.api_route(PATH + "/{work_id}", methods=["GET", "HEAD"])
    async def read(work_id: str, request: Request):
        return await call(service.read, request.state.authenticated_request, work_id)

    def command_route(name):
        async def endpoint(work_id: str, request: Request):
            try:
                value = _body(await request.body(), name)
            except (WireInputError, ValueError, json.JSONDecodeError):
                return _error("invalid_input")
            return await call(commands[name], request.state.authenticated_request, work_id, value,
                              status=201 if name in {"messages", "proposals"} else 200)

        endpoint.__name__ = f"conversation_{name}"
        return endpoint

    for name in BODIES:
        router.add_api_route(PATH + "/{work_id}/" + name, command_route(name), methods=["POST"])
    return router
