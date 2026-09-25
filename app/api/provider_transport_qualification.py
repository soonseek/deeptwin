"""The owner's provider-transport qualification path (T087 -> T090).

The credential gateway refuses every send (`transport_unqualified`) until it has adopted a
`provider-transport-qualification-v1` document naming the digest of the manifest its
transport was built from. These two routes, contributed by `provider-conformance-v1`
beside the conformance service they depend on, are the owner's way to produce one:

- ``GET /api/v1/extensions/provider-transport-qualification``
  (``extensions.provider-transport-qualification.read``, ``extension.read``): the shipped
  manifest's digest, what a qualification requires (a matched 4/4 verified-installation
  conformance run whose admission is current, and the offline transport conformance), the
  prerequisite state with the run that meets it, the newest sealed qualification and the
  gateway's adopted revision (one nonsecret ``transports`` read of the gateway; no custody,
  no provider request, no mock run). ``state`` is ``qualified`` only when the gateway
  adopted a document naming this digest; otherwise ``reason`` says why.
- ``POST`` the same path (``extensions.provider-transport-qualification.execute``,
  ``extension.manage``, CSRF) with exactly ``{"command_id", "manifest_sha256",
  "conformance_command_id"}``: runs :class:`PersistentTransportQualification` (it re-checks
  the named run, runs its own offline conformance of the manifest against a loopback mock
  provider it starts itself, seals the record) and publishes the document with the
  gateway client's ``bind_transport``. ``conformance_command_id`` is ``null`` when the owner
  has no run to name; the act then refuses naming the missing prerequisite. The command id
  is replay-safe (same id and body: the same qualification, republished; same id with
  another body: ``409 command_conflict``).

Every refusal answers the fixed error schema whose ``code`` is the named reason and whose
``message`` is the exact text the owner screen shows (`REFUSALS`).
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..extensions.provider_transport_qualification import (
    COMMAND_SCHEMA,
    PREREQUISITES,
    STATE_SCHEMA,
    PersistentTransportQualification,
    TransportQualificationError,
)
from .routes import NOT_RETRYABLE, RETRYABLE, _authenticated, api_error
from .wire import WireInputError, parse_query

PATH = "/api/v1/extensions/provider-transport-qualification"
MAX_BODY_BYTES = 1024
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_BODY_FIELDS = frozenset({"command_id", "manifest_sha256", "conformance_command_id"})

# code -> (status, exact owner-facing text, retryability); the owner screen shows the same text
REFUSALS = {
    "verified_installation_missing": (409, (
        "검증된 제공자 설치(verified installation)가 없어 전송 매니페스트를 검증하지 않았습니다. "
        "먼저 제공자 설치를 검증하고, 그 설치로 제공자 적합성 검사를 실행해 주세요."), NOT_RETRYABLE),
    "conformance_run_missing": (409, (
        "검증된 설치에 대한 제공자 적합성 검사(conformance) 실행이 없어 전송 매니페스트를 검증하지 "
        "않았습니다. 먼저 적합성 검사를 실행해 주세요."), NOT_RETRYABLE),
    "conformance_run_unmatched": (409, (
        "검증된 설치에서 4개 벡터를 모두 통과한(matched 4/4) 제공자 적합성 검사가 없어 전송 "
        "매니페스트를 검증하지 않았습니다."), NOT_RETRYABLE),
    "conformance_admission_stale": (409, (
        "적합성 검사 뒤 설치 헤드나 릴리스 소스가 바뀌어 그 검사로는 검증하지 않았습니다. "
        "현재 설치로 적합성 검사를 다시 실행해 주세요."), NOT_RETRYABLE),
    "manifest_changed": (409, (
        "검토한 전송 매니페스트가 지금 배포된 매니페스트와 다릅니다. 상태를 다시 읽고 다시 "
        "검증해 주세요."), NOT_RETRYABLE),
    "transport_conformance_failed": (409, (
        "전송 매니페스트가 오프라인 전송 적합성 검사(로컬 모의 제공자)를 통과하지 못해 검증하지 "
        "않았습니다."), NOT_RETRYABLE),
    "command_conflict": (409, (
        "이 요청 ID는 이미 다른 내용으로 쓰였습니다. 새 요청으로 다시 시도해 주세요."), NOT_RETRYABLE),
    "invalid_input": (400, "전송 매니페스트 검증 요청 형식을 확인해 주세요.", NOT_RETRYABLE),
    "unauthenticated": (401, "세션이 끝났습니다. 시작 화면(./)에서 다시 로그인해 주세요.",
                        NOT_RETRYABLE),
    "access_denied": (403, "이 요청은 허용되지 않았습니다.", NOT_RETRYABLE),
    "unavailable": (503, "전송 매니페스트 검증을 처리하지 못했습니다.", RETRYABLE),
}
_GATEWAY_STATES = frozenset({"adopted", "adopted_other_manifest", "not_adopted", "unavailable"})
_REASONS = frozenset({None, "gateway_unavailable", "manifest_changed", "not_published",
                      "not_qualified"})


def is_transport_qualification_path(path: str) -> bool:
    return path == PATH or path.startswith(PATH + "/")


def preflight(scope, body):
    """Cheap wire admission before auth: the exact path, no query, a GET without a body
    or a bounded POST body (its exact shape is checked by the route)."""
    parse_query(scope.get("query_string", b""), allowed=())
    method = scope["method"]
    if (scope["path"] != PATH or method not in {"GET", "POST"}
            or (method == "GET" and body) or (method == "POST" and not 1 <= len(body) <= MAX_BODY_BYTES)):
        raise WireInputError("invalid_input")


def refusal(code):
    status, message, retryability = REFUSALS.get(code, REFUSALS["unavailable"])
    return api_error(status=status, code=code if code in REFUSALS else "unavailable",
                     message=message, retryability=retryability)


def _error_response(error: TransportQualificationError):
    if error.reason is not None:
        return refusal(error.reason)
    if error.code == "not_found":
        return refusal("conformance_run_missing")
    if error.code == "conflict":
        return refusal("conformance_run_unmatched")
    return refusal(error.code)


def _ref(value):
    return (type(value) is dict and set(value) == {"kind", "id", "version", "sha256"}
            and type(value["kind"]) is str and type(value["id"]) is str
            and type(value["version"]) is int and type(value["sha256"]) is str
            and _HEX64.fullmatch(value["sha256"]) is not None)


def _projected_state(value):
    """The closed GET body (anything else is unavailable, never forwarded)."""
    eligible, latest, gateway = value["eligible_conformance"], value["qualification"], value["gateway"]
    if (value["schema_version"] != STATE_SCHEMA or _HEX64.fullmatch(value["manifest_sha256"]) is None
            or value["prerequisite"] not in PREREQUISITES
            or (eligible is None) != (value["prerequisite"] != "met")
            or not (eligible is None or (_UUID.fullmatch(eligible["command_id"])
                                         and _ref(eligible["verified_installation_ref"])
                                         and _ref(eligible["result_ref"])))
            or not (latest is None or (type(latest["revision"]) is int
                                       and _ref(latest["qualification_ref"])
                                       and _UUID.fullmatch(latest["conformance_command_id"])))
            or gateway["state"] not in _GATEWAY_STATES
            or value["reason"] not in _REASONS
            or value["state"] != ("qualified" if value["reason"] is None else "unqualified")):
        raise TransportQualificationError("unavailable")
    return value


def _body(request: Request, raw: bytes) -> dict:
    types = [value for name, value in request.scope.get("headers", ())
             if bytes(name).lower() == b"content-type"]
    if (len(types) != 1 or bytes(types[0]).split(b";", 1)[0].strip().lower() != b"application/json"
            or request.query_params or not 1 <= len(raw) <= MAX_BODY_BYTES):
        raise ValueError("body framing")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate field")
            value[key] = item
        return value

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    if (type(value) is not dict or set(value) != _BODY_FIELDS
            or type(value["command_id"]) is not str or _UUID.fullmatch(value["command_id"]) is None
            or type(value["manifest_sha256"]) is not str
            or _HEX64.fullmatch(value["manifest_sha256"]) is None
            or not (value["conformance_command_id"] is None
                    or (type(value["conformance_command_id"]) is str
                        and _UUID.fullmatch(value["conformance_command_id"]) is not None))):
        raise ValueError("body shape")
    return {"schema_version": COMMAND_SCHEMA, **value}


def create_router(*, service):
    if type(service) is not PersistentTransportQualification:
        raise TypeError("Invalid provider transport qualification route dependencies")
    router = APIRouter()

    @router.get(PATH, name="extensions.provider-transport-qualification.read")
    async def read(request: Request):
        try:
            authenticated = _authenticated(request, read=True)
        except Exception:  # noqa: BLE001 - the boundary authenticated or this is refused
            return refusal("unauthenticated")
        try:
            value = await run_in_threadpool(service.state, authenticated)
            return JSONResponse(_projected_state(value), status_code=200)
        except TransportQualificationError as error:
            return _error_response(error)
        except Exception:  # noqa: BLE001 - sanitize the public boundary
            return refusal("unavailable")

    @router.post(PATH, name="extensions.provider-transport-qualification.execute")
    async def execute(request: Request):
        try:
            authenticated = _authenticated(request, read=False)
        except Exception:  # noqa: BLE001 - the boundary authenticated (with CSRF) or refused
            return refusal("access_denied")
        try:
            payload = _body(request, bytes(await request.body()))
        except (ValueError, UnicodeDecodeError, RecursionError):
            return refusal("invalid_input")
        try:
            result = await run_in_threadpool(service.qualify, authenticated, payload)
            document = result["qualification"]
            return JSONResponse({
                "command_id": payload["command_id"], "published": result["published"] is True,
                "qualification": {
                    "revision": document["revision"],
                    "manifest_sha256": document["manifest_sha256"],
                    "qualification_ref": document["qualification_ref"],
                    "conformance_command_id": document["installation_conformance"]["command_id"]}},
                status_code=200)
        except TransportQualificationError as error:
            return _error_response(error)
        except Exception:  # noqa: BLE001 - sanitize the public boundary
            return refusal("unavailable")

    return router


__all__ = ["MAX_BODY_BYTES", "PATH", "REFUSALS", "create_router",
           "is_transport_qualification_path", "preflight", "refusal"]
