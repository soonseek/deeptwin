"""T048: the run panel's run source must mirror the public snapshot contract.

app/static/run-list.mjs lists the runs the public snapshot records so the
owner can pick one for the run panel to observe; a drift from the snapshot's
version string (app/api/routes.py) or from the runtime ledger's durable run
phases would let the shell accept a snapshot the server never serves or
mislabel a run's durable phase. The module must also be a catalogued public
asset, or the supported factory cannot serve it.
"""

import re
from pathlib import Path

from app.api.assets import MODULES
from app.runtime.ledger import RUN_PHASES

_RUN_LIST = Path(__file__).resolve().parents[1] / "static" / "run-list.mjs"
_ROUTES = Path(__file__).resolve().parents[1] / "api" / "routes.py"


def _source():
    return _RUN_LIST.read_text(encoding="utf-8")


def _mjs_const(name):
    match = re.search(rf"export const {name} = '([^']*)';", _source())
    assert match is not None, f"{name} is missing from run-list.mjs"
    return match.group(1)


def _mjs_list(name):
    match = re.search(rf"export const {name} = Object\.freeze\(\[(.*?)\]\);", _source(), re.DOTALL)
    assert match is not None, f"{name} is missing from run-list.mjs"
    return re.findall(r"'([a-z_]+)'", match.group(1))


def test_the_run_list_module_is_a_catalogued_public_asset():
    assert MODULES["run-list.mjs"] == "application/javascript"
    assert _RUN_LIST.is_file()


def test_the_snapshot_version_mirrors_the_public_snapshot_route():
    version = _mjs_const("SNAPSHOT_VERSION")
    assert f'"snapshot_version": "{version}"' in _ROUTES.read_text(encoding="utf-8")


def test_the_durable_run_phases_mirror_the_runtime_ledger():
    assert set(_mjs_list("RUN_PHASES")) == set(RUN_PHASES)


def test_the_run_bound_mirrors_the_snapshot_item_bound():
    # review MUST: a list bound below the server's would refuse a snapshot the server served
    from app.api.routes import MAX_SNAPSHOT_ITEMS

    match = re.search(r"export const MAX_RUNS = ([0-9_]+);", _source())
    assert match is not None, "MAX_RUNS is missing from run-list.mjs"
    assert int(match.group(1).replace("_", "")) == MAX_SNAPSHOT_ITEMS
