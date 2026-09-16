"""Actual retained public-source files with controlled ownership/mount observations."""

import hashlib
import json
import os
from base64 import urlsafe_b64decode, urlsafe_b64encode
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.domain.refs import canonical_json
from app.operations.setup import OriginProfile
from app.tests.deployment_source_fixture import ROOT, inputs, module, profile


def _b64(raw):
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def trust_bytes(origin):
    return canonical_json(
        {
            "schema": "deployment-public-trust-set-v1",
            "domain": "deeptwin-deployment-public-trust-set-v1",
            "version": 1,
            "instance_id": origin.instance_id,
            "origin_profile_digest": _b64(bytes.fromhex(origin.digest)),
            "keys": [
                {
                    "key_id": "33333333-3333-4333-8333-333333333333",
                    "algorithm": "ed25519",
                    "public_key": _b64(b"p" * 32),
                    "trust_class": "instance_operator",
                    "adapter_ids": ["deeptwin-stage-operator-v1"],
                }
            ],
            "adapters": [
                {
                    "operator_adapter": "deeptwin-stage-operator-v1",
                    "operator_version": "1.0.0",
                    "deployment_profile_id": origin.deployment_profile_id,
                }
            ],
        }
    )


def consumed_marker(receipt_digest=None, *, outcome="failed"):
    receipt_digest = receipt_digest or _b64(b"r" * 32)
    return canonical_json(
        {
            "schema": "deployment-consumption-v1",
            "domain": "deeptwin-deployment-consumption-v1",
            "consumption_id": "66666666-6666-4666-8666-666666666666",
            "request_id": "77777777-7777-4777-8777-777777777777",
            "request_digest": _b64(b"q" * 32),
            "receipt_digest": receipt_digest,
            "winning_lifecycle_revision": 2,
            "consumed_at": "2026-09-16T00:00:00.000Z",
            "outcome": outcome,
        }
    )


def _public_receipt_case(name="valid_succeeded_present"):
    fixture = json.loads(
        (ROOT / "app/tests/fixtures/deployment-receipt-ed25519-v1.json").read_bytes()
    )
    return next(case for case in fixture["cases"] if case["name"] == name)


class ActualReceiptIngress:
    ingress_root = Path("/run/deeptwin/deployment-receipt-ingress")
    incoming_root = Path("/run/deeptwin/deployment-receipts")
    receipts_root = incoming_root / "receipts"

    def __init__(self, tmp_path, monkeypatch, *, case_name="valid_succeeded_present"):
        self.c, self.f, self.m = module("contracts"), module("files"), module("mounts")
        case = _public_receipt_case(case_name)
        self.profile = OriginProfile.from_dict(case["profile"])
        self.receipt_bytes = case["receipt_utf8"].encode("utf-8")
        self.trust_bytes = case["trust_utf8"].encode("utf-8")
        prepare_inputs = inputs(
            identity=self.profile.instance_id,
            portable=self.profile.deployment_profile_id == "portable-compose-v1",
        )
        receipt_instance = canonical_json(
            {
                "schema_version": "deployment-receipt-instance-v1",
                "prepare_instance_sha256": hashlib.sha256(
                    prepare_inputs[3]
                ).hexdigest(),
                "trust_set_sha256": hashlib.sha256(self.trust_bytes).hexdigest(),
                "receipt_ingress_id": "44444444-4444-4444-8444-444444444444",
                "consumption_exchange_id": "55555555-5555-4555-8555-555555555555",
            }
        )
        source_contracts = module("receipt_source_contracts")
        rendered = module("receipt_render").render_receipt_sources(
            *prepare_inputs,
            source_contracts.RECEIPT_RECIPE_BYTES,
            receipt_instance,
            self.trust_bytes,
        )
        self.ingress_bytes = rendered.ingress_bytes
        self.pins = json.loads(rendered.pins_bytes)
        self.receipt_digest_hex = hashlib.sha256(self.receipt_bytes).hexdigest()
        self.receipt_digest = _b64(bytes.fromhex(self.receipt_digest_hex))
        self.base = tmp_path
        self.metadata = {}
        self.original_stat, self.original_fstat = os.stat, os.fstat
        self.original_open_directory = self.f.open_directory
        device = self.original_stat(tmp_path).st_dev
        self.device = f"{os.major(device)}:{os.minor(device)}"
        roots = [
            (self.ingress_root, 0, 21201, True),
            (self.incoming_root, 20113, 21201, True),
            *((path, 20102, 20102, False) for path in self.c.BUILTIN_ROOTS),
        ]
        self.mount_lines = []
        for index, (logical, uid, gid, read_only) in enumerate(roots, 1):
            actual = self.actual(logical)
            actual.mkdir(parents=True, exist_ok=True)
            actual.chmod(0o750)
            self.register(actual, uid, gid)
            self.mount_lines.append(
                f"{index} 999 {self.device} /vol{index} {logical} "
                f"{'ro' if read_only else 'rw'} - ext4 /dev/fake rw\n"
            )
        self.ingress_path = self.actual(self.ingress_root) / "ingress.json"
        self.ingress_path.write_bytes(self.ingress_bytes)
        self.ingress_path.chmod(0o440)
        self.register(self.ingress_path, 0, 21201)
        self.receipts_path = self.actual(self.receipts_root)
        self.receipts_path.mkdir(mode=0o750)
        self.register(self.receipts_path, 20113, 21201)

        def observed(info):
            uid, gid = self.metadata.get(
                (info.st_dev, info.st_ino), (info.st_uid, info.st_gid)
            )
            values = {
                field: getattr(info, field)
                for field in dir(info)
                if field.startswith("st_")
            }
            return SimpleNamespace(**(values | {"st_uid": uid, "st_gid": gid}))

        monkeypatch.setattr(os, "fstat", lambda fd: observed(self.original_fstat(fd)))
        monkeypatch.setattr(
            os,
            "stat",
            lambda *args, **kwargs: observed(self.original_stat(*args, **kwargs)),
        )
        monkeypatch.setattr(
            self.f,
            "open_directory",
            lambda path, **kwargs: self.original_open_directory(
                self.actual(path), **kwargs
            ),
        )
        monkeypatch.setattr(self.m, "native_platform", lambda: "linux/amd64")
        monkeypatch.setattr(
            self.m,
            "read_mountinfo",
            lambda: self.m.parse_mountinfo("".join(self.mount_lines).encode()),
        )

    def actual(self, path):
        return self.base.joinpath(*Path(path).parts[1:])

    def register(self, path, uid, gid):
        info = self.original_stat(path, follow_symlinks=False)
        self.metadata[(info.st_dev, info.st_ino)] = uid, gid

    def open(
        self,
        *,
        profile_value=None,
        recipe_pin=None,
        instance_pin=None,
        ingress_pin=None,
        protected_roots=(),
    ):
        return module("receipt_sources").open_receipt_ingress_source(
            profile=self.profile if profile_value is None else profile_value,
            receipt_recipe_sha256=(
                self.pins["receipt_recipe_sha256"] if recipe_pin is None else recipe_pin
            ),
            receipt_instance_sha256=(
                self.pins["receipt_instance_sha256"]
                if instance_pin is None
                else instance_pin
            ),
            ingress_sha256=(
                self.pins["ingress_sha256"] if ingress_pin is None else ingress_pin
            ),
            protected_roots=protected_roots,
        )

    def add_final(self, payload=None, *, digest_hex=None):
        payload = self.receipt_bytes if payload is None else payload
        digest_hex = (
            hashlib.sha256(payload).hexdigest() if digest_hex is None else digest_hex
        )
        path = self.receipts_path / f"{digest_hex}.json"
        path.write_bytes(payload)
        path.chmod(0o440)
        self.register(path, 20113, 21201)
        return path

    def add_stage(self, number, payload=b""):
        path = self.receipts_path / f".stage-{UUID(int=number + 1)}.tmp"
        path.write_bytes(payload)
        path.chmod(0o600)
        self.register(path, 20113, 20113)
        return path

    def replace_ingress(self, payload=None):
        old = self.ingress_path.with_name("old-ingress")
        self.ingress_path.rename(old)
        self.ingress_path.write_bytes(
            self.ingress_bytes if payload is None else payload
        )
        self.ingress_path.chmod(0o440)
        self.register(self.ingress_path, 0, 21201)
        return old


@pytest.fixture
def actual_receipt_ingress(tmp_path, monkeypatch):
    return ActualReceiptIngress(tmp_path, monkeypatch)


@pytest.fixture
def actual_portable_receipt_ingress(tmp_path, monkeypatch):
    return ActualReceiptIngress(tmp_path, monkeypatch, case_name="valid_failed_absent")


class ActualPublicTrust:
    public_root = "/run/deeptwin/deployment-verify-public"

    def __init__(self, tmp_path, monkeypatch):
        self.c, self.f, self.m = module("contracts"), module("files"), module("mounts")
        self.profile = profile()
        prepare_inputs = inputs()
        candidate = trust_bytes(self.profile)
        receipt_instance = canonical_json(
            {
                "schema_version": "deployment-receipt-instance-v1",
                "prepare_instance_sha256": hashlib.sha256(
                    prepare_inputs[3]
                ).hexdigest(),
                "trust_set_sha256": hashlib.sha256(candidate).hexdigest(),
                "receipt_ingress_id": "44444444-4444-4444-8444-444444444444",
                "consumption_exchange_id": "55555555-5555-4555-8555-555555555555",
            }
        )
        source_contracts = module("receipt_source_contracts")
        rendered = module("receipt_render").render_receipt_sources(
            *prepare_inputs,
            source_contracts.RECEIPT_RECIPE_BYTES,
            receipt_instance,
            candidate,
        )
        self.trust_bytes = rendered.trust_bytes
        self.trust_sha256 = hashlib.sha256(self.trust_bytes).hexdigest()
        self.base = tmp_path
        self.metadata = {}
        self.original_stat, self.original_fstat = os.stat, os.fstat
        self.original_open_directory = self.f.open_directory
        device = self.original_stat(tmp_path).st_dev
        self.device = f"{os.major(device)}:{os.minor(device)}"
        roots = [(self.public_root, 0, 20102, True)] + [
            (str(path), 20102, 20102, False) for path in self.c.BUILTIN_ROOTS
        ]
        self.mount_lines = []
        for index, (logical, uid, gid, read_only) in enumerate(roots, 1):
            actual = self.actual(logical)
            actual.mkdir(parents=True, exist_ok=True)
            actual.chmod(0o750)
            self.register(actual, uid, gid)
            self.mount_lines.append(
                f"{index} 999 {self.device} /vol{index} {logical} "
                f"{'ro' if read_only else 'rw'} - ext4 /dev/fake rw\n"
            )
        self.trust_path = self.actual(self.public_root) / "trust-set.json"
        self.trust_path.write_bytes(self.trust_bytes)
        self.trust_path.chmod(0o440)
        self.register(self.trust_path, 0, 20102)

        def observed(info):
            uid, gid = self.metadata.get(
                (info.st_dev, info.st_ino), (info.st_uid, info.st_gid)
            )
            values = {
                name: getattr(info, name)
                for name in dir(info)
                if name.startswith("st_")
            }
            return SimpleNamespace(**(values | {"st_uid": uid, "st_gid": gid}))

        monkeypatch.setattr(os, "fstat", lambda fd: observed(self.original_fstat(fd)))
        monkeypatch.setattr(
            os,
            "stat",
            lambda *args, **kwargs: observed(self.original_stat(*args, **kwargs)),
        )
        monkeypatch.setattr(
            self.f,
            "open_directory",
            lambda path, **kwargs: self.original_open_directory(
                self.actual(path), **kwargs
            ),
        )
        monkeypatch.setattr(self.m, "native_platform", lambda: "linux/amd64")
        monkeypatch.setattr(
            self.m,
            "read_mountinfo",
            lambda: self.m.parse_mountinfo("".join(self.mount_lines).encode()),
        )

    def actual(self, path):
        return self.base.joinpath(*str(path).split("/")[1:])

    def register(self, path, uid, gid):
        info = self.original_stat(path, follow_symlinks=False)
        self.metadata[(info.st_dev, info.st_ino)] = uid, gid

    def open(self, *, profile_value=None, pin=None, protected_roots=()):
        return module("receipt_sources").open_public_trust_source(
            profile=self.profile if profile_value is None else profile_value,
            trust_sha256=self.trust_sha256 if pin is None else pin,
            protected_roots=protected_roots,
        )

    def replace_file(self, payload=None):
        old = self.trust_path.with_name("old-trust")
        self.trust_path.rename(old)
        self.trust_path.write_bytes(self.trust_bytes if payload is None else payload)
        self.trust_path.chmod(0o440)
        self.register(self.trust_path, 0, 20102)
        return old


@pytest.fixture
def actual_public_trust(tmp_path, monkeypatch):
    return ActualPublicTrust(tmp_path, monkeypatch)


class ActualConsumptionExchange:
    exchange_root = Path("/run/deeptwin/deployment-consumption-exchange")
    consumed_root = Path("/run/deeptwin/deployment-consumed")
    namespace_root = consumed_root / "consumed"

    def __init__(self, tmp_path, monkeypatch):
        self.c, self.f, self.m = module("contracts"), module("files"), module("mounts")
        self.profile = profile()
        prepare_inputs = inputs()
        candidate_trust = trust_bytes(self.profile)
        receipt_instance = canonical_json(
            {
                "schema_version": "deployment-receipt-instance-v1",
                "prepare_instance_sha256": hashlib.sha256(
                    prepare_inputs[3]
                ).hexdigest(),
                "trust_set_sha256": hashlib.sha256(candidate_trust).hexdigest(),
                "receipt_ingress_id": "44444444-4444-4444-8444-444444444444",
                "consumption_exchange_id": "55555555-5555-4555-8555-555555555555",
            }
        )
        source_contracts = module("receipt_source_contracts")
        rendered = module("receipt_render").render_receipt_sources(
            *prepare_inputs,
            source_contracts.RECEIPT_RECIPE_BYTES,
            receipt_instance,
            candidate_trust,
        )
        self.consumption_exchange_bytes = rendered.consumption_exchange_bytes
        self.pins = json.loads(rendered.pins_bytes)
        self.base = tmp_path
        self.metadata = {}
        self.original_stat, self.original_fstat = os.stat, os.fstat
        self.original_open_directory = self.f.open_directory
        device = self.original_stat(tmp_path).st_dev
        self.device = f"{os.major(device)}:{os.minor(device)}"
        roots = [
            (self.exchange_root, 0, 21201, True),
            (self.consumed_root, 20102, 21201, False),
            *((path, 20102, 20102, False) for path in self.c.BUILTIN_ROOTS),
        ]
        self.mount_lines = []
        for index, (logical, uid, gid, read_only) in enumerate(roots, 1):
            actual = self.actual(logical)
            actual.mkdir(parents=True, exist_ok=True)
            actual.chmod(0o750)
            self.register(actual, uid, gid)
            self.mount_lines.append(
                f"{index} 999 {self.device} /vol{index} {logical} "
                f"{'ro' if read_only else 'rw'} - ext4 /dev/fake rw\n"
            )
        self.exchange_path = (
            self.actual(self.exchange_root) / "consumption-exchange.json"
        )
        self.exchange_path.write_bytes(self.consumption_exchange_bytes)
        self.exchange_path.chmod(0o440)
        self.register(self.exchange_path, 0, 21201)
        self.consumed_path = self.actual(self.namespace_root)
        self.consumed_path.mkdir(mode=0o750)
        self.register(self.consumed_path, 20102, 21201)

        def observed(info):
            uid, gid = self.metadata.get(
                (info.st_dev, info.st_ino), (info.st_uid, info.st_gid)
            )
            values = {
                field: getattr(info, field)
                for field in dir(info)
                if field.startswith("st_")
            }
            return SimpleNamespace(**(values | {"st_uid": uid, "st_gid": gid}))

        monkeypatch.setattr(os, "fstat", lambda fd: observed(self.original_fstat(fd)))
        monkeypatch.setattr(
            os,
            "stat",
            lambda *args, **kwargs: observed(self.original_stat(*args, **kwargs)),
        )

        def chown(fd, uid, gid):
            info = self.original_fstat(fd)
            old_uid, old_gid = self.metadata.get(
                (info.st_dev, info.st_ino), (20102, 20102)
            )
            self.metadata[(info.st_dev, info.st_ino)] = (
                old_uid if uid == -1 else uid,
                old_gid if gid == -1 else gid,
            )

        monkeypatch.setattr(os, "fchown", chown)
        monkeypatch.setattr(
            self.f,
            "open_directory",
            lambda path, **kwargs: self.original_open_directory(
                self.actual(path), **kwargs
            ),
        )
        monkeypatch.setattr(self.m, "native_platform", lambda: "linux/amd64")
        monkeypatch.setattr(
            self.m,
            "read_mountinfo",
            lambda: self.m.parse_mountinfo("".join(self.mount_lines).encode()),
        )

    def actual(self, path):
        return self.base.joinpath(*Path(path).parts[1:])

    def register(self, path, uid, gid):
        info = self.original_stat(path, follow_symlinks=False)
        self.metadata[(info.st_dev, info.st_ino)] = uid, gid

    def open(
        self,
        *,
        profile_value=None,
        recipe_pin=None,
        instance_pin=None,
        exchange_pin=None,
        protected_roots=(),
    ):
        return module("receipt_sources").open_consumption_exchange_source(
            profile=self.profile if profile_value is None else profile_value,
            receipt_recipe_sha256=(
                self.pins["receipt_recipe_sha256"] if recipe_pin is None else recipe_pin
            ),
            receipt_instance_sha256=(
                self.pins["receipt_instance_sha256"]
                if instance_pin is None
                else instance_pin
            ),
            consumption_exchange_sha256=(
                self.pins["consumption_exchange_sha256"]
                if exchange_pin is None
                else exchange_pin
            ),
            protected_roots=protected_roots,
        )

    def add_final(self, payload, *, receipt_digest=None):
        receipt_digest = receipt_digest or json.loads(payload)["receipt_digest"]
        name = urlsafe_b64decode(receipt_digest + "=").hex() + ".json"
        path = self.consumed_path / name
        path.write_bytes(payload)
        path.chmod(0o440)
        self.register(path, 20102, 21201)
        return path

    def add_stage(self, number, payload=b""):
        path = self.consumed_path / f".stage-{UUID(int=number + 1)}.tmp"
        path.write_bytes(payload)
        path.chmod(0o600)
        self.register(path, 20102, 20102)
        return path

    def replace_exchange(self, payload=None):
        old = self.exchange_path.with_name("old-consumption-exchange")
        self.exchange_path.rename(old)
        self.exchange_path.write_bytes(
            self.consumption_exchange_bytes if payload is None else payload
        )
        self.exchange_path.chmod(0o440)
        self.register(self.exchange_path, 0, 21201)
        return old


@pytest.fixture
def actual_consumption_exchange(tmp_path, monkeypatch):
    return ActualConsumptionExchange(tmp_path, monkeypatch)


class ActualReceiptPublicInit:
    """Fixed public-init roots backed only by real temporary files and descriptors."""

    input_root = Path("/run/deeptwin/receipt-init-input")
    target_specs = (
        (Path("/run/deeptwin/deployment-verify-public"), 0, 20102),
        (Path("/run/deeptwin/deployment-receipt-ingress"), 0, 21201),
        (Path("/run/deeptwin/deployment-consumption-exchange"), 0, 21201),
        (Path("/run/deeptwin/deployment-receipts"), 20113, 21201),
        (Path("/run/deeptwin/deployment-consumed"), 20102, 21201),
    )

    def __init__(self, tmp_path, monkeypatch):
        self.c, self.f, self.m = module("contracts"), module("files"), module("mounts")
        self.base = tmp_path
        self.metadata = {}
        self.original_stat, self.original_fstat = os.stat, os.fstat
        self.original_open_directory = self.f.open_directory
        self.base.chmod(0o755)
        self.register(self.base, 0, 0)
        device = self.original_stat(tmp_path).st_dev
        self.device = f"{os.major(device)}:{os.minor(device)}"

        case = _public_receipt_case()
        self.profile = OriginProfile.from_dict(case["profile"])
        self.receipt_bytes = case["receipt_utf8"].encode("utf-8")
        self.trust_bytes = case["trust_utf8"].encode("utf-8")
        self.prepare_inputs = inputs(identity=self.profile.instance_id)
        self.receipt_instance_bytes = canonical_json(
            {
                "schema_version": "deployment-receipt-instance-v1",
                "prepare_instance_sha256": hashlib.sha256(
                    self.prepare_inputs[3]
                ).hexdigest(),
                "trust_set_sha256": hashlib.sha256(self.trust_bytes).hexdigest(),
                "receipt_ingress_id": "44444444-4444-4444-8444-444444444444",
                "consumption_exchange_id": "55555555-5555-4555-8555-555555555555",
            }
        )
        source_contracts = module("receipt_source_contracts")
        self.receipt_recipe_bytes = source_contracts.RECEIPT_RECIPE_BYTES
        self.output = module("receipt_render").render_receipt_sources(
            *self.prepare_inputs,
            self.receipt_recipe_bytes,
            self.receipt_instance_bytes,
            self.trust_bytes,
        )
        self.pins = json.loads(self.output.pins_bytes)

        for logical in (
            Path("/opt"),
            self.c.RELEASE_ROOT,
            self.c.RELEASE_ROOT / "deploy",
            self.c.RELEASE_ROOT / "deploy/security",
            Path("/run"),
            Path("/run/deeptwin"),
            self.input_root,
        ):
            actual = self.actual(logical)
            actual.mkdir(parents=True, exist_ok=True)
            actual.chmod(0o750 if logical == self.input_root else 0o755)
            self.register(actual, 0, 0)

        release_files = (
            ("deploy/compose.yaml", self.prepare_inputs[0]),
            ("deploy/security/service-ids.json", self.prepare_inputs[1]),
            (
                "deploy/security/deployment-prepare-recipe-v1.json",
                self.prepare_inputs[2],
            ),
            (
                "deploy/security/deployment-receipt-recipe-v1.json",
                self.receipt_recipe_bytes,
            ),
        )
        for relative, raw in release_files:
            path = self.actual(self.c.RELEASE_ROOT / relative)
            path.write_bytes(raw)
            path.chmod(0o644)
            self.register(path, 0, 0)

        input_files = (
            ("prepare-instance.json", self.prepare_inputs[3]),
            ("receipt-instance.json", self.receipt_instance_bytes),
            ("trust-set.json", self.trust_bytes),
            ("receipt-source-pins.json", self.output.pins_bytes),
        )
        for name, raw in input_files:
            path = self.actual(self.input_root / name)
            path.write_bytes(raw)
            path.chmod(0o440)
            self.register(path, 0, 0)

        for logical, _uid, _gid in self.target_specs:
            actual = self.actual(logical)
            actual.mkdir(parents=True, exist_ok=True)
            actual.chmod(0o755)
            self.register(actual, 0, 0)

        self.mount_lines = [
            f"100 1 {self.device} /release {self.c.RELEASE_ROOT} ro - overlay overlay rw\n",
            f"101 1 {self.device} /input {self.input_root} ro - tmpfs tmpfs rw\n",
        ]
        for index, (name, _raw) in enumerate(input_files, 110):
            self.mount_lines.append(
                f"{index} 101 {self.device} /config-{index} "
                f"{self.input_root / name} ro - tmpfs tmpfs rw\n"
            )
        for index, (logical, _uid, _gid) in enumerate(self.target_specs, 200):
            self.mount_lines.append(
                f"{index} 1 {self.device} /target-{index} {logical} "
                "rw - ext4 /dev/fake rw\n"
            )

        def observed(info):
            uid, gid = self.metadata.get(
                (info.st_dev, info.st_ino), (info.st_uid, info.st_gid)
            )
            values = {
                field: getattr(info, field)
                for field in dir(info)
                if field.startswith("st_")
            }
            return SimpleNamespace(**(values | {"st_uid": uid, "st_gid": gid}))

        monkeypatch.setattr(os, "fstat", lambda fd: observed(self.original_fstat(fd)))
        monkeypatch.setattr(
            os,
            "stat",
            lambda *args, **kwargs: observed(self.original_stat(*args, **kwargs)),
        )

        def chown(fd, uid, gid):
            info = self.original_fstat(fd)
            old_uid, old_gid = self.metadata.get(
                (info.st_dev, info.st_ino), (info.st_uid, info.st_gid)
            )
            self.metadata[(info.st_dev, info.st_ino)] = (
                old_uid if uid == -1 else uid,
                old_gid if gid == -1 else gid,
            )

        monkeypatch.setattr(os, "fchown", chown)
        monkeypatch.setattr(
            self.f,
            "open_directory",
            lambda path, **kwargs: self.original_open_directory(
                self.actual(path), **kwargs
            ),
        )
        monkeypatch.setattr(self.m, "native_platform", lambda: "linux/amd64")
        monkeypatch.setattr(
            self.m,
            "read_mountinfo",
            lambda: self.m.parse_mountinfo("".join(self.mount_lines).encode()),
        )
        monkeypatch.setattr(os, "geteuid", lambda: 0)

    def actual(self, path):
        return self.base.joinpath(*Path(path).parts[1:])

    def register(self, path, uid, gid):
        info = self.original_stat(path, follow_symlinks=False)
        self.metadata[(info.st_dev, info.st_ino)] = uid, gid

    def observed(self, path):
        info = os.stat(path, follow_symlinks=False)
        return (
            info.st_dev,
            info.st_ino,
            info.st_uid,
            info.st_gid,
            info.st_mode & 0o7777,
            info.st_nlink,
            info.st_size,
        )

    def snapshot_targets(self):
        """Return immutable target-only names, metadata, inodes and regular bytes."""
        result = []
        for logical, _uid, _gid in self.target_specs:
            root = self.actual(logical)
            stack = [(Path("."), root)]
            while stack:
                relative, current = stack.pop()
                info = self.original_stat(current, follow_symlinks=False)
                uid, gid = self.metadata.get(
                    (info.st_dev, info.st_ino), (info.st_uid, info.st_gid)
                )
                is_directory = current.is_dir()
                result.append(
                    (
                        str(logical),
                        str(relative),
                        info.st_dev,
                        info.st_ino,
                        uid,
                        gid,
                        info.st_mode & 0o7777,
                        info.st_nlink,
                        None if is_directory else current.read_bytes(),
                    )
                )
                if is_directory:
                    for child in sorted(current.iterdir(), reverse=True):
                        stack.append((relative / child.name, child))
        return tuple(result)

    def make_partial_source(self):
        """Corrupt only this fixture's temporary trust target."""
        path = self.actual(self.target_specs[0][0]) / "partial"
        path.write_bytes(b"partial")
        path.chmod(0o600)
        self.register(path, 0, 0)

    def install_existing_targets(self):
        """Populate all five targets with the exact completed public-init state."""
        source_values = (
            (self.target_specs[0], "trust-set.json", self.output.trust_bytes),
            (self.target_specs[1], "ingress.json", self.output.ingress_bytes),
            (
                self.target_specs[2],
                "consumption-exchange.json",
                self.output.consumption_exchange_bytes,
            ),
        )
        for (logical, uid, gid), name, raw in source_values:
            root = self.actual(logical)
            root.chmod(0o750)
            self.register(root, uid, gid)
            path = root / name
            path.write_bytes(raw)
            path.chmod(0o440)
            self.register(path, uid, gid)
        for (logical, uid, gid), name in zip(
            self.target_specs[3:], ("receipts", "consumed"), strict=True
        ):
            root = self.actual(logical)
            root.chmod(0o750)
            self.register(root, uid, gid)
            child = root / name
            child.mkdir(mode=0o750)
            self.register(child, uid, gid)

    def empty_target(self, logical):
        root = self.actual(logical)
        for child in root.iterdir():
            if child.is_dir():
                for grandchild in child.iterdir():
                    grandchild.unlink()
                child.rmdir()
            else:
                child.unlink()
        root.chmod(0o755)
        self.register(root, 0, 0)

    def replace_input_root(self, displaced_name):
        root = self.actual(self.input_root)
        root.rename(self.base / displaced_name)
        root.mkdir(mode=0o750)
        self.register(root, 0, 0)
        for name, raw in (
            ("prepare-instance.json", self.prepare_inputs[3]),
            ("receipt-instance.json", self.receipt_instance_bytes),
            ("trust-set.json", self.trust_bytes),
            ("receipt-source-pins.json", self.output.pins_bytes),
        ):
            path = root / name
            path.write_bytes(raw)
            path.chmod(0o440)
            self.register(path, 0, 0)

    def add_receipt(self):
        digest_hex = hashlib.sha256(self.receipt_bytes).hexdigest()
        path = self.actual(self.target_specs[3][0]) / "receipts" / f"{digest_hex}.json"
        path.write_bytes(self.receipt_bytes)
        path.chmod(0o440)
        self.register(path, 20113, 21201)
        return path

    def add_consumed(self, payload=None):
        payload = consumed_marker() if payload is None else payload
        receipt_digest = json.loads(payload)["receipt_digest"]
        name = urlsafe_b64decode(receipt_digest + "=").hex() + ".json"
        path = self.actual(self.target_specs[4][0]) / "consumed" / name
        path.write_bytes(payload)
        path.chmod(0o440)
        self.register(path, 20102, 21201)
        return path


@pytest.fixture
def actual_receipt_public_init(tmp_path, monkeypatch):
    return ActualReceiptPublicInit(tmp_path, monkeypatch)
