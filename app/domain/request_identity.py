"""Shared request capabilities and transaction authentication, independent of HTTP."""

from dataclasses import dataclass, field

from .refs import MAX_INTEGER, uuid_string
from .schemas import Actor


class SessionBoundaryError(PermissionError):
    """Safe local-boundary refusal without secret or capability detail."""


class RequestDenied(SessionBoundaryError):
    pass


def authenticate_in_transaction(authenticate, session, db):
    """Persistent web authority must validate inside the caller's exact writer.

    Historical preview/unit authorities retain their existing in-memory contract.
    This does not let a supplied actor or wrapper stand in for persistent authority.
    """
    from ..services.owner_auth import PersistentOwnerAuthority

    owner = getattr(authenticate, "__self__", None)
    if isinstance(owner, PersistentOwnerAuthority):
        if (
            type(owner) is not PersistentOwnerAuthority
            or getattr(authenticate, "__func__", None) is not PersistentOwnerAuthority.authenticate_bound
        ):
            raise RequestDenied("Persistent session authority binding changed")
        return owner.authenticate_bound(session, db=db)
    return authenticate(session)


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    session_id: str
    actor: Actor
    expires_at: int

    def __post_init__(self):
        uuid_string(self.session_id)
        if type(self.actor) is not Actor or self.actor.kind != "human":
            raise ValueError("A local session requires a human actor")
        if type(self.expires_at) is not int or not 0 < self.expires_at <= MAX_INTEGER:
            raise ValueError("Session expiry must be bounded")


@dataclass(frozen=True, slots=True)
class AuthenticatedRequest:
    method: str
    host: str
    origin: str | None
    session: AuthenticatedSession
    csrf_verified: bool

    @property
    def is_read(self):
        return self.method in {"GET", "HEAD"}


@dataclass(frozen=True, slots=True)
class ServiceClientRead:
    """One admitted TLS service-client bearer read of one declared route.

    It carries no credential. ``verify`` re-checks the durable grant (state, credential
    revision, expiry, recovery epoch, network profile and this exact scope) and returns
    the service-client actor, so a revoke committed during the read withholds its result.
    It is a read-only capability: no mutation path accepts it.
    """

    method: str
    client_id: str
    credential_revision: int
    scope: str
    route_id: str
    _verify: object = field(repr=False, compare=False)

    def __post_init__(self):
        uuid_string(self.client_id)
        if (self.method not in {"GET", "HEAD"} or type(self.credential_revision) is not int
                or not 1 <= self.credential_revision <= MAX_INTEGER
                or type(self.scope) is not str or type(self.route_id) is not str
                or not callable(self._verify)):
            raise ValueError("A service-client read is invalid")

    @property
    def is_read(self):
        return True

    def verify(self):
        try:
            actor = self._verify()
        except Exception:  # noqa: BLE001 - one uniform denial at the credential boundary
            raise RequestDenied("Service client credential is no longer current") from None
        if type(actor) is not Actor or actor.kind != "service_client" or actor.id != self.client_id:
            raise RequestDenied("Service client credential is no longer current")
        return actor
