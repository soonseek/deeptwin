"""Authenticated HTTP ingress route for credential create/rotate (T090).

The control plane never imports the vault implementation: the route validates
the exact wire (session/CSRF authority first, then the ingress wire checks) and
hands the validated intent to a trusted host-wired ``credential_gateway_submit``
callable attached on application state — later the broker-backed UDS client,
today honestly absent (the route reports unavailability). The gateway returns a
redacted receipt; a receipt of any other shape is rejected so nothing a gateway
returns can echo secret material to the browser.
"""

from __future__ import annotations

import re

from fastapi import Request
from fastapi.responses import JSONResponse

from .credential_ingress import CredentialIngressError, parse_credential_ingress
from .routes import (
    NOT_RETRYABLE,
    ApiDependencyUnavailable,
    _authenticated,
    _failure,
    api_error,
)

_RECEIPT_FIELDS = frozenset({"handle", "provider", "state"})
_RECEIPT_STATES = frozenset({"active"})
_RETIRE_FIELDS = frozenset({"handle", "state"})
_RETIRE_STATES = frozenset({"cleanup_pending", "erasure_completed"})
_SNAPSHOT_STATES = frozenset({
    "active", "cleanup_pending", "secret_input_lost", "erasure_completed",
})
_HANDLE = re.compile(r"[0-9a-f]{32}\Z")


def _redacted_receipt(receipt: object) -> dict:
    if (
        type(receipt) is not dict
        or set(receipt) != _RECEIPT_FIELDS
        or any(type(value) is not str for value in receipt.values())
        or receipt["state"] not in _RECEIPT_STATES
    ):
        raise ApiDependencyUnavailable("credential gateway receipt is invalid")
    return {name: receipt[name] for name in ("handle", "provider", "state")}


def _redacted_retirement(receipt: object) -> dict:
    if (
        type(receipt) is not dict
        or set(receipt) != _RETIRE_FIELDS
        or any(type(value) is not str for value in receipt.values())
        or receipt["state"] not in _RETIRE_STATES
    ):
        raise ApiDependencyUnavailable("credential gateway receipt is invalid")
    return {name: receipt[name] for name in ("handle", "state")}


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
        ):
            raise ApiDependencyUnavailable("credential snapshot is invalid")
        redacted.append(
            {name: entry[name] for name in ("handle", "provider", "state")}
        )
    return redacted


def install_credential_ingress(app) -> None:
    """Attach the authenticated create/rotate ingress route."""

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
            except CredentialIngressError:
                return api_error(
                    status=400,
                    code="invalid_input",
                    message="자격증명 요청 형식을 확인해 주세요.",
                    retryability=NOT_RETRYABLE,
                )
            submit = getattr(
                request.app.state, "credential_gateway_submit", None
            )
            if submit is None:
                raise ApiDependencyUnavailable(
                    "credential gateway is not attached"
                )
            receipt = _redacted_receipt(submit(ingress))
            return JSONResponse(status_code=201, content=receipt)
        except Exception as exc:  # noqa: BLE001 - sanitize the public boundary
            return _failure(exc)

    @app.api_route("/api/v1/credentials/{handle}", methods=["DELETE"])
    async def credential_delete_v1(handle: str, request: Request):
        try:
            _authenticated(request, read=False)
            if type(handle) is not str or _HANDLE.fullmatch(handle) is None:
                return api_error(
                    status=400,
                    code="invalid_input",
                    message="자격증명 핸들 형식을 확인해 주세요.",
                    retryability=NOT_RETRYABLE,
                )
            retire = getattr(
                request.app.state, "credential_gateway_retire", None
            )
            if retire is None:
                raise ApiDependencyUnavailable(
                    "credential gateway is not attached"
                )
            receipt = _redacted_retirement(retire(handle))
            return JSONResponse(status_code=200, content=receipt)
        except Exception as exc:  # noqa: BLE001 - sanitize the public boundary
            return _failure(exc)

    @app.api_route("/api/v1/credentials", methods=["GET"])
    async def credential_status_v1(request: Request):
        try:
            # A status read is a snapshot of already-known redacted state; it
            # must make zero vault, gateway, provider or network effect.
            _authenticated(request, read=True)
            snapshot = getattr(
                request.app.state, "credential_status_snapshot", None
            )
            if snapshot is None:
                raise ApiDependencyUnavailable(
                    "credential status snapshot is not attached"
                )
            return JSONResponse(
                status_code=200,
                content={"credentials": _redacted_snapshot(snapshot())},
            )
        except Exception as exc:  # noqa: BLE001 - sanitize the public boundary
            return _failure(exc)


__all__ = ["install_credential_ingress"]
