"""Synthetic deployment roots: no real deployment material is accessed."""
import hmac
import importlib
import json
import os
from base64 import urlsafe_b64encode

import pytest

from app.domain.refs import canonical_json
from app.operations.setup import OriginProfile


def profile():
    return OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=4193)


def test_root_genesis_is_readable_and_existing_state_is_never_replaced(tmp_path):
    root = importlib.import_module("app.operations.session_root")
    directory = tmp_path / "session-root"
    arguments = {"profile": profile(), "recovery_epoch": 1,
                     "expected_uid": os.getuid(), "expected_gid": os.getgid()}
    receipt = root.initialize_session_root(directory, **arguments)
    before = {name: (directory / name).read_bytes() for name in ("root.key", "manifest.json")}
    assert len(before["root.key"]) == 32
    assert root.initialize_session_root(directory, **arguments) == receipt
    assert before == {name: (directory / name).read_bytes() for name in before}
    handle = root.open_session_root(directory, **arguments)
    assert handle.receipt == receipt
    assert not hasattr(handle, "initialize")
    handle.close()
    with pytest.raises(root.SessionRootError):
        handle.derive_csrf("A" * 43)


def test_root_loader_refuses_same_size_key_corruption(tmp_path):
    root = importlib.import_module("app.operations.session_root")
    arguments = {"profile": profile(), "recovery_epoch": 1,
                     "expected_uid": os.getuid(), "expected_gid": os.getgid()}
    root.initialize_session_root(tmp_path / "root", **arguments)
    key = tmp_path / "root" / "root.key"
    key.chmod(0o600)
    key.write_bytes(bytes(32))
    key.chmod(0o400)
    with pytest.raises(root.SessionRootError):
        root.open_session_root(tmp_path / "root", **arguments)


@pytest.mark.parametrize("damage", ["missing_key", "missing_manifest", "mode", "directory_mode",
                                    "hardlink", "symlink", "manifest", "uid", "epoch", "profile"])
def test_root_reopen_never_repairs_damaged_or_mismatched_state(tmp_path, damage):
    root = importlib.import_module("app.operations.session_root")
    directory = tmp_path / "root"
    arguments = {"profile": profile(), "recovery_epoch": 1, "expected_uid": os.getuid(), "expected_gid": os.getgid()}
    root.initialize_session_root(directory, **arguments)
    if damage == "missing_key":
        (directory / "root.key").unlink()
    elif damage == "missing_manifest":
        (directory / "manifest.json").unlink()
    elif damage == "mode":
        (directory / "root.key").chmod(0o600)
    elif damage == "directory_mode":
        directory.chmod(0o755)
    elif damage == "hardlink":
        os.link(directory / "root.key", tmp_path / "linked-key")
    elif damage == "symlink":
        (directory / "root.key").rename(tmp_path / "key")
        (directory / "root.key").symlink_to(tmp_path / "key")
    elif damage == "manifest":
        manifest = directory / "manifest.json"
        manifest.chmod(0o600)
        manifest.write_bytes(manifest.read_bytes() + b" ")
        manifest.chmod(0o400)
    elif damage == "uid":
        arguments["expected_uid"] += 1
    elif damage == "epoch":
        arguments["recovery_epoch"] = 2
    else:
        arguments["profile"] = OriginProfile.local(instance_id="3" * 32, path_id="2" * 32, port=4193)
    before = {name: (directory / name).read_bytes() for name in os.listdir(directory)}
    for operation in (root.open_session_root, root.initialize_session_root):
        with pytest.raises(root.SessionRootError):
            operation(directory, **arguments)
    assert before == {name: (directory / name).read_bytes() for name in os.listdir(directory)}


def test_root_manifest_tag_and_csrf_match_independent_hmac(tmp_path):
    root = importlib.import_module("app.operations.session_root")
    arguments = {"profile": profile(), "recovery_epoch": 1, "expected_uid": os.getuid(), "expected_gid": os.getgid()}
    root.initialize_session_root(tmp_path / "root", **arguments)
    key = (tmp_path / "root" / "root.key").read_bytes()
    manifest = json.loads((tmp_path / "root" / "manifest.json").read_bytes())
    tag = manifest.pop("integrity_tag")
    encode = lambda value: urlsafe_b64encode(value).rstrip(b"=").decode()
    assert tag == encode(hmac.digest(key, canonical_json({"domain": "deeptwin-session-root-manifest-v1", "manifest": manifest}), "sha256"))
    handle = root.open_session_root(tmp_path / "root", **arguments)
    token = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    body = b'{"domain":"deeptwin-csrf-v1","origin_base":"http://11111111111111111111111111111111.localhost:4193/22222222222222222222222222222222/","recovery_epoch":1,"session_token_b64url":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}'
    assert handle.derive_csrf(token) == encode(hmac.digest(key, body, "sha256"))
    assert "integrity_tag" not in handle.receipt
    assert key.hex() not in repr(handle)
    handle.close()


def test_plain_handle_constructor_cannot_claim_verified_root_authority(tmp_path):
    root = importlib.import_module("app.operations.session_root")
    arguments = {"profile": profile(), "recovery_epoch": 1, "expected_uid": os.getuid(), "expected_gid": os.getgid()}
    root.initialize_session_root(tmp_path / "root", **arguments)
    manifest = json.loads((tmp_path / "root" / "manifest.json").read_bytes())
    with pytest.raises((root.SessionRootError, TypeError)):
        root.SessionRootHandle(b"x" * 32, manifest, profile(), _verified=True)
