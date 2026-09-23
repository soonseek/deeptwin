"""T087 core boundary (ADR-014): the core never reaches the presentation layer.

Starting from every module under `app/domain`, `app/services`, `app/runtime`,
`app/operations` and `app/extensions`, the transitive import graph is walked
statically (every `import`, `from … import`, relative import, and literal
`importlib.import_module` / `__import__` target, including imports under
`TYPE_CHECKING` or inside functions). No path may reach `app.api`, `app.static`,
`app.server`, FastAPI, Starlette, Jinja or Uvicorn, directly or through any other
`app` module; and a dynamic import whose target is not a string literal is itself a
violation, because it could bypass this check. A synthetic tree proves the walker
catches each form.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE = ("app.domain", "app.services", "app.runtime", "app.operations", "app.extensions")
FORBIDDEN = ("app.api", "app.static", "app.server", "fastapi", "starlette", "jinja2", "uvicorn")
_DYNAMIC = {"import_module", "__import__"}


def _modules(root: Path) -> dict:
    found = {}
    for path in (root / "app").rglob("*.py"):
        relative = path.relative_to(root)
        if "tests" in relative.parts or "__pycache__" in relative.parts:
            continue
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        found[".".join(parts)] = path
    return found


def _imports(name: str, path: Path, modules: dict):
    """(targets, unresolvable dynamic imports) of one module."""

    package = name.split(".") if path.name == "__init__.py" else name.split(".")[:-1]
    targets, dynamic = set(), []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[:len(package) - node.level + 1] if node.level else []
            target = ".".join([*base, *([node.module] if node.module else [])])
            targets.add(target)
            targets.update(f"{target}.{alias.name}" for alias in node.names
                           if f"{target}.{alias.name}" in modules)
        elif isinstance(node, ast.Call):
            function = node.func
            called = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", None)
            if called in _DYNAMIC:
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    targets.add(first.value)
                else:
                    dynamic.append(f"{name}:{node.lineno}")
    return targets, dynamic


def _forbidden(target: str) -> bool:
    return any(target == item or target.startswith(item + ".") for item in FORBIDDEN)


def boundary_violations(root: Path) -> list[str]:
    modules = _modules(root)
    starts = sorted(name for name in modules if name.startswith(CORE))
    parent = dict.fromkeys(starts)
    stack, seen, violations = list(starts), set(), []

    def chain(name):
        path = [name]
        while parent.get(path[-1]) is not None:
            path.append(parent[path[-1]])
        return " <- ".join(path)

    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        targets, dynamic = _imports(name, modules[name], modules)
        violations.extend(f"unresolvable dynamic import at {item}" for item in dynamic)
        for target in sorted(targets):
            if _forbidden(target):
                violations.append(f"{target} <- {chain(name)}")
                continue
            module = target
            while module and module not in modules:
                module = module.rpartition(".")[0]
            if module and module.startswith("app") and module not in seen:
                parent.setdefault(module, name)
                stack.append(module)
    return sorted(set(violations))


def test_the_core_never_reaches_presentation_or_web_frameworks():
    assert boundary_violations(ROOT) == []


@pytest.mark.parametrize(("files", "expected"), [
    ({"app/services/a.py": "from ..api import routes\n"}, "app.api"),
    ({"app/services/a.py": "from app.storage import x\n", "app/storage.py": "import fastapi\n"}, "fastapi"),
    ({"app/runtime/a.py": "def f():\n    from app import server\n"}, "app.server"),
    ({"app/domain/a.py": "import importlib\nimportlib.import_module('app.static.x')\n"}, "app.static"),
    ({"app/extensions/a.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import starlette.requests\n"},
     "starlette"),
    ({"app/operations/a.py": "import importlib\nname = 'x'\nimportlib.import_module(name)\n"}, "unresolvable"),
])
def test_the_walker_catches_each_form(tmp_path, files, expected):
    for package in ("app", "app/services", "app/runtime", "app/domain", "app/extensions", "app/operations",
                    "app/api", "app/static"):
        (tmp_path / package).mkdir(parents=True, exist_ok=True)
        (tmp_path / package / "__init__.py").write_text("")
    (tmp_path / "app/api/routes.py").write_text("")
    (tmp_path / "app/server.py").write_text("")
    (tmp_path / "app/static/x.py").write_text("")
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    found = boundary_violations(tmp_path)
    assert found and all(expected in item for item in found), found


def test_the_walk_actually_covers_the_core():
    modules = _modules(ROOT)
    assert sum(name.startswith(CORE) for name in modules) > 100
