"""Browser and optional HTTPS clients must meet one transport-independent command port."""

import ast
from dataclasses import dataclass
from pathlib import Path
import traceback
from uuid import uuid4

import pytest

from app.api.service_clients import (
    BrowserCommandSurface,
    HeadlessCommandSurface,
    ServiceRequestDenied,
)
from app.domain.schemas import Actor
from app.services.command_clients import (
    CanonicalClientCommand,
    CommandMutation,
    CommandPrincipal,
    CommandService,
    CommandServiceDenied,
)
from app.services.service_clients import ServiceClientRegistry


REPOSITORY = Path(__file__).resolve().parents[2]


def identifier():
    return str(uuid4())


def denial_sink(target=None):
    def record(reason_code):
        if target is not None:
            target.append(reason_code)
        return True

    return record


@dataclass
class Engine:
    revision: int = 7

    def execute(self, command, principal):
        assert type(command) is CanonicalClientCommand
        assert type(principal) is CommandPrincipal
        return CommandMutation(
            object_id=command.target_id,
            revision=self.revision + 1,
            event_type="work.revised",
            authority_class="ordinary_scoped",
            projection={"title": command.arguments["title"]},
        )


@dataclass
class MaliciousEngine:
    overrides: dict

    def execute(self, command, principal):
        values = {
            "object_id": command.target_id,
            "revision": command.expected_revision + 1,
            "event_type": "work.revised",
            "authority_class": "ordinary_scoped",
            "projection": {"title": command.arguments["title"]},
        }
        values.update(self.overrides)
        return CommandMutation(**values)


class FailingEngine:
    def execute(self, _command, _principal):
        raise ValueError("raw-engine-detail-must-not-escape")


def command(command_id=None):
    return {
        "schema_version": "client-command-v1",
        "command_id": command_id or identifier(),
        "command_type": "work.revise",
        "target_id": identifier(),
        "expected_revision": 7,
        "args": {"title": "새 제목"},
    }


def test_core_dependency_layers_never_import_http_or_static_presentation():
    roots = [REPOSITORY / "app" / name for name in ("domain", "runtime", "extensions", "services")]
    forbidden = []
    for root in roots:
        for source in root.glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(name == "api" and getattr(node, "level", 0) > 0
                       or name == "static" and getattr(node, "level", 0) > 0
                       or name == "app.api" or name.startswith("app.api.")
                       or name == "app.static" or name.startswith("app.static.")
                       for name in names):
                    forbidden.append((source, node.lineno, names))
    assert forbidden == []


def test_browser_and_headless_surfaces_produce_same_mutation_contract():
    owner = Actor(identifier(), "human", "local_session")
    owner_token = object()
    secret_values = iter((b"a" * 32,))
    clients = ServiceClientRegistry(
        verify_owner=lambda value: owner if value is owner_token else None,
        clock=lambda: 1_000,
        random_bytes=lambda size: next(secret_values),
    )
    issued = clients.issue(
        owner_token, client_id=identifier(), name="CI",
        scopes=("command:work.revise",), allowed_network_profile="portable_https",
        expires_at=2_000,
    )
    service = CommandService(
        engine=Engine(),
        policies={"work.revise": "ordinary_scoped", "approval.decide": "human_only"},
        denial_sink=denial_sink(), clock=lambda: 1_000,
    )
    browser = BrowserCommandSurface(
        service=service,
        verify_owner=lambda value: owner if value is owner_token else None,
    )
    headless = HeadlessCommandSurface(service=service, clients=clients)
    target_id = identifier()
    browser_value = command()
    browser_value["target_id"] = target_id
    headless_value = command()
    headless_value["target_id"] = target_id

    browser_receipt = browser.submit(browser_value, owner_request=owner_token)
    headless_receipt = headless.submit(
        headless_value,
        authorization=f"Bearer {issued.secret}",
        network_profile="portable_https",
        tls=True,
        cookie_header=None,
    )
    comparable = ("object_id", "revision", "event_type", "authority_class", "projection")
    assert {name: browser_receipt[name] for name in comparable} == {
        name: headless_receipt[name] for name in comparable
    }
    assert browser_receipt["actor_kind"] == "human"
    assert headless_receipt["actor_kind"] == "service_client"


def test_headless_surface_requires_tls_bearer_and_rejects_cookie_fallback():
    owner = Actor(identifier(), "human", "local_session")
    token = object()
    clients = ServiceClientRegistry(
        verify_owner=lambda value: owner if value is token else None,
        clock=lambda: 1_000, random_bytes=lambda size: b"a" * size,
    )
    issued = clients.issue(
        token, client_id=identifier(), name="CI", scopes=("command:work.revise",),
        allowed_network_profile="portable_https", expires_at=2_000,
    )
    surface = HeadlessCommandSurface(
        service=CommandService(
            engine=Engine(), policies={"work.revise": "ordinary_scoped"},
            denial_sink=denial_sink(), clock=lambda: 1_000,
        ),
        clients=clients,
    )
    for overrides in (
        {"tls": False},
        {"authorization": None},
        {"authorization": issued.secret},
        {"cookie_header": "session=browser"},
    ):
        arguments = {
            "authorization": f"Bearer {issued.secret}",
            "network_profile": "portable_https", "tls": True, "cookie_header": None,
            **overrides,
        }
        with pytest.raises(ServiceRequestDenied):
            surface.submit(command(), **arguments)


@pytest.mark.parametrize(
    "overrides", ({"tls": False}, {"cookie_header": "session=COOKIE-SECRET-SENTINEL"}),
)
def test_headless_preflight_traceback_does_not_retain_raw_bearer(overrides):
    owner = Actor(identifier(), "human", "local_session")
    token = object()
    clients = ServiceClientRegistry(
        verify_owner=lambda value: owner if value is token else None,
        clock=lambda: 1_000, random_bytes=lambda size: b"a" * size,
    )
    issued = clients.issue(
        token, client_id=identifier(), name="trace", scopes=("command:work.revise",),
        allowed_network_profile="portable_https", expires_at=2_000,
    )
    denials = []
    surface = HeadlessCommandSurface(
        service=CommandService(
            engine=Engine(), policies={"work.revise": "ordinary_scoped"},
            denial_sink=denial_sink(denials), clock=lambda: 1_000,
        ),
        clients=clients,
    )
    raw = f"Bearer {issued.secret}"
    arguments = {
        "authorization": raw, "network_profile": "portable_https", "tls": True,
        "cookie_header": None, **overrides,
    }
    with pytest.raises(ServiceRequestDenied) as captured:
        surface.submit(command(), **arguments)
    assert traceback.extract_tb(captured.value.__traceback__)
    sensitive_values = [raw]
    if overrides.get("cookie_header") is not None:
        sensitive_values.append(overrides["cookie_header"])
    current = captured.value.__traceback__
    while current is not None:
        if current.tb_frame.f_globals.get("__name__") == "app.api.service_clients":
            rendered = repr(current.tb_frame.f_locals)
            assert all(secret not in rendered for secret in sensitive_values)
        current = current.tb_next
    assert denials == ["transport"]


def test_service_client_cannot_cross_human_only_command_even_with_forged_mapping():
    denials = []
    service = CommandService(
        engine=Engine(), policies={"approval.decide": "human_only"},
        denial_sink=denial_sink(denials), clock=lambda: 1_000,
    )
    client = CommandPrincipal.service_client(
        client_id=identifier(), scopes=("command:approval.decide",), expires_at=2_000,
    )
    request = CanonicalClientCommand.from_mapping({
        **command(), "command_type": "approval.decide",
    })
    with pytest.raises(CommandServiceDenied, match="human"):
        service.submit(request, client)
    assert denials == ["human_only"]


def test_principal_flags_cannot_relabel_provider_or_service_actor_as_human():
    with pytest.raises(CommandServiceDenied):
        CommandPrincipal(
            Actor(identifier(), "service_client", "service_credential"),
            ("command:approval.decide",), 2_000, True, False,
        )
    with pytest.raises(CommandServiceDenied):
        CommandPrincipal(
            Actor(identifier(), "provider", "model_output"), (), 2_000, True, False,
        )
    with pytest.raises(CommandServiceDenied):
        CommandPrincipal(
            Actor(identifier(), "human", "local_session"), (), 2_000, True, True,
        )


def test_command_mutation_projection_is_deeply_immutable_and_receipts_are_detached():
    source = {"nested": {"items": [{"value": "original"}]}}
    mutation = CommandMutation(
        object_id=identifier(), revision=8, event_type="work.revised",
        authority_class="ordinary_scoped", projection=source,
    )
    source["nested"]["items"][0]["value"] = "changed"
    assert mutation.projection["nested"]["items"][0]["value"] == "original"
    with pytest.raises(TypeError):
        mutation.projection["nested"]["items"][0]["value"] = "injected"
    detached = mutation.projection_copy()
    detached["nested"]["items"][0]["value"] = "local"
    assert mutation.projection["nested"]["items"][0]["value"] == "original"
    assert "original" not in repr(mutation)


def test_canonical_command_repr_does_not_expose_argument_payload():
    sentinel = "private-command-argument-sentinel"
    request = CanonicalClientCommand.from_mapping({
        **command(), "args": {"title": sentinel},
    })

    assert sentinel not in repr(request)
    assert "_arguments" not in repr(request)


def test_command_denial_sink_is_required_and_fails_closed():
    with pytest.raises(TypeError, match="denial sink"):
        CommandService(engine=Engine(), policies={"work.revise": "ordinary_scoped"},
                       denial_sink=None, clock=lambda: 1_000)
    with pytest.raises(TypeError, match="clock"):
        CommandService(engine=Engine(), policies={"work.revise": "ordinary_scoped"},
                       denial_sink=denial_sink(), clock=None)
    service = CommandService(
        engine=Engine(), policies={"work.revise": "ordinary_scoped"},
        denial_sink=lambda _reason: False, clock=lambda: 1_000,
    )
    principal = CommandPrincipal.human(Actor(identifier(), "human", "local_session"))
    with pytest.raises(CommandServiceDenied, match="audit sink failed"):
        service.submit_mapping({"not": "a command"}, principal)


def test_deployment_only_and_invalid_commands_emit_closed_denial_reasons():
    denials = []
    principal = CommandPrincipal.human(Actor(identifier(), "human", "local_session"))
    service = CommandService(
        engine=Engine(), policies={"work.revise": "deployment_only"},
        denial_sink=denial_sink(denials), clock=lambda: 1_000,
    )
    with pytest.raises(CommandServiceDenied, match="not registered"):
        service.submit_mapping({**command(), "command_type": "work.unknown"}, principal)
    with pytest.raises(CommandServiceDenied, match="deployment"):
        service.submit(CanonicalClientCommand.from_mapping(command()), principal)
    with pytest.raises(CommandServiceDenied, match="invalid"):
        service.submit_mapping({"not": "a command"}, principal)
    assert denials == ["unregistered_command", "deployment_only", "invalid_command"]


def test_expired_principal_clock_failure_and_engine_exception_are_denied_and_logged():
    request = CanonicalClientCommand.from_mapping(command())
    actor = Actor(identifier(), "service_client", "service_credential")

    expired_denials = []
    expired = CommandService(
        engine=Engine(), policies={"work.revise": "ordinary_scoped"},
        denial_sink=denial_sink(expired_denials), clock=lambda: 1_000,
    )
    principal = CommandPrincipal(
        actor, ("command:work.revise",), 1_000, False, False,
    )
    with pytest.raises(CommandServiceDenied, match="expired"):
        expired.submit(request, principal)
    assert expired_denials == ["principal_expired"]

    clock_denials = []
    broken_clock = CommandService(
        engine=Engine(), policies={"work.revise": "ordinary_scoped"},
        denial_sink=denial_sink(clock_denials), clock=lambda: "not-a-time",
    )
    with pytest.raises(CommandServiceDenied, match="clock"):
        broken_clock.submit(
            request, CommandPrincipal.human(Actor(identifier(), "human", "local_session")),
        )
    assert clock_denials == ["clock"]

    engine_denials = []
    failed_engine = CommandService(
        engine=FailingEngine(), policies={"work.revise": "ordinary_scoped"},
        denial_sink=denial_sink(engine_denials), clock=lambda: 1_000,
    )
    with pytest.raises(CommandServiceDenied, match="engine failed") as captured:
        failed_engine.submit(
            request, CommandPrincipal.human(Actor(identifier(), "human", "local_session")),
        )
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert engine_denials == ["engine_failure"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"object_id": identifier()}, "another target"),
        ({"revision": 9}, "next revision"),
        ({"event_type": "work.fabricated"}, "unregistered event"),
    ),
)
def test_command_service_rejects_engine_mutations_that_break_command_identity(overrides, message):
    request = CanonicalClientCommand.from_mapping(command())
    principal = CommandPrincipal.human(Actor(identifier(), "human", "local_session"))
    denials = []
    service = CommandService(
        engine=MaliciousEngine(overrides),
        policies={"work.revise": "ordinary_scoped"},
        denial_sink=denial_sink(denials), clock=lambda: 1_000,
    )

    with pytest.raises(CommandServiceDenied, match=message):
        service.submit(request, principal)
    expected = {
        "another target": "target_mismatch",
        "next revision": "revision_mismatch",
        "unregistered event": "event_unregistered",
    }
    assert denials == [expected[message]]
