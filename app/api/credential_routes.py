"""Authenticated HTTP credential routes over the credential-v2 gateway (T090).

The control plane never imports the vault implementation. Each route checks the
session/CSRF authority first, then its exact wire, and only then hands the act to
host-wired state seams: ``credential_gateway_submit`` (create/rotate),
``credential_gateway_retire`` (owner delete) and ``credential_status_snapshot``
(a committed-ledger read). `attach_credential_gateway` binds them to
:class:`~app.api.credential_commands.CredentialActs`, which allocates the gateway
command ids per owner act (``intent_id`` is the act's idempotency key), transmits
a secret at most once per command id and recovers ambiguity by query. Without an
attachment the routes are honestly unavailable. Every seam's return value is
reshaped to a closed redacted projection, so nothing a gateway returns can echo
secret material to the browser.

``cleanup_pending`` and ``erasure_completed`` describe DeepTwin's locally managed
encrypted copies only; no route revokes a key at the provider, so every retirement
projection states ``provider_revocation: "not_performed"``.
"""

from __future__ import annotations

import json
import re

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .credential_commands import CredentialCommandError
from .credential_ingress import (
    CredentialIngressError,
    CredentialIngressTooLarge,
    parse_credential_ingress,
)
from .routes import (
    NOT_RETRYABLE,
    RETRYABLE,
    ApiDependencyUnavailable,
    _authenticated,
    _failure,
    api_error,
)

_RECEIPT_FIELDS = frozenset({"handle", "provider", "state"})
_RECEIPT_STATES = frozenset({"stored_unbound"})
_RETIRE_FIELDS = frozenset({"handle", "state"})
_RETIRE_STATES = frozenset({"cleanup_pending", "erasure_completed"})
_SNAPSHOT_STATES = frozenset({
    "stored_unbound", "pending", "cleanup_pending", "secret_input_lost", "erasure_completed",
})
_HANDLE = re.compile(r"[0-9a-f]{32}\Z")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_MAX_DELETE_BODY = 1024
_ACT_ERRORS = {
    "invalid_input": (400, "invalid_input", "자격증명 요청 형식을 확인해 주세요.", NOT_RETRYABLE),
    "not_found": (404, "not_found", "해당 자격증명을 찾지 못했습니다.", NOT_RETRYABLE),
    "conflict": (409, "conflict", "이 요청은 이미 다른 내용으로 처리됐거나 대상이 바뀌었습니다.",
                 NOT_RETRYABLE),
    "act_in_progress": (409, "conflict", "같은 자격증명에 대한 이전 요청이 아직 끝나지 않았습니다.",
                        RETRYABLE),
    "secret_input_lost": (409, "secret_input_lost",
                          "비밀 값이 저장되기 전에 유실됐습니다. 새 요청으로 비밀 값을 다시 입력해 주세요.",
                          NOT_RETRYABLE),
    "command_pending": (503, "command_pending",
                        "요청 결과를 아직 확인하지 못했습니다. 같은 요청을 다시 보내면 결과를 조회합니다.",
                        RETRYABLE),
    "gateway_unavailable": (503, "dependency_unavailable",
                            "자격증명 게이트웨이에 연결하지 못했습니다.", RETRYABLE),
}


def _act_failure(error: CredentialCommandError):
    known = _ACT_ERRORS.get(error.code)
    if known is None:
        return _failure(ApiDependencyUnavailable("credential gateway result is invalid"))
    status, code, message, retryability = known
    return api_error(status=status, code=code, message=message, retryability=retryability)


def _redacted_receipt(receipt: object) -> dict:
    if (
        type(receipt) is not dict
        or set(receipt) != _RECEIPT_FIELDS
        or any(type(value) is not str for value in receipt.values())
        or receipt["state"] not in _RECEIPT_STATES
        or _HANDLE.fullmatch(receipt["handle"]) is None
    ):
        raise ApiDependencyUnavailable("credential gateway receipt is invalid")
    return {name: receipt[name] for name in ("handle", "provider", "state")}


def _redacted_retirement(receipt: object) -> dict:
    if (
        type(receipt) is not dict
        or set(receipt) != _RETIRE_FIELDS
        or any(type(value) is not str for value in receipt.values())
        or receipt["state"] not in _RETIRE_STATES
        or _HANDLE.fullmatch(receipt["handle"]) is None
    ):
        raise ApiDependencyUnavailable("credential gateway receipt is invalid")
    return {"handle": receipt["handle"], "state": receipt["state"],
            "provider_revocation": "not_performed"}


def _redacted_snapshot(entries: object) -> list[dict]:
    if type(entries) is not list or len(entries) > 256:
        raise ApiDependencyUnavailable("credential snapshot is invalid")
    redacted = []
    for entry in entries:
        if (
            type(entry) is not dict
            or set(entry) != _RECEIPT_FIELDS
            or any(type(value) is not str for value in entry.values())
            or entry["state"] not in _SNAPSHOT_STATES
            or _HANDLE.fullmatch(entry["handle"]) is None
        ):
            raise ApiDependencyUnavailable("credential snapshot is invalid")
        redacted.append(
            {name: entry[name] for name in ("handle", "provider", "state")}
            | {"provider_revocation": "not_performed"}
        )
    return redacted


def _delete_intent(request: Request, body: bytes) -> str:
    """The exact `{"intent_id": uuid}` body of an owner delete act."""
    types = [value for name, value in request.scope.get("headers", ())
             if bytes(name).lower() == b"content-type"]
    if (len(types) != 1 or bytes(types[0]).split(b";", 1)[0].strip().lower() != b"application/json"
            or request.query_params or not 1 <= len(body) <= _MAX_DELETE_BODY):
        raise ValueError("delete intent framing")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate field")
            value[key] = item
        return value

    value = json.loads(body.decode("utf-8"), object_pairs_hook=unique)
    if type(value) is not dict or set(value) != {"intent_id"}:
        raise ValueError("delete intent shape")
    intent = value["intent_id"]
    if type(intent) is not str or _UUID.fullmatch(intent) is None:
        raise ValueError("delete intent id")
    return intent


def install_credential_ingress(app) -> None:
    """Attach the authenticated create/rotate, delete and status routes."""

    @app.api_route("/api/v1/credentials", methods=["POST"])
    async def credentials_v1(request: Request):
        try:
            _authenticated(request, read=False)
            body = await request.body()
            try:
                ingress = parse_credential_ingress(
                    [
                        (bytes(name), bytes(value))
                        for name, value in request.scope.get("headers", ())
                    ],
                    bytes(body),
                )
            except CredentialIngressError as exc:
                return api_error(
                    status=413 if isinstance(exc, CredentialIngressTooLarge) else 400,
                    code="invalid_input",
                    message="자격증명 요청 형식을 확인해 주세요.",
                    retryability=NOT_RETRYABLE,
                )
            finally:
                del body
            if request.query_params:
                return api_error(status=400, code="invalid_input",
                                 message="자격증명 요청 형식을 확인해 주세요.",
                                 retryability=NOT_RETRYABLE)
            submit = getattr(
                request.app.state, "credential_gateway_submit", None
            )
            if submit is None:
                raise ApiDependencyUnavailable(
                    "credential gateway is not attached"
                )
            try:
                receipt = await run_in_threadpool(submit, ingress)
            except CredentialCommandError as exc:
                return _act_failure(exc)
            finally:
                del ingress
            return JSONResponse(status_code=201, content=_redacted_receipt(receipt))
        except Exception as exc:  # noqa: BLE001 - sanitize the public boundary
            return _failure(exc)

    @app.api_route("/api/v1/credentials/{handle}", methods=["DELETE"])
    async def credential_delete_v1(handle: str, request: Request):
        try:
            _authenticated(request, read=False)
            body = await request.body()
            try:
                if type(handle) is not str or _HANDLE.fullmatch(handle) is None:
                    raise ValueError("handle")
                intent_id = _delete_intent(request, bytes(body))
            except (ValueError, UnicodeDecodeError, RecursionError):
                return api_error(
                    status=400,
                    code="invalid_input",
                    message="자격증명 핸들 형식을 확인해 주세요.",
                    retryability=NOT_RETRYABLE,
                )
            retire = getattr(
                request.app.state, "credential_gateway_retire", None
            )
            if retire is None:
                raise ApiDependencyUnavailable(
                    "credential gateway is not attached"
                )
            try:
                receipt = await run_in_threadpool(retire, intent_id, handle)
            except CredentialCommandError as exc:
                return _act_failure(exc)
            return JSONResponse(status_code=200, content=_redacted_retirement(receipt))
        except Exception as exc:  # noqa: BLE001 - sanitize the public boundary
            return _failure(exc)

    @app.api_route("/api/v1/credentials", methods=["GET"])
    async def credential_status_v1(request: Request):
        try:
            # A status read is a snapshot of already-committed redacted ledger state;
            # it makes zero vault, gateway, provider or network effect.
            _authenticated(request, read=True)
            snapshot = getattr(
                request.app.state, "credential_status_snapshot", None
            )
            if snapshot is None:
                raise ApiDependencyUnavailable(
                    "credential status snapshot is not attached"
                )
            return JSONResponse(
                status_code=200,
                content={"credentials": _redacted_snapshot(snapshot())},
            )
        except Exception as exc:  # noqa: BLE001 - sanitize the public boundary
            return _failure(exc)


__all__ = ["attach_credential_gateway", "install_credential_ingress"]


def attach_credential_gateway(app, client, ledger) -> None:
    """Bind a frame-only gateway client and the control-plane command ledger to the
    route state seams.

    The client comes from :mod:`app.workers.credential_channel`, which imports no
    vault code. The status snapshot reads the ledger only — never the gateway.
    """
    from .credential_commands import CredentialActs

    acts = CredentialActs(client, ledger)
    app.state.credential_gateway_submit = acts.store
    app.state.credential_gateway_retire = (
        lambda intent_id, handle: acts.delete(intent_id=intent_id, handle=handle)
    )
    app.state.credential_status_snapshot = ledger.snapshot
