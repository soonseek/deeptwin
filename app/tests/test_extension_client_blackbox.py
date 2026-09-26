"""T087 alternate client: the installed `deeptwin-client` against the real TLS server.

The client wheel is built from its own package root and installed with pip into a fresh
venv; it runs with `python -I` from a directory outside the repository, where
`import app` fails. The server is `create_app` on the portable HTTPS profile, served by
uvicorn over real TLS in its own process (tests/fixtures/portable_https_server.py), so
calls reach the route surface actually composed through the frozen router-composition
seam.

What this proves: the owner creates scoped service clients from a browser session over
TLS (Secure cookie, CSRF; each secret returned once), and the installed client's bearer
is admitted on the routes whose descriptor declares `browser_session_or_service_bearer`
(`/api/v1/snapshot` under `snapshot.read`, `/api/v1/events` under `events.read`), with
the same projection and cursor the browser path reads at the same point. A credential
without the route's scope gets 403; browser-session-only routes (the extension reads
among them) give the uniform 401; a revoked secret gets 401 on the next call; an
untrusted chain and an `http://` origin are refused; and no secret or canary appears in
the client's or the server's output.

Still open (T025/T087): the contracts name no service-client command scope, so no bearer
command route exists and command receipt/event-order parity across restart and
concurrency is not shown; extension reads await T087's own contribution and scope.
"""

import base64
import http.client
import json
import os
import select
import signal
import socket
import ssl
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from app.tests.support.sdk_packages import (
    REPOSITORY,
    build,
    fresh_environment,
    pip_install,
    run_isolated,
)

pytestmark = pytest.mark.skipif(
    subprocess.run(["openssl", "version"], capture_output=True, check=False).returncode != 0,
    reason="openssl is required to make the throwaway test CA",
)

# the portable profile requires a dotted DNS name; nothing resolves it here, so every
# caller dials 127.0.0.1 while TLS verification and Host stay on this name
HOST = "deeptwin.test"
CAPABILITY = base64.urlsafe_b64encode(b"K" * 32).rstrip(b"=").decode()
CANARY_RAW = b"deeptwin-t087-canary-not-issued!"
CANARY = "dt_sc_" + base64.urlsafe_b64encode(CANARY_RAW).rstrip(b"=").decode()


def _openssl(directory, *args):
    subprocess.run(["openssl", *args], cwd=directory, check=True, capture_output=True, timeout=60)


def _certificates(directory):
    curve = ("-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes")
    _openssl(directory, "req", "-x509", *curve, "-keyout", "ca.key", "-out", "ca.pem", "-days", "2",
             "-subj", "/CN=deeptwin t087 test ca",
             "-addext", "basicConstraints=critical,CA:TRUE",
             "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    (directory / "leaf.cnf").write_text(
        "subjectAltName=DNS:" + HOST + "\nbasicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n"
        "authorityKeyIdentifier=keyid\nsubjectKeyIdentifier=hash\n")
    _openssl(directory, "req", *curve, "-keyout", "leaf.key", "-out", "leaf.csr", "-subj", "/CN=" + HOST)
    _openssl(directory, "x509", "-req", "-in", "leaf.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
             "-CAcreateserial", "-out", "leaf.pem", "-days", "2", "-extfile", "leaf.cnf")
    return directory / "ca.pem", directory / "leaf.pem", directory / "leaf.key"


@pytest.fixture(scope="module")
def client_python(tmp_path_factory):
    work = tmp_path_factory.mktemp("client-env")
    wheel = build("deeptwin-client", "wheel", work / "dist")
    python = fresh_environment(work / "venv")
    pip_install(python, wheel, cwd=work)
    return python, work


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    certs = tmp_path_factory.mktemp("tls")
    ca, leaf, key = _certificates(certs)
    owned = tmp_path_factory.mktemp("server")
    logs = tmp_path_factory.mktemp("server-logs")
    stderr_path = logs / "stderr.txt"
    stderr_file = open(stderr_path, "wb")  # noqa: SIM115 - held open for the server process lifetime
    process = subprocess.Popen(
        [sys.executable, "-B", str(REPOSITORY / "app" / "tests" / "fixtures" / "portable_https_server.py"),
         "--owned-dir", str(owned), "--certificate", str(leaf), "--private-key", str(key), "--host-name", HOST],
        cwd=REPOSITORY, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_file,
        start_new_session=True,
    )
    try:
        process.stdin.write(CAPABILITY.encode() + b"\n")
        process.stdin.close()
        ready, _, _ = select.select([process.stdout], [], [], 60)
        line = process.stdout.readline().decode().strip() if ready else ""
        if not line.startswith("PORTABLE_HTTPS_URL="):
            raise AssertionError("server did not start: "
                                 + stderr_path.read_bytes()[-4000:].decode(errors="replace"))
        url = line.split("=", 1)[1]
        port = int(url.rsplit(":", 1)[1])
        context = ssl.create_default_context(cafile=str(ca))
        deadline = time.monotonic() + 30
        while True:
            try:
                with (socket.create_connection(("127.0.0.1", port), timeout=2) as raw,
                      context.wrap_socket(raw, server_hostname=HOST)):
                    break
            except OSError:
                if time.monotonic() > deadline or process.poll() is not None:
                    raise
                time.sleep(0.1)
        yield {"url": url, "ca": ca, "context": context, "port": port,
               "output": lambda: stderr_path.read_bytes()}
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(5)
        stderr_file.close()


def _owner(server, method, path, body=None, cookie=None, csrf=None):
    headers = {"Origin": server["url"], "Sec-Fetch-Site": "same-origin", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if cookie is not None:
        headers["Cookie"] = cookie
    if csrf is not None:
        headers["X-DeepTwin-CSRF"] = csrf
    raw = socket.create_connection(("127.0.0.1", server["port"]), timeout=30)
    connection = http.client.HTTPSConnection(HOST, server["port"], timeout=30, context=server["context"])
    connection.sock = server["context"].wrap_socket(raw, server_hostname=HOST)
    try:
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.headers), json.loads(response.read() or b"null")
    finally:
        connection.close()


_CLIENT_SCRIPT = r"""
import json, sys
from pathlib import Path
try:
    import app  # noqa: F401
except ModuleNotFoundError:
    pass
else:
    raise SystemExit("the client environment can import the repository core")
import deeptwin_client
from deeptwin_client import ApiError, ClientConfigurationError, DeepTwinClient, TransportError
url, ca = sys.argv[1], sys.argv[2]
reader, events_only = sys.stdin.readline().strip(), sys.stdin.readline().strip()
assert "site-packages" in Path(deeptwin_client.__file__).parts, deeptwin_client.__file__
report = {"file": deeptwin_client.__file__}


def outcome(call):
    try:
        response = call()
    except ApiError as error:
        return {"status": error.status, "code": error.code, "text": str(error)}
    return {"status": "admitted", "body": response}


client = DeepTwinClient(url, bearer=reader, ca_file=ca, connect_address="127.0.0.1")
report["repr"] = repr(client)
report["snapshot"] = outcome(client.snapshot)
report["events"] = outcome(lambda: client.request("GET", "/api/v1/events").body)
for name, call in {
    "extensions.candidates.list": client.list_extension_candidates,
    "extensions.installations.list": client.list_extension_installations,
    "extensions.bindings.list": client.list_extension_bindings,
    "commands.read": lambda: client.read_command("00000000-0000-4000-8000-000000000000"),
    "service-clients.list": lambda: client.request("GET", "/api/v1/service-clients").body,
}.items():
    report[name] = outcome(call)
scoped = DeepTwinClient(url, bearer=events_only, ca_file=ca, connect_address="127.0.0.1")
report["wrong_scope.snapshot"] = outcome(scoped.snapshot)
report["wrong_scope.events"] = outcome(lambda: scoped.request("GET", "/api/v1/events").body)
untrusted = DeepTwinClient(url, bearer=reader, connect_address="127.0.0.1")
try:
    untrusted.snapshot()
except TransportError as error:
    report["untrusted"] = str(error)
try:
    DeepTwinClient(url.replace("https://", "http://"), bearer=reader, ca_file=ca)
except ClientConfigurationError as error:
    report["plaintext"] = str(error)
print(json.dumps(report))
"""


def _creation(scopes):
    return {"client_id": str(uuid.uuid4()), "name": "installed client", "scopes": scopes,
            "allowed_network_profile": "portable_https", "expires_at": int(time.time()) + 3_600}


def _run_client(python, server, cwd, secrets):
    code, stdout, stderr = run_isolated(python, _CLIENT_SCRIPT, cwd=cwd,
                                        args=(server["url"], str(server["ca"])),
                                        stdin="\n".join(secrets) + "\n")
    assert code == 0, "installed client failed"
    return json.loads(stdout), (stdout, stderr)


def test_installed_client_bearer_is_admitted_on_declared_routes_and_matches_the_browser(
        server, client_python, tmp_path):
    python, _ = client_python
    status, headers, body = _owner(server, "POST", "/session/bootstrap", {
        "login_name": "owner", "password": "synthetic owner passphrase", "raw_capability_b64u": CAPABILITY})
    assert status == 201, body
    cookie = headers["set-cookie"].split(";", 1)[0]
    csrf = body["csrf_token"]
    assert "Secure" in headers["set-cookie"]
    for path in ("/api/v1/snapshot", "/api/v1/extensions/candidates",
                 "/api/v1/extensions/installations", "/api/v1/extensions/bindings"):
        owner_status, _, _ = _owner(server, "GET", path, cookie=cookie)
        assert owner_status == 200, path
    # the owner issues two scoped clients in the browser session; CSRF is required
    refused, _, _ = _owner(server, "POST", "/api/v1/service-clients", _creation(["snapshot.read"]),
                           cookie=cookie)
    assert refused == 403
    issued_secrets, records = [], {}
    for name, scopes in (("reader", ["snapshot.read", "events.read"]), ("events_only", ["events.read"])):
        status, _, issued = _owner(server, "POST", "/api/v1/service-clients", _creation(scopes),
                                   cookie=cookie, csrf=csrf)
        assert status == 201 and issued["secret_available_once"] is True
        records[name] = issued["client"]
        issued_secrets.append(issued.pop("secret"))
    status, _, listing = _owner(server, "GET", "/api/v1/service-clients", cookie=cookie)
    assert status == 200
    assert {item["client_id"] for item in listing["items"]} == {
        record["client_id"] for record in records.values()}
    assert not any(secret in json.dumps(listing) for secret in issued_secrets)
    _, _, browser_snapshot = _owner(server, "GET", "/api/v1/snapshot", cookie=cookie)
    _, _, browser_events = _owner(server, "GET", "/api/v1/events", cookie=cookie)

    outside = tmp_path / "outside-repository"
    outside.mkdir()
    assert REPOSITORY not in outside.parents
    report, outputs = _run_client(python, server, outside, issued_secrets)
    assert Path(report["file"]).is_relative_to(python.parent.parent)
    # admitted on the declared bearer routes, with the browser's own projection and cursor
    assert report["snapshot"] == {"status": "admitted", "body": browser_snapshot}
    assert report["events"] == {"status": "admitted", "body": browser_events}
    # a valid credential without the route's declared scope
    assert report["wrong_scope.snapshot"]["status"] == 403
    assert report["wrong_scope.snapshot"]["code"] == "access_denied"
    assert report["wrong_scope.events"]["status"] == "admitted"
    # browser-session-only routes never admit a bearer
    for name in ("extensions.candidates.list", "extensions.installations.list",
                 "extensions.bindings.list", "commands.read", "service-clients.list"):
        assert report[name]["status"] == 401, (name, report[name])
        assert report[name]["code"] == "unauthenticated", (name, report[name])
    assert report["untrusted"].startswith("TLS verification or handshake failed")
    assert report["plaintext"] == "base URL must be an https origin"

    # revocation takes effect on the next request
    status, _, revoked = _owner(
        server, "POST", f"/api/v1/service-clients/{records['reader']['client_id']}/revoke",
        {"expected_revision": 1}, cookie=cookie, csrf=csrf)
    assert status == 200 and revoked["state"] == "revoked"
    after, after_outputs = _run_client(python, server, outside, issued_secrets)
    assert after["snapshot"]["status"] == 401 and after["snapshot"]["code"] == "unauthenticated"
    assert after["events"]["status"] == 401
    assert after["wrong_scope.events"]["status"] == "admitted"

    # plaintext to the TLS listener carries only the non-secret canary and is never served
    try:
        plain = http.client.HTTPConnection("127.0.0.1", server["port"], timeout=10)
        plain.request("GET", "/api/v1/snapshot", headers={"Host": f"{HOST}:{server['port']}",
                                                           "Authorization": "Bearer " + CANARY})
        plain_status = plain.getresponse().status
    except (OSError, http.client.HTTPException):
        plain_status = None
    assert plain_status != 200

    server_output = server["output"]().decode(errors="replace")
    for text in (*outputs, *after_outputs, server_output):
        for secret in (*issued_secrets, CANARY, CANARY_RAW.decode()):
            assert secret not in text


def test_canary_bearer_is_well_formed_but_never_issued():
    assert len(CANARY_RAW) == 32 and len(CANARY) == 49
