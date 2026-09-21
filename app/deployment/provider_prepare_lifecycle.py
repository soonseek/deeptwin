"""Provider-only transitions and complete historical command verification."""

from hashlib import sha256

from ..domain.public_events import (
    EventEnvelope,
    _decode_cursor,
    _event_cursor_in_transaction,
)
from ..domain.refs import EntityRef, canonical_json, parse_canonical, uuid_string
from . import prepare_lifecycle as legacy
from .prepare_contracts import require
from .provider_prepare_contracts import (
    make_provider_cancellation,
    parse_provider_cancel,
    parse_provider_prepare,
)

PATH = "/api/v1/deployment/provider-requests"
NAMESPACES = {
    "prepared": "deployment-prepare-provider-v1",
    "cancelled": "deployment-cancel-provider-v1",
}


def _body(item, *, command_id=None, cursor=None):
    request, last = item["request"], item["history"][-1]
    request_id = request["request_id"]
    result = {
        "request_id": request_id,
        "request_digest": request["request_digest"],
        "kind": "extension_stage",
        "state": last["state"],
        "revision": last["revision"],
        "publication_state": item["outbox"]["request"]["state"],
        "cancellation_publication_state": item["outbox"].get("cancel", {}).get("state"),
        "source_context_sha256": request["effect_payload"]["source_context"]["sha256"],
        "preserved_inventory_sha256": request["effect_payload"][
            "preserved_inventory_sha256"
        ],
        "links": {
            "self": PATH + "/" + request_id,
            "cancel": PATH + "/" + request_id + "/cancel",
            "events": "/api/v1/events",
        },
    }
    if command_id is None:
        result["request"] = request
    else:
        result.update(command_id=command_id, event_cursor=cursor)
    require(
        len(canonical_json(result)) <= (73728 if command_id is None else 8192),
        "unavailable",
    )
    return result


def read_body(item):
    if item.get("receipt") is not None:
        from .provider_receipt_lifecycle import read_body as receipt_read
        return receipt_read(item)
    return _body(item)


def cancellation_payload(item, *, profile):
    if item.get("receipt") is not None:
        from .provider_receipt_lifecycle import cancellation_payload as receipt_cancel
        return receipt_cancel(item, profile=profile)
    return make_provider_cancellation(
        item["raw"],
        profile=profile,
        cancelled_ms=item["history"][-1]["transitioned_ms"],
    )


def transition(db, roots, profile, item, *, state, now, actor_ref, value=None):
    require(
        state in {"prepared", "cancelled", "expired"}
        and (
            not item["history"]
            if state == "prepared"
            else len(item["history"]) == 1 and item["history"][0]["state"] == "prepared"
        ),
        "unavailable",
    )
    command_id = value["command_id"] if value is not None else None
    history, event = legacy._append_transition(
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
    receipt = _body(item, command_id=command_id, cursor=cursor)
    legacy._store_command(
        db,
        profile,
        item,
        actor_ref=actor_ref,
        namespace=NAMESPACES[state],
        value=value,
        http_status=201 if state == "prepared" else 200,
        receipt=receipt,
        lifecycle_revision=history["revision"],
    )
    return receipt


def verify(db, roots, profile, item, commands):
    if item.get("receipt") is not None:
        from .provider_receipt_lifecycle import verify as receipt_verify
        return receipt_verify(db, roots, profile, item, commands)
    history, outs, row = item["history"], item["outbox"], item["row"]
    require(1 <= len(history) <= 2 and history[0]["state"] == "prepared", "unavailable")
    last = history[-1]
    require(
        last["state"] in {"prepared", "cancelled", "expired"}
        and item["head"]["revision"] == last["revision"]
        and item["head"]["lifecycle_hash"] == last["hash"]
        and not any(
            item.get(key) is not None
            for key in ("receipt", "consumption", "consumed_outbox", "installation")
        )
        and set(outs)
        == ({"request", "cancel"} if last["state"] == "cancelled" else {"request"})
        and outs["request"]["state"]
        in (
            {"pending", "published"}
            if last["state"] == "prepared"
            else {"published", "suppressed"}
        ),
        "unavailable",
    )
    for role, out in outs.items():
        payload = (
            item["raw"]
            if role == "request"
            else cancellation_payload(item, profile=profile)
        )
        require(
            out["lifecycle_revision"] == (1 if role == "request" else 2)
            and out["payload_sha256"] == sha256(payload).hexdigest()
            and out["payload_size"] == len(payload),
            "unavailable",
        )
        if out["state"] == "published":
            require(
                history[out["lifecycle_revision"] - 1]["transitioned_ms"]
                <= out["published_ms"]
                <= item["control"]["clock_floor_ms"],
                "unavailable",
            )
            if role == "request" and len(history) == 2:
                require(out["published_ms"] <= last["transitioned_ms"], "unavailable")
    expected_commands = set()
    for number, step in enumerate(history, 1):
        state, now = step["state"], step["transitioned_ms"]
        require(
            step["revision"] == number
            and row["created_ms"] <= now <= item["control"]["clock_floor_ms"],
            "unavailable",
        )
        if number == 1:
            require(
                now == row["created_ms"]
                and step["command_id"] == item["anchor"]["prepare_command_id"]
                and step["previous_revision"] is None
                and step["previous_hash"] is None,
                "unavailable",
            )
        else:
            require(
                state in {"cancelled", "expired"}
                and step["previous_revision"] == 1
                and step["previous_hash"] == history[0]["hash"]
                and (
                    now >= row["expires_ms"]
                    if state == "expired"
                    else now < row["expires_ms"]
                ),
                "unavailable",
            )
        actor = EntityRef.from_dict(parse_canonical(step["actor_ref"].encode()))
        require(
            actor == (roots.actor if state == "expired" else item["actor"]),
            "unavailable",
        )
        size = db.execute(
            "SELECT typeof(envelope),length(envelope) FROM api_event_envelopes WHERE event_id=?",
            (step["event_id"],),
        ).fetchone()
        require(
            size is not None and size[0] == "blob" and 0 < size[1] <= 8192,
            "unavailable",
        )
        event_row = db.execute(
            "SELECT * FROM api_event_envelopes WHERE event_id=?", (step["event_id"],)
        ).fetchone()
        event = EventEnvelope.from_bytes(event_row["envelope"])
        correlation = step["command_id"] if state != "expired" else event.correlation_id
        uuid_string(correlation)
        expected = EventEnvelope.create(
            event_id=step["event_id"],
            sequence=event_row["sequence"],
            **legacy.event_fields(
                roots, item["ref"], state, now, actor, correlation, revision=number
            ),
        )
        require(
            event.body_bytes == expected.body_bytes
            and event_row["vault_id"] == roots.genesis.id
            and event_row["event_type"] == expected.event_type,
            "unavailable",
        )
        if state == "expired":
            require(step["command_id"] is None, "unavailable")
            continue
        expected_commands.add(step["command_id"])
        command = commands.get(step["command_id"])
        require(command is not None, "unavailable")
        value = parse_canonical(command["input_json"].encode())
        parsed = (
            parse_provider_prepare(value)
            if state == "prepared"
            else parse_provider_cancel(
                value["request_id"],
                {k: v for k, v in value.items() if k != "request_id"},
            )
        )
        namespace = NAMESPACES[state]
        require(
            parsed == value
            and value["command_id"] == command["command_id"]
            and command["request_id"] == item["ref"].id
            and command["actor_ref"] == step["actor_ref"]
            and command["lifecycle_revision"] == number
            and command["namespace"] == namespace
            and command["http_status"] == (201 if state == "prepared" else 200)
            and command["input_digest"]
            == legacy.input_digest(profile, actor.as_dict(), namespace, value),
            "unavailable",
        )
        if state == "prepared":
            require(
                value["candidate_id"] == item["anchor"]["candidate_ref"]["id"]
                and value["slot_id"] == row["slot_id"]
                and value["source_context_sha256"]
                == item["context"]["row"]["context_sha256"]
                and value["expires_in_seconds"] * 1000
                == row["expires_ms"] - row["created_ms"],
                "unavailable",
            )
        else:
            require(
                value["request_id"] == item["ref"].id
                and value["request_digest"] == row["request_digest"]
                and value["expected_revision"] == 1,
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
            else {"request": outs["request"], "cancel": {"state": "pending"}},
        }
        require(
            receipt
            == _body(
                frozen, command_id=command["command_id"], cursor=receipt["event_cursor"]
            ),
            "unavailable",
        )
    require(
        {
            key
            for key, command in commands.items()
            if command["request_id"] == item["ref"].id
        }
        == expected_commands,
        "unavailable",
    )
