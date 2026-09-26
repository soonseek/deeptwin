"""The browser's term dictionary mirrors the server's closed vocabularies (2026-09-26 UI phase 2).

app/static/ui-format.mjs turns internal terms into the owner's words: every public event type
the server can emit (app/domain/events.py EVENT_TYPES) has a sentence, every public event
status and error code (app/domain/public_events.py) a label, and every graph node kind, edge
kind and failure policy (app/domain/graph_schema.py) a label. A new server term without a
label would fall back to the generic "기록된 사건" or the raw value; this test makes that drift
visible instead of silent.
"""

import re
from pathlib import Path

from app.api.assets import MODULES
from app.domain.events import EVENT_TYPES
from app.domain.graph_schema import EDGE_KINDS, FAILURE_POLICIES, NODE_KINDS
from app.domain.public_events import ERROR_CODES, STATUSES

_FORMAT = Path(__file__).resolve().parents[1] / "static" / "ui-format.mjs"


def _table(name):
    source = _FORMAT.read_text(encoding="utf-8")
    match = re.search(rf"export const {name} = Object\.freeze\(\{{(.*?)\n\}}\);", source, re.DOTALL)
    assert match is not None, name
    return set(re.findall(r"'?([a-z][a-z_.]*)'?:\s*['\[]", match.group(1)))


def test_the_dictionary_is_a_catalogued_public_asset():
    assert MODULES["ui-format.mjs"] == "application/javascript"


def test_every_public_event_type_has_a_sentence():
    assert _table("EVENT_TEXT") == set(EVENT_TYPES)


def test_every_event_status_and_error_code_has_a_label():
    assert _table("EVENT_STATUS_LABELS") == set(STATUSES)
    assert _table("EVENT_STATUS_TONES") == set(STATUSES)
    assert _table("EVENT_ERROR_LABELS") == set(ERROR_CODES)


def test_every_graph_term_has_a_label():
    assert _table("NODE_KIND_LABELS") == set(NODE_KINDS)
    assert _table("EDGE_KIND_LABELS") == set(EDGE_KINDS)
    assert _table("FAILURE_POLICY_LABELS") == set(FAILURE_POLICIES)
