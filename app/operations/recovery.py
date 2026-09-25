"""`recovery`: operator-only update/recovery guidance, receipt intake and backup restore (T072).

Deployment operator tooling, never an end-user product journey, and never a browser
path. Three things live here:

- `update_guidance`: the one closed projection of the update lifecycle (current release,
  the pending request and its state, the backup the gate requires and whether it still
  holds the live state, the last refusal and the operator's next steps). The update tool's
  `status` prints it and the control plane serves it read-only to the owner
  (`GET /api/v1/platform/update`); neither can change anything through it.
- `read_operator_input`: every receipt, trust set, manifest and image-lock input the
  operator tools accept comes from an operator-owned regular file OUTSIDE the data
  directory and the session root. Everything a browser can upload lands inside the data
  directory (restore bundles, owner material, sources), so a browser-uploaded file can
  never become deployment authority; the product API has no route that accepts a
  deployment/recovery receipt for an update or an owner recovery.
- `import_owner_recovery` wraps the T025 owner-recovery import with that intake and
  refuses while an update is `migrating` (one deployment-authority transition at a time);
  `restore_update_backup` restores the gate backup of an update into an empty staging
  directory as `restored_review` (never over the active vault) and, when the live vault
  holds data written after that backup, refuses unless the operator names the exact live
  state digest being left out: loss of new data is never silent.

    python -m app.operations.recovery guidance              <common options>
    python -m app.operations.recovery import-owner-recovery <common> --receipt R --trust-set T
    python -m app.operations.recovery restore-update-backup <common> --staging-dir S
                                     --backup-worker-config C [--request-id I]
                                     [--acknowledge-new-data-after-backup DIGEST]
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from contextlib import closing
from pathlib import Path

from ..domain.refs import canonical_json
from .updates import UpdateError, UpdateStore, state_digest

GUIDANCE_SCHEMA = "deeptwin-update-guidance-v1"
# the closed next steps, in order, per lifecycle state
STEPS = {
    None: (),
    "prepared": ("stop_control_plane", "take_verified_backup", "apply_image_lock_and_sign_receipt",
                 "migrate_with_receipt", "start_new_release"),
    "backup_verified": ("stop_control_plane", "apply_image_lock_and_sign_receipt", "migrate_with_receipt",
                        "start_new_release"),
    "backup_stale": ("stop_control_plane", "take_verified_backup_again", "apply_image_lock_and_sign_receipt",
                     "migrate_with_receipt", "start_new_release"),
    "migrating": ("stop_control_plane", "rerun_migrate_with_same_receipt", "start_new_release"),
    "failed": ("keep_current_release", "prepare_new_request"),
    "completed": (),
    "cancelled": (),
}


def _inside(path, root):
    return path == root or root in path.parents


def read_operator_input(maintenance, path, limit):
    """An operator-owned public input (receipt, trust set, manifest, image lock).

    Refused unless it is a regular, singly linked file owned by the operator identity,
    not writable by group or others, never through a symbolic link, and outside the data
    directory and the session root (where every browser upload lands)."""
    absolute = Path(os.path.abspath(os.fspath(path)))
    real = Path(os.path.realpath(absolute))
    for root in (maintenance.data_dir, maintenance.root_dir):
        root_real = Path(os.path.realpath(root))
        if _inside(absolute, Path(root)) or _inside(real, root_real):
            raise UpdateError("input_source_refused")
    try:
        fd = os.open(absolute, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise UpdateError("invalid_request") from None
    try:
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_uid != maintenance.uid
                or stat.S_IMODE(metadata.st_mode) & 0o022):
            raise UpdateError("input_source_refused")
        data = os.read(fd, limit + 1)
    finally:
        os.close(fd)
    if not 1 <= len(data) <= limit:
        raise UpdateError("invalid_request")
    return data


def _request_view(store, db, head):
    request = store.request(db, head["request_id"])
    return {"request_id": head["request_id"], "state": head["state"], "revision": head["revision"],
            "target_release_id": request["target_release_id"],
            "target_release_manifest_sha256": request["target_manifest_sha256"],
            "target_image_lock_set_sha256": request["target_image_lock_sha256"],
            "recovery_epoch": request["recovery_epoch"], "created_at": request["created_at"],
            "expires_at": request["expires_at"], "recorded_at": head["recorded_at"],
            "failure_code": head["failure_code"]}


def update_guidance(db, *, live_state_digest=None) -> dict:
    """The read-only projection; `db` None means no update was ever prepared."""
    empty = {"schema_version": GUIDANCE_SCHEMA, "product_authority": "read_only", "current_release": None,
             "request": None, "backup": {"required": False, "state": "not_required"}, "last_refusal": None,
             "next_steps": [], "history": []}
    if db is None:
        return empty
    store = UpdateStore
    release = store.release(db)
    heads = store.heads(db)
    active = next((head for head in heads if head["state"] in ("prepared", "backup_verified", "migrating")), None)
    shown = active if active is not None else next(iter(heads), None)
    value = dict(empty)
    if release is not None:
        value["current_release"] = {"release_id": release["release_id"],
                                    "release_manifest_sha256": release["manifest_sha256"],
                                    "image_lock_set_sha256": release["image_lock_sha256"],
                                    "installed_at": release["installed_at"]}
    value["history"] = [{"request_id": head["request_id"], "state": head["state"], "recorded_at": head["recorded_at"]}
                        for head in heads[:5]]
    if shown is None:
        return value
    value["request"] = _request_view(store, db, shown)
    state = shown["state"]
    if state == "prepared":
        value["backup"] = {"required": True, "state": "absent"}
    elif state in ("backup_verified", "migrating"):
        holds = live_state_digest is None or live_state_digest == shown["backup_state_digest"]
        value["backup"] = {"required": True, "state": "verified" if holds else "stale",
                           "backup_id": shown["backup_id"], "state_digest": shown["backup_state_digest"]}
        if state == "backup_verified" and not holds:
            state = "backup_stale"
    elif shown["backup_id"] is not None:
        value["backup"] = {"required": False, "state": "kept", "backup_id": shown["backup_id"],
                           "state_digest": shown["backup_state_digest"]}
    if active is not None:
        refusals = store.refusals(db, shown["request_id"])
        if refusals:
            last = refusals[-1]
            value["last_refusal"] = {"code": last["code"], "component": last["detail"]
                                     if last["code"].startswith("component_") else None,
                                     "recorded_at": last["recorded_at"]}
    value["next_steps"] = list(STEPS[state])
    return value


def guidance_for(data_dir) -> dict:
    """The guidance straight from a vault database (read-only; the control plane's view)."""
    path = Path(os.path.abspath(os.fspath(data_dir))) / "intake.sqlite3"
    import sqlite3

    if not path.is_file():
        return update_guidance(None)
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)) as db:
        db.row_factory = sqlite3.Row
        if not UpdateStore.installed(db):
            return update_guidance(None)
        UpdateStore.verify(db)
        pending = db.execute("SELECT 1 FROM deployment_update_lifecycle l WHERE state='backup_verified' AND "
                             "revision=(SELECT max(revision) FROM deployment_update_lifecycle m "
                             "WHERE m.request_id=l.request_id)").fetchone()
        # only a verified gate needs the live digest (it says whether the backup still holds)
        digest = state_digest(db) if pending is not None else None
        return update_guidance(db, live_state_digest=digest)


def refuse_start_during_migration(data_dir) -> None:
    """The control plane's start refuses (safe state) while an update is `migrating`:
    only the operator's `migrate` with the journaled receipt may finish it."""
    import sqlite3

    path = Path(os.path.abspath(os.fspath(data_dir))) / "intake.sqlite3"
    if not path.is_file():
        return
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)) as db:
        db.row_factory = sqlite3.Row
        if not UpdateStore.installed(db):
            return
        active = UpdateStore.active(db)
    if active is not None and active["state"] == "migrating":
        raise UpdateError("migration_in_progress")


# ---- owner recovery through the operator intake ------------------------------------------------

def import_owner_recovery(maintenance, *, receipt_path, trust_path) -> dict:
    from .deployment_control import OwnerRecoveryError, import_receipt

    receipt_bytes = read_operator_input(maintenance, receipt_path, 8192)
    trust_bytes = read_operator_input(maintenance, trust_path, 16384)
    store = UpdateStore(maintenance.data_dir)
    with closing(store.connect()) as db:
        if store.installed(db):
            store.verify(db)
            active = store.active(db)
            if active is not None and active["state"] == "migrating":
                raise UpdateError("update_in_progress")
    try:
        return import_receipt(maintenance, receipt_bytes=receipt_bytes, trust_bytes=trust_bytes)
    except OwnerRecoveryError as error:
        raise UpdateError(error.code) from None


# ---- restoring an update's gate backup ------------------------------------------------------------

def restore_update_backup(maintenance, *, staging_dir, crypto, request_id=None,
                          acknowledge_new_data_after_backup=None) -> dict:
    from .backup import restore_backup
    from .updates import _backup_files, _check_backup_files

    import json

    store = UpdateStore(maintenance.data_dir)
    with closing(store.connect()) as db:
        if not store.installed(db):
            raise UpdateError("no_backup")
        store.verify(db)
        heads = [head for head in store.heads(db) if head["backup_id"] is not None
                 and (request_id is None or head["request_id"] == request_id)]
        if not heads:
            raise UpdateError("no_backup")
        head = heads[0]
        if head["state"] == "migrating":
            raise UpdateError("migration_in_progress")  # finish the journaled migration first
        live = state_digest(db)
    _check_backup_files(maintenance, head)
    new_data = live != head["backup_state_digest"]
    if new_data and acknowledge_new_data_after_backup != live:
        # the restore would not hold what was written since the backup: say so, never silently
        raise UpdateError("new_data_after_backup", live)
    ciphertext, receipt_path, _tombstone = _backup_files(maintenance, head["backup_id"])
    receipt = json.loads(receipt_path.read_bytes())
    staging = Path(os.path.abspath(os.fspath(staging_dir)))
    if _inside(staging, maintenance.data_dir):
        raise UpdateError("invalid_request")  # never inside (let alone over) the active vault
    outcome = restore_backup(ciphertext, receipt, staging, crypto=crypto, active_vault_dir=maintenance.data_dir)
    if outcome.state != "restored_review":
        raise UpdateError("restore_failed", outcome.failure)
    return {"state": "restored_review", "request_id": head["request_id"], "backup_id": head["backup_id"],
            "staging_dir": str(staging), "backup_state_digest": head["backup_state_digest"],
            "live_state_digest": live, "new_data_after_backup_left_out": new_data,
            "active_vault_changed": False,
            "next": "review the staged vault; it stays restored_review until a new owner bootstraps and "
                    "explicitly reactivates an environment"}


# ---- command line --------------------------------------------------------------------------------

def run(argv=None):
    from .updates import _backup_client, open_maintenance

    parser = argparse.ArgumentParser(prog="python -m app.operations.recovery",
                                     description="DeepTwin update/recovery guidance (control plane stopped)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("guidance", "import-owner-recovery", "restore-update-backup"):
        command = commands.add_parser(name)
        for option in ("--data-dir", "--session-root-dir", "--deployment-config", "--work-dir"):
            command.add_argument(option, type=Path, required=True)
        command.add_argument("--expected-uid", type=int, required=True)
        command.add_argument("--expected-gid", type=int, required=True)
        if name == "import-owner-recovery":
            command.add_argument("--receipt", type=Path, required=True)
            command.add_argument("--trust-set", type=Path, required=True)
        if name == "restore-update-backup":
            command.add_argument("--staging-dir", type=Path, required=True)
            command.add_argument("--backup-worker-config", type=Path, required=True)
            command.add_argument("--request-id")
            command.add_argument("--acknowledge-new-data-after-backup")
    args = parser.parse_args(argv)
    try:
        with open_maintenance(data_dir=args.data_dir, session_root_dir=args.session_root_dir,
                              deployment_config=args.deployment_config, work_dir=args.work_dir,
                              expected_uid=args.expected_uid, expected_gid=args.expected_gid) as maintenance:
            if args.command == "guidance":
                result = {"state": "guidance", **guidance_for(maintenance.data_dir)}
            elif args.command == "import-owner-recovery":
                result = import_owner_recovery(maintenance, receipt_path=args.receipt, trust_path=args.trust_set)
            else:
                client, _probes = _backup_client(args.backup_worker_config)
                if client is None:
                    raise UpdateError("component_unavailable", "backup-crypto")
                result = restore_update_backup(
                    maintenance, staging_dir=args.staging_dir, crypto=client, request_id=args.request_id,
                    acknowledge_new_data_after_backup=args.acknowledge_new_data_after_backup)
    except UpdateError as error:
        refusal = {"state": "refused", "code": error.code}
        if error.code == "new_data_after_backup":
            refusal["live_state_digest"] = error.detail
        sys.stdout.write(canonical_json(refusal).decode("utf-8") + "\n")
        return 2
    sys.stdout.write(canonical_json(result).decode("utf-8") + "\n")
    return 0


def main():
    raise SystemExit(run())


if __name__ == "__main__":
    main()
