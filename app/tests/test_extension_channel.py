"""Task 25 slice 1a: fixed extension worker channel values and the fixed
image argv parser (T018-foundation transport values for the worker-private
probe; contracts/extension-candidates.md SocketMount `broker_pair`,
deployment-prepare-sources.md control identity, extension-lineage-values §5
argv structure).

Every value is derived from `deployment.contracts.slot` and
`deployment.contracts.CONTROL`; nothing here is I/O, authority or a live
channel — the values are inert until the worker probe service exists.
"""

from pathlib import Path

import pytest

from app.deployment.contracts import CONTROL, IPC_ROOT, slot
from app.workers import broker
from app.workers.extension_channel import (
    EXTENSION_CHANNEL_PROFILE,
    ExtensionChannelError,
    extension_channel,
    parse_worker_argv,
)
from app.workers.ipc_root import PairRootSpec

INSTANCE = "0123456789abcdef0123456789abcdef"


def test_channel_values_derive_from_the_slot_and_control_identities():
    root, spec = extension_channel(instance_id=INSTANCE, slot_number=7)
    expected = slot(INSTANCE, 7)
    assert type(root) is PairRootSpec and type(spec) is broker.ChannelSpec
    assert root.pair_root == IPC_ROOT / expected["socket_mount"]["mount_id"]
    assert root.pair_root == Path(expected["socket_mount"]["container_path"])
    assert (root.responder_uid, root.responder_gid, root.pair_gid) == (
        expected["uid"],
        expected["gid"],
        expected["pair_gid"],
    )
    # the channel's pair root is the endpoint below the outer root, never the root
    assert spec.pair_root == root.endpoint_path
    assert spec.channel_id == expected["channel_id"]
    assert spec.responder_service == expected["service_identity"]
    assert spec.requester_service == CONTROL["service_identity"]
    assert (
        spec.request_direction
        == f"{CONTROL['service_identity']}-to-{expected['service_identity']}"
    )
    assert spec.protocol_id == expected["protocol_id"]
    assert (spec.requester_uid, spec.requester_gid) == (CONTROL["uid"], CONTROL["gid"])
    assert (spec.responder_uid, spec.responder_gid) == (
        expected["uid"],
        expected["gid"],
    )
    assert spec.pair_gid == expected["pair_gid"]
    assert spec.socket_name == expected["socket_name"]
    assert (spec.root_uid, spec.root_gid) == (expected["uid"], expected["pair_gid"])
    assert (spec.socket_uid, spec.socket_gid) == (expected["uid"], expected["pair_gid"])
    assert (spec.root_mode, spec.socket_mode) == (0o2710, 0o660)


def test_the_channel_profile_constants_are_explicit_and_route_binding_compatible():
    _root, spec = extension_channel(instance_id=INSTANCE, slot_number=1)
    assert EXTENSION_CHANNEL_PROFILE == "extension-channel-profile-v1"
    assert spec.requester_message_types == (
        "extension-artifact-v1",
        "extension-request-v1",
    )
    assert spec.responder_message_types == (
        "extension-artifact-v1",
        "extension-result-v1",
    )
    assert spec.max_frame_bytes == broker.MAX_FRAME_BYTES == 65_536
    # the slot's protocol identity and the broker's extension profile agree
    assert spec.protocol_id == broker.EXTENSION_PROTOCOL_ID
    assert spec.requester_message_types == broker.EXTENSION_REQUESTER_MESSAGE_TYPES
    assert spec.responder_message_types == broker.EXTENSION_RESPONDER_MESSAGE_TYPES
    broker._require_extension_profile(spec)
    assert (spec.max_in_flight, spec.max_queue_depth, spec.max_operation_ms) == (
        1,
        16,
        30_000,
    )
    # the same inputs always produce equal values: routing facts, not state
    assert extension_channel(instance_id=INSTANCE, slot_number=1) == (
        extension_channel(instance_id=INSTANCE, slot_number=1)
    )
    assert (
        extension_channel(instance_id=INSTANCE, slot_number=2)[1].channel_id
        != spec.channel_id
    )


@pytest.mark.parametrize(
    "instance_id", ["", "abc", INSTANCE.upper(), INSTANCE + "0", 12, None]
)
def test_the_instance_grammar_is_the_slot_grammar(instance_id):
    with pytest.raises(ExtensionChannelError):
        extension_channel(instance_id=instance_id, slot_number=1)


@pytest.mark.parametrize("slot_number", [0, 17, -1, 1.0, "1", None, True])
def test_the_slot_number_is_bounded_and_exact(slot_number):
    with pytest.raises(ExtensionChannelError):
        extension_channel(instance_id=INSTANCE, slot_number=slot_number)


def test_the_fixed_argv_parses_exactly_five_elements_and_ignores_argv0():
    for argv0 in ("/usr/local/bin/worker", "worker", "anything"):
        assert parse_worker_argv(
            [argv0, "--instance-id", INSTANCE, "--slot-number", "16"]
        ) == (INSTANCE, 16)
    assert parse_worker_argv(
        ["w", "--instance-id", INSTANCE, "--slot-number", "1"]
    ) == (INSTANCE, 1)


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["w"],
        ["w", "--instance-id", INSTANCE, "--slot-number"],
        ["w", "--instance-id", INSTANCE, "--slot-number", "1", "--extra"],
        ["w", "--slot-number", "1", "--instance-id", INSTANCE],  # fixed order
        ["w", "--instance-id", INSTANCE.upper(), "--slot-number", "1"],
        ["w", "--instance-id", INSTANCE, "--slot-number", "01"],  # no leading zeros
        ["w", "--instance-id", INSTANCE, "--slot-number", "0"],
        ["w", "--instance-id", INSTANCE, "--slot-number", "17"],
        ["w", "--instance-id", INSTANCE, "--slot-number", "+1"],
        ["w", "--instance-id", INSTANCE, "--slot-number", " 1"],
        ["w", "--instance-id", INSTANCE, "--slot-number", "1.0"],
        ["w", "--instance-id=" + INSTANCE, "--slot-number", "1"],
        ["w", "--instance-id", INSTANCE, "--slot-number", 1],
        [
            "w",
            "--instance-id",
            INSTANCE,
            "--slot-number",
            "9" * 5000,
        ],  # never int() first
        ["w", "--instance-id", INSTANCE, "--slot-number", "00"],
        ["w", "--instance-id", INSTANCE, "--slot-number", "1_0"],
        ["w", "--instance-id", INSTANCE, "--slot-number", "1\n"],
        ["w", "--instance-id", INSTANCE, "--slot-number", "١"],  # Arabic-Indic one
        ["w", "--instance-id", INSTANCE, "--slot-number", "１"],  # fullwidth one
        ["w", "--instance-id", INSTANCE, "--slot-number", b"1"],
        ["w", "--instance-id", INSTANCE.encode(), "--slot-number", "1"],
        ["w", "--instance-id", INSTANCE[:-1] + "\udcff", "--slot-number", "1"],
        ("w", "--instance-id", INSTANCE, "--slot-number", "1"),  # a list, not a tuple
        "w --instance-id x --slot-number 1",
        None,
    ],
)
def test_the_fixed_argv_refuses_every_other_shape(argv):
    with pytest.raises(ExtensionChannelError):
        parse_worker_argv(argv)


def test_every_slot_channel_satisfies_the_listener_rule_and_a_route_binding():
    # the plan names listener._validate_pair_channel as the rule owner and
    # requires the profile to be WorkerRouteBinding-satisfiable: both are
    # exercised here rather than restated field by field
    from app.domain.refs import EntityRef
    from app.runtime.worker_coordinator import WorkerRouteBinding
    from app.tests.test_alternatives import ref
    from app.workers import ipc_root, listener

    profile = EntityRef.from_dict(ref("runtime_profile", 1))  # a synthetic fixture ref
    for number in range(1, 17):
        root, spec = extension_channel(instance_id=INSTANCE, slot_number=number)
        listener._validate_pair_channel(root, spec)
        assert (spec.root_mode, spec.socket_mode) == (ipc_root.ENDPOINT_MODE, 0o660)
        binding = WorkerRouteBinding(
            profile_ref=profile,
            channel_spec=spec,
            request_message_type="extension-request-v1",
            response_message_types=("extension-result-v1",),
            artifact_stream_message_type="extension-artifact-v1",
        )
        assert binding.channel_spec is spec


def test_the_channel_digest_is_stable_for_a_fixed_slot():
    # hash stability (proposal §5): any silent drift in a derived field changes it
    _root, spec = extension_channel(instance_id=INSTANCE, slot_number=3)
    digest = broker._spec_digest(spec)
    assert digest == broker._spec_digest(
        extension_channel(instance_id=INSTANCE, slot_number=3)[1]
    )
    assert digest != broker._spec_digest(
        extension_channel(instance_id=INSTANCE, slot_number=4)[1]
    )
    assert digest != broker._spec_digest(
        extension_channel(instance_id="f" * 32, slot_number=3)[1]
    )


def test_the_module_imports_no_api_static_or_server_code():
    # checked in a fresh interpreter: the test process itself may already
    # have loaded the web layer for other suites
    import subprocess
    import sys

    probe = (
        "import sys; import app.workers.extension_channel; "
        "print(sorted(name for name in sys.modules "
        "if name == 'app.server' or name.startswith(('app.api', 'app.static'))))"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=Path(__file__).resolve().parents[2],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert completed.stdout.strip() == "[]"
