"""Regenerate the /api/v1 route inventory table in docs/release/api-compatibility.md from the
build-installed descriptors (app/api/route_contributions/*.json), in catalog order.

    python specs/001-autonomous-release/tools/route_inventory.py --write
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/release/api-compatibility.md"
START = "Current inventory ("
END = "The descriptor files are the authoritative list"


def _catalog_order() -> list[str]:
    source = (ROOT / "app/api/first_party_catalog.py").read_text()
    return re.findall(r'"([a-z0-9-]+-v\d+\.json)"', source)


def table() -> str:
    order = _catalog_order()
    directory = ROOT / "app/api/route_contributions"
    rows, total, policies = [], 0, set()
    for name in order:
        path = directory / name
        if not path.exists():
            continue
        descriptor = json.loads(path.read_text())
        routes = descriptor["routes"]
        total += len(routes)
        scopes = sorted({route["required_scope"] for route in routes if route.get("required_scope")})
        policies.update(route.get("auth_policy") for route in routes)
        ids = ", ".join(route["route_id"] for route in routes)
        rows.append(f"| `{descriptor['contribution_id']}` | {ids} ({len(routes)}) | "
                    + ", ".join(f"`{scope}`" for scope in scopes) + " |")
    policy = ", ".join(f"`{item}`" for item in sorted(p for p in policies if p))
    head = f"Current inventory ({total} routes in {len(rows)} contributions; auth policies: {policy}):\n\n"
    return head + "| Contribution | Routes | Scopes |\n| --- | --- | --- |\n" + "\n".join(rows) + "\n\n"


def write() -> None:
    text = DOC.read_text()
    start, end = text.index(START), text.index(END)
    DOC.write_text(text[:start] + table() + text[end:])


if __name__ == "__main__":
    write() if "--write" in sys.argv else print(table(), end="")
