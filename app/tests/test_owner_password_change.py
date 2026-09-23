"""T025 tail: the owner changes their password and ends other sessions (api.md §1:
`/session` password change and revoke-others; sessions rotate after a password change).

A password change re-verifies the current password, seals the next authenticator
revision and advances the account's auth epoch in one writer: every earlier session —
other browsers and this one's old cookie — stops authenticating, and this browser
receives a fresh session. The old password no longer logs in; the new one does.
Revoke-others ends every other session and keeps this one. Wrong current passwords
are the uniform 401; a too-short or unchanged new password is refused before any work.
"""

from fastapi.testclient import TestClient

from app.server import create_app
from app.tests.test_web_owner_integration import bootstrap_client, configured, headers

OLD = "synthetic owner passphrase"
NEW = "a different synthetic passphrase"


def login(client, profile, password):
    return client.post(profile.base_path + "session/login", headers=headers(profile),
                       json={"login_name": "owner", "password": password})


def snapshot(client, profile):
    return client.get(profile.base_path + "api/v1/snapshot", headers=headers(profile)).status_code


class Browser:
    """A second browser on the same server: its own cookie jar over the one test client."""

    def __init__(self, client, name):
        self.client, self.name, self.jar = client, name, None

    def __enter__(self):
        self.saved = list(self.client.cookies.jar)
        self.client.cookies.clear()
        for cookie in self.jar or ():
            self.client.cookies.jar.set_cookie(cookie)
        return self.client

    def __exit__(self, *_exc):
        self.jar = list(self.client.cookies.jar)
        self.client.cookies.clear()
        for cookie in self.saved:
            self.client.cookies.jar.set_cookie(cookie)


def test_a_password_change_ends_every_old_session_and_rotates_this_one(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        second = Browser(client, "second")
        with second as other:
            assert login(other, profile, OLD).status_code == 200
            assert snapshot(other, profile) == 200
        name = app.state.owner_authority.cookie_name
        old_cookie = [cookie.value for cookie in client.cookies.jar if cookie.name == name]
        changed = client.post(profile.base_path + "session/password", headers=headers(profile, csrf),
                              json={"current_password": OLD, "new_password": NEW})
        assert changed.status_code == 200, changed.text
        assert changed.json()["state"] == "authenticated"
        assert [cookie.value for cookie in client.cookies.jar if cookie.name == name] != old_cookie
        assert snapshot(client, profile) == 200  # this browser continues on its rotated session
        with second as other:
            assert snapshot(other, profile) == 401  # every earlier session ended
            assert login(other, profile, OLD).status_code == 401


def test_the_new_password_logs_in_after_a_change(tmp_path):
    # its own server: login attempts share one bounded rate bucket per source and account
    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        changed = client.post(profile.base_path + "session/password", headers=headers(profile, csrf),
                              json={"current_password": OLD, "new_password": NEW})
        assert changed.status_code == 200, changed.text
        client.cookies.clear()
        assert login(client, profile, NEW).status_code == 200
        assert snapshot(client, profile) == 200


def test_wrong_short_or_unchanged_passwords_are_refused(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        path = profile.base_path + "session/password"
        wrong = client.post(path, headers=headers(profile, csrf),
                            json={"current_password": "not the owner passphrase", "new_password": NEW})
        assert wrong.status_code == 401
        short = client.post(path, headers=headers(profile, csrf), json={"current_password": OLD, "new_password": "short"})
        assert short.status_code == 400
        same = client.post(path, headers=headers(profile, csrf), json={"current_password": OLD, "new_password": OLD})
        assert same.status_code == 400
        extra = client.post(path, headers=headers(profile, csrf),
                            json={"current_password": OLD, "new_password": NEW, "login_name": "x"})
        assert extra.status_code == 400
        no_csrf = client.post(path, headers=headers(profile), json={"current_password": OLD, "new_password": NEW})
        assert no_csrf.status_code in {401, 403}
        assert snapshot(client, profile) == 200 and login(client, profile, OLD).status_code == 200


def test_revoke_others_keeps_only_this_session(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        second = Browser(client, "second")
        with second as other:
            assert login(other, profile, OLD).status_code == 200
        revoked = client.post(profile.base_path + "session/revoke-others", headers=headers(profile, csrf), json={})
        assert revoked.status_code == 200, revoked.text
        assert revoked.json() == {"state": "revoked_others", "revoked": 1}
        assert snapshot(client, profile) == 200
        with second as other:
            assert snapshot(other, profile) == 401
        again = client.post(profile.base_path + "session/revoke-others", headers=headers(profile, csrf), json={})
        assert again.json()["revoked"] == 0
