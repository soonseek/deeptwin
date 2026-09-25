"""Fixed nonversioned owner session HTTP adapter; no domain command aliases."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ..services.owner_auth import OwnerAuthError
from .assets import MODULES, asset_endpoint
from .web_boundary import auth_error


def create_session_router(authority):
    router = APIRouter()

    def cookie(response, value):
        response.set_cookie(authority.cookie_name, value, path=authority.profile.base_path,
                            secure=authority.profile.scheme == "https", httponly=True,
                            samesite="strict", max_age=604800)

    # the instance's first screen (T025, experience.md §5.1.3): the setup/login page,
    # a public static asset like every module; the page decides its form from /health
    router.add_api_route("/", asset_endpoint("start.html"), methods=["GET", "HEAD"])

    @router.api_route("/health", methods=["GET", "HEAD"])
    def health():
        # the public setup state the first screen needs: whether an owner exists and the
        # bootstrap claim's state — never a name, a digest or a session fact; a fault
        # is the closed envelope behind the boundary's headers, never a bare 500
        if authority.reconciling:
            # a recovery start: nothing but this state until the reconciliation commits
            return {"state": "recovery_reconciliation"}
        try:
            owner, setup = authority.setup_state()
        except OwnerAuthError as error:
            return auth_error(error)
        return {"state": "available", "owner": owner, "setup": setup}

    # the shell's modules are public static assets (api.md: the static shell is
    # public); the boundary blanks HEAD bodies and adds the security headers
    for name in MODULES:
        router.add_api_route("/" + name, asset_endpoint(name), methods=["GET", "HEAD"])

    @router.post("/session/bootstrap")
    async def bootstrap(request: Request):
        value = request.state.owner_payload
        try:
            exchange = await run_in_threadpool(authority.bootstrap, **value, source_key=request.state.owner_source)
            response = JSONResponse({"state": "authenticated", "csrf_token": exchange.csrf_token}, status_code=201)
            cookie(response, exchange.token_b64u)
            return response
        except OwnerAuthError as error:
            return auth_error(error)
        finally:
            value.clear()

    @router.post("/session/login")
    async def login(request: Request):
        value = request.state.owner_payload
        try:
            try:
                prior = authority.token_from_cookie(request.state.owner_cookie)
            except OwnerAuthError:
                prior = None
            exchange = await run_in_threadpool(authority.login, **value, source_key=request.state.owner_source, prior_cookie=prior)
            response = JSONResponse({"state": "authenticated", "csrf_token": exchange.csrf_token})
            cookie(response, exchange.token_b64u)
            return response
        except OwnerAuthError as error:
            return auth_error(error)
        finally:
            value.clear()

    @router.api_route("/session", methods=["GET", "HEAD"])
    def session(request: Request):
        token = authority.token_from_cookie(request.state.owner_cookie)
        value = authority.session_view(request.state.authenticated_request, token_b64u=token)
        return Response() if request.method == "HEAD" else JSONResponse(value)

    @router.post("/session/password")
    async def password(request: Request):
        value = request.state.owner_payload
        try:
            token = authority.token_from_cookie(request.state.owner_cookie)
            exchange = await run_in_threadpool(
                authority.change_password, request.state.authenticated_request,
                current_password=value["current_password"], new_password=value["new_password"],
                source_key=request.state.owner_source, token_b64u=token)
            response = JSONResponse({"state": "authenticated", "csrf_token": exchange.csrf_token})
            cookie(response, exchange.token_b64u)  # the session rotates with the password
            return response
        except OwnerAuthError as error:
            return auth_error(error)
        finally:
            value.clear()

    @router.post("/session/revoke-others")
    async def revoke_others(request: Request):
        try:
            token = authority.token_from_cookie(request.state.owner_cookie)
            return JSONResponse(await run_in_threadpool(
                authority.revoke_others, request.state.authenticated_request, token_b64u=token))
        except OwnerAuthError as error:
            return auth_error(error)

    @router.post("/session/logout")
    async def logout(request: Request):
        try:
            token = authority.token_from_cookie(request.state.owner_cookie)
            value = await run_in_threadpool(authority.logout, request.state.authenticated_request,
                command_id=request.state.owner_payload["command_id"], token_b64u=token)
            response = JSONResponse(value)
            response.delete_cookie(authority.cookie_name, path=authority.profile.base_path,
                                   secure=authority.profile.scheme == "https", httponly=True, samesite="strict")
            return response
        except OwnerAuthError as error:
            return auth_error(error)

    return router
