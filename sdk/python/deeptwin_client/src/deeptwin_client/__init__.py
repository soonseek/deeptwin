"""DeepTwin HTTPS service client (T087, ADR-014).

A dependency-free client for the DeepTwin ``/api/v1`` surface as a scoped service
client: every call is HTTPS with certificate and host verification and carries exactly
one ``Authorization: Bearer`` credential. There is no plaintext HTTP mode, no cookie
jar, no browser-session fallback and no redirect following. The client never imports
the DeepTwin core; the server stays the only authority for scope, revision, permission,
budget and event semantics.
"""

from .client import (
    API_PREFIX,
    ApiError,
    ClientConfigurationError,
    DeepTwinClient,
    Response,
    TransportError,
)

__version__ = "0.1.0"

__all__ = (
    "API_PREFIX",
    "ApiError",
    "ClientConfigurationError",
    "DeepTwinClient",
    "Response",
    "TransportError",
    "__version__",
)
