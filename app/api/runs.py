"""Fixed HTTP adapter for owner-started runs (the connected browser path).

`GET|HEAD /api/v1/run-environments/{work_id}` (T048) reads what a run of one work
can use: the owner's prepared environment versions bound back to their stored graph
and work revision (`services/run_environments.py`), or exactly why there is none."""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..services.alternative_drafts import (
    FILE_SCHEMA,
    FREEZE_SCHEMA,
    SAVE_SCHEMA,
    DraftError,
    PersistentAlternativeDrafts,
)
from ..services.owner_auth import OwnerAuthError
from ..services.run_artifacts import PersistentRunArtifacts, RunArtifactError
from ..services.run_environments import PersistentRunEnvironments, RunEnvironmentError
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
ENVIRONMENTS_PREFIX = "/api/v1/run-environments/"
STATUS = {
    "invalid_input": 400,
    "unauthenticated": 401,
    "access_denied": 403,
    "not_found": 404,
    "conflict": 409,
    "too_large": 413,
    "unavailable": 503,
}
# the artifact routes answer codes of their own: a byte range (or a page) past the
# original, a page asked of a file that has none, and a document worker that refused
ARTIFACT_STATUS = {**STATUS, "range_not_satisfiable": 416, "unsupported_media": 415,
                   "codec_failed": 502}
_ARTIFACT_VIEWS = {"content", "preview"}
MAX_PAGE_DIGITS = 5
_REF_FIELDS = ("kind", "id", "version", "sha256")
_CREATE_FIELDS = (
    "command_id", "graph_ref", "work_revision_ref", "environment_ref", "consent_ref",
    "budget_policy_ref",
)


# a draft save carries the owner's edited copy: the text bound plus the command's members
DRAFT_BODY_BYTES = 600_000
# an alternative file travels base64-encoded in its command (4 MiB decoded)
FILE_BODY_BYTES = 5_600_000 + 8_192


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
    code = (error.code if isinstance(error, RunRouteError | RunServiceError | RunArtifactError
                                     | DraftError) else "unavailable")
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


def is_run_environments_path(path: str) -> bool:
    return path.startswith(ENVIRONMENTS_PREFIX)


def environments_preflight(scope, body):
    parse_query(scope.get("query_string", b""), allowed=())
    parts = scope["path"][len(ENVIRONMENTS_PREFIX):].split("/")
    if len(parts) != 1 or scope["method"] not in {"GET", "HEAD"} or body:
        raise WireInputError("invalid_input")
    try:
        uuid_string(parts[0])
    except (TypeError, ValueError):
        raise WireInputError("invalid_input") from None


def is_run_path(path: str) -> bool:
    """`/api/v1/runs`, `/api/v1/runs/{id}`, `/{id}/resume`, `/{id}/cancel` and
    `/{id}/recover`, and the run's artifacts: `/{id}/artifacts`, `/{id}/artifacts/{aid}`,
    `…/{aid}/content`, `…/{aid}/preview`, `…/{aid}/pages/{n}` and `…/{aid}/pages/{n}/image`;
    the approvals routes under the same prefix
    keep their own adapter."""

    if path == PATH:
        return True
    if not path.startswith(PATH + "/") or is_approval_path(path):
        return False
    parts = path[len(PATH) + 1:].split("/")
    return (len(parts) == 1 or (len(parts) == 2 and parts[1] in {"resume", "cancel", "recover"})
            or _artifact_parts(parts) is not None or _draft_parts(parts) is not None
            or _is_file_upload(parts) or _is_difference(parts))


def _is_file_upload(parts) -> bool:
    return len(parts) == 4 and parts[1] == "artifacts" and parts[3] == "alternative-files"


def _is_difference(parts) -> bool:
    return (len(parts) == 6 and parts[1] == "artifacts" and parts[3] == "alternatives"
            and parts[5] == "difference")


def _draft_parts(parts):
    """(artifact id, draft id or None, "freeze" or None) for a drafts path, else None."""

    if len(parts) < 4 or parts[1] != "artifacts" or parts[3] != "drafts" or len(parts) > 6:
        return None
    if len(parts) == 4:
        return (parts[2], None, None)
    if len(parts) == 5:
        return (parts[2], parts[4], None)
    return (parts[2], parts[4], parts[5]) if parts[5] in {"freeze", "differences"} else None


def is_draft_save(path: str, method: str) -> bool:
    """The one run route whose body is an edited copy (larger than a command)."""

    if method != "POST" or not path.startswith(PATH + "/"):
        return False
    drafts = _draft_parts(path[len(PATH) + 1:].split("/"))
    return drafts is not None and drafts[1] is None


def is_file_upload(path: str, method: str) -> bool:
    return (method == "POST" and path.startswith(PATH + "/")
            and _is_file_upload(path[len(PATH) + 1:].split("/")))


def _artifact_parts(parts):
    """(artifact id or None, view or None) for an artifacts path, else None; a page
    path is (artifact id, "pages/{n}") or (artifact id, "pages/{n}/image")."""

    if len(parts) in {5, 6} and parts[1] == "artifacts" and parts[3] == "pages":
        if len(parts) == 6 and parts[5] != "image":
            return None
        return (parts[2], "/".join(parts[3:]))
    if len(parts) < 2 or parts[1] != "artifacts" or len(parts) > 4:
        return None
    if len(parts) == 2:
        return (None, None)
    if len(parts) == 3:
        return (parts[2], None)
    return (parts[2], parts[3]) if parts[3] in _ARTIFACT_VIEWS else None


def page_number(raw) -> int:
    """A canonical decimal page number, 1-based and bounded."""

    if (type(raw) is not str or not 1 <= len(raw) <= MAX_PAGE_DIGITS or not raw.isascii()
            or not raw.isdecimal() or raw != str(int(raw)) or int(raw) < 1):
        raise RunRouteError()
    return int(raw)


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
        if _is_difference(parts):
            uuid_string(parts[2])
            uuid_string(parts[4])
            # observing carries no content: the alternative is named by its path (a browser
            # command may send the empty JSON object)
            if method not in {"GET", "HEAD", "POST"} or body not in (b"", b"{}") \
                    or (method != "POST" and body):
                raise RunRouteError()
            return None
        if _is_file_upload(parts):
            uuid_string(parts[2])
            if method != "POST" or content_type.split(";", 1)[0] != "application/json":
                raise RunRouteError()
            value = parse_json_object(
                body, required=("schema_version", "command_id", "media_type", "name", "content_b64",
                                "selectors", "reviewed_whole"),
                field_types={"schema_version": str, "command_id": str, "media_type": str, "name": str,
                             "content_b64": str, "selectors": list, "reviewed_whole": bool},
                limits=WireLimits(max_bytes=FILE_BODY_BYTES, max_depth=5, max_items=1024,
                                  max_members=8, max_string_bytes=FILE_BODY_BYTES))
            if value["schema_version"] != FILE_SCHEMA:
                raise RunRouteError()
            uuid_string(value["command_id"])
            return value
        drafts = _draft_parts(parts)
        if drafts is not None:
            uuid_string(drafts[0])
            if drafts[1] is not None:
                uuid_string(drafts[1])
            if drafts[2] in {None, "differences"} and method in {"GET", "HEAD"}:
                if body:
                    raise RunRouteError()
                return None
            if method != "POST" or content_type.split(";", 1)[0] != "application/json":
                raise RunRouteError()
            if drafts[1] is None:  # save
                value = parse_json_object(
                    body, required=("schema_version", "command_id", "draft_id", "expected_revision",
                                    "format"), optional=("text", "rows"),
                    field_types={"schema_version": str, "command_id": str, "draft_id": (str, type(None)),
                                 "expected_revision": int, "format": str, "text": str, "rows": list},
                    limits=WireLimits(max_bytes=DRAFT_BODY_BYTES, max_depth=4, max_items=140_000,
                                      max_members=8, max_string_bytes=DRAFT_BODY_BYTES))
                if value["schema_version"] != SAVE_SCHEMA or ("text" in value) == ("rows" in value):
                    raise RunRouteError()
                return value
            if drafts[2] != "freeze":
                raise RunRouteError()
            value = parse_json_object(
                body, required=("schema_version", "command_id", "expected_revision", "reviewed_whole"),
                field_types={"schema_version": str, "command_id": str, "expected_revision": int,
                             "reviewed_whole": bool},
                limits=WireLimits(max_bytes=1024, max_depth=2, max_items=8, max_members=4,
                                  max_string_bytes=128))
            if value["schema_version"] != FREEZE_SCHEMA:
                raise RunRouteError()
            return value
        artifact = _artifact_parts(parts)
        if artifact is not None:
            if method not in {"GET", "HEAD"} or body:
                raise RunRouteError()
            if artifact[0] is not None:
                uuid_string(artifact[0])
            if artifact[1] is not None and artifact[1].startswith("pages/"):
                page_number(parts[4])
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
    artifacts = PersistentRunArtifacts(context.domain_store, context.owner_authority, runs,
                                       codec=context.document_codec)
    drafts = PersistentAlternativeDrafts(artifacts)
    environments = PersistentRunEnvironments(context.domain_store, context.owner_authority,
                                             runs_available=lambda: runs.available)
    return ContributionServices(
        create_router(runs=runs, artifacts=artifacts, drafts=drafts, base_path=context.base_path,
                      environments=environments),
        {"runs.service": runs, "run-artifacts.service": artifacts,
         "alternative-drafts.service": drafts},
    )


def create_router(*, runs, base_path, artifacts=None, drafts=None, environments=None):
    router = APIRouter()

    @router.api_route(ENVIRONMENTS_PREFIX + "{work_id}", methods=["GET", "HEAD"])
    async def run_environments(request: Request, work_id: str):
        try:
            if environments is None:
                raise RunEnvironmentError("unavailable")
            value = await run_in_threadpool(environments.read, request.state.authenticated_request, work_id)
            return JSONResponse(value, headers={"Cache-Control": "no-store"})
        except (RunEnvironmentError, OwnerAuthError) as error:
            return run_error(RunRouteError(getattr(error, "code", "unavailable")))

    async def draft_call(method, *args, status=200, **kwargs):
        try:
            if drafts is None:
                raise RunRouteError("unavailable")
            value = await run_in_threadpool(method, *args, base_path=base_path, **kwargs)
            return JSONResponse(value, status_code=status)
        except (RunRouteError, RunServiceError, RunArtifactError, DraftError) as error:
            return artifact_error(error)

    @router.api_route(PATH + "/{run_id}/artifacts/{artifact_id}/alternatives/{alternative_id}/difference",
                      methods=["GET", "HEAD"])
    async def difference_read(request: Request, run_id: str, artifact_id: str, alternative_id: str):
        return await draft_call(drafts.read_difference if drafts else None,
                                request.state.authenticated_request, run_id, artifact_id, alternative_id)

    @router.post(PATH + "/{run_id}/artifacts/{artifact_id}/alternatives/{alternative_id}/difference")
    async def difference_observe(request: Request, run_id: str, artifact_id: str, alternative_id: str):
        return await draft_call(drafts.observe_difference if drafts else None,
                                request.state.authenticated_request, run_id, artifact_id, alternative_id,
                                status=201)

    @router.post(PATH + "/{run_id}/artifacts/{artifact_id}/alternative-files")
    async def alternative_file(request: Request, run_id: str, artifact_id: str):
        return await draft_call(drafts.upload_file if drafts else None,
                                request.state.authenticated_request, run_id, artifact_id,
                                request.state.run_payload, status=201)

    @router.api_route(PATH + "/{run_id}/artifacts/{artifact_id}/drafts", methods=["GET", "HEAD"])
    async def draft_list(request: Request, run_id: str, artifact_id: str):
        return await draft_call(drafts.list if drafts else None,
                                request.state.authenticated_request, run_id, artifact_id)

    @router.post(PATH + "/{run_id}/artifacts/{artifact_id}/drafts")
    async def draft_save(request: Request, run_id: str, artifact_id: str):
        return await draft_call(drafts.save if drafts else None, request.state.authenticated_request,
                                run_id, artifact_id, request.state.run_payload, status=201)

    @router.api_route(PATH + "/{run_id}/artifacts/{artifact_id}/drafts/{draft_id}",
                      methods=["GET", "HEAD"])
    async def draft_read(request: Request, run_id: str, artifact_id: str, draft_id: str):
        return await draft_call(drafts.read if drafts else None,
                                request.state.authenticated_request, run_id, artifact_id, draft_id)

    @router.api_route(PATH + "/{run_id}/artifacts/{artifact_id}/drafts/{draft_id}/differences",
                      methods=["GET", "HEAD"])
    async def draft_differences(request: Request, run_id: str, artifact_id: str, draft_id: str):
        return await draft_call(drafts.differences if drafts else None,
                                request.state.authenticated_request, run_id, artifact_id, draft_id)

    @router.post(PATH + "/{run_id}/artifacts/{artifact_id}/drafts/{draft_id}/freeze")
    async def draft_freeze(request: Request, run_id: str, artifact_id: str, draft_id: str):
        return await draft_call(drafts.freeze if drafts else None,
                                request.state.authenticated_request, run_id, artifact_id, draft_id,
                                request.state.run_payload, status=201)

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

    @router.api_route(PATH + "/{run_id}/artifacts/{artifact_id}/pages/{page}", methods=["GET", "HEAD"])
    async def artifact_page(request: Request, run_id: str, artifact_id: str, page: str):
        try:
            if artifacts is None:
                raise RunRouteError("unavailable")
            value = await run_in_threadpool(artifacts.page, request.state.authenticated_request,
                                            run_id, artifact_id, page_number(page), base_path=base_path)
            return JSONResponse(value)
        except (RunRouteError, RunServiceError, RunArtifactError) as error:
            return artifact_error(error)

    @router.api_route(PATH + "/{run_id}/artifacts/{artifact_id}/pages/{page}/image",
                      methods=["GET", "HEAD"])
    async def artifact_page_image(request: Request, run_id: str, artifact_id: str, page: str):
        try:
            if artifacts is None:
                raise RunRouteError("unavailable")
            number = page_number(page)
            meta, png, digest = await run_in_threadpool(
                artifacts.page_image, request.state.authenticated_request, run_id, artifact_id,
                number, base_path=base_path)
            # a derived image the document worker produced: typed as the PNG it was
            # checked to be, never the original, sandboxed like every artifact body
            headers = {"Content-Disposition": f'inline; filename="{meta["role"]}-{meta["ordinal"]}-page-{number}.png"',
                       "Content-Length": str(len(png)), "X-DeepTwin-Derived-SHA256": digest,
                       "Content-Security-Policy": "sandbox; default-src 'none'"}
            return Response(png, media_type="image/png", headers=headers)
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
