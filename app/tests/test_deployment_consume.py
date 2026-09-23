"""Task 24 step (e2b): the service consume transaction against the actual
in-process staged worker (contracts/deployment-receipt-journal-v3.md §4 expected
derivation, §5 consume transaction, §6 admission matrix).

`PersistentDeploymentPrepare.consume_receipt` admits the command, expires a
due head before any socket, derives the expectation from the retained slot
and the candidate's provenance lineage, observes the staged service through
`stage_observer` (the responder is the actual `WorkerProbeService` over the
macOS seams), preseals the evidence, and commits the acceptance body in the
final writer after repeating every check. Every failure after the preseal
leaves no authority; a mismatch is 409; an unobservable service is 503.
"""

import sqlite3
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from app.deployment import prepare_records as records
from app.deployment import prepare_storage as storage
from app.deployment import stage_observer
from app.deployment.prepare_contracts import DeploymentPrepareError
from app.domain.refs import canonical_json, parse_canonical
from app.extensions.candidate_contracts import metadata_ref, parse_bundle
from app.extensions.lineage_contracts import parse_lineage
from app.tests import deployment_prepare_fixture
from app.tests.deployment_receipt_import_fixture import receipt_context, signed_case
from app.tests.deployment_source_fixture import decoded_artifacts, profile
from app.tests.extension_candidate_fixture import candidate_payload
from app.tests.test_extension_lineage_contracts import lineage_mapping
from app.tests.test_extension_listener import open_fds
from app.tests.test_extension_probe import serve_in_thread
from app.tests.test_extension_worker_metadata import (
    GID,
    UID,
    WORKER_BYTES,
    _identity_bytes,
)
from app.workers import broker, listener
from app.workers import extension_metadata as em
from app.workers import extension_probe as ep
from app.workers.extension_channel import extension_channel

SLOT = 1


def worker_identity_bytes():
    return _identity_bytes(WORKER_BYTES)


def lineage_bundle(*, identity_bytes=None, slot=SLOT):
    """A candidate whose provenance is a real lineage joined to its descriptor,
    with the selected platform's embedded identity equal to the staged worker's
    identity file (so the probe reply can agree with the expectation)."""
    origin = profile()
    mapping = lineage_mapping()
    mapping["platforms"][0]["build_identity"] = parse_canonical(
        identity_bytes or worker_identity_bytes()
    )
    lineage = parse_lineage(canonical_json(mapping))
    value = candidate_payload()
    topology = decoded_artifacts()[0]
    topology_slot = topology["slots"][slot - 1]
    descriptor = value["service_descriptor"]
    descriptor["index"] = deepcopy(mapping["index"])
    descriptor["platforms"] = [
        deepcopy(item["measured_platform_entry"]) for item in mapping["platforms"]
    ]
    descriptor["evidence"]["provenance_ref"] = metadata_ref("provenance", lineage.content_bytes)
    descriptor["command"] = {
        "protocol_id": "deeptwin-extension-worker-v1",
        "argv": [
            "/opt/deeptwin-extension/bin/worker",
            "--instance-id",
            origin.instance_id,
            "--slot-number",
            str(slot),
        ],
    }
    descriptor.update(
        service_identity=topology_slot["service_identity"],
        uid=topology_slot["uid"],
        gid=topology_slot["gid"],
        socket_mounts=[topology_slot["socket_mount"]],
    )
    descriptor["broker_endpoint"] = {
        "channel_id": topology_slot["channel_id"],
        "requester_service": "control",
        "responder_service": topology_slot["service_identity"],
        "protocol_id": topology_slot["protocol_id"],
        "requester_uid": 20102,
        "requester_gid": 20102,
        "pair_gid": topology_slot["pair_gid"],
        "socket_mount_id": topology_slot["socket_mount"]["mount_id"],
        "socket_name": "worker.sock",
    }
    for document in value["documents"]:
        if document["document_kind"] == "provenance":
            document["content"] = mapping
    value["manifest"]["source"]["provenance_ref"] = metadata_ref(
        "provenance", lineage.content_bytes
    )
    value["manifest"]["artifact"]["service_descriptor_ref"] = metadata_ref(
        "service_descriptor", canonical_json(descriptor)
    )
    return parse_bundle(value), topology, topology_slot


class StagedWorker:
    """The actual probe service of the admitted slot on the source fixture's
    pair root (the fixture already initialised `/run/deeptwin/ipc/xs01` with
    fake ownership).

    Every seam this host needs, in one place — none of them is a check this
    suite can claim: both extension handshakes run with `verify_peer=False`
    (no SO_PEERCRED on macOS); the connect seam returns a fixed
    `PeerCredentials` equal to the slot, so a peer-uid mismatch is the observer
    suite's case, never this one's; `listener._process_identity` reports the
    slot's uid/gid/pair gid; `os.chown` of the bound socket registers fake
    ownership like the fixture's `fchown`; the AF_UNIX bind goes through a
    short `/private/tmp` alias; mountinfo is synthetic and thread-keyed (the
    worker sees its slot read-write, control read-only); the worker's
    metadata source runs on a fixed-file tree at a real path with the
    fixture's directory remap bypassed for that tree only, and its
    `_expected_owner`/`_credentials`/`_native_platform` are faked (the
    identity file is the lineage's embedded amd64 identity unless the test
    wants a divergent worker). Positive Linux authentication, real mounts, the
    real worker image and the container are host gates."""

    def __init__(self, fixture, profile, monkeypatch, *, identity_bytes=None):
        import os
        import socket
        import threading

        from app.deployment import files as f
        from app.deployment import mounts as m
        from app.extensions.port_contracts import PORT_SCHEMA_SHAPES
        from app.tests.test_extension_lineage_contracts import shipped_schema_bytes
        from app.tests.test_extension_worker_metadata import _write

        # `fixture` is the ActualSources fixture (remapped roots, fake ownership)
        self.instance_id = profile.instance_id
        root, spec = extension_channel(instance_id=self.instance_id, slot_number=SLOT)
        self.root, self.spec = root, spec
        mapped = fixture.actual(root.pair_root)
        assert (mapped / "endpoint").is_dir()
        original_stat = fixture.original_stat
        monkeypatch.setattr(
            listener, "_process_identity",
            lambda: (root.responder_uid, root.responder_gid, frozenset({root.pair_gid})),
        )

        def chown(path, uid, gid, *, dir_fd=None, follow_symlinks=True):
            # the bound socket's ownership is registered like the fixture's fchown
            info = original_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
            fixture.metadata[(info.st_dev, info.st_ino)] = (uid, gid)

        monkeypatch.setattr(os, "chown", chown)
        self.alias_root = Path(tempfile.mkdtemp(
            prefix="dt-consume-", dir="/private/tmp" if sys.platform == "darwin" else None))
        (self.alias_root / "endpoint").symlink_to(mapped / "endpoint", target_is_directory=True)
        monkeypatch.setattr(
            listener, "_anchored_socket_path",
            lambda _fd, _pair, name: str(self.alias_root / "endpoint" / name),
        )

        def server(sock, channel_spec, secret, *, responder_boot_id, deadline):
            return broker._extension_server_handshake_impl(
                sock, channel_spec, secret, responder_boot_id=responder_boot_id,
                deadline=deadline, verify_peer=False,
            )

        def client(sock, channel_spec, secret, *, requester_boot_id, responder_boot_id, deadline):
            return broker._extension_client_handshake_impl(
                sock, channel_spec, secret, requester_boot_id=requester_boot_id,
                responder_boot_id=responder_boot_id, deadline=deadline, verify_peer=False,
            )

        peer = broker.PeerCredentials(pid=4242, uid=root.responder_uid, gid=root.responder_gid)

        def connect_verified(channel_spec, *, local_service, deadline):
            path = listener._anchored_socket_path(-1, root, channel_spec.socket_name)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(path)
            return sock, broker._endpoint_identity(os.stat(path)), peer

        monkeypatch.setattr(listener.broker, "_extension_server_handshake", server)
        monkeypatch.setattr(listener.broker, "_extension_client_handshake", client)
        monkeypatch.setattr(listener.broker, "connect_verified", connect_verified)
        info = original_stat(mapped)
        device = f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}"
        self.side = {"worker_ident": None}

        def read_mountinfo():
            flag = "rw" if threading.get_ident() == self.side["worker_ident"] else "ro"
            return m.parse_mountinfo(
                f"1 1 {device} / {root.pair_root} {flag},relatime shared:1 - tmpfs tmpfs rw\n".encode()
            )

        monkeypatch.setattr(listener, "_read_mountinfo", read_mountinfo)

        def derived(*, instance_id, slot_number):
            derived_root, derived_spec = extension_channel(
                instance_id=instance_id, slot_number=slot_number
            )
            assert (instance_id, slot_number) == (self.instance_id, SLOT)
            return derived_root, derived_spec

        monkeypatch.setattr(ep, "extension_channel", derived)
        monkeypatch.setattr(stage_observer, "extension_channel", derived)
        # the worker's fixed-file tree at a real path: directory opens under it
        # bypass the fixture's root remapping, ownership is the fixture's default
        tree = fixture.base / "staged-worker" / "root"
        prefix = tree / "opt" / "deeptwin-extension"
        _write(prefix / "bin" / "worker", WORKER_BYTES, 0o555)
        _write(
            prefix / "identity" / "build-identity-v1.json",
            identity_bytes or worker_identity_bytes(),
            0o444,
        )
        for role, raw in zip(PORT_SCHEMA_SHAPES, shipped_schema_bytes(), strict=True):
            _write(prefix / "ports" / "tool-port-v1" / f"{role}.schema.json", raw, 0o444)
        for directory in (tree, tree / "opt", prefix, prefix / "bin", prefix / "identity",
                          prefix / "ports", prefix / "ports" / "tool-port-v1"):
            directory.chmod(0o755)
        remapped_open = f.open_directory
        real_open = fixture.original_open_directory

        def open_directory(path, **kwargs):
            if Path(path).is_relative_to(tree):
                return real_open(path, **kwargs)
            return remapped_open(path, **kwargs)

        monkeypatch.setattr(f, "open_directory", open_directory)
        tree_info = original_stat(tree)
        tree_device = f"{os.major(tree_info.st_dev)}:{os.minor(tree_info.st_dev)}"
        table = m.parse_mountinfo(
            f"1 1 {tree_device} / {tree} ro,relatime shared:1 - tmpfs tmpfs rw\n".encode()
        )
        monkeypatch.setattr(em, "EXTENSION_ROOT", tree)
        monkeypatch.setattr(em, "EXTENSION_PREFIX", prefix)
        # unregistered inodes keep their real ownership under the fixture
        monkeypatch.setattr(em, "_expected_owner", lambda: (os.getuid(), os.getgid()))
        monkeypatch.setattr(em, "_native_platform", lambda: "linux/amd64")
        monkeypatch.setattr(em, "_credentials", lambda: (UID, UID, GID, GID))
        monkeypatch.setattr(em, "_read_mountinfo", lambda: table)
        self.service = None

    def start(self):
        self.service = ep.open_worker_probe_service(
            instance_id=self.instance_id, slot_number=SLOT
        )
        self.box = {}
        self.thread = serve_in_thread(self.service, self.box, self.side, deadline_ms=20_000)

    def stop(self):
        if self.service is not None:
            self.thread.join(25)
            try:
                self.service.close()
            except ep.ProbeServiceError:
                pass
            self.service = None
        if self.alias_root is not None:
            (self.alias_root / "endpoint").unlink(missing_ok=True)
            self.alias_root.rmdir()
            self.alias_root = None


def pending(actual, monkeypatch):
    prepared, command, _, _ = signed_case(
        actual, monkeypatch, case_name="valid_succeeded_present"
    )
    result = actual.service.import_receipt(actual.request, prepared["request_id"], command)
    assert result["disposition"] == "pending_postconditions"
    return prepared, command


def consume_payload(prepared, command):
    return {
        "command_id": str(uuid4()),
        "request_digest": prepared["request_digest"],
        "receipt_digest": command["receipt_digest"],
        "expected_revision": 2,
    }


def counts(domain):
    with domain._connection() as db:
        return tuple(
            db.execute("SELECT count(*) FROM deployment_prepare_" + table).fetchone()[0]
            for table in ("installations", "installation_heads", "consumptions",
                          "consumed_outbox", "commands", "lifecycle")
        )


@pytest.fixture
def lineage_candidate(monkeypatch):
    bundle = lineage_bundle()
    monkeypatch.setattr(deployment_prepare_fixture, "matching_bundle", lambda: bundle)
    return bundle


def test_consume_observes_the_actual_staged_worker_and_commits_accepted3(
    tmp_path, monkeypatch, lineage_candidate
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command = pending(actual, monkeypatch)
        # the staged worker's seams are installed after prepare/import: the
        # consume transaction reacquires no slot lease and no live source
        worker = StagedWorker(actual.actual, actual.profile, monkeypatch)
        before = counts(actual.domain)
        baseline = open_fds()
        worker.start()
        try:
            payload = consume_payload(prepared, command)
            reply = actual.service.consume_receipt(actual.request, prepared["request_id"], payload)
        finally:
            worker.stop()
        assert worker.box.get("served") == 2, worker.box.get("error")
        assert reply["disposition"] == "consumed_success" and reply["revision"] == 3
        assert reply["command_id"] == payload["command_id"]
        current = actual.service.read(actual.read_request, prepared["request_id"])
        assert current["state"] == "accepted" and current["installation"] == reply["installation"]
        assert counts(actual.domain) == (
            before[0] + 1, before[1] + 1, before[2] + 1, before[3], before[4] + 1, before[5] + 1,
        )
        with actual.domain._connection() as db:
            journal = records.verify(actual.domain, db, actual.profile)
            item = journal["requests"][prepared["request_id"]]
            expected = records.expected_stage_identity(
                actual.domain, db, actual.profile, item
            )
        evidence = item["installation"]["evidence"]
        assert evidence["expected"] == expected.as_dict()
        assert evidence["connection"]["requester_boot_id"] == stage_observer._process_boot_id()
        # the worker's code-owned registry now carries `status` (T087 slice)
        assert evidence["probes"][0]["reply"]["runtime"]["registered_operations"] == ["describe_tools", "invoke_tool", "status"]
        # exact replay returns the frozen reply without a second observation
        observed = []
        monkeypatch.setattr(
            stage_observer, "observe_stage_postcondition",
            lambda **kwargs: observed.append(kwargs) or (_ for _ in ()).throw(AssertionError()),
        )
        assert actual.service.consume_receipt(actual.request, prepared["request_id"], payload) == reply
        assert observed == []
        # accepted3 + any: a fresh consume, a cancel and an import are 409
        for call in (
            lambda: actual.service.consume_receipt(
                actual.request, prepared["request_id"], consume_payload(prepared, command)
            ),
            lambda: actual.service.cancel(
                actual.request, prepared["request_id"],
                {"command_id": str(uuid4()), "request_digest": prepared["request_digest"],
                 "expected_revision": 3},
            ),
            lambda: actual.service.import_receipt(
                actual.request, prepared["request_id"], {**command, "command_id": str(uuid4())}
            ),
        ):
            with pytest.raises(DeploymentPrepareError) as failure:
                call()
            assert failure.value.code == "conflict"
        assert open_fds() == baseline


def test_a_worker_whose_identity_differs_from_the_lineage_is_a_conflict(
    tmp_path, monkeypatch, lineage_candidate
):
    other = parse_canonical(worker_identity_bytes())
    other["extension_version"] = "1.0.1"
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command = pending(actual, monkeypatch)
        worker = StagedWorker(actual.actual, actual.profile, monkeypatch, identity_bytes=canonical_json(other))
        before = counts(actual.domain)
        blobs_before = blob_count(actual.domain)
        worker.start()
        try:
            with pytest.raises(DeploymentPrepareError) as failure:
                actual.service.consume_receipt(
                    actual.request, prepared["request_id"], consume_payload(prepared, command)
                )
        finally:
            worker.stop()
        assert failure.value.code == "conflict"
        assert counts(actual.domain) == before
        assert blob_count(actual.domain) == blobs_before  # nothing was presealed
        assert actual.service.read(actual.read_request, prepared["request_id"])["state"] == "receipt_pending"


def blob_count(domain):
    with domain._connection() as db:
        return db.execute("SELECT count(*) FROM domain_blobs").fetchone()[0]


def test_an_unobservable_staged_service_is_dependency_unavailable(
    tmp_path, monkeypatch, lineage_candidate
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command = pending(actual, monkeypatch)
        StagedWorker(actual.actual, actual.profile, monkeypatch)  # seams only: no probe service is listening
        before = counts(actual.domain)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.consume_receipt(
                actual.request, prepared["request_id"], consume_payload(prepared, command)
            )
        assert failure.value.code == "dependency_unavailable"
        assert counts(actual.domain) == before


def test_a_candidate_without_a_lineage_provenance_is_refused_before_any_socket(
    tmp_path, monkeypatch
):
    # the default fixture candidate carries a synthetic provenance document
    observed = []
    monkeypatch.setattr(
        stage_observer, "observe_stage_postcondition",
        lambda **kwargs: observed.append(kwargs) or (_ for _ in ()).throw(AssertionError()),
    )
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command = pending(actual, monkeypatch)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.consume_receipt(
                actual.request, prepared["request_id"], consume_payload(prepared, command)
            )
        assert failure.value.code == "conflict"
        assert observed == []


def test_a_due_head_expires_before_any_socket_and_wrong_heads_conflict(
    tmp_path, monkeypatch, lineage_candidate
):
    import time

    observed = []
    monkeypatch.setattr(
        stage_observer, "observe_stage_postcondition",
        lambda **kwargs: observed.append(kwargs) or (_ for _ in ()).throw(AssertionError()),
    )
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command = pending(actual, monkeypatch)
        current = actual.service.read(actual.read_request, prepared["request_id"])
        from app.deployment.prepare_contracts import epoch_ms

        # wrong digest / revision / unknown request: 409 and 404, no observation
        for change, code in (
            ({"request_digest": "A" * 43}, "conflict"),
            ({"expected_revision": 1}, "invalid_input"),
        ):
            with pytest.raises(DeploymentPrepareError) as failure:
                actual.service.consume_receipt(
                    actual.request, prepared["request_id"],
                    {**consume_payload(prepared, command), **change},
                )
            assert failure.value.code == code
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.consume_receipt(
                actual.request, str(uuid4()), consume_payload(prepared, command)
            )
        assert failure.value.code == "not_found"
        # the matching due head expires (revision 3) and returns 409
        deadline = epoch_ms(current["request"]["expires_at"])
        monkeypatch.setattr(time, "time_ns", lambda: deadline * 1_000_000)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.consume_receipt(
                actual.request, prepared["request_id"], consume_payload(prepared, command)
            )
        assert failure.value.code == "conflict"
        after = actual.service.read(actual.read_request, prepared["request_id"])
        assert after["state"] == "expired" and after["revision"] == 3
        assert observed == []


def test_the_final_writer_rechecks_the_head_after_the_observation(
    tmp_path, monkeypatch, lineage_candidate
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command = pending(actual, monkeypatch)
        worker = StagedWorker(actual.actual, actual.profile, monkeypatch)
        original = actual.domain.put_blob
        cancelled = {"done": False}

        def preseal(*args, **kwargs):
            blob = original(*args, **kwargs)
            if not cancelled["done"]:
                cancelled["done"] = True
                actual.service.cancel(
                    actual.request, prepared["request_id"],
                    {"command_id": str(uuid4()), "request_digest": prepared["request_digest"],
                     "expected_revision": 2},
                )
            return blob

        monkeypatch.setattr(actual.domain, "put_blob", preseal)
        before = counts(actual.domain)
        worker.start()
        try:
            with pytest.raises(DeploymentPrepareError) as failure:
                actual.service.consume_receipt(
                    actual.request, prepared["request_id"], consume_payload(prepared, command)
                )
        finally:
            worker.stop()
        assert failure.value.code == "conflict"
        assert cancelled["done"]
        after = counts(actual.domain)
        assert after[:4] == before[:4]  # no installation, head or consumption
        assert actual.service.read(actual.read_request, prepared["request_id"])["state"] == "cancelled"


@pytest.mark.parametrize(
    "target", ["installation_anchor", "acceptance", "staged_event", "consumption_anchor",
               "consumptions", "installations", "installation_heads", "commit"],
)
def test_each_authority_write_fault_leaves_no_partial_acceptance(
    tmp_path, monkeypatch, lineage_candidate, target
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command = pending(actual, monkeypatch)
        worker = StagedWorker(actual.actual, actual.profile, monkeypatch)
        before = counts(actual.domain)
        blobs_before = blob_count(actual.domain)
        original_insert = storage.insert
        original_put = actual.domain._put_in_transaction
        original_transition = records.lifecycle.commit_acceptance_transition
        original_staged = records.lifecycle.append_staged_event

        def fail():
            raise sqlite3.OperationalError("controlled authority fault")

        puts = {"count": 0}

        def put(db, record):
            puts["count"] += 1
            if (target == "installation_anchor" and puts["count"] == 1) or (
                target == "consumption_anchor" and puts["count"] == 2
            ):
                fail()
            return original_put(db, record)

        def insert(db, table, values):
            if table == target:
                fail()
            return original_insert(db, table, values)

        def transition(*args, **kwargs):
            if target == "acceptance":
                fail()
            return original_transition(*args, **kwargs)

        def staged(*args, **kwargs):
            if target == "staged_event":
                fail()
            return original_staged(*args, **kwargs)

        monkeypatch.setattr(actual.domain, "_put_in_transaction", put)
        monkeypatch.setattr(storage, "insert", insert)
        monkeypatch.setattr(records.lifecycle, "commit_acceptance_transition", transition)
        monkeypatch.setattr(records.lifecycle, "append_staged_event", staged)
        if target == "commit":
            real_connection = actual.domain._connection

            def denying_connection(*args, **kwargs):
                manager = real_connection(*args, **kwargs)

                class Wrapper:
                    def __enter__(self_inner):
                        db = manager.__enter__()
                        if kwargs.get("write"):
                            db.set_authorizer(
                                lambda action, a1, a2, database, trigger: (
                                    sqlite3.SQLITE_DENY
                                    if action == sqlite3.SQLITE_TRANSACTION and a1 == "COMMIT"
                                    and counts_installations(db)
                                    else sqlite3.SQLITE_OK
                                )
                            )
                        return db

                    def __exit__(self_inner, *exc):
                        return manager.__exit__(*exc)

                return Wrapper()

            def counts_installations(db):
                return db.execute("SELECT count(*) FROM deployment_prepare_installations").fetchone()[0] > 0

            monkeypatch.setattr(actual.domain, "_connection", denying_connection)
        worker.start()
        try:
            with pytest.raises((DeploymentPrepareError, sqlite3.Error)):
                actual.service.consume_receipt(
                    actual.request, prepared["request_id"], consume_payload(prepared, command)
                )
        finally:
            worker.stop()
        monkeypatch.undo()
        assert counts(actual.domain) == before
        # the fault fired after the preseal: exactly the orphan blob remains
        assert blob_count(actual.domain) == blobs_before + 1
        with actual.domain._connection() as db:
            journal = records.verify(actual.domain, db, actual.profile)
        assert journal["requests"][prepared["request_id"]]["history"][-1]["state"] == "receipt_pending"


@pytest.mark.parametrize("code", ["probe_invalid", "probe_deadline", "probe_unavailable"])
def test_every_non_mismatch_observer_failure_is_dependency_unavailable_with_no_authority(
    tmp_path, monkeypatch, lineage_candidate, code
):
    def failing(**kwargs):
        raise stage_observer.StagePostconditionError(code)

    monkeypatch.setattr(stage_observer, "observe_stage_postcondition", failing)
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command = pending(actual, monkeypatch)
        before, blobs = counts(actual.domain), blob_count(actual.domain)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.consume_receipt(
                actual.request, prepared["request_id"], consume_payload(prepared, command)
            )
        assert failure.value.code == "dependency_unavailable"
        assert counts(actual.domain) == before and blob_count(actual.domain) == blobs
        assert actual.service.read(actual.read_request, prepared["request_id"])["state"] == "receipt_pending"


def test_replay_with_a_changed_body_or_a_foreign_command_id_is_a_conflict(
    tmp_path, monkeypatch, lineage_candidate
):
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command = pending(actual, monkeypatch)
        worker = StagedWorker(actual.actual, actual.profile, monkeypatch)
        worker.start()
        try:
            payload = consume_payload(prepared, command)
            reply = actual.service.consume_receipt(actual.request, prepared["request_id"], payload)
        finally:
            worker.stop()
        observed = []
        monkeypatch.setattr(
            stage_observer, "observe_stage_postcondition",
            lambda **kwargs: observed.append(kwargs) or (_ for _ in ()).throw(AssertionError()),
        )
        # the same command id with a different body is not a replay
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.consume_receipt(
                actual.request, prepared["request_id"], {**payload, "receipt_digest": "A" * 43}
            )
        assert failure.value.code == "conflict"
        # the import command's id presented as a consume is another operation's command
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.consume_receipt(
                actual.request, prepared["request_id"],
                {**payload, "command_id": command["command_id"]},
            )
        assert failure.value.code == "conflict"
        assert observed == []
        assert actual.service.consume_receipt(actual.request, prepared["request_id"], payload) == reply


def test_a_prepared_head_without_a_receipt_is_a_conflict_before_any_socket(
    tmp_path, monkeypatch, lineage_candidate
):
    observed = []
    monkeypatch.setattr(
        stage_observer, "observe_stage_postcondition",
        lambda **kwargs: observed.append(kwargs) or (_ for _ in ()).throw(AssertionError()),
    )
    with receipt_context(tmp_path, monkeypatch) as actual:
        prepared = actual.service.prepare(actual.request, actual.payload)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.consume_receipt(
                actual.request, prepared["request_id"],
                {"command_id": str(uuid4()), "request_digest": prepared["request_digest"],
                 "receipt_digest": "E" * 43, "expected_revision": 2},
            )
        assert failure.value.code == "conflict"
        assert observed == []
        assert actual.service.read(actual.read_request, prepared["request_id"])["state"] == "prepared"
