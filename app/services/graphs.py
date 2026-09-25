"""The owner's read of one stored functional graph (T037/T048).

A `graph` record holds a functional graph in the design encoding. The read admits it
through `GraphVersion.from_untrusted`, exactly as a run does, and returns the parsed
graph so the browser can draw it. A record that does not parse is refused, never shown
half-read. Nothing here edits, compiles or runs a graph.
"""

from __future__ import annotations

from functools import wraps

from ..domain.graph_schema import GraphContractError, GraphVersion
from ..domain.refs import DomainContractError, EntityRef, uuid_string
from ..domain.store import DomainStore
from .design_persistence import DesignPersistenceError, decode_design_refs
from .owner_auth import OwnerAuthError, PersistentOwnerAuthority

__all__ = ["GraphServiceError", "PersistentGraphs"]

CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "unavailable"})
MAX_VERSION = 1_000_000


class GraphServiceError(ValueError):
    def __init__(self, code="invalid_input"):
        if code not in CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (GraphServiceError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage errors must not disclose detail
            raise GraphServiceError("unavailable") from None

    return invoke


class PersistentGraphs:
    def __init__(self, domain_store, owner_authority):
        if type(domain_store) is not DomainStore:
            raise TypeError("Exact DomainStore required")
        if type(owner_authority) is not PersistentOwnerAuthority or owner_authority._domain is not domain_store:
            raise TypeError("Owner authority must share the actual domain store")
        self._domain = domain_store
        self._owner = owner_authority

    @_closed
    def read(self, request, graph_id: str, version) -> dict:
        self._owner.authenticate_bound(request.session)
        try:
            uuid_string(graph_id)
            version = int(version)
        except (TypeError, ValueError):
            raise GraphServiceError("not_found") from None
        if not 1 <= version <= MAX_VERSION:
            raise GraphServiceError("not_found")
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            row = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind='graph' AND id=? "
                             "AND version=?", (roots.genesis.id, graph_id, version)).fetchone()
            if row is None:
                raise GraphServiceError("not_found")
            record = self._domain._load(db, EntityRef("graph", graph_id, version, row["sha256"]), roots)[0]
        content = record.body.get("content")
        if type(content) is not dict or content.get("design_kind") != "functional_graph" or "design" not in content:
            raise GraphServiceError("invalid_input")
        try:
            graph = GraphVersion.from_untrusted(decode_design_refs(content["design"]))
        except (DesignPersistenceError, GraphContractError, DomainContractError, TypeError, ValueError):
            raise GraphServiceError("invalid_input") from None
        return {"graph_ref": record.ref.as_dict(), "graph": graph.as_dict()}
