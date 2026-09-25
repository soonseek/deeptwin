"""`deployment-control`: the stopped-control-plane owner-recovery maintenance tool (operator only).

The operator side of `app/services/deployment_control.py` (the restricted reconciliation
start): this module prepares, cancels and imports; that one reconciles on the next start.

This is deployment operator tooling, never an end-user product journey. It runs only while
the control plane is stopped (it takes the data directory's serving lock and refuses `busy`
when a server holds it) and drives one N→N+1 recovery through four subcommands:

    python -m app.operations.deployment_control status  <common options>
    python -m app.operations.deployment_control prepare <common options> --new-verifier V [--ttl-seconds S]
    python -m app.operations.deployment_control cancel  <common options>
    python -m app.operations.deployment_control import  <common options> --receipt R --trust-set T

    common options: --data-dir D --session-root-dir S --deployment-config C --work-dir W
                    --expected-uid U --expected-gid G

`prepare` reads the current session-root generation (epoch N, which the deployment
configuration and the database must both name) and seals one `owner_recovery` request
(`deployment-request-v1`) with a fresh 32-byte nonce, bound to the non-secret verifier of
the new one-time capability the operator generated offline (the capability itself never
reaches this tool). The request is written to `W/requests/<request_id>.json` for the holder
of the recovery trust set to sign; the signing stays outside this tool.

`import` accepts the signed `deployment-recovery-receipt-v1`, verifies it against the
pending request and the `deployment-public-trust-set-v2` (a key holding the recovery
adapter), binds its `new_verifier_sha256` to the prepared verifier, then advances the
session root to N+1 (`advance_session_root`) and rewrites the deployment configuration
with epoch N+1 and the new verifier. The next start of the control plane with
`--recovery-trust-set` runs the restricted reconciliation start.

`cancel` ends a prepared request explicitly; a receipt for it is refused afterwards, and
a request whose import has begun can no longer be cancelled (the import is resumed).

Crash safety and idempotency. `W/pending.json` is the single commit pointer
(`prepared` → `importing` → `imported`, or `prepared` → `cancelled`); every file is written
to a temporary name, fsynced, renamed and its directory fsynced. The `importing` state is
journaled with the receipt digest before the root moves, so a crash at any later step is
completed by re-running `import` with the same receipt; `advance_session_root` is itself
verify-only over an already-advanced root, and the configuration is rewritten only from
exactly epoch N. Re-importing the identical receipt after completion is a no-op; any other
receipt for a request that is not the pending one is refused (`replayed` or
`receipt_mismatch`). Output is one canonical JSON line with no secret.
"""

import argparse
import json
import os
import sqlite3
import stat
import sys
import time
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from ..domain.refs import canonical_json, parse_canonical

PENDING_SCHEMA = "deeptwin-owner-recovery-pending-v1"
_STATES = frozenset({"prepared", "importing", "imported", "cancelled"})
_PENDING_FIELDS = frozenset({"schema", "state", "request_id", "request_sha256", "new_verifier_b64u",
                             "previous_epoch", "receipt_sha256", "trust_set_sha256"})
DEFAULT_TTL_SECONDS = 3600


class OwnerRecoveryError(Exception):
    """A closed refusal; `code` names it and carries no secret or filesystem detail."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _step(name):
    """A named point between two durable steps; tests replace it to inject a crash."""


def _sha256(data):
    return sha256(data).hexdigest()


# ---- owned files -----------------------------------------------------------------------

def _owned_directory(path, uid, gid, *, create=False):
    path = Path(os.path.abspath(os.fspath(path)))
    if create:
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    metadata = os.fstat(fd)
    if (not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != uid or metadata.st_gid != gid):
        os.close(fd)
        raise OwnerRecoveryError("unavailable")
    return fd


def _child_directory(parent, name, uid, gid):
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
        os.fsync(parent)
    except FileExistsError:
        pass
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    metadata = os.fstat(fd)
    if (stat.S_IMODE(metadata.st_mode) != 0o700 or metadata.st_uid != uid or metadata.st_gid != gid):
        os.close(fd)
        raise OwnerRecoveryError("unavailable")
    return fd


def _read(directory_fd, name, limit, uid, gid):
    """The bytes of one owned regular file, or None when absent."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    try:
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or metadata.st_uid != uid or metadata.st_gid != gid):
            raise OwnerRecoveryError("unavailable")
        data = os.read(fd, limit + 1)
        if len(data) > limit:
            raise OwnerRecoveryError("unavailable")
        return data
    finally:
        os.close(fd)


def _replace(directory_fd, name, data, *, mode=0o600):
    """Crash-safe replace: temporary name, fsync, atomic rename, directory fsync."""
    temporary = "." + name + ".tmp"
    try:
        os.unlink(temporary, dir_fd=directory_fd)
    except FileNotFoundError:
        pass
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=directory_fd)
    try:
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.rename(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    os.fsync(directory_fd)


def _read_input(path, limit):
    """An operator-supplied public input (receipt, trust set); never followed through a link."""
    try:
        fd = os.open(os.path.abspath(os.fspath(path)), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise OwnerRecoveryError("invalid_request") from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OwnerRecoveryError("invalid_request")
        data = os.read(fd, limit + 1)
    finally:
        os.close(fd)
    if not 1 <= len(data) <= limit:
        raise OwnerRecoveryError("invalid_request")
    return data


# ---- the stopped control plane -----------------------------------------------------------

class _Maintenance:
    """The held serving lock of a stopped control plane plus its three named inputs."""

    def __init__(self, *, data_dir, session_root_dir, deployment_config, work_dir, expected_uid,
                 expected_gid):
        from ..services.owner_admission import AdmissionRejected, ServingLock

        if (type(expected_uid) is not int or type(expected_gid) is not int
                or min(expected_uid, expected_gid) < 0):
            raise OwnerRecoveryError("invalid_request")
        if os.geteuid() != expected_uid or os.getegid() != expected_gid:
            raise OwnerRecoveryError("unavailable")
        self.uid, self.gid = expected_uid, expected_gid
        self.data_dir = Path(os.path.abspath(os.fspath(data_dir)))
        self.root_dir = Path(os.path.abspath(os.fspath(session_root_dir)))
        self.config_path = Path(os.path.abspath(os.fspath(deployment_config)))
        work = self.work_path = Path(os.path.abspath(os.fspath(work_dir)))
        paths = (self.data_dir, self.root_dir, work)
        if any(a == b or a in b.parents for a in paths for b in paths if a is not b):
            raise OwnerRecoveryError("invalid_request")
        self.lock = None
        self.work = self.requests = self.receipts = None
        try:
            data = _owned_directory(self.data_dir, self.uid, self.gid)
            try:
                # a data directory that never served has no lock and nothing to recover
                if _read(data, "owner-auth.lock", 0, self.uid, self.gid) is None:
                    raise OwnerRecoveryError("unavailable")
            finally:
                os.close(data)
            try:
                self.lock = ServingLock(self.data_dir, expected_uid=self.uid, expected_gid=self.gid,
                                        create=False)
            except AdmissionRejected:
                # the control plane is running (or the lock is unsafe): never touch its state
                raise OwnerRecoveryError("busy") from None
            self.work = _owned_directory(work, self.uid, self.gid, create=True)
            self.requests = _child_directory(self.work, "requests", self.uid, self.gid)
            self.receipts = _child_directory(self.work, "receipts", self.uid, self.gid)
        except OwnerRecoveryError:
            self.close()
            raise
        except OSError:
            self.close()
            raise OwnerRecoveryError("unavailable") from None

    def close(self):
        for name in ("requests", "receipts", "work"):
            fd = getattr(self, name)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)
        if self.lock is not None:
            self.lock.close()
            self.lock = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    # -- the deployment configuration (non-secret) --

    def configuration(self):
        from ..operations.setup import (
            INITIAL_RECOVERY_EPOCH,
            OriginProfile,
            build_bootstrap_configuration,
            build_recovered_configuration,
        )

        try:
            with open(self.config_path, "rb") as source:
                value = json.loads(source.read(8193))
            profile = OriginProfile.from_dict(value["origin_profile"])
            build = (build_bootstrap_configuration if value["recovery_epoch"] == INITIAL_RECOVERY_EPOCH
                     else build_recovered_configuration)
            configuration = build(profile=profile, verifier_b64u=value["verifier_b64u"],
                                  recovery_epoch=value["recovery_epoch"])
            if configuration != value:
                raise ValueError
            return profile, configuration
        except (OSError, ValueError, KeyError, TypeError):
            raise OwnerRecoveryError("configuration_invalid") from None

    def write_configuration(self, configuration):
        directory = os.open(self.config_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            mode = stat.S_IMODE(os.stat(self.config_path.name, dir_fd=directory, follow_symlinks=False).st_mode)
            _replace(directory, self.config_path.name, canonical_json(configuration), mode=mode)
        finally:
            os.close(directory)

    # -- the session root and the database at rest --

    def root_generation(self, profile, epoch):
        from .session_root import SessionRootError, open_session_root

        try:
            handle = open_session_root(self.root_dir, profile=profile, recovery_epoch=epoch,
                                       expected_uid=self.uid, expected_gid=self.gid)
        except SessionRootError:
            return None
        try:
            return {"epoch": handle.receipt["recovery_epoch"], "generation_id": handle.receipt["generation_id"],
                    "manifest_sha256": handle.manifest_digest}
        finally:
            handle.close()

    def database(self):
        """The database's current control epoch and the vault's system actor (read-only)."""
        path = self.data_dir / "intake.sqlite3"
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
                row = db.execute("SELECT epoch, generation_id, manifest_digest FROM owner_auth_control "
                                 "ORDER BY epoch DESC LIMIT 1").fetchone()
                roots = db.execute("SELECT roots FROM domain_vault WHERE singleton=1").fetchone()
        except sqlite3.Error:
            raise OwnerRecoveryError("unavailable") from None
        if row is None or roots is None:
            raise OwnerRecoveryError("unavailable")
        actor = parse_canonical(roots[0].encode("utf-8") if type(roots[0]) is str else roots[0])["actor"]
        return {"epoch": row[0], "generation_id": row[1], "manifest_sha256": row[2], "actor": actor}

    # -- the pending pointer --

    def pending(self):
        raw = _read(self.work, "pending.json", 4096, self.uid, self.gid)
        if raw is None:
            return None
        try:
            value = parse_canonical(raw)
            if (type(value) is not dict or set(value) != _PENDING_FIELDS or value["schema"] != PENDING_SCHEMA
                    or value["state"] not in _STATES):
                raise ValueError
            return value
        except (ValueError, TypeError, KeyError):
            raise OwnerRecoveryError("unavailable") from None

    def set_pending(self, value):
        _replace(self.work, "pending.json", canonical_json(value))

    def request_bytes(self, pending):
        raw = _read(self.requests, pending["request_id"] + ".json", 4096, self.uid, self.gid)
        if raw is None or _sha256(raw) != pending["request_sha256"]:
            raise OwnerRecoveryError("unavailable")
        return raw


def _consistent_epoch(maintenance, profile, configuration):
    """Configuration, root and database all at the same epoch N and generation."""
    epoch = configuration["recovery_epoch"]
    root = maintenance.root_generation(profile, epoch)
    if root is None:
        raise OwnerRecoveryError("root_unavailable")
    database = maintenance.database()
    if database["epoch"] != epoch:
        # a recovered configuration whose reconciliation start has not yet run
        raise OwnerRecoveryError("reconciliation_pending" if database["epoch"] == epoch - 1 else "unavailable")
    if (database["generation_id"], database["manifest_sha256"]) != (root["generation_id"], root["manifest_sha256"]):
        raise OwnerRecoveryError("unavailable")
    return root, database


# ---- subcommands -------------------------------------------------------------------------

def status(maintenance):
    profile, configuration = maintenance.configuration()
    epoch = configuration["recovery_epoch"]
    root = maintenance.root_generation(profile, epoch) or maintenance.root_generation(profile, epoch + 1)
    try:
        database_epoch = maintenance.database()["epoch"]
    except OwnerRecoveryError:
        database_epoch = None
    pending = maintenance.pending()
    return {"state": "status", "configuration_epoch": epoch,
            "root_epoch": None if root is None else root["epoch"], "database_epoch": database_epoch,
            "pending": None if pending is None else {"state": pending["state"], "request_id": pending["request_id"]}}


def prepare(maintenance, *, new_verifier, ttl_seconds=DEFAULT_TTL_SECONDS, now_ms=None):
    from ..deployment.recovery_contracts import make_recovery_request
    from ..operations.setup import CapabilityVerifier, SetupContractError

    try:
        CapabilityVerifier(new_verifier)
    except (SetupContractError, TypeError, ValueError):
        raise OwnerRecoveryError("invalid_request") from None
    if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 86400:
        raise OwnerRecoveryError("invalid_request")
    pending = maintenance.pending()
    if pending is not None and pending["state"] == "prepared":
        if pending["new_verifier_b64u"] != new_verifier:
            raise OwnerRecoveryError("pending")  # cancel it first
        maintenance.request_bytes(pending)
        return _prepared(maintenance, pending, repeated=True)
    if pending is not None and pending["state"] == "importing":
        raise OwnerRecoveryError("import_in_progress")
    profile, configuration = maintenance.configuration()
    if configuration["verifier_b64u"] == new_verifier:
        raise OwnerRecoveryError("invalid_request")  # the old capability never opens a new epoch
    root, database = _consistent_epoch(maintenance, profile, configuration)
    now = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    request_id = str(uuid4())
    request = make_recovery_request(
        profile=profile, request_id=request_id, nonce=os.urandom(32), actor_ref=database["actor"],
        created_ms=now - now % 1000, ttl_seconds=ttl_seconds, current_epoch=root["epoch"],
        current_generation_id=root["generation_id"], current_manifest_sha256=root["manifest_sha256"])
    # the request file is written before the pointer names it: an unnamed request file left
    # by a crash is inert, and a receipt for it is never imported
    _replace(maintenance.requests, request_id + ".json", request, mode=0o644)
    _step("request_written")
    value = {"schema": PENDING_SCHEMA, "state": "prepared", "request_id": request_id,
             "request_sha256": _sha256(request), "new_verifier_b64u": new_verifier,
             "previous_epoch": root["epoch"], "receipt_sha256": None, "trust_set_sha256": None}
    maintenance.set_pending(value)
    return _prepared(maintenance, value, repeated=False)


def _prepared(maintenance, pending, *, repeated):
    request = parse_canonical(maintenance.request_bytes(pending))
    return {"state": "prepared", "repeated": repeated, "request_id": pending["request_id"],
            "request_path": str(maintenance.work_path / "requests" / (pending["request_id"] + ".json")),
            "previous_epoch": pending["previous_epoch"], "target_epoch": pending["previous_epoch"] + 1,
            "expires_at": request["expires_at"]}


def cancel(maintenance):
    pending = maintenance.pending()
    if pending is None:
        raise OwnerRecoveryError("no_pending")
    if pending["state"] == "cancelled":
        return {"state": "cancelled", "repeated": True, "request_id": pending["request_id"]}
    if pending["state"] == "importing":
        raise OwnerRecoveryError("import_in_progress")  # re-run import to complete it
    if pending["state"] == "imported":
        raise OwnerRecoveryError("already_imported")
    maintenance.set_pending({**pending, "state": "cancelled"})
    return {"state": "cancelled", "repeated": False, "request_id": pending["request_id"]}


def import_receipt(maintenance, *, receipt_bytes, trust_bytes):
    from ..deployment.receipt_contracts import ReceiptWireError
    from ..deployment.recovery_contracts import (
        parse_recovery_receipt,
        verifier_sha256,
        verify_recovery_receipt,
    )
    from ..operations.setup import build_recovered_configuration
    from .session_root import SessionRootError, advance_session_root

    if type(receipt_bytes) is not bytes or type(trust_bytes) is not bytes:
        raise OwnerRecoveryError("invalid_request")
    pending = maintenance.pending()
    if pending is None:
        raise OwnerRecoveryError("no_pending")
    try:
        claimed = parse_recovery_receipt(receipt_bytes)["request_id"]
    except ReceiptWireError:
        raise OwnerRecoveryError("receipt_invalid") from None
    if claimed != pending["request_id"]:
        # a receipt for any request this tool sealed earlier (cancelled or already consumed)
        # is a replay; one for a request it never sealed is foreign
        known = _read(maintenance.requests, claimed + ".json", 4096, maintenance.uid, maintenance.gid)
        raise OwnerRecoveryError("replayed" if known is not None else "receipt_mismatch")
    if pending["state"] == "cancelled":
        raise OwnerRecoveryError("cancelled")
    if pending["state"] == "imported":
        if _sha256(receipt_bytes) != pending["receipt_sha256"]:
            raise OwnerRecoveryError("replayed")
        return _imported(pending, repeated=True)
    request_bytes = maintenance.request_bytes(pending)
    profile, configuration = maintenance.configuration()
    try:
        receipt = verify_recovery_receipt(receipt_bytes, request_bytes=request_bytes,
                                          trust_bytes=trust_bytes, profile=profile)
    except ReceiptWireError:
        raise OwnerRecoveryError("receipt_invalid") from None
    if receipt["new_verifier_sha256"] != verifier_sha256(pending["new_verifier_b64u"]):
        raise OwnerRecoveryError("receipt_mismatch")
    previous, target = pending["previous_epoch"], pending["previous_epoch"] + 1
    if pending["state"] == "prepared":
        # the root, configuration and database must still be exactly where the request found them
        if configuration["recovery_epoch"] != previous:
            raise OwnerRecoveryError("unavailable")
        root, _database = _consistent_epoch(maintenance, profile, configuration)
        if (root["generation_id"], root["manifest_sha256"]) != (
                receipt["previous_generation_id"], receipt["previous_manifest_sha256"]):
            raise OwnerRecoveryError("receipt_mismatch")
        _replace(maintenance.receipts, pending["request_id"] + ".json", receipt_bytes, mode=0o644)
        pending = {**pending, "state": "importing", "receipt_sha256": _sha256(receipt_bytes),
                   "trust_set_sha256": _sha256(trust_bytes)}
        maintenance.set_pending(pending)
        _step("importing_recorded")
    elif _sha256(receipt_bytes) != pending["receipt_sha256"]:
        raise OwnerRecoveryError("import_in_progress")  # only the journaled receipt completes it
    try:
        manifest = advance_session_root(maintenance.root_dir, profile=profile, receipt_bytes=receipt_bytes,
                                        request_bytes=request_bytes, trust_bytes=trust_bytes,
                                        expected_uid=maintenance.uid, expected_gid=maintenance.gid)
    except SessionRootError:
        raise OwnerRecoveryError("root_unavailable") from None
    _step("root_advanced")
    recovered = build_recovered_configuration(profile=profile, verifier_b64u=pending["new_verifier_b64u"],
                                              recovery_epoch=target)
    if configuration != recovered:
        if configuration["recovery_epoch"] != previous:
            raise OwnerRecoveryError("unavailable")
        maintenance.write_configuration(recovered)
    _step("config_written")
    pending = {**pending, "state": "imported"}
    maintenance.set_pending(pending)
    return _imported(pending, repeated=False, generation_id=manifest["generation_id"])


def _imported(pending, *, repeated, generation_id=None):
    result = {"state": "imported", "repeated": repeated, "request_id": pending["request_id"],
              "recovery_epoch": pending["previous_epoch"] + 1,
              "next": "start the control plane with --recovery-trust-set; the owner then sets up again "
                      "with the new one-time capability"}
    if generation_id is not None:
        result["generation_id"] = generation_id
    return result


# ---- command line ------------------------------------------------------------------------

def open_maintenance(*, data_dir, session_root_dir, deployment_config, work_dir, expected_uid, expected_gid):
    return _Maintenance(data_dir=data_dir, session_root_dir=session_root_dir,
                        deployment_config=deployment_config, work_dir=work_dir,
                        expected_uid=expected_uid, expected_gid=expected_gid)


def run(argv=None):
    parser = argparse.ArgumentParser(prog="python -m app.operations.deployment_control",
                                     description="DeepTwin owner-recovery maintenance (control plane stopped)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "prepare", "cancel", "import"):
        command = commands.add_parser(name)
        for option in ("--data-dir", "--session-root-dir", "--deployment-config", "--work-dir"):
            command.add_argument(option, type=Path, required=True)
        command.add_argument("--expected-uid", type=int, required=True)
        command.add_argument("--expected-gid", type=int, required=True)
        if name == "prepare":
            command.add_argument("--new-verifier", required=True,
                                 help="the non-secret verifier of the new one-time capability")
            command.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
        if name == "import":
            command.add_argument("--receipt", type=Path, required=True)
            command.add_argument("--trust-set", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        inputs = {}
        if args.command == "import":
            inputs = {"receipt_bytes": _read_input(args.receipt, 8192),
                      "trust_bytes": _read_input(args.trust_set, 16384)}
        with open_maintenance(data_dir=args.data_dir, session_root_dir=args.session_root_dir,
                              deployment_config=args.deployment_config, work_dir=args.work_dir,
                              expected_uid=args.expected_uid, expected_gid=args.expected_gid) as maintenance:
            if args.command == "status":
                result = status(maintenance)
            elif args.command == "prepare":
                result = prepare(maintenance, new_verifier=args.new_verifier, ttl_seconds=args.ttl_seconds)
            elif args.command == "cancel":
                result = cancel(maintenance)
            else:
                result = import_receipt(maintenance, **inputs)
    except OwnerRecoveryError as error:
        sys.stdout.write(canonical_json({"state": "refused", "code": error.code}).decode("utf-8") + "\n")
        return 2
    sys.stdout.write(canonical_json(result).decode("utf-8") + "\n")
    return 0


def main():
    raise SystemExit(run())


if __name__ == "__main__":
    main()
