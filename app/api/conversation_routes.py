"""Authenticated HTTP projection for one shared, work-bound conversation.

The browser supplies message content and exact references, never an actor or authority.
Material chat text remains inert unless it is tied to a server-issued challenge and passes
the same ``Conversation.validate_invocation`` path as the corresponding UI button.  A
successful response is a validation receipt only; this module deliberately executes no
domain command.
"""

import json
import sqlite3

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..domain.refs import DomainContractError, EntityRef, ObjectRef
from ..services.conversation import (
    Conversation,
    ConversationAuthorityError,
    ConversationConflict,
    ConversationError,
    TrustedConversationActor,
)
from ..storage import ConflictError
from .routes import api_error
from .session import AuthenticatedRequest, RequestDenied

_USER_MESSAGE_ORIGINS = frozenset({
    "work_request",
    "clarification",
    "own_artifact",
    "analysis_evidence",
})


class ConversationApiInput(ValueError):
    pass


_HANDLED_ERRORS = (
    ConversationApiInput,
    ConversationError,
    DomainContractError,
    ConflictError,
    KeyError,
    OSError,
    RequestDenied,
    sqlite3.Error,
    TypeError,
    ValueError,
)


def _actor(request, *, read):
    authenticated = request.scope.get("state", {}).get("authenticated_request")
    if (type(authenticated) is not AuthenticatedRequest
            or authenticated.is_read is not read
            or (not read and not authenticated.csrf_verified)
            or authenticated.session.actor.kind != "human"):
        raise RequestDenied("Authenticated local conversation request required")
    return TrustedConversationActor(
        authenticated.session.actor.id,
        "human",
        "local_human",
    )


async def _payload(request, fields):
    if request.query_params:
        raise ConversationApiInput("Conversation mutations do not accept query fields")
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise ConversationApiInput("Conversation body must be JSON")
    try:
        raw = (await request.body()).decode("utf-8")

        def exact_object(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ConversationApiInput("Duplicate JSON field")
                value[key] = item
            return value

        value = json.loads(raw, object_pairs_hook=exact_object)
    except (ConversationApiInput, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ConversationApiInput("Conversation body is invalid") from exc
    if type(value) is not dict or set(value) != set(fields):
        raise ConversationApiInput("Conversation fields are invalid")
    return value


def _entity_refs(value):
    if type(value) is not list or len(value) > 64:
        raise ConversationApiInput("Message references are invalid")
    try:
        refs = tuple(EntityRef.from_dict(item) for item in value)
    except (DomainContractError, TypeError, ValueError) as exc:
        raise ConversationApiInput("Message references are invalid") from exc
    if len(set(refs)) != len(refs):
        raise ConversationApiInput("Message references are duplicated")
    return refs


def _object_ref(value):
    if type(value) is not dict or set(value) != {
        "kind", "id", "version", "content_hash"
    }:
        raise ConversationApiInput("An exact command target is required")
    try:
        result = ObjectRef(**value)
    except (DomainContractError, TypeError, ValueError) as exc:
        raise ConversationApiInput("An exact command target is required") from exc
    if result.version is None or result.content_hash is None:
        raise ConversationApiInput("An exact command target is required")
    return result


def _command_target(conversation, command_id, work_id, target):
    command = conversation.get_command(command_id)
    if (command["work_id"] != work_id
            or command["exact_target_ref"] != target.as_dict()):
        raise ConversationConflict("Command target does not match this work")
    return command


def _error(error):
    if isinstance(error, ConversationAuthorityError):
        return api_error(
            status=403,
            code="authority_required",
            message="이 행동은 인증된 DeepTwin 소유자의 명시적 확인이 필요합니다.",
        )
    if isinstance(error, (ConversationConflict, ConflictError)):
        return api_error(
            status=409,
            code="stale_or_conflicting_state",
            message="현재 업무 버전이나 확인 대상이 달라졌습니다. 최신 상태를 다시 확인하세요.",
        )
    if isinstance(error, KeyError):
        return api_error(
            status=404,
            code="not_found",
            message="요청한 업무나 대화 대상을 찾지 못했습니다.",
        )
    if isinstance(error, (sqlite3.Error, OSError)):
        return api_error(
            status=503,
            code="storage_unavailable",
            message="대화 기록을 DeepTwin 인스턴스의 업무 저장소에 저장하지 못했습니다.",
            retryability="retryable",
        )
    if isinstance(error, RequestDenied):
        return api_error(
            status=403,
            code="access_denied",
            message="인증된 DeepTwin 브라우저 세션이 필요합니다.",
        )
    if isinstance(error, (
        ConversationApiInput,
        ConversationError,
        DomainContractError,
        TypeError,
        ValueError,
    )):
        return api_error(
            status=400,
            code="invalid_input",
            message="대화 내용과 참조 대상을 확인해 주세요.",
        )
    raise error


async def _service(call, *args, **kwargs):
    try:
        return await run_in_threadpool(call, *args, **kwargs)
    except _HANDLED_ERRORS as error:
        return _error(error)


def install_conversation_routes(app, *, conversation):
    if type(conversation) is not Conversation:
        raise TypeError("Conversation routes require one trusted Conversation service")

    @app.get("/api/v1/works/{work_id}/messages")
    async def list_messages(work_id: str, request: Request):
        try:
            _actor(request, read=True)
            if request.query_params:
                raise ConversationApiInput("Conversation reads do not accept query fields")
        except _HANDLED_ERRORS as error:
            return _error(error)
        result = await _service(conversation.list_messages, work_id)
        if isinstance(result, JSONResponse):
            return result
        return {"messages": result}

    @app.post("/api/v1/works/{work_id}/messages", status_code=201)
    async def add_message(work_id: str, request: Request):
        try:
            actor = _actor(request, read=False)
            value = await _payload(request, {
                "work_revision",
                "content",
                "semantic_origin",
                "referenced_entity_refs",
            })
            if value["semantic_origin"] not in _USER_MESSAGE_ORIGINS:
                raise ConversationApiInput(
                    "The ordinary message route cannot create command requests"
                )
            refs = _entity_refs(value["referenced_entity_refs"])
        except _HANDLED_ERRORS as error:
            return _error(error)
        result = await _service(
            conversation.add_message,
            work_id,
            value["work_revision"],
            value["content"],
            semantic_origin=value["semantic_origin"],
            actor=actor,
            referenced_entities=refs,
        )
        if isinstance(result, JSONResponse):
            return result
        return {"message": result}

    @app.get("/api/v1/works/{work_id}/conversation-commands")
    async def list_commands(work_id: str, request: Request):
        try:
            _actor(request, read=True)
            if request.query_params:
                raise ConversationApiInput("Conversation reads do not accept query fields")
        except _HANDLED_ERRORS as error:
            return _error(error)
        result = await _service(conversation.list_proposed_commands, work_id)
        if isinstance(result, JSONResponse):
            return result
        return {"commands": result}

    @app.post(
        "/api/v1/conversation/commands/{command_id}/challenges",
        status_code=201,
    )
    async def open_challenge(command_id: str, request: Request):
        try:
            actor = _actor(request, read=False)
            value = await _payload(request, {"work_id", "exact_target_ref"})
            target = _object_ref(value["exact_target_ref"])
        except _HANDLED_ERRORS as error:
            return _error(error)
        checked = await _service(
            _command_target,
            conversation,
            command_id,
            value["work_id"],
            target,
        )
        if isinstance(checked, JSONResponse):
            return checked
        result = await _service(
            conversation.open_challenge,
            command_id,
            authority=actor,
        )
        if isinstance(result, JSONResponse):
            return result
        return {"challenge": result}

    @app.post("/api/v1/conversation/commands/{command_id}/button-validation")
    async def validate_button(command_id: str, request: Request):
        try:
            actor = _actor(request, read=False)
            value = await _payload(request, {
                "work_id",
                "challenge_id",
                "token",
                "exact_target_ref",
            })
            target = _object_ref(value["exact_target_ref"])
        except _HANDLED_ERRORS as error:
            return _error(error)
        checked = await _service(
            _command_target,
            conversation,
            command_id,
            value["work_id"],
            target,
        )
        if isinstance(checked, JSONResponse):
            return checked
        result = await _service(
            conversation.validate_invocation,
            command_id,
            value["challenge_id"],
            value["token"],
            authority=actor,
            response_message_id=None,
            route="button",
        )
        if isinstance(result, JSONResponse):
            return result
        return {"validation": result, "executed": False}

    @app.post("/api/v1/works/{work_id}/command-responses")
    async def validate_chat(work_id: str, request: Request):
        try:
            actor = _actor(request, read=False)
            value = await _payload(request, {
                "work_revision",
                "command_id",
                "challenge_id",
                "token",
                "content",
                "exact_target_ref",
            })
            target = _object_ref(value["exact_target_ref"])
        except _HANDLED_ERRORS as error:
            return _error(error)
        checked = await _service(
            _command_target,
            conversation,
            value["command_id"],
            work_id,
            target,
        )
        if isinstance(checked, JSONResponse):
            return checked
        result = await _service(
            conversation.record_and_validate_chat_invocation,
            work_id,
            value["work_revision"],
            value["content"],
            value["command_id"],
            value["challenge_id"],
            value["token"],
            authority=actor,
            exact_target=target,
        )
        if isinstance(result, JSONResponse):
            return result
        message, validation = result
        return {"message": message, "validation": validation, "executed": False}

    return conversation
