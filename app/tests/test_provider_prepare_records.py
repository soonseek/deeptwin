"""Actual CAS/DomainStore graph, context indices and immutable history checks."""

import sqlite3
from copy import deepcopy
from uuid import uuid4

import pytest

from app.deployment import prepare_storage as storage
from app.deployment.prepare_contracts import DeploymentPrepareError
from app.domain.refs import DomainContractError, canonical_json, parse_canonical
from app.domain.schemas import ImmutableRecord
from app.domain.store import StorageError, _writer
from app.tests.provider_prepare_fixture import provider_context


@pytest.mark.parametrize(
    "mutation", ["future_accepted", "future_staged", "swapped", "forged_head"]
)
def test_real_staged_history_rejects_cas_sealed_forged_inventory_at_consumer(
    tmp_path, monkeypatch, mutation
):
    from app.deployment import provider_prepare_records as provider
    from app.deployment.provider_prepare_contracts import parse_provider_inventory

    with provider_context(
        tmp_path.resolve(), monkeypatch, slot_id=2, legacy_staged=True
    ) as actual:
        receipt = actual.service.prepare_provider(actual.request, actual.payload)
        with actual.domain._connection() as db:
            roots = actual.domain._read_roots(db)
            journal = actual.service._journal(db)
            item = journal["requests"][receipt["request_id"]]
            provider.verify_inventories(
                actual.domain, db, roots, actual.profile, journal
            )
            forged = parse_canonical(item["inventory_raw"])
            entry = forged["installations"][0]
            assert entry["request_ref"]["id"] == actual.legacy_request["request_id"]
            future = item["history"][0]["event_id"]
            sequences = dict(
                db.execute("SELECT event_id,sequence FROM api_event_envelopes")
            )
            assert (
                sequences[entry["accepted_event_id"]]
                < sequences[entry["staged_event_id"]]
                <= forged["at_event_sequence"]
                < sequences[future]
            )
        if mutation == "swapped":
            entry["accepted_event_id"], entry["staged_event_id"] = (
                entry["staged_event_id"],
                entry["accepted_event_id"],
            )
        elif mutation == "forged_head":
            entry["installation_ref"]["sha256"] = "0" * 64
            entry["head_digest"] = storage.digest(
                "installation_heads",
                {
                    "extension_id": entry["extension_id"],
                    "request_id": entry["request_ref"]["id"],
                    "revision": 1,
                    "installation_anchor_digest": entry["installation_ref"]["sha256"],
                },
            )
        else:
            entry[mutation.removeprefix("future_") + "_event_id"] = future
        raw = canonical_json(forged)
        parse_provider_inventory(raw)
        blob = actual.domain.put_blob(raw, purpose="operational")
        retained = actual.domain.read_blob(blob, purpose="operational")
        assert retained == raw
        # Negative consumer input only: do not pretend to rewrite the immutable
        # anchor/index/request closure or substitute a successful journal check.
        negative = {
            **journal,
            "requests": {
                **journal["requests"],
                receipt["request_id"]: {**item, "inventory_raw": retained},
            },
        }
        with actual.domain._connection() as db:
            provider.verify_inventories(
                actual.domain, db, roots, actual.profile, journal
            )
            with pytest.raises(DeploymentPrepareError) as caught:
                provider.verify_inventories(
                    actual.domain, db, roots, actual.profile, negative
                )
            assert caught.value.code == "unavailable"
        assert actual.service.read_provider(actual.read_request, receipt["request_id"])[
            "request"
        ]["effect_payload"]["preserved_inventory"] == parse_canonical(
            item["inventory_raw"]
        )


def test_actual_graph_indexes_exact_deduplicated_nested_source_refs(
    tmp_path, monkeypatch
):
    with provider_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare_provider(actual.request, actual.payload)
        with actual.domain._connection() as db:
            journal = actual.service._journal(db)
            item = journal["requests"][receipt["request_id"]]
            roots = actual.domain._read_roots(db)
            record = actual.domain._load(db, item["ref"], roots)[0]
            actual.domain._check_graph(db, [item["ref"]], roots)
            anchor = record.body["content"]
            expected = {
                tuple(ref[key] for key in ("purpose", "sha256", "size"))
                for ref in (
                    anchor["request_blob_ref"],
                    anchor["preserved_inventory_blob_ref"],
                    *(doc["blob_ref"] for doc in anchor["source_documents"]),
                )
            }
            observed = {
                tuple(row)
                for row in db.execute(
                    "SELECT purpose,sha256,size FROM domain_record_blobs WHERE source_kind='deployment_request' AND source_id=?",
                    (item["ref"].id,),
                )
            }
            assert observed == expected and len(observed) <= 20
        for mutation in ("vault", "wrapper", "old"):
            body = deepcopy(record.body)
            if mutation == "vault":
                body["content"]["source_documents"][0]["blob_ref"]["vault_id"] = str(
                    uuid4()
                )
            elif mutation == "wrapper":
                body["content"]["source_documents"][0]["extra"] = True
            else:
                body["content"]["schema_version"] = "deployment-request-anchor-v1"
            with pytest.raises(DomainContractError):
                ImmutableRecord.from_bytes(canonical_json(body))

        # A structurally consistent foreign vault still cannot enter this actual
        # DomainStore graph: this reaches put/_check_graph, not just schema parsing.
        body = deepcopy(record.body)
        body["id"] = body["content"]["request_id"] = str(uuid4())
        foreign = str(uuid4())
        for blob in (
            body["content"]["request_blob_ref"],
            body["content"]["preserved_inventory_blob_ref"],
            *(doc["blob_ref"] for doc in body["content"]["source_documents"]),
        ):
            blob["vault_id"] = foreign
        foreign_record = ImmutableRecord.from_bytes(canonical_json(body))
        with pytest.raises((DomainContractError, StorageError)):
            actual.domain.put(foreign_record)
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT 1 FROM domain_records WHERE id=?", (body["id"],)
                ).fetchone()
                is None
            )


def test_vault_qualified_relation_fk_cannot_alias_existing_request(
    tmp_path, monkeypatch
):
    with provider_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare_provider(actual.request, actual.payload)
        with _writer(), actual.domain._connection(write=True) as db:
            assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(
                    "UPDATE deployment_prepare_provider_requests SET vault_id=? WHERE request_id=?",
                    (str(uuid4()), receipt["request_id"]),
                )


@pytest.mark.parametrize(
    "mutation",
    [
        "half_docs",
        "doc_size",
        "context17",
        "relation",
        "association",
        "boundary",
        "wrong_vault",
        "cursor",
    ],
)
def test_rehashed_corrupt_indices_cannot_replace_actual_cas_graph_or_event_provenance(
    tmp_path, monkeypatch, mutation
):
    with provider_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare_provider(actual.request, actual.payload)
        with sqlite3.connect(actual.domain.path) as db:
            db.row_factory = sqlite3.Row
            if mutation == "half_docs":
                db.execute(
                    "DELETE FROM deployment_prepare_provider_context_documents WHERE ordinal=18"
                )
            elif mutation == "relation":
                db.execute("DELETE FROM deployment_prepare_provider_requests")
            elif mutation == "association":
                db.execute(
                    "DELETE FROM domain_record_blobs WHERE source_kind='deployment_request'"
                )
            else:
                table = {
                    "doc_size": "provider_context_documents",
                    "context17": "provider_contexts",
                    "boundary": "provider_requests",
                    "wrong_vault": "provider_requests",
                    "cursor": "commands",
                }[mutation]
                row = dict(
                    db.execute(
                        "SELECT * FROM deployment_prepare_" + table + " LIMIT 1"
                    ).fetchone()
                )
                if mutation == "doc_size":
                    row["size"] += 1
                elif mutation == "context17":
                    row["context_sha256"] = receipt["preserved_inventory_sha256"]
                elif mutation == "boundary":
                    row["at_event_sequence"] += 1
                elif mutation == "wrong_vault":
                    row["vault_id"] = str(uuid4())
                else:
                    import json

                    reply = json.loads(row["receipt_json"])
                    reply["event_cursor"] = "arbitrary"
                    row["receipt_json"] = storage.encoded(reply)
                row["hash"] = storage.digest(table, row)
                selector = (
                    "ordinal"
                    if table == "provider_context_documents"
                    else "context_id"
                    if table == "provider_contexts"
                    else "command_id"
                    if table == "commands"
                    else "request_id"
                )
                db.execute(
                    "UPDATE deployment_prepare_"
                    + table
                    + " SET "
                    + ",".join(key + "=?" for key in row)
                    + " WHERE "
                    + selector
                    + "=?",
                    (*row.values(), row[selector]),
                )
        with pytest.raises(DeploymentPrepareError) as denied:
            actual.service.read_provider(actual.read_request, receipt["request_id"])
        assert denied.value.code == "unavailable"
