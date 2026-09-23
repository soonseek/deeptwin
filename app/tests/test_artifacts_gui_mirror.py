"""T045: the artifact viewer must mirror the server's artifact contract.

app/static/artifacts.mjs renders the preview kinds the run-artifacts service
derives (app/services/run_artifacts.py) and bounds the list it accepts by the
service's own bound; a drift would let the viewer accept a shape the server
never serves or drop one it does. Every closed code the artifact routes can
answer has a message. The module must be a catalogued public asset, and the
supported boundary's page policy must admit the same-origin image the viewer
shows.
"""

import re
from pathlib import Path

from app.api.assets import MODULES
from app.api.web_boundary import SECURITY_HEADERS
from app.services import run_artifacts

_VIEWER = Path(__file__).resolve().parents[1] / "static" / "artifacts.mjs"
_SERVICE = Path(run_artifacts.__file__)


def _source():
    return _VIEWER.read_text(encoding="utf-8")


def test_the_viewer_is_a_catalogued_public_asset():
    assert MODULES["artifacts.mjs"] == "application/javascript"


def test_the_preview_kinds_mirror_the_service():
    match = re.search(r"export const PREVIEW_KINDS = Object\.freeze\(\[(.*?)\]\);", _source(), re.DOTALL)
    assert match is not None
    viewer = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    served = set(re.findall(r'"kind": "([a-z_]+)"', _SERVICE.read_text(encoding="utf-8")))
    served |= set(re.findall(r'_derived\("([a-z_]+)"', _SERVICE.read_text(encoding="utf-8")))
    assert viewer == served


def test_the_list_bound_mirrors_the_service():
    match = re.search(r"export const MAX_ARTIFACTS = (\d+);", _source())
    assert match is not None and int(match.group(1)) == run_artifacts.MAX_ARTIFACTS


def test_every_answerable_code_has_a_message():
    match = re.search(r"export const ERROR_MESSAGES = Object\.freeze\(\{(.*?)\}\);", _source(), re.DOTALL)
    assert match is not None
    messages = set(re.findall(r"^\s*([a-z_]+):", match.group(1), re.MULTILINE))
    # a missing range is never asked by the viewer (it reads previews and whole originals)
    assert run_artifacts.CODES - {"range_not_satisfiable"} <= messages


def test_the_page_policy_admits_same_origin_images_only():
    policy = SECURITY_HEADERS["content-security-policy"]
    assert "img-src 'self';" in policy and "default-src 'none'" in policy
