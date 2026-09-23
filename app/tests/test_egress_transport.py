"""T043 transport half: the pinned HTTPS transport behind the egress broker.

A local TLS server with a test CA (made with the openssl CLI) stands in for a
granted destination. The transport connects only to the pinned address it is
handed, binds SNI and certificate checking to the URL's hostname, never follows a
redirect or a proxy, and abandons a body as soon as it would exceed the limit.
"""

import http.server
import shutil
import socket
import ssl
import subprocess
import threading

import pytest

from app.runtime.egress import EgressBrokerError, broker_fetch, freeze_egress_policy
from app.runtime.egress_transport import make_pinned_transport

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl CLI")

HOST = "granted.example"
BIG = 256 * 1024


def _openssl(*args, cwd):
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    root = tmp_path_factory.mktemp("pki")
    _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem",
             "-days", "2", "-subj", "/CN=deeptwin test ca", cwd=root)
    (root / "san.cnf").write_text(f"subjectAltName=DNS:{HOST}\n")
    _openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "leaf.key", "-out", "leaf.csr",
             "-subj", f"/CN={HOST}", cwd=root)
    _openssl("x509", "-req", "-in", "leaf.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial",
             "-out", "leaf.pem", "-days", "2", "-extfile", "san.cnf", cwd=root)
    return root


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.server.seen.append({"path": self.path, "headers": dict(self.headers)})
        if self.path == "/redirect":
            self._reply(302, b"", {"Location": "/final"})
        elif self.path == "/declared-big":
            self._reply(200, b"x" * BIG)
        elif self.path == "/chunked-big":
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                for _ in range(BIG // 1024):
                    self.wfile.write(b"400\r\n" + b"y" * 1024 + b"\r\n")
                    self.server.sent += 1024
                self.wfile.write(b"0\r\n\r\n")
            except OSError:
                pass  # the client abandoned the transfer
        else:
            self._reply(200, b"hello " + self.path.encode())

    do_HEAD = do_GET

    def _reply(self, status, body, headers=None):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


@pytest.fixture
def server(pki):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.seen, httpd.sent, httpd.sni = [], 0, []
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(pki / "leaf.pem", pki / "leaf.key")
    context.sni_callback = lambda _sock, name, _ctx: httpd.sni.append(name)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    thread.join(5)


def client_context(pki):
    return ssl.create_default_context(cafile=str(pki / "ca.pem"))


def transport_for(pki, server, limit=64 * 1024):
    return make_pinned_transport(max_response_bytes=limit, ssl_context=client_context(pki),
                                 port=server.server_address[1], timeout=5)


def test_connects_to_the_pinned_address_with_sni_bound_to_the_hostname(pki, server, monkeypatch):
    # proxy variables are never consulted, and no name is ever resolved
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:1")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("the transport resolved a name"))
    transport = transport_for(pki, server)
    status, headers, body = transport("GET", f"https://{HOST}/doc?q=1", ("127.0.0.1",), {"Accept": "text/plain"})
    assert (status, body) == (200, b"hello /doc?q=1")
    assert headers["content-length"] == str(len(body))
    assert server.sni == [HOST]
    assert server.seen[0]["headers"]["Host"] == f"{HOST}:{server.server_address[1]}"  # bare on 443
    assert server.seen[0]["headers"]["Accept-Encoding"] == "identity"


def test_a_certificate_for_another_name_refuses(pki, server):
    transport = transport_for(pki, server)
    with pytest.raises(EgressBrokerError, match="certificate"):
        transport("GET", "https://other.example/", ("127.0.0.1",), {})


def test_an_untrusted_or_non_verifying_context_is_refused(pki, server):
    with pytest.raises(EgressBrokerError, match="certificate"):
        make_pinned_transport(max_response_bytes=1024, port=server.server_address[1], timeout=5)(
            "GET", f"https://{HOST}/", ("127.0.0.1",), {})
    lax = ssl.create_default_context()
    lax.check_hostname = False
    lax.verify_mode = ssl.CERT_NONE
    with pytest.raises(EgressBrokerError, match="verifying"):
        make_pinned_transport(max_response_bytes=1024, ssl_context=lax)


def test_redirects_are_returned_to_the_broker_never_followed(pki, server):
    status, headers, _body = transport_for(pki, server)("GET", f"https://{HOST}/redirect", ("127.0.0.1",), {})
    assert status == 302 and headers["location"] == "/final"
    assert [item["path"] for item in server.seen] == ["/redirect"]


def test_a_declared_oversized_body_refuses_before_reading(pki, server):
    with pytest.raises(EgressBrokerError, match="byte limit"):
        transport_for(pki, server)("GET", f"https://{HOST}/declared-big", ("127.0.0.1",), {})


def test_a_streamed_oversized_body_is_abandoned_mid_transfer(pki, server):
    limit = 8 * 1024
    with pytest.raises(EgressBrokerError, match="byte limit"):
        transport_for(pki, server, limit)("GET", f"https://{HOST}/chunked-big", ("127.0.0.1",), {})
    assert server.sent < BIG  # the transfer never completed


def test_head_reads_no_body(pki, server):
    status, _headers, body = transport_for(pki, server)("HEAD", f"https://{HOST}/x", ("127.0.0.1",), {})
    assert (status, body) == (200, b"")


def test_an_unreachable_pinned_address_falls_through_only_to_other_pinned_ones(pki, server):
    closed = socket.socket()
    closed.bind(("127.0.0.2", 0))
    closed.close()
    transport = transport_for(pki, server)
    assert transport("GET", f"https://{HOST}/a", ("127.0.0.3", "127.0.0.1"), {})[0] == 200
    with pytest.raises(EgressBrokerError, match="no pinned address"):
        transport("GET", f"https://{HOST}/a", ("127.0.0.3",), {})


def test_the_broker_revalidates_each_hop_and_the_transport_only_sees_pinned_addresses(pki, server):
    public = "93.184.216.34"
    policy = freeze_egress_policy(granted_hosts=[HOST], product_origins=["deeptwin.local"],
                                  max_redirects=2, max_response_bytes=64 * 1024)
    inner = transport_for(pki, server)
    handed = []

    def loopback_for_test(method, url, addresses, headers):
        handed.append(addresses)
        assert addresses == (public,)  # exactly what the broker admitted
        return inner(method, url, ("127.0.0.1",), headers)

    result = broker_fetch(policy, "GET", f"https://{HOST}/redirect",
                          resolver=lambda host: [public], transport=loopback_for_test)
    assert result.final_url == f"https://{HOST}/final" and result.body == b"hello /final"
    assert result.redirect_chain == (f"https://{HOST}/redirect",) and len(handed) == 2
