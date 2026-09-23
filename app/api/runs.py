"""Fixed HTTP adapter for owner-started runs (the connected browser path)."""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.run_artifacts import PersistentRunArtifacts, RunArtifactError
from ..services.runs import (
    CANCEL_SCHEMA,
    COMMAND_SCHEMA,
    RECOVER_SCHEMA,
    RESUME_SCHEMA,
    PersistentRuns,
    RunServiceError,
)
from .first_party import ContributionServices
from .run_approvals import is_approval_path
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/runs"
STATUS = {
    "invalid_input": 400,
    "unauthenticated": 401,
    "access_denied": 403,
    "not_found": 404,
    "conflict": 409,
    "too_large": 413,
    "unavailable": 503,
}
# the artifact routes answer one code of their own: a byte range past the original
ARTIFACT_STATUS = {**STATUS, "range_not_satisfiable": 416}
_ARTIFACT_VIEWS = {"content", "preview"}
_REF_FIELDS = ("kind", "id", "version", "sha256")
_CREATE_FIELDS = (
    "command_id", "graph_ref", "work_revision_ref", "environment_ref", "consent_ref",
    "budget_policy_ref",
)


class RunRouteError(ValueError):
    """Closed wire-level codes for the run routes."""

    def __init__(self, code="invalid_input"):
        super().__init__(code)
        self.code = code


def run_error(error):
    code = (error.code if isinstance(error, RunRouteError | RunServiceError | RunArtifactError)
            else "unavailable")
    if code not in STATUS:
        code = "unavailable"
    return JSONResponse(
        {
            "code": code,
            "message": "Run request could not be admitted",
            "retryability": "not_retryable",
            "affected_refs": [],
            "correlation_id": str(uuid4()),
        },
        status_code=STATUS[code],
    )


def artifact_error(error):
    code = (error.code if isinstance(error, RunRouteError | RunServiceError | RunArtifactError)
            else "unavailable")
    if code not in ARTIFACT_STATUS:
        code = "unavailable"
    return JSONResponse(
        {
            "code": code,
            "message": "Artifact request could not be admitted",
            "retryability": "not_retryable",
            "affected_refs": [],
            "correlation_id": str(uuid4()),
        },
        status_code=ARTIFACT_STATUS[code],
    )


def is_run_path(path: str) -> bool:
    """`/api/v1/runs`, `/api/v1/runs/{id}`, `/{id}/resume`, `/{id}/cancel` and
    `/{id}/recover`, and the run's artifacts: `/{id}/artifacts`, `/{id}/artifacts/{aid}`,
    `…/{aid}/content`, `…/{aid}/preview`; the approvals routes under the same prefix
    keep their own adapter."""

    if path == PATH:
        return True
    if not path.startswith(PATH + "/") or is_approval_path(path):
        return False
    parts = path[len(PATH) + 1:].split("/")
    return (len(parts) == 1 or (len(parts) == 2 and parts[1] in {"resume", "cancel", "recover"})
            or _artifact_parts(parts) is not None)


def _artifact_parts(parts):
    """(artifact id or None, view or None) for an artifacts path, else None."""

    if len(parts) < 2 or parts[1] != "artifacts" or len(parts) > 4:
        return None
    if len(parts) == 2:
        return (None, None)
    if len(parts) == 3:
        return (parts[2], None)
    return (parts[2], parts[3]) if parts[3] in _ARTIFACT_VIEWS else None


def _ref_shape(value):
    if type(value) is not dict or tuple(sorted(value)) != tuple(sorted(_REF_FIELDS)):
        raise RunRouteError()
    if (type(value["kind"]) is not str or type(value["id"]) is not str
            or type(value["version"]) is not int or type(value["sha256"]) is not str):
        raise RunRouteError()
    return value


def preflight(scope, body, content_type):
    try:
        path, method = scope["path"], scope["method"]
        parse_query(scope.get("query_string", b""), allowed=())
        if path == PATH:
            if method != "POST" or content_type.split(";", 1)[0] != "application/json":
                raise RunRouteError()
            value = parse_json_object(
                body,
                required=_CREATE_FIELDS,
                field_types={"command_id": str, **{name: dict for name in _CREATE_FIELDS[1:]}},
                limits=WireLimits(
                    max_bytes=4096, max_depth=3, max_items=32, max_members=8,
                    max_string_bytes=256,
                ),  # six members plus five four-field references
            )
            uuid_string(value["command_id"])
            for name in _CREATE_FIELDS[1:]:
                _ref_shape(value[name])
            return {"schema_version": COMMAND_SCHEMA, **value}
        parts = path[len(PATH) + 1:].split("/")
        run_id = uuid_string(parts[0])
        artifact = _artifact_parts(parts)
        if artifact is not None:
            if method not in {"GET", "HEAD"} or body:
                raise RunRouteError()
            if artifact[0] is not None:
                uuid_string(artifact[0])
            return None
        if len(parts) == 2:
            if method != "POST" or content_type.split(";", 1)[0] != "application/json":
                raise RunRouteError()
            value = parse_json_object(
                body, required=("command_id",), field_types={"command_id": str},
                limits=WireLimits(max_bytes=4096, max_depth=2, max_items=4, max_members=2,
                                  max_string_bytes=256),
            )
            uuid_string(value["command_id"])
            schema = {"resume": RESUME_SCHEMA, "cancel": CANCEL_SCHEMA,
                      "recover": RECOVER_SCHEMA}[parts[1]]
            return {"schema_version": schema, "run_id": run_id, **value}
        if method not in {"GET", "HEAD"} or body:
            raise RunRouteError()
        return None
    except RunRouteError:
        raise
    except (WireInputError, ValueError, TypeError):
        raise RunRouteError() from None


def run_services(context, *, dependencies):
    if set(dependencies) != {"run-approvals.service"}:
        raise TypeError("Invalid run dependencies")
    runs = PersistentRuns(
        context.domain_store, context.owner_authority,
        ledger=context.components.runtime_ledger, budget_book=context.components.budget_book,
        approvals=dependencies["run-approvals.service"], executor=context.run_executor,
    )
    artifacts = PersistentRunArtifacts(context.domain_store, context.owner_authority, runs)
    return ContributionServices(
        create_router(runs=runs, artifacts=artifacts, base_path=context.base_path),
        {"runs.service": runs, "run-artifacts.service": artifacts},
    )


def create_router(*, runs, base_path, artifacts=None):
    router = APIRouter()

    @router.api_route(PATH + "/{run_id}/artifacts", methods=["GET", "HEAD"])
    async def artifact_list(request: Request, run_id: str):
        try:
            if artifacts is None:
                raise RunRouteError("unavailable")
            value = await run_in_threadpool(artifacts.list, request.state.authenticated_request,
                                            run_id, base_path=base_path)
            return JSONResponse(value)
        except (RunRouteError, RunServiceError, RunArtifactError) as error:
            return artifact_error(error)

    @router.api_route(PATH + "/{run_id}/artifacts/{artifact_id}", methods=["GET", "HEAD"])
    async def artifact_read(request: Request, run_id: str, artifact_id: str):
        try:
            if artifacts is None:
                raise RunRouteError("unavailable")
            value = await run_in_threadpool(artifacts.read, request.state.authenticated_request,
                                            run_id, artifact_id, base_path=base_path)
            return JSONResponse(value)
        except (RunRouteError, RunServiceError, RunArtifactError) as error:
            return artifact_error(error)

    @router.api_route(PATH + "/{run_id}/artifacts/{artifact_id}/preview", methods=["GET", "HEAD"])
    async def artifact_preview(request: Request, run_id: str, artifact_id: str):
        try:
            if artifacts is None:
                raise RunRouteError("unavailable")
            value = await run_in_threadpool(artifacts.preview, request.state.authenticated_request,
                                            run_id, artifact_id, base_path=base_path)
            return JSONResponse(value)
        except (RunRouteError, RunServiceError, RunArtifactError) as error:
            return artifact_error(error)

    @router.api_route(PATH + "/{run_id}/artifacts/{artifact_id}/content", methods=["GET", "HEAD"])
    async def artifact_content(request: Request, run_id: str, artifact_id: str):
        try:
            if artifacts is None:
                raise RunRouteError("unavailable")
            ranges = request.headers.getlist("range")
            if len(ranges) > 1:
                raise RunRouteError()
            meta, data, served, sniffed = await run_in_threadpool(
                artifacts.content, request.state.authenticated_request, run_id, artifact_id,
                base_path=base_path, range_header=ranges[0] if ranges else None)
            # the original, never transcoded; always an attachment, and typed only
            # when its bytes are a recognised image the viewer shows (nothing the
            # browser could execute is ever served under a renderable type)
            media = sniffed if sniffed.startswith("image/") else "application/octet-stream"
            name = f"{meta['role']}-{meta['ordinal']}"
            headers = {"Content-Disposition": f'attachment; filename="{name}"',
                       "Accept-Ranges": "bytes", "Content-Length": str(len(data)),
                       "Content-Security-Policy": "sandbox; default-src 'none'"}
            if served is None:
                return Response(data, media_type=media, headers=headers)
            headers["Content-Range"] = f"bytes {served[0]}-{served[1]}/{meta['size']}"
            return Response(data, status_code=206, media_type=media, headers=headers)
        except (RunRouteError, RunServiceError, RunArtifactError) as error:
            return artifact_error(error)

    @router.post(PATH)
    async def create(request: Request):
        try:
            value = await run_in_threadpool(
                runs.create, request.state.authenticated_request,
                request.state.run_payload, base_path=base_path,
            )
            return JSONResponse(value, status_code=201)
        except RunServiceError as error:
            return run_error(error)

    @router.post(PATH + "/{run_id}/resume")
    async def resume(request: Request, run_id: str):
        try:
            payload = request.state.run_payload
            value = await run_in_threadpool(
                runs.resume, request.state.authenticated_request, run_id,
                {"schema_version": payload["schema_version"], "command_id": payload["command_id"]},
                base_path=base_path,
            )
            return JSONResponse(value)
        except RunServiceError as error:
            return run_error(error)

    @router.post(PATH + "/{run_id}/recover")
    async def recover(request: Request, run_id: str):
        try:
            payload = request.state.run_payload
            value = await run_in_threadpool(
                runs.recover, request.state.authenticated_request, run_id,
                {"schema_version": payload["schema_version"], "command_id": payload["command_id"]},
                base_path=base_path,
            )
            return JSONResponse(value)
        except RunServiceError as error:
            return run_error(error)

    @router.post(PATH + "/{run_id}/cancel")
    async def cancel(request: Request, run_id: str):
        try:
            payload = request.state.run_payload
            value = await run_in_threadpool(
                runs.cancel, request.state.authenticated_request, run_id,
                {"schema_version": payload["schema_version"], "command_id": payload["command_id"]},
                base_path=base_path,
            )
            return JSONResponse(value)
        except RunServiceError as error:
            return run_error(error)

    @router.api_route(PATH + "/{run_id}", methods=["GET", "HEAD"])
    async def read(request: Request, run_id: str):
        try:
            value = await run_in_threadpool(runs.read, run_id, base_path=base_path)
            # HEAD carries GET's headers; the boundary blanks the body
            return JSONResponse(value)
        except RunServiceError as error:
            return run_error(error)

    return router
