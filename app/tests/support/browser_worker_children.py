"""Test-only children for the real-process browser/fetch qualification (T043).

- `serve-fetch <base> <fixture.json> --attachment-config=...` runs the unmodified fetch
  entrypoint (`app.workers.fetch_worker_main.main`);
- `serve-browser <base> --attachment-config=...` runs the unmodified browser entrypoint
  (`app.workers.browser_worker_main.main`) — the parent starts it inside a fresh network
  namespace (`unshare --net`) under the browser identity;
- `request <base>` reads a JSON plan on stdin, runs each case through
  `BrowserClient.for_worker` and prints one JSON line;
- `dispatch <base>` reads a JSON plan on stdin and runs a compiled graph whose `writer`
  node is bound to a browser tool through the real dispatcher and
  `BrowserAttemptTransport`, printing the sealed node result.

The parent test (root on Linux) starts each child under a fixed numeric identity, so the
kernel supplies every peer credential. The substitutions, all module-local:

- the fixed `cp-browser`, `cp-fetch` and `browser-fetch` profiles are relocated into owned
  temporary pair roots (as the document and credential children do);
- in the fetch child only, because this qualification has no outbound network: the
  resolver answers from the fixture's table (public-looking addresses, private and
  rebinding answers), the pinned transport trusts the fixture's test CA, connects to the
  fixture's port, and a pinned address is translated to the loopback fixture server only
  when the fixture table names it (any other address refuses before a socket is opened).
  The broker's policy, the transport's TLS/SNI checks and every byte limit are unchanged.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path


def profiles(base: Path):
    from app.workers import browser_channel, fetch_channel
    from app.workers.ipc_root import PairRootSpec

    result = {}
    for name, fixed in (("cp-browser", browser_channel.browser_channel),
                        ("cp-fetch", fetch_channel.control_fetch_channel),
                        ("browser-fetch", fetch_channel.browser_fetch_channel)):
        fixed_root, fixed_spec = fixed()
        root = PairRootSpec(pair_root=base / name, responder_uid=fixed_root.responder_uid,
                            responder_gid=fixed_root.responder_gid, pair_gid=fixed_root.pair_gid)
        result[name] = (root, dataclasses.replace(fixed_spec, pair_root=root.endpoint_path))
    return result


def _relocate(base: Path) -> None:
    from app.workers import browser_channel, fetch_channel

    found = profiles(base)
    browser_channel.browser_channel = lambda: found["cp-browser"]  # module-local profiles only
    fetch_channel.control_fetch_channel = lambda: found["cp-fetch"]
    fetch_channel.browser_fetch_channel = lambda: found["browser-fetch"]


def _fixture_network(path: Path) -> None:
    import socket
    import ssl

    from app.runtime import egress_transport
    from app.workers import fetch_service

    fixture = json.loads(path.read_text())
    answers = {host: [tuple(item) for item in sequence] for host, sequence in fixture["resolver"].items()}
    translated = set(fixture["public_addresses"])
    port, timeout = fixture["port"], fixture["timeout"]
    context = ssl.create_default_context(cafile=fixture["ca"])

    def resolver(host):
        sequence = answers.get(host)
        if not sequence:
            return ()
        return sequence.pop(0) if len(sequence) > 1 else sequence[0]

    def connect(self):
        if self._pinned_address not in translated:
            raise OSError("the fixture names no such address")
        raw = socket.create_connection(("127.0.0.1", self.port), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise

    egress_transport._PinnedConnection.connect = connect
    fetch_service.system_resolver = resolver
    fetch_service.pinned_transport_factory = lambda limit: egress_transport.make_pinned_transport(
        max_response_bytes=limit, ssl_context=context, timeout=timeout, port=port)


def _observation(value):
    summary = value.summary()
    summary.pop("sandbox")
    return summary


def _center_pixel(png: bytes):
    import io

    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        rgb = image.convert("RGB")
        return list(rgb.getpixel((rgb.size[0] // 2, rgb.size[1] // 2)))


def _client(base: Path, plan):
    from app.workers.browser_channel import BrowserClient, BrowserControlConfiguration

    return BrowserClient.for_worker(BrowserControlConfiguration(
        browser_pair_root=str(base / "cp-browser"), browser_requester_boot_id=plan["browser_boot"],
        fetch_pair_root=str(base / "cp-fetch"), fetch_requester_boot_id=plan["fetch_boot"]))


def _request(base: Path) -> int:
    from hashlib import sha256

    from app.workers.browser_channel import BrowserChannelError, BrowserRequest
    from app.workers.fetch_channel import BrowserGrant

    plan = json.loads(sys.stdin.read())
    client = _client(base, plan)
    results = {}
    for case in plan["cases"]:
        request = BrowserRequest(**case["request"])
        grant = BrowserGrant(**{key: tuple(item) if type(item) is list else item for key, item in case["grant"].items()})
        try:
            if case.get("skip_local_check"):
                # the worker-side enforcement, without control's own source pre-check
                identifier = client._fetch.register(grant)
                try:
                    value = client._exchange(request, identifier, grant)
                finally:
                    client._fetch.revoke(identifier)
            else:
                value = client.run(request, grant)
            entry = {"ok": True, **_observation(value), "sandbox": value.sandbox,
                     "digest_matches": sha256(value.output).hexdigest() == value.output_sha256}
            if value.op == "read":
                entry["text"] = value.output.decode("utf-8")
            if value.op == "screenshot":
                entry["center"] = _center_pixel(value.output)
        except BrowserChannelError as error:
            entry = {"ok": False, "code": error.code, "sent": error.sent}
        results[case["name"]] = entry
    sys.stdout.write(json.dumps(results, sort_keys=True) + "\n")
    sys.stdout.flush()
    return 0


def _dispatch(base: Path) -> int:
    import tempfile

    from app.runtime import browser_attempt_transport as bt
    from app.runtime import node_attempts as na
    from app.runtime import scheduler as sch
    from app.tests.test_browser_worker import browser_compiled, browser_run_subject
    from app.tests.test_scheduler_attempt_dispatch import build, handlers
    from app.workers.browser_channel import BrowserRequest
    from app.workers.fetch_channel import BrowserGrant

    plan = json.loads(sys.stdin.read())
    client = _client(base, plan)
    with tempfile.TemporaryDirectory(prefix="dt-t043-dispatch-") as directory:
        subject, run = browser_run_subject(Path(directory) / "ledger")
        compiled = browser_compiled(subject, plan["tool"])
        grant = BrowserGrant(**{key: tuple(item) if type(item) is list else item for key, item in plan["grant"].items()})
        transport = bt.BrowserAttemptTransport.build(
            domain_store=subject.domain, ledger=subject.ledger, compiled=compiled, node_id="writer",
            binding_id="source-read", client=client, request=BrowserRequest(**plan["request"]), grant=grant)
        dispatcher = na.NodeAttemptDispatcher.build(
            ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
            bindings={"writer": na.AttemptBinding.create(
                envelope_ref=subject.refs.envelope, profile_ref=subject.refs.profile,
                budget_policy_ref=subject.refs.budget, deadline_at_ms=10_000, lease_duration_ms=60_000,
                model_calls=1, tool_calls=1, node_visits=1, loop_rounds=0,
                output_bytes=transport.output_bytes_bound, candidates=0, api_microunits=None,
                principal=subject.principal, grant=subject.grant)},
            transport=transport)
        outcome = build(subject, run, dispatcher, handlers(subject, []), compiled=compiled).run()
        execution = sch.execution_identity(run.run_id, "writer", 0)
        ref = dict(outcome.result_refs).get(execution)
        value = {"result": None}
        if ref is not None:
            from app.domain.store import BlobRef

            content = subject.domain.get(ref).body["content"]
            blob = content["output"]["blob"] if content["output"] else None
            value["result"] = {"schema_version": content["schema_version"], "tool_id": content["tool_id"],
                               "operation": content["operation"], "final_url": content["observation"]["final_url"],
                               "title": content["observation"]["title"], "output_blob": blob}
            if blob is not None:
                value["output_text"] = subject.domain.read_blob(BlobRef.from_dict(blob),
                                                                purpose="operational").decode("utf-8")
        calls = subject.ledger.tool_calls_for_attempt(na.attempt_identity(run.run_id, "writer", 0, 0))
        value["tool_calls"] = [{"state": item["state"], "tool_id": item["tool_id"]} for item in calls]
    sys.stdout.write(json.dumps(value, sort_keys=True, default=str) + "\n")
    sys.stdout.flush()
    return 0


def main() -> int:
    role, base = sys.argv[1], Path(sys.argv[2])
    _relocate(base)
    if role == "serve-fetch":
        _fixture_network(Path(sys.argv[3]))
        from app.workers import fetch_worker_main

        return fetch_worker_main.main([sys.argv[0], *sys.argv[4:]])
    if role == "serve-browser":
        from app.workers import browser_worker_main

        return browser_worker_main.main([sys.argv[0], *sys.argv[3:]])
    if role == "dispatch":
        return _dispatch(base)
    return _request(base)


if __name__ == "__main__":
    raise SystemExit(main())
