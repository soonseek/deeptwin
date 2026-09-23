"""Exact external transport and cheap wire admission before persistent auth."""
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..deployment.prepare_contracts import DeploymentPrepareError
from ..extensions.candidate_contracts import CandidateError
from ..extensions.provider_conformance_contracts import ConformanceError
from ..extensions.provider_installation_contracts import InstallationError
from ..services.owner_auth import OwnerAuthError, validate_credentials
from ..services.owner_material_intake import OwnerMaterialIntake
from ..services.owner_material_upload_lock import UploadLock
from ..services.run_approvals import RunApprovalError
from ..services.run_consents import RunConsentError
from ..services.runs import RunServiceError
from ..services.works import WorkServiceError
from . import owner_material_upload as material_upload
from . import provider_installation as installation
from .assets import PUBLIC_ASSET_PATHS
from .deployment_prepare import PATH as DEPLOYMENT_PATH
from .deployment_prepare import deployment_error
from .deployment_prepare import preflight as deployment_preflight
from .extension_candidates import PATH as CANDIDATE_PATH
from .extension_candidates import candidate_error
from .extension_candidates import preflight as candidate_preflight
from .provider_conformance import PATH as PROVIDER_CONFORMANCE_PATH
from .provider_conformance import conformance_error
from .provider_conformance import preflight as provider_conformance_preflight
from .provider_deployment_prepare import PATH as PROVIDER_DEPLOYMENT_PATH
from .provider_deployment_prepare import preflight as provider_deployment_preflight
from .run_approvals import ApprovalRouteError, approval_error, is_approval_path
from .run_approvals import preflight as approval_preflight
from .run_consents import ConsentRouteError, consent_error, is_consent_path
from .run_consents import preflight as consent_preflight
from .runs import (
    DRAFT_BODY_BYTES,
    FILE_BODY_BYTES,
    RunRouteError,
    is_draft_save,
    is_file_upload,
    is_run_path,
    run_error,
)
from .runs import preflight as run_preflight
from .wire import (
    WireInputError,
    WireLimits,
    parse_json_object,
    parse_query,
    parse_singleton_headers,
)
from .works import MAX_BODY_BYTES as WORK_BODY_BYTES
from .works import WorkRouteError, is_work_path, work_error
from .works import preflight as work_preflight

SECURITY_HEADERS = {
    "cache-control": "no-store", "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer", "x-frame-options": "DENY",
    "content-security-policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'",
}
STATUS = {"invalid_input": 400, "credentials": 401, "capacity": 429, "unavailable": 503,
          "setup_incomplete": 409, "setup_unavailable": 409, "unauthenticated": 401,
          "access_denied": 403, "conflict": 409}


def auth_error(error):
    return JSONResponse({"code": error.code, "message": "Session request could not be admitted",
                         "retryability": "not_retryable", "affected_refs": []},
                        status_code=STATUS[error.code])


class WebBoundary:
    def __init__(self, app, *, authority):
        self.app, self.authority = app, authority

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        profile = self.authority.profile

        async def safe_send(message):
            if message["type"] == "http.response.start":
                headers = dict(SECURITY_HEADERS)
                if profile.scheme == "https":
                    headers["strict-transport-security"] = "max-age=31536000"
                message = {**message, "headers": [(k, v) for k, v in message["headers"]
                           if k.lower().decode("ascii") not in headers]
                           + [(k.encode(), v.encode()) for k, v in headers.items()]}
            elif message["type"] == "http.response.body" and scope["method"] == "HEAD":
                message = {**message, "body": b""}
            await send(message)

        state = {}
        provider_external = profile.base_path.rstrip("/") + PROVIDER_DEPLOYMENT_PATH
        provider_route = scope.get("path", "") == provider_external or scope.get("path", "").startswith(provider_external + "/")
        conformance_external = profile.base_path.rstrip("/") + PROVIDER_CONFORMANCE_PATH
        conformance_route = (scope.get("path", "") == conformance_external
            or scope.get("path", "").startswith(conformance_external + "/"))
        installation_external = profile.base_path.rstrip('/')+installation.PATH
        installation_route = (scope.get('path','') == installation_external
            or scope.get('path','').startswith(installation_external+'/'))
        try:
            raw_headers = scope.get("headers", [])
            if len(raw_headers) > 256 or sum(len(k) + len(v) for k, v in raw_headers) > 65536:
                raise OwnerAuthError("invalid_input")
            fields = parse_singleton_headers(raw_headers, names=("host", "origin", "sec-fetch-site", "cookie",
                "x-deeptwin-csrf", "content-length", "content-type", "last-event-id",
                "x-deeptwin-source-metadata", "content-encoding", "range"), required=("host",))
            if any(name.lower() == b"forwarded" or name.lower().startswith(b"x-forwarded-")
                   or name.lower() in {b"x-original-url", b"x-rewrite-url"} for name, _ in raw_headers):
                raise OwnerAuthError("access_denied")
            if (scope.get("scheme") != profile.scheme or scope.get("root_path", "")
                    or fields["host"] != profile.http_origin.split("://", 1)[1]
                    or fields.get("origin") not in (None, profile.http_origin)
                    or fields.get("sec-fetch-site") not in (None, "none", "same-origin")):
                raise OwnerAuthError("access_denied")
            raw = scope.get("raw_path", b"")
            if (not raw or b"%" in raw or b"\\" in raw or b"//" in raw
                    or any(part in {b".", b".."} for part in raw.split(b"/"))):
                raise OwnerAuthError("access_denied")
            try:
                path = raw.decode("ascii")
            except UnicodeError:
                raise OwnerAuthError("access_denied") from None
            if path != scope["path"] or not path.startswith(profile.base_path):
                raise OwnerAuthError("access_denied")
            path = "/" + path[len(profile.base_path):]
            method = scope["method"]
            candidate_route = path == CANDIDATE_PATH or path.startswith(CANDIDATE_PATH + "/")
            deployment_route = path == DEPLOYMENT_PATH or path.startswith(DEPLOYMENT_PATH + "/")
            provider_route = path == PROVIDER_DEPLOYMENT_PATH or path.startswith(PROVIDER_DEPLOYMENT_PATH + "/")
            conformance_route = (path == PROVIDER_CONFORMANCE_PATH
                or path.startswith(PROVIDER_CONFORMANCE_PATH + "/"))
            installation_route = path == installation.PATH or path.startswith(installation.PATH+'/')
            approval_route = is_approval_path(path)
            run_route = is_run_path(path)
            consent_route = is_consent_path(path)
            work_route = is_work_path(path)
            session_route = path == "/session" or path.startswith("/session/")
            establishment = path in {"/session/bootstrap", "/session/login"} and method == "POST"
            logout = path == "/session/logout" and method == "POST"
            password_change = path == "/session/password" and method == "POST"
            revoke_others = path == "/session/revoke-others" and method == "POST"
            if method not in {"GET", "HEAD"} and (fields.get("origin") != profile.http_origin
                                                   or fields.get("sec-fetch-site") != "same-origin"):
                raise OwnerAuthError("access_denied")
            if session_route or path in PUBLIC_ASSET_PATHS:
                parse_query(scope.get("query_string", b""), allowed=())  # no query rides on an asset
            body = b""
            source_upload = material_upload.is_source_upload(path, method)
            if installation_route:
                declared = installation.preflight({**scope,'path':path},fields)
                state['authenticated_request'] = await run_in_threadpool(self.authority.authenticate_request,
                    method=method,host=fields['host'],origin=fields.get('origin'),
                    sec_fetch_site=fields.get('sec-fetch-site'),cookie_header=fields.get('cookie'),
                    csrf_token=fields.get('x-deeptwin-csrf'))
                if method == 'POST':
                    try: state['upload_lock'] = UploadLock(self.authority._domain.data_dir)
                    except WorkServiceError as error: raise InstallationError(error.code) from None
                    state['installation_packet'] = await installation.receive_packet(receive,declared)
                else:
                    message = await receive()
                    if message['type'] == 'http.disconnect': return
                    if message['type'] != 'http.request' or message.get('body',b'') or message.get('more_body',False):
                        raise InstallationError()
            elif source_upload:
                work_id, meta = material_upload.preflight({**scope, "path": path}, fields)
                authenticated = await run_in_threadpool(self.authority.authenticate_request,
                    method=method, host=fields["host"], origin=fields.get("origin"),
                    sec_fetch_site=fields.get("sec-fetch-site"), cookie_header=fields.get("cookie"),
                    csrf_token=fields.get("x-deeptwin-csrf"))
                state["authenticated_request"] = authenticated
                lease = UploadLock(self.authority._domain.data_dir)
                state["upload_lock"] = lease
                intake = OwnerMaterialIntake(scope["app"].state.first_party_exports["works.service"])
                await run_in_threadpool(intake.admit, authenticated, work_id, meta)
                state["source_metadata"] = meta
                state["source_bytes"] = await material_upload.receive_original(receive, meta)
            elif method not in {"GET", "HEAD"} or candidate_route or deployment_route or provider_route or conformance_route or approval_route or run_route or consent_route or work_route:
                limit = 1048576 if path == CANDIDATE_PATH and method == "POST" else 8192 if session_route else 131072
                if deployment_route or provider_route or conformance_route or approval_route or run_route or consent_route:
                    limit = 4096
                if candidate_route and method in {"GET", "HEAD"}:
                    limit = 0
                if (deployment_route or provider_route) and method in {"GET", "HEAD"}:
                    limit = 0
                if conformance_route and method in {"GET", "HEAD"}:
                    limit = 0
                if approval_route and method in {"GET", "HEAD"}:
                    limit = 0
                if (run_route or consent_route) and method in {"GET", "HEAD"}:
                    limit = 0
                if run_route and is_draft_save(path, method):
                    limit = DRAFT_BODY_BYTES
                if run_route and is_file_upload(path, method):
                    limit = FILE_BODY_BYTES
                if work_route:
                    limit = WORK_BODY_BYTES if method == "POST" else 0
                length = fields.get("content-length", "0")
                if not length.isdecimal():
                    raise OwnerAuthError("invalid_input")
                if int(length) > limit:
                    if conformance_route:
                        raise ConformanceError("invalid_input" if limit == 0 else "too_large")
                    if deployment_route or provider_route:
                        raise DeploymentPrepareError("invalid_input" if limit == 0 else "too_large")
                    if candidate_route:
                        raise CandidateError("invalid_input" if limit == 0 else "too_large")
                    if approval_route:
                        raise ApprovalRouteError("invalid_input" if limit == 0 else "too_large")
                    if run_route:
                        raise RunRouteError("invalid_input" if limit == 0 else "too_large")
                    if consent_route:
                        raise ConsentRouteError("invalid_input" if limit == 0 else "too_large")
                    if work_route:
                        raise WorkRouteError("invalid_input" if limit == 0 else "too_large")
                    response = JSONResponse({"code": "invalid_input"}, status_code=413)
                    return await response(scope, receive, safe_send)
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > limit:
                        if conformance_route:
                            raise ConformanceError("invalid_input" if limit == 0 else "too_large")
                        if deployment_route or provider_route:
                            raise DeploymentPrepareError("invalid_input" if limit == 0 else "too_large")
                        if candidate_route:
                            raise CandidateError("invalid_input" if limit == 0 else "too_large")
                        if approval_route:
                            raise ApprovalRouteError("invalid_input" if limit == 0 else "too_large")
                        if run_route:
                            raise RunRouteError("invalid_input" if limit == 0 else "too_large")
                        if consent_route:
                            raise ConsentRouteError("invalid_input" if limit == 0 else "too_large")
                        if work_route:
                            raise WorkRouteError("invalid_input" if limit == 0 else "too_large")
                        response = JSONResponse({"code": "invalid_input"}, status_code=413)
                        return await response(scope, receive, safe_send)
                    body += chunk
                    if not message.get("more_body", False):
                        break
            if password_change:
                if fields.get("content-type", "").split(";", 1)[0] != "application/json":
                    raise OwnerAuthError("invalid_input")
                data = parse_json_object(body, required=("current_password", "new_password"),
                                         field_types={"current_password": str, "new_password": str},
                                         limits=WireLimits(max_bytes=8192, max_string_bytes=1024))
                validate_credentials("owner", data["current_password"])
                validate_credentials("owner", data["new_password"], choosing=True)
                state["owner_payload"] = data
            if revoke_others and body not in (b"", b"{}"):
                raise OwnerAuthError("invalid_input")
            if establishment or logout:
                if fields.get("content-type", "").split(";", 1)[0] != "application/json":
                    raise OwnerAuthError("invalid_input")
                required = (("command_id",) if logout else ("login_name", "password", "raw_capability_b64u")
                            if path == "/session/bootstrap" else ("login_name", "password"))
                data = parse_json_object(body, required=required, field_types={key: str for key in required},
                                         limits=WireLimits(max_bytes=8192, max_string_bytes=1024))
                if establishment:
                    validate_credentials(data["login_name"], data["password"], choosing=path == "/session/bootstrap")
                else:
                    from ..domain.refs import uuid_string
                    uuid_string(data["command_id"])
                state["owner_payload"] = data
            if installation_route:
                pass  # already preflighted and authenticated before any receive
            elif conformance_route:
                if method in {"GET", "HEAD"} and fields.get("content-length", "0") != "0":
                    raise ConformanceError("invalid_input")
                state["provider_conformance_payload"] = provider_conformance_preflight(
                    {**scope, "path": path}, body, fields.get("content-type", ""))
            elif provider_route:
                if method in {"GET", "HEAD"} and fields.get("content-length", "0") != "0":
                    raise DeploymentPrepareError()
                state["provider_deployment_payload"] = provider_deployment_preflight({**scope, "path": path}, body, fields.get("content-type", ""))
            elif deployment_route:
                if method in {"GET", "HEAD"} and fields.get("content-length", "0") != "0":
                    raise DeploymentPrepareError()
                state["deployment_payload"] = deployment_preflight({**scope, "path": path}, body, fields.get("content-type", ""))
            elif candidate_route:
                if method in {"GET", "HEAD"} and fields.get("content-length", "0") != "0":
                    raise CandidateError()
                state["candidate_payload"] = candidate_preflight({**scope,"path":path},body,fields.get("content-type",""))
            elif approval_route:
                if method in {"GET", "HEAD"} and fields.get("content-length", "0") != "0":
                    raise ApprovalRouteError()
                state["approval_payload"] = approval_preflight({**scope, "path": path}, body, fields.get("content-type", ""))
            elif run_route:
                if method in {"GET", "HEAD"} and fields.get("content-length", "0") != "0":
                    raise RunRouteError()
                state["run_payload"] = run_preflight({**scope, "path": path}, body, fields.get("content-type", ""))
            elif consent_route:
                if method in {"GET", "HEAD"} and fields.get("content-length", "0") != "0":
                    raise ConsentRouteError()
                state["consent_payload"] = consent_preflight({**scope, "path": path}, body, fields.get("content-type", ""))
            elif work_route and not source_upload:
                if method in {"GET", "HEAD"} and fields.get("content-length", "0") != "0":
                    raise WorkRouteError()
                state["work_payload"] = work_preflight({**scope, "path": path}, body, fields.get("content-type", ""))
            elif path.startswith('/api/v1/') and not source_upload:
                from .routes import preflight_api_v1
                preflight_api_v1({**scope, "path": path}, body)
            public = ((path in {"/", "/health"} or path in PUBLIC_ASSET_PATHS)
                      and method in {"GET", "HEAD"}) or establishment
            if not public and not source_upload and not installation_route:
                try:
                    state["authenticated_request"] = await run_in_threadpool(
                        self.authority.authenticate_request, method=method, host=fields["host"],
                        origin=fields.get("origin"), sec_fetch_site=fields.get("sec-fetch-site"),
                        cookie_header=fields.get("cookie"), csrf_token=fields.get("x-deeptwin-csrf"))
                except OwnerAuthError as error:
                    if not logout or error.code != "unauthenticated":
                        raise
                    # A revoked cookie can only retrieve its exact private logout receipt.
                    token = self.authority.token_from_cookie(fields.get("cookie"))
                    self.authority.verify_csrf(token, fields.get("x-deeptwin-csrf"))
                    state["authenticated_request"] = None
            peer = scope.get("client")
            if not peer or type(peer[0]) is not str:
                raise OwnerAuthError("access_denied")
            state["owner_source"] = peer[0]
            state["owner_cookie"] = fields.get("cookie")
            routed = {**scope, "path": path, "raw_path": path.encode(), "state": {**scope.get("state", {}), **state}}
            consumed = False

            async def replay():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()
            await self.app(routed, replay if method not in {"GET", "HEAD"} or candidate_route or deployment_route or provider_route or conformance_route or approval_route or run_route or consent_route or work_route else receive, safe_send)
        except (RunRouteError, RunServiceError) as error:
            await run_error(error)(scope, receive, safe_send)
        except (ConsentRouteError, RunConsentError) as error:
            await consent_error(error)(scope, receive, safe_send)
        except (WorkRouteError, WorkServiceError) as error:
            await work_error(error)(scope, receive, safe_send)
        except (ApprovalRouteError, RunApprovalError) as error:
            await approval_error(error)(scope, receive, safe_send)
        except DeploymentPrepareError as error:
            await deployment_error(error)(scope, receive, safe_send)
        except CandidateError as error:
            await candidate_error(error)(scope, receive, safe_send)
        except ConformanceError as error:
            await conformance_error(error)(scope, receive, safe_send)
        except InstallationError as error:
            await installation.installation_error(error)(scope,receive,safe_send)
        except (WireInputError, ValueError) as error:
            error = error if isinstance(error, OwnerAuthError) else OwnerAuthError("invalid_input")
            response = (installation.installation_error(error) if installation_route else conformance_error(ConformanceError(error.code if error.code in
                {"invalid_input", "unauthenticated", "access_denied", "unavailable", "capacity", "conflict"}
                else "unavailable")) if conformance_route else
                deployment_error(DeploymentPrepareError(error.code if error.code in {"invalid_input", "unauthenticated", "access_denied", "unavailable", "capacity", "conflict"} else "unavailable")) if provider_route else auth_error(error))
            await response(scope, receive, safe_send)
        except OwnerAuthError as error:
            response = (installation.installation_error(error) if installation_route else conformance_error(ConformanceError(error.code if error.code in
                {"invalid_input", "unauthenticated", "access_denied", "unavailable", "capacity", "conflict"}
                else "unavailable")) if conformance_route else
                deployment_error(DeploymentPrepareError(error.code if error.code in {"invalid_input", "unauthenticated", "access_denied", "unavailable", "capacity", "conflict"} else "unavailable")) if provider_route else auth_error(error))
            await response(scope, receive, safe_send)
        finally:
            if installation_route:
                # An intake/publication interruption remains the primary failure;
                # nevertheless attempt every owned cleanup and drop request state.
                import sys
                primary = sys.exc_info()[1]
                cleanup_error = None
                for key, method in (("upload_lock", "close"), ("owner_payload", "clear")):
                    if key in state:
                        try:
                            getattr(state[key], method)()
                        except BaseException as error:
                            if cleanup_error is None:
                                cleanup_error = error
                state.clear()
                if primary is None and cleanup_error is not None:
                    raise cleanup_error
            else:
                if "upload_lock" in state:
                    state["upload_lock"].close()
                if "owner_payload" in state:
                    state["owner_payload"].clear()
                state.clear()
