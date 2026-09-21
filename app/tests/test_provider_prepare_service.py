"""Actual authenticated provider commands, retained history and replay."""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from threading import Barrier
from uuid import uuid4

import pytest

from app.deployment.prepare_contracts import DeploymentPrepareError, epoch_ms
from app.deployment.prepare_service import PersistentDeploymentPrepare
from app.domain.refs import canonical_json, parse_canonical
from app.tests.provider_prepare_fixture import provider_context


def provider_variant(actual, slot_id):
    from app.extensions.candidate_contracts import metadata_ref, parse_bundle
    from app.extensions.provider_lineage import (
        parse_provider_lineage,
        validate_provider_descriptor_lineage,
    )
    from app.tests.test_provider_lineage import shipped_schema_bytes
    from app.tests.test_provider_prepare_contracts import _provider_candidate

    slot = parse_canonical(actual.tree.bundle[9][1])["slots"][slot_id - 1]
    value = _provider_candidate(slot)[0].as_dict()
    value["command_id"] = str(uuid4())
    for key in ("manifest", "service_descriptor"):
        value[key]["extension_id"] = "synthetic-provider-second"
    lineage = next(
        doc["content"]
        for doc in value["documents"]
        if doc["document_kind"] == "provenance"
    )
    lineage["extension_id"] = "synthetic-provider-second"
    for platform in lineage["platforms"]:
        platform["build_identity"]["extension_id"] = "synthetic-provider-second"
    provenance = metadata_ref("provenance", canonical_json(lineage))
    value["manifest"]["source"]["provenance_ref"] = provenance
    value["service_descriptor"]["evidence"]["provenance_ref"] = provenance
    value["manifest"]["artifact"]["service_descriptor_ref"] = metadata_ref(
        "service_descriptor", canonical_json(value["service_descriptor"])
    )
    validate_provider_descriptor_lineage(
        parse_provider_lineage(canonical_json(lineage)),
        parse_bundle(value).descriptor,
        instance_id=actual.profile.instance_id,
        slot_number=slot_id,
        schema_bytes=shipped_schema_bytes(),
    )
    return actual.registry.register(actual.request, value)["candidate_ref"][
        "candidate_id"
    ]


@pytest.mark.parametrize("target", ["candidate_cas", "managed_inventory"])
def test_final_writer_refuses_actual_candidate_or_inventory_drift(
    tmp_path, monkeypatch, target
):
    from pathlib import Path

    with provider_context(
        tmp_path.resolve(),
        monkeypatch,
        slot_id=2,
        legacy_staged=True,
        defer_legacy_stage=True,
    ) as actual:
        with actual.domain._connection() as db:
            candidate_blob = db.execute(
                "SELECT purpose,sha256 FROM domain_record_blobs "
                "WHERE source_kind='extension_manifest' AND source_id=? LIMIT 1",
                (actual.payload["candidate_id"],),
            ).fetchone()
        original = actual.domain.put_blob
        calls, checkpoints = [], []

        def seal(raw, **kwargs):
            blob = original(raw, **kwargs)
            calls.append(blob)
            if len(calls) == 20:
                checkpoints.append(target)
                if target == "candidate_cas":
                    # Immutable candidate corruption, not a replacement API.
                    path = (
                        Path(actual.domain.data_dir)
                        / "domain-cas"
                        / candidate_blob[0]
                        / candidate_blob[1]
                    )
                    path.write_bytes(path.read_bytes() + b"!")
                else:
                    # Genuine accepted receipt and staged installation after the
                    # first snapshot, before the provider final writer.
                    actual.stage_legacy()
            return blob

        monkeypatch.setattr(actual.domain, "put_blob", seal)
        with pytest.raises(DeploymentPrepareError) as caught:
            actual.service.prepare_provider(actual.request, actual.payload)
        assert caught.value.code == (
            "unavailable" if target == "candidate_cas" else "conflict"
        )
        assert checkpoints == [target]
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_provider_requests"
                ).fetchone()[0]
                == 0
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_provider_contexts"
                ).fetchone()[0]
                == 0
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_commands WHERE command_id=?",
                    (actual.payload["command_id"],),
                ).fetchone()[0]
                == 0
            )
            assert db.execute(
                "SELECT count(*) FROM deployment_prepare_requests"
            ).fetchone()[0] == (target == "managed_inventory")
            if target == "managed_inventory":
                assert (
                    actual.service._journal(db)["requests"][
                        actual.legacy_request["request_id"]
                    ]["history"][-1]["state"]
                    == "accepted"
                )
                assert (
                    db.execute(
                        "SELECT count(*) FROM deployment_prepare_installations"
                    ).fetchone()[0]
                    == 1
                )


@pytest.mark.parametrize("terminal", ["cancelled", "expired"])
def test_provider_terminal_history_permanently_reserves_extension_and_slot(
    tmp_path, monkeypatch, terminal
):
    with provider_context(tmp_path.resolve(), monkeypatch) as actual:
        alternate = provider_variant(actual, 1)
        receipt = actual.service.prepare_provider(actual.request, actual.payload)
        current = actual.service.read_provider(
            actual.read_request, receipt["request_id"]
        )
        cancel = {
            "command_id": str(uuid4()),
            "request_digest": receipt["request_digest"],
            "expected_revision": 1,
        }
        if terminal == "expired":
            deadline = epoch_ms(current["request"]["expires_at"])
            monkeypatch.setattr(time, "time_ns", lambda: deadline * 1000000)
            with pytest.raises(DeploymentPrepareError) as caught:
                actual.service.cancel_provider(
                    actual.request, receipt["request_id"], cancel
                )
            assert caught.value.code == "conflict"
        else:
            assert (
                actual.service.cancel_provider(
                    actual.request, receipt["request_id"], cancel
                )["state"]
                == terminal
            )
        assert (
            actual.service.read_provider(actual.read_request, receipt["request_id"])[
                "state"
            ]
            == terminal
        )
        for changes, expected in (
            ({"slot_id": 2}, "conflict"),
            ({"candidate_id": alternate}, "capacity"),
        ):
            with pytest.raises(DeploymentPrepareError) as caught:
                actual.service.prepare_provider(
                    actual.request,
                    {**actual.payload, **changes, "command_id": str(uuid4())},
                )
            assert caught.value.code == expected
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_provider_requests"
                ).fetchone()[0]
                == 1
            )
            assert db.execute(
                "SELECT count(*) FROM deployment_prepare_commands"
            ).fetchone()[0] == (2 if terminal == "cancelled" else 1)


def test_new_valid_source_context_cannot_rotate_retained_provider_context(
    tmp_path, monkeypatch
):
    from contextlib import closing

    from app.deployment.provider_source_render import render_provider_sources
    from app.deployment.provider_sources import open_provider_source_context
    from app.tests.provider_source_fixture import case

    with provider_context(tmp_path.resolve(), monkeypatch) as actual:
        alternate = provider_variant(actual, 2)
        receipt = actual.service.prepare_provider(actual.request, actual.payload)
        actual.service.cancel_provider(
            actual.request,
            receipt["request_id"],
            {
                "command_id": str(uuid4()),
                "request_digest": receipt["request_digest"],
                "expected_revision": 1,
            },
        )
        original_files = actual.context.read_current()
        inputs = case(capacity=2)[0]
        changed = parse_canonical(inputs["provider_instance_bytes"])
        changed["context_id"] = str(uuid4())
        inputs["provider_instance_bytes"] = canonical_json(changed)
        replacement = render_provider_sources(**inputs).bundle_files
        assert replacement[:9] == original_files[:9]
        actual.context.close()
        actual.tree.install_bundle(replacement)
        with closing(
            open_provider_source_context(
                profile=actual.profile,
                context_sha256=sha256(replacement[16][1]).hexdigest(),
                protected_roots=(),
            )
        ) as context:
            assert context.read_current() == replacement
            second = PersistentDeploymentPrepare(
                actual.domain,
                actual.owner,
                actual.registry,
                topology_source=actual.service._topology,
                exchange_source=actual.service._exchange,
                provider_source_context=context,
            )
            with pytest.raises(DeploymentPrepareError) as caught:
                second.prepare_provider(
                    actual.request,
                    {
                        **actual.payload,
                        "command_id": str(uuid4()),
                        "candidate_id": alternate,
                        "slot_id": 2,
                        "source_context_sha256": sha256(replacement[16][1]).hexdigest(),
                    },
                )
            assert caught.value.code == "conflict"
            assert second.prepare_provider(actual.request, actual.payload) == receipt
            assert (
                second.read_provider(actual.read_request, receipt["request_id"])[
                    "state"
                ]
                == "cancelled"
            )
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT context_id FROM deployment_prepare_provider_contexts"
                ).fetchone()[0]
                == parse_canonical(original_files[16][1])["context_id"]
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_provider_requests"
                ).fetchone()[0]
                == 1
            )


def borrowed_service(actual):
    service = actual.service
    return PersistentDeploymentPrepare(
        actual.domain,
        actual.owner,
        actual.registry,
        topology_source=service._topology,
        exchange_source=service._exchange,
        provider_source_context=actual.context,
    )


def test_real_provider_prepare_retains_cas_journal_and_historical_read(
    tmp_path, monkeypatch
):
    with provider_context(tmp_path, monkeypatch) as actual:
        assert actual.context is not None
        result = actual.service.prepare_provider(actual.request, actual.payload)
        assert result["state"] == "prepared"
        assert result["revision"] == 1
        assert result["publication_state"] == "pending"
        current = actual.service.read_provider(
            actual.read_request, result["request_id"]
        )
        assert current["request_digest"] == result["request_digest"]
        assert (
            current["request"]["effect_payload"]["preserved_inventory"]["installations"]
            == []
        )
        assert actual.service.prepare_provider(actual.request, actual.payload) == result


def test_legacy_endpoint_refuses_provider_id_without_poisoning_history(
    tmp_path, monkeypatch
):
    with provider_context(tmp_path, monkeypatch) as actual:
        result = actual.service.prepare_provider(actual.request, actual.payload)
        with pytest.raises(DeploymentPrepareError) as caught:
            actual.service.read(actual.read_request, result["request_id"])
        assert caught.value.code == "not_found"
        with pytest.raises(DeploymentPrepareError) as caught:
            actual.service.cancel(
                actual.request,
                result["request_id"],
                {
                    "command_id": str(uuid4()),
                    "request_digest": result["request_digest"],
                    "expected_revision": 1,
                },
            )
        assert caught.value.code == "not_found"
        for method, revision in (
            (actual.service.import_receipt, 1),
            (actual.service.consume_receipt, 2),
        ):
            with pytest.raises(DeploymentPrepareError) as caught:
                method(
                    actual.request,
                    result["request_id"],
                    {
                        "command_id": str(uuid4()),
                        "request_digest": result["request_digest"],
                        "receipt_digest": "A" * 43,
                        "expected_revision": revision,
                    },
                )
            assert caught.value.code == "not_found"
        assert not actual.service._unavailable


def test_real_staged_legacy_installation_is_frozen_at_provider_boundary(
    tmp_path, monkeypatch
):
    with provider_context(
        tmp_path, monkeypatch, slot_id=2, legacy_staged=True
    ) as actual:
        # History semantics, not a real one-second throughput qualification.
        from types import SimpleNamespace
        from app.deployment import prepare_service, provider_prepare_service

        sampled = time.monotonic()
        clock = SimpleNamespace(monotonic=lambda: sampled, time_ns=time.time_ns)
        monkeypatch.setattr(prepare_service, "time", clock)
        monkeypatch.setattr(provider_prepare_service, "time", clock)
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        read = actual.service.read_provider(actual.read_request, prepared["request_id"])
        inventory = read["request"]["effect_payload"]["preserved_inventory"]
        assert len(inventory["installations"]) == 1
        entry = inventory["installations"][0]
        assert entry["request_ref"]["id"] == actual.legacy_request["request_id"]
        assert entry["slot_id"] == 1
        assert entry["head_revision"] == 1
        assert entry["head_digest"] != entry["installation_ref"]["sha256"]
        assert (
            entry["head_digest"]
            == sha256(
                canonical_json(
                    {
                        "namespace": "deployment-prepare-storage-v3",
                        "table": "installation_heads",
                        "row": {
                            "extension_id": entry["extension_id"],
                            "request_id": entry["request_ref"]["id"],
                            "revision": 1,
                            "installation_anchor_digest": entry["installation_ref"][
                                "sha256"
                            ],
                        },
                    }
                )
            ).hexdigest()
        )
        with actual.domain._connection() as db:
            sequences = dict(
                db.execute("SELECT event_id,sequence FROM api_event_envelopes")
            )
            assert (
                sequences[entry["accepted_event_id"]]
                < sequences[entry["staged_event_id"]]
                <= inventory["at_event_sequence"]
            )
        assert read["publication_state"] == "published"


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_cancellation_deadline_commits_expiry_before_returning_conflict(
    tmp_path, monkeypatch, offset
):
    with provider_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare_provider(actual.request, actual.payload)
        current = actual.service.read_provider(
            actual.read_request, receipt["request_id"]
        )
        deadline = epoch_ms(current["request"]["expires_at"])
        monkeypatch.setattr(time, "time_ns", lambda: (deadline + offset) * 1000000)
        actual.context.close()
        value = {
            "command_id": str(uuid4()),
            "request_digest": receipt["request_digest"],
            "expected_revision": 1,
        }
        if offset < 0:
            cancelled = actual.service.cancel_provider(
                actual.request, receipt["request_id"], value
            )
            assert cancelled["state"] == "cancelled"
        else:
            with pytest.raises(DeploymentPrepareError) as caught:
                actual.service.cancel_provider(
                    actual.request, receipt["request_id"], value
                )
            assert caught.value.code == "conflict"
        later = actual.service.read_provider(actual.read_request, receipt["request_id"])
        assert later["state"] == ("cancelled" if offset < 0 else "expired")
        with actual.domain._connection() as db:
            assert db.execute(
                "SELECT count(*) FROM deployment_prepare_commands WHERE command_id=?",
                (value["command_id"],),
            ).fetchone()[0] == (1 if offset < 0 else 0)


def test_exact_replay_precedes_clock_rng_and_missing_source(tmp_path, monkeypatch):
    from app.deployment import provider_prepare_service as implementation

    with provider_context(tmp_path, monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        actual.context.close()
        value = {
            "command_id": str(uuid4()),
            "request_digest": prepared["request_digest"],
            "expected_revision": 1,
        }
        cancelled = actual.service.cancel_provider(
            actual.request, prepared["request_id"], value
        )

        def forbidden(*args, **kwargs):
            pytest.fail("exact replay reached new time or randomness")

        monkeypatch.setattr(actual.service, "_now", forbidden)
        monkeypatch.setattr(implementation, "uuid4", forbidden)
        monkeypatch.setattr(implementation, "token_bytes", forbidden)
        assert (
            actual.service.prepare_provider(actual.request, actual.payload) == prepared
        )
        assert (
            actual.service.cancel_provider(
                actual.request, prepared["request_id"], value
            )
            == cancelled
        )


def test_actual_authentication_and_global_command_namespace_refuse_conflicts(
    tmp_path, monkeypatch
):
    with provider_context(tmp_path, monkeypatch) as actual:
        for request in (
            replace(actual.request, csrf_verified=False),
            replace(actual.request, origin="https://elsewhere.invalid"),
            replace(actual.request, method="GET"),
        ):
            with pytest.raises(DeploymentPrepareError) as caught:
                actual.service.prepare_provider(request, actual.payload)
            assert caught.value.code == "access_denied"
        receipt = actual.service.prepare_provider(actual.request, actual.payload)
        for value in (
            {**actual.payload, "expires_in_seconds": 61},
            {**actual.payload, "slot_id": 2},
        ):
            with pytest.raises(DeploymentPrepareError) as caught:
                actual.service.prepare_provider(actual.request, value)
            assert caught.value.code == "conflict"
        with pytest.raises(DeploymentPrepareError) as caught:
            actual.service.cancel_provider(
                actual.request,
                receipt["request_id"],
                {
                    "command_id": actual.payload["command_id"],
                    "request_digest": receipt["request_digest"],
                    "expected_revision": 1,
                },
            )
        assert caught.value.code == "conflict"


def test_two_actual_services_compete_for_one_permanent_reservation(
    tmp_path, monkeypatch
):
    with provider_context(tmp_path, monkeypatch) as actual:
        second = borrowed_service(actual)
        barrier = Barrier(2)

        def invoke(service):
            barrier.wait(timeout=5)
            try:
                return service.prepare_provider(actual.request, actual.payload)
            except DeploymentPrepareError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(invoke, service) for service in (actual.service, second)
            ]
            results = [future.result(timeout=30) for future in futures]
        receipts = [result for result in results if type(result) is dict]
        assert receipts and all(receipt == receipts[0] for receipt in receipts)
        assert all(
            type(result) is dict or result in {"capacity", "dependency_unavailable"}
            for result in results
        )
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_requests"
                ).fetchone()[0]
                == 1
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_provider_context_documents"
                ).fetchone()[0]
                == 18
            )
        assert second.prepare_provider(actual.request, actual.payload) == receipts[0]


@pytest.mark.parametrize("target", ["context", "slot"])
def test_final_writer_rechecks_sources_after_actual_blob_presealing(
    tmp_path, monkeypatch, target
):
    with provider_context(tmp_path, monkeypatch) as actual:
        original = actual.domain.put_blob
        calls = []

        def seal(raw, **kwargs):
            blob = original(raw, **kwargs)
            calls.append(blob)
            if len(calls) == 20:
                if target == "context":
                    actual.context.close()
                else:
                    actual.tree.actual(
                        __import__("pathlib").Path("/run/deeptwin/ipc/xs01")
                    ).chmod(0o750)
            return blob

        monkeypatch.setattr(actual.domain, "put_blob", seal)
        with pytest.raises(DeploymentPrepareError) as caught:
            actual.service.prepare_provider(actual.request, actual.payload)
        assert caught.value.code == "dependency_unavailable"
        with actual.domain._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_requests"
                ).fetchone()[0]
                == 0
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_provider_contexts"
                ).fetchone()[0]
                == 0
            )


@pytest.mark.parametrize(
    "target",
    [
        "provider_contexts",
        "provider_context_documents",
        "requests",
        "provider_requests",
        "lifecycle",
        "heads",
        "commands",
    ],
)
def test_failed_authority_write_rolls_back_whole_provider_admission(
    tmp_path, monkeypatch, target
):
    import sqlite3

    from app.deployment import prepare_storage as storage

    with provider_context(tmp_path, monkeypatch) as actual:
        original = storage.insert

        def fail_after_write(db, table, values):
            result = original(db, table, values)
            if table == target:
                raise sqlite3.OperationalError("injected authority write failure")
            return result

        monkeypatch.setattr(storage, "insert", fail_after_write)
        with pytest.raises(DeploymentPrepareError):
            actual.service.prepare_provider(actual.request, actual.payload)
        with actual.domain._connection() as db:
            assert all(
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_" + table
                ).fetchone()[0]
                == 0
                for table in storage.TABLES_V4
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM domain_records WHERE kind='deployment_request'"
                ).fetchone()[0]
                == 0
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM api_event_envelopes WHERE event_type LIKE 'deployment.%'"
                ).fetchone()[0]
                == 0
            )
