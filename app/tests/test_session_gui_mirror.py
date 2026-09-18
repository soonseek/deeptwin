"""T048/T025: the shell's supported-factory session client must mirror the
server's session contract.

app/static/session.mjs carries the session route, the CSRF header name, the
deployment base path grammar and the error partition it preserves on thrown
errors; a drift from app/api/session_routes.py, app/api/web_boundary.py or
the route partitions would let the shell read the token from a route the
supported factory does not serve, send a header the boundary ignores, or
mislabel a refusal. The module must also be a catalogued public asset, or
the supported factory cannot serve it to the shell.
"""

import re
from pathlib import Path

from app.api.assets import MODULES
from app.api.runs import STATUS as RUN_STATUS
from app.api.web_boundary import STATUS as SESSION_STATUS

_SESSION = Path(__file__).resolve().parents[1] / "static" / "session.mjs"


def _source():
    return _SESSION.read_text(encoding="utf-8")


def _mjs_const(name):
    match = re.search(rf"export const {name} = '([^']*)';", _source())
    assert match is not None, f"{name} is missing from session.mjs"
    return match.group(1)


def _mjs_list(name):
    match = re.search(rf"export const {name} = Object\.freeze\(\[(.*?)\]\);", _source(), re.DOTALL)
    assert match is not None, f"{name} is missing from session.mjs"
    return re.findall(r"'([a-z_]+)'", match.group(1))


def test_the_session_module_is_a_catalogued_public_asset():
    assert MODULES["session.mjs"] == MODULES["runtime.mjs"] == "application/javascript"
    assert _SESSION.is_file()


def test_the_session_route_and_header_mirror_the_supported_boundary():
    routes = (Path(__file__).resolve().parents[1] / "api" / "session_routes.py").read_text(encoding="utf-8")
    assert f'@router.api_route("{_mjs_const("SESSION_PATH")}", methods=["GET", "HEAD"])' in routes
    boundary = (Path(__file__).resolve().parents[1] / "api" / "web_boundary.py").read_text(encoding="utf-8")
    assert f'"{_mjs_const("CSRF_HEADER").lower()}"' in boundary


def test_the_client_wire_shape_is_admitted_by_the_real_supported_factory(tmp_path):
    # review closure: the string mirror alone would stay green on a router prefix, a
    # renamed session field or a header the boundary parses but no longer verifies —
    # so the client's exact route and header are exercised against the real factory
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from app.server import create_app
    from app.tests.test_web_owner_integration import (
        bootstrap_client,
        configured,
        headers,
    )

    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        session = client.get(profile.base_path + _mjs_const("SESSION_PATH").lstrip("/"),
                             headers=headers(profile))
        assert session.status_code == 200, session.text
        assert session.json()["state"] == "authenticated"
        assert type(session.json()["csrf_token"]) is str and session.json()["csrf_token"]
        # the token the client reads is the one a command must carry under the client's header name
        run_path = f"{profile.base_path}api/v1/runs/{uuid4()}/cancel"
        command = {"command_id": str(uuid4())}
        admitted = client.post(run_path, json=command,
                               headers={**headers(profile), _mjs_const("CSRF_HEADER"): session.json()["csrf_token"]})
        assert admitted.status_code == 404, admitted.text  # past the session: the run is unknown
        assert admitted.json()["code"] == "not_found"
        refused = client.post(run_path, json=command, headers=headers(profile))
        assert refused.status_code in {401, 403}, refused.text
        assert refused.json()["code"] in set(_mjs_list("ERROR_CODES"))
        assert csrf == session.json()["csrf_token"]


def test_the_error_partition_covers_the_run_routes_and_the_session_refusals():
    codes = set(_mjs_list("ERROR_CODES"))
    assert set(RUN_STATUS) <= codes
    assert set(SESSION_STATUS) <= codes
