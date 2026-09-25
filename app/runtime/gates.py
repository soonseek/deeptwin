"""Identity of a human-gate approval request (runtime.md §4 `awaiting_human`).

When the scheduler stops at a human gate it records one replayable ledger
command per (run, gate node, approval scope). Its identity is derived from
exactly those three values, so the approvals service can look the pending
gate up without any registry: an approval is recordable only for a gate
some run's scheduler durably asked for.

An execution-bound (v2) decision answers a narrower ask: the dispatcher's
durable request for one attempt of one execution behind that gate
(`request_execution_approval`), carrying the executing node as the ledger's
execution row names it and, when known, the digest of the attempt's exact
artifact inputs. Its identity is derived from (run, gate node, scope,
execution, attempt number) and read back through the helpers below. The ask
also carries the server-set instant it expires at (`expires_at_ms`: the
ledger's clock when it was first recorded plus a bounded time to live). It is
kept in the command's result, not its payload, so the replayable identity and
payload stay the same whenever the ask is repeated.

When the scheduler stops a visit because its attempt's decision is not an
approval (rejected, expired, superseded by an owner recovery), it records that
reason once per attempt (`refuse_execution_approval`, identity derived from the
ask's), so a later read of the run reports the same stop without re-deciding.
"""

from __future__ import annotations

import json
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


# --- the ledger's ask for one execution-bound (v2) decision ---------------------------------

EXECUTION_APPROVAL_REQUEST_COMMAND = "request_execution_approval"
EXECUTION_REQUEST_FIELDS = frozenset({
    "run_id", "node_id", "approval_scope", "execution_id", "execution_node_id", "attempt_no",
    "inputs_digest",
})
SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")


def execution_approval_request_identity(
    run_id: str, node_id: str, approval_scope: str, execution_id: str, attempt_no: int
) -> str:
    """The single command identity of the ledger's ask for one attempt's decision:
    the gate's (run, node, scope), the execution (node visit) and the attempt number.
    The executing node is not part of it: the ledger derives it from its own execution
    row, so one attempt has exactly one ask, whatever a caller names."""

    try:
        uuid_string(run_id)
        uuid_string(execution_id)
    except (DomainContractError, TypeError, ValueError):
        raise ValueError("invalid run or execution id") from None
    if type(attempt_no) is not int or attempt_no < 1:
        raise ValueError("invalid attempt number")
    return str(
        uuid5(
            NAMESPACE_URL,
            canonical_json(
                {
                    "domain": "deeptwin-execution-approval-request-v1",
                    "run_id": run_id,
                    "node_id": local_identifier(node_id, "node id"),
                    "approval_scope": local_identifier(approval_scope, "approval scope"),
                    "execution_id": execution_id,
                    "attempt_no": attempt_no,
                }
            ).decode(),
        )
    )


def _execution_request_payload(row) -> dict:
    """One held execution-approval ask, re-derived from its own payload; a row that
    does not reproduce its identity or grammar is never trusted (ValueError). The
    mapping returned adds `expires_at_ms` from the command's recorded result."""

    payload = json.loads(bytes(row["payload"]))
    if type(payload) is not dict or set(payload) != EXECUTION_REQUEST_FIELDS:
        raise ValueError("corrupt execution approval request")
    result = json.loads(bytes(row["result"]))
    expires = result.get("expires_at_ms") if type(result) is dict else None
    if type(expires) is not int or type(expires) is bool or expires < 0:
        raise ValueError("corrupt execution approval request")
    digest = payload["inputs_digest"]
    if digest is not None and (type(digest) is not str or SHA256_HEX.fullmatch(digest) is None):
        raise ValueError("corrupt execution approval request")
    local_identifier(payload["execution_node_id"], "execution node id")
    if execution_approval_request_identity(
        payload["run_id"], payload["node_id"], payload["approval_scope"],
        payload["execution_id"], payload["attempt_no"],
    ) != row["command_id"]:
        raise ValueError("corrupt execution approval request")
    return {**payload, "expires_at_ms": expires}


def execution_approval_request(
    db, vault_id: str, run_id: str, node_id: str, approval_scope: str,
    execution_id: str, attempt_no: int,
) -> dict | None:
    """The ledger's held ask for this exact attempt's decision, or None. The single
    reader shared by the ledger, the approvals service and the dispatcher."""

    try:
        command_id = execution_approval_request_identity(
            run_id, node_id, approval_scope, execution_id, attempt_no)
    except ValueError:
        return None
    row = db.execute(
        "SELECT command_id, payload, result FROM runtime_commands WHERE vault_id=? AND command_id=? AND kind=?",
        (vault_id, command_id, EXECUTION_APPROVAL_REQUEST_COMMAND),
    ).fetchone()
    return None if row is None else _execution_request_payload(row)


def execution_approval_requests(db, vault_id: str, run_id: str) -> list[dict]:
    """Every ask the ledger holds for one run, in recording order."""

    uuid_string(run_id)
    table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_commands'"
    ).fetchone()
    if table is None:
        return []
    rows = db.execute(
        "SELECT command_id, payload, result FROM runtime_commands WHERE vault_id=? AND kind=? "
        "ORDER BY created_at_ms, rowid",
        (vault_id, EXECUTION_APPROVAL_REQUEST_COMMAND),
    ).fetchall()
    held = [_execution_request_payload(row) for row in rows]
    return [item for item in held if item["run_id"] == run_id]


# --- the scheduler's recorded stop of one attempt's visit ------------------------------------

EXECUTION_APPROVAL_REFUSAL_COMMAND = "refuse_execution_approval"
# why a visit stopped at its attempt's decision: the owner rejected it, the ask (or the
# unused approval) expired, or an owner recovery superseded the decision
REFUSAL_REASONS = frozenset({"rejected", "expired", "superseded"})


def execution_approval_refusal_identity(ask_identity: str) -> str:
    """The single command identity of the recorded stop of the attempt one ask names."""

    uuid_string(ask_identity)
    return str(uuid5(NAMESPACE_URL, canonical_json({
        "domain": "deeptwin-execution-approval-refusal-v1", "request_id": ask_identity}).decode()))


def execution_approval_refusal(
    db, vault_id: str, run_id: str, node_id: str, approval_scope: str,
    execution_id: str, attempt_no: int,
) -> str | None:
    """The reason recorded when the scheduler stopped this attempt's visit, or None."""

    try:
        command_id = execution_approval_refusal_identity(execution_approval_request_identity(
            run_id, node_id, approval_scope, execution_id, attempt_no))
    except ValueError:
        return None
    row = db.execute(
        "SELECT payload FROM runtime_commands WHERE vault_id=? AND command_id=? AND kind=?",
        (vault_id, command_id, EXECUTION_APPROVAL_REFUSAL_COMMAND),
    ).fetchone()
    if row is None:
        return None
    payload = json.loads(bytes(row["payload"]))
    if type(payload) is not dict or payload.get("reason") not in REFUSAL_REASONS:
        raise ValueError("corrupt execution approval refusal")
    return payload["reason"]
