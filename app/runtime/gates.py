"""Identity of a human-gate approval request (runtime.md §4 `awaiting_human`).

When the scheduler stops at a human gate it records one replayable ledger
command per (run, gate node, approval scope). Its identity is derived from
exactly those three values, so the approvals service can look the pending
gate up without any registry: an approval is recordable only for a gate
some run's scheduler durably asked for.
"""

from __future__ import annotations

import re
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import DomainContractError, canonical_json, uuid_string

LOCAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
GATE_REQUEST_COMMAND = "request_gate_approval"


def tool_approval_scope(tool_id, version) -> str:
    """The gate scope an owner's approval of one tool call names — `tool-` and the
    uuid5 of the canonical (tool id, version) pair: delimiter-proof, fixed-length and
    lowercase, so every id and version the execute grammar admits fits the gate scope
    grammar, the graph schema's local identifiers and the authority's scope grammar. The
    compiled graph requires it on a node bound to an external-family tool, a human gate
    supplies it through an approval edge, the scheduler asks the ledger for it under the
    gate's id, the approvals service records the owner's decision against it, and the
    extension transport verifies the named approval is that decision before the send."""

    if type(tool_id) is not str or type(version) is not str:
        raise ValueError("a tool approval scope names a tool id and a version")
    pair = canonical_json({"tool_id": tool_id, "version": version}).decode()
    scope = "tool-" + str(uuid5(NAMESPACE_URL, f"deeptwin:tool-approval-scope:{pair}"))
    if LOCAL.fullmatch(scope) is None:  # closed by construction; the grammar is pinned by test
        raise ValueError("the tool and version cannot be named as an approval scope")
    return scope


def local_identifier(value, label: str) -> str:
    if type(value) is not str or LOCAL.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")
    return value


def gate_request_recorded(
    db, vault_id: str, run_id: str, node_id: str, approval_scope: str
) -> bool:
    """True only when the ledger holds this exact gate request command.

    The single reader of the request row, shared by the ledger and the
    approvals service (which reads the ledger's table through the same
    SQLite database), so the two can never drift apart.
    """

    try:
        command_id = gate_request_identity(run_id, node_id, approval_scope)
    except ValueError:
        return False
    row = db.execute(
        "SELECT 1 FROM runtime_commands WHERE vault_id=? AND command_id=? AND kind=?",
        (vault_id, command_id, GATE_REQUEST_COMMAND),
    ).fetchone()
    return row is not None


def gate_request_identity(run_id: str, node_id: str, approval_scope: str) -> str:
    """The single command identity of one gate's approval request."""

    try:
        uuid_string(run_id)
    except (DomainContractError, TypeError, ValueError):
        raise ValueError("invalid run id") from None
    # canonical JSON keeps the components delimiter-proof ("a:b","c" ≠ "a","b:c")
    return str(
        uuid5(
            NAMESPACE_URL,
            canonical_json(
                {
                    "domain": "deeptwin-gate-request-v1",
                    "run_id": run_id,
                    "node_id": local_identifier(node_id, "node id"),
                    "approval_scope": local_identifier(
                        approval_scope, "approval scope"
                    ),
                }
            ).decode(),
        )
    )
