"""T087 alternate client: the installed `deeptwin-client` against the real TLS server.

The client wheel is built from its own package root and installed with pip into a fresh
venv; it runs with `python -I` from a directory outside the repository, where
`import app` fails. The server is `create_app` on the portable HTTPS profile, served by
uvicorn over real TLS in its own process (tests/fixtures/portable_https_server.py), so
calls reach the route surface actually composed through the frozen router-composition
seam.

What this proves today: TLS with certificate/host verification against the test CA,
the exact Host the portable profile requires, a refused untrusted chain, plaintext
refused before I/O, and that the owner-session path answers the same mounted routes the
client calls. What it records: no route in that composition admits a service-client
bearer yet (every contribution is `browser_session`; T025 has not mounted the bearer
path), so the installed client's bearer calls receive the uniform pre-auth denial.
Browser/client parity of receipts, revisions, authority and event order across restart
and concurrency waits on that T025 path.
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
    process = subprocess.Popen(
        [sys.executable, "-B", str(REPOSITORY / "app" / "tests" / "fixtures" / "portable_https_server.py"),
         "--owned-dir", str(owned), "--certificate", str(leaf), "--private-key", str(key), "--host-name", HOST],
        cwd=REPOSITORY, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        process.stdin.write(CAPABILITY.encode() + b"\n")
        process.stdin.close()
        ready, _, _ = select.select([process.stdout], [], [], 60)
        line = process.stdout.readline().decode().strip() if ready else ""
        if not line.startswith("PORTABLE_HTTPS_URL="):
            raise AssertionError("server did not start: " + process.stderr.read1(4000).decode(errors="replace"))
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
        yield {"url": url, "ca": ca, "context": context}
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(5)


def _owner(server, method, path, body=None, cookie=None):
    headers = {"Origin": server["url"], "Sec-Fetch-Site": "same-origin", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if cookie is not None:
        headers["Cookie"] = cookie
    port = int(server["url"].rsplit(":", 1)[1])
    raw = socket.create_connection(("127.0.0.1", port), timeout=30)
    connection = http.client.HTTPSConnection(HOST, port, timeout=30, context=server["context"])
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
url, ca, bearer = sys.argv[1], sys.argv[2], sys.stdin.readline().strip()
assert "site-packages" in Path(deeptwin_client.__file__).parts, deeptwin_client.__file__
report = {"file": deeptwin_client.__file__}
client = DeepTwinClient(url, bearer=bearer, ca_file=ca, connect_address="127.0.0.1")
report["repr"] = repr(client)
calls = {
    "snapshot": client.snapshot,
    "extensions.candidates.list": client.list_extension_candidates,
    "extensions.installations.list": client.list_extension_installations,
    "extensions.bindings.list": client.list_extension_bindings,
}
for name, call in calls.items():
    try:
        call()
    except ApiError as error:
        report[name] = {"status": error.status, "code": error.code, "text": str(error)}
    else:
        report[name] = {"status": "admitted"}
untrusted = DeepTwinClient(url, bearer=bearer, connect_address="127.0.0.1")
try:
    untrusted.snapshot()
except TransportError as error:
    report["untrusted"] = str(error)
try:
    DeepTwinClient(url.replace("https://", "http://"), bearer=bearer, ca_file=ca)
except ClientConfigurationError as error:
    report["plaintext"] = str(error)
print(json.dumps(report))
"""


def test_installed_client_reaches_mounted_tls_routes_where_the_owner_path_is_served(
        server, client_python, tmp_path):
    python, _ = client_python
    # the owner-session path over the same TLS listener: the routes the client calls are mounted
    status, headers, body = _owner(server, "POST", "/session/bootstrap", {
        "login_name": "owner", "password": "synthetic owner passphrase", "raw_capability_b64u": CAPABILITY})
    assert status == 201, body
    cookie = headers["set-cookie"].split(";", 1)[0]
    assert "Secure" in headers["set-cookie"]
    for path in ("/api/v1/snapshot", "/api/v1/extensions/candidates",
                 "/api/v1/extensions/installations", "/api/v1/extensions/bindings"):
        owner_status, _, _ = _owner(server, "GET", path, cookie=cookie)
        assert owner_status == 200, path

    outside = tmp_path / "outside-repository"
    outside.mkdir()
    assert REPOSITORY not in outside.parents
    code, stdout, stderr = run_isolated(python, _CLIENT_SCRIPT, cwd=outside,
                                        args=(server["url"], str(server["ca"])), stdin=CANARY + "\n")
    assert code == 0, stderr[-4000:]
    report = json.loads(stdout)
    assert Path(report["file"]).is_relative_to(python.parent.parent)
    # no mounted route admits a service-client bearer yet: each answers the uniform pre-auth
    # denial the browser path gives an absent session (T025 bearer mounting is still open)
    for name in ("snapshot", "extensions.candidates.list", "extensions.installations.list",
                 "extensions.bindings.list"):
        assert report[name]["status"] == 401, (name, report[name])
        assert report[name]["code"] == "unauthenticated", (name, report[name])
    assert report["untrusted"].startswith("TLS verification or handshake failed")
    assert report["plaintext"] == "base URL must be an https origin"
    assert CANARY not in stdout and CANARY not in stderr
    assert CANARY_RAW.decode() not in stdout


def test_canary_bearer_is_well_formed_but_never_issued():
    assert len(CANARY_RAW) == 32 and len(CANARY) == 49
