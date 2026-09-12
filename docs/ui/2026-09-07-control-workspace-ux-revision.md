# Control workspace UX revision

Status: paused after the user's first-use journey correction on 2026-09-07. Partial implementation is preserved; final verification and usability acceptance are not complete. The prior “수정해” authorized those scoped changes, not an established product shell or permission to connect engines. See `2026-09-07-first-use-experience.md` for the new review focus.

## Scope and visual direction

Retain the dark, readable control graph, Korean task labels, teal selection, existing artifact files and exact provenance. Restructure information rather than recolor the prototype. At desktop width, put the selected output work area alongside the graph; on narrower screens, explicit selection brings that work area into view. Separate “selected original” from “my alternative under the same conditions.” Keep workspace, conversation and graph views on the same state, with different initial disclosure levels.

Design comparison keeps three compact same-focus summaries and one selected full-size graph. Improvement review starts with differences, competing unconfirmed explanations and round outcomes; full source pairs, traces and paired runs remain available as disclosures. Internal audit records remain intact with current context identified, without inventing per-context causal links.

## Work and verification

- Root: renderer work area, selected artifact state, original/alternative distinction, conversation layout, contextual audit, CSS and geometry checks.
- Comparison scope: three-design comparison and improvement hierarchy, with new failing tests before implementation.
- Interaction scope: responsive selection focus and mode-scoped disclosures, with new failing browser tests.
- Regression scope: preserve all existing semantic, lineage, storage, security and byte-level assertions; adapt only approved visibility/layout expectations.
- Then: independent specification review, quality review, complete automated suite, fresh screenshots and self-critique. Actual usability remains for the user to judge.

## Boundaries

No real model, browser/file executor, lens inference, evaluation, learning, approval, export or transmission is connected. Existing synthetic artifact bodies are unchanged, including their English sample contents. No edits to the old prototype, protected plan changes or unrelated worktree files. No install, push or merge.
