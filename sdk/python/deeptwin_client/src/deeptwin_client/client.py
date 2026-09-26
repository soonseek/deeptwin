"""HTTPS single-bearer transport and the typed ``/api/v1`` calls."""

import base64
import http.client
import ipaddress
import json
import re
import socket
import ssl
from urllib.parse import urlencode, urlsplit

API_PREFIX = "/api/v1"

_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]{1,256}$")
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_BEARER_PREFIX = "dt_sc_"
_MAX_RESPONSE_BYTES = 1_048_576
_ERROR_TEXT = 256


class ClientConfigurationError(ValueError):
    """The client was configured or called with a value it refuses before any I/O."""


class TransportError(ConnectionError):
    """TLS, connection or wire failure; the message never carries the credential."""


class ApiError(Exception):
    """The server answered with a non-success status and its closed error body."""

    def __init__(self, status, code, retryability, correlation_id):
        super().__init__(f"DeepTwin API error {status}: {code}")
        self.status = status
        self.code = code
        self.retryability = retryability
        self.correlation_id = correlation_id


class Response:
    __slots__ = ("body", "status")

    def __init__(self, status, body):
        self.status = status
        self.body = body

    def __repr__(self):
        return f"Response(status={self.status})"


def _plain_segment(value):
    return _SEGMENT.fullmatch(value) is not None and value not in {".", ".."}


def _segment(value):
    if type(value) is not str or not _plain_segment(value):
        raise ClientConfigurationError("path segment is invalid")
    return value


def _check_bearer(value):
    if type(value) is not str or len(value) != 49 or not value.startswith(_BEARER_PREFIX):
        raise ClientConfigurationError("bearer credential has the wrong form")
    encoded = value[len(_BEARER_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(encoded + "=")
    except (ValueError, UnicodeError):
        raise ClientConfigurationError("bearer credential has the wrong form") from None
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != encoded:
        raise ClientConfigurationError("bearer credential has the wrong form")


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate member")
        result[key] = value
    return result


def _short(value):
    return value[:_ERROR_TEXT] if type(value) is str else None


def _list_query(limit, after):
    query = {}
    if limit is not None:
        if type(limit) is not int or not 1 <= limit <= 1_000:
            raise ClientConfigurationError("limit is invalid")
        query["limit"] = str(limit)
    if after is not None:
        query["after"] = _segment(after)
    return query


class _AddressedHTTPSConnection(http.client.HTTPSConnection):
    """Dial a fixed IP address while TLS verification and Host stay on the origin name."""

    def __init__(self, host, port, *, address, timeout, context):
        super().__init__(host, port, timeout=timeout, context=context)
        self._address = address
        self._tls_context = context

    def connect(self):
        raw = socket.create_connection((self._address, self.port), self.timeout)
        try:
            self.sock = self._tls_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class DeepTwinClient:
    """One HTTPS origin, one bearer credential, verified TLS."""

    __slots__ = ("_address", "_authorization", "_context", "_host", "_port", "_timeout")

    def __init__(self, base_url, *, bearer, ca_file=None, timeout=10.0, connect_address=None):
        """``connect_address`` optionally names the IP literal to dial (like curl's
        ``--resolve``); certificate verification and the Host header still use the
        origin's name, so it never weakens TLS."""
        if type(base_url) is not str:
            raise ClientConfigurationError("base URL must be an https origin")
        try:
            parsed = urlsplit(base_url)
            port = parsed.port or 443
        except ValueError:
            raise ClientConfigurationError("base URL must be an https origin") from None
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"} or _HOST.fullmatch(parsed.hostname) is None):
            raise ClientConfigurationError("base URL must be an https origin")
        if type(timeout) not in {int, float} or not 0 < timeout <= 300:
            raise ClientConfigurationError("timeout is invalid")
        if connect_address is not None:
            try:
                connect_address = str(ipaddress.ip_address(connect_address))
            except ValueError:
                raise ClientConfigurationError("connect address must be an IP literal") from None
        _check_bearer(bearer)
        context = ssl.create_default_context(cafile=None if ca_file is None else str(ca_file))
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        self._host, self._port = parsed.hostname, port
        self._authorization = "Bearer " + bearer
        self._context = context
        self._timeout = float(timeout)
        self._address = connect_address

    def __repr__(self):
        return f"DeepTwinClient(https://{self._host}:{self._port})"

    def __reduce__(self):
        raise TypeError("a DeepTwin client holds a credential and is not serializable")

    # -- transport --------------------------------------------------------------------

    def request(self, method, path, *, query=None, body=None):
        if method not in {"GET", "POST"}:
            raise ClientConfigurationError("method is not supported")
        if (type(path) is not str or not path.startswith(API_PREFIX + "/")
                or not all(_plain_segment(part) for part in path[1:].split("/"))):
            raise ClientConfigurationError("path must be a plain /api/v1 path")
        if query:
            path += "?" + urlencode(sorted(query.items()))
        headers = {"Authorization": self._authorization, "Accept": "application/json"}
        payload = None
        if body is not None:
            if method != "POST" or type(body) is not dict:
                raise ClientConfigurationError("only a POST carries a JSON object body")
            payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"),
                                 allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif method == "POST":
            payload = b""
        if self._address is None:
            connection = http.client.HTTPSConnection(
                self._host, self._port, timeout=self._timeout, context=self._context)
        else:
            connection = _AddressedHTTPSConnection(
                self._host, self._port, address=self._address, timeout=self._timeout,
                context=self._context)
        failure = None
        try:
            connection.request(method, path, body=payload, headers=headers)
            headers = None
            response = connection.getresponse()
            status = response.status
            media = (response.getheader("Content-Type") or "").split(";", 1)[0].strip()
            data = response.read(_MAX_RESPONSE_BYTES + 1)
        except ssl.SSLError as error:
            failure = f"TLS verification or handshake failed: {type(error).__name__}"
        except (OSError, http.client.HTTPException) as error:
            failure = f"connection failed: {type(error).__name__}"
        finally:
            headers = None
            connection.close()
        if failure is not None:
            raise TransportError(failure)
        if len(data) > _MAX_RESPONSE_BYTES:
            raise TransportError("response exceeds the client bound")
        parsed = None
        if media == "application/json" and data:
            try:
                parsed = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates)
            except (UnicodeError, ValueError):
                raise TransportError("response is not valid JSON") from None
        if status >= 400:
            fields = parsed if type(parsed) is dict else {}
            raise ApiError(status, _short(fields.get("code")), _short(fields.get("retryability")),
                           _short(fields.get("correlation_id")))
        if not 200 <= status < 300:
            raise TransportError(f"unexpected status {status}")
        return Response(status, parsed)

    # -- core ---------------------------------------------------------------------------

    def snapshot(self):
        return self.request("GET", API_PREFIX + "/snapshot").body

    def read_command(self, command_id):
        return self.request("GET", f"{API_PREFIX}/commands/{_segment(command_id)}").body

    def submit_command(self, command):
        return self.request("POST", API_PREFIX + "/commands", body=command).body

    # -- extensions (read surface) ---------------------------------------------------

    def list_extension_candidates(self, *, limit=None, after=None):
        return self.request("GET", API_PREFIX + "/extensions/candidates",
                            query=_list_query(limit, after)).body

    def read_extension_candidate(self, candidate_id):
        return self.request("GET", f"{API_PREFIX}/extensions/candidates/{_segment(candidate_id)}").body

    def list_extension_installations(self, *, limit=None, after=None):
        return self.request("GET", API_PREFIX + "/extensions/installations",
                            query=_list_query(limit, after)).body

    def list_extension_bindings(self, *, limit=None, after=None):
        return self.request("GET", API_PREFIX + "/extensions/bindings",
                            query=_list_query(limit, after)).body

    def read_extension_binding(self, slot_key_digest):
        return self.request("GET", f"{API_PREFIX}/extensions/bindings/{_segment(slot_key_digest)}").body
