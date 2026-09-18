"""T048 (logic half): the run GUI constants must mirror the server contracts.

app/static/runtime.mjs carries the closed run phases, the create command's
input kinds and the error partition for client-side validation; a drift
between the GUI copy and app/services/runs.py or app/api/runs.py would let
the GUI show a phase the server never derives, send a reference of a kind
the server refuses, or mislabel an error. This test parses the .mjs
constants and compares them against the Python contracts, the same way
test_records_contract_mirror.py pins records.mjs.
"""

import re
from pathlib import Path

from app.api.runs import _CREATE_FIELDS, STATUS
from app.services.runs import _INPUT_KINDS, PHASES

_RUNTIME = Path(__file__).resolve().parents[1] / "static" / "runtime.mjs"


def _source():
    return _RUNTIME.read_text(encoding="utf-8")


def _mjs_list(name):
    match = re.search(rf"export const {name} = Object\.freeze\(\[(.*?)\]\);", _source(), re.DOTALL)
    assert match is not None, f"{name} is missing from runtime.mjs"
    return re.findall(r"'([a-z_]+)'", match.group(1))


def _mjs_map(name):
    match = re.search(rf"export const {name} = Object\.freeze\(\{{(.*?)\}}\);", _source(), re.DOTALL)
    assert match is not None, f"{name} is missing from runtime.mjs"
    return dict(re.findall(r"([a-z_]+): '([^']*)'", match.group(1)))


def test_phases_mirror_the_run_service_in_order():
    assert _mjs_list("PHASES") == list(PHASES)


def test_phase_labels_cover_every_phase_with_text():
    labels = _mjs_map("PHASE_LABELS")
    assert set(labels) == set(PHASES)
    assert all(label.strip() for label in labels.values())


def test_input_kinds_mirror_the_create_command():
    assert _mjs_map("INPUT_KINDS") == dict(_INPUT_KINDS)
    assert list(_mjs_map("INPUT_KINDS")) == list(_CREATE_FIELDS[1:])


def test_error_codes_mirror_the_route_partition():
    assert set(_mjs_list("ERROR_CODES")) == set(STATUS)
