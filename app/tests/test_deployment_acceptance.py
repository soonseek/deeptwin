"""Task 24 step (e2a): the acceptance writer, the accepted3 lifecycle rules, the
registered events and the v3 read body (contracts/deployment-receipt-journal-v3.md
§4 records and bijections, §5 the final-writer part of the consume transaction,
§6 events and read fields, §7 lifecycle/records API).

`records.accept_stage` is the one writer body that turns a `receipt_pending2`
request with a succeeded receipt and a presealed postcondition evidence blob
into `accepted3`: the installation anchor and head, the acceptance transition
with its `deployment.request_accepted` event, the `extension.staged` event,
the success consumption anchor v2 and the index rows, in one transaction.
The service orchestration around it (admission, expiry precedence, the
observer, presealing, final-writer rechecks) is step (e2b); here the evidence
bytes are built by the test in the contract's grammar.
"""

import hashlib
import json
from base64 import urlsafe_b64encode
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app.deployment import prepare_lifecycle as lifecycle
from app.deployment import prepare_records as records
from app.deployment import prepare_storage as storage
from app.deployment import prepare_v3_schema_exports as v3_exports
from app.deployment import stage_observer
from app.deployment.prepare_contracts import DeploymentPrepareError
from app.deployment.prepare_v3_contracts import parse_consume
from app.domain.events import EVENT_TYPES
from app.domain.public_events import EventEnvelope
from app.domain.refs import canonical_json, parse_canonical
from app.domain.schema_exports import events_schema
from app.domain.store import _writer
from app.extensions.lineage_contracts import parse_build_identity
from app.tests import deployment_prepare_fixture
from app.tests.deployment_receipt_import_fixture import receipt_context, signed_case
from app.tests.test_deployment_consume import lineage_bundle, worker_identity_bytes

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def lineage_candidate(monkeypatch):
    """The verifier re-derives the expectation from the candidate's provenance
    lineage (journal v3 §4), so every accepted journal here is built on the
    lineage-joined candidate; the evidence names that lineage's identity."""
    bundle = lineage_bundle()
    monkeypatch.setattr(deployment_prepare_fixture, "matching_bundle", lambda: bundle)
    return bundle


def nonce():
    return urlsafe_b64encode(hashlib.sha256(str(uuid4()).encode()).digest()).rstrip(b"=").decode()


def evidence_for(item, *, expected=None, **changes):
    """A §4 evidence blob agreeing with the item's request and receipt."""
    request = item["request"]
    receipt = item["receipt"]
    # an Absent result (a failed receipt) carries no identity: the request's
    # effect names the service the evidence would have to describe
    present = receipt["value"]["effect_result"]["new_service"]
    service_identity = present.get(
        "service_identity", request["effect_payload"]["new_service_effect"]["service_identity"]
    )
    identity = parse_build_identity(worker_identity_bytes())
    expected = expected or {
        "service_identity": service_identity,
        "build_identity_digest": identity.digest,
        "port_schema_set_digest": identity.schema_set_digest,
        "port_contract_version": "tool-port-v1",
        "platform": request["effect_payload"]["selected_platform_entry"]["platform"],
        "uid": 22001,
        "gid": 22001,
    }

    def probe():
        return {
            "challenge": nonce(),
            "request_message_id": str(uuid4()),
            "reply_message_id": str(uuid4()),
            "reply": {
                "service_identity": expected["service_identity"],
                "component": {
                    "build_identity_digest": expected["build_identity_digest"],
                    "port_contract_version": expected["port_contract_version"],
                    "port_schema_set_digest": expected["port_schema_set_digest"],
                },
                "runtime": {
                    "platform": expected["platform"],
                    "uid": expected["uid"],
                    "gid": expected["gid"],
                    "registered_operations": [],
                },
            },
        }

    value = {
        "schema_version": "extension-stage-postcondition-v1",
        "request_id": request["request_id"],
        "request_digest": request["request_digest"],
        "receipt_digest": receipt["digest"],
        "request_blob_sha256": hashlib.sha256(item["raw"]).hexdigest(),
        "receipt_blob_sha256": receipt["row"]["receipt_sha256"],
        # observed inside the receipt-import → acceptance window
        "observed_at": lifecycle.stamp(item["history"][-1]["transitioned_ms"]),
        "attempt_ms": 120,
        "connection": {
            "channel_id": "cp-" + expected["service_identity"],
            "connection_id": "3" * 64,
            "requester_boot_id": "4" * 64,
            "responder_boot_id": "5" * 64,
            "peer_uid": expected["uid"],
            "peer_gid": expected["gid"],
        },
        "probes": [probe(), probe()],
        "expected": expected,
        "comparison": "equal",
        **changes,
    }
    return canonical_json(value)


def pending(actual, monkeypatch):
    """A receipt_pending2 request with a succeeded receipt, plus its journal item."""
    prepared, command, _, _ = signed_case(
        actual, monkeypatch, case_name="valid_succeeded_present"
    )
    result = actual.service.import_receipt(actual.request, prepared["request_id"], command)
    assert result["disposition"] == "pending_postconditions"
    with actual.domain._connection() as db:
        journal = records.verify(actual.domain, db, actual.profile)
    return prepared, journal["requests"][prepared["request_id"]], command


def consume_value(prepared, command):
    return parse_consume(
        prepared["request_id"],
        {
            "command_id": str(uuid4()),
            "request_digest": prepared["request_digest"],
            "receipt_digest": command["receipt_digest"],
            "expected_revision": 2,
        },
    )


def accept(actual, prepared, command, raw, *, now_offset_ms=None):
    """The final-writer body on the real store: preseal, then one transaction."""
    blob = actual.domain.put_blob(raw, purpose="operational")
    value = consume_value(prepared, command)
    with _writer(), actual.domain._connection(write=True) as db:
        actor = actual.service._authenticate(actual.request, db)
        journal = actual.service._journal(db)
        actor_ref = actual.service._actor_ref(db, actor)
        item = journal["requests"][prepared["request_id"]]
        now = actual.service._now(db, journal["control"])
        actual.service._floor(db, journal["control"], now)
        if now_offset_ms is not None:
            now = item["row"]["expires_ms"] + now_offset_ms
        roots = actual.domain._read_roots(db)
        reply = records.accept_stage(
            actual.domain,
            db,
            roots,
            actual.profile,
            item,
            now=now,
            actor_ref=actor_ref,
            value=value,
            evidence=blob,
            evidence_bytes=raw,
        )
        records.verify(actual.domain, db, actual.profile)
    return reply, value


def events_of(domain, event_type):
    with domain._connection() as db:
        rows = db.execute(
            "SELECT envelope FROM api_event_envelopes WHERE event_type=? ORDER BY sequence",
            (event_type,),
        ).fetchall()
    return [EventEnvelope.from_bytes(row[0]) for row in rows]


def test_accept_stage_commits_the_installation_head_consumption_and_events(
    tmp_path, monkeypatch
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, item, command = pending(actual, monkeypatch)
        raw = evidence_for(item)
        reply, value = accept(actual, prepared, command, raw)
        present = item["receipt"]["value"]["effect_result"]["new_service"]
        assert reply == {
            "command_id": value["command_id"],
            "request_id": prepared["request_id"],
            "receipt_digest": command["receipt_digest"],
            "outcome": "succeeded",
            "disposition": "consumed_success",
            "revision": 3,
            "installation": {
                "installation_id": reply["installation"]["installation_id"],
                "extension_id": item["request"]["effect_payload"]["extension_id"],
                "installation_digest": reply["installation"]["installation_digest"],
                "revision": 1,
            },
            "event_cursor": reply["event_cursor"],
        }
        assert Draft202012Validator(
            v3_exports.consume_receipt_schema(), format_checker=FormatChecker()
        ).is_valid(reply)
        # the journal verifies and loads the acceptance; the constructor accepts it
        with actual.domain._connection() as db:
            journal = records.verify(actual.domain, db, actual.profile)
            counts = {
                table: db.execute(
                    "SELECT count(*) FROM deployment_prepare_" + table
                ).fetchone()[0]
                for table in ("installations", "installation_heads", "consumptions",
                              "consumed_outbox")
            }
        assert counts == {
            "installations": 1,
            "installation_heads": 1,
            "consumptions": 1,
            "consumed_outbox": 0,
        }
        accepted = journal["requests"][prepared["request_id"]]
        assert [h["state"] for h in accepted["history"]] == [
            "prepared", "receipt_pending", "accepted",
        ]
        assert accepted["head"]["revision"] == 3
        installation = accepted["installation"]
        anchor = installation["anchor"]
        assert anchor["schema_version"] == "extension-installation-anchor-v1"
        assert anchor["state"] == "staged" and anchor["revision"] == 1
        assert anchor["previous_record_digest"] is None
        assert anchor["service_identity"] == present["service_identity"]
        assert anchor["manifest_digest"] == present["manifest_digest"]
        assert anchor["image_manifest_digest"] == present["image_manifest_digest"]
        assert anchor["consume_command_id"] == value["command_id"]
        assert anchor["postcondition_evidence_blob_ref"]["sha256"] == hashlib.sha256(raw).hexdigest()
        assert installation["ref"].sha256 == reply["installation"]["installation_digest"]
        assert installation["ref"].id == reply["installation"]["installation_id"]
        assert installation["head"]["revision"] == 1
        consumption = accepted["consumption"]["anchor"]
        assert consumption["schema_version"] == "deployment-receipt-consumption-anchor-v2"
        assert consumption["winning_lifecycle_revision"] == 3
        assert consumption["outcome"] == "succeeded"
        assert consumption["effect_ref"] == installation["ref"].as_dict()
        assert accepted["consumption"]["row"]["lifecycle_revision"] == 3
        assert accepted["consumed_outbox"] is None
        # both events, in one writer, with the contract's fields
        (accepted_event,) = events_of(actual.domain, "deployment.request_accepted")
        assert accepted_event.status == "succeeded" and accepted_event.error_code is None
        assert accepted_event.public_metadata == {"revision": 3}
        assert accepted_event.correlation_id == value["command_id"]
        assert accepted_event.object_refs[0].kind == "deployment_request"
        (staged,) = events_of(actual.domain, "extension.staged")
        assert staged.status == "succeeded"
        assert staged.public_metadata == {
            "extension_kind": "tool", "trust_tier": "runtime_worker", "revision": 1,
        }
        assert staged.causation_id == accepted_event.event_id
        assert staged.correlation_id == value["command_id"]
        assert (staged.object_refs[0].kind, staged.object_refs[0].id) == (
            "extension_installation", installation["ref"].id,
        )
        assert consumption["public_event_id"] == accepted_event.event_id
        # the current read shows the v3 head and validates against prepare-api-v3
        current = actual.service.read(actual.read_request, prepared["request_id"])
        assert current["state"] == "accepted" and current["revision"] == 3
        assert current["receipt"]["disposition"] == "consumed_success"
        assert current["consumption_publication_state"] is None
        assert current["installation"] == reply["installation"]
        assert Draft202012Validator(
            v3_exports.read_schema(), format_checker=FormatChecker()
        ).is_valid(current)
        # the stored revision-2 import reply keeps its frozen disposition
        with actual.domain._connection() as db:
            stored = db.execute(
                "SELECT receipt_json FROM deployment_prepare_commands WHERE namespace='deployment-receipt-import-v1'"
            ).fetchone()[0]
        assert json.loads(stored)["disposition"] == "pending_postconditions"
        # accepted is terminal: a second acceptance is refused, cancel is 409
        with pytest.raises(DeploymentPrepareError) as failure:
            accept(actual, prepared, command, raw)
        assert failure.value.code == "conflict"
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.cancel(
                actual.request,
                prepared["request_id"],
                {"command_id": str(uuid4()), "request_digest": prepared["request_digest"],
                 "expected_revision": 3},
            )
        assert failure.value.code == "conflict"
        assert actual.service.read(actual.read_request, prepared["request_id"])["state"] == "accepted"


@pytest.mark.parametrize(
    "change",
    [
        "wrong_request_id",
        "wrong_receipt_digest",
        "wrong_request_sha",
        "comparison_unequal",
        "one_probe",
        "same_challenge",
        "service_identity",
        "peer_uid",
        "reply_differs",
        "extra_field",
        "peer_outside_slot",
        "channel_outside_slot",
        "observed_after_now",
        "observed_before_receipt",
    ],
)
def test_accept_stage_refuses_evidence_outside_the_grammar_or_the_request(
    tmp_path, monkeypatch, change
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, item, command = pending(actual, monkeypatch)
        base = parse_canonical(evidence_for(item))
        if change == "peer_outside_slot":
            # internally consistent evidence about a peer that is not the
            # admitted slot: only the slot comparison can refuse it
            base["expected"]["uid"] = base["expected"]["gid"] = 7
            base["connection"]["peer_uid"] = base["connection"]["peer_gid"] = 7
            for probe in base["probes"]:
                probe["reply"]["runtime"]["uid"] = probe["reply"]["runtime"]["gid"] = 7
        elif change == "channel_outside_slot":
            base["connection"]["channel_id"] = "cp-ext-other"
        elif change == "observed_after_now":
            base["observed_at"] = "2099-01-01T00:00:00.000Z"
        elif change == "observed_before_receipt":
            base["observed_at"] = "1970-01-01T00:00:00.000Z"
        elif change == "wrong_request_id":
            base["request_id"] = str(uuid4())
        elif change == "wrong_receipt_digest":
            base["receipt_digest"] = "A" * 43
        elif change == "wrong_request_sha":
            base["request_blob_sha256"] = "9" * 64
        elif change == "comparison_unequal":
            base["comparison"] = "unequal"
        elif change == "one_probe":
            base["probes"] = base["probes"][:1]
        elif change == "same_challenge":
            base["probes"][1]["challenge"] = base["probes"][0]["challenge"]
        elif change == "service_identity":
            base["expected"]["service_identity"] = "ext-other"
            for probe in base["probes"]:
                probe["reply"]["service_identity"] = "ext-other"
        elif change == "peer_uid":
            base["connection"]["peer_uid"] = 1
        elif change == "reply_differs":
            base["probes"][1]["reply"]["runtime"]["uid"] = 22002
        else:
            base["future"] = None
        raw = canonical_json(base)
        with pytest.raises(DeploymentPrepareError) as failure:
            accept(actual, prepared, command, raw)
        assert failure.value.code == "conflict"
        with actual.domain._connection() as db:
            assert db.execute("SELECT count(*) FROM deployment_prepare_installations").fetchone()[0] == 0
            journal = records.verify(actual.domain, db, actual.profile)
        assert journal["requests"][prepared["request_id"]]["history"][-1]["state"] == "receipt_pending"


@pytest.mark.parametrize("offset_ms", [0, 1, -60_000_000])
def test_accept_stage_requires_now_inside_the_request_interval(
    tmp_path, monkeypatch, offset_ms
):
    # the final-writer body owns the time precondition: not at or after the
    # deadline (that is the caller's expiry precedence) and never before the
    # receipt import it consumes
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, item, command = pending(actual, monkeypatch)
        with pytest.raises(DeploymentPrepareError) as failure:
            accept(actual, prepared, command, evidence_for(item), now_offset_ms=offset_ms)
        assert failure.value.code == "conflict"
        assert actual.service.read(actual.read_request, prepared["request_id"])["state"] == "receipt_pending"


def test_append_transition_admits_accepted_only_from_receipt_pending_with_a_command(
    tmp_path, monkeypatch
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared = actual.service.prepare(actual.request, actual.payload)
        with _writer(), actual.domain._connection(write=True) as db:
            actor = actual.service._authenticate(actual.request, db)
            journal = actual.service._journal(db)
            actor_ref = actual.service._actor_ref(db, actor)
            item = journal["requests"][prepared["request_id"]]
            roots = actual.domain._read_roots(db)
            now = actual.service._now(db, journal["control"])
            with pytest.raises(DeploymentPrepareError):  # from prepared
                lifecycle._append_transition(
                    db, roots, actual.profile, item, state="accepted", now=now,
                    actor_ref=actor_ref, command_id=str(uuid4()),
                )
            pending_item = dict(item, history=item["history"] + [
                {**item["history"][0], "state": "receipt_pending", "revision": 2}
            ])
            with pytest.raises(DeploymentPrepareError):  # without a command
                lifecycle._append_transition(
                    db, roots, actual.profile, pending_item, state="accepted", now=now,
                    actor_ref=actor_ref, command_id=None,
                )


@pytest.mark.parametrize("state", ["prepared", "rejected", "cancelled3"])
def test_accept_stage_requires_a_pending_succeeded_head(tmp_path, monkeypatch, state):
    with receipt_context(tmp_path, monkeypatch) as actual:
        if state == "prepared":
            prepared = actual.service.prepare(actual.request, actual.payload)
            command = {"receipt_digest": "E" * 43}
        elif state == "rejected":
            prepared, command, _, _ = signed_case(
                actual, monkeypatch, case_name="valid_failed_absent"
            )
            actual.service.import_receipt(actual.request, prepared["request_id"], command)
        else:
            prepared, item, command = pending(actual, monkeypatch)
            actual.service.cancel(
                actual.request,
                prepared["request_id"],
                {"command_id": str(uuid4()), "request_digest": prepared["request_digest"],
                 "expected_revision": 2},
            )
        with actual.domain._connection() as db:
            item = records.verify(actual.domain, db, actual.profile)["requests"][
                prepared["request_id"]
            ]
        raw = evidence_for(item) if item.get("receipt") else b'{"schema_version":"extension-stage-postcondition-v1"}'
        with pytest.raises(DeploymentPrepareError) as failure:
            accept(actual, prepared, command, raw)
        assert failure.value.code == "conflict"


@pytest.mark.parametrize(
    "damage",
    ["drop_head", "drop_installation", "consumed_outbox", "consumption_revision",
     "installed_ms"],
)
def test_verifier_refuses_every_broken_acceptance_relationship(tmp_path, monkeypatch, damage):
    import sqlite3

    def rehash(db, table, key):
        # keep the row hash valid so the named relationship, not the hash, refuses
        db.row_factory = sqlite3.Row
        row = dict(db.execute("SELECT * FROM deployment_prepare_" + table).fetchone())
        db.execute(
            "UPDATE deployment_prepare_" + table + " SET hash=? WHERE " + key + "=?",
            (storage.digest(table, {k: v for k, v in row.items() if k != "hash"}), row[key]),
        )

    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, item, command = pending(actual, monkeypatch)
        accept(actual, prepared, command, evidence_for(item))
        with sqlite3.connect(actual.domain.path) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            if damage == "installed_ms":
                db.execute("UPDATE deployment_prepare_installations SET installed_ms=installed_ms+1")
                rehash(db, "installations", "request_id")
            elif damage == "drop_head":
                db.execute("DELETE FROM deployment_prepare_installation_heads")
            elif damage == "drop_installation":
                db.execute("DELETE FROM deployment_prepare_installations")
                db.execute("DELETE FROM deployment_prepare_installation_heads")
            elif damage == "consumed_outbox":
                row = db.execute("SELECT consumption_id FROM deployment_prepare_consumptions").fetchone()
                values = {
                    "consumption_id": row[0], "payload_sha256": "a" * 64, "payload_size": 1,
                    "state": "pending", "published_ms": None, "revision": 1,
                }
                values["hash"] = storage.digest("consumed_outbox", values)
                db.execute(
                    "INSERT INTO deployment_prepare_consumed_outbox VALUES (?,?,?,?,?,?,?)",
                    tuple(values[k] for k in ("consumption_id", "payload_sha256", "payload_size",
                                              "state", "published_ms", "revision", "hash")),
                )
            else:
                db.execute("UPDATE deployment_prepare_consumptions SET lifecycle_revision=2")
                rehash(db, "consumptions", "request_id")
        with actual.domain._connection() as db, pytest.raises(DeploymentPrepareError):
            records.verify(actual.domain, db, actual.profile)


def test_lifecycle_admits_accepted_only_from_receipt_pending_with_a_command():
    with pytest.raises(DeploymentPrepareError):
        lifecycle.event_fields(None, None, "accepted", 0, None, str(uuid4()), revision=2)
    fields = lifecycle.event_fields(
        type("Roots", (), {"genesis": type("G", (), {"id": str(uuid4())})(), "access_policy": None})(),
        type("Ref", (), {"kind": "deployment_request", "id": str(uuid4()), "version": 1, "sha256": "a" * 64})(),
        "accepted",
        1_700_000_000_000,
        None,
        str(uuid4()),
        revision=3,
    )
    assert fields["event_type"] == "deployment.request_accepted"
    assert fields["status"] == "succeeded" and fields["error_code"] is None
    assert fields["public_metadata"] == {"revision": 3}
    assert fields["actor_kind"] == "human"


def test_request_accepted_is_registered_and_the_event_export_is_regenerated():
    assert "deployment.request_accepted" in EVENT_TYPES
    schema = events_schema()
    assert schema == json.loads((ROOT / "schemas/v1/event-metadata.schema.json").read_text())
    assert set(schema["$defs"]["deployment.request_accepted"]["properties"]) == {"revision"}


@pytest.mark.parametrize(
    "change",
    [{}, {"comparison": "unequal"}, {"attempt_ms": 0}, {"attempt_ms": 2001}, {"probes": []},
     {"schema_version": "x"}, {"extra": 1}],
)
def test_parse_stage_evidence_is_the_closed_grammar(change):
    value = {
        "schema_version": "extension-stage-postcondition-v1",
        "request_id": str(uuid4()),
        "request_digest": "A" * 43,
        "receipt_digest": "E" * 43,  # canonical: the last character is in AEIMQUYcgkosw048
        "request_blob_sha256": "1" * 64,
        "receipt_blob_sha256": "2" * 64,
        "observed_at": "2026-09-18T00:00:00.000Z",
        "attempt_ms": 5,
        "connection": {
            "channel_id": "cp-ext-1", "connection_id": "3" * 64,
            "requester_boot_id": "4" * 64, "responder_boot_id": "5" * 64,
            "peer_uid": 22001, "peer_gid": 22001,
        },
        "probes": [
            {
                "challenge": nonce(), "request_message_id": str(uuid4()),
                "reply_message_id": str(uuid4()),
                "reply": {
                    "service_identity": "ext-1",
                    "component": {"build_identity_digest": "6" * 64,
                                  "port_contract_version": "tool-port-v1",
                                  "port_schema_set_digest": "7" * 64},
                    "runtime": {"platform": "linux/amd64", "uid": 22001, "gid": 22001,
                                "registered_operations": []},
                },
            }
            for _ in range(2)
        ],
        "expected": {
            "service_identity": "ext-1", "build_identity_digest": "6" * 64,
            "port_schema_set_digest": "7" * 64, "port_contract_version": "tool-port-v1",
            "platform": "linux/amd64", "uid": 22001, "gid": 22001,
        },
        "comparison": "equal",
    }
    raw = canonical_json({**value, **change})
    if change:
        with pytest.raises(stage_observer.StagePostconditionError) as error:
            stage_observer.parse_stage_evidence(raw)
        assert error.value.code == "probe_invalid"
    else:
        parsed = stage_observer.parse_stage_evidence(raw)
        assert parsed == value
        with pytest.raises(stage_observer.StagePostconditionError):
            stage_observer.parse_stage_evidence(raw + b"\n")
