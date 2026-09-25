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

``POST /api/v1/credentials/fences`` (``credential_act_fence``) is the owner's explicit
resolution of a store act whose gateway command stays ``unknown`` (see
:meth:`~app.api.credential_commands.CredentialActs.fence`). The status read also
lists each provider connection's binding head (binding revision, and whether a
catalog snapshot/model choice is current for that revision) and the unfinished or
fenced acts, all from the committed ledger.

``POST /api/v1/credentials/connections/{provider}/catalog-refresh``
(``credential_catalog_refresh``) is the owner's one explicit provider read: the model
list for the connection's current binding revision, through the gateway's
provider-send path, recorded by CAS on that revision (a rotation in between answers
``409 catalog_stale``). ``…/model-choice`` (``credential_model_choice``) records a
model that revision's catalog lists. Neither is called by any other route.

The browser-facing ``handle`` is the record id (hex): a stable nonsecret address
for rotate/delete. It is not a gateway resolution handle and confers no dispatch
authority (api.md "Secrets", handle wording, 2026-09-25).

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
_SNAPSHOT_KEYS = frozenset({"credentials", "connections", "pending_acts"})
_CONNECTION_FIELDS = frozenset({"provider", "state", "handle", "binding_revision", "catalog",
                                "model_choice", "gateway_head", "models", "chosen_model"})
_CONNECTION_STATES = frozenset({"bound", "revoked_pending_erasure"})
_PENDING_FIELDS = frozenset({"intent_id", "kind", "handle", "provider", "state",
                             "fence_available_at", "uncertain_record"})
_UNCERTAIN = frozenset({"unknown", "secret_input_lost", "retirement_pending", "cleanup_pending"})
_FENCE_FIELDS = frozenset({"intent_id", "state", "uncertain_record"})
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z")
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
    "connection_bound": (409, "connection_bound",
                         "이 제공자에는 이미 연결된 키가 있습니다. 새 키로 바꾸려면 교체를 사용하세요.",
                         NOT_RETRYABLE),
    "connection_conflict": (409, "connection_conflict",
                            "저장하는 동안 제공자 연결이 바뀌었습니다. 이번 키는 연결하지 않고 정리합니다.",
                            NOT_RETRYABLE),
    "fenced": (409, "fenced",
               "이 요청은 결과를 확인하지 못해 차단됐습니다. 새 요청으로 다시 시도해 주세요.",
               NOT_RETRYABLE),
    "not_fenceable": (409, "conflict", "이 요청은 차단할 수 있는 상태가 아닙니다.", NOT_RETRYABLE),
    "fence_not_due": (409, "fence_not_due",
                      "아직 결과를 기다리는 중입니다. 조금 뒤에 다시 차단할 수 있습니다.", RETRYABLE),
    "catalog_unavailable": (503, "dependency_unavailable",
                            "모델 목록을 읽을 게이트웨이 경로가 연결되어 있지 않습니다.", RETRYABLE),
    "catalog_unsupported": (409, "catalog_unsupported",
                            "이 제공자의 모델 목록은 게이트웨이로 읽을 수 없습니다.", NOT_RETRYABLE),
    "connection_unbound": (409, "connection_unbound",
                           "이 제공자에는 연결된 키가 없습니다. 먼저 키를 저장해 주세요.", NOT_RETRYABLE),
    "catalog_stale": (409, "catalog_stale",
                      ("요청하는 동안 제공자 연결이 바뀌었습니다. 이 결과는 쓰지 않습니다. "
                       "현재 연결로 모델 목록을 다시 새로 고쳐 주세요."), NOT_RETRYABLE),
    "model_not_listed": (409, "model_not_listed",
                         "현재 연결의 모델 목록에 없는 모델입니다.", NOT_RETRYABLE),
    "binding_refused": (409, "binding_refused",
                        "게이트웨이가 이 연결의 키 사용을 거부했습니다. 연결 상태를 다시 읽어 주세요.",
                        NOT_RETRYABLE),
    "transport_unqualified": (409, "transport_unqualified",
                              ("게이트웨이의 제공자 전송 매니페스트가 검증(qualification)되지 않았거나 "
                               "검증 뒤 바뀌었습니다. 이 키로는 아무 요청도 보내지 않았습니다."),
                              NOT_RETRYABLE),
    "budget_refused": (409, "budget_refused",
                       ("이 새로 고침의 예산 예약이 한도를 넘었거나 이미 쓰였습니다. "
                        "제공자에게는 보내지 않았습니다. 새로 고침을 다시 시작해 주세요."),
                       NOT_RETRYABLE),
    "provider_rejected": (424, "provider_rejected",
                          "제공자가 이 키로 모델 목록을 읽는 것을 거부했습니다.", NOT_RETRYABLE),
    "provider_unavailable": (503, "provider_unavailable",
                             "제공자의 모델 목록을 읽지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
                             RETRYABLE),
}
_PROVIDERS = frozenset({"claude", "codex"})
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_CATALOG_FIELDS = frozenset({"provider", "binding_revision", "catalog", "models", "chosen_model"})
_CHOICE_FIELDS = frozenset({"provider", "binding_revision", "model"})


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


def _invalid_snapshot():
    return ApiDependencyUnavailable("credential snapshot is invalid")


def _redacted_connection(entry: object) -> dict:
    if (
        type(entry) is not dict
        or set(entry) != _CONNECTION_FIELDS
        or entry["provider"] not in ("claude", "codex")
        or entry["state"] not in _CONNECTION_STATES
        or type(entry["handle"]) is not str or _HANDLE.fullmatch(entry["handle"]) is None
        or type(entry["binding_revision"]) is not int or entry["binding_revision"] < 1
        or entry["catalog"] not in ("current", "absent")
        or entry["model_choice"] not in ("current", "absent")
        or entry["gateway_head"] not in ("applied", "pending")
        or not _model_list(entry["models"], empty=entry["catalog"] == "absent")
        or not (entry["chosen_model"] is None if entry["model_choice"] == "absent"
                else entry["chosen_model"] in entry["models"])
    ):
        raise _invalid_snapshot()
    return {name: entry[name] for name in sorted(_CONNECTION_FIELDS)}


def _model_list(value, *, empty):
    if type(value) is not list:
        return False
    if empty:
        return value == []
    return (1 <= len(value) <= 200 and len(set(value)) == len(value)
            and all(type(model) is str and _MODEL.fullmatch(model) for model in value))


def _redacted_catalog(receipt: object) -> dict:
    if (type(receipt) is not dict or set(receipt) != _CATALOG_FIELDS
            or receipt["provider"] not in _PROVIDERS
            or type(receipt["binding_revision"]) is not int or receipt["binding_revision"] < 1
            or receipt["catalog"] != "current" or not _model_list(receipt["models"], empty=False)
            or not (receipt["chosen_model"] is None or receipt["chosen_model"] in receipt["models"])):
        raise ApiDependencyUnavailable("credential catalog receipt is invalid")
    return {name: receipt[name] for name in sorted(_CATALOG_FIELDS)}


def _redacted_choice(receipt: object) -> dict:
    if (type(receipt) is not dict or set(receipt) != _CHOICE_FIELDS
            or receipt["provider"] not in _PROVIDERS
            or type(receipt["binding_revision"]) is not int or receipt["binding_revision"] < 1
            or type(receipt["model"]) is not str or _MODEL.fullmatch(receipt["model"]) is None):
        raise ApiDependencyUnavailable("credential model choice receipt is invalid")
    return {name: receipt[name] for name in sorted(_CHOICE_FIELDS)}


def _redacted_pending(entry: object) -> dict:
    if (
        type(entry) is not dict
        or set(entry) != _PENDING_FIELDS
        or type(entry["intent_id"]) is not str or _UUID.fullmatch(entry["intent_id"]) is None
        or entry["kind"] not in ("create", "rotate", "delete")
        or type(entry["handle"]) is not str or _HANDLE.fullmatch(entry["handle"]) is None
        or entry["provider"] not in ("claude", "codex")
        or entry["state"] not in ("command_pending", "fenced")
        or not (entry["fence_available_at"] is None
                or (type(entry["fence_available_at"]) is str
                    and _STAMP.fullmatch(entry["fence_available_at"]) is not None))
        or not (entry["uncertain_record"] is None or entry["uncertain_record"] in _UNCERTAIN)
    ):
        raise _invalid_snapshot()
    return {name: entry[name] for name in sorted(_PENDING_FIELDS)}


def _redacted_status(value: object) -> dict:
    """The GET body. A bare list is the credential list alone (a seam without binding
    state); the ledger's snapshot also carries connections and pending acts."""
    if type(value) is list:
        return {"credentials": _redacted_snapshot(value)}
    if (type(value) is not dict or set(value) != _SNAPSHOT_KEYS
            or type(value["connections"]) is not list or len(value["connections"]) > 16
            or type(value["pending_acts"]) is not list or len(value["pending_acts"]) > 256):
        raise _invalid_snapshot()
    return {"credentials": _redacted_snapshot(value["credentials"]),
            "connections": [_redacted_connection(entry) for entry in value["connections"]],
            "pending_acts": [_redacted_pending(entry) for entry in value["pending_acts"]]}


def _redacted_fence(receipt: object) -> dict:
    if (type(receipt) is not dict or set(receipt) != _FENCE_FIELDS
            or type(receipt["intent_id"]) is not str or _UUID.fullmatch(receipt["intent_id"]) is None
            or receipt["state"] != "fenced" or receipt["uncertain_record"] not in _UNCERTAIN):
        raise ApiDependencyUnavailable("credential fence receipt is invalid")
    return {"intent_id": receipt["intent_id"], "state": "fenced",
            "uncertain_record": receipt["uncertain_record"],
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


def _exact_json(request: Request, body: bytes, fields: set) -> dict:
    """An exact small JSON object body with exactly ``fields`` (no query, one JSON type)."""
    types = [value for name, value in request.scope.get("headers", ())
             if bytes(name).lower() == b"content-type"]
    if (len(types) != 1 or bytes(types[0]).split(b";", 1)[0].strip().lower() != b"application/json"
            or request.query_params or not 1 <= len(body) <= _MAX_DELETE_BODY):
        raise ValueError("body framing")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate field")
            value[key] = item
        return value

    value = json.loads(body.decode("utf-8"), object_pairs_hook=unique)
    if type(value) is not dict or set(value) != fields:
        raise ValueError("body shape")
    return value


def _model_choice_body(request: Request, body: bytes) -> tuple[int, str]:
    value = _exact_json(request, body, {"binding_revision", "model"})
    revision, model = value["binding_revision"], value["model"]
    if (type(revision) is not int or not 1 <= revision <= 2**31
            or type(model) is not str or _MODEL.fullmatch(model) is None):
        raise ValueError("model choice")
    return revision, model


def _delete_intent(request: Request, body: bytes) -> str:
    """The exact `{"intent_id": uuid}` body of an owner act (delete, fence, refresh)."""
    value = _exact_json(request, body, {"intent_id"})
    intent = value["intent_id"]
    if type(intent) is not str or _UUID.fullmatch(intent) is None:
        raise ValueError("delete intent id")
    return intent


class CredentialSeams:
    """The three bound route seams, fixed at composition (the supported factory).

    ``None`` in a seam keeps that route honestly unavailable."""

    __slots__ = ("credential_act_fence", "credential_catalog_refresh", "credential_gateway_retire",
                 "credential_gateway_submit", "credential_model_choice", "credential_status_snapshot")

    def __init__(self, *, submit=None, retire=None, snapshot=None, fence=None, refresh=None,
                 choose=None):
        for value in (submit, retire, snapshot, fence, refresh, choose):
            if value is not None and not callable(value):
                raise TypeError("a credential seam must be callable")
        self.credential_gateway_submit = submit
        self.credential_gateway_retire = retire
        self.credential_status_snapshot = snapshot
        self.credential_act_fence = fence
        self.credential_catalog_refresh = refresh
        self.credential_model_choice = choose


def credential_seams(client, ledger, *, catalog_lister=None) -> CredentialSeams:
    """Bind a frame-only gateway client, the control-plane ledger and (optionally) the
    gateway catalog lister to the seams."""
    from .credential_commands import CredentialActs

    acts = CredentialActs(client, ledger, catalog_lister=catalog_lister)
    return CredentialSeams(
        submit=acts.store,
        retire=lambda intent_id, handle: acts.delete(intent_id=intent_id, handle=handle),
        snapshot=ledger.snapshot,
        fence=lambda intent_id: acts.fence(intent_id=intent_id),
        refresh=lambda intent_id, provider: acts.refresh_catalog(intent_id=intent_id,
                                                                 provider=provider),
        choose=lambda provider, revision, model: acts.choose_model(
            provider=provider, binding_revision=revision, model=model),
    )


def install_credential_ingress(app, *, seams=None) -> None:
    """Attach the authenticated create/rotate, delete and status routes to an app or
    router. Without ``seams`` each request reads the seams from ``app.state`` (the
    development host); with a :class:`CredentialSeams` they are fixed."""
    if seams is not None and type(seams) is not CredentialSeams:
        raise TypeError("credential seams must be exact")

    def bound(request):
        return request.app.state if seams is None else seams

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
                bound(request), "credential_gateway_submit", None
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
                bound(request), "credential_gateway_retire", None
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

    @app.api_route("/api/v1/credentials/fences", methods=["POST"])
    async def credential_fence_v1(request: Request):
        # The owner's explicit resolution of a create/rotate act whose gateway command
        # stayed `unknown`: after the fence delay and a fresh `unknown` query the act
        # becomes terminal `fenced`. No secret is re-sent, nothing is bound, and a late
        # commit of that command is retired as `unbound_orphan`.
        try:
            _authenticated(request, read=False)
            body = await request.body()
            try:
                intent_id = _delete_intent(request, bytes(body))
            except (ValueError, UnicodeDecodeError, RecursionError):
                return api_error(status=400, code="invalid_input",
                                 message="차단할 요청 형식을 확인해 주세요.",
                                 retryability=NOT_RETRYABLE)
            fence = getattr(bound(request), "credential_act_fence", None)
            if fence is None:
                raise ApiDependencyUnavailable("credential gateway is not attached")
            try:
                receipt = await run_in_threadpool(fence, intent_id)
            except CredentialCommandError as exc:
                return _act_failure(exc)
            return JSONResponse(status_code=200, content=_redacted_fence(receipt))
        except Exception as exc:  # noqa: BLE001 - sanitize the public boundary
            return _failure(exc)

    @app.api_route("/api/v1/credentials/connections/{provider}/catalog-refresh", methods=["POST"])
    async def credential_catalog_refresh_v1(provider: str, request: Request):
        # The owner's one explicit provider read: the model list for the connection's
        # CURRENT binding revision, through the gateway's provider-send path (the gateway
        # resolves the key; it never reaches this process). The result is recorded by CAS
        # on the revision read before the request; a rotation in between refuses it.
        try:
            _authenticated(request, read=False)
            body = await request.body()
            try:
                if provider not in _PROVIDERS:
                    raise ValueError("provider")
                intent_id = _delete_intent(request, bytes(body))
            except (ValueError, UnicodeDecodeError, RecursionError):
                return api_error(status=400, code="invalid_input",
                                 message="모델 목록 새로 고침 요청 형식을 확인해 주세요.",
                                 retryability=NOT_RETRYABLE)
            refresh = getattr(bound(request), "credential_catalog_refresh", None)
            if refresh is None:
                raise ApiDependencyUnavailable("credential catalog refresh is not attached")
            try:
                receipt = await run_in_threadpool(refresh, intent_id, provider)
            except CredentialCommandError as exc:
                return _act_failure(exc)
            return JSONResponse(status_code=200, content=_redacted_catalog(receipt))
        except Exception as exc:  # noqa: BLE001 - sanitize the public boundary
            return _failure(exc)

    @app.api_route("/api/v1/credentials/connections/{provider}/model-choice", methods=["POST"])
    async def credential_model_choice_v1(provider: str, request: Request):
        # The owner's model choice, validated against the catalog of the named binding
        # revision, which must be the current one. No provider call.
        try:
            _authenticated(request, read=False)
            body = await request.body()
            try:
                if provider not in _PROVIDERS:
                    raise ValueError("provider")
                revision, model = _model_choice_body(request, bytes(body))
            except (ValueError, UnicodeDecodeError, RecursionError):
                return api_error(status=400, code="invalid_input",
                                 message="모델 선택 요청 형식을 확인해 주세요.",
                                 retryability=NOT_RETRYABLE)
            choose = getattr(bound(request), "credential_model_choice", None)
            if choose is None:
                raise ApiDependencyUnavailable("credential model choice is not attached")
            try:
                receipt = await run_in_threadpool(choose, provider, revision, model)
            except CredentialCommandError as exc:
                return _act_failure(exc)
            return JSONResponse(status_code=200, content=_redacted_choice(receipt))
        except Exception as exc:  # noqa: BLE001 - sanitize the public boundary
            return _failure(exc)

    @app.api_route("/api/v1/credentials", methods=["GET"])
    async def credential_status_v1(request: Request):
        try:
            # A status read is a snapshot of already-committed redacted ledger state;
            # it makes zero vault, gateway, provider or network effect.
            _authenticated(request, read=True)
            snapshot = getattr(
                bound(request), "credential_status_snapshot", None
            )
            if snapshot is None:
                raise ApiDependencyUnavailable(
                    "credential status snapshot is not attached"
                )
            return JSONResponse(
                status_code=200,
                content=_redacted_status(snapshot()),
            )
        except Exception as exc:  # noqa: BLE001 - sanitize the public boundary
            return _failure(exc)


__all__ = ["CredentialSeams", "attach_credential_gateway", "credential_seams",
           "install_credential_ingress"]


def attach_credential_gateway(app, client, ledger, *, catalog_lister=None) -> None:
    """Bind a frame-only gateway client and the control-plane command ledger to the
    route state seams.

    The client comes from :mod:`app.workers.credential_channel`, which imports no
    vault code. The status snapshot reads the ledger only — never the gateway.
    """
    seams = credential_seams(client, ledger, catalog_lister=catalog_lister)
    app.state.credential_gateway_submit = seams.credential_gateway_submit
    app.state.credential_gateway_retire = seams.credential_gateway_retire
    app.state.credential_status_snapshot = seams.credential_status_snapshot
    app.state.credential_act_fence = seams.credential_act_fence
    app.state.credential_catalog_refresh = seams.credential_catalog_refresh
    app.state.credential_model_choice = seams.credential_model_choice
