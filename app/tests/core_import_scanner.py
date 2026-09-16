"""Static dependency gate, not a sandbox for malicious or generated Python."""

import ast
from pathlib import Path

FORBIDDEN = ("app.api", "app.static", "app.server", "fastapi", "starlette", "jinja2")
CORE = ("domain", "runtime", "extensions", "services", "operations")
DYNAMIC = {"__import__", "builtins.__import__", "importlib.import_module"}
LOADER_MODULES = ("importlib.util", "importlib.machinery", "runpy")


def violations(repository):
    repository = Path(repository)
    result = []
    pending = [
        source for name in CORE for source in (repository / "app" / name).rglob("*.py")
    ]
    seen = set()

    def enqueue(target):
        parts = target.split(".")
        for length in range(1, len(parts) + 1):
            path = repository.joinpath(*parts[:length])
            initializer = path / "__init__.py"
            if initializer.is_file():
                pending.append(initializer)
            module_path = path.with_suffix(".py")
            if module_path.is_file():
                pending.append(module_path)

    while pending:
        source = pending.pop()
        if source in seen:
            continue
        seen.add(source)
        enqueue(".".join(source.relative_to(repository).with_suffix("").parts))
        module = ".".join(source.relative_to(repository).with_suffix("").parts)
        package = (
            module.removesuffix(".__init__")
            if source.name == "__init__.py"
            else module.rsplit(".", 1)[0]
        )
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        aliases = {}
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
                for a in node.names:
                    aliases[a.asname or a.name.split(".")[0]] = (
                        a.name if a.asname else a.name.split(".")[0]
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = package.split(".")
                    base = ".".join(parts[: len(parts) - node.level + 1])
                    base = ".".join(filter(None, (base, node.module)))
                else:
                    base = node.module or ""
                targets = [
                    base,
                    *[base + "." + a.name for a in node.names if a.name != "*"],
                ]
                for a in node.names:
                    aliases[a.asname or a.name] = base + "." + a.name
            for target in targets:
                if any(
                    target == bad or target.startswith(bad + ".") for bad in FORBIDDEN
                ):
                    result.append(
                        (str(source.relative_to(repository)), node.lineno, target)
                    )
                elif target in DYNAMIC or any(
                    target == loader or target.startswith(loader + ".")
                    for loader in LOADER_MODULES
                ):
                    result.append(
                        (
                            str(source.relative_to(repository)),
                            node.lineno,
                            "dynamic module loading: " + target,
                        )
                    )
                else:
                    enqueue(target)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Name, ast.Attribute)):
                continue
            if isinstance(node, ast.Name):
                target = aliases.get(node.id, node.id)
            elif isinstance(node.value, ast.Name):
                target = aliases.get(node.value.id, node.value.id) + "." + node.attr
            else:
                continue
            if target in DYNAMIC:
                result.append(
                    (
                        str(source.relative_to(repository)),
                        node.lineno,
                        "dynamic module loading: " + target,
                    )
                )
    return sorted(set(result))
