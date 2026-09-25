"""The browser shell's static modules: one closed, content-typed catalogue
served flat (no nested tree: the supported boundary refuses `..`, `%` and
`//` in raw paths) by both the supported factory and the development
preview. `index.html` is the preview's shell only; the supported factory's
`/` serves `start.html`, the first screen (T025: the first-owner setup or the
login form, decided by the public setup state on `/health`). Assets are
served whole (no byte ranges, no validators) under the boundary's `no-store`;
content-digested immutable asset paths (api.md) are deferred to the T025
shell work.
"""

from pathlib import Path
from types import MappingProxyType
from uuid import uuid4

from fastapi.responses import JSONResponse, Response

STATIC = Path(__file__).resolve().parents[1] / "static"
JAVASCRIPT = "application/javascript"
MODULES = MappingProxyType({
    "app.mjs": JAVASCRIPT,
    "styles.css": "text/css",
    "chat.mjs": JAVASCRIPT,
    "settings.mjs": JAVASCRIPT,
    "speech-input.mjs": JAVASCRIPT,
    "audio-capture-worklet.mjs": JAVASCRIPT,
    "approvals.mjs": JAVASCRIPT,
    "approval-screen.mjs": JAVASCRIPT,
    "records.mjs": JAVASCRIPT,
    "runtime.mjs": JAVASCRIPT,
    "session.mjs": JAVASCRIPT,
    "run-panel.mjs": JAVASCRIPT,
    "run-list.mjs": JAVASCRIPT,
    "artifacts.mjs": JAVASCRIPT,
    "alternatives.mjs": JAVASCRIPT,
    "alternative-file.mjs": JAVASCRIPT,
    "inquiry.mjs": JAVASCRIPT,
    "work-export.mjs": JAVASCRIPT,
    "source-deletion.mjs": JAVASCRIPT,
    "observe.mjs": JAVASCRIPT,
    "observe.html": "text/html",
    "start.mjs": JAVASCRIPT,
    "start.html": "text/html",
    "work.mjs": JAVASCRIPT,
    "work.html": "text/html",
    "records-page.mjs": JAVASCRIPT,
    "account.mjs": JAVASCRIPT,
    "claude-connection.mjs": JAVASCRIPT,
    "work-model.mjs": JAVASCRIPT,
    "graph.mjs": JAVASCRIPT,
    "workspace.mjs": JAVASCRIPT,
    "records.html": "text/html",
    "versions.mjs": JAVASCRIPT,
    "experiments.mjs": JAVASCRIPT,
    "versions-page.mjs": JAVASCRIPT,
    "versions.html": "text/html",
})
PUBLIC_ASSET_PATHS = frozenset("/" + name for name in MODULES)
_SHELL = "index.html"


def _unavailable():
    return JSONResponse(
        {
            "code": "unavailable",
            "message": "Asset could not be served",
            "retryability": "not_retryable",
            "affected_refs": [],
            "correlation_id": str(uuid4()),
        },
        status_code=503,
    )


def asset_response(name):
    """The exact catalogued file as one whole response, or the closed
    unavailable envelope; never a path the caller composed."""

    if name not in MODULES and name != _SHELL:
        return _unavailable()
    path = STATIC / name
    if not path.is_file():
        return _unavailable()
    media_type = MODULES.get(name, "text/html")
    return Response(content=path.read_bytes(), media_type=media_type)


def asset_endpoint(name):
    """A parameterless route endpoint for one catalogued name: nothing about
    the request (query, body, headers) can re-aim it."""

    if name not in MODULES and name != _SHELL:
        raise ValueError("not a catalogued asset")

    def endpoint():
        return asset_response(name)

    endpoint.__name__ = "asset_" + name.replace(".", "_").replace("-", "_")
    return endpoint
