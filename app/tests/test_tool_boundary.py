"""US3 tool dispatcher boundary: closed registry, grants, effects, replay.

The dispatcher, not the model, maps tool ids to code: an unregistered tool
or an unknown version is unsupported, never interpreted, and nothing an
extension or model outputs can add a tool or widen its input profile. Tool
arguments carry no artifact or selector refs — the ordered artifact-input
bindings are the sole byte-input authority — and no argument smuggles a
host path. The required grant must match exactly; the ports contract's
external family of effects requires an explicit effect approval; replay policy
is authoritative (a `replay="never"` tool never re-dispatches the same request,
a dedup tool returns the same envelope); and an unknown external outcome
holds the request — retry is blocked until reconciliation (runtime.md §6,
FR-014/FR-032; T047). An admitted, in-flight envelope is the only key to a
tool's side channels: scoped file access that follows no symlink at any depth
(nor a directory swapped mid-walk) and refuses hardlinks, fifos and oversize
files; network access only to declared hosts through the egress broker; and
renderable results that are bounded, never active content, and sniffed.
"""

import dataclasses
import os

import pytest

from app.runtime.egress import freeze_egress_policy
from app.runtime.tools import (
    ToolBoundaryError,
    admit_network,
    admit_tool_result,
    dispatch_tool,
    open_in_scope,
    open_tool_registry,
    record_outcome,
    register_tool,
)
from app.tests.test_alternatives import ref

REQUEST = "00000000-0000-4000-8000-00000000ee01"
REQUEST2 = "00000000-0000-4000-8000-00000000ee02"


def definition(**overrides):
    value = {
        "tool_id": "deeptwin_pdf_render",
        "version": 1,
        "argument_keys": {"page_range": "str", "dpi": "int"},
        "result_schema_id": "pdf-render-result-v1",
        "effect_class": "write_reversible",
        "required_grant": ref("grant", 1401),
        "filesystem_scopes": ["workspace/artifacts"],
        "network_scopes": [],
        "timeout_seconds": 60,
        "max_result_bytes": 8_388_608,
        "idempotency": "dedup_by_request",
        "replay": "safe",
        "implementation_sha256": "cd" * 32,
        "qualification_ref": ref("extension_qualification", 1402),
    }
    value.update(overrides)
    return value


def request(**overrides):
    value = {
        "tool_id": "deeptwin_pdf_render",
        "version": 1,
        "request_id": REQUEST,
        "arguments": {"page_range": "1-4", "dpi": 144},
        "grant_ref": ref("grant", 1401),
        "effect_approval_ref": None,
        "artifact_inputs": [ref("artifact", 1403)],
    }
    value.update(overrides)
    return value


def registry():
    return register_tool(open_tool_registry(), definition())


def test_the_registry_is_closed_and_exact():
    state = registry()
    with pytest.raises(ToolBoundaryError):
        register_tool(state, definition())  # same id+version never twice
    with pytest.raises(ToolBoundaryError):
        # unknown tool: unsupported, never interpreted
        dispatch_tool(state, request(tool_id="model_invented_tool"))
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(version=9))
    with pytest.raises(ToolBoundaryError):
        register_tool(state, definition(effect_class="vibes"))


def test_arguments_never_carry_refs_or_host_paths():
    state = registry()
    envelope, state = dispatch_tool(state, request())
    assert envelope.tool_id == "deeptwin_pdf_render"
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(
            request_id=REQUEST2,
            arguments={"page_range": "1-4", "dpi": 144,
                       "artifact_ref": ref("artifact", 1404)},
        ))
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(
            request_id=REQUEST2,
            arguments={"page_range": "/etc/passwd", "dpi": 144},
        ))
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(
            request_id=REQUEST2,
            arguments={"page_range": "../../secrets", "dpi": 144},
        ))
    with pytest.raises(ToolBoundaryError):
        # undeclared argument keys widen the input profile: refused
        dispatch_tool(state, request(
            request_id=REQUEST2,
            arguments={"page_range": "1-4", "dpi": 144, "shell": "rm"},
        ))
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(
            request_id=REQUEST2,
            arguments={"page_range": "1-4", "dpi": "144"},  # wrong type
        ))


def test_the_grant_must_match_exactly():
    state = registry()
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(grant_ref=ref("grant", 1499)))


def test_external_and_irreversible_effects_require_approval():
    state = register_tool(registry(), definition(
        tool_id="deeptwin_send_email", effect_class="external_irreversible",
        replay="never", idempotency="none",
    ))
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(
            tool_id="deeptwin_send_email", request_id=REQUEST2,
        ))
    envelope, state = dispatch_tool(state, request(
        tool_id="deeptwin_send_email", request_id=REQUEST2,
        effect_approval_ref=ref("action_approval", 1405),
    ))
    assert envelope.effect_class == "external_irreversible"
    # a write tool never demands an approval it does not need
    _envelope, _state = dispatch_tool(state, request())


def test_replay_policy_is_authoritative():
    state = register_tool(registry(), definition(
        tool_id="deeptwin_send_email", effect_class="external_irreversible",
        replay="never", idempotency="none",
    ))
    _envelope, state = dispatch_tool(state, request(
        tool_id="deeptwin_send_email", request_id=REQUEST2,
        effect_approval_ref=ref("action_approval", 1405),
    ))
    with pytest.raises(ToolBoundaryError):
        # an irreversible request never re-dispatches
        dispatch_tool(state, request(
            tool_id="deeptwin_send_email", request_id=REQUEST2,
            effect_approval_ref=ref("action_approval", 1405),
        ))
    first, state = dispatch_tool(state, request())
    again, state = dispatch_tool(state, request())  # dedup_by_request
    assert again == first


def test_an_unknown_outcome_blocks_retry_until_reconciled():
    state = register_tool(registry(), definition(
        tool_id="deeptwin_send_email", effect_class="external_irreversible",
        replay="requires_confirmation", idempotency="none",
    ))
    _envelope, state = dispatch_tool(state, request(
        tool_id="deeptwin_send_email", request_id=REQUEST2,
        effect_approval_ref=ref("action_approval", 1405),
    ))
    state = record_outcome(state, REQUEST2, "unknown")
    with pytest.raises(ToolBoundaryError):
        # unknown external outcome: held, never silently retried
        dispatch_tool(state, request(
            tool_id="deeptwin_send_email", request_id=REQUEST2,
            effect_approval_ref=ref("action_approval", 1405),
        ))
    state = record_outcome(state, REQUEST2, "failed")
    with pytest.raises(ToolBoundaryError):
        record_outcome(state, REQUEST2, "succeeded")  # outcomes are final
    with pytest.raises(ToolBoundaryError):
        record_outcome(state, "00000000-0000-4000-8000-00000000ee09",
                       "succeeded")


def test_values_are_issued_never_constructed():
    state = registry()
    envelope, state = dispatch_tool(state, request())
    with pytest.raises(TypeError):
        dataclasses.replace(envelope, effect_class="read")
    with pytest.raises(TypeError):
        dataclasses.replace(state, dispatched=())
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(object(), request())
    with pytest.raises(ToolBoundaryError):
        register_tool(object(), definition())


def test_the_effect_vocabulary_is_the_ports_contracts_and_nothing_else():
    # T087 reconciliation: the ports contract's seven effect classes are the one closed set
    # the ledger, the transport and this boundary share; the boundary's earlier four names
    # (read/write/external/irreversible) are refused — a legacy `external` never states
    # reversibility, and a second spelling would shadow the closed set; the approval rule is
    # the ports' external family, equal to the ledger's own set
    from app.extensions import port_contracts
    from app.runtime import ledger, tools

    assert tools.EFFECT_CLASSES == port_contracts.EFFECT_CLASSES
    assert tools.APPROVAL_EFFECTS == ledger.TOOL_APPROVAL_EFFECTS
    assert tools.APPROVAL_EFFECTS == {name for name, family in port_contracts.EFFECT_FAMILIES.items() if family == "X"}
    assert not hasattr(tools, "LEGACY_EFFECT_CLASSES")
    for name in sorted(port_contracts.EFFECT_CLASSES):
        state = register_tool(open_tool_registry(), definition(effect_class=name))
        assert state.definitions[0].effect_class == name
    for refused in ("write", "external", "irreversible", "READ", ["read"], None, 1):
        with pytest.raises(ToolBoundaryError):
            register_tool(open_tool_registry(), definition(effect_class=refused))


@pytest.mark.parametrize("effect", ["none", "read"])
def test_a_no_effect_or_read_tool_never_records_an_unknown_outcome(effect):
    # review closure: the ports forbid an unknown effect for the N family (nothing external
    # could be in doubt), so the boundary refuses to hold such a request on an unknown outcome
    state = register_tool(open_tool_registry(), definition(effect_class=effect))
    _envelope, state = dispatch_tool(state, request())
    with pytest.raises(ToolBoundaryError):
        record_outcome(state, REQUEST, "unknown")
    state = record_outcome(state, REQUEST, "failed")
    assert state.dispatched[0][3] == "failed"


@pytest.mark.parametrize("effect", ["external_reversible", "external_irreversible",
                                    "instance_critical_secret", "instance_critical_storage"])
def test_every_external_family_effect_requires_an_approval(effect):
    state = register_tool(open_tool_registry(), definition(
        tool_id="deeptwin_send_email", effect_class=effect, replay="never", idempotency="none"))
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(tool_id="deeptwin_send_email", request_id=REQUEST2))
    envelope, _state = dispatch_tool(state, request(
        tool_id="deeptwin_send_email", request_id=REQUEST2, effect_approval_ref=ref("action_approval", 1405)))
    assert envelope.effect_class == effect


@pytest.mark.parametrize("effect", ["none", "read", "write_reversible"])
def test_no_other_effect_takes_an_approval(effect):
    state = register_tool(open_tool_registry(), definition(effect_class=effect))
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(effect_approval_ref=ref("action_approval", 1405)))
    envelope, _state = dispatch_tool(state, request())
    assert envelope.effect_class == effect



# --- side channels: filesystem scope, network scope, renderable results ------------

SCOPE = "workspace/artifacts"


def in_flight(**overrides):
    state = register_tool(open_tool_registry(), definition(**overrides))
    envelope, state = dispatch_tool(state, request())
    return state, envelope


@pytest.fixture
def scope_dir(tmp_path):
    root = tmp_path / "scope"
    (root / "pages").mkdir(parents=True)
    (root / "pages" / "one.txt").write_text("page one")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("host secret")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    yield root, outside, descriptor
    os.close(descriptor)


def test_scoped_reads_follow_no_symlink_at_any_depth(scope_dir):
    root, outside, fd = scope_dir
    state, envelope = in_flight()
    handle = open_in_scope(state, envelope, SCOPE, fd, "pages/one.txt")
    assert os.read(handle, 64) == b"page one"
    os.close(handle)
    (root / "link.txt").symlink_to(outside / "secret.txt")
    (root / "linkdir").symlink_to(outside)
    for relative in ("link.txt", "linkdir/secret.txt"):
        with pytest.raises(ToolBoundaryError, match="symlink"):
            open_in_scope(state, envelope, SCOPE, fd, relative)
    for relative in ("../outside/secret.txt", "/etc/passwd", "pages/../pages/one.txt",
                     "pages//one.txt", "./pages/one.txt", "~/x", "pages/one.txt\x00", ""):
        with pytest.raises(ToolBoundaryError):
            open_in_scope(state, envelope, SCOPE, fd, relative)
    with pytest.raises(ToolBoundaryError, match="no such filesystem scope"):
        open_in_scope(state, envelope, "workspace/other", fd, "pages/one.txt")


def test_hardlinks_devices_and_oversize_files_are_refused(scope_dir):
    root, outside, fd = scope_dir
    state, envelope = in_flight(max_result_bytes=4)
    os.link(outside / "secret.txt", root / "alias.txt")
    with pytest.raises(ToolBoundaryError, match="single-link"):
        open_in_scope(state, envelope, SCOPE, fd, "alias.txt")
    os.mkfifo(root / "pipe")
    with pytest.raises(ToolBoundaryError, match="single-link regular"):
        open_in_scope(state, envelope, SCOPE, fd, "pipe")
    with pytest.raises(ToolBoundaryError, match="byte cap"):
        open_in_scope(state, envelope, SCOPE, fd, "pages/one.txt")


def test_a_directory_swapped_for_a_symlink_mid_walk_refuses(scope_dir):
    root, outside, fd = scope_dir
    state, envelope = in_flight()
    (root / "a").mkdir()
    (root / "a" / "b").mkdir()
    (outside / "b").mkdir()
    (outside / "b" / "secret.txt").write_text("host secret")

    def swap(component):
        if component == "b":  # after `a` was opened, before `b`
            os.rename(root / "a" / "b", root / "a" / "b-moved")
            (root / "a" / "b").symlink_to(outside / "b")

    with pytest.raises(ToolBoundaryError, match="symlink"):
        open_in_scope(state, envelope, SCOPE, fd, "a/b/secret.txt", _between=swap)


def test_scoped_writes_create_exclusively_and_only_for_writing_tools(scope_dir):
    root, _outside, fd = scope_dir
    state, envelope = in_flight()
    handle = open_in_scope(state, envelope, SCOPE, fd, "pages/new.txt", write=True)
    os.write(handle, b"x")
    os.close(handle)
    assert oct((root / "pages" / "new.txt").stat().st_mode & 0o777) == "0o600"
    with pytest.raises(ToolBoundaryError, match="never replaces"):
        open_in_scope(state, envelope, SCOPE, fd, "pages/one.txt", write=True)
    (root / "dangling").symlink_to(root / "nowhere")
    with pytest.raises(ToolBoundaryError):
        open_in_scope(state, envelope, SCOPE, fd, "dangling", write=True)
    read_state, read_envelope = in_flight(effect_class="read", idempotency="idempotent")
    with pytest.raises(ToolBoundaryError, match="read-only"):
        open_in_scope(read_state, read_envelope, SCOPE, fd, "pages/x.txt", write=True)


def test_side_channels_need_the_in_flight_envelope(scope_dir):
    _root, _outside, fd = scope_dir
    state, envelope = in_flight()
    finished = record_outcome(state, REQUEST, "succeeded")
    with pytest.raises(ToolBoundaryError, match="in-flight"):
        open_in_scope(finished, envelope, SCOPE, fd, "pages/one.txt")
    other_state, _other = in_flight()
    with pytest.raises(ToolBoundaryError, match="in-flight"):
        open_in_scope(other_state, envelope, SCOPE, fd, "pages/one.txt")
    with pytest.raises(ToolBoundaryError, match="framework-issued"):
        admit_tool_result(state, object(), "text/plain", b"x")


def policy():
    return freeze_egress_policy(granted_hosts=["docs.example.com"], product_origins=["app.local"],
                                max_redirects=2, max_response_bytes=1024)


def test_network_reaches_only_declared_hosts_through_the_broker():
    calls = []

    def transport(method, url, addresses, headers):
        calls.append((url, addresses))
        return 200, {}, b"ok"

    public = lambda host: ["93.184.216.34"]
    closed_state, closed = in_flight()
    with pytest.raises(ToolBoundaryError, match="no network scope"):
        admit_network(closed_state, closed, policy(), "GET", "https://docs.example.com/a",
                      resolver=public, transport=transport)
    state, envelope = in_flight(network_scopes=["docs.example.com"])
    result = admit_network(state, envelope, policy(), "GET", "https://docs.example.com/a",
                           resolver=public, transport=transport)
    assert result.body == b"ok" and calls == [("https://docs.example.com/a", ("93.184.216.34",))]
    with pytest.raises(ToolBoundaryError, match="outside"):
        admit_network(state, envelope, policy(), "GET", "https://evil.example.net/",
                      resolver=public, transport=transport)
    metadata = lambda host: ["169.254.169.254"]
    with pytest.raises(ToolBoundaryError, match="egress refused"):
        admit_network(state, envelope, policy(), "GET", "https://docs.example.com/a",
                      resolver=metadata, transport=transport)
    with pytest.raises(ToolBoundaryError, match="egress refused"):
        admit_network(state, envelope, policy(), "GET", "http://docs.example.com/a",
                      resolver=public, transport=transport)
    assert len(calls) == 1


def test_renderable_results_are_bounded_declared_and_sniffed(tmp_path):
    from app.adapters.documents import render_pdf
    from app.tests.test_document_tools import docx_spec

    state, envelope = in_flight(max_result_bytes=200_000)
    render_pdf(docx_spec(), tmp_path / "real.pdf")
    real = (tmp_path / "real.pdf").read_bytes()
    assert admit_tool_result(state, envelope, "application/pdf", real) == "application/pdf"
    assert admit_tool_result(state, envelope, "text/plain", "결과".encode()) == "text/plain"
    for active in ("text/html", "image/svg+xml", "application/javascript", "TEXT/HTML; charset=x"):
        with pytest.raises(ToolBoundaryError, match="active"):
            admit_tool_result(state, envelope, active, b"<script>alert(1)</script>")
    with pytest.raises(ToolBoundaryError, match="declared format"):
        admit_tool_result(state, envelope, "application/pdf", b"<html>not a pdf</html>")
    with pytest.raises(ToolBoundaryError, match="declared format"):
        admit_tool_result(state, envelope, "image/png", b"%PDF-1.7 disguised")
    with pytest.raises(ToolBoundaryError, match="not renderable"):
        admit_tool_result(state, envelope, "application/octet-stream", b"x")
    with pytest.raises(ToolBoundaryError, match="binary"):
        admit_tool_result(state, envelope, "text/plain", b"a\x00b")
    small_state, small = in_flight(max_result_bytes=3)
    with pytest.raises(ToolBoundaryError, match="byte cap"):
        admit_tool_result(small_state, small, "text/plain", b"four")
