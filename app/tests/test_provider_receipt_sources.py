"""Real retained incoming bytes and owned channel lifetime."""

import pytest
from app.tests.provider_receipt_fixture import (
    provider_receipt_context,
    signed_receipt,
    install_receipt,
)
from app.deployment.provider_receipt_sources import open_provider_receipt_channels
from app.deployment import contracts as c
from app.domain.refs import canonical_json
from uuid import uuid4
from pathlib import Path
from app.operations.setup import parse_base64url_32
import os


def test_consumed_projection_is_exact_and_repeat_observation(tmp_path, monkeypatch):
    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        raw = signed_receipt(actual, request, outcome="failed")
        digest = install_receipt(actual, raw)
        marker = canonical_json(
            {
                "schema": "deployment-provider-consumption-v1",
                "domain": "deeptwin-deployment-provider-consumption-v1",
                "consumption_id": str(uuid4()),
                **{
                    k: request[k]
                    for k in (
                        "request_id",
                        "request_digest",
                        "instance_id",
                        "origin_profile_digest",
                    )
                },
                "receipt_digest": digest,
                "source_context_sha256": actual.payload["source_context_sha256"],
                "preserved_inventory_sha256": request["effect_payload"][
                    "preserved_inventory_sha256"
                ],
                "winning_lifecycle_revision": 2,
                "consumed_at": request["created_at"],
                "outcome": "failed",
            }
        )
        channels = open_provider_receipt_channels(
            actual.context, profile=actual.profile
        )
        try:
            first = channels.publish_consumed(
                receipt_digest=digest, expected_payloads=(marker,)
            )
            second = channels.publish_consumed(
                receipt_digest=digest, expected_payloads=(marker,)
            )
            assert first == second
            assert first.role == "consumed" and first.size_bytes == len(marker)
        finally:
            channels.close()


def test_actual_selected_bytes_busy_guard_and_borrowed_context(tmp_path, monkeypatch):
    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        raw = signed_receipt(actual, request)
        digest = install_receipt(actual, raw)
        baseline = len(actual.tree.live)
        channels = open_provider_receipt_channels(
            actual.context, profile=actual.profile
        )
        assert channels is not None
        try:
            identity = channels.recheck_current()
            assert (
                identity.as_dict()["source_context_sha256"]
                == actual.payload["source_context_sha256"]
            )
            leaf = channels.open_receipt(digest)
            try:
                assert leaf.receipt_bytes == raw
                with pytest.raises(c.DeploymentSourceError):
                    channels.open_receipt(digest)
            finally:
                leaf.close()
        finally:
            channels.close()
        assert len(actual.tree.live) == baseline
        assert actual.context.read_current() == actual.tree.bundle


@pytest.mark.parametrize(
    "mutation", ["replace", "mode", "link", "size", "bytes", "unlink", "root"]
)
def test_selected_receipt_and_channel_currentness_rejects_changes(
    tmp_path, monkeypatch, mutation
):
    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        raw = signed_receipt(actual, request)
        digest = install_receipt(actual, raw)
        path = actual.tree.actual(
            Path("/run/deeptwin/provider-deployment-receipts/receipts")
            / (parse_base64url_32(digest).hex() + ".json")
        )
        channels = open_provider_receipt_channels(
            actual.context, profile=actual.profile
        )
        leaf = channels.open_receipt(digest)
        try:
            if mutation == "mode":
                path.chmod(0o640)
            elif mutation == "link":
                os.link(path, path.with_suffix(".copy"))
            elif mutation == "unlink":
                path.unlink()
            elif mutation == "root":
                path.parent.rename(path.parent.with_name("moved-receipts"))
                path.parent.mkdir(mode=0o750)
            elif mutation == "replace":
                path.unlink()
                path.write_bytes(raw)
                path.chmod(0o440)
            else:
                path.chmod(0o640)
                path.write_bytes(raw + b" " if mutation == "size" else b"x" * len(raw))
                path.chmod(0o440)
            with pytest.raises(c.DeploymentSourceError):
                leaf.recheck_current()
        finally:
            leaf.close()
            channels.close()


def test_acquisition_faults_close_each_owned_directory_and_preserve_primary(
    tmp_path, monkeypatch
):
    from app.deployment import files

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        baseline = set(actual.tree.live)
        original = files.Directory.open
        for target in range(1, 5):
            seen = []
            primary = KeyboardInterrupt("acquisition interrupted")

            def opened(*args, **kwargs):
                seen.append(args[0])
                if len(seen) == target:
                    raise primary
                return original(*args, **kwargs)

            with monkeypatch.context() as fault:
                fault.setattr(files.Directory, "open", opened)
                with pytest.raises(KeyboardInterrupt) as caught:
                    open_provider_receipt_channels(
                        actual.context, profile=actual.profile
                    )
                assert caught.value is primary
            assert set(actual.tree.live) == baseline
            assert actual.context.read_current() == actual.tree.bundle


def test_full_240_opaque_entries_and_selected_receipt_stay_bounded(
    tmp_path, monkeypatch
):
    from app.tests.provider_source_reader_fixture import CHANNELS

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        raw = signed_receipt(actual, request)
        digest = install_receipt(actual, raw)
        for root, namespace, uid, ro, limit, cap in CHANNELS:
            existing = len(list(actual.tree.actual(root / namespace).glob("*.json")))
            for number in range(1, limit - existing + 1):
                actual.tree.payload(namespace, number, raw=b"opaque not receipt JSON")
            for number in range(1, 33):
                actual.tree.payload(namespace, number, stage=True)
        channels = open_provider_receipt_channels(
            actual.context, profile=actual.profile
        )
        try:
            leaf = channels.open_receipt(digest)
            try:
                assert leaf.receipt_bytes == raw
                assert actual.tree.peak <= 256
                print(
                    f"Task43 measured file/scandir FD peak={actual.tree.peak}; full namespace entries=240"
                )
            finally:
                leaf.close()
        finally:
            channels.close()
        overflow = actual.tree.payload("receipts", 999)
        with pytest.raises(c.DeploymentSourceError):
            open_provider_receipt_channels(actual.context, profile=actual.profile)
        assert overflow.exists()


def test_hollow_subclass_closed_channels_fail_without_authority(tmp_path, monkeypatch):
    from app.deployment.provider_receipt_sources import ProviderReceiptChannels
    from app.domain.refs import parse_canonical

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        digest = install_receipt(
            actual, signed_receipt(actual, request, outcome="failed")
        )
        actual.service.import_provider_receipt(
            actual.request,
            prepared["request_id"],
            {
                "command_id": str(uuid4()),
                "request_digest": prepared["request_digest"],
                "receipt_digest": digest,
                "expected_revision": 1,
            },
        )
        namespace = actual.tree.actual(
            Path("/run/deeptwin/provider-deployment-consumed/consumed")
        )
        raw = next(namespace.glob("*.json")).read_bytes()
        assert parse_canonical(raw)["receipt_digest"] == digest
        channels = open_provider_receipt_channels(
            actual.context, profile=actual.profile
        )
        channels.close()

        class Pretender(ProviderReceiptChannels):
            pass

        for value in (
            object.__new__(ProviderReceiptChannels),
            object.__new__(Pretender),
            channels,
        ):
            with pytest.raises(c.DeploymentSourceError):
                value.publish_consumed(receipt_digest=digest, expected_payloads=(raw,))
        assert actual.context.read_current() == actual.tree.bundle
