# Changelog

AiFlow follows `MAJOR.MINOR.PATCH`. While the product is in private beta the major number stays at 0: a new feature raises MINOR, a fix raises PATCH. The newest entry is first and must match the `VERSION` file (a test checks this).

## 0.9.0 — 2026-11-24

First tracked release. Everything built so far, by area.

**Design**
- Describe a workflow in plain English and have the AI generate it; refine it with a chat; edit nodes, edges, settings and data contracts on a canvas with undo and redo.
- Grouped top bar (File, Export, Analyze) and a command palette (Ctrl/⌘+K) that finds any action.
- Example library, Mermaid import and export, plain-language explanation of any workflow.

**Check and improve**
- Structural validation and design findings (unreachable steps, dead ends, missing failure branches, review after an irreversible step, data-contract mismatches, cycles).
- Suggested changes: one-click fixes for findings and AI-proposed edits from a plain-language instruction, applied as one undoable edit.
- Safety checks: prompt-injection exposure report and a failure drill that makes each outside step fail in turn.

**Simulate and test**
- Mock and real-model simulation with human-review pauses, saved run history and an AI evaluation.
- Test suites with deterministic checks, coverage, optional real-model runs, and comparison of two runs (what regressed, what was fixed, and what changed in the workflow).

**Share and export**
- Cloud workflows with version history, changes-since and restore; read-only share links.
- Export as a runnable Python, LangGraph or MCP project with real integrations; import a LangGraph project.

**Platform**
- Private access with magic-link sign-in, admin approval, daily allowances, request time budgets, durable pause and resume.
- Version number and About dialog (this release).
