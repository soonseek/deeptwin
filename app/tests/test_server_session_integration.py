"""HTTP integration for the superseded pre-ADR-009 loopback bootstrap boundary."""

from fastapi.testclient import TestClient

from app.server import create_app


ORIGIN = "http://127.0.0.1:4193"
FETCH = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}


def exchange(client, application):
    bootstrap = application.state.local_sessions.mint_bootstrap()
    response = client.post(
        "/api/session/bootstrap",
        json={"capability": bootstrap.capability},
        headers=FETCH,
    )
    assert response.status_code == 201
    return bootstrap, response.json(), response


def test_only_one_use_post_exchanges_development_bootstrap_for_strict_cookie(tmp_path):
    application = create_app(tmp_path, port=4193, understanding_provider_ready=False)
    with TestClient(application, base_url=ORIGIN) as client:
        assert client.get("/api/bootstrap", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 403
        bootstrap, body, response = exchange(client, application)
        assert set(body) == {"csrf_token", "expires_at"}
        assert bootstrap.capability not in response.text
        cookie = response.headers["set-cookie"]
        assert "deeptwin_local_session=" in cookie
        assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie
        replay = client.post(
            "/api/session/bootstrap",
            json={"capability": bootstrap.capability},
            headers=FETCH,
        )
        assert replay.status_code == 403
        # Replay revokes the session that the capability created.
        assert client.get("/api/bootstrap", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 403


def test_authenticated_get_and_exact_csrf_mutation_use_the_same_session(tmp_path):
    application = create_app(tmp_path, port=4193, understanding_provider_ready=False)
    with TestClient(application, base_url=ORIGIN) as client:
        _, session, _ = exchange(client, application)
        bootstrap = client.get("/api/bootstrap", headers={"Sec-Fetch-Site": "same-origin"})
        assert bootstrap.status_code == 200
        assert set(bootstrap.json()) == {"works", "capabilities", "providers"}
        assert client.post("/api/works", json={"text": "x"},
                           headers={"Sec-Fetch-Site": "same-origin"}).status_code == 403
        accepted = client.post(
            "/api/works", json={"text": "x"},
            headers={**FETCH, "X-CSRF-Token": session["csrf_token"]},
        )
        assert accepted.status_code == 201


def test_authenticated_reload_adds_a_bounded_page_csrf_without_breaking_an_open_tab(tmp_path):
    application = create_app(tmp_path, port=4193, understanding_provider_ready=False)
    with TestClient(application, base_url=ORIGIN) as client:
        _, session, _ = exchange(client, application)
        refreshed = client.get("/api/session/csrf", headers={"Sec-Fetch-Site": "same-origin"})
        assert refreshed.status_code == 200
        replacement = refreshed.json()["csrf_token"]
        assert replacement != session["csrf_token"]
        assert client.post(
            "/api/works", json={"text": "first tab"},
            headers={**FETCH, "X-CSRF-Token": session["csrf_token"]},
        ).status_code == 201
        assert client.post(
            "/api/works", json={"text": "reloaded tab"},
            headers={**FETCH, "X-CSRF-Token": replacement},
        ).status_code == 201


def test_bootstrap_and_api_reject_ambiguous_or_wrong_local_transport(tmp_path):
    application = create_app(tmp_path, port=4193, understanding_provider_ready=False)
    with TestClient(application, base_url=ORIGIN) as client:
        bootstrap = application.state.local_sessions.mint_bootstrap()
        for headers in (
            {"Origin": "https://evil.example", "Sec-Fetch-Site": "same-origin"},
            {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"},
            {"Origin": ORIGIN},
            {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin", "Host": "localhost:4194"},
        ):
            response = client.post(
                "/api/session/bootstrap", json={"capability": bootstrap.capability}, headers=headers,
            )
            assert response.status_code == 403
        duplicate = client.post(
            "/api/session/bootstrap", json={"capability": bootstrap.capability},
            headers=[("Origin", ORIGIN), ("Origin", ORIGIN),
                     ("Sec-Fetch-Site", "same-origin")],
        )
        assert duplicate.status_code == 403


def test_static_shell_is_public_but_never_leaks_a_bootstrap_or_csrf_secret(tmp_path):
    application = create_app(tmp_path, port=4193, understanding_provider_ready=False)
    with TestClient(application, base_url=ORIGIN) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "csrf" not in response.text.casefold()
        assert "bootstrap=" not in response.text.casefold()
        assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
