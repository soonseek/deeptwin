"""Finite test-owned deployment for the T049 browser case (2026-09-25): the real
supported app, the real sandboxed browser worker, the real fetch service and the
isolated document worker, each a separate process under its own identity.

`launch --owned-dir DIR` (root, Linux) is what the browser test starts. It
- serves the local HTTPS fixture site (a test CA made by `openssl`, loopback only);
- initializes the three browser pair roots and starts the unmodified fetch entrypoint as
  20104 and the unmodified browser entrypoint as 20105 inside a fresh network namespace
  (`unshare --net`), exactly as the root-only qualification in test_browser_worker.py;
- starts `serve` (below) as the control identity 20102 (pair groups 21104/21102) on a
  fixed port and relays its announcement; the line `restart` on stdin SIGKILLs that
  server process and starts a fresh one on the same data, port and workers (a crash and
  restart — the ledger, checkpoints and records are all that carry over).

`serve` (20102) starts the document worker harness as its own child process, builds the
app with the product's `BrowserToolset` over the real `cp-browser`/`cp-fetch` pair roots
and the code-owned test executor of `app/tests/support/runtime_e2e.py`, and once: sets up
the owner (the browser test logs in), creates the owner's browser grant through its route
(pure navigation to the three fixture pages), approves a design whose tool permissions is
that grant record (the real producers of `browser_grant_chain.approved_environment`), and
seeds what the owner's routes cannot create (two stored graphs bound to the grant record,
a budget policy, the execution envelope/profile refs). It announces `E2E_SEED=` /
`E2E_URL=`. No browser grant is ever supplied in code: each dispatch builds it from the
persisted record and re-checks it against the run's approved tool permissions.

The fetch child's only substitutions are the test-support ones of
`app/tests/support/browser_worker_children.py` (fixture resolver table, test CA, fixture
port, public-looking → loopback translation). No model, no outbound network, no paid call.
"""
import argparse
import base64
import http.server
import json
import os
import secrets
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY))
from app.domain.refs import EntityRef  # noqa: E402

CONTROL, FETCH, BROWSER = 20_102, 20_104, 20_105
BOOTS = {"control": "control-boot-t049", "browser": "browser-boot-t049"}
PUBLIC = "93.184.216.34"
READY_SECONDS = 90


def _environment():
    return {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPOSITORY), "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8", "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}


def _die_with_parent():
    """preexec: SIGKILL this child when its parent dies (runs after the uid switch)."""

    import ctypes

    ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG


def _write(path, value, mode=0o644):
    path.write_text(json.dumps(value))
    os.chmod(path, mode)
    return path


def chromium():
    import glob

    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    found = sorted(glob.glob(os.path.join(root, "chromium_headless_shell-*", "chrome-linux", "headless_shell")))
    return found[-1] if found else None


# --- the fixture site (root process, loopback only) --------------------------------------

class _Site(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        self.server.seen.append((host, self.path))
        found = self.server.pages.get(self.path) if host == "granted.test" else None
        if found is None:
            media, body, status = "text/plain", b"no", 404
        else:
            (media, body), status = found, 200
        if self.path == "/slow-once" and not self.server.slowed:
            self.server.slowed = True  # the first read outlasts its deadline; later ones are prompt
            time.sleep(6)
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass


def _site(directory: Path):
    from app.tests.support.runtime_e2e import site_pages

    def openssl(*args):
        subprocess.run(["openssl", *args], cwd=directory, check=True, capture_output=True)

    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem", "-days", "2",
            "-subj", "/CN=deeptwin t049 test ca")
    (directory / "san.cnf").write_text("subjectAltName=DNS:granted.test\n")
    openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "leaf.key", "-out", "leaf.csr", "-subj",
            "/CN=granted.test")
    openssl("x509", "-req", "-in", "leaf.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial", "-out",
            "leaf.pem", "-days", "2", "-extfile", "san.cnf")
    os.chmod(directory, 0o755)
    os.chmod(directory / "ca.pem", 0o644)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    httpd.daemon_threads = True
    httpd.seen, httpd.pages, httpd.slowed = [], site_pages(), False
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(directory / "leaf.pem", directory / "leaf.key")
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


class _Worker:
    """A worker child whose stderr JSON events are watched for readiness."""

    def __init__(self, argv, ready, **options):
        self.process = subprocess.Popen(argv, cwd=REPOSITORY, env=_environment(), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **options)
        self.lines = []
        self._changed = threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()
        limit = time.monotonic() + READY_SECONDS
        with self._changed:
            while not any(f'"event": "{ready}"' in line for line in self.lines):
                if self.process.poll() is not None or time.monotonic() > limit:
                    raise RuntimeError(f"worker never logged {ready}: {self.lines[-10:]}")
                self._changed.wait(0.5)

    def _read(self):
        for raw in self.process.stderr:
            with self._changed:
                self.lines.append(raw.decode(errors="replace").rstrip("\n"))
                self._changed.notify_all()

    def stop(self):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(5)


def _relay(stream, sink):
    for raw in stream:
        sink.write(raw.decode(errors="replace"))
        sink.flush()


def launch(owned: Path) -> int:
    from app.tests.support.browser_worker_children import profiles
    from app.workers import browser_channel, fetch_channel, ipc_root

    path = chromium()
    if os.geteuid() != 0 or path is None:
        raise RuntimeError("the T049 deployment needs root (real identities) and a headless Chromium")
    os.chmod(owned, 0o755)
    site_dir, base, app_dir = owned / "site", owned / "ipc", owned / "app"
    for directory in (site_dir, base, app_dir):
        directory.mkdir()
    os.chmod(base, 0o755)
    os.chown(app_dir, CONTROL, CONTROL)
    os.chmod(app_dir, 0o700)
    httpd = _site(site_dir)
    workers, state = [], {"server": None, "stopping": False}
    try:
        for name, (root, _spec) in profiles(base).items():
            (base / name).mkdir(mode=0o700)
            ipc_root.initialize_pair_root(root)
        config = base / "config"
        config.mkdir(mode=0o755)
        profile_root = base / "browser-profile"
        profile_root.mkdir(mode=0o700)
        os.chown(profile_root, BROWSER, BROWSER)
        _write(config / "fixture.json", {"resolver": {"granted.test": [[PUBLIC]]}, "public_addresses": [PUBLIC],
                                         "port": httpd.server_address[1], "timeout": 10,
                                         "ca": str(site_dir / "ca.pem")})
        _write(config / "fetch.json", {
            "schema": fetch_channel.ATTACHMENT_SCHEMA, "control_pair_root": str(base / "cp-fetch"),
            "control_requester_boot_id": BOOTS["control"], "browser_pair_root": str(base / "browser-fetch"),
            "browser_requester_boot_id": BOOTS["browser"]})
        _write(config / "browser.json", {
            "schema": browser_channel.WORKER_ATTACHMENT_SCHEMA, "pair_root": str(base / "cp-browser"),
            "requester_boot_id": BOOTS["control"], "fetch_pair_root": str(base / "browser-fetch"),
            "fetch_requester_boot_id": BOOTS["browser"], "chromium_path": path,
            "profile_root": str(profile_root)})
        children = [sys.executable, "-B", "-m", "app.tests.support.browser_worker_children"]
        workers.append(_Worker([*children, "serve-fetch", str(base), str(config / "fixture.json"),
                                f"--attachment-config={config / 'fetch.json'}"], "fetch_ready",
                               user=FETCH, group=FETCH, extra_groups=[21102, 21110],
                               preexec_fn=_die_with_parent))
        workers.append(_Worker(["unshare", "--net", "--", "setpriv", f"--reuid={BROWSER}", f"--regid={BROWSER}",
                                "--groups=21104,21110", "--no-new-privs", "--inh-caps=-all", "--",
                                *children, "serve-browser", str(base),
                                f"--attachment-config={config / 'browser.json'}"], "browser_ready"))
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        def start():
            server = subprocess.Popen(
                [sys.executable, "-B", str(Path(__file__).resolve()), "serve", "--owned-dir", str(owned),
                 "--port", str(port)], cwd=REPOSITORY, env=_environment(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, user=CONTROL, group=CONTROL,
                extra_groups=[21104, 21102], preexec_fn=_die_with_parent)
            threading.Thread(target=_relay, args=(server.stdout, sys.stdout), daemon=True).start()
            threading.Thread(target=_relay, args=(server.stderr, sys.stderr), daemon=True).start()
            state["server"] = server

        def stop_server(sig=signal.SIGTERM):
            server = state["server"]
            if server is not None and server.poll() is None:
                server.send_signal(sig)
                try:
                    server.wait(10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(5)

        def terminate(_signum, _frame):
            state["stopping"] = True
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, terminate)
        start()
        for line in sys.stdin:
            if line.strip() == "restart":
                stop_server(signal.SIGKILL)  # a crash: nothing is flushed or handed over
                print("E2E_RESTARTED", flush=True)
                start()
        return 0
    finally:
        server = state["server"]
        if server is not None and server.poll() is None:
            server.kill()
            server.wait(5)
        for worker in reversed(workers):
            worker.stop()
        httpd.shutdown()
        httpd.server_close()


# --- the app server (control identity) ----------------------------------------------

def seal(app, profile, capability):
    """What the owner's routes cannot create, plus the owner's own grant chain: the owner
    is set up here (the browser later logs in), creates the browser grant through the
    `browser_grants.create` route, and approves a design whose `tool_permissions` is that
    grant record through the real producers; the runs' environment is that approval's
    sealed environment record, and both graphs bind the grant record as their grant."""

    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.runtime.budgets import BudgetPolicy
    from app.services.design_persistence import encode_design_refs
    from app.tests.support.browser_grant_chain import approved_environment
    from app.tests.support.runtime_e2e import e2e_graph, grant_command
    from app.tests.test_graph_contract import parse
    from app.tests.test_server_api_v1 import immutable
    from app.tests.test_web_owner_integration import bootstrap_client, bound_request, headers

    client = TestClient(app, base_url=profile.http_origin)  # in-process; no lifespan, no socket
    csrf = bootstrap_client(client, profile, capability)
    created = client.post(profile.base_path + "api/v1/browser-grants", headers=headers(profile, csrf),
                          json=grant_command())
    if created.status_code != 201:
        raise RuntimeError(f"the owner's grant was not created: {created.status_code}")
    grant_ref = EntityRef.from_dict(created.json()["ref"])
    request = bound_request(app, client, profile, csrf)
    environment = approved_environment(SimpleNamespace(app=app, request=request), grant_ref)
    domain = app.state.domain_store
    roots = domain.roots()
    policy = BudgetPolicy.create(
        profile="execution", provider_mode="subscription", max_model_calls=1, max_tool_calls=8,
        max_node_visits=24, max_loop_rounds=1, max_output_bytes=16 * 1024 * 1024, max_concurrency=4,
        max_wall_seconds=3_600, max_candidates=1)
    graphs = {name: immutable(domain, roots, "graph", content={
        "design_kind": "functional_graph",
        "design": encode_design_refs(parse(e2e_graph(grant_ref, recovery=name == "recovery")).as_dict())}).ref.as_dict()
        for name in ("main", "recovery")}
    return {"graphs": graphs,
            "work_revision_ref": immutable(domain, roots, "work_revision").ref.as_dict(),
            "environment_ref": environment.as_dict(),
            "budget_policy_ref": immutable(domain, roots, "budget_policy",
                                           content=policy.domain_content()).ref.as_dict(),
            "grant_ref": grant_ref.as_dict(),
            "executor": {"envelope": immutable(domain, roots, "execution_envelope").ref.as_dict(),
                         "profile": immutable(domain, roots, "runtime_profile").ref.as_dict(),
                         "grant": grant_ref.as_dict()}}


def serve(owned: Path, port: int) -> int:
    import uvicorn

    from app.operations.session_root import initialize_session_root
    from app.operations.setup import OriginProfile, build_bootstrap_configuration, derive_capability_verifier
    from app.server import create_app
    from app.tests.support.browser_worker_children import _relocate
    from app.tests.support.document_worker_harness import process_client
    from app.tests.support.runtime_e2e import RuntimeE2EExecutor
    from app.workers.browser_channel import BrowserControlConfiguration

    base, app_dir = owned / "ipc", owned / "app"
    _relocate(base)  # the fixed cp-browser/cp-fetch profiles, relocated to the owned pair roots
    worker_socket = app_dir / "document.sock"
    if worker_socket.exists():
        worker_socket.unlink()  # the previous server's worker died with it
    secret = secrets.token_bytes(32)
    worker = subprocess.Popen([sys.executable, "-B", "-m", "app.tests.support.document_worker_harness",
                               str(worker_socket)], cwd=REPOSITORY, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, preexec_fn=_die_with_parent)
    worker.stdin.write(secret.hex().encode() + b"\n")
    worker.stdin.close()
    if worker.stdout.readline().strip() != b"ready":
        raise RuntimeError("document worker did not start")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(128)
    profile = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=port)
    capability = base64.urlsafe_b64encode(b"T" * 32).rstrip(b"=").decode()
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=derive_capability_verifier(capability))
    if not (app_dir / "root").exists():
        initialize_session_root(app_dir / "root", profile=profile, recovery_epoch=1,
                                expected_uid=os.getuid(), expected_gid=os.getgid())
    codec = process_client(worker_socket, secret)
    executor = RuntimeE2EExecutor(codec=codec, state_path=app_dir / "contexts.json")
    browser = BrowserControlConfiguration(
        browser_pair_root=str(base / "cp-browser"), browser_requester_boot_id=BOOTS["control"],
        fetch_pair_root=str(base / "cp-fetch"), fetch_requester_boot_id=BOOTS["control"])
    app = create_app(app_dir / "data", deployment_config=configuration, session_root_dir=app_dir / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(), run_executor=executor,
                     document_worker=codec, browser_worker=browser)
    seed_path = app_dir / "seed.json"
    if seed_path.exists():
        seed = json.loads(seed_path.read_text())
    else:
        seed = seal(app, profile, capability)
        seed_path.write_text(json.dumps(seed))
    executor.bind(app, seed["executor"], seed["graphs"])
    public = {key: seed[key] for key in ("graphs", "work_revision_ref", "environment_ref",
                                           "budget_policy_ref", "grant_ref")}
    print(f"E2E_SEED={json.dumps(public, separators=(',', ':'))}", flush=True)
    print(f"E2E_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False,
                                      timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()
        worker.kill()
        worker.wait(5)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("launch", "serve"))
    parser.add_argument("--owned-dir", required=True, type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    owned = args.owned_dir.resolve(strict=True)
    if args.mode == "launch":
        if not owned.is_dir() or any(owned.iterdir()):
            raise RuntimeError("Fixture requires its newly owned empty directory")
        return launch(owned)
    return serve(owned, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
