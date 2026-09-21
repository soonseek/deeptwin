"""Receipt-bearing provider history and frozen responses on the existing journal."""

from hashlib import sha256
from ..domain.refs import EntityRef, canonical_json, parse_canonical
from ..domain.public_events import (
    EventEnvelope,
    _decode_cursor,
    _event_cursor_in_transaction,
)
from . import prepare_lifecycle as old
from .prepare_contracts import require
from .provider_receipt_contracts import (
    parse_provider_receipt_import,
    parse_provider_consume,
    parse_provider_pending_cancel,
    make_provider_pending_cancellation,
)
from .provider_receipt_schema_exports import (
    provider_command_receipt_v2_schema,
    provider_request_read_v2_schema,
)
from .receipt_contracts import _validate

NAMESPACES = {
    "receipt_pending": "deployment-receipt-import-provider-v1",
    "rejected": "deployment-receipt-import-provider-v1",
    "accepted": "deployment-consume-provider-v1",
    "cancelled": "deployment-cancel-provider-v2",
}


def _body(item, *, command_id=None, cursor=None):
    from .provider_prepare_lifecycle import PATH

    request, last, receipt = item["request"], item["history"][-1], item["receipt"]
    path = PATH + "/" + item["ref"].id
    result = {
        "request_id": item["ref"].id,
        "request_digest": request["request_digest"],
        "kind": "extension_stage",
        "state": last["state"],
        "revision": last["revision"],
        "publication_state": item["outbox"]["request"]["state"],
        "cancellation_publication_state": item["outbox"].get("cancel", {}).get("state"),
        "consumption_publication_state": (item.get("consumed_outbox") or {}).get(
            "state"
        ),
        "source_context_sha256": request["effect_payload"]["source_context"]["sha256"],
        "preserved_inventory_sha256": request["effect_payload"][
            "preserved_inventory_sha256"
        ],
        "receipt": {
            "receipt_ref": receipt["ref"].as_dict(),
            "receipt_digest": receipt["digest"],
            "outcome": receipt["value"]["outcome"],
            "import_revision": 2,
        },
        "consumption_ref": item["consumption"]["ref"].as_dict()
        if item.get("consumption")
        else None,
        "installation_ref": item["installation"]["ref"].as_dict()
        if item.get("installation")
        else None,
        "links": {
            "self": path,
            "cancel": path + "/cancel",
            "receipts": path + "/receipts",
            "consume": path + "/consume",
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
    _validate(
        result,
        provider_request_read_v2_schema()
        if command_id is None
        else provider_command_receipt_v2_schema(),
    )
    return result


def read_body(item):
    return _body(item)


def cancellation_payload(item, *, profile):
    return make_provider_pending_cancellation(
        request_bytes=item["raw"],
        receipt_bytes=item["receipt"]["raw"],
        profile=profile,
        cancelled_ms=item["history"][-1]["transitioned_ms"],
    )


def consumed_payload(item):
    request, content = item["request"], item["consumption"]["anchor"]
    return canonical_json(
        {
            "schema": "deployment-provider-consumption-v1",
            "domain": "deeptwin-deployment-provider-consumption-v1",
            "consumption_id": item["consumption"]["ref"].id,
            **{
                k: request[k]
                for k in (
                    "request_id",
                    "request_digest",
                    "instance_id",
                    "origin_profile_digest",
                )
            },
            "receipt_digest": item["receipt"]["digest"],
            "source_context_sha256": request["effect_payload"]["source_context"][
                "sha256"
            ],
            "preserved_inventory_sha256": request["effect_payload"][
                "preserved_inventory_sha256"
            ],
            "winning_lifecycle_revision": 2,
            "consumed_at": content["consumed_at"],
            "outcome": content["outcome"],
        }
    )


def _freeze_command(db, roots, profile, item, *, actor_ref, value, event):
    cursor = _event_cursor_in_transaction(
        db, vault_id=roots.genesis.id, sequence=event.sequence, event_types=()
    )
    result = _body(item, command_id=value["command_id"], cursor=cursor)
    last = item["history"][-1]
    old._store_command(
        db,
        profile,
        item,
        actor_ref=actor_ref,
        namespace=NAMESPACES[last["state"]],
        value=value,
        http_status=200,
        receipt=result,
        lifecycle_revision=last["revision"],
    )
    return result


def transition(
    db, roots, profile, item, *, state, now, actor_ref, value=None, receipt_outcome=None
):
    _, event = old._append_transition(
        db,
        roots,
        profile,
        item,
        state=state,
        now=now,
        actor_ref=actor_ref,
        command_id=None if value is None else value["command_id"],
        receipt_outcome=receipt_outcome,
    )
    return (
        None
        if value is None
        else _freeze_command(
            db, roots, profile, item, actor_ref=actor_ref, value=value, event=event
        )
    )


def staged_event_fields(
    roots, installation_ref, now, actor_ref, *, correlation_id, causation_id
):
    from ..domain.public_events import ObjectRef

    return {
        "vault_id": roots.genesis.id,
        "recorded_at_utc": old.instant(now),
        "observed_at_utc": old.instant(now),
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
            "extension_kind": "provider",
            "trust_tier": "runtime_worker",
            "revision": 1,
        },
        "private_evidence_refs": (),
        "retention_class": "core",
        "policy_ref": roots.access_policy,
    }


def verify(db, roots, profile, item, commands):
    from . import provider_prepare_lifecycle as prepared

    history, receipt, outs = item["history"], item["receipt"], item["outbox"]
    require(
        len(history) in (2, 3)
        and history[1]["state"]
        == (
            "receipt_pending"
            if receipt["value"]["outcome"] == "succeeded"
            else "rejected"
        ),
        "unavailable",
    )
    last = history[-1]
    require(
        len(history) == 2
        or history[1]["state"] == "receipt_pending"
        and last["state"] in {"cancelled", "expired", "accepted"},
        "unavailable",
    )
    require(
        item["head"]["revision"] == last["revision"]
        and item["head"]["lifecycle_hash"] == last["hash"],
        "unavailable",
    )
    require(
        outs["request"]["state"] in {"published", "suppressed"}
        and set(outs)
        == ({"request", "cancel"} if last["state"] == "cancelled" else {"request"}),
        "unavailable",
    )
    prefix = {
        **item,
        "history": history[:1],
        "head": {"revision": 1, "lifecycle_hash": history[0]["hash"]},
        "outbox": {
            "request": {
                **outs["request"],
                "state": "pending",
                "published_ms": None,
                "revision": 1,
            }
        },
        "receipt": None,
        "consumption": None,
        "consumed_outbox": None,
        "installation": None,
    }
    prepared.verify(
        db,
        roots,
        profile,
        prefix,
        {history[0]["command_id"]: commands[history[0]["command_id"]]},
    )
    for role, out in outs.items():
        raw = (
            item["raw"]
            if role == "request"
            else cancellation_payload(item, profile=profile)
        )
        require(
            out["lifecycle_revision"] == (1 if role == "request" else 3)
            and out["payload_sha256"] == sha256(raw).hexdigest()
            and out["payload_size"] == len(raw),
            "unavailable",
        )
        if out["state"] == "published":
            require(
                history[out["lifecycle_revision"] - 1]["transitioned_ms"]
                <= out["published_ms"]
                <= item["control"]["clock_floor_ms"],
                "unavailable",
            )
            if role == "request":
                require(
                    out["published_ms"] <= history[1]["transitioned_ms"], "unavailable"
                )
    ids = {history[0]["command_id"]}
    for index, step in enumerate(history[1:], 2):
        state, now = step["state"], step["transitioned_ms"]
        prior = history[index - 2]
        require(
            step["revision"] == index
            and step["previous_revision"] == index - 1
            and step["previous_hash"] == prior["hash"]
            and prior["transitioned_ms"] <= now <= item["control"]["clock_floor_ms"]
            and (
                now >= item["row"]["expires_ms"]
                if state == "expired"
                else now < item["row"]["expires_ms"]
            ),
            "unavailable",
        )
        actor = EntityRef.from_dict(parse_canonical(step["actor_ref"].encode()))
        require(
            actor == (roots.actor if state == "expired" else item["actor"]),
            "unavailable",
        )
        event_row = db.execute(
            "SELECT * FROM api_event_envelopes WHERE event_id=?", (step["event_id"],)
        ).fetchone()
        require(
            event_row is not None
            and type(event_row["envelope"]) is bytes
            and len(event_row["envelope"]) <= 8192,
            "unavailable",
        )
        event = EventEnvelope.from_bytes(event_row["envelope"])
        expected = EventEnvelope.create(
            event_id=step["event_id"],
            sequence=event_row["sequence"],
            **old.event_fields(
                roots,
                item["ref"],
                state,
                now,
                actor,
                step["command_id"] or event.correlation_id,
                revision=index,
                receipt_outcome=receipt["value"]["outcome"] if index == 2 else None,
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
        command = commands.get(step["command_id"])
        require(command is not None, "unavailable")
        ids.add(step["command_id"])
        value = parse_canonical(command["input_json"].encode())
        parser = (
            parse_provider_receipt_import
            if index == 2
            else parse_provider_consume
            if state == "accepted"
            else parse_provider_pending_cancel
        )
        require(
            parser(
                item["ref"].id, {k: v for k, v in value.items() if k != "request_id"}
            )
            == value
            and value["command_id"] == step["command_id"]
            and value["request_digest"] == item["request"]["request_digest"]
            and value["receipt_digest"] == receipt["digest"]
            and command["request_id"] == item["ref"].id
            and command["namespace"] == NAMESPACES[state]
            and command["actor_ref"] == step["actor_ref"]
            and command["lifecycle_revision"] == index
            and command["http_status"] == 200
            and command["input_digest"]
            == old.input_digest(profile, actor.as_dict(), NAMESPACES[state], value),
            "unavailable",
        )
        reply = parse_canonical(command["receipt_json"].encode())
        cursor = _decode_cursor(reply["event_cursor"])
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
            "history": history[:index],
            "outbox": {"request": outs["request"]},
            "consumption": item["consumption"]
            if state in {"rejected", "accepted"}
            else None,
            "installation": item["installation"] if state == "accepted" else None,
            "consumed_outbox": {"state": "pending"} if state == "rejected" else None,
        }
        if state == "cancelled":
            frozen["outbox"]["cancel"] = {"state": "pending"}
        require(
            reply
            == _body(
                frozen, command_id=step["command_id"], cursor=reply["event_cursor"]
            ),
            "unavailable",
        )
    require(
        ids == {k for k, v in commands.items() if v["request_id"] == item["ref"].id},
        "unavailable",
    )
