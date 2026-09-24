"""Fixed HTTP adapter for the owner's Claude API connection: the
`claude-connection-v1` contribution.

- `GET /api/v1/connections/claude` reads the connection state. It never returns
  the key, a hash or a handle.
- `POST …/key` stores the key in server memory only.
- `POST …/forget` drops the key.
- `POST …/catalog` is the owner's explicit, free `GET /v1/models` read.
- `POST …/model-choice` seals a `model_choice` record for a model the refreshed
  catalog listed.

The shared `/api/v1` preflight admits each body exactly before auth. The secret's
own bounds are checked again by the service.
"""

import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..services.claude_connection import ClaudeConnection, ClaudeConnectionError
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/connections/claude"
STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403, "not_found": 404,
          "conflict": 409, "unavailable": 503, "provider_unavailable": 503, "provider_rejected": 424}
MAX_SECRET_BYTES = 65_536
COMMANDS = {
    "key": (("secret",), {"secret": str}, WireLimits(max_bytes=98_304, max_depth=2, max_items=4,
                                                      max_members=4, max_string_bytes=MAX_SECRET_BYTES)),
    "forget": ((), {}, WireLimits(max_bytes=64, max_depth=2, max_items=4, max_members=4, max_string_bytes=8)),
    "catalog": ((), {}, WireLimits(max_bytes=64, max_depth=2, max_items=4, max_members=4, max_string_bytes=8)),
    "model-choice": (("model_id",), {"model_id": str}, WireLimits(max_bytes=512, max_depth=2, max_items=4,
                                                                  max_members=4, max_string_bytes=128)),
}


def is_claude_connection_path(path: str) -> bool:
    return path == PATH or path.startswith(PATH + "/")


def _body(raw: bytes, command: str) -> dict:
    required, types, limits = COMMANDS[command]
    return parse_json_object(raw or b"{}", required=required, field_types=types, limits=limits)


def preflight(scope, body):
    path, method = scope["path"], scope["method"]
    parse_query(scope.get("query_string", b""), allowed=())
    if path == PATH:
        if method not in {"GET", "HEAD"} or body:
            raise WireInputError("invalid_input")
        return
    command = path[len(PATH) + 1:]
    if command not in COMMANDS or method != "POST":
        raise WireInputError("invalid_input")
    _body(body, command)


def connection_error(error):
    code = error.code if isinstance(error, ClaudeConnectionError) else "invalid_input"
    return JSONResponse({"code": code, "message": "Claude connection request could not be admitted",
                         "retryability": "not_retryable", "affected_refs": [],
                         "correlation_id": str(uuid4())}, status_code=STATUS.get(code, 503))


def connection_services(context):
    from ..services.claude_run_executor import ClaudeRunExecutor

    executor = context.run_executor if type(context.run_executor) is ClaudeRunExecutor else None
    connection = ClaudeConnection(context.domain_store, context.owner_authority,
                                  transport=None if executor is None else executor.transport)
    if executor is not None:
        executor.bind(context.domain_store, connection)
    return ContributionServices(create_router(connection=connection), {"claude.connection": connection})


def create_router(*, connection):
    router = APIRouter()

    @router.api_route(PATH, methods=["GET", "HEAD"])
    async def read(request: Request):
        try:
            return JSONResponse(await run_in_threadpool(connection.state, request.state.authenticated_request),
                                headers={"Cache-Control": "no-store"})
        except ClaudeConnectionError as error:
            return connection_error(error)

    def handler(name):
        async def command(request: Request):
            try:
                value = _body(await request.body(), name)
            except (WireInputError, ValueError, json.JSONDecodeError):
                return connection_error(ClaudeConnectionError("invalid_input"))
            authenticated = request.state.authenticated_request
            try:
                if name == "key":
                    secret = value.pop("secret")
                    try:
                        result = await run_in_threadpool(connection.store_key, authenticated, secret)
                    finally:
                        secret = ""
                elif name == "forget":
                    result = await run_in_threadpool(connection.forget_key, authenticated)
                elif name == "catalog":
                    result = await run_in_threadpool(connection.refresh_catalog, authenticated)
                else:
                    result = await run_in_threadpool(connection.choose_model, authenticated, value["model_id"])
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
            except ClaudeConnectionError as error:
                return connection_error(error)
        return command

    for name in COMMANDS:
        router.add_api_route(f"{PATH}/{name}", handler(name), methods=["POST"])
    return router
