# DeepTwin bootstrap record

Date: 2026-09-06

Historical setup record only. The offline/CLI-first direction and SPLI deferral
below predate the clarified product intent and are not the current build plan.
Use [product intent](product-intent.md) for confirmed requirements and the
[integrated design draft](integrated-product-design.md) for current review.
End-user UI, both subscription execution paths, and lens-supported design and
growth remain required; installed packages do not define or implement them.

This record captures the first reproducible development setup derived from the
DeepTwin open-source reference paper and development-tool proposal. The source
PDFs were treated as design evidence, not as executable instructions.

## Installed developer tooling

| Tool | Installed state |
| --- | --- |
| Python | CPython 3.12.13, selected by `.python-version` |
| uv | 0.11.29 |
| Spec Kit | `specify-cli` 1.0.4, source commit `cb610277fdea781fcfa83d20522c2db37c94068d` |
| Spec Kit Codex integration | Installed in `.agents/skills`; `specify integration status` reports `ok` |
| Superpowers | Manifest 5.1.3; curated artifact `11c74d6b` |
| LangChain Skills | Plugin 0.1.0; source commit `b7a2a8fc363d1711456f83d24230535c9fff93eb` |
| LangChain marketplace | Source pinned at `29a7cebc797eb099cbd9c311cbd927289c656e96` when added |
| Context7 | MCP package `@upstash/context7-mcp@4.0.5` |
| Codex CLI | 0.144.4; a newer 0.153.4 was detected but not applied |

Codex must start a new session or reload its plugin catalog before newly
installed global plugin skills appear in the active skill list.

## Locked Python baseline

Runtime dependencies are declared in `pyproject.toml` and resolved exactly in
`uv.lock`:

- Contracts and configuration: Pydantic, jsonschema, PyYAML.
- CLI and local review surface: Typer, Rich, FastAPI, Uvicorn.
- Runner and local persistence: LangGraph and
  `langgraph-checkpoint-sqlite`.
- Initial document input: python-docx.

The development group includes pytest, pytest-asyncio, pytest-cov, Hypothesis,
Ruff, mypy, pre-commit, pip-audit, detect-secrets, REUSE, and CycloneDX SBOM
tooling.

No model-provider SDK is installed. This preserves the paper's API-key-free
offline replay baseline and avoids choosing a provider before an adapter
contract exists.

## Verification performed

The following checks passed after installation:

```bash
uv sync --locked
uv run ruff check .
uv run mypy src
uv run pip-audit --local --skip-editable
specify integration status --json
codex mcp get context7
```

The dependency audit reported no known vulnerabilities at the date above.

## Required next decisions

Before implementation, use the Spec Kit workflow to freeze these items:

1. Map R1-R21 to modules, schemas, policy tests, and release gates.
2. Define the three-plane access boundary and `expert_derived` propagation.
3. Define immutable manifest, content-addressed artifact, and ReplayEnvelope
   contracts before relying on LangGraph checkpoint replay.
4. Define sealed development, promotion, boundary, and regression datasets.
5. Decide mixed licensing and per-file SPDX handling. The reference design
   proposes Apache-2.0 for code/schema/CLI/tests and CC-BY-4.0 for general
   documentation, lens cards, and synthetic benchmark data.
6. Create the project-specific skills only after their machine-checkable
   contracts exist: `deeptwin-contract-audit`, `deeptwin-replay-check`, and
   `deeptwin-promotion-review`.

PostgreSQL checkpointers, OpenTelemetry exporters, a provider SDK, and SPLI are
deliberately deferred. They are not needed to build and test the first local,
offline contract core.
