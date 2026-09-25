"""T075: the implementation matrix generator covers every requirement and task."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "specs/001-autonomous-release/tools/implementation_matrix.py"


def _tool():
    spec = importlib.util.spec_from_file_location("implementation_matrix", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_requirement_gets_a_row_and_ranges_expand():
    tool = _tool()
    requirements = tool.requirements()
    assert len(requirements) == 44
    assert tool._cited("FR-010–012") == {"FR-010", "FR-011", "FR-012"}
    assert tool._cited("FR-013/030") == {"FR-013", "FR-030"}
    matrix = tool.build()
    for ident in requirements:
        assert f"| {ident} |" in matrix


def test_a_requirement_is_complete_only_when_all_citing_tasks_are_checked():
    tool = _tool()
    tasks = tool.tasks()
    matrix = tool.build()
    for line in matrix.splitlines():
        if line.startswith("| FR-") or line.startswith("| SC-"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            ident, open_tasks, state = cells[0], cells[3], cells[-1]
            citing = [t for t, (_done, ids) in tasks.items() if ident in ids]
            assert state == ("complete" if all(tasks[t][0] for t in citing) and citing else state)
            if state == "complete":
                assert open_tasks == "—"
