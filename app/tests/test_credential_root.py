import json
import os
from uuid import uuid4

import pytest


def initialized(tmp_path):
    from app.operations.credential_root_init import initialize_credential_root
    args = dict(root_directory=tmp_path / "root", records_directory=tmp_path / "records",
                vault_id=str(uuid4()), expected_uid=os.getuid(), expected_gid=os.getgid())
    initialize_credential_root(**args)
    return args


def test_genesis_pair_is_strict_and_serving_never_initializes(tmp_path):
    from app.workers.credential_vault import CredentialVault, CredentialVaultError
    args = initialized(tmp_path)
    assert (args["root_directory"] / "root.key").stat().st_size == 32
    assert (args["root_directory"] / "root.key").stat().st_mode & 0o777 == 0o400
    with CredentialVault(**args) as vault:
        assert vault.health()["stored_unbound"] == 0
    with pytest.raises(CredentialVaultError):
        CredentialVault(str(tmp_path / "legacy"))
    assert not (tmp_path / "legacy").exists()


def test_initializer_noop_and_partial_legacy_preservation(tmp_path):
    from app.operations.credential_root_init import initialize_credential_root
    from app.workers.credential_vault import CredentialVault, CredentialVaultError
    args = initialized(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    initialize_credential_root(**args)
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    legacy = tmp_path / "legacy"
    legacy.mkdir(mode=0o700)
    (legacy / "index.json").write_bytes(b'legacy-secret-bytes')
    with pytest.raises(CredentialVaultError):
        CredentialVault(**(args | {"records_directory": legacy}))
    assert (legacy / "index.json").read_bytes() == b'legacy-secret-bytes'


def test_root_envelope_authentication_and_maximum_secret(tmp_path):
    from app.workers.credential_root import CredentialRoot
    from app.workers.credential_vault import CredentialVaultError
    args = initialized(tmp_path)
    metadata = dict(command_id=str(uuid4()), record_id=str(uuid4()), record_version=1,
                    provider="claude", auth_mode="api", created_at="2026-09-19T00:00:00.000000Z", predecessor=None)
    with CredentialRoot(**args) as root:
        payload = root.seal(metadata, b"x" * 65536, b"n" * 24)
        assert len(payload) <= 96 * 1024
        assert root.open(payload, metadata) == b"x" * 65536
        value = json.loads(payload)
        value["header"]["provider"] = "codex"
        altered = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        with pytest.raises(CredentialVaultError):
            root.open(altered, metadata)
        with pytest.raises(CredentialVaultError):
            root.open(b" " + payload, metadata)


@pytest.mark.parametrize("damage", ["missing_key", "wrong_key", "key_mode", "root_mode", "key_link", "key_hardlink", "records_link", "owner", "layout_swap", "partial", "journal_link", "lock_mode"])
def test_invalid_pair_refused_without_repair(tmp_path, damage):
    from app.workers.credential_vault import CredentialVault, CredentialVaultError
    args = initialized(tmp_path)
    root, records = args["root_directory"], args["records_directory"]
    if damage == "missing_key":
        (root / "root.key").unlink()
    elif damage == "wrong_key":
        (root / "root.key").chmod(0o600)
        (root / "root.key").write_bytes(b"x" * 32)
        (root / "root.key").chmod(0o400)
    elif damage == "key_mode":
        (root / "root.key").chmod(0o600)
    elif damage == "root_mode":
        root.chmod(0o755)
    elif damage in ("key_link", "key_hardlink"):
        target = tmp_path / "saved-key"
        (root / "root.key").rename(target)
        if damage == "key_link":
            (root / "root.key").symlink_to(target)
        else:
            os.link(target, root / "root.key")
    elif damage == "records_link":
        target = tmp_path / "records-link"
        target.symlink_to(records, target_is_directory=True)
        args["records_directory"] = target
    elif damage == "owner":
        args["expected_uid"] = os.getuid() + 1
    elif damage == "layout_swap":
        other = tmp_path / "other"
        other.mkdir()
        other_args = initialized(other)
        (records / "layout.json").write_bytes((other_args["records_directory"] / "layout.json").read_bytes())
    elif damage == "partial":
        (records / "layout.json").unlink()
    elif damage == "journal_link":
        target = tmp_path / "saved-journal"
        (records / "journal.sqlite").rename(target)
        (records / "journal.sqlite").symlink_to(target)
    else:
        (records / "mutation.lock").chmod(0o644)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(CredentialVaultError):
        CredentialVault(**args)
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("relation", ["identical", "root_parent", "records_parent", "alias"])
def test_genesis_rejects_overlapping_directories_before_writes(tmp_path, relation):
    from app.operations.credential_root_init import initialize_credential_root
    from app.workers.credential_vault import CredentialVaultError
    root, records = tmp_path / "root", tmp_path / "records"
    if relation == "identical":
        records = root
    elif relation == "root_parent":
        records = root / "records"
    elif relation == "records_parent":
        root = records / "root"
    else:
        root.mkdir(mode=0o700)
        records.symlink_to(root, target_is_directory=True)
    before = set(tmp_path.iterdir())
    with pytest.raises(CredentialVaultError):
        initialize_credential_root(root, records, vault_id=str(uuid4()), expected_uid=os.getuid(), expected_gid=os.getgid())
    assert set(tmp_path.iterdir()) == before


def test_lifecycle_excludes_maintenance_until_close(tmp_path):
    import fcntl
    from app.workers.credential_vault import CredentialVault
    args = initialized(tmp_path)
    vault = CredentialVault(**args)
    fd = os.open(args["records_directory"] / "lifecycle.lock", os.O_RDWR)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        vault.close()
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        vault.close()
        os.close(fd)


@pytest.mark.parametrize("field,value", [("record_version", True), ("record_version", 0), ("record_version", 2**63),
    ("record_id", "00000000-0000-0000-0000-000000000000"), ("created_at", "2026-02-30T00:00:00.000000Z"),
    ("auth_mode", "subscription"), ("algorithm_id", "aes"), ("schema", "credential-record-v2"), ("extra", "bad")])
def test_strict_header_rejects_mutations(tmp_path, field, value):
    from app.workers.credential_root import CredentialRoot
    from app.workers.credential_vault import CredentialVaultError
    from app.tests.test_credential_custody import metadata
    args, meta = initialized(tmp_path), metadata()
    with CredentialRoot(**args) as root:
        payload = json.loads(root.seal(meta, b"synthetic", b"n" * 24))
        payload["header"][field] = value
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        with pytest.raises(CredentialVaultError):
            root.open(raw, meta)


@pytest.mark.parametrize("damage", ["duplicate", "extra", "padded", "nonce_short", "cipher_short", "tag", "truncated", "oversize", "swapped"])
def test_strict_envelope_rejects_encoding_and_authentication_damage(tmp_path, damage):
    from app.workers.credential_root import CredentialRoot
    from app.workers.credential_vault import CredentialVaultError
    from app.tests.test_credential_custody import metadata
    args, meta = initialized(tmp_path), metadata()
    with CredentialRoot(**args) as root:
        raw = root.seal(meta, b"synthetic", b"n" * 24)
        value = json.loads(raw)
        if damage == "duplicate":
            raw = raw[:-1] + b',"nonce_b64u":"bm5ubm5ubm5ubm5ubm5ubm5ubm5ubm5u"}'
        elif damage == "extra":
            value["extra"] = 1
        elif damage == "padded":
            value["ciphertext_b64u"] += "="
        elif damage == "nonce_short":
            value["nonce_b64u"] = "bm4"
        elif damage == "cipher_short":
            value["ciphertext_b64u"] = "bm4"
        elif damage == "tag":
            value["ciphertext_b64u"] = ("A" if value["ciphertext_b64u"][0] != "A" else "B") + value["ciphertext_b64u"][1:]
        elif damage == "truncated":
            raw = raw[:-20]
        elif damage == "oversize":
            raw = b"x" * (96 * 1024 + 1)
        else:
            other = metadata()
            value["ciphertext_b64u"] = json.loads(root.seal(other, b"synthetic-other", b"q" * 24))["ciphertext_b64u"]
        if damage not in ("duplicate", "truncated", "oversize"):
            raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        with pytest.raises(CredentialVaultError):
            root.open(raw, meta)


def test_complete_root_cannot_initialize_another_records_directory(tmp_path):
    from app.operations.credential_root_init import initialize_credential_root
    from app.workers.credential_vault import CredentialVaultError
    args = initialized(tmp_path)
    other = tmp_path / "other-records"
    with pytest.raises(CredentialVaultError):
        initialize_credential_root(**(args | {"records_directory": other}))
    assert not other.exists()


def _initialize_process(args, barrier, output):
    from app.operations.credential_root_init import initialize_credential_root
    from app.workers.credential_vault import CredentialVaultError
    barrier.wait(5)
    try:
        output.put({"ok": initialize_credential_root(**args)["storage_id"]})
    except CredentialVaultError as exc:
        output.put({"error": exc.code})


@pytest.mark.parametrize("race", ["same_pair", "same_root", "same_records"])
def test_independent_process_genesis_exclusion(tmp_path, race):
    import multiprocessing
    from app.workers.credential_vault import CredentialVault
    context = multiprocessing.get_context("spawn")
    barrier, output = context.Event(), context.Queue()
    args = dict(root_directory=tmp_path / "root", records_directory=tmp_path / "records",
                vault_id=str(uuid4()), expected_uid=os.getuid(), expected_gid=os.getgid())
    other = dict(args)
    if race == "same_root":
        other["records_directory"] = tmp_path / "other-records"
    elif race == "same_records":
        other["root_directory"] = tmp_path / "other-root"
    children = [context.Process(target=_initialize_process, args=(item, barrier, output)) for item in (args, other)]
    for child in children:
        child.start()
    barrier.set()
    try:
        results = [output.get(timeout=15) for _ in children]
        assert sum("ok" in value for value in results) == (2 if race == "same_pair" else 1), results
        if race == "same_pair":
            assert results[0] == results[1]
        else:
            assert {value.get("error") for value in results} == {None, "maintenance_required"}
        opened = 0
        for item in (args, other):
            from app.workers.credential_vault import CredentialVaultError
            try:
                with CredentialVault(**item):
                    opened += 1
            except CredentialVaultError:
                pass
        assert opened == (2 if race == "same_pair" else 1)
    finally:
        for child in children:
            child.join(5)
            if child.is_alive():
                child.terminate()
                child.join(3)
            assert child.exitcode == 0
            child.close()
        output.close()
        output.join_thread()


def test_initialized_pair_change_during_vault_lifetime_is_rejected(tmp_path):
    from app.workers.credential_vault import CredentialVault, CredentialVaultError
    from app.tests.test_credential_custody import metadata
    args = initialized(tmp_path)
    with CredentialVault(**args) as vault:
        (args["root_directory"] / "root.key").chmod(0o600)
        with pytest.raises(CredentialVaultError):
            vault.store_at(metadata=metadata(), secret=b"synthetic")


@pytest.mark.parametrize("target", ["mutation.lock", "lifecycle.lock", "journal.sqlite"])
def test_replaced_fixed_inode_is_refused(tmp_path, target):
    from app.workers.credential_vault import CredentialVault, CredentialVaultError
    from app.tests.test_credential_custody import metadata
    args = initialized(tmp_path)
    with CredentialVault(**args) as vault:
        original = args["records_directory"] / target
        data = original.read_bytes()
        original.rename(tmp_path / "old-inode")
        original.write_bytes(data)
        original.chmod(0o600)
        with pytest.raises(CredentialVaultError):
            vault.query_record(metadata=metadata())


def test_initializer_partial_records_never_creates_root_material(tmp_path):
    from app.operations.credential_root_init import initialize_credential_root
    from app.workers.credential_vault import CredentialVaultError
    records = tmp_path / "records"
    records.mkdir(mode=0o700)
    (records / "layout.json").write_bytes(b"partial")
    (records / "layout.json").chmod(0o600)
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    with pytest.raises(CredentialVaultError):
        initialize_credential_root(root, records, vault_id=str(uuid4()), expected_uid=os.getuid(), expected_gid=os.getgid())
    assert list(root.iterdir()) == []
    assert (records / "layout.json").read_bytes() == b"partial"


@pytest.mark.parametrize("damage", ["mode", "symlink", "hardlink", "group"])
def test_journal_sidecars_and_group_refused_before_sqlite_open(tmp_path, damage):
    from app.workers.credential_vault import CredentialVault, CredentialVaultError
    args = initialized(tmp_path)
    sidecar = args["records_directory"] / "journal.sqlite-journal"
    if damage == "symlink":
        sidecar.symlink_to(args["records_directory"] / "layout.json")
    elif damage == "hardlink":
        os.link(args["records_directory"] / "layout.json", sidecar)
    elif damage == "mode":
        sidecar.write_bytes(b"synthetic")
        sidecar.chmod(0o644)
    else:
        args["expected_gid"] = os.getgid() + 1
    journal_before = (args["records_directory"] / "journal.sqlite").read_bytes()
    with pytest.raises(CredentialVaultError):
        CredentialVault(**args)
    assert (args["records_directory"] / "journal.sqlite").read_bytes() == journal_before


def test_envelope_is_independently_decryptable_with_separate_nonce(tmp_path):
    import base64
    from nacl.secret import Aead
    from app.workers.credential_root import CredentialRoot
    from app.tests.test_credential_custody import metadata
    args, meta = initialized(tmp_path), metadata()
    with CredentialRoot(**args) as root:
        payload = json.loads(root.seal(meta, b"x" * 65536, b"n" * 24))
    ciphertext = base64.urlsafe_b64decode(payload["ciphertext_b64u"] + "=")
    nonce = base64.urlsafe_b64decode(payload["nonce_b64u"])
    assert len(ciphertext) == 65552 and len(nonce) == 24
    aad = json.dumps(payload["header"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert Aead((args["root_directory"] / "root.key").read_bytes()).decrypt(ciphertext, aad, nonce) == b"x" * 65536
