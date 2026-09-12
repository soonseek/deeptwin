"""Authenticated, strict API-key connection routes with masked responses only."""

import json
import sqlite3

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from ..adapters.keychain import (
    CredentialAccessDenied,
    CredentialError,
    CredentialNeedsUnlock,
    CredentialNotFound,
)
from ..services.provider_connections import (
    CorruptProviderConnection,
    ProviderConnectionConflict,
    ProviderConnections,
)
from .routes import api_error
from .session import AuthenticatedRequest, RequestDenied

_CONFIGURE_FIELDS = {
    "expected_version",
    "key",
    "workspace_id",
    "project_id",
    "organization_id",
}


class ProviderConnectionInput(ValueError):
    pass


def _authenticated(request, *, read):
    value = request.scope.get("state", {}).get("authenticated_request")
    if (type(value) is not AuthenticatedRequest
            or value.is_read is not read
            or (not read and not value.csrf_verified)
            or value.session.actor.kind != "human"):
        raise RequestDenied("Authenticated provider request required")


def _path(provider, mode):
    if provider not in {"claude", "codex"}:
        raise KeyError(provider)
    if mode != "api":
        raise ProviderConnectionInput("Only explicit API-key connections are supported here")


async def _payload(request, fields):
    if request.query_params:
        raise ProviderConnectionInput("Provider mutations do not accept query fields")
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise ProviderConnectionInput("Provider connection body must be JSON")
    try:
        raw = (await request.body()).decode("utf-8")

        def exact_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ProviderConnectionInput("Duplicate JSON field")
                result[key] = value
            return result

        def reject_constant(_value):
            raise ProviderConnectionInput("Non-finite JSON value")

        value = json.loads(
            raw,
            object_pairs_hook=exact_object,
            parse_constant=reject_constant,
        )
    except (
        ProviderConnectionInput,
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
    ) as exc:
        raise ProviderConnectionInput("Provider connection body is invalid") from exc
    if type(value) is not dict or set(value) != set(fields):
        raise ProviderConnectionInput("Provider connection fields are invalid")
    return value


def _error(error):
    if isinstance(error, ProviderConnectionConflict):
        return api_error(
            status=409,
            code="stale_state",
            message="연결 설정이 다른 화면에서 변경되었습니다. 현재 상태를 다시 불러오세요.",
        )
    if isinstance(error, KeyError):
        return api_error(
            status=404,
            code="not_found",
            message="요청한 모델 제공자를 찾지 못했습니다.",
        )
    if isinstance(error, CredentialNeedsUnlock):
        return api_error(
            status=503,
            code="credential_needs_unlock",
            message="보호된 API 키 저장소가 잠겨 있습니다. 잠금을 해제한 뒤 다시 시도하세요.",
            retryability="retryable",
        )
    if isinstance(error, CredentialAccessDenied):
        return api_error(
            status=503,
            code="credential_access_blocked",
            message="DeepTwin이 보호된 API 키 저장소에 접근할 수 없습니다.",
        )
    if isinstance(error, CredentialNotFound):
        return api_error(
            status=503,
            code="credential_missing",
            message="보관된 API 키를 찾지 못했습니다. 연결을 다시 설정하세요.",
        )
    if isinstance(error, CredentialError):
        return api_error(
            status=503,
            code="dependency_unavailable",
            message="보호된 API 키 저장소를 사용할 수 없습니다. 연결 상태를 유지한 채 다시 시도하세요.",
            retryability="retryable",
        )
    if isinstance(error, (CorruptProviderConnection, sqlite3.Error, OSError)):
        return api_error(
            status=503,
            code="storage_failed",
            message="보관된 연결 상태를 안전하게 확인하지 못했습니다.",
        )
    if isinstance(error, RequestDenied):
        return api_error(
            status=403,
            code="access_denied",
            message="인증된 DeepTwin 브라우저 세션이 필요합니다.",
        )
    if isinstance(error, (ProviderConnectionInput, TypeError, ValueError)):
        return api_error(
            status=400,
            code="invalid_input",
            message="API 연결 방식과 입력 항목을 확인해 주세요.",
        )
    raise error


_HANDLED = (
    CorruptProviderConnection,
    CredentialError,
    KeyError,
    OSError,
    ProviderConnectionConflict,
    ProviderConnectionInput,
    RequestDenied,
    sqlite3.Error,
    TypeError,
    ValueError,
)


async def _service(call, *args, **kwargs):
    try:
        return await run_in_threadpool(call, *args, **kwargs)
    except _HANDLED as error:
        return _error(error)


def _current_connections(request):
    """Resolve the lifespan-current service instead of a stale route closure."""
    value = getattr(request.app.state, "provider_connections", None)
    if not isinstance(value, ProviderConnections):
        raise CorruptProviderConnection(
            "Current provider connection service is unavailable"
        )
    return value


def install_provider_connection_routes(app, *, connections):
    if not isinstance(connections, ProviderConnections):
        raise TypeError("Provider routes require ProviderConnections")

    @app.get("/api/v1/connections/{provider}/{mode}")
    async def read_connection(provider: str, mode: str, request: Request):
        try:
            _authenticated(request, read=True)
            _path(provider, mode)
            if request.query_params:
                raise ProviderConnectionInput(
                    "Provider reads do not accept query fields"
                )
        except _HANDLED as error:
            return _error(error)
        try:
            current = _current_connections(request)
        except _HANDLED as error:
            return _error(error)
        return await _service(current.get, provider, mode)

    @app.put("/api/v1/connections/{provider}/{mode}")
    async def configure_connection(provider: str, mode: str, request: Request):
        try:
            _authenticated(request, read=False)
            _path(provider, mode)
            value = await _payload(request, _CONFIGURE_FIELDS)
        except _HANDLED as error:
            return _error(error)
        try:
            current = _current_connections(request)
        except _HANDLED as error:
            return _error(error)
        return await _service(
            current.configure,
            provider,
            mode,
            value["expected_version"],
            value["key"],
            workspace_id=value["workspace_id"],
            project_id=value["project_id"],
            organization_id=value["organization_id"],
        )

    @app.delete("/api/v1/connections/{provider}/{mode}")
    async def delete_connection(provider: str, mode: str, request: Request):
        try:
            _authenticated(request, read=False)
            _path(provider, mode)
            value = await _payload(request, {"expected_version"})
        except _HANDLED as error:
            return _error(error)
        try:
            current = _current_connections(request)
        except _HANDLED as error:
            return _error(error)
        return await _service(
            current.delete,
            provider,
            mode,
            value["expected_version"],
        )

    return connections
