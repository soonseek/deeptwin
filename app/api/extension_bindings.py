"""Owner routes for extension bindings, rollback retention and the installation inventory (T087).

`extension-bindings-v1` contributes, over :class:`PersistentExtensionBindings`
(`app/extensions/binding_service.py`):

- ``GET /api/v1/extensions/installations?limit=&after=`` (``extensions.installations.list``): bounded
  page of every staged/verified installation with its trust tier (from the port contract), service
  tuple, staging request/receipt refs and the slots whose current head names it.
- ``GET /api/v1/extensions/bindings?limit=&after=`` (``extensions.bindings.list``): bounded page of
  binding slots with the exact five-field `BindingSlotKeyV1`, digest and head.
- ``GET /api/v1/extensions/bindings/{slot_key_digest}`` (``extensions.bindings.read``): one slot's
  key, logical slot and capability selector, head, immutable history, rollback-retention heads (each
  with the server's release warning), coexisting slots of the same port/scope/purpose, same-slot
  holders and affected environments.
- ``POST /api/v1/extensions/binding-slot-keys`` (``extensions.bindings.slot_key``): the exact key and
  digest the server computes for a logical slot (port, slot id, target scope, selector) and the
  slot's current head. It writes nothing.
- ``POST /api/v1/extensions/bindings`` (``extensions.bindings.bind``),
  ``POST …/bindings/{slot_key_digest}/disable`` (``extensions.bindings.disable``),
  ``POST …/bindings/{slot_key_digest}/rollback`` (``extensions.bindings.rollback``) and
  ``POST …/bindings/{slot_key_digest}/rollback-retentions/{target_binding_record_digest}/release``
  (``extensions.bindings.retention_release``): owner acts with the exact expected head.

The contract's `/extensions/{id}/bindings…` paths are served here without the extension-id
segment, because `/api/v1/extensions/{id}` would collide with the fixed `candidates`,
`provider-installation`, `provider-conformance` and `provider-transport-qualification` segments;
the extension id is carried in each command body instead. Every refusal answers the fixed error
schema whose ``message`` is the exact text the owner screen shows (`REFUSALS`).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..extensions.binding_service import (
    BindingError,
    PersistentExtensionBindings,
    parse_json_body,
)
from .first_party import ContributionServices
from .routes import NOT_RETRYABLE, RETRYABLE, _authenticated, api_error
from .wire import WireInputError, parse_query

INSTALLATIONS = "/api/v1/extensions/installations"
BINDINGS = "/api/v1/extensions/bindings"
SLOT_KEYS = "/api/v1/extensions/binding-slot-keys"
MAX_BODY_BYTES = 16384
_HEX = r"[0-9a-f]{64}"
_SLOT = re.compile(rf"{BINDINGS}/({_HEX})\Z")
_ACT = re.compile(rf"{BINDINGS}/({_HEX})/(disable|rollback)\Z")
_RELEASE = re.compile(rf"{BINDINGS}/({_HEX})/rollback-retentions/({_HEX})/release\Z")
_STALE = "화면이 읽은 뒤 서버 상태가 바뀌어 아무것도 바꾸지 않았습니다. 다시 읽은 뒤 확인해 주세요."

REFUSALS = {
    "invalid_input": (400, "바인딩 요청 형식을 확인해 주세요.", NOT_RETRYABLE),
    "unauthenticated": (401, "세션이 끝났습니다. 시작 화면(./)에서 다시 로그인해 주세요.", NOT_RETRYABLE),
    "access_denied": (403, "이 요청은 허용되지 않았습니다.", NOT_RETRYABLE),
    "not_found": (404, "그 바인딩 slot 기록이 없습니다.", NOT_RETRYABLE),
    "binding_head_stale": (409, "이 slot의 현재 바인딩 헤드가 보낸 기대 헤드와 다릅니다(다른 후보가 먼저 바꿨을 수 있음). " + _STALE,
                           NOT_RETRYABLE),
    "binding_unchanged": (409, "이 slot은 이미 같은 설치와 같은 검증 기록으로 활성 상태입니다. 바꾼 것은 없습니다.",
                          NOT_RETRYABLE),
    "retention_head_stale": (409, "롤백 보존 헤드가 보낸 기대 헤드와 다릅니다. " + _STALE, NOT_RETRYABLE),
    "rollback_target_invalid": (409, "대상은 이 slot의 현재 헤드보다 앞선, 활성이었던 바인딩 수정본이어야 합니다. 바꾼 것은 없습니다.",
                                NOT_RETRYABLE),
    "retention_not_retained": (409, "이 대상의 롤백 보존이 '보존중'이 아닙니다(이미 해제·사용됨 또는 없음). 롤백·해제할 수 없습니다.",
                               NOT_RETRYABLE),
    "target_mismatch": (409, "보낸 대상 설치·서비스 묶음이 보존 기록과 다릅니다. 바꾼 것은 없습니다.", NOT_RETRYABLE),
    "qualification_missing": (409, "이 포트와 설치에 대한 봉인된 검증(qualification) 기록이 없습니다. 이 서버에서 검증 기록이 있는 포트는 제공자 포트(전송 매니페스트 검증)뿐입니다.",
                              NOT_RETRYABLE),
    "qualification_not_current": (409, "검증 기록이 더 이상 현재가 아닙니다(설치 헤드·릴리스 소스·전송 매니페스트가 바뀜). 다시 검증한 뒤 시도해 주세요.",
                                  NOT_RETRYABLE),
    "extension_mismatch": (409, "보낸 확장 ID가 검증된 설치나 대상 바인딩의 확장과 다릅니다.", NOT_RETRYABLE),
    "selector_mismatch": (409, "capability selector의 provider_id가 검증 기록의 제공자와 다릅니다.", NOT_RETRYABLE),
    "selector_unsupported": (409, "이 포트의 capability selector 형식은 계약에 아직 확정되지 않아 이 서버가 받지 않습니다.",
                             NOT_RETRYABLE),
    "command_conflict": (409, "이 요청 ID는 이미 다른 내용으로 쓰였습니다. 새 요청으로 다시 시도해 주세요.", NOT_RETRYABLE),
    "capacity": (429, "바인딩 기록의 저장 한도에 닿았습니다.", NOT_RETRYABLE),
    "unavailable": (503, "바인딩 요청을 처리하지 못했습니다. 같은 요청 ID로만 다시 보냅니다.", RETRYABLE),
}


def is_bindings_path(path: str) -> bool:
    return (path in {INSTALLATIONS, BINDINGS, SLOT_KEYS}
            or path.startswith((BINDINGS + "/", INSTALLATIONS + "/", SLOT_KEYS + "/")))


def preflight(scope, body):
    """Wire admission before auth: exact paths and methods, `limit`/`after` only on the two lists,
    a GET without a body, a bounded POST body (its exact shape is checked by the service)."""
    path, method = scope["path"], scope["method"]
    raw = scope.get("query_string", b"")
    if method == "GET" and path in {INSTALLATIONS, BINDINGS}:
        parse_query(raw, allowed=("limit", "after"), max_bytes=256)
        if body:
            raise WireInputError("invalid_input")
        return
    parse_query(raw, allowed=())
    if method == "GET" and _SLOT.fullmatch(path) and not body:
        return
    if (method == "POST" and (path in {BINDINGS, SLOT_KEYS} or _ACT.fullmatch(path) or _RELEASE.fullmatch(path))
            and 1 <= len(body) <= MAX_BODY_BYTES):
        return
    raise WireInputError("invalid_input")


def refusal(code):
    status, message, retryability = REFUSALS.get(code, REFUSALS["unavailable"])
    return api_error(status=status, code=code if code in REFUSALS else "unavailable",
                     message=message, retryability=retryability)


def binding_services(context, *, dependencies):
    if set(dependencies) != {"provider-transport-qualification.service"}:
        raise TypeError("Invalid extension binding dependencies")
    service = PersistentExtensionBindings(
        dependencies["provider-transport-qualification.service"],
        instance_id=context.owner_authority.profile.instance_id)
    return ContributionServices(create_router(service=service, base_path=context.base_path),
                                {"extension-bindings.service": service})


def reconcile_binding_startup(own_exports):
    """Startup: the binding heads reconciled against their retention, command and event records."""
    own_exports["extension-bindings.service"].reconcile_startup()


def _links(value, base_path):
    prefix = base_path.rstrip("/")

    def walk(item):
        if isinstance(item, dict):
            return {key: (prefix + link if key in {"self", "request_link"} and isinstance(link, str)
                          else walk(link)) for key, link in item.items()}
        if isinstance(item, list):
            return [walk(entry) for entry in item]
        return item
    return walk(value)


def _json_body(request: Request, raw: bytes):
    types = [value for name, value in request.scope.get("headers", ())
             if bytes(name).lower() == b"content-type"]
    if (len(types) != 1 or bytes(types[0]).split(b";", 1)[0].strip().lower() != b"application/json"
            or request.query_params):
        raise BindingError("invalid_input")
    return parse_json_body(raw, maximum=MAX_BODY_BYTES)


def create_router(*, service, base_path):
    if type(service) is not PersistentExtensionBindings or type(base_path) is not str:
        raise TypeError("Invalid extension binding route dependencies")
    router = APIRouter()

    async def answer(request, read, work):
        try:
            authenticated = _authenticated(request, read=read)
        except Exception:  # noqa: BLE001 - the boundary authenticated (with CSRF for acts) or refused
            return refusal("unauthenticated" if read else "access_denied")
        try:
            payload = None if read else _json_body(request, bytes(await request.body()))
            value = await run_in_threadpool(work, authenticated, payload)
            return JSONResponse(_links(value, base_path), status_code=200)
        except BindingError as error:
            return refusal(error.code)
        except Exception:  # noqa: BLE001 - sanitize the public boundary
            return refusal("unavailable")

    def page(request):
        query = request.query_params
        return {"limit": query.get("limit"), "after": query.get("after")}

    @router.get(INSTALLATIONS, name="extensions.installations.list")
    async def installations(request: Request):
        options = page(request)
        return await answer(request, True, lambda auth, _body: service.installations(auth, **options))

    @router.get(BINDINGS, name="extensions.bindings.list")
    async def bindings(request: Request):
        options = page(request)
        return await answer(request, True, lambda auth, _body: service.bindings(auth, **options))

    @router.get(BINDINGS + "/{slot_key_digest}", name="extensions.bindings.read")
    async def slot(request: Request, slot_key_digest: str):
        return await answer(request, True, lambda auth, _body: service.slot(auth, slot_key_digest))

    @router.post(SLOT_KEYS, name="extensions.bindings.slot_key")
    async def slot_key(request: Request):
        return await answer(request, False, service.compose_slot_key)

    @router.post(BINDINGS, name="extensions.bindings.bind")
    async def bind(request: Request):
        return await answer(request, False, service.bind)

    @router.post(BINDINGS + "/{slot_key_digest}/disable", name="extensions.bindings.disable")
    async def disable(request: Request, slot_key_digest: str):
        return await answer(request, False, lambda auth, body: service.disable(auth, slot_key_digest, body))

    @router.post(BINDINGS + "/{slot_key_digest}/rollback", name="extensions.bindings.rollback")
    async def rollback(request: Request, slot_key_digest: str):
        return await answer(request, False, lambda auth, body: service.rollback(auth, slot_key_digest, body))

    @router.post(BINDINGS + "/{slot_key_digest}/rollback-retentions/{target_binding_record_digest}/release",
                 name="extensions.bindings.retention_release")
    async def release(request: Request, slot_key_digest: str, target_binding_record_digest: str):
        return await answer(request, False, lambda auth, body: service.release(
            auth, slot_key_digest, target_binding_record_digest, body))

    return router


__all__ = ["BINDINGS", "INSTALLATIONS", "MAX_BODY_BYTES", "REFUSALS", "SLOT_KEYS", "binding_services",
           "create_router", "is_bindings_path", "preflight", "reconcile_binding_startup", "refusal"]
