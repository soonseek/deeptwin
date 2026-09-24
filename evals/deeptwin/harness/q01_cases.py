"""Frozen Q01 development trial inputs, materialized from the authored materials.

Each development boundary case of ``tasks/v01-q01/Task.md`` becomes one frozen
trial input: the visible source (originals, fixed criteria, candidate, research
lens pack) plus at most one authored counterexample. A case carries no label,
expected status or ordinal hint; its id is a stable hash of the candidate and
counterexample identities. Expected boundaries live only in the independent
verifier, never here.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from evals.deeptwin.q01_materials import q01_counterexample, q01_source

CASE_SCHEMA = "q01-frozen-case-1"
ENVIRONMENT_SCHEMA = "q01-environment-1"
AUTHORED_SOURCE = "evals/deeptwin/q01_materials.py#q01_counterexample"
TASK_DIR = Path(__file__).resolve().parents[1] / "tasks" / "v01-q01"
ENVIRONMENT_DIR = "environment"
ENVIRONMENT_MANIFEST = "environment/manifest.json"
INSTRUCTION_FILE = "instruction.md"

# (candidate id, authored counterexample kind or None) for every row of the
# development boundary table. The material generator arguments are the only
# inputs; no expected class is named here.
CASE_SPECS = (
    ("c71", None),
    ("c24", None),
    ("c86", None),
    ("c09", None),
    ("c53", None),
    ("c71", "images-delete"),
    ("c86", "mixed-attribution"),
    ("c71", "mixed-attribution"),
    ("c42", "central-crop"),
    ("c18", None),
)


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def file_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + "\n").encode("utf-8")


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def case_id_for(candidate_id: str, counterexample_id: str | None) -> str:
    key = canonical({"candidate_id": candidate_id, "counterexample_id": counterexample_id})
    return "q01-" + sha256(key.encode("utf-8")).hexdigest()[:10]


def materialize_case(candidate_id: str, kind: str | None) -> dict:
    source = q01_source(candidate_id)
    authored = []
    if kind is not None:
        authored.append({"counterexample": q01_counterexample(kind, candidate_id), "source": AUTHORED_SOURCE})
    counterexample_id = authored[0]["counterexample"]["id"] if authored else None
    return {
        "schema": CASE_SCHEMA,
        "case_id": case_id_for(candidate_id, counterexample_id),
        "source": source,
        "authored_counterexamples": authored,
    }


def materialize_all() -> list[dict]:
    cases = [materialize_case(candidate_id, kind) for candidate_id, kind in CASE_SPECS]
    ids = [case["case_id"] for case in cases]
    if len(set(ids)) != len(ids):  # pragma: no cover - authored table consistency
        raise ValueError("duplicate Q01 case id")
    # Sorted by opaque id so file order does not follow the boundary table.
    return sorted(cases, key=lambda case: case["case_id"])


def environment_manifest(cases: list[dict]) -> dict:
    return {
        "schema": ENVIRONMENT_SCHEMA,
        "materials": "evals/deeptwin/q01_materials.py",
        "network": "none",
        "cases": [{"case_id": case["case_id"], "path": f"{ENVIRONMENT_DIR}/cases/{case['case_id']}.json",
                   "sha256": digest(file_bytes(case))} for case in cases],
    }


def write_environment(task_dir: Path = TASK_DIR) -> dict:
    """Regenerate the frozen environment files (a deliberate authoring step)."""
    cases = materialize_all()
    target = Path(task_dir) / ENVIRONMENT_DIR / "cases"
    target.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (target / f"{case['case_id']}.json").write_bytes(file_bytes(case))
    manifest = environment_manifest(cases)
    (Path(task_dir) / ENVIRONMENT_MANIFEST).write_bytes(file_bytes(manifest))
    return manifest


if __name__ == "__main__":  # pragma: no cover - authoring entry point
    write_environment()
