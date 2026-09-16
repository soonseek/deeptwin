"""Resolved reusable-core imports and identity-compatible API facades."""

from pathlib import Path

import pytest

from app.tests.core_import_scanner import violations


def test_actual_reusable_core_has_no_presentation_dependencies():
    assert violations(Path(__file__).resolve().parents[2]) == []


@pytest.mark.parametrize(
    "files",
    [
        {"app/operations/a.py": "import app.api.session"},
        {
            "app/domain/a.py": "from app.helper import value",
            "app/helper.py": "import app.api.session",
        },
        {
            "app/domain/a.py": "import app.helpers.child",
            "app/helpers/__init__.py": "import fastapi",
            "app/helpers/child.py": "value = 1",
        },
        {
            "app/domain/a.py": "import app.helper",
            "app/__init__.py": "import starlette",
            "app/helper.py": "value = 1",
        },
        {
            "app/domain/a.py": "from app.helper import value",
            "app/helper.py": "from importlib import import_module as load\nvalue = load('app.api.session')",
        },
        {
            "app/domain/a.py": "from app.helpers import child",
            "app/helpers/child.py": "from .. import other",
            "app/other.py": "import jinja2",
        },
        {
            "app/domain/a.py": "from app.helper import load\nload('app.api')",
            "app/helper.py": "from importlib import import_module as load",
        },
        {
            "app/domain/a.py": "import app.helper",
            "app/helper.py": "import importlib\nload = importlib.import_module\nload('app.api')",
        },
    ],
)
def test_transitive_local_and_operations_violations(tmp_path, files):
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    assert violations(tmp_path)


def test_allowed_transitive_cycles_are_scanned_without_execution(tmp_path):
    for name, content in {
        "app/domain/a.py": "import app.helper\nraise RuntimeError('must not execute')",
        "app/helper.py": "from app.helpers import child\nimport json",
        "app/helpers/child.py": "from ..domain import a",
        "app/unused.py": "import fastapi",
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    assert violations(tmp_path) == []


@pytest.mark.parametrize(
    "filename,source",
    [
        ("app/domain/a.py", "from ..api.session import AuthenticatedRequest as R"),
        ("app/domain/nested/a.py", "from ... import api as presentation"),
        ("app/domain/nested/__init__.py", "from ...api import session"),
        ("app/services/a.py", "import app.api.wire as wire"),
        ("app/services/a.py", "from app import server as service"),
        ("app/extensions/a.py", "from ..static import assets"),
        ("app/runtime/a.py", "from fastapi.responses import Response"),
        ("app/runtime/a.py", "import starlette"),
        ("app/runtime/a.py", "from jinja2 import Template"),
        ("app/runtime/a.py", "import importlib as i\ni.import_module('app.api')"),
        (
            "app/runtime/a.py",
            "from importlib import import_module as load\nload('app.api')",
        ),
        ("app/runtime/a.py", "__import__('app.api')"),
        (
            "app/runtime/a.py",
            "import importlib.util\nimportlib.util.spec_from_file_location('x', 'app/api/session.py')",
        ),
        (
            "app/runtime/a.py",
            "from importlib.machinery import SourceFileLoader\nSourceFileLoader('x', 'app/api/session.py')",
        ),
        ("app/runtime/a.py", "import runpy\nrunpy.run_module('app.api.session')"),
    ],
)
def test_nested_relative_absolute_alias_and_dynamic_loading_are_detected(
    tmp_path, filename, source
):
    path = tmp_path / filename
    path.parent.mkdir(parents=True)
    path.write_text(source)
    assert violations(tmp_path)


def test_allowed_sibling_and_standard_library_imports(tmp_path):
    path = tmp_path / "app/domain/nested/__init__.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "from ..refs import EntityRef\nfrom ...runtime import ledger\nimport json\nfrom pathlib import Path"
    )
    assert violations(tmp_path) == []


def test_api_facades_preserve_core_object_identity():
    from app.api import session, views, wire
    from app.domain import public_events, request_identity
    from app.domain import wire as core_wire

    for name in (
        "AuthenticatedRequest",
        "AuthenticatedSession",
        "RequestDenied",
        "SessionBoundaryError",
        "authenticate_in_transaction",
    ):
        assert getattr(session, name) is getattr(request_identity, name)
    for name in (
        "WireLimits",
        "WireInputError",
        "parse_json_object",
        "parse_query",
        "parse_singleton_headers",
    ):
        assert getattr(wire, name) is getattr(core_wire, name)
    for name in (
        "EventEnvelope",
        "PublicEventView",
        "EventPage",
        "PublicEventJournal",
        "_append_event_in_transaction",
        "_event_cursor_in_transaction",
    ):
        assert getattr(views, name) is getattr(public_events, name)
    assert views.render_sse.__module__ == "app.api.views"
