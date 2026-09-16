"""Actual owner/service and retained U/J/K from one bounded synthetic Node session."""

import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from uuid import uuid4

from app.deployment import receipt_sources as sources
from app.deployment.prepare_contracts import epoch_ms
from app.deployment.prepare_service import PersistentDeploymentPrepare
from app.deployment.receipt_render import render_receipt_sources
from app.deployment.receipt_source_contracts import RECEIPT_RECIPE_BYTES
from app.domain.refs import canonical_json, parse_canonical
from app.tests.deployment_prepare_fixture import service_context
from app.tests.deployment_receipt_session_fixture import OwnedReceiptSession
from app.tests.deployment_source_fixture import inputs


def b64(raw):
    return urlsafe_b64encode(raw).decode().rstrip("=")


def receipt_files(physical, profile, session, *, capacity=1):
    """Install synthetic public U/J/K files before the actual HTTP factory opens them."""
    release = inputs(capacity=capacity)
    instance_raw = canonical_json(
        {**parse_canonical(release[3]), "origin_profile": profile.as_dict()}
    )
    receipt_instance = canonical_json(
        {
            "schema_version": "deployment-receipt-instance-v1",
            "prepare_instance_sha256": sha256(instance_raw).hexdigest(),
            "trust_set_sha256": sha256(session.trust_bytes).hexdigest(),
            "receipt_ingress_id": str(uuid4()),
            "consumption_exchange_id": str(uuid4()),
        }
    )
    rendered = render_receipt_sources(
        *release[:3],
        instance_raw,
        RECEIPT_RECIPE_BYTES,
        receipt_instance,
        session.trust_bytes,
    )
    for index, (root, uid, gid, ro, name, raw) in enumerate(
        (
            (
                sources.PUBLIC_TRUST_ROOT,
                0,
                20102,
                True,
                "trust-set.json",
                rendered.trust_bytes,
            ),
            (
                sources.RECEIPT_INGRESS_ROOT,
                0,
                21201,
                True,
                "ingress.json",
                rendered.ingress_bytes,
            ),
            (
                sources.CONSUMPTION_EXCHANGE_ROOT,
                0,
                21201,
                True,
                "consumption-exchange.json",
                rendered.consumption_exchange_bytes,
            ),
            (sources.INCOMING_ROOT, 20113, 21201, True, "receipts", None),
            (sources.CONSUMED_ROOT, 20102, 21201, False, "consumed", None),
        ),
        200,
    ):
        target = physical.actual(root)
        target.mkdir(parents=True, mode=0o750)
        physical.register(target, uid, gid)
        physical.mount_lines.append(
            f"{index} 999 {physical.device} /receipt{index} {root} {'ro' if ro else 'rw'} - ext4 /dev/fake rw\n"
        )
        child = target / name
        if raw is None:
            child.mkdir(mode=0o750)
        else:
            child.write_bytes(raw)
            child.chmod(0o440)
        physical.register(child, uid, gid)
    return rendered


def http_receipt_sources(physical, profile, session, *, capacity=1):
    rendered = receipt_files(physical, profile, session, capacity=capacity)
    pins = parse_canonical(rendered.pins_bytes)
    return {
        "DEEPTWIN_RECEIPT_RECIPE_SHA256": pins["receipt_recipe_sha256"],
        "DEEPTWIN_RECEIPT_INSTANCE_SHA256": pins["receipt_instance_sha256"],
        "DEEPTWIN_DEPLOYMENT_TRUST_SHA256": pins["trust_sha256"],
        "DEEPTWIN_RECEIPT_INGRESS_SHA256": pins["ingress_sha256"],
        "DEEPTWIN_CONSUMPTION_EXCHANGE_SHA256": pins["consumption_exchange_sha256"],
    }


def http_signed_case(physical, session, current, monkeypatch, *, case_name):
    """Publish one actual selected public signature; never import through a callback."""
    response = session.case(canonical_json(current["request"]), case_name=case_name)
    raw = urlsafe_b64decode(
        response["receipt_b64"] + "=" * (-len(response["receipt_b64"]) % 4)
    )
    digest = sha256(raw).digest()
    final = physical.actual(sources.RECEIPTS_ROOT) / (digest.hex() + ".json")
    final.write_bytes(raw)
    final.chmod(0o440)
    physical.register(final, 20113, 21201)
    now = max(
        time.time_ns() // 1000000, epoch_ms(current["request"]["created_at"]) + 2123
    )
    monkeypatch.setattr(time, "time_ns", lambda: now * 1000000)
    return {
        "command_id": str(uuid4()),
        "request_digest": current["request_digest"],
        "receipt_digest": b64(digest),
        "expected_revision": 1,
    }, final


def reopen(actual, *, trust=True, ingress=True, consumption=True, prepare_sources=True):
    return PersistentDeploymentPrepare(
        actual.domain,
        actual.owner,
        actual.registry,
        topology_source=actual.topology if prepare_sources else None,
        exchange_source=actual.exchange if prepare_sources else None,
        public_trust_source=actual.trust if trust else None,
        receipt_ingress_source=actual.ingress if ingress else None,
        consumption_exchange_source=actual.consumption if consumption else None,
    )


@contextmanager
def receipt_context(tmp_path, monkeypatch, *, capacity=1):
    with (
        service_context(tmp_path, monkeypatch, capacity=capacity) as actual,
        ExitStack() as stack,
    ):
        session = stack.enter_context(OwnedReceiptSession(actual.profile))
        rendered = receipt_files(
            actual.actual, actual.profile, session, capacity=capacity
        )
        pins = parse_canonical(rendered.pins_bytes)
        common = {
            "profile": actual.profile,
            "protected_roots": (),
            "receipt_recipe_sha256": pins["receipt_recipe_sha256"],
            "receipt_instance_sha256": pins["receipt_instance_sha256"],
        }
        actual.trust = sources.open_public_trust_source(
            profile=actual.profile,
            trust_sha256=pins["trust_sha256"],
            protected_roots=(),
        )
        stack.callback(actual.trust.close)
        actual.ingress = sources.open_receipt_ingress_source(
            **common, ingress_sha256=pins["ingress_sha256"]
        )
        stack.callback(actual.ingress.close)
        actual.consumption = sources.open_consumption_exchange_source(
            **common, consumption_exchange_sha256=pins["consumption_exchange_sha256"]
        )
        stack.callback(actual.consumption.close)
        actual.session, actual.receipt_output = session, rendered
        actual.service = reopen(actual)
        yield actual


def signed_case(actual, monkeypatch, *, case_name="valid_failed_absent", payload=None):
    prepared = actual.service.prepare(actual.request, payload or actual.payload)
    current = actual.service.read(actual.read_request, prepared["request_id"])
    command, final = http_signed_case(
        actual.actual, actual.session, current, monkeypatch, case_name=case_name
    )
    return prepared, command, final.read_bytes(), final
