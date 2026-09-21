"""Fixed provider-only routes under the existing deployment contribution."""

from fastapi import APIRouter, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from ..deployment.prepare_contracts import DeploymentPrepareError, require
from ..deployment.prepare_service import PersistentDeploymentPrepare
from ..deployment.provider_prepare_contracts import (
    parse_provider_cancel,
    parse_provider_prepare,
)
from ..deployment.provider_receipt_contracts import parse_provider_receipt_import, parse_provider_consume, parse_provider_pending_cancel
from ..domain.refs import canonical_json, uuid_string
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/deployment/provider-requests"


def preflight(scope, body, content_type):
    try:
        path, method = scope["path"], scope["method"]
        parse_query(scope.get("query_string", b""), allowed=())
        request_id = None
        operation = None
        optional = ()
        if path == PATH:
            require(method == "POST", "invalid_input")
            required = (
                "command_id",
                "kind",
                "candidate_id",
                "slot_id",
                "expires_in_seconds",
                "source_context_sha256",
            )
        else:
            parts = (
                path[len(PATH) + 1 :].split("/") if path.startswith(PATH + "/") else []
            )
            require(bool(parts), "invalid_input")
            request_id = uuid_string(parts[0])
            if len(parts) == 1 and method in {"GET", "HEAD"}:
                require(not body, "invalid_input")
                return None
            require(
                len(parts) == 2 and parts[1] in {"cancel", "receipts", "consume"} and method == "POST",
                "invalid_input",
            )
            required = ("command_id", "request_digest", "expected_revision")
            operation = parts[1]
            if operation == "cancel":
                optional = ("receipt_digest",)
            else:
                required += ("receipt_digest",)
        require(content_type.split(";", 1)[0] == "application/json", "invalid_input")
        value = parse_json_object(
            body,
            required=required,
            optional=optional,
            limits=WireLimits(
                max_bytes=4096,
                max_depth=4,
                max_items=32,
                max_members=8,
                max_string_bytes=256,
            ),
        )
        if request_id is None:
            return parse_provider_prepare(value)
        parser = parse_provider_receipt_import if operation == "receipts" else parse_provider_consume if operation == "consume" else parse_provider_pending_cancel if "receipt_digest" in value else parse_provider_cancel
        parsed = parser(request_id, value)
        return {key: val for key, val in parsed.items() if key != "request_id"}
    except DeploymentPrepareError:
        raise
    except (WireInputError, ValueError):
        raise DeploymentPrepareError("invalid_input") from None


def create_router(*, service: PersistentDeploymentPrepare, base_path: str) -> APIRouter:
    from .deployment_prepare import deployment_error

    router = APIRouter()

    def response(value, status=200):
        require(base_path == service._profile.base_path, "unavailable")
        projected = {
            **value,
            "links": {
                key: base_path.rstrip("/") + path
                for key, path in value["links"].items()
            },
        }
        raw = canonical_json(projected)
        require(len(raw) <= (73728 if "request" in value else 8192), "unavailable")
        return Response(raw, status_code=status, media_type="application/json")

    @router.post(PATH)
    async def prepare(request: Request):
        try:
            return response(
                await run_in_threadpool(
                    service.prepare_provider,
                    request.state.authenticated_request,
                    request.state.provider_deployment_payload,
                ),
                201,
            )
        except DeploymentPrepareError as error:
            return deployment_error(error)

    @router.post(PATH + "/{request_id}/cancel")
    async def cancel(request: Request, request_id: str):
        try:
            return response(
                await run_in_threadpool(
                    service.cancel_provider,
                    request.state.authenticated_request,
                    request_id,
                    request.state.provider_deployment_payload,
                )
            )
        except DeploymentPrepareError as error:
            return deployment_error(error)

    @router.api_route(PATH + "/{request_id}", methods=["GET", "HEAD"])
    async def read(request: Request, request_id: str):
        try:
            return response(
                await run_in_threadpool(
                    service.read_provider,
                    request.state.authenticated_request,
                    request_id,
                )
            )
        except DeploymentPrepareError as error:
            return deployment_error(error)

    @router.post(PATH + "/{request_id}/receipts")
    async def receipt_import(request: Request, request_id: str):
        try:
            return response(await run_in_threadpool(service.import_provider_receipt, request.state.authenticated_request, request_id, request.state.provider_deployment_payload))
        except DeploymentPrepareError as error:
            return deployment_error(error)

    @router.post(PATH + "/{request_id}/consume")
    async def consume(request: Request, request_id: str):
        try:
            return response(await run_in_threadpool(service.consume_provider_receipt, request.state.authenticated_request, request_id, request.state.provider_deployment_payload))
        except DeploymentPrepareError as error:
            return deployment_error(error)

    return router
