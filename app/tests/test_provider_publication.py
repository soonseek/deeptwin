"""Source-bound publication on real trees, with independent canonical wire fixtures."""

import hashlib
import importlib
import json
import os
import stat
import subprocess
import sys
from base64 import urlsafe_b64decode, urlsafe_b64encode
from copy import deepcopy

import pytest

from app.deployment import contracts as c
from app.deployment import files as f
from app.deployment import publication as p
from app.deployment.provider_prepare_contracts import (
    parse_provider_cancellation,
    parse_provider_request,
)
from app.domain.refs import canonical_json
from app.operations.setup import OriginProfile
from app.tests.provider_source_reader_fixture import BASE, STATIC, ReaderTree
from app.tests.test_provider_prepare_contracts import (
    _expected_effect,
    _inputs,
    _inventory_entry,
)


def publisher():
    try:
        return importlib.import_module("app.deployment.provider_publication")
    except ModuleNotFoundError as error:
        assert error.name == "app.deployment.provider_publication"
        pytest.fail("Actual source-bound provider publisher is missing")


def signed(value):
    unsigned = {key: item for key, item in value.items() if key != "request_digest"}
    value = deepcopy(unsigned)
    value["request_digest"] = (
        urlsafe_b64encode(hashlib.sha256(canonical_json(unsigned)).digest())
        .rstrip(b"=")
        .decode()
    )
    return canonical_json(value)


def wire_pair(**options):
    # Accepted independent source/candidate fixtures and hand-authored envelope;
    # neither publisher nor Task38 constructors produce the expected bytes.
    inputs, lineage = _inputs(**options)
    profile = inputs["profile"]
    request = signed(
        {
            "schema": "deployment-request-v2",
            "domain": "deeptwin-deployment-request-v2",
            "request_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "kind": "extension_stage",
            "request_nonce": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
            "instance_id": profile.instance_id,
            "origin_profile_digest": urlsafe_b64encode(bytes.fromhex(profile.digest))
            .rstrip(b"=")
            .decode(),
            "effect_payload": _expected_effect(inputs, lineage),
            "preconditions": {},
            "created_by": {
                "kind": "actor",
                "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                "version": 1,
                "sha256": "9" * 64,
            },
            "created_at": "2023-11-14T22:13:20.000Z",
            "expires_at": "2023-11-14T23:13:20.000Z",
        }
    )
    data = json.loads(request)
    cancellation = canonical_json(
        {
            "schema": "deployment-provider-cancellation-v1",
            "domain": "deeptwin-deployment-provider-cancellation-v1",
            "request_id": data["request_id"],
            "request_digest": data["request_digest"],
            "instance_id": data["instance_id"],
            "origin_profile_digest": data["origin_profile_digest"],
            "source_context_sha256": data["effect_payload"]["source_context"]["sha256"],
            "preserved_inventory_sha256": data["effect_payload"][
                "preserved_inventory_sha256"
            ],
            "lifecycle_revision": 2,
            "cancelled_at": "2023-11-14T22:14:20.000Z",
        }
    )
    return (("request", request), ("cancel", cancellation))


def publication_tree(tmp_path, monkeypatch, **options):
    tree = ReaderTree(tmp_path, monkeypatch, **options)
    observe = tree.observed

    def linux_metadata(info):
        value = observe(info)
        # APFS counts regular entries in directory nlink; Linux ext4 does not.
        if stat.S_ISDIR(value.st_mode):
            value.st_nlink = 2
        return value

    tree.observed = linux_metadata
    open_fd = os.open

    def opened_fd(path, flags, *args, **kwargs):
        fd = open_fd(path, flags, *args, **kwargs)
        if flags & os.O_CREAT and str(path).startswith(".stage-"):
            info = tree.raw_fstat(fd)
            tree.metadata[(info.st_dev, info.st_ino)] = 20102, 20102
        return fd

    monkeypatch.setattr(os, "open", opened_fd)

    def chown(fd, uid, gid):
        assert uid == -1 and gid == 21201
        info = tree.raw_fstat(fd)
        tree.metadata[(info.st_dev, info.st_ino)] = 20102, gid

    def rename(fd, source, target):
        # Test-only syscall substitute. Real names/inodes, never a native claim.
        os.link(source, target, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        os.unlink(source, dir_fd=fd)

    monkeypatch.setattr(os, "fchown", chown)
    monkeypatch.setattr(p, "_rename_noreplace", rename)
    return tree


@pytest.fixture
def pub_tree(tmp_path, monkeypatch):
    tree = publication_tree(tmp_path, monkeypatch)
    yield tree
    for fd in tuple(tree.live):
        tree.raw_close(fd)


def opened(tree, payloads=None):
    context = tree.open()
    try:
        lease = publisher().open_provider_outbox_lease(
            context,
            profile=tree.profile,
            expected_payloads=wire_pair() if payloads is None else payloads,
        )
    except BaseException:
        context.close()
        raise
    return context, lease


def digest_of(payloads):
    return json.loads(payloads[0][1])["request_digest"]


def final_path(tree, role, digest):
    return tree.actual(
        BASE
        / "provider-deployment-outbox"
        / ("requests" if role == "request" else "cancelled")
        / (urlsafe_b64decode(digest + "=").hex() + ".json")
    )


def test_independent_wire_and_actual_reader_dependencies_are_accepted(pub_tree):
    request, cancellation = wire_pair()
    assert (
        parse_provider_request(request[1], profile=pub_tree.profile)["schema"]
        == "deployment-request-v2"
    )
    assert (
        parse_provider_cancellation(cancellation[1], profile=pub_tree.profile)[
            "lifecycle_revision"
        ]
        == 2
    )
    context = pub_tree.open()
    try:
        assert context.read_current() == pub_tree.bundle
    finally:
        context.close()
    assert not pub_tree.live


@pytest.mark.parametrize("role", ["request", "cancel"])
def test_exact_actual_publication_and_fsynced_reobservation(pub_tree, role):
    payloads = wire_pair()
    digest = digest_of(payloads)
    context, lease = opened(pub_tree, payloads)
    try:
        assert lease.observe_existing(role=role, request_digest=digest) is None
        attempt = lease.stage(role=role, request_digest=digest)
        observed = lease.commit(attempt)
        raw = dict(payloads)[role]
        assert observed.role == role and observed.request_digest == digest
        assert observed.payload_sha256 == hashlib.sha256(raw).hexdigest()
        assert observed.size_bytes == len(raw)
        assert (
            observed.file_identity.uid,
            observed.file_identity.gid,
            observed.file_identity.mode,
        ) == (20102, 21201, 0o440)
        assert final_path(pub_tree, role, digest).read_bytes() == raw
        assert lease.observe_existing(role=role, request_digest=digest) == observed
        with pytest.raises(c.DeploymentSourceError):
            lease.stage(role=role, request_digest=digest)
        with pytest.raises(c.DeploymentSourceError):
            lease.commit(attempt)
    finally:
        lease.close()
    assert context.read_current() == pub_tree.bundle
    context.close()
    assert not pub_tree.live


@pytest.mark.parametrize("namespace", ["receipts", "consumed"])
@pytest.mark.parametrize("operation", ["factory", "observe", "stage", "commit"])
def test_cross_namespace_change_between_successful_guards_refuses(
    pub_tree, monkeypatch, namespace, operation
):
    payloads = wire_pair()
    digest = digest_of(payloads)
    context = pub_tree.open()
    module = publisher()
    lease = None
    old = pub_tree.payload(namespace, raw=b"opaque-before")

    def replace():
        # Same name/count/bytes, but a new inode and full signature.
        old.rename(old.with_suffix(".saved"))
        pub_tree.payload(namespace, raw=b"opaque-before")
        old.with_suffix(".saved").unlink()

    try:
        if operation == "factory":
            open_dir = f.Directory.open.__func__
            changed = False

            def opening(cls, path, **kwargs):
                nonlocal changed
                result = open_dir(cls, path, **kwargs)
                if path == BASE / "provider-deployment-outbox" and not changed:
                    changed = True
                    replace()
                return result

            monkeypatch.setattr(f.Directory, "open", classmethod(opening))
            with pytest.raises(c.DeploymentSourceError):
                module.open_provider_outbox_lease(
                    context, profile=pub_tree.profile, expected_payloads=payloads
                )
        else:
            lease = module.open_provider_outbox_lease(
                context, profile=pub_tree.profile, expected_payloads=payloads
            )
            if operation == "observe":
                lease.commit(lease.stage(role="request", request_digest=digest))
                original = p._existing_for_policy

                def existing(*args, **kwargs):
                    result = original(*args, **kwargs)
                    replace()
                    return result

                monkeypatch.setattr(p, "_existing_for_policy", existing)
                action = lambda: lease.observe_existing(
                    role="request", request_digest=digest
                )
            elif operation == "stage":
                original = p._stage_payload

                def staging(*args, **kwargs):
                    result = original(*args, **kwargs)
                    replace()
                    return result

                monkeypatch.setattr(p, "_stage_payload", staging)
                action = lambda: lease.stage(role="request", request_digest=digest)
            else:
                attempt = lease.stage(role="request", request_digest=digest)
                original = p._commit_stage

                def committing(*args, **kwargs):
                    original(*args, **kwargs)
                    replace()

                monkeypatch.setattr(p, "_commit_stage", committing)
                action = lambda: lease.commit(attempt)
            with pytest.raises(c.DeploymentSourceError):
                action()
        # Both observations independently are stable and valid; publisher span
        # comparison, rather than mocked context refusal, must detect the change.
        assert context.read_current() == pub_tree.bundle
    finally:
        if lease is not None:
            lease.close()
        context.close()
    assert not pub_tree.live


def test_safe_between_calls_and_all_opaque_payloads_are_untouched(
    pub_tree, monkeypatch
):
    opaque = [
        pub_tree.payload(
            ns, stage=stage, state=state, number=state + 1, raw=b"not canonical JSON"
        )
        for ns in ("requests", "cancelled", "receipts", "consumed")
        for stage, state in ((True, 0), (True, 1), (True, 2))
    ]
    opaque += [
        pub_tree.payload(ns, raw=b"invalid bytes") for ns in ("receipts", "consumed")
    ]
    context, lease = opened(pub_tree)
    digest = digest_of(wire_pair())
    before = {path: (path.stat().st_ino, path.read_bytes()) for path in opaque}
    open_regular = f.open_regular
    forbidden = {str(path) for path in opaque}

    def opening(fd, name, **kwargs):
        assert str(pub_tree.paths[fd] / name) not in forbidden
        return open_regular(fd, name, **kwargs)

    monkeypatch.setattr(f, "open_regular", opening)
    try:
        assert lease.observe_existing(role="request", request_digest=digest) is None
        pub_tree.payload("receipts", number=2, raw=b"still opaque")
        pub_tree.payload("consumed", number=2, raw=b"also opaque")
        attempt = lease.stage(role="request", request_digest=digest)
        pub_tree.payload("receipts", number=3, raw=b"safe between calls")
        lease.commit(attempt)
        assert lease.observe_existing(role="request", request_digest=digest) is not None
        assert {
            path: (path.stat().st_ino, path.read_bytes()) for path in opaque
        } == before
    finally:
        lease.close()
        context.close()


@pytest.mark.parametrize("when", ["between", "during"])
@pytest.mark.parametrize("same", [True, False])
def test_single_no_replace_race_exact_or_different_bytes(
    pub_tree, monkeypatch, when, same
):
    payloads = wire_pair()
    digest = digest_of(payloads)
    context, lease = opened(pub_tree, payloads)
    attempt = lease.stage(role="request", request_digest=digest)
    path = final_path(pub_tree, "request", digest)
    raw = payloads[0][1] if same else b"malformed but metadata safe"
    rename, calls = p._rename_noreplace, []

    def racing(fd, source, target):
        calls.append((source, target))
        if when == "during":
            pub_tree.write(path, raw, 20102, 21201)
        return rename(fd, source, target)

    monkeypatch.setattr(p, "_rename_noreplace", racing)
    if when == "between":
        pub_tree.write(path, raw, 20102, 21201)
    try:
        if same:
            result = lease.commit(attempt)
            assert result.file_identity.inode == path.stat().st_ino
        else:
            with pytest.raises(c.DeploymentSourceError):
                lease.commit(attempt)
        assert path.read_bytes() == raw
        assert len(calls) == (0 if when == "between" and not same else 1)
        assert len(tuple(path.parent.glob(".stage-*.tmp"))) == 1
        assert lease._active is None
        with pytest.raises(c.DeploymentSourceError):
            lease.commit(attempt)
    finally:
        lease.close()
        context.close()


def test_alien_hollow_closed_attempts_and_context_ownership(pub_tree):
    context, lease = opened(pub_tree)
    other = publisher().open_provider_outbox_lease(
        context, profile=pub_tree.profile, expected_payloads=wire_pair()
    )
    digest = digest_of(wire_pair())
    attempt = lease.stage(role="request", request_digest=digest)
    stage_fd = attempt._stage.fd
    try:
        for value in (
            attempt,
            object(),
            object.__new__(publisher().ProviderPublicationAttempt),
        ):
            with pytest.raises(c.DeploymentSourceError):
                other.commit(value)
        assert os.fstat(stage_fd).st_size == len(wire_pair()[0][1])
        with pytest.raises(c.DeploymentSourceError):
            lease.stage(role="cancel", request_digest=digest)
        attempt.close()
        attempt.close()
        assert lease._active is None
        with pytest.raises(OSError):
            os.fstat(stage_fd)
        attempt = lease.stage(role="cancel", request_digest=digest)
        context.close()
        with pytest.raises(c.DeploymentSourceError):
            lease.commit(attempt)
        assert lease._active is None
        for action in (
            lambda: lease.observe_existing(role="request", request_digest=digest),
            lambda: lease.stage(role="request", request_digest=digest),
        ):
            with pytest.raises(c.DeploymentSourceError):
                action()
    finally:
        other.close()
        lease.close()
    assert not pub_tree.live


@pytest.mark.parametrize(
    "mutation", ["leaf", "original", "directory", "mount", "stage", "metadata", "bytes"]
)
def test_actual_source_or_unrelated_stage_replacement_during_effect_refuses(
    pub_tree, monkeypatch, mutation
):
    digest = digest_of(wire_pair())
    other = pub_tree.payload("requests", number=100, stage=True, raw=b"opaque")
    context, lease = opened(pub_tree)
    original = p._stage_payload

    def staging(*args, **kwargs):
        stage = original(*args, **kwargs)
        if mutation in ("leaf", "bytes"):
            target = pub_tree.actual(STATIC / "documents" / "source-context.json")
        elif mutation == "original":
            target = pub_tree.actual(BASE / "extension-topology" / "topology.json")
        else:
            target = other
        if mutation == "directory":
            directory = pub_tree.actual(
                BASE / "provider-deployment-outbox" / "cancelled"
            )
            directory.rename(directory.with_name("saved"))
            pub_tree.directory(
                BASE / "provider-deployment-outbox" / "cancelled", 20102, 21201
            )
        elif mutation == "mount":
            pub_tree.mount_lines[0] = pub_tree.mount_lines[0].replace(
                "/volume-100", "/changed-backing"
            )
        elif mutation == "metadata":
            other.chmod(0o777)
        elif mutation == "bytes":
            target.chmod(0o640)
            target.write_bytes(target.read_bytes().replace(b"context", b"CONTExT", 1))
            target.chmod(0o440)
        else:
            raw = target.read_bytes()
            target.rename(target.with_suffix(".saved"))
            pub_tree.write(
                target,
                raw,
                0 if mutation in ("leaf", "original") else 20102,
                20102 if mutation == "original" else 21201,
            )
            target.with_suffix(".saved").unlink()
        return stage

    monkeypatch.setattr(p, "_stage_payload", staging)
    try:
        with pytest.raises(c.DeploymentSourceError):
            lease.stage(role="request", request_digest=digest)
        assert lease._active is None
    finally:
        lease.close()
        context.close()
    assert not pub_tree.live


@pytest.mark.parametrize(
    "change",
    [
        "list",
        "pair_list",
        "role",
        "bytes",
        "empty",
        "request_size",
        "cancel_size",
        "count",
        "requests17",
        "cancels17",
        "aggregate",
        "reverse",
        "duplicate",
        "id",
        "cancel_only",
        "cancel_id",
        "cancel_context",
        "noncanonical",
        "context",
        "geometry",
        "inventory",
        "slot",
        "platform",
    ],
)
def test_payload_bounds_grammar_and_actual_joins_before_owned_acquisition(
    pub_tree, monkeypatch, change
):
    pairs = wire_pair()
    request, cancel = json.loads(pairs[0][1]), json.loads(pairs[1][1])
    variants = {
        "list": list(pairs),
        "pair_list": (list(pairs[0]),),
        "role": (("receipt", b"x"),),
        "bytes": (("request", bytearray(b"x")),),
        "empty": (("request", b""),),
        "request_size": (("request", b"x" * 65537),),
        "cancel_size": (("cancel", b"x" * 8193),),
        "count": pairs * 17,
        "requests17": (pairs[0],) * 17,
        "cancels17": (pairs[1],) * 17,
        "aggregate": (("request", b"x" * 65536),) * 16
        + (("cancel", b"x" * 8192),) * 15
        + (("cancel", b"x" * 8193),),
        "reverse": tuple(reversed(pairs)),
        "duplicate": (pairs[0], pairs[0]),
        "cancel_only": (pairs[1],),
        "noncanonical": (("request", pairs[0][1] + b"\n"),),
    }
    if change in variants:
        payloads = variants[change]
    elif change.startswith("cancel_"):
        cancel["request_id" if change == "cancel_id" else "source_context_sha256"] = (
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
            if change == "cancel_id"
            else "f" * 64
        )
        payloads = (pairs[0], ("cancel", canonical_json(cancel)))
    else:
        effect = request["effect_payload"]
        if change == "context":
            effect["source_context"]["sha256"] = "f" * 64
        elif change == "geometry":
            effect["geometry"]["sha256"] = "e" * 64
        elif change == "inventory":
            effect["preserved_inventory"]["topology_sha256"] = "d" * 64
            effect["preserved_inventory_sha256"] = hashlib.sha256(
                canonical_json(effect["preserved_inventory"])
            ).hexdigest()
        elif change == "slot":
            effect["new_service_effect"]["service_identity"] = (
                "extension-" + "1" * 32 + "-xs02"
            )
        elif change == "platform":
            effect["selected_platform_entry"]["platform"] = "linux/arm64"
        elif change == "id":
            request["created_at"] = "2023-11-14T22:13:21.000Z"
            request["expires_at"] = "2023-11-14T23:13:21.000Z"
        raw = signed(request)
        payloads = (("request", raw),)
        if change == "id":
            payloads = tuple(
                sorted(
                    (pairs[0], ("request", raw)),
                    key=lambda pair: urlsafe_b64decode(
                        json.loads(pair[1])["request_digest"] + "="
                    ),
                )
            )
    context = pub_tree.open()
    baseline = set(pub_tree.live)
    calls = []
    open_dir = f.Directory.open.__func__

    def opening(cls, path, **kwargs):
        calls.append(path)
        return open_dir(cls, path, **kwargs)

    monkeypatch.setattr(f.Directory, "open", classmethod(opening))
    try:
        with pytest.raises(c.DeploymentSourceError):
            publisher().open_provider_outbox_lease(
                context, profile=pub_tree.profile, expected_payloads=payloads
            )
        assert not calls
        assert pub_tree.live == baseline
    finally:
        context.close()


@pytest.mark.parametrize(
    "occupied",
    ["unknown", "malformed", "wrong_bytes", "symlink", "hardlink", "mode", "size"],
)
def test_bad_occupied_final_is_never_adopted_or_deleted(pub_tree, occupied):
    payloads = wire_pair()
    digest = digest_of(payloads)
    target = final_path(pub_tree, "request", digest)
    if occupied == "unknown":
        target = target.with_name("f" * 64 + ".json")
    raw = b"wrong" if occupied in ("malformed", "wrong_bytes") else payloads[0][1]
    if occupied == "size":
        raw = b"x" * 65537
    pub_tree.write(target, raw, 20102, 21201)
    if occupied == "mode":
        target.chmod(0o640)
    elif occupied in ("symlink", "hardlink"):
        source = target.with_name("external")
        target.rename(source)
        if occupied == "symlink":
            target.symlink_to(source)
        else:
            os.link(source, target)
    # Metadata-invalid finals may already be refused by the actual context.
    context = None
    try:
        with pytest.raises(c.DeploymentSourceError):
            context = pub_tree.open()
            publisher().open_provider_outbox_lease(
                context, profile=pub_tree.profile, expected_payloads=payloads
            )
        assert target.read_bytes() == raw
    finally:
        if context is not None:
            context.close()


def test_empty_tuple_and_exhausted_stage_budget(pub_tree):
    context, lease = opened(pub_tree, ())
    try:
        with pytest.raises(c.DeploymentSourceError):
            lease.stage(role="request", request_digest=digest_of(wire_pair()))
    finally:
        lease.close()
        context.close()
    for number in range(1, 33):
        pub_tree.payload("requests", number=number, stage=True)
    context, lease = opened(pub_tree)
    try:
        with pytest.raises(c.DeploymentSourceError):
            lease.stage(role="request", request_digest=digest_of(wire_pair()))
        assert (
            len(
                tuple(
                    pub_tree.actual(
                        BASE / "provider-deployment-outbox" / "requests"
                    ).iterdir()
                )
            )
            == 32
        )
    finally:
        lease.close()
        context.close()


def many_pairs():
    pairs = wire_pair(capacity=16)
    requests, cancellations = [], []
    for number in range(1, 17):
        request = json.loads(pairs[0][1])
        request["request_id"] = f"{number:08d}-1000-4000-8000-{number:012d}"
        raw = signed(request)
        request = json.loads(raw)
        cancel = json.loads(pairs[1][1])
        cancel["request_id"], cancel["request_digest"] = (
            request["request_id"],
            request["request_digest"],
        )
        requests.append(("request", raw))
        cancellations.append(("cancel", canonical_json(cancel)))
    key = lambda pair: urlsafe_b64decode(json.loads(pair[1])["request_digest"] + "=")
    return tuple(sorted(requests, key=key) + sorted(cancellations, key=key))


def test_sixteen_request_and_cancellation_finals_with_maximum_aggregate_inventory(
    tmp_path, monkeypatch
):
    tree = publication_tree(tmp_path, monkeypatch, capacity=16)
    pairs = many_pairs()
    assert len(pairs) == 32
    for role, raw in pairs:
        tree.write(
            final_path(tree, role, json.loads(raw)["request_digest"]), raw, 20102, 21201
        )
    # 48+48+96+48 = 240; all opaque stages and incoming bytes remain unparsed.
    for namespace in ("requests", "cancelled", "receipts", "consumed"):
        for number in range(1, 33):
            tree.payload(namespace, number=number, stage=True)
    for namespace, count in (("receipts", 64), ("consumed", 16)):
        for number in range(1, count + 1):
            tree.payload(namespace, number=number)
    context, lease = opened(tree, pairs)
    try:
        for role in ("request", "cancel"):
            observation = lease.observe_existing(
                role=role, request_digest=digest_of(pairs)
            )
            assert observation.role == role
        tree.payload("consumed", number=17)
        with pytest.raises(c.DeploymentSourceError):
            lease.observe_existing(role="request", request_digest=digest_of(pairs))
    finally:
        lease.close()
        context.close()
    assert not tree.live


@pytest.mark.parametrize(
    "change",
    [
        "valid",
        "selected_slot",
        "extension_present",
        "service",
        "topology_id",
        "profile",
        "slot_range",
    ],
)
def test_preserved_inventory_matches_actual_original_slots(
    tmp_path, monkeypatch, change
):
    capacity = 1 if change == "slot_range" else 16
    tree = publication_tree(tmp_path, monkeypatch, capacity=capacity)
    raw = wire_pair(capacity=capacity)[0][1]
    request = json.loads(raw)
    effect = request["effect_payload"]
    entry = _inventory_entry(
        _inputs(capacity=16)[0]["source_bundle_files"], 2, "previous-extension"
    )
    if change == "selected_slot":
        entry = _inventory_entry(tree.bundle, 1, "previous-extension")
    elif change == "extension_present":
        entry = _inventory_entry(tree.bundle, 2, "synthetic-provider")
    elif change == "service":
        entry["service_identity"] = json.loads(tree.bundle[9][1])["slots"][2][
            "service_identity"
        ]
    inventory = effect["preserved_inventory"]
    inventory["installations"] = [entry]
    if change == "topology_id":
        inventory["topology_id"] = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    elif change == "profile":
        inventory["origin_profile_digest"] = "f" * 64
    effect["preserved_inventory_sha256"] = hashlib.sha256(
        canonical_json(inventory)
    ).hexdigest()
    payloads = (("request", signed(request)),)
    context = tree.open()
    try:
        if change == "valid":
            lease = publisher().open_provider_outbox_lease(
                context, profile=tree.profile, expected_payloads=payloads
            )
            lease.close()
        else:
            with pytest.raises(c.DeploymentSourceError):
                publisher().open_provider_outbox_lease(
                    context, profile=tree.profile, expected_payloads=payloads
                )
    finally:
        context.close()
    assert not tree.live


@pytest.mark.parametrize(
    "kind",
    [
        "hollow_profile",
        "wrong_profile",
        "context_subclass",
        "hollow_context",
        "closed_context",
        "tuple_subclass",
        "role_subclass",
        "bytes_subclass",
        "native",
    ],
)
def test_exact_factory_inputs_and_native_gate_fail_before_extra_acquisition(
    pub_tree, monkeypatch, kind
):
    module = publisher()
    context = pub_tree.open()
    profile, payloads, supplied_context = pub_tree.profile, wire_pair(), context
    if kind == "hollow_profile":
        profile = object.__new__(OriginProfile)
    elif kind == "wrong_profile":
        profile = OriginProfile.local(instance_id="2" * 32, path_id="2" * 32, port=8080)
        payloads = ()
    elif kind == "context_subclass":
        supplied_context = object.__new__(type("Subclass", (type(context),), {}))
    elif kind == "hollow_context":
        supplied_context = object.__new__(type(context))
    elif kind == "closed_context":
        context.close()
    elif kind == "tuple_subclass":
        payloads = type("Tuple", (tuple,), {})(payloads)
    elif kind == "role_subclass":
        payloads = ((type("Role", (str,), {})("request"), payloads[0][1]),)
    elif kind == "bytes_subclass":
        payloads = (("request", type("Raw", (bytes,), {})(payloads[0][1])),)
    else:
        monkeypatch.setattr(
            module.m,
            "native_platform",
            lambda: (_ for _ in ()).throw(c.DeploymentSourceUnavailable()),
        )
    baseline = set(pub_tree.live)
    try:
        with pytest.raises(c.DeploymentSourceError):
            module.open_provider_outbox_lease(
                supplied_context, profile=profile, expected_payloads=payloads
            )
        assert pub_tree.live == baseline
    finally:
        context.close()


def test_fresh_import_and_unused_factory_have_no_external_effects():
    script = """
import os, pathlib, socket, sqlite3
import app.deployment.provider_sources
import app.deployment.provider_prepare_contracts
def forbidden(*args, **kwargs):
    raise AssertionError("unexpected external effect")
for name in ("open", "write", "fsync", "rename", "unlink", "fchown", "fchmod"):
    setattr(os, name, forbidden)
pathlib.Path.read_bytes = forbidden
socket.socket = forbidden
sqlite3.connect = forbidden
import app.deployment.provider_publication as module
assert callable(module.open_provider_outbox_lease)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("replacement", [False, True])
def test_eexist_target_mutation_after_exact_read_before_closing_guard_refuses(
    pub_tree, monkeypatch, replacement
):
    payloads = wire_pair()
    digest = digest_of(payloads)
    context, lease = opened(pub_tree, payloads)
    attempt = lease.stage(role="request", request_digest=digest)
    path = final_path(pub_tree, "request", digest)
    rename, existing = p._rename_noreplace, p._existing_for_policy

    def raced(fd, source, target):
        pub_tree.write(path, payloads[0][1], 20102, 21201)
        return rename(fd, source, target)

    def read_then_changed(*args, **kwargs):
        result = existing(*args, **kwargs)
        if replacement:
            path.rename(path.with_suffix(".saved"))
        pub_tree.write(path, b"different bytes", 20102, 21201)
        if replacement:
            path.with_suffix(".saved").unlink()
        return result

    monkeypatch.setattr(p, "_rename_noreplace", raced)
    monkeypatch.setattr(p, "_existing_for_policy", read_then_changed)
    try:
        with pytest.raises(c.DeploymentSourceError):
            lease.commit(attempt)
        assert lease._active is None
        assert path.read_bytes() == b"different bytes"
    finally:
        lease.close()
        context.close()


def test_absent_observation_cannot_return_before_closing_snapshot(
    pub_tree, monkeypatch
):
    context, lease = opened(pub_tree)
    original = f.Directory.recheck_current
    calls = 0

    def checked(directory):
        nonlocal calls
        result = original(directory)
        if directory is lease._directories[0]:
            calls += 1
            if calls == 2:
                pub_tree.payload("receipts", raw=b"opaque during absent observation")
        return result

    monkeypatch.setattr(f.Directory, "recheck_current", checked)
    try:
        with pytest.raises(c.DeploymentSourceError):
            lease.observe_existing(
                role="request", request_digest=digest_of(wire_pair())
            )
        assert calls == 2
    finally:
        lease.close()
        context.close()


@pytest.mark.parametrize("ordinary", [False, True])
def test_failed_commit_consumes_attempt_without_retry_and_keeps_lease_closable(
    pub_tree, monkeypatch, ordinary
):
    context, lease = opened(pub_tree)
    digest = digest_of(wire_pair())
    attempt = lease.stage(role="request", request_digest=digest)
    primary = (
        OSError("private syscall detail") if ordinary else c.DeploymentSourceError()
    )
    calls = []

    def fail(*args):
        calls.append(args)
        raise primary

    monkeypatch.setattr(p, "_rename_noreplace", fail)
    try:
        with pytest.raises(c.DeploymentSourceError) as caught:
            lease.commit(attempt)
        assert type(caught.value) is (
            c.PublicationUnavailable if ordinary else c.DeploymentSourceError
        )
        assert "private" not in str(caught.value)
        assert len(calls) == 1 and lease._active is None
        assert not lease._closed
        with pytest.raises(c.DeploymentSourceError):
            lease.commit(attempt)
        assert len(calls) == 1
        assert len(tuple(final_path(pub_tree, "request", digest).parent.iterdir())) == 1
    finally:
        lease.close()
        context.close()
