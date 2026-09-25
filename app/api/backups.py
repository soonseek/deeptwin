"""Fixed HTTP adapter for the owner's backup and staged restore: the `backups-v1`
contribution (T073; app/services/backups.py).

- `GET /api/v1/backups`: what is true now — worker attached/ready/key lost, the backups
  made (external receipts) and the staged restores.
- `POST …/preview`: the ACTUAL included content of a backup made now, with its digest.
- `POST /api/v1/backups`: create, only with `confirmed: true` and that digest.
- `GET …/{backup_id}/ciphertext|receipt`: the encrypted bundle and its external receipt.
- `POST …/restores`: begin a staged restore from an external receipt.
- `POST …/restores/{restore_id}/bundle`: the encrypted bundle as `application/octet-stream`.
- `GET …/restores/{restore_id}`: the staged `restored_review` state.

The shared `/api/v1` preflight admits every body exactly before auth (`preflight`).
When no backup worker is attached the routes still answer: the state says
`not_configured` and create/restore answer an honest 503 `backup_worker_unavailable`.
"""

from __future__ import annotations

import json
import re
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ..services.backups import MAX_BUNDLE_BYTES, BackupService, BackupServiceError
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/backups"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404,
          "conflict": 409, "too_large": 413, "unavailable": 503, "backup_worker_unavailable": 503,
          "backup_key_unavailable": 503, "backup_failed": 503, "restore_failed": 422}
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_BUNDLE = re.compile(rf"/api/v1/backups/({_UUID})/(ciphertext|receipt)\Z")
_RESTORE = re.compile(rf"/api/v1/backups/restores/({_UUID})\Z")
_UPLOAD = re.compile(rf"/api/v1/backups/restores/({_UUID})/bundle\Z")
BODIES = {
    "preview": (("schema_version", "request_id"), {"schema_version": str, "request_id": str},
                WireLimits(max_bytes=256, max_depth=2, max_items=4, max_members=4, max_string_bytes=64)),
    "create": (("schema_version", "request_id", "preview_sha", "confirmed"),
               {"schema_version": str, "request_id": str, "preview_sha": str, "confirmed": bool},
               WireLimits(max_bytes=512, max_depth=2, max_items=4, max_members=6, max_string_bytes=128)),
    "restore": (("schema_version", "request_id", "receipt"),
                {"schema_version": str, "request_id": str, "receipt": dict},
                WireLimits(max_bytes=4096, max_depth=6, max_items=32, max_members=16, max_string_bytes=128)),
}
SCHEMAS = {"preview": "backup-preview-request-v1", "create": "backup-create-v1",
           "restore": "backup-restore-v1"}

__all__ = ["MAX_UPLOAD_BYTES", "backup_services", "create_router", "is_backup_path", "is_bundle_upload",
           "preflight"]
MAX_UPLOAD_BYTES = MAX_BUNDLE_BYTES


def is_backup_path(path: str) -> bool:
    return path == PATH or path.startswith(PATH + "/")


def is_bundle_upload(path: str, method: str) -> bool:
    return method == "POST" and _UPLOAD.fullmatch(path) is not None


def _body(raw: bytes, name: str) -> dict:
    required, types, limits = BODIES[name]
    value = parse_json_object(raw, required=required, field_types=types, limits=limits)
    if value["schema_version"] != SCHEMAS[name]:
        raise WireInputError("invalid_input")
    return value


def _content_type(scope) -> str:
    for name, value in scope.get("headers", ()):
        if name.lower() == b"content-type":
            return value.decode("latin-1").split(";", 1)[0].strip().lower()
    return ""


def preflight(scope, body):
    path, method = scope["path"], scope["method"]
    parse_query(scope.get("query_string", b""), allowed=())
    reading = method in {"GET", "HEAD"}
    if path == PATH:
        if reading:
            if body:
                raise WireInputError("invalid_input")
            return
        if method != "POST":
            raise WireInputError("invalid_input")
        _body(body, "create")
        return
    if path == PATH + "/preview" and method == "POST":
        _body(body, "preview")
        return
    if path == PATH + "/restores" and method == "POST":
        _body(body, "restore")
        return
    if (_BUNDLE.fullmatch(path) or _RESTORE.fullmatch(path)) and reading:
        if body:
            raise WireInputError("invalid_input")
        return
    if is_bundle_upload(path, method):
        if _content_type(scope) != "application/octet-stream" or not 1 <= len(body) <= MAX_UPLOAD_BYTES:
            raise WireInputError("invalid_input")
        return
    raise WireInputError("invalid_input")


def backup_error(error):
    code = error.code if isinstance(error, BackupServiceError) else "invalid_input"
    value = {"code": code, "message": "backup request could not be admitted",
             "retryability": "retryable" if code in {"conflict", "backup_worker_unavailable"} else "not_retryable",
             "affected_refs": [], "correlation_id": str(uuid4())}
    if code.startswith("backup_") or code == "restore_failed":
        value["reason"] = code  # the closed backup code the screen states (session.mjs keeps `reason`)
    if isinstance(error, BackupServiceError) and error.detail is not None:
        value["detail"] = error.detail  # a closed, secret-free failure sentence
    return JSONResponse(value, status_code=STATUS.get(code, 503), headers={"Cache-Control": "no-store"})


def backup_services(context):
    from .first_party import ContributionServices

    service = BackupService(context.domain_store, context.owner_authority, client=context.backup_worker)
    return ContributionServices(create_router(service=service), {"backups.service": service})


def create_router(*, service):
    router = APIRouter()
    headers = {"Cache-Control": "no-store"}

    async def call(method, *args):
        try:
            return JSONResponse(await run_in_threadpool(method, *args), headers=headers)
        except BackupServiceError as error:
            return backup_error(error)

    @router.api_route(PATH, methods=["GET", "HEAD"])
    async def read(request: Request):
        return await call(service.state, request.state.authenticated_request)

    @router.post(PATH + "/preview")
    async def preview(request: Request):
        try:
            value = _body(await request.body(), "preview")
        except (WireInputError, ValueError, json.JSONDecodeError):
            return backup_error(BackupServiceError("invalid_input"))
        return await call(service.preview, request.state.authenticated_request, value["request_id"])

    @router.post(PATH)
    async def create(request: Request):
        try:
            value = _body(await request.body(), "create")
        except (WireInputError, ValueError, json.JSONDecodeError):
            return backup_error(BackupServiceError("invalid_input"))
        return await call(service.create, request.state.authenticated_request, value["request_id"],
                          value["preview_sha"], value["confirmed"])

    def download(member):
        async def handler(request: Request, backup_id: str):
            try:
                data = await run_in_threadpool(service.bundle, request.state.authenticated_request,
                                               backup_id, member)
            except BackupServiceError as error:
                return backup_error(error)
            name = f"deeptwin-backup-{backup_id}" + (".age" if member == "ciphertext" else ".receipt.json")
            return Response(data, media_type="application/octet-stream" if member == "ciphertext"
                            else "application/json", headers={
                "Content-Disposition": f'attachment; filename="{name}"', "Content-Length": str(len(data)),
                "Cache-Control": "no-store"})
        return handler

    router.add_api_route(PATH + "/{backup_id}/ciphertext", download("ciphertext"), methods=["GET", "HEAD"])
    router.add_api_route(PATH + "/{backup_id}/receipt", download("receipt"), methods=["GET", "HEAD"])

    @router.post(PATH + "/restores")
    async def restore_begin(request: Request):
        try:
            value = _body(await request.body(), "restore")
        except (WireInputError, ValueError, json.JSONDecodeError):
            return backup_error(BackupServiceError("invalid_input"))
        return await call(service.restore_begin, request.state.authenticated_request, value["request_id"],
                          value["receipt"])

    @router.api_route(PATH + "/restores/{restore_id}", methods=["GET", "HEAD"])
    async def restore_read(request: Request, restore_id: str):
        return await call(service.restore_state, request.state.authenticated_request, restore_id)

    @router.post(PATH + "/restores/{restore_id}/bundle")
    async def restore_upload(request: Request, restore_id: str):
        return await call(service.restore_upload, request.state.authenticated_request, restore_id,
                          await request.body())

    return router
