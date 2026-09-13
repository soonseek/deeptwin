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


def _redacted_receipt(receipt: object) -> dict:
    if (
        type(receipt) is not dict
        or set(receipt) != _RECEIPT_FIELDS
        or any(type(value) is not str for value in receipt.values())
        or receipt["state"] not in _RECEIPT_STATES
    ):
        raise ApiDependencyUnavailable("credential gateway receipt is invalid")
    return {name: receipt[name] for name in ("handle", "provider", "state")}


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


__all__ = ["install_credential_ingress"]
