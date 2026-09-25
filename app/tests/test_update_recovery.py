"""T072: the web-release update/recovery tooling over the T025 `DeploymentControlPort`.

Every case is offline and runs against a real served instance (a real `create_app`
start with an owner and a live session, then stopped). The deployment authority that
signs update receipts is played by an in-test Ed25519 key in a
`deployment-public-trust-set-v2` (recovery_fixture); nothing is pulled, installed or
started. The gate backups are real: the verified locked age 1.3.2 runtime
(DEEPTWIN_AGE_RUNTIME_ROOT) behind the same backup-crypto port the networkless worker
serves, with a real backup-key volume made by backup-key-init. Without that runtime the
backup-dependent cases skip and say so; the rest still run.
"""

import ast
import json
import os
import sqlite3
import sys
import time
from base64 import urlsafe_b64encode
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.deployment.prepare_contracts import stamp
from app.deployment.recovery_schema_exports import RECOVERY_ADAPTER, STAGE_ADAPTER
from app.domain import store as domain_store
from app.domain.refs import canonical_json, parse_canonical
from app.operations import recovery, updates
from app.operations.updates import UpdateError, UpdateStore
from app.server import create_app
from app.tests.recovery_fixture import Signer, receipt_for, trust_v2
from app.tests.test_deployment_control_tool import (
    assert_recovered_start,
    configuration,
    new_capability,
    served,
)
from app.tests.test_web_owner_integration import headers
from app.workers.backup_stream import REQUEST_SCHEMA as BACKUP_PROTOCOL

AGE_ROOT = os.environ.get("DEEPTWIN_AGE_RUNTIME_ROOT")
needs_age = pytest.mark.skipif(
    not AGE_ROOT, reason="DEEPTWIN_AGE_RUNTIME_ROOT (the verified locked age 1.3.2) is not set")
REPOSITORY = Path(__file__).resolve().parents[2]


def b64(raw):
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


# ---- the instance, the release inputs and the deployment authority ------------------------

def image_lock(release_id="1.1.0", services=None):
    return canonical_json({"schema": updates.IMAGE_LOCK_SCHEMA, "release_id": release_id,
                           "services": services or {"control": "sha256:" + "c" * 64,
                                                    "backup": "sha256:" + "b" * 64}})


def manifest(lock, *, release_id="1.1.0", data_schema=None, components=None):
    return canonical_json({
        "schema": updates.MANIFEST_SCHEMA, "release_id": release_id,
        "image_lock_set_sha256": sha256(lock).hexdigest(),
        "data_schema": data_schema if data_schema is not None else {
            "domain": [[1, domain_store.MIGRATION_SHA256], [2, domain_store.MIGRATION_2_SHA256]]},
        "components": components if components is not None else [
            {"component_id": "backup-crypto", "protocol": BACKUP_PROTOCOL}]})


class Instance:
    """A served, stopped instance with its update inputs and signer."""

    def __init__(self, tmp_path, *, v1=False):
        self.tmp = tmp_path
        self.state = served(tmp_path)
        if v1:
            downgrade_domain_to_v1(tmp_path / "data")
        self.lock = image_lock()
        self.manifest = manifest(self.lock)
        self.crypto = None
        self.probes = {"backup-crypto": lambda: {"protocol": BACKUP_PROTOCOL}}

    def tool(self):
        return updates.open_maintenance(
            data_dir=self.tmp / "data", session_root_dir=self.tmp / "root",
            deployment_config=self.state.config_path, work_dir=self.tmp / "work",
            expected_uid=os.getuid(), expected_gid=os.getgid())

    def prepare(self, manifest_bytes=None, lock=None):
        with self.tool() as maintenance:
            result = updates.prepare(maintenance, manifest_bytes=manifest_bytes or self.manifest,
                                     image_lock_bytes=lock or self.lock)
        return result, Path(result["request_path"]).read_bytes()

    def backup(self, **kwargs):
        with self.tool() as maintenance:
            return updates.backup(maintenance, crypto=self.crypto, probes=kwargs.pop("probes", self.probes),
                                  **kwargs)

    def cancel(self):
        with self.tool() as maintenance:
            return updates.cancel(maintenance)

    def migrate(self, receipt, *, trust=None, probes=None, steps=None):
        with self.tool() as maintenance:
            return updates.migrate(maintenance, receipt_bytes=receipt,
                                   trust_bytes=self.state.trust if trust is None else trust,
                                   probes=self.probes if probes is None else probes, steps=steps)

    def receipt(self, request_bytes, *, signer=None, trust=None, completed_ms=None, **changes):
        return update_receipt(self.state.profile, request_bytes, signer or self.state.signer,
                              self.state.trust if trust is None else trust, completed_ms=completed_ms, **changes)

    def db(self):
        db = sqlite3.connect(self.tmp / "data" / "intake.sqlite3")
        db.row_factory = sqlite3.Row
        return db

    def rows(self, query, args=()):
        with self.db() as db:
            return [tuple(row) for row in db.execute(query, args)]

    def head(self, request_id):
        with self.db() as db:
            return UpdateStore.head(db, request_id)

    def digest(self):
        with self.db() as db:
            return updates.state_digest(db)

    def domain_rows(self):
        return self.rows("SELECT version FROM domain_migrations ORDER BY version")

    def guidance(self):
        return recovery.guidance_for(self.tmp / "data")


def update_receipt(profile, request_bytes, signer, trust_bytes, *, completed_ms=None, **changes):
    request = parse_canonical(request_bytes)
    payload, preconditions = request["effect_payload"], request["preconditions"]
    unsigned = {
        "schema": updates.RECEIPT_SCHEMA, "domain": updates.RECEIPT_DOMAIN,
        "request_id": request["request_id"], "request_digest": request["request_digest"],
        "request_nonce": request["request_nonce"], "kind": "release_update",
        "instance_id": request["instance_id"], "origin_profile_digest": request["origin_profile_digest"],
        "deployment_profile_id": profile.deployment_profile_id, "operator_adapter": RECOVERY_ADAPTER,
        "operator_version": "1.0.0", "recovery_epoch": preconditions["current_recovery_epoch"],
        "previous_release_manifest_sha256": preconditions["current_release_manifest_sha256"],
        "release_manifest_sha256": payload["target_release_manifest_sha256"],
        "image_lock_set_sha256": payload["target_image_lock_set_sha256"], "outcome": "applied",
        "completed_at": stamp(time.time_ns() // 1_000_000 if completed_ms is None else completed_ms),
        "key_id": signer.key_id, "trust_set_digest": b64(sha256(trust_bytes).digest()),
        "trust_class": "instance_operator",
    }
    unsigned.update(changes)
    signature = b64(signer.key.sign(updates.receipt_preimage(unsigned)).signature)
    return canonical_json({**unsigned, "signature": signature})


def downgrade_domain_to_v1(data_dir):
    """A vault still at domain schema 1 (before the legacy-file CAS links)."""
    with sqlite3.connect(data_dir / "intake.sqlite3") as db:
        db.execute("DROP INDEX domain_legacy_files_work")
        db.execute("DROP TABLE domain_legacy_files")
        db.execute("DROP INDEX domain_files_identity")
        db.execute("DELETE FROM domain_migrations WHERE version=2")


def refused(code, action):
    with pytest.raises(UpdateError) as error:
        action()
    assert error.value.code == code, (error.value.code, error.value.detail)
    return error.value


@pytest.fixture(scope="module")
def age_runtime():
    from app.workers.backup_crypto import AgeRuntime

    return AgeRuntime.open(AGE_ROOT)


def with_worker_port(instance, age_runtime):
    """The backup-crypto port as the networkless worker serves it: the verified age
    runtime and the backup-key volume that only the worker holds."""
    from app.operations.backup import BackupKeyHandle, LocalAgeCrypto, age_keygen
    from app.operations.backup_key import initialize_backup_key

    volume = instance.tmp / "backup-key"
    volume.mkdir()
    initialize_backup_key(volume, keygen=age_keygen(age_runtime))
    instance.crypto = LocalAgeCrypto(age_runtime, BackupKeyHandle(volume))
    return instance


@pytest.fixture
def ready(tmp_path, age_runtime):
    """prepared + backup_verified over a domain-v1 vault, with its request bytes."""
    instance = with_worker_port(Instance(tmp_path, v1=True), age_runtime)
    result, request = instance.prepare()
    backed = instance.backup()
    assert backed["state"] == "backup_verified"
    return instance, result, request


# ---- the exact request --------------------------------------------------------------------

def test_the_request_binds_manifest_origin_image_lock_and_epoch(tmp_path):
    instance = Instance(tmp_path)
    result, request_bytes = instance.prepare()
    request = parse_canonical(request_bytes)
    profile = instance.state.profile
    assert request["kind"] == "release_update" and len(request["request_nonce"]) == 43
    assert request["instance_id"] == profile.instance_id
    assert request["origin_profile_digest"] == b64(bytes.fromhex(profile.digest))
    assert request["effect_payload"] == {
        "target_release_id": "1.1.0",
        "target_release_manifest_sha256": sha256(instance.manifest).hexdigest(),
        "target_image_lock_set_sha256": sha256(instance.lock).hexdigest(),
        "target_data_schema_sha256": updates.schema_sha256(parse_canonical(instance.manifest)["data_schema"]),
        "target_recovery_epoch": 1}
    preconditions = request["preconditions"]
    assert preconditions["current_recovery_epoch"] == 1 and preconditions["current_release_manifest_sha256"] is None
    with instance.db() as db:
        assert preconditions["current_data_schema_sha256"] == updates.schema_sha256(updates.data_schema(db))
    unsigned = {key: value for key, value in request.items() if key != "request_digest"}
    assert request["request_digest"] == b64(sha256(canonical_json(unsigned)).digest())
    assert result["state"] == "prepared" and result["revision"] == 1
    # the stored immutable bytes are the ones handed to the signer
    assert instance.rows("SELECT request FROM deployment_update_requests") == [(request_bytes,)]
    # idempotent re-run; a different target needs the pending one cancelled first
    again, _ = instance.prepare()
    assert again["repeated"] and again["request_id"] == result["request_id"]
    other_lock = image_lock("1.2.0")
    refused("pending", lambda: instance.prepare(manifest(other_lock, release_id="1.2.0"), other_lock))
    # an image lock the manifest does not name, or a non-canonical manifest, never seals
    instance.cancel()
    refused("invalid_request", lambda: instance.prepare(instance.manifest, image_lock(services={
        "control": "sha256:" + "d" * 64})))
    refused("invalid_request", lambda: instance.prepare(instance.manifest + b" ", instance.lock))
    # a target the code has no migration step for is refused before anything is sealed
    unknown = manifest(instance.lock, data_schema={"domain": [[1, domain_store.MIGRATION_SHA256],
                                                              [2, domain_store.MIGRATION_2_SHA256], [3, "e" * 64]]})
    refused("migration_unsupported", lambda: instance.prepare(unknown, instance.lock))


def test_the_tool_refuses_while_the_control_plane_runs_and_during_an_owner_recovery(tmp_path):
    from app.operations import deployment_control

    instance = Instance(tmp_path)
    app = create_app(tmp_path / "data", **instance.state.arguments)
    with TestClient(app, base_url=instance.state.profile.http_origin):
        refused("busy", instance.tool)
    _capability, verifier = new_capability()
    with instance.tool() as maintenance:
        deployment_control.prepare(maintenance, new_verifier=verifier)
    refused("recovery_pending", instance.prepare)
    with instance.tool() as maintenance:
        deployment_control.cancel(maintenance)
    assert instance.prepare()[0]["state"] == "prepared"


# ---- the backup gate -------------------------------------------------------------------------

def test_migration_refuses_without_a_verified_backup(tmp_path):
    instance = Instance(tmp_path, v1=True)
    result, request = instance.prepare()
    refused("backup_required", lambda: instance.migrate(instance.receipt(request)))
    assert instance.head(result["request_id"])["state"] == "prepared"
    assert instance.rows("SELECT count(*) FROM deployment_update_consumptions") == [(0,)]
    assert instance.domain_rows() == [(1,)]
    guidance = instance.guidance()
    assert guidance["backup"] == {"required": True, "state": "absent"}
    assert guidance["last_refusal"]["code"] == "backup_required"
    assert guidance["next_steps"][:2] == ["stop_control_plane", "take_verified_backup"]
    # a backup without the backup-crypto component is refused in a safe state
    refused("component_unavailable", lambda: instance.backup(probes={}))
    assert instance.head(result["request_id"])["state"] == "prepared"


@needs_age
def test_a_full_update_migrates_once_with_the_receipt_consumed_in_the_same_transaction(ready):
    instance, result, request = ready
    request_id = result["request_id"]
    head = instance.head(request_id)
    assert head["state"] == "backup_verified" and head["backup_state_digest"] == instance.digest()
    # the gate backup is an ordinary owner backup too: ciphertext and external receipt
    backups = instance.tmp / "data" / "backups"
    assert (backups / f"{head['backup_id']}.age").read_bytes().startswith(b"age-encryption.org/v1\n")
    receipt = instance.receipt(request)
    done = instance.migrate(receipt)
    assert done["state"] == "completed" and done["repeated"] is False
    assert done["steps"] == [["domain", [2, domain_store.MIGRATION_2_SHA256]]]
    assert instance.domain_rows() == [(1,), (2,)]
    consumption = instance.rows("SELECT receipt_sha256, request_id, request_nonce, migration_id "
                                "FROM deployment_update_consumptions")
    assert consumption == [(sha256(receipt).hexdigest(), request_id, parse_canonical(request)["request_nonce"],
                            done["migration_id"])]
    assert instance.rows("SELECT migration_id, state_digest_before FROM deployment_update_applied") == [
        (done["migration_id"], head["backup_state_digest"])]
    assert [row[0] for row in instance.rows("SELECT state FROM deployment_update_lifecycle WHERE request_id=? "
                                            "ORDER BY revision", (request_id,))] == [
        "prepared", "backup_verified", "migrating", "completed"]
    assert instance.rows("SELECT release_id, manifest_sha256 FROM deployment_update_releases") == [
        ("1.1.0", sha256(instance.manifest).hexdigest())]
    # replay: the identical receipt is a verify-only no-op; any other one is a replay
    assert instance.migrate(receipt)["repeated"] is True
    refused("replayed", lambda: instance.migrate(instance.receipt(request, completed_ms=time.time_ns() // 1_000_000
                                                                  + 1000)))
    refused("already_completed", instance.cancel)
    assert instance.rows("SELECT count(*) FROM deployment_update_consumptions") == [(1,)]
    # the migrated vault starts, and the owner's session (not an authority the update ends) holds
    state = instance.state
    app = create_app(instance.tmp / "data", **state.arguments)
    with TestClient(app, base_url=state.profile.http_origin) as client:
        client.cookies.set("deeptwin_session", state.cookie)
        assert client.get(state.profile.base_path + "session", headers=headers(state.profile)).status_code == 200
        guidance = client.get(state.profile.base_path + "api/v1/platform/update", headers=headers(state.profile))
        assert guidance.status_code == 200, guidance.text
        body = guidance.json()
        assert body["current_release"]["release_id"] == "1.1.0" and body["request"]["state"] == "completed"
        assert body["product_authority"] == "read_only" and body["next_steps"] == []
        assert client.post(state.profile.base_path + "api/v1/platform/update", headers=headers(state.profile),
                           json={}).status_code in (400, 403, 405)
    # the next update names this release as its precondition; the same target is already current
    refused("already_current", instance.prepare)


@needs_age
def test_a_write_after_the_backup_invalidates_the_gate_until_a_new_backup(tmp_path, age_runtime):
    from app.domain.schemas import ImmutableRecord
    from app.domain.store import DomainStore
    from app.storage import Store

    # a current-schema vault (opening the domain store below would itself move a v1 vault
    # to schema 2: that pre-T072 in-place step is not what this case is about)
    instance = with_worker_port(Instance(tmp_path), age_runtime)
    result, request = instance.prepare()
    instance.backup()
    receipt = instance.receipt(request)
    domain = DomainStore(Store(instance.tmp / "data"))
    roots = domain.roots()
    record = ImmutableRecord.create(
        kind="work_revision", id=str(uuid4()), version=1, created_at_utc="2026-09-25T00:00:00.000000Z",
        actor_ref=roots.actor, parent_refs=(), purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy, content={"text": "백업 뒤에 쓴 새 자료"})
    domain.put(record)
    del domain
    assert instance.guidance()["backup"]["state"] == "stale"
    assert instance.guidance()["next_steps"][1] == "take_verified_backup_again"
    refused("backup_stale", lambda: instance.migrate(receipt))
    assert instance.head(result["request_id"])["state"] == "backup_verified"
    assert instance.rows("SELECT count(*) FROM deployment_update_consumptions") == [(0,)]
    assert instance.rows("SELECT count(*) FROM deployment_update_releases") == [(0,)]
    # a new verified backup holds the new record; then the same receipt migrates
    instance.backup()
    assert instance.guidance()["backup"]["state"] == "verified"
    assert instance.migrate(receipt)["state"] == "completed"
    assert instance.rows("SELECT count(*) FROM domain_records WHERE id=?", (record.ref.id,)) == [(1,)]


@needs_age
@pytest.mark.parametrize("damage", ["deleted", "altered", "tombstoned"])
def test_a_missing_or_altered_gate_backup_refuses(ready, damage):
    instance, result, request = ready
    head = instance.head(result["request_id"])
    ciphertext = instance.tmp / "data" / "backups" / f"{head['backup_id']}.age"
    if damage == "deleted":
        ciphertext.unlink()
    elif damage == "altered":
        body = bytearray(ciphertext.read_bytes())
        body[-1] ^= 1
        ciphertext.write_bytes(bytes(body))
    else:
        (ciphertext.parent / f"{head['backup_id']}.deleted.json").write_text("{}")
    refused("backup_missing", lambda: instance.migrate(instance.receipt(request)))
    assert instance.domain_rows() == [(1,)]


# ---- cancel versus receipt ---------------------------------------------------------------------

@needs_age
def test_a_committed_cancel_wins_over_a_verified_receipt(ready, monkeypatch):
    instance, result, request = ready
    request_id = result["request_id"]
    receipt = instance.receipt(request)

    def cancel_now(name):
        if name == "receipt_verified":
            # the other side of the race, through the same CAS in its own transaction
            head = instance.head(request_id)
            UpdateStore(instance.tmp / "data").advance(request_id, expected_revision=head["revision"],
                                                      state="cancelled")

    monkeypatch.setattr(updates, "_step", cancel_now)
    refused("cancelled", lambda: instance.migrate(receipt))
    monkeypatch.setattr(updates, "_step", lambda name: None)
    assert instance.head(request_id)["state"] == "cancelled"
    assert instance.rows("SELECT count(*) FROM deployment_update_consumptions") == [(0,)]
    assert instance.domain_rows() == [(1,)]
    refused("cancelled", lambda: instance.migrate(receipt))
    assert instance.cancel()["repeated"] is True


@needs_age
def test_a_journaled_receipt_wins_over_a_later_cancel(ready, monkeypatch):
    instance, result, request = ready
    receipt = instance.receipt(request)

    def crash(name):
        if name == "migrating_recorded":
            raise RuntimeError("the process ended here")

    monkeypatch.setattr(updates, "_step", crash)
    with pytest.raises(RuntimeError):
        instance.migrate(receipt)
    monkeypatch.setattr(updates, "_step", lambda name: None)
    refused("migration_in_progress", instance.cancel)
    # the control plane does not serve over a journaled migration (safe state) ...
    refused("migration_in_progress", lambda: create_app(instance.tmp / "data", **instance.state.arguments))
    assert instance.migrate(receipt)["state"] == "completed"
    # ... and starts again once the operator finished it
    with TestClient(create_app(instance.tmp / "data", **instance.state.arguments),
                    base_url=instance.state.profile.http_origin) as client:
        assert client.get(instance.state.profile.base_path + "health").status_code == 200
    refused("already_completed", instance.cancel)


@needs_age
def test_a_prepared_cancel_refuses_every_later_receipt(tmp_path, age_runtime):
    instance = with_worker_port(Instance(tmp_path, v1=True), age_runtime)
    result, request = instance.prepare()
    assert instance.cancel()["state"] == "cancelled"
    refused("cancelled", lambda: instance.migrate(instance.receipt(request)))
    refused("no_pending", lambda: instance.backup())
    # a new request is a new nonce and id; the old receipt stays refused for it
    second, second_request = instance.prepare()
    assert second["request_id"] != result["request_id"]
    instance.backup()
    refused("cancelled", lambda: instance.migrate(instance.receipt(request)))
    assert instance.migrate(instance.receipt(second_request))["state"] == "completed"


# ---- replay and restart after a crash at every step -----------------------------------------------

@needs_age
@pytest.mark.parametrize("step", ["receipt_verified", "migrating_recorded", "migration_applied", "committed"])
def test_a_crash_at_every_migration_step_is_completed_by_re_running(ready, monkeypatch, step):
    instance, result, request = ready
    request_id = result["request_id"]
    receipt = instance.receipt(request)

    def crash(name):
        if name == step:
            raise RuntimeError("the process ended here")

    monkeypatch.setattr(updates, "_step", crash)
    with pytest.raises(RuntimeError):
        instance.migrate(receipt)
    monkeypatch.setattr(updates, "_step", lambda name: None)
    head = instance.head(request_id)
    expected = {"receipt_verified": "backup_verified", "migrating_recorded": "migrating",
                "migration_applied": "migrating", "committed": "completed"}[step]
    assert head["state"] == expected
    if step != "committed":
        # nothing was consumed or migrated: the crashed transaction rolled back as a whole
        assert instance.domain_rows() == [(1,)]
        assert instance.rows("SELECT count(*) FROM deployment_update_consumptions") == [(0,)]
    if expected == "migrating":
        other = instance.receipt(request, completed_ms=time.time_ns() // 1_000_000 + 1000)
        refused("migration_in_progress", lambda: instance.migrate(other))
        assert instance.guidance()["next_steps"] == ["stop_control_plane", "rerun_migrate_with_same_receipt",
                                                     "start_new_release"]
    done = instance.migrate(receipt)
    assert done["state"] == "completed" and done["repeated"] is (step == "committed")
    assert instance.domain_rows() == [(1,), (2,)]
    assert instance.rows("SELECT count(*) FROM deployment_update_consumptions") == [(1,)]
    assert instance.rows("SELECT count(*) FROM deployment_update_applied") == [(1,)]


@needs_age
def test_a_crash_while_preparing_or_backing_up_is_inert_and_re_runs(tmp_path, age_runtime, monkeypatch):
    instance = with_worker_port(Instance(tmp_path), age_runtime)

    def crash(target):
        def hook(name):
            if name == target:
                raise RuntimeError("the process ended here")
        return hook

    monkeypatch.setattr(updates, "_step", crash("request_written"))
    with pytest.raises(RuntimeError):
        instance.prepare()
    assert instance.rows("SELECT count(*) FROM deployment_update_requests") == [(0,)]
    monkeypatch.setattr(updates, "_step", crash("backup_created"))
    result, _request = instance.prepare()
    with pytest.raises(RuntimeError):
        instance.backup()
    assert instance.head(result["request_id"])["state"] == "prepared"
    monkeypatch.setattr(updates, "_step", lambda name: None)
    assert instance.backup()["state"] == "backup_verified"


# ---- missing component handshake and a failing step ---------------------------------------------

@needs_age
def test_a_missing_or_wrong_component_leaves_a_safe_state(tmp_path, age_runtime):
    instance = with_worker_port(Instance(tmp_path, v1=True), age_runtime)
    instance.manifest = manifest(instance.lock, components=[
        {"component_id": "backup-crypto", "protocol": BACKUP_PROTOCOL},
        {"component_id": "document-worker", "protocol": "deeptwin-document-port-v1"}])
    result, request = instance.prepare()
    instance.backup()
    receipt = instance.receipt(request)
    error = refused("component_unavailable", lambda: instance.migrate(receipt))
    assert error.detail == "document-worker"

    def unreachable():
        raise ConnectionRefusedError("no worker")

    probes = {**instance.probes, "document-worker": unreachable}
    refused("component_unavailable", lambda: instance.migrate(receipt, probes=probes))
    probes = {**instance.probes, "document-worker": lambda: {"protocol": "deeptwin-document-port-v0"}}
    refused("component_version_mismatch", lambda: instance.migrate(receipt, probes=probes))
    assert instance.head(result["request_id"])["state"] == "backup_verified"
    assert instance.domain_rows() == [(1,)]
    assert instance.rows("SELECT count(*) FROM deployment_update_consumptions") == [(0,)]
    guidance = instance.guidance()
    assert guidance["last_refusal"]["code"] == "component_version_mismatch"
    assert guidance["last_refusal"]["component"] == "document-worker"
    probes = {**instance.probes, "document-worker": lambda: {"protocol": "deeptwin-document-port-v1"}}
    assert instance.migrate(receipt, probes=probes)["state"] == "completed"


def test_the_real_backup_client_without_a_reachable_worker_is_a_missing_component(tmp_path, capsys):
    instance = Instance(tmp_path)
    instance.prepare()
    config = tmp_path / "backup-worker.json"
    config.write_text(json.dumps({"schema": "deeptwin-backup-worker-attachment-v1",
                                  "pair_root": str(tmp_path / "no-pair"), "requester_boot_id": "0" * 32}))
    code = updates.run(["backup", "--data-dir", str(tmp_path / "data"), "--session-root-dir", str(tmp_path / "root"),
                        "--deployment-config", str(instance.state.config_path), "--work-dir", str(tmp_path / "work"),
                        "--expected-uid", str(os.getuid()), "--expected-gid", str(os.getgid()),
                        "--backup-worker-config", str(config)])
    assert code == 2
    assert json.loads(capsys.readouterr().out) == {"state": "refused", "code": "component_unavailable",
                                                   "component": "backup-crypto"}


@needs_age
def test_a_failing_step_rolls_back_and_ends_failed_with_the_data_unchanged(ready):
    instance, result, request = ready
    before = instance.digest()

    def broken(db):
        db.execute("CREATE TABLE domain_half_done (x INTEGER)")
        raise updates.MigrationStepFailure("synthetic step failure")

    steps = {("domain", (2, domain_store.MIGRATION_2_SHA256)): broken}
    refused("migration_failed", lambda: instance.migrate(instance.receipt(request), steps=steps))
    head = instance.head(result["request_id"])
    assert head["state"] == "failed" and head["failure_code"] == "migration_failed"
    assert instance.digest() == before and instance.domain_rows() == [(1,)]
    assert instance.rows("SELECT count(*) FROM sqlite_master WHERE name='domain_half_done'") == [(0,)]
    assert instance.rows("SELECT count(*) FROM deployment_update_consumptions") == [(0,)]
    guidance = instance.guidance()
    assert guidance["request"]["state"] == "failed" and guidance["backup"]["state"] == "kept"
    assert guidance["next_steps"] == ["keep_current_release", "prepare_new_request"]
    refused("failed", lambda: instance.migrate(instance.receipt(request)))


# ---- receipts that must not migrate -------------------------------------------------------------------

@needs_age
def test_forged_foreign_and_mismatched_receipts_change_nothing(ready):
    instance, result, request = ready
    state = instance.state
    now = time.time_ns() // 1_000_000
    good = instance.receipt(request)
    forged = parse_canonical(good)
    forged["signature"] = b64(bytes(64))
    stage_only = Signer(adapters=(STAGE_ADAPTER,))
    stage_trust = trust_v2(state.profile, stage_only)
    stranger = Signer()
    cases = [
        ("receipt_invalid", canonical_json(forged), None),
        ("receipt_invalid", good + b"\n", None),
        # a stage-only key never signs a deployment-authority update
        ("receipt_invalid", instance.receipt(request, signer=stage_only, trust=stage_trust), stage_trust),
        # a key outside the pinned trust set
        ("receipt_invalid", instance.receipt(request, signer=stranger), None),
        ("receipt_mismatch", instance.receipt(request, image_lock_set_sha256="f" * 64), None),
        ("receipt_mismatch", instance.receipt(request, release_manifest_sha256="f" * 64), None),
        ("receipt_mismatch", instance.receipt(request, recovery_epoch=2), None),
        ("receipt_mismatch", instance.receipt(request, request_nonce=b64(os.urandom(32))), None),
        ("receipt_mismatch", instance.receipt(request, origin_profile_digest=b64(os.urandom(32))), None),
        ("receipt_expired", instance.receipt(request, completed_ms=now + 2 * 86_400_000), None),
        ("receipt_mismatch", instance.receipt(request, request_id=str(uuid4())), None),
    ]
    for code, receipt, trust in cases:
        refused(code, lambda: instance.migrate(receipt, trust=trust))
    assert instance.head(result["request_id"])["state"] == "backup_verified"
    assert instance.domain_rows() == [(1,)]
    assert instance.rows("SELECT count(*) FROM deployment_update_consumptions") == [(0,)]
    assert instance.migrate(good)["state"] == "completed"


@needs_age
def test_an_owner_recovery_between_backup_and_receipt_invalidates_the_epoch(ready):
    from app.operations import deployment_control

    instance, result, request = ready
    receipt = instance.receipt(request)
    capability, verifier = new_capability()
    with instance.tool() as maintenance:
        prepared = deployment_control.prepare(maintenance, new_verifier=verifier)
    recovery_request = Path(prepared["request_path"]).read_bytes()
    recovery_receipt = receipt_for(instance.state.profile, recovery_request, instance.state.signer,
                                   instance.state.trust, new_verifier=verifier)
    operator = instance.tmp / "operator"
    operator.mkdir(mode=0o700)
    (operator / "receipt.json").write_bytes(recovery_receipt)
    (operator / "trust.json").write_bytes(instance.state.trust)
    with instance.tool() as maintenance:
        imported = recovery.import_owner_recovery(maintenance, receipt_path=operator / "receipt.json",
                                                  trust_path=operator / "trust.json")
    assert imported["state"] == "imported" and configuration(instance.state)["recovery_epoch"] == 2
    assert_recovered_start(instance.tmp, instance.state, capability)
    refused("epoch_changed", lambda: instance.migrate(receipt))
    assert instance.rows("SELECT count(*) FROM deployment_update_consumptions") == [(0,)]
    assert instance.head(result["request_id"])["state"] == "backup_verified"


# ---- the recovery path: operator intake only, restore never silent ---------------------------------------

def test_the_recovery_path_refuses_browser_uploaded_and_unowned_receipts(tmp_path):
    instance = Instance(tmp_path)
    receipt = b'{"schema":"deployment-recovery-receipt-v1"}'
    uploads = tmp_path / "data" / "restores" / str(uuid4())
    uploads.mkdir(parents=True)
    (uploads / "bundle").write_bytes(receipt)
    operator = tmp_path / "operator"
    operator.mkdir(mode=0o700)
    (operator / "link.json").symlink_to(uploads / "bundle")
    (operator / "shared.json").write_bytes(receipt)
    os.chmod(operator / "shared.json", 0o666)
    (operator / "trust.json").write_bytes(instance.state.trust)
    with instance.tool() as maintenance:
        for path in (uploads / "bundle", operator / "link.json", tmp_path / "root" / "anything.json"):
            refused("input_source_refused", lambda: recovery.import_owner_recovery(
                maintenance, receipt_path=path, trust_path=operator / "trust.json"))
        refused("input_source_refused", lambda: recovery.read_operator_input(maintenance, operator / "shared.json",
                                                                             8192))
    # the product surface: one read-only route; no route accepts an update or recovery receipt
    contributions = sorted((REPOSITORY / "app" / "api" / "route_contributions").glob("*.json"))
    routes = [route for path in contributions for route in json.loads(path.read_text())["routes"]]
    platform = [route for route in routes if route["path"].startswith("/api/v1/platform")]
    assert platform == [{"route_id": "platform.update.read", "methods": ["GET", "HEAD"],
                         "path": "/api/v1/platform/update", "auth_policy": "browser_session",
                         "required_scope": "deployment.read"}]
    assert not [route for route in routes if "recover" in route["path"] and "POST" in route["methods"]
                and "receipt" in route["route_id"]]


@needs_age
def test_restoring_a_gate_backup_is_staged_and_never_silently_loses_new_data(ready):
    instance, _result, request = ready
    instance.migrate(instance.receipt(request))
    staging = instance.tmp / "staging"
    staging.mkdir(mode=0o700)
    with instance.tool() as maintenance:
        error = refused("new_data_after_backup", lambda: recovery.restore_update_backup(
            maintenance, staging_dir=staging, crypto=instance.crypto))
        live = error.detail
        assert live == instance.digest() and not any(staging.iterdir())
        refused("invalid_request", lambda: recovery.restore_update_backup(
            maintenance, staging_dir=instance.tmp / "data" / "staged", crypto=instance.crypto,
            acknowledge_new_data_after_backup=live))
        restored = recovery.restore_update_backup(maintenance, staging_dir=staging, crypto=instance.crypto,
                                                  acknowledge_new_data_after_backup=live)
    assert restored["state"] == "restored_review" and restored["new_data_after_backup_left_out"] is True
    assert restored["active_vault_changed"] is False and instance.digest() == live
    marker = json.loads((staging / "restored_review.json").read_bytes())
    assert marker["dispatch"] == "blocked"
    with sqlite3.connect(staging / "vault" / "intake.sqlite3") as db:
        staged = db.execute("SELECT count(*) FROM domain_records").fetchone()
        assert not db.execute("SELECT name FROM sqlite_master WHERE name GLOB 'deployment_update_*' "
                              "OR name GLOB 'owner_auth_*'").fetchall()
    assert instance.rows("SELECT count(*) FROM domain_records") == [staged]


# ---- no runtime pip/npm -----------------------------------------------------------------------------------

def _imports(path):
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
            names.add("os." + node.attr)
    return names


def test_the_tooling_never_imports_a_process_or_package_manager():
    forbidden = {"subprocess", "pip", "ensurepip", "venv", "importlib.metadata", "urllib.request", "http.client",
                 "socket", "os.system", "os.popen", "os.execv", "os.execvp", "os.spawnv", "os.posix_spawn"}
    for name in ("updates.py", "recovery.py"):
        assert not _imports(REPOSITORY / "app" / "operations" / name) & forbidden, name
    assert not _imports(REPOSITORY / "app" / "api" / "platform_update.py") & forbidden


_SPAWNS = []


def _audit(event, args):
    if _SPAWNS and _SPAWNS[0] == "on" and event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn",
                                                    "os.spawn", "os.fork"}:
        _SPAWNS.append((event, repr(args)[:500]))


sys.addaudithook(_audit)


@needs_age
def test_a_whole_update_spawns_only_the_verified_age_runtime(tmp_path, age_runtime):
    instance = with_worker_port(Instance(tmp_path, v1=True), age_runtime)
    _SPAWNS[:] = ["on"]
    try:
        _result, request = instance.prepare()
        instance.backup()
        assert instance.migrate(instance.receipt(request))["state"] == "completed"
    finally:
        spawned = _SPAWNS[1:]
        _SPAWNS[:] = []
    assert spawned, "the age runtime really ran"
    age_root = str(Path(AGE_ROOT).resolve())
    for event, args in spawned:
        assert event == "subprocess.Popen", event
        lowered = args.lower()
        assert not any(tool in lowered for tool in ("pip", "npm", "npx", "uv ", "apt", "docker", "yarn")), args
        assert age_root in args or "/age" in args, args
