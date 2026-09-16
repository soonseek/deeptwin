"""Actual selected receipt files stay inert until later admission authority."""

import builtins
import copy
import hashlib
import json
import os
import pickle
import subprocess
import sys
import textwrap
from base64 import urlsafe_b64encode

import pytest

from app.domain.refs import canonical_json
from app.tests.deployment_receipt_source_fixture import (
    actual_portable_receipt_ingress as actual_portable_receipt_ingress,  # noqa: PLC0414
)
from app.tests.deployment_receipt_source_fixture import (
    actual_receipt_ingress as actual_receipt_ingress,  # noqa: PLC0414
)
from app.tests.deployment_source_fixture import ROOT, module


def _selector(raw):
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _changed_receipt(actual, field, value):
    parsed = json.loads(actual.receipt_bytes)
    parsed[field] = value
    return canonical_json(parsed)


def test_selected_receipt_lease_retains_actual_bytes_digest_and_file_identity(
    actual_receipt_ingress,
):
    actual = actual_receipt_ingress
    actual.add_final()
    source = actual.open()
    lease = source.open_receipt(actual.receipt_digest)
    initial = lease.file_identity
    assert lease.receipt_bytes == actual.receipt_bytes
    assert lease.recheck_current() == initial
    assert lease.receipt_digest == actual.receipt_digest
    source.close()
    with pytest.raises(actual.c.DeploymentSourceError):
        _ = lease.receipt_bytes
    with pytest.raises(actual.c.DeploymentSourceError):
        _ = lease.receipt_digest
    with pytest.raises(actual.c.DeploymentSourceError):
        _ = lease.file_identity
    lease.close()
    lease.close()


def test_public_construction_copy_and_pickle_never_supply_receipt_lease(
    actual_receipt_ingress,
):
    actual, receipt_sources = actual_receipt_ingress, module("receipt_sources")
    actual.add_final()
    with pytest.raises(TypeError):
        receipt_sources.ReceiptFileLease()
    with (
        actual.open() as source,
        source.open_receipt(actual.receipt_digest) as lease,
        source.open_receipt(actual.receipt_digest) as second,
    ):
        observation = lease.file_identity
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with pytest.raises(TypeError):
                operation(lease)
        assert copy.copy(observation) == observation
        assert second.file_identity == observation
        with pytest.raises(actual.c.DeploymentSourceError):
            source.open_receipt(observation)


def test_portable_public_fixture_selected_receipt_is_a_real_retained_lease(
    actual_portable_receipt_ingress,
):
    actual = actual_portable_receipt_ingress
    actual.add_final()
    with (
        actual.open() as source,
        source.open_receipt(actual.receipt_digest) as lease,
    ):
        assert lease.receipt_bytes == actual.receipt_bytes
        assert lease.receipt_digest == actual.receipt_digest


@pytest.mark.parametrize(
    "selector",
    [
        b"not-text",
        "A" * 42 + "B",
        "A" * 43 + "=",
        "/" * 43,
        "00" * 32,
        "",
    ],
)
def test_receipt_selector_rejects_type_padding_padbits_slash_and_hex(
    actual_receipt_ingress, selector
):
    actual = actual_receipt_ingress
    actual.add_final()
    with actual.open() as source, pytest.raises(actual.c.DeploymentSourceError):
        source.open_receipt(selector)


def test_missing_selected_final_is_a_source_failure(actual_receipt_ingress):
    actual = actual_receipt_ingress
    with (
        actual.open() as source,
        pytest.raises(actual.c.DeploymentSourceError) as error,
    ):
        source.open_receipt(_selector(b"m" * 32))
    assert error.type is actual.c.DeploymentSourceError


def test_filename_and_complete_byte_digest_mismatch_is_not_wire_invalid(
    actual_receipt_ingress,
):
    actual = actual_receipt_ingress
    wrong = "0" * 64
    actual.add_final(digest_hex=wrong)
    with (
        actual.open() as source,
        pytest.raises(actual.c.DeploymentSourceError) as error,
    ):
        source.open_receipt(_selector(bytes.fromhex(wrong)))
    assert error.type is actual.c.DeploymentSourceError


@pytest.mark.parametrize(
    "change", ["bom", "duplicate", "noncanonical", "unknown", "bad_signature"]
)
def test_intrinsically_invalid_selected_wire_has_narrow_source_subtype(
    actual_receipt_ingress, change
):
    actual = actual_receipt_ingress
    if change == "bom":
        payload = b"\xef\xbb\xbf" + actual.receipt_bytes
    elif change == "duplicate":
        payload = actual.receipt_bytes.replace(
            b"{", b'{"schema":"deployment-receipt-v1",', 1
        )
    elif change == "noncanonical":
        payload = actual.receipt_bytes + b"\n"
    elif change == "bad_signature":
        payload = _changed_receipt(actual, "signature", "A" * 85 + "B")
    else:
        parsed = json.loads(actual.receipt_bytes)
        parsed["unknown_selected_field"] = "must-not-be-reflected"
        payload = canonical_json(parsed)
    path = actual.add_final(payload)
    with (
        actual.open() as source,
        pytest.raises(
            module("receipt_sources").DeploymentReceiptInvalid,
            match="^deployment_receipt_invalid$",
        ) as error,
    ):
        source.open_receipt(_selector(bytes.fromhex(path.stem)))
    assert error.value.code == "deployment_receipt_invalid"
    assert "must-not-be-reflected" not in str(error.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("instance_id", "9" * 32),
        ("origin_profile_digest", _selector(b"o" * 32)),
        ("deployment_profile_id", "portable-compose-v1"),
        ("trust_set_digest", _selector(b"t" * 32)),
    ],
)
def test_structurally_valid_foreign_j_bindings_remain_source_failures(
    actual_receipt_ingress, field, value
):
    actual = actual_receipt_ingress
    payload = _changed_receipt(actual, field, value)
    path = actual.add_final(payload)
    with (
        actual.open() as source,
        pytest.raises(actual.c.DeploymentSourceError) as error,
    ):
        source.open_receipt(_selector(bytes.fromhex(path.stem)))
    assert error.type is actual.c.DeploymentSourceError


def test_unverified_structurally_valid_signature_is_an_inert_observation(
    actual_receipt_ingress, monkeypatch
):
    actual = actual_receipt_ingress
    payload = _changed_receipt(actual, "signature", _selector(b"s" * 64))
    path = actual.add_final(payload)
    receipt_contracts = module("receipt_contracts")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("signature authority was called")

    monkeypatch.setattr(receipt_contracts, "verify_receipt", forbidden)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "nacl" or name.startswith("nacl."):
            raise AssertionError("crypto dependency was imported")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with (
        actual.open() as source,
        source.open_receipt(_selector(bytes.fromhex(path.stem))) as lease,
    ):
        assert lease.receipt_bytes == payload


@pytest.mark.parametrize("change", ["mode", "owner", "group", "hardlink", "symlink"])
def test_unsafe_selected_metadata_never_returns_a_lease(actual_receipt_ingress, change):
    actual = actual_receipt_ingress
    path = actual.add_final()
    if change == "mode":
        path.chmod(0o640)
    elif change in {"owner", "group"}:
        info = os.stat(path, follow_symlinks=False)
        actual.metadata[(info.st_dev, info.st_ino)] = (
            99 if change == "owner" else 20113,
            99 if change == "group" else 21201,
        )
    elif change == "hardlink":
        os.link(path, path.with_name("link"))
    else:
        path.rename(path.with_name("actual"))
        path.symlink_to(path.with_name("actual"))
    with pytest.raises(actual.c.DeploymentSourceError) as error:
        actual.open()
    assert error.type is actual.c.DeploymentSourceError


@pytest.mark.parametrize(
    "change",
    [
        "named_swap",
        "same_length_bytes",
        "mode",
        "owner",
        "group",
        "link",
        "incoming_root",
        "namespace",
        "source",
    ],
)
def test_lease_recheck_never_refreshes_after_file_or_owner_drift(
    actual_receipt_ingress, change
):
    actual = actual_receipt_ingress
    path = actual.add_final()
    with actual.open() as source:
        lease = source.open_receipt(actual.receipt_digest)
        try:
            if change == "named_swap":
                path.rename(path.with_name("old-receipt"))
                actual.add_final()
            elif change == "same_length_bytes":
                path.chmod(0o640)
                path.write_bytes(b"x" * len(actual.receipt_bytes))
                path.chmod(0o440)
            elif change == "mode":
                path.chmod(0o640)
            elif change == "owner":
                info = os.stat(path, follow_symlinks=False)
                actual.metadata[(info.st_dev, info.st_ino)] = 99, 21201
            elif change == "group":
                info = os.stat(path, follow_symlinks=False)
                actual.metadata[(info.st_dev, info.st_ino)] = 20113, 99
            elif change == "link":
                os.link(path, path.with_name("new-link"))
            elif change == "incoming_root":
                root = actual.actual(actual.incoming_root)
                root.rename(root.with_name("old-incoming"))
                root.mkdir(mode=0o750)
                actual.register(root, 20113, 21201)
                child = root / "receipts"
                child.mkdir(mode=0o750)
                actual.register(child, 20113, 21201)
                replacement = child / path.name
                replacement.write_bytes(actual.receipt_bytes)
                replacement.chmod(0o440)
                actual.register(replacement, 20113, 21201)
            elif change == "namespace":
                actual.receipts_path.rename(
                    actual.receipts_path.with_name("old-receipts")
                )
                actual.receipts_path.mkdir(mode=0o750)
                actual.register(actual.receipts_path, 20113, 21201)
                replacement = actual.receipts_path / path.name
                replacement.write_bytes(actual.receipt_bytes)
                replacement.chmod(0o440)
                actual.register(replacement, 20113, 21201)
            else:
                actual.replace_ingress()
            with pytest.raises(actual.c.DeploymentSourceError):
                lease.recheck_current()
            with pytest.raises(actual.c.DeploymentSourceError):
                _ = lease.receipt_bytes
        finally:
            lease.close()


def test_failed_selected_creation_closes_its_actual_file_descriptor(
    actual_receipt_ingress, monkeypatch
):
    actual = actual_receipt_ingress
    payload = b"invalid-but-digest-matching"
    actual.add_final(payload)
    opened = set()
    original_open, original_close = os.open, os.close

    def track_open(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.add(fd)
        return fd

    def track_close(fd):
        original_close(fd)
        opened.discard(fd)

    with actual.open() as source:
        monkeypatch.setattr(os, "open", track_open)
        monkeypatch.setattr(os, "close", track_close)
        with pytest.raises(module("receipt_sources").DeploymentReceiptInvalid):
            source.open_receipt(_selector(hashlib.sha256(payload).digest()))
        assert opened == set()


def test_named_swap_during_selected_open_closes_fd_and_fails_as_source(
    actual_receipt_ingress, monkeypatch
):
    actual = actual_receipt_ingress
    path = actual.add_final()
    original = actual.f._open_final

    def swap_after_open(*args, **kwargs):
        opened = original(*args, **kwargs)
        path.rename(path.with_name("old-during-open"))
        actual.add_final()
        return opened

    with actual.open() as source:
        monkeypatch.setattr(actual.f, "_open_final", swap_after_open)
        with pytest.raises(actual.c.DeploymentSourceError) as error:
            source.open_receipt(actual.receipt_digest)
    assert error.type is actual.c.DeploymentSourceError


def test_selected_file_change_after_real_structure_parse_is_not_returned(
    actual_receipt_ingress, monkeypatch
):
    actual = actual_receipt_ingress
    path = actual.add_final()
    receipt_sources = module("receipt_sources")
    real_parse = receipt_sources.parse_receipt

    def parse_then_change(raw):
        parsed = real_parse(raw)
        path.chmod(0o640)
        path.write_bytes(b"x" * len(raw))
        path.chmod(0o440)
        return parsed

    with actual.open() as source:
        monkeypatch.setattr(receipt_sources, "parse_receipt", parse_then_change)
        with pytest.raises(actual.c.DeploymentSourceError) as error:
            source.open_receipt(actual.receipt_digest)
    assert error.type is actual.c.DeploymentSourceError


@pytest.mark.parametrize("drift", ["selected_file", "ingress_j"])
def test_real_rejecting_parse_gives_source_drift_precedence_and_closes_fd(
    actual_receipt_ingress, monkeypatch, drift
):
    actual = actual_receipt_ingress
    payload = b"malformed-receipt-with-current-digest"
    path = actual.add_final(payload)
    selector = _selector(hashlib.sha256(payload).digest())
    receipt_sources = module("receipt_sources")
    receipt_contracts = module("receipt_contracts")
    real_parse = receipt_sources.parse_receipt
    opened = set()
    original_open, original_close = os.open, os.close

    def rejecting_parse_then_drift(raw):
        try:
            real_parse(raw)
        except receipt_contracts.ReceiptWireError:
            if drift == "selected_file":
                path.chmod(0o640)
                path.write_bytes(b"x" * len(raw))
                path.chmod(0o440)
            else:
                actual.replace_ingress()
            raise
        raise AssertionError("the actual malformed receipt unexpectedly parsed")

    def track_open(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.add(fd)
        return fd

    def track_close(fd):
        original_close(fd)
        opened.discard(fd)

    with actual.open() as source:
        monkeypatch.setattr(
            receipt_sources, "parse_receipt", rejecting_parse_then_drift
        )
        monkeypatch.setattr(os, "open", track_open)
        monkeypatch.setattr(os, "close", track_close)
        with pytest.raises(actual.c.DeploymentSourceError) as error:
            source.open_receipt(selector)
        assert error.type is actual.c.DeploymentSourceError
        assert opened == set()


def test_fresh_process_ingress_and_lease_path_imports_no_crypto_or_ipc(
    actual_receipt_ingress,
):
    actual = actual_receipt_ingress
    actual.add_final()
    script = textwrap.dedent(
        """
        import builtins
        import importlib
        import json
        import os
        import sys
        from pathlib import Path
        from types import SimpleNamespace

        from app.operations.setup import OriginProfile
        from app.deployment import contracts as c
        from app.deployment import files as f
        from app.deployment import mounts as m

        base = Path(sys.argv[1])
        recipe_pin, instance_pin, ingress_pin, selector = sys.argv[2:]
        profile = OriginProfile.from_dict(json.loads(sys.stdin.read()))
        logical_roots = (
            Path('/run/deeptwin/deployment-receipt-ingress'),
            Path('/run/deeptwin/deployment-receipts'),
            *c.BUILTIN_ROOTS,
        )
        real_stat, real_fstat = os.stat, os.fstat
        metadata = {}
        for index, logical in enumerate(logical_roots):
            actual_path = base.joinpath(*logical.parts[1:])
            info = real_stat(actual_path, follow_symlinks=False)
            metadata[(info.st_dev, info.st_ino)] = (
                (0, 21201) if index == 0 else
                (20113, 21201) if index == 1 else (20102, 20102)
            )
        for logical, owner in (
            (logical_roots[0] / 'ingress.json', (0, 21201)),
            (logical_roots[1] / 'receipts', (20113, 21201)),
        ):
            actual_path = base.joinpath(*logical.parts[1:])
            if actual_path.exists():
                info = real_stat(actual_path, follow_symlinks=False)
                metadata[(info.st_dev, info.st_ino)] = owner
        receipt_path = next((base / 'run/deeptwin/deployment-receipts/receipts').iterdir())
        info = real_stat(receipt_path, follow_symlinks=False)
        metadata[(info.st_dev, info.st_ino)] = (20113, 21201)

        def observed(info):
            uid, gid = metadata.get((info.st_dev, info.st_ino), (info.st_uid, info.st_gid))
            values = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
            return SimpleNamespace(**(values | {'st_uid': uid, 'st_gid': gid}))

        os.fstat = lambda fd: observed(real_fstat(fd))
        os.stat = lambda *args, **kwargs: observed(real_stat(*args, **kwargs))
        original_open_directory = f.open_directory
        f.open_directory = lambda path, **kwargs: original_open_directory(
            base.joinpath(*path.parts[1:]), **kwargs
        )
        device = real_stat(base).st_dev
        device_text = f'{os.major(device)}:{os.minor(device)}'
        lines = []
        for index, logical in enumerate(logical_roots, 1):
            lines.append(
                f'{index} 999 {device_text} /vol{index} {logical} '
                f"{'ro' if index <= 2 else 'rw'} - ext4 /dev/fake rw\\n"
            )
        m.native_platform = lambda: 'linux/amd64'
        m.read_mountinfo = lambda: m.parse_mountinfo(''.join(lines).encode())

        original_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name == 'nacl' or name.startswith('nacl.') or name.endswith('ipc_root'):
                raise AssertionError('forbidden authority import: ' + name)
            return original_import(name, *args, **kwargs)
        builtins.__import__ = guarded_import

        receipt_sources = importlib.import_module('app.deployment.receipt_sources')
        with receipt_sources.open_receipt_ingress_source(
            profile=profile,
            receipt_recipe_sha256=recipe_pin,
            receipt_instance_sha256=instance_pin,
            ingress_sha256=ingress_pin,
            protected_roots=(),
        ) as source:
            with source.open_receipt(selector) as lease:
                assert lease.receipt_bytes == receipt_path.read_bytes()
                lease.recheck_current()
        assert not any(name == 'nacl' or name.startswith('nacl.') for name in sys.modules)
        assert 'app.deployment.receipt_crypto' not in sys.modules
        assert 'app.workers.ipc_root' not in sys.modules
        print('fresh-retained-j-lease-ok')
        """
    )
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            script,
            str(actual.base),
            actual.pins["receipt_recipe_sha256"],
            actual.pins["receipt_instance_sha256"],
            actual.pins["ingress_sha256"],
            actual.receipt_digest,
        ],
        cwd=ROOT,
        input=json.dumps(actual.profile.as_dict()),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "fresh-retained-j-lease-ok\n"
