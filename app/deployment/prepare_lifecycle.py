"""Closed lifecycle transitions and immutable command/read projections."""

from hashlib import sha256
from uuid import uuid4

from ..domain.public_events import (
    EventEnvelope,
    _append_event_in_transaction,
    _decode_cursor,
    _event_cursor_in_transaction,
)
from ..domain.refs import (
    EntityRef,
    ObjectRef,
    canonical_json,
    parse_canonical,
    uuid_string,
)
from . import prepare_storage as storage
from .prepare_contracts import (
    cancellation,
    links,
    parse_cancel,
    parse_prepare,
    require,
    stamp,
)
from .prepare_v2_contracts import cancellation_v2, parse_cancel_v2, parse_receipt_import
from .prepare_v3_contracts import parse_consume

NAMESPACES = {"prepared": "deployment-prepare-v1", "cancelled": "deployment-cancel-v1"}


def instant(milliseconds):
    return stamp(milliseconds)[:-1] + "000Z"


def input_digest(profile, actor_ref, namespace, value):
    return sha256(
        canonical_json(
            {
                "namespace": namespace,
                "instance_id": profile.instance_id,
                "origin_digest": profile.digest,
                "actor_ref": actor_ref,
                "input": value,
            }
        )
    ).hexdigest()


def body(item, *, command_id=None, cursor=None):
    request = item["request"]
    result = {
        "request_id": request["request_id"],
        "request_digest": request["request_digest"],
        "kind": "extension_stage",
        "state": item["history"][-1]["state"],
        "revision": item["history"][-1]["revision"],
        "publication_state": item["outbox"]["request"]["state"],
        "cancellation_publication_state": item["outbox"].get("cancel", {}).get("state"),
        "links": links(request["request_id"]),
    }
    if command_id is None:
        result["request"] = request
    else:
        result.update(command_id=command_id, event_cursor=cursor)
    return result


def read_body(item):
    receipt = item.get("receipt")
    accepted = item["history"][-1]["state"] == "accepted"
    return {
        **body(item),
        "receipt": None
        if receipt is None
        else {
            "receipt_digest": receipt["digest"],
            "outcome": receipt["value"]["outcome"],
            # the accepted3 head consumed the success; the stored revision-2
            # import reply keeps its frozen pending disposition
            "disposition": "consumed_success"
            if accepted
            else disposition(receipt["value"]["outcome"]),
            "import_revision": 2,
        },
        "consumption_publication_state": None
        if item.get("consumed_outbox") is None
        else item["consumed_outbox"]["state"],
        "installation": installation_summary(item["installation"])
        if item.get("installation") is not None
        else None,
    }


def disposition(outcome):
    require(outcome in {"succeeded", "failed", "unknown"}, "unavailable")
    return (
        "pending_postconditions" if outcome == "succeeded" else "consumed_non_success"
    )


def cancellation_payload(item, *, profile):
    if item.get("anchor", {}).get("schema_version") == "deployment-provider-request-anchor-v2":
        from .provider_prepare_lifecycle import cancellation_payload as provider_payload
        return provider_payload(item, profile=profile)
    latest = item["history"][-1]
    emitter = cancellation if latest["revision"] == 2 else cancellation_v2
    return emitter(item["request"], latest["transitioned_ms"], profile=profile)


def consumed_payload(item):
    content = item["consumption"]["anchor"]
    return canonical_json(
        {
            "schema": "deployment-consumption-v1",
            "domain": "deeptwin-deployment-consumption-v1",
            "consumption_id": item["consumption"]["ref"].id,
            "request_id": item["ref"].id,
            "request_digest": item["request"]["request_digest"],
            "receipt_digest": item["receipt"]["digest"],
            "winning_lifecycle_revision": 2,
            "consumed_at": content["consumed_at"],
            "outcome": content["outcome"],
        }
    )


def event_fields(
    roots,
    ref,
    state,
    milliseconds,
    actor_ref,
    correlation_id,
    *,
    revision=None,
    receipt_outcome=None,
):
    receipt_state = state in {"receipt_pending", "rejected"}
    if receipt_state:
        require(
            (state == "receipt_pending" and receipt_outcome == "succeeded")
            or (state == "rejected" and receipt_outcome in {"failed", "unknown"}),
            "unavailable",
        )
    if state == "accepted":
        # journal v3 §6: the acceptance is always the third revision
        require(revision == 3 and receipt_outcome is None, "unavailable")
    return {
        "vault_id": roots.genesis.id,
        "recorded_at_utc": instant(milliseconds),
        "observed_at_utc": instant(milliseconds),
        "actor_kind": "system" if state == "expired" else "human",
        "actor_ref": actor_ref,
        "event_type": "deployment.receipt_committed"
        if receipt_state
        else "deployment.request_" + state,
        "object_refs": (ObjectRef(ref.kind, ref.id, ref.version, ref.sha256),),
        "correlation_id": correlation_id,
        "causation_id": None,
        "status": (
            {"succeeded": "pending", "failed": "failed", "unknown": "unknown"}[
                receipt_outcome
            ]
            if receipt_state
            else {
                "prepared": "pending",
                "cancelled": "cancelled",
                "expired": "blocked",
                "accepted": "succeeded",
            }[state]
        ),
        "error_code": "stale_state"
        if state == "expired"
        else "outcome_unknown"
        if receipt_outcome == "unknown"
        else None,
        "public_metadata": {
            "revision": revision
            if revision is not None
            else 1
            if state == "prepared"
            else 2
        },
        "private_evidence_refs": (),
        "retention_class": "core",
        "policy_ref": roots.access_policy,
    }


def outbox(db, item, role, payload):
    return storage.insert(
        db,
        "outbox",
        {
            "request_id": item["request"]["request_id"],
            "role": role,
            "lifecycle_revision": 1
            if role == "request"
            else item["history"][-1]["revision"],
            "payload_sha256": sha256(payload).hexdigest(),
            "payload_size": len(payload),
            "state": "pending",
            "published_ms": None,
            "revision": 1,
        },
    )


def _append_transition(
    db,
    roots,
    profile,
    item,
    *,
    state,
    now,
    actor_ref,
    command_id=None,
    receipt_outcome=None,
):
    previous = item["history"][-1] if item["history"] else None
    require(
        (state == "prepared" and previous is None)
        or (
            state in {"cancelled", "expired", "receipt_pending", "rejected"}
            and previous is not None
            and previous["state"] == "prepared"
        )
        or (
            state in {"cancelled", "expired", "accepted"}
            and previous is not None
            and previous["state"] == "receipt_pending"
        ),
        "unavailable",
    )
    require((state == "expired") == (command_id is None), "unavailable")
    revision = 1 if previous is None else previous["revision"] + 1
    event = _append_event_in_transaction(
        db,
        **event_fields(
            roots,
            item["ref"],
            state,
            now,
            actor_ref,
            command_id or str(uuid4()),
            revision=revision,
            receipt_outcome=receipt_outcome,
        ),
    )
    history = storage.insert(
        db,
        "lifecycle",
        {
            "request_id": item["request"]["request_id"],
            "revision": revision,
            "previous_revision": None if previous is None else previous["revision"],
            "previous_hash": None if previous is None else previous["hash"],
            "state": state,
            "transitioned_ms": now,
            "actor_ref": storage.encoded(actor_ref.as_dict()),
            "command_id": command_id,
            "event_id": event.event_id,
        },
    )
    item["history"].append(history)
    if previous is None:
        item["head"] = storage.insert(
            db,
            "heads",
            {
                "request_id": item["request"]["request_id"],
                "revision": 1,
                "lifecycle_hash": history["hash"],
            },
        )
        item["outbox"]["request"] = outbox(db, item, "request", item["raw"])
    else:
        item["head"] = storage.advance(
            db, "heads", item["head"], {"lifecycle_hash": history["hash"]}
        )
        prior = item["outbox"]["request"]
        if prior["state"] == "pending":
            item["outbox"]["request"] = storage.advance(
                db, "outbox", prior, {"state": "suppressed", "published_ms": None}
            )
        if state == "cancelled":
            item["outbox"]["cancel"] = outbox(
                db, item, "cancel", cancellation_payload(item, profile=profile)
            )
    return history, event


def transition(db, roots, profile, item, *, state, now, actor_ref, value=None):
    require(state in {"prepared", "cancelled", "expired"}, "unavailable")
    command_id = value["command_id"] if value is not None else None
    history, event = _append_transition(
        db,
        roots,
        profile,
        item,
        state=state,
        now=now,
        actor_ref=actor_ref,
        command_id=command_id,
    )
    if command_id is None:
        return None
    cursor = _event_cursor_in_transaction(
        db, vault_id=roots.genesis.id, sequence=event.sequence, event_types=()
    )
    receipt = body(item, command_id=command_id, cursor=cursor)
    namespace = (
        "deployment-cancel-v2" if history["revision"] == 3 else NAMESPACES[state]
    )
    _store_command(
        db,
        profile,
        item,
        actor_ref=actor_ref,
        namespace=namespace,
        value=value,
        http_status=201 if state == "prepared" else 200,
        receipt=receipt,
        lifecycle_revision=history["revision"],
    )
    return receipt


def _store_command(
    db,
    profile,
    item,
    *,
    actor_ref,
    namespace,
    value,
    http_status,
    receipt,
    lifecycle_revision,
):
    storage.insert(
        db,
        "commands",
        {
            "command_id": value["command_id"],
            "namespace": namespace,
            "request_id": item["request"]["request_id"],
            "actor_ref": storage.encoded(actor_ref.as_dict()),
            "input_json": storage.encoded(value),
            "input_digest": input_digest(
                profile, actor_ref.as_dict(), namespace, value
            ),
            "http_status": http_status,
            "receipt_json": storage.encoded(receipt),
            "lifecycle_revision": lifecycle_revision,
        },
    )


def commit_receipt_transition(
    db, roots, profile, item, *, now, actor_ref, value, receipt_outcome
):
    state = "receipt_pending" if receipt_outcome == "succeeded" else "rejected"
    history, event = _append_transition(
        db,
        roots,
        profile,
        item,
        state=state,
        now=now,
        actor_ref=actor_ref,
        command_id=value["command_id"],
        receipt_outcome=receipt_outcome,
    )
    receipt = {
        "command_id": value["command_id"],
        "request_id": item["ref"].id,
        "receipt_digest": value["receipt_digest"],
        "outcome": receipt_outcome,
        "disposition": disposition(receipt_outcome),
        "revision": history["revision"],
        "event_cursor": _event_cursor_in_transaction(
            db, vault_id=roots.genesis.id, sequence=event.sequence, event_types=()
        ),
    }
    _store_command(
        db,
        profile,
        item,
        actor_ref=actor_ref,
        namespace="deployment-receipt-import-v1",
        value=value,
        http_status=200,
        receipt=receipt,
        lifecycle_revision=2,
    )
    return receipt, event


def installation_summary(installation):
    """The v3 installation summary carried by the consume reply and the read body."""
    ref = installation["ref"]
    return {
        "installation_id": ref.id,
        "extension_id": installation["anchor"]["extension_id"],
        "installation_digest": ref.sha256,
        "revision": 1,
    }


def commit_acceptance_transition(
    db, roots, profile, item, *, now, actor_ref, value, installation
):
    """receipt_pending2 → accepted3 with the frozen consume reply and command
    (journal v3 §5/§6); the caller has already put the installation anchor."""
    history, event = _append_transition(
        db,
        roots,
        profile,
        item,
        state="accepted",
        now=now,
        actor_ref=actor_ref,
        command_id=value["command_id"],
    )
    reply = {
        "command_id": value["command_id"],
        "request_id": item["ref"].id,
        "receipt_digest": value["receipt_digest"],
        "outcome": "succeeded",
        "disposition": "consumed_success",
        "revision": history["revision"],
        "installation": installation_summary(installation),
        "event_cursor": _event_cursor_in_transaction(
            db, vault_id=roots.genesis.id, sequence=event.sequence, event_types=()
        ),
    }
    _store_command(
        db,
        profile,
        item,
        actor_ref=actor_ref,
        namespace="deployment-consume-v1",
        value=value,
        http_status=200,
        receipt=reply,
        lifecycle_revision=3,
    )
    return reply, event


def staged_event_fields(roots, installation_ref, milliseconds, actor_ref, *,
                        correlation_id, causation_id):
    """The `extension.staged` event of the installation head change (journal
    v3 §6): the installation ObjectRef, the consume command as correlation,
    the acceptance event as causation, the fixed stage arm's kind and tier."""
    from ..extensions.port_contracts import PORT_CONTRACTS

    # the candidate manifest's admitted tuple: `stage_for_candidate` pins every
    # retained stage request to exactly this port contract's kind and tier
    port = PORT_CONTRACTS["tool-port-v1"]
    return {
        "vault_id": roots.genesis.id,
        "recorded_at_utc": instant(milliseconds),
        "observed_at_utc": instant(milliseconds),
        "actor_kind": "human",
        "actor_ref": actor_ref,
        "event_type": "extension.staged",
        "object_refs": (
            ObjectRef(
                installation_ref.kind,
                installation_ref.id,
                installation_ref.version,
                installation_ref.sha256,
            ),
        ),
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "status": "succeeded",
        "error_code": None,
        "public_metadata": {
            "extension_kind": port.extension_kind,
            "trust_tier": port.trust_tier,
            "revision": 1,
        },
        "private_evidence_refs": (),
        "retention_class": "core",
        "policy_ref": roots.access_policy,
    }


def append_staged_event(db, roots, item, *, now, actor_ref, installation_ref,
                        correlation_id, causation_id):
    return _append_event_in_transaction(
        db,
        **staged_event_fields(
            roots,
            installation_ref,
            now,
            actor_ref,
            correlation_id=correlation_id,
            causation_id=causation_id,
        ),
    )


def verify(db, roots, profile, item, commands):
    if item["anchor"]["schema_version"] == "deployment-provider-request-anchor-v2":
        from .provider_prepare_lifecycle import verify as verify_provider
        return verify_provider(db, roots, profile, item, commands)
    history, outboxes = item["history"], item["outbox"]
    row, ref = item["row"], item["ref"]
    require(1 <= len(history) <= 3 and history[0]["state"] == "prepared", "unavailable")
    latest = history[-1]
    require(
        item["head"]["revision"] == latest["revision"]
        and item["head"]["lifecycle_hash"] == latest["hash"],
        "unavailable",
    )
    require(
        set(outboxes)
        == ({"request", "cancel"} if latest["state"] == "cancelled" else {"request"}),
        "unavailable",
    )
    require(
        outboxes["request"]["state"]
        in (
            {"pending", "published"}
            if latest["state"] == "prepared"
            else {"published", "suppressed"}
        ),
        "unavailable",
    )
    for role, out in outboxes.items():
        payload = (
            item["raw"]
            if role == "request"
            else cancellation_payload(item, profile=profile)
        )
        require(
            out["lifecycle_revision"]
            == (1 if role == "request" else latest["revision"])
            and out["payload_sha256"] == sha256(payload).hexdigest()
            and out["payload_size"] == len(payload),
            "unavailable",
        )
        if out["state"] == "published":
            require(
                out["published_ms"]
                >= history[out["lifecycle_revision"] - 1]["transitioned_ms"]
                and out["published_ms"] <= item["control"]["clock_floor_ms"],
                "unavailable",
            )
            if role == "request":
                require(
                    len(history) == 1
                    or out["published_ms"] <= history[1]["transitioned_ms"],
                    "unavailable",
                )
    expected_commands = set()
    for number, transition_row in enumerate(history, 1):
        state = transition_row["state"]
        now = transition_row["transitioned_ms"]
        require(
            transition_row["revision"] == number
            and row["created_ms"] <= now <= item["control"]["clock_floor_ms"],
            "unavailable",
        )
        if number == 1:
            require(
                now == row["created_ms"]
                and transition_row["command_id"]
                == item["anchor"]["prepare_command_id"],
                "unavailable",
            )
        else:
            require(
                transition_row["previous_hash"] == history[number - 2]["hash"]
                and transition_row["previous_revision"] == number - 1
                and now >= history[number - 2]["transitioned_ms"]
                and (
                    (
                        number == 2
                        and state
                        in {"cancelled", "expired", "receipt_pending", "rejected"}
                    )
                    or (
                        number == 3
                        and history[1]["state"] == "receipt_pending"
                        and (
                            state in {"cancelled", "expired"}
                            or (
                                state == "accepted"
                                and item["receipt"]["value"]["outcome"] == "succeeded"
                            )
                        )
                    )
                )
                and (
                    now >= row["expires_ms"]
                    if state == "expired"
                    else now < row["expires_ms"]
                ),
                "unavailable",
            )
        actor = EntityRef.from_dict(
            parse_canonical(transition_row["actor_ref"].encode())
        )
        require(
            actor == (roots.actor if state == "expired" else item["actor"]),
            "unavailable",
        )
        event_size = db.execute(
            "SELECT typeof(envelope),length(envelope) FROM api_event_envelopes WHERE event_id=? LIMIT 2",
            (transition_row["event_id"],),
        ).fetchone()
        require(
            event_size is not None
            and event_size[0] == "blob"
            and 0 < event_size[1] <= 8192,
            "unavailable",
        )
        event_row = db.execute(
            "SELECT * FROM api_event_envelopes WHERE event_id=? LIMIT 2",
            (transition_row["event_id"],),
        ).fetchone()
        event = EventEnvelope.from_bytes(event_row["envelope"])
        correlation = (
            transition_row["command_id"] if state != "expired" else event.correlation_id
        )
        uuid_string(correlation)
        expected = EventEnvelope.create(
            event_id=transition_row["event_id"],
            sequence=event_row["sequence"],
            **event_fields(
                roots,
                ref,
                state,
                now,
                actor,
                correlation,
                revision=number,
                receipt_outcome=item["receipt"]["value"]["outcome"]
                if state in {"receipt_pending", "rejected"}
                else None,
            ),
        )
        require(
            event.body_bytes == expected.body_bytes
            and event_row["vault_id"] == roots.genesis.id
            and event_row["event_type"] == expected.event_type,
            "unavailable",
        )
        if state == "expired":
            continue
        expected_commands.add(transition_row["command_id"])
        command = commands.get(transition_row["command_id"])
        require(command is not None, "unavailable")
        value = parse_canonical(command["input_json"].encode())
        imported = state in {"receipt_pending", "rejected"}
        accepted = state == "accepted"
        namespace = (
            "deployment-receipt-import-v1"
            if imported
            else "deployment-consume-v1"
            if accepted
            else "deployment-cancel-v2"
            if number == 3
            else NAMESPACES[state]
        )
        route_parser = (
            parse_receipt_import
            if imported
            else parse_consume
            if accepted
            else parse_cancel_v2
            if number == 3
            else parse_cancel
        )
        parsed = (
            parse_prepare(value)
            if state == "prepared"
            else route_parser(
                value["request_id"],
                {k: v for k, v in value.items() if k != "request_id"},
            )
        )
        require(
            parsed == value
            and command["request_id"] == ref.id
            and command["actor_ref"] == transition_row["actor_ref"]
            and command["lifecycle_revision"] == number
            and command["namespace"] == namespace
            and command["http_status"] == (201 if state == "prepared" else 200)
            and value["command_id"] == command["command_id"]
            and command["input_digest"]
            == input_digest(profile, actor.as_dict(), namespace, value),
            "unavailable",
        )
        if state == "prepared":
            require(
                value["candidate_id"] == item["anchor"]["candidate_ref"]["id"]
                and value["slot_id"] == row["slot_id"]
                and value["expires_in_seconds"] * 1000
                == row["expires_ms"] - row["created_ms"],
                "unavailable",
            )
        else:
            require(
                value["request_id"] == ref.id
                and value["request_digest"] == row["request_digest"]
                and value["expected_revision"] == number - 1,
                "unavailable",
            )
        receipt = parse_canonical(command["receipt_json"].encode())
        cursor = _decode_cursor(receipt["event_cursor"])
        current = _decode_cursor(
            _event_cursor_in_transaction(
                db, vault_id=roots.genesis.id, sequence=event.sequence, event_types=()
            )
        )
        require(
            cursor["generation"] <= current["generation"]
            and {**cursor, "generation": current["generation"]} == current,
            "unavailable",
        )
        frozen = {
            **item,
            "history": history[:number],
            "outbox": {"request": {"state": "pending"}}
            if number == 1
            else {"request": outboxes["request"], "cancel": {"state": "pending"}},
        }
        expected_reply = (
            {
                "command_id": command["command_id"],
                "request_id": ref.id,
                "receipt_digest": item["receipt"]["digest"],
                "outcome": item["receipt"]["value"]["outcome"],
                "disposition": disposition(item["receipt"]["value"]["outcome"]),
                "revision": 2,
                "event_cursor": receipt["event_cursor"],
            }
            if imported
            else {
                "command_id": command["command_id"],
                "request_id": ref.id,
                "receipt_digest": item["receipt"]["digest"],
                "outcome": "succeeded",
                "disposition": "consumed_success",
                "revision": 3,
                "installation": installation_summary(item["installation"]),
                "event_cursor": receipt["event_cursor"],
            }
            if accepted
            else body(
                frozen, command_id=command["command_id"], cursor=receipt["event_cursor"]
            )
        )
        require(receipt == expected_reply, "unavailable")
        if imported or accepted:
            require(value["receipt_digest"] == item["receipt"]["digest"], "unavailable")
    require(
        {key for key, value in commands.items() if value["request_id"] == ref.id}
        == expected_commands,
        "unavailable",
    )
