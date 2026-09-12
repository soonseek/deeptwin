"""Test-only client that enters through the real one-use local HTTP session."""

from urllib.parse import urlsplit

from fastapi.testclient import TestClient as _TestClient


class LocalTestClient(_TestClient):
    csrf_token = None

    def __enter__(self):
        entered = super().__enter__()
        capability = self.app.state.local_sessions.mint_bootstrap()
        origin = str(self.base_url).rstrip("/")
        response = self.post(
            "/api/session/bootstrap",
            json={"capability": capability.capability},
            headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"},
        )
        if response.status_code != 201:
            super().__exit__(None, None, None)
            raise AssertionError("Test client could not establish a real local session")
        self.csrf_token = response.json()["csrf_token"]
        return entered

    def request(self, method, url, *, headers=None, **kwargs):
        values = dict(headers or {})
        values.setdefault("Sec-Fetch-Site", "same-origin")
        path = urlsplit(str(url)).path
        if method.upper() not in {"GET", "HEAD", "OPTIONS"} and path != "/api/session/bootstrap":
            values.setdefault("Origin", str(self.base_url).rstrip("/"))
        return super().request(method, url, headers=values, **kwargs)

