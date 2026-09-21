"""The fixed inert shared gateway profile (Task51 G1; contracts/provider-owned-shared-gateway.md §4).

`gateway_channel()` is a pure declaration of the `cp-provider` topology: the
pair root, the channel and its identities, message tuples and bounds, agreeing
with the checked-in static topology file — which production never loads as
trust. No I/O, no listener, no generation, no override argument.
"""

import inspect
import json
from pathlib import Path

from app.workers import broker, ipc_root

ROOT = Path(__file__).resolve().parents[2]


def test_fixed_gateway_profile_is_literal_and_inert():
    from app.workers.gateway_channel import gateway_channel
    root, spec = gateway_channel()
    assert str(root.pair_root) == "/run/deeptwin/ipc/cp-provider"
    assert (root.responder_uid, root.responder_gid, root.pair_gid) == (20103, 20103, 21101)
    assert (spec.channel_id, spec.protocol_id) == ("cp-provider", "credential-gateway-v1")
    assert (spec.requester_service, spec.responder_service) == ("control", "provider")
    assert spec.request_direction == "control-to-provider"
    assert (spec.requester_uid, spec.requester_gid) == (20102, 20102)
    assert spec.pair_root == root.endpoint_path
    assert spec.socket_name == "worker.sock"
    assert spec.requester_message_types == ("credential_op",)
    assert spec.responder_message_types == ("credential_result",)
    assert (spec.max_frame_bytes, spec.max_in_flight, spec.max_queue_depth,
            spec.max_operation_ms) == (65536, 1, 16, 30000)


def test_the_profile_is_a_pure_factory_with_no_override_and_exact_types():
    from app.workers import gateway_channel as module
    assert module.PROFILE_ID == "provider-gateway-channel-v1"
    signature = inspect.signature(module.gateway_channel)
    assert list(signature.parameters) == []  # no path, peer, spec, callback or environment override
    root, spec = module.gateway_channel()
    assert type(root) is ipc_root.PairRootSpec and type(spec) is broker.ChannelSpec
    again_root, again_spec = module.gateway_channel()
    assert (again_root, again_spec) == (root, spec)
    # ownership and modes are the channel's own values, never a caller's
    assert (spec.responder_uid, spec.responder_gid, spec.pair_gid) == (20103, 20103, 21101)
    assert (spec.root_uid, spec.root_gid, spec.socket_uid, spec.socket_gid) == (20103, 21101, 20103, 21101)
    assert (spec.root_mode, spec.socket_mode) == (0o2710, 0o660)
    # the module performs no I/O and initializes nothing at import: only pure declarations
    source = inspect.getsource(module)
    for forbidden in ("os.open", "socket.", "bind_worker_listener", "initialize_pair_root",
                      "acquire_generation", "open(", "json.load"):
        assert forbidden not in source, forbidden


def test_the_profile_agrees_with_the_static_topology_file_without_loading_it_at_runtime():
    # the checked-in service ids are compared here as literal candidate values; production
    # code declares the profile itself and reads no file for it
    from app.workers.gateway_channel import gateway_channel
    static = json.loads((ROOT / "deploy" / "security" / "service-ids.json").read_text())
    entry = static["pairs"]["cp-provider"]
    root, spec = gateway_channel()
    assert entry["pair_gid"] == root.pair_gid == spec.pair_gid
    assert (entry["requester"], entry["responder"]) == (spec.requester_service, spec.responder_service)
    assert entry["root"] == str(root.pair_root)
    assert entry["socket"] == spec.socket_name
    assert (entry["socket_uid"], entry["socket_gid"]) == (spec.socket_uid, spec.socket_gid)
    assert int(entry["socket_mode"], 8) == spec.socket_mode
    assert int(entry["endpoint_mode"], 8) == spec.root_mode
    assert (entry["endpoint_uid"], entry["endpoint_gid"]) == (spec.root_uid, spec.root_gid)
    provider = static["services"]["provider"]
    assert (provider["uid"], provider["gid"]) == (root.responder_uid, root.responder_gid)
