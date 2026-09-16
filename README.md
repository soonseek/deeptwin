# DeepTwin

DeepTwin is an open-source framework being designed so nondevelopers can
describe their work, review and approve an agent environment, and operate it
through a UI. Its DeepTwin engine is intended to investigate differences
between agent artifacts and users' own full or partial alternatives, test
changes against previous work, and promote the exact evaluated environment
version only after human approval.

This repository is currently in bootstrap state. It contains the pinned Python
environment, development tooling, and product-design records;
it does not yet claim that the reference framework has been implemented or
empirically validated.

Adopted high-level product baseline:
[integrated product design](docs/superpowers/specs/2026-09-06-deeptwin-integrated-product-design.md).
The user has adopted the product structure and confirmed the organized
document review. The next scoped artifact is the
[UI structure design work plan](docs/superpowers/plans/2026-09-06-deeptwin-ui-structure.md).
Unresolved choices remain open; this is not an approved UI or engine
implementation specification, and the design-plan tasks have not been run.
Product intent and current design process:
[product intent](docs/product-intent.md),
[build process proposal](docs/BUILD_PROCESS_KO.md), and
[brainstorming progress](docs/brainstorming-progress.md).
Read these before deriving product requirements from the bootstrap choices below.

## Developer bootstrap

```bash
uv sync --locked
uv run python -c "import langgraph, pydantic, jsonschema"
```

The original setup used a local offline baseline. That installation choice is
not the current product scope or build priority. The product must support end
users' own Claude and Codex subscriptions as separate usable paths, with an
explicitly selected API option and no automatic paid fallback. No end-user CLI
workflow is required. These paths have not yet been implemented or validated.

See [docs/BOOTSTRAP.md](docs/BOOTSTRAP.md) for installed tooling, exact pins,
verification commands, and deferred decisions.

## Specification workflow

The repository-scoped Spec Kit skills live in `.agents/skills`. The current
stage is Superpowers writing-plans for initial UI structure design, following
integrated design review.
After design review and the relevant planning approval, use the specification
workflow without treating the paper's limited reference preview as the full
user-requested product:

1. `$speckit-constitution` for project principles and hard safety boundaries.
2. `$speckit-specify` for reviewed user requirements and paper-derived contracts.
3. `$speckit-plan` and `$speckit-tasks` only after the specification is reviewed.

Do not treat expert alternatives as intermediate ground truth, expose sealed
evaluation data to the runner, or auto-promote knowledge. Lens capabilities
are part of the product design, including initial design and critique;
episode-level SPLI is conditional, not a mandatory questionnaire or a reason
to block unrelated work. Installing a skill does not implement these engines.
