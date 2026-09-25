"""Fixed pin registration and the existing application's source ownership."""

import os
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import deployment_prepare as prepare
from app.api import first_party as fp
from app.api.router_composition import RouteCompositionError
from app.deployment import contracts as c
from app.tests.provider_source_reader_fixture import (
    reader_tree as reader_tree,  # noqa: PLC0414
)

KEY = "DEEPTWIN_PROVIDER_STAGE_CONTEXT_SHA256"
EXPORT = "deployment-provider.source-context"


def context(tree, values):
    return SimpleNamespace(
        startup_inputs=fp.StartupInputs(values),
        owner_authority=SimpleNamespace(profile=tree.profile),
        domain_store=None,
        base_path=tree.profile.base_path,
    )


def test_actual_startup_key_is_frozen(monkeypatch):
    monkeypatch.setenv(KEY, "a" * 64)
    frozen = fp.build_startup_inputs(values=None, protected_roots=())
    monkeypatch.setenv(KEY, "b" * 64)
    assert frozen.values.get(KEY) == "a" * 64
    assert prepare.STARTUP_KEYS[-2:] == (KEY, 'DEEPTWIN_INSTALLATION_RELEASE_CONTEXT_SHA256')


def test_installation_release_optional_source_export_is_owned(tmp_path, monkeypatch):
    from app.tests.test_installation_release_sources import retained_case
    from app.deployment.installation_release_contracts import STARTUP_KEY
    tree, raw = retained_case(tmp_path, monkeypatch)
    monkeypatch.setattr(prepare, 'PersistentDeploymentPrepare', lambda *args, **kw: SimpleNamespace(**kw))
    result = prepare.prepare_services(context(tree, {KEY:c.digest(tree.bundle[16][1]), STARTUP_KEY:c.digest(raw)}),
        dependencies={'extension-candidates.registry':None})
    try:
        source = result.exports['installation-release.source-context']
        provider = result.exports[EXPORT]
        assert source.read_current()[1][1] == raw
        assert source._provider_context is provider
        assert result.owned_resources == (provider,source)
    finally:
        for handle in reversed(result.owned_resources): handle.close()
    assert not tree.live


def test_missing_release_pin_preserves_provider_export(reader_tree,monkeypatch):
    monkeypatch.setattr(prepare,'PersistentDeploymentPrepare',lambda *args,**kw: SimpleNamespace(**kw))
    result = prepare.prepare_services(context(reader_tree,{KEY:c.digest(reader_tree.bundle[16][1])}),
        dependencies={'extension-candidates.registry':None})
    try:
        assert result.exports['installation-release.source-context'] is None
        assert result.exports[EXPORT].read_current() == reader_tree.bundle
    finally:
        for handle in reversed(result.owned_resources): handle.close()


def test_actual_reader_export_owned_at_startup(reader_tree, monkeypatch):
    from app.deployment.contracts import digest

    monkeypatch.setattr(
        prepare,
        "PersistentDeploymentPrepare",
        lambda *args, **kw: SimpleNamespace(**kw),
    )
    result = prepare.prepare_services(
        context(reader_tree, {KEY: digest(reader_tree.bundle[16][1])}),
        dependencies={"extension-candidates.registry": None},
    )
    source = result.exports.get(EXPORT)
    assert source is not None, "Startup must open and own the actual provider reader"
    try:
        assert source.read_current() == reader_tree.bundle
        assert result.owned_resources == (source,)
    finally:
        for handle in result.owned_resources:
            handle.close()
    assert not reader_tree.live


@pytest.mark.parametrize("pin", [None, "", "A" * 64, "x", 123])
def test_bad_or_absent_pin_never_opens_provider(reader_tree, monkeypatch, pin):
    monkeypatch.setattr(
        prepare,
        "PersistentDeploymentPrepare",
        lambda *args, **kw: SimpleNamespace(**kw),
    )

    def forbidden(**kw):
        pytest.fail("invalid provider pin opened paths")

    monkeypatch.setattr(prepare, "open_provider_source_context", forbidden)
    # Invalid non-string values are omitted by the actual frozen snapshot builder.
    frozen = fp.build_startup_inputs(
        values={} if pin is None else {KEY: pin}, protected_roots=()
    )
    ctx = context(reader_tree, {})
    ctx.startup_inputs = frozen
    result = prepare.prepare_services(
        ctx, dependencies={"extension-candidates.registry": None}
    )
    assert result.exports[EXPORT] is None
    assert result.exports["deployment-prepare.service"] is not None
    assert result.owned_resources == ()
    assert not reader_tree.opens


@pytest.mark.parametrize(
    "error", [c.DeploymentSourceError, c.DeploymentSourceUnavailable]
)
def test_unavailable_context_does_not_disable_old_service(
    reader_tree, monkeypatch, error
):
    monkeypatch.setattr(
        prepare,
        "PersistentDeploymentPrepare",
        lambda *args, **kw: SimpleNamespace(**kw),
    )

    def unavailable(**kw):
        raise error()

    monkeypatch.setattr(prepare, "open_provider_source_context", unavailable)
    result = prepare.prepare_services(
        context(reader_tree, {KEY: "a" * 64}),
        dependencies={"extension-candidates.registry": None},
    )
    assert result.exports[EXPORT] is None
    assert result.exports["deployment-prepare.service"] is not None


def test_provider_process_control_exception_propagates(reader_tree, monkeypatch):
    primary = KeyboardInterrupt("startup")

    def interrupted(**kwargs):
        raise primary

    monkeypatch.setattr(prepare, "open_provider_source_context", interrupted)
    with pytest.raises(KeyboardInterrupt) as caught:
        prepare.prepare_services(
            context(reader_tree, {KEY: "a" * 64}),
            dependencies={"extension-candidates.registry": None},
        )
    assert caught.value is primary


def test_frozen_pin_and_original_five_source_arguments(reader_tree, monkeypatch):
    closed, observed = [], []

    class OldSource:
        def close(self):
            closed.append(self)

    originals = [OldSource() for _ in range(5)]
    for name, value in zip(
        (
            "open_topology_source",
            "open_exchange_source",
            "open_public_trust_source",
            "open_receipt_ingress_source",
            "open_consumption_exchange_source",
        ),
        originals,
    ):
        monkeypatch.setattr(prepare, name, lambda _value=value, **kw: _value)

    def service(*args, **kw):
        observed.append(kw)
        return SimpleNamespace(**kw)

    monkeypatch.setattr(prepare, "PersistentDeploymentPrepare", service)
    values = {key: "a" * 64 for key in prepare.STARTUP_KEYS[:9]}
    values[KEY] = c.digest(reader_tree.bundle[16][1])
    ctx = context(reader_tree, values)
    values[KEY] = "b" * 64
    monkeypatch.setenv(KEY, "c" * 64)
    result = prepare.prepare_services(
        ctx, dependencies={"extension-candidates.registry": None}
    )
    source = result.exports[EXPORT]
    assert source.read_current() == reader_tree.bundle
    assert observed == [
        dict(
            zip(
                (
                    "topology_source",
                    "exchange_source",
                    "public_trust_source",
                    "receipt_ingress_source",
                    "consumption_exchange_source",
                ),
                originals,
            ),
            provider_source_context=source,
        )
    ]
    assert result.owned_resources == (*originals, source)
    for resource in result.owned_resources:
        resource.close()
    assert closed == originals
    assert not reader_tree.live


@pytest.mark.parametrize("checkpoint", ["service", "router", "result"])
def test_contribution_construction_failure_closes_actual_reader(
    reader_tree, monkeypatch, checkpoint
):
    primary = KeyboardInterrupt("construction")
    monkeypatch.setattr(
        prepare,
        "PersistentDeploymentPrepare",
        lambda *args, **kw: SimpleNamespace(**kw),
    )

    def fail(*args, **kw):
        raise primary

    monkeypatch.setattr(
        prepare,
        {
            "service": "PersistentDeploymentPrepare",
            "router": "create_router",
            "result": "ContributionServices",
        }[checkpoint],
        fail,
    )
    with pytest.raises(KeyboardInterrupt) as caught:
        prepare.prepare_services(
            context(reader_tree, {KEY: c.digest(reader_tree.bundle[16][1])}),
            dependencies={"extension-candidates.registry": None},
        )
    assert caught.value is primary
    assert reader_tree.peak >= 47
    assert not reader_tree.live


def app_arguments(tree):
    """Synthetic session setup only, using the existing real application owner."""
    from base64 import urlsafe_b64encode

    from app.operations.session_root import initialize_session_root
    from app.operations.setup import build_bootstrap_configuration

    session = tree.base / "app-session"
    data = tree.base / "app-data"
    initialize_session_root(
        session,
        profile=tree.profile,
        recovery_epoch=1,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    data.mkdir(mode=0o700)
    # Provider protected-root observations preserve the real directories' metadata.
    tree.mount(session, False)
    tree.mount(data, False)
    return data, {
        "deployment_config": build_bootstrap_configuration(
            profile=tree.profile,
            verifier_b64u=urlsafe_b64encode(b"s" * 32).rstrip(b"=").decode(),
        ),
        "session_root_dir": session,
        "expected_uid": os.getuid(),
        "expected_gid": os.getgid(),
        "first_party_startup_values": {KEY: c.digest(tree.bundle[16][1])},
    }


@pytest.mark.parametrize(
    "failure", [None, "activation", "composition", "assembly", "dependency"]
)
def test_actual_application_owner_cleanup(reader_tree, monkeypatch, failure):
    from app import server
    from app.api import first_party_catalog

    data, arguments = app_arguments(reader_tree)
    sources = []
    actual_open = prepare.open_provider_source_context

    def opened(**kwargs):
        source = actual_open(**kwargs)
        sources.append(source)
        return source

    monkeypatch.setattr(prepare, "open_provider_source_context", opened)

    def fail(*args, **kw):
        raise RuntimeError("controlled lifecycle failure")

    if failure == "activation":
        entries = tuple(
            replace(entry, startup_reconcile=fail)
            if entry.factory is prepare.prepare_services
            else entry
            for entry in first_party_catalog.INSTALLED
        )
        monkeypatch.setattr(first_party_catalog, "INSTALLED", entries)
    elif failure == "composition":
        entries = tuple(
            replace(entry, provides=(*entry.provides, "deployment-test.missing-export"))
            if entry.factory is prepare.prepare_services
            else entry
            for entry in first_party_catalog.INSTALLED
        )
        monkeypatch.setattr(first_party_catalog, "INSTALLED", entries)
    elif failure == "dependency":
        entries = tuple(
            replace(entry, provides=("deployment-prepare.service",))
            if entry.factory is prepare.prepare_services
            else entry
            for entry in first_party_catalog.INSTALLED
        )
        monkeypatch.setattr(first_party_catalog, "INSTALLED", entries)
    elif failure == "assembly":
        from app.api import session_routes

        monkeypatch.setattr(session_routes, "create_session_router", fail)
    if failure in {"composition", "assembly", "dependency"}:
        with pytest.raises(
            RouteCompositionError if failure in {"composition", "dependency"} else RuntimeError
        ):
            server.create_app(data, **arguments)
    else:
        application = server.create_app(data, **arguments)
        source = application.state.first_party_exports[EXPORT]
        assert source is sources[0]
        assert source.read_current() == reader_tree.bundle
        assert application.state.route_composition.route_count == 98
        if failure == "activation":
            with pytest.raises(RuntimeError), TestClient(application):
                pytest.fail("activation failure entered serving")
        else:
            with TestClient(application):
                assert source.read_current() == reader_tree.bundle
    if failure == "dependency":
        assert sources == []
    else:
        assert len(sources) == 1
        with pytest.raises(c.DeploymentSourceError):
            sources[0].read_current()
    assert not reader_tree.live
