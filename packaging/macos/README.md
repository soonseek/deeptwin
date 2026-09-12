# Superseded macOS packaging experiments

This directory preserves the pre-ADR-009 native `.app`/DMG/launcher dependency and isolation
experiments. It is not a current DeepTwin distribution target, build input, product surface or
release gate. Do not invoke these files from the self-hosted web release or present their passing
canaries as web-worker qualification.

The current distribution and worker requirements are defined by constitution 3.0.1,
`specs/001-autonomous-release/decisions.md` ADR-009–012, the current tasks and `deploy/`.
