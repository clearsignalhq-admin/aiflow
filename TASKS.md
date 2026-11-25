# AiFlow — Current Iteration

## Iteration 19 — Closing the Backlog

#### Task 66 — Backlog Follow-ups `[x]`

- [x] Save-state note next to the workflow name (unsaved / saved to cloud)
- [x] Pass-rate-over-time chart in the Tests dialog
- [x] Save a copy of a shared workflow into your own account
- [x] Recent actions first in the action search
- [x] "Read more in the user guide" links from the ⓘ help dialogs; guide link and version on the landing page
- [x] `scripts/bump_version.py` (start a release) and `scripts/deploy.py` (deploy with the commit stamped, clean-tree check)
- [x] Backlog rewritten: every remaining item is now Done, Needs you, or Not planned, each with its reason
- [x] Test setup gives every test an in-memory `localStorage` (newer Node versions break jsdom's)
- [x] The one long-failing backend test fixed (it depended on the developer's local Turnstile secret); the backend suite is fully green
- [x] Top bar kept tidy with the new save-state note (buttons never wrap; the note is an icon until there is room)
- [x] Tests: 20 frontend, 24 backend

---

## Iteration 18 — Video Guide

#### Task 65 — Video Guide Storyboards `[x]`

- [x] `docs/video-guide/`: four storyboards (about 3, 4, 3 and 3½ minutes) with scene timeline, screenshots, on-screen notes, narration, chapter markers and a one-line summary; production notes with wording rules, pronunciation, a NotebookLM instruction block and a pre-publish checklist
- [x] Found while checking the narration against the real product, and fixed: the suggested failure-branch fix left its success flag untyped, so simulated fixes followed both branches (version 0.10.1)
- [x] Tests: 23 (screenshots exist and are all used, contents links resolve, scene timelines contiguous, chapter markers match, narration pace); backend assertion added for the fix

---

## Iteration 17 — User Guide

#### Task 64 — User Guide `[x]`

- [x] `docs/user-guide/README.md`: quick start, the screen, every feature, limits and allowances, shortcuts, troubleshooting, glossary; 25 screenshots
- [x] `docs/user-guide/capture/`: Playwright script, local capture backend (fake user, in-memory storage, canned AI) and an orchestrator that regenerates every screenshot from a clean state without touching real services
- [x] In the app: public `/guide` page (contents list, screenshots, anchors), **Help → User guide**, link from About; Markdown renderer extended with images, safe links and heading anchors
- [x] Found while capturing and fixed: stray "0" on the Validate button; suggested fixes left a cluttered layout and a stale run overlay; suggestion cards were a wall of text; canvas cropped newly added steps; mismatched text sizes
- [x] Version 0.10.0
- [x] Tests: 16 new frontend (renderer, guide page, Help menu), 2 for the Validate button

---

## Iteration 16 — Version Number and About

#### Task 63 — Version Number and About Screen `[x]`

- [x] One source of truth: root `VERSION`, `scripts/sync_version.py` (write / `--check`), `CHANGELOG.md`; tests fail on drift
- [x] Backend: `app/version.py`, FastAPI version, `GET /api/health` reports version and commit (`GIT_COMMIT` from a template parameter)
- [x] Frontend: version, commit and build date stamped at build time (Vite `define`; Amplify supplies the commit)
- [x] **Help** menu with **About AiFlow** (versions, changelog, copy version info) and a banner when page and server differ in major/minor version
- [x] Tests: 5 backend and 19 frontend

---

## Iteration 15 — Top Bar

#### Task 62 — Grouped Menus and Command Palette `[x]`

- [x] File / Export / Analyze menus with keyboard support, dividers, disabled reasons, hover-to-switch
- [x] Everyday actions kept on the bar (Validate with badges, Simulate, Tests, Refine, Generate); theme toggle and account menu on the right
- [x] Command palette (Ctrl/⌘+K): searches every action by name, group and description
- [x] One shared action list for menus and palette; responsive behaviour for narrow windows
- [x] Tests: 19 new (menus, keyboard, palette, filtering), 2 existing updated

---

## Iteration 14 — Cloud Workflows and Sharing

Source: `docs/future/2026-11-24 AiFlow - Future Directions.md` (Tier F: cloud workflows, versioning, diff, share by link).

#### Task 61 — Cloud Workflows, Versions and Share Links `[x]`

- [x] `supabase/update_202611241800.sql` (and `schema.sql`): `cloud_workflows` and `workflow_versions`, row-level security, unique (workflow, version)
- [x] `api/cloud_routes.py`: create / list / open / save / delete, version list, diff (reuses the Task 58 workflow diff), restore as a new version, share and stop sharing, public read-only `GET /api/shared/{token}` (rate limited, owner never exposed)
- [x] Limits: 30 workflows per user, newest 30 versions kept; identical saves add no version; racing saves give a clear conflict
- [x] **Cloud** dialog (save, open, versions, changes since, restore, share link, delete) and the public `/shared/:token` page (read-only canvas, JSON download)
- [x] Shared diff component used by run comparison and version history
- [x] Tests: 14 backend and 18 frontend

---

## Iteration 13 — Failure Injection and Safety Checks

Source: `docs/future/2026-11-24 AiFlow - Future Directions.md` (B7, B8).

#### Task 60 — Resilience Drill and Injection Exposure `[x]`

- [x] `inject` simulation setting: make one step fail (error, timeout, empty, malformed) with a warning in the trace
- [x] `services/resilience.py`: baseline run, then one run per external step and failure kind; verdicts handled / halted / not noticed; undecidable conditions count as halted; capped at 30 steps
- [x] `services/injection_exposure.py`: untrusted sources to AI steps to write sinks, with human-review gating and severity
- [x] `POST /api/workflows/injection-exposure` (free) and `/resilience` (one execution)
- [x] **Safety** dialog; show-the-step from an exposure
- [x] Tests: 21 backend (including: the suggested failure-branch fix turns "not noticed" into "handled") and 8 frontend

---

## Iteration 12 — Suggested Changes

Source: `docs/future/2026-11-24 AiFlow - Future Directions.md` (AI-suggested fixes).

#### Task 59 — Suggested Fixes and AI-Proposed Changes `[x]`

- [x] Typed edit operations (`schemas/patch.py`): add/remove/update step, add/remove/relabel connection; unknown operations and fields rejected
- [x] `services/patching.py`: all-or-nothing application per change on a copy, guards (one START, at least one END, no edges into START or out of END, size limits), placement of new steps, plain-language descriptions
- [x] `services/fixes.py`: deterministic fixes for unreachable steps, dead ends, single-branch and unlabelled decisions, undeclared or missing schema fields, missing failure branches; each verified to apply
- [x] `services/change_suggester.py`: AI proposals parsed into the same operations, validated and checked against the workflow; unusable ones discarded with reasons
- [x] `POST /api/workflows/fixes` (free), `/suggest` (one AI request, daily limit, timeout), `/apply-changes`
- [x] **Suggest** dialog: fixes list, describe-a-change box, per-change Apply, Apply all fixes, one undo step
- [x] Tests: 43 backend (including a failure-branch fix that still simulates) and 13 frontend

---

## Iteration 11 — Run Comparison and Regression

Source: `docs/future/2026-11-24 AiFlow - Future Directions.md` (B5).

#### Task 58 — Compare Suite Runs `[x]`

- [x] `services/run_comparison.py`: per-case classification (regressed / fixed / still failing / unchanged / added / removed / incomplete), flipped checks, path and output changes, cost and model-call deltas, coverage movement
- [x] Workflow diff between the two stored snapshots (steps added, removed, edited with before/after values; edges); detection of edited test cases
- [x] Warnings for runs that are not directly comparable (mode, seed, edited cases, unfinished runs, real-model variation) and for regressions nothing explains
- [x] `GET /api/suite-runs/compare?base=&head=` (user-scoped, same suite only) and a **Compare with** control with a report in the suite dialog
- [x] Tests: 31 backend (including an end-to-end edit → regression → explained-by-diff) and 14 frontend

---

## Iteration 10 — Real Integrations, Real-Model Suites, More Formats, Import

Source: the follow-ups listed after Tasks 51–53 (`BACKLOG.md`).

#### Task 54 — Real Integrations in Exported Code `[x]`

- [x] `connectors.py` in exports: API (httpx; percent-encoded URL values, `env:` headers, JSON body), DATABASE (SQLAlchemy, bound parameters, `env:` connection), knowledge search (embeddings or offline keyword scoring)
- [x] Mock mode returns fixtures; outside it TOOL/TRANSFORM raise `NotImplementedError`; requirements and `.env.example` follow the steps used
- [x] Tests run generated projects against a local HTTP server, a SQLite database and a knowledge folder (injection and traversal attempts included)

#### Task 55 — Real-LLM Test Suites `[x]`

- [x] `llm_mode` on suite runs (schema.sql + `update_202611241700.sql`); estimate endpoint; up-front and per-case allowance checks; model calls charged per case; cap of 20 cases per real run
- [x] UI: simulated/real switch, estimate panel, confirmation, model-call counts in the report
- [x] Tests use a fake provider; no real API call is ever made

#### Task 56 — More Export Formats `[x]`

- [x] Plain Python (no framework) and MCP tool server alongside LangGraph; `POST /api/workflows/export` with `target`; format picker in the dialog
- [x] Generated projects run their own tests; branches match the simulator seed for seed; MCP server also verified over stdio with the official client in an isolated environment
- [ ] OpenAI Agents SDK: **not built**. The SDK is agent-centric rather than graph-based, so the mapping needs design decisions, and it could not be run here to verify

#### Task 57 — Import from LangGraph `[x]`

- [x] `langgraph_importer.py`: reads the code with `ast` (never executes it); exact restore from `workflow.json`; builder calls, step-type guessing, simple routers translated to expressions
- [x] `POST /api/workflows/import/langgraph` and an Import tab; everything guessed is reported as a warning
- [x] AiFlow's own generated code reads back with the same step types, edges and labels for all examples

---

## Iteration 9 — Sharing and Leaving the Tool

Source: `docs/future/2026-11-24 AiFlow - Future Directions.md` (D1, D3, quick wins). Descriptions in `BACKLOG.md` (Tasks 51–53).

#### Task 51 — Mermaid Export and Import `[x]`

- [x] `services/mermaid.ts`: export with a shape and class per node type; tolerant import (chains, `&`, link styles, classes, front matter, comments)
- [x] Inference warnings, START/END handling, size limits, never throws; statement splitter respects quotes and entities
- [x] Round trip verified on all 10 example workflows (and re-export is byte-identical)
- [x] Modal with Export (copy, download .mmd) and Import (live preview, errors, warnings)

#### Task 52 — Explain This Workflow `[x]`

- [x] `services/explainer.py`: deterministic Markdown (steps in flow order, decisions, people, connections, rough time/cost, findings); user text cannot break tables or headings
- [x] `POST /api/workflows/explain` (no LLM, no allowance used)
- [x] Safe Markdown renderer (no raw HTML) and a modal with copy / download

#### Task 53 — LangGraph Exporter `[x]`

- [x] `services/langgraph_exporter.py` replaces the stub: graph, steps, routing, HITL interrupts, CLI, README, requirements
- [x] `POST /api/workflows/export/langgraph` returns a reproducible zip; optional suite id adds generated tests
- [x] Generated projects run their own pytest in tests (subprocess); branches match the simulator seed-for-seed; hostile text stays data
- [x] **Code** button: suite picker, download, next steps

---

## Iteration 8 — Production Readiness (follow-ups from the Task 44 spike)

Source: `docs/AiFlow - Async Suite Runs Design.md`. Full descriptions in `BACKLOG.md` (Tasks 46–50).

#### Task 46 — Durable Pause/Resume `[x]`

- [x] Persist the continuation with the run row (`workflow_runs.continuation`); schema.sql + `update_202611241400.sql`
- [x] Rebuild the paused state from the database on resume (user-scoped, validated); in-memory store stays as the fast path
- [x] pytest: pause, drop the in-memory store, resume still works (service and API level), corrupt continuations refused

#### Task 47 — Atomic Usage Counter `[x]`

- [x] SQL function `increment_usage(user, field, by, date)` — service role only; schema.sql + `update_202611241500.sql`
- [x] `increment_usage` now a single RPC call; supports `by > 1`; field whitelist
- [x] pytest incl. concurrency and migration/schema consistency

#### Task 48 — Align Simulation Timeout With the Gateway `[x]`

- [x] Simulate/resume guard 25 s inside a 28 s request budget; generate/chat 25 s; clear 504 messages
- [x] LLM evaluation uses only the remaining budget, falling back to mock with a reason
- [x] Lambda `Timeout` 60 → 30 s in `template.yaml` (needs `sam deploy`)

#### Task 49 — Benchmark Mock Simulation `[x]`

- [x] `backend/benchmarks/bench_simulation.py`; results recorded in the design note (worst p95 ≈ 0.33 ms/case)
- [x] Loose regression test; synchronous-suite cutoff decided (case cap, bulk insert)

#### Task 50 — Suites: Data Model, Job API, Client-Driven Executor `[x]`

Decisions recorded in the design note §8 (client-driven executor, caps 10/50, shared allowance, deterministic assertions only).

- [x] Tables `suites`, `suite_runs`, `suite_case_results` + RLS; `schema.sql` + `update_202611241600.sql`
- [x] Deterministic assertions (10 types) with validation at save time; value-vs-schema validator
- [x] Suite runner (mock mode, seeded, auto-approve), exact edge coverage, pass rate, node-failure hot spots
- [x] Job API with idempotent case execution, cancel, stale detection, tier caps, up-front allowance check, retention (20 runs per suite)
- [x] UI: **Tests** button; suite editor (cases, inputs, checks), run with live progress and Stop, report, previous runs
- [x] Tests: backend (assertions, runner, API via an in-memory database fake, store queries) and frontend (editor, report, modal flows, executor, API client)

---

## Post-MVP2.5 — Hardening & Signal

Source: `docs/future/2026-11-24 AiFlow - Future Directions.md` (§4 Phase 1, adjusted in §8.5). Full task descriptions are in `BACKLOG.md` (Tasks 36–45). Work in order; complete each task (including tests) before the next.

### Iteration 5 — Safety and Contracts

#### Task 36 — Safe Expression Evaluator `[x]`

- [x] Replace `eval()` in `select_condition_edges` with a safe evaluator
- [x] Report evaluation errors in the trace (no silent fall-through)
- [x] pytest incl. escape attempts
- [ ] (optional, deferred) "test expression" box in CONDITION properties panel

#### Task 37 — Edge-Condition Contract `[x]`

- [x] Decide + document expression language and result → edge mapping
- [x] Remove/document hardcoded label vocabulary
- [x] Align generator prompt, validator, simulator, properties panel
- [x] Validator warns on unmatchable CONDITION edges
- [x] Update docs/README

#### Task 38 — Request Size Limits `[x]`

- [x] Limits on nodes / edges / config size (all workflow endpoints)
- [x] Request body size limit
- [x] UI error messages + oversized import rejected
- [x] pytest per limit

### Iteration 6 — Signal

#### Task 39 — Static Analysis / Lint Engine `[x]`

- [x] Rule set with `severity`, `node_id`, `rule_id`, `fix_hint`
- [x] Lint endpoint + pytest per rule
- [x] Findings panel + node badges in UI

#### Task 40 — Data Contracts `[x]`

- [x] Optional `input_schema` / `output_schema` on nodes (frontend + backend)
- [x] Generator fills them; validator checks edge compatibility
- [x] Properties panel view/edit

#### Task 41 — Schema-Conformant Mock Outputs `[x]`

- [x] Mock handlers conform to `output_schema` (seeded, deterministic)
- [x] Per-node `mock_output` override
- [x] CONDITION branches taken on real data

### Iteration 7 — Persistence and Cleanup

#### Task 42 — Persist Traces and Runs `[x]`

- [x] Supabase tables + RLS; `schema.sql` change **and** matching `update_YYYYMMDDhhmm.sql`
- [x] API: list / fetch / delete runs; retention + size caps
- [x] UI: run history + replay

#### Task 43 — Fix `user-pick` Condition Mode `[x]`

- [x] Pause at CONDITION and let user pick an edge (reuse HITL pause/resume)
- [x] Tests incl. an end-to-end HITL pause test

#### Task 44 — Spike: Async Suite Runs on Lambda `[x]`

- [x] Design note in `docs/` (timeouts, job model, storage, usage accounting)

#### Task 45 — Cleanup and Doc Consistency `[x]`

- [x] Fix redundant branch in `mock_evaluate`
- [x] Audit broad `except Exception` handlers
- [x] BACKLOG.md / TASKS.md synced (Tasks 21–33 marked done in backlog)

**Follow-ups found during this iteration** (not scheduled; details in `docs/AiFlow - Async Suite Runs Design.md` §9, tracked in `BACKLOG.md` Tasks 46–50):

- Pause/resume state is in-memory, so it is unreliable on Lambda (Task 46)
- `increment_usage` is not atomic (Task 47)
- The simulate guard is 120 s but API Gateway cuts requests at 30 s (Task 48)
- `App.tsx` was calling Validate / re-run / resume without an auth token. Fixed in this iteration

---

## MVP2.5 — Private Deployment (completed)

Auth (Supabase), access control, admin page, landing page, SEO, AWS Lambda + Amplify deployment — done. Tasks 34 (email templates) and 35 (auth rate limits) were **skipped** pending custom SMTP / plan upgrade; see `BACKLOG.md` → Future Enhancements.

---

## MVP2 — Workflow Simulator (completed)

Full spec: `docs/AiFlow - MVP2.md`

---

## Iteration 1 — Backend Simulation Engine

### Task 21 — Simulation Engine `[x]`

- [x] Pydantic models: `NodeExecution`, `ExecutionTrace`, `SimulationSettings`, `SimulateRequest`
- [x] `simulator.py`: topological sort, handler dispatch, trace builder
- [x] `node_handlers.py`: mock handler per NodeType
- [x] `POST /api/workflows/simulate` endpoint
- [x] Extension point stubbed for future real-LLM calls (`settings.llm_mode == 'real'` → `NotImplementedError`)
- [x] pytest coverage (valid trace, START→END, LLM mock shape, CONDITION expression, cycle detection, disconnected node)

### Task 22 — HITL Simulation `[x]`

- [x] Auto-approve mode: immediate `{ approved: true, reviewer: "auto" }`
- [x] Pause mode: `POST /api/workflows/simulate/resume` endpoint
- [x] pytest: auto-approve unbroken trace; pause returns paused status

---

## Iteration 2 — Frontend Simulator UI

### Task 23 — SimulateModal `[x]`

- [x] Settings form (HITL mode, CONDITION mode, display mode, delay slider)
- [x] Input textarea (JSON, client-side validated)
- [x] API call + loading state

### Task 24 — TracePanel `[x]`

- [x] Steps list with status badges and durations
- [x] Expand/collapse step for input/output JSON
- [x] Clear trace button
- [x] Next Step button (manual mode)

### Task 25 — Canvas Node Highlighting `[x]`

- [x] `executionStatus` prop on `WorkflowNodeComponent`
- [x] CSS status rings (pending/running/success/error/waiting)
- [x] Animated playback (setTimeout chain in App)
- [x] Instant mode (all at once)

### Task 26 — Toolbar + App Wiring `[x]`

- [x] Simulate button in toolbar
- [x] `showSimulateModal` + `simulationTrace` state
- [x] Playback logic + clear-on-new

---

## Iteration 2b — Simulation Evaluation

### Task 30 — Simulation Evaluator Backend `[x]`

- [x] `SimulationEvaluation` model: `score`, `summary`, `strengths`, `issues`, `recommendations`
- [x] `evaluate: bool = False` in `SimulationSettings`
- [x] `evaluation: SimulationEvaluation | None` in `SimulateWorkflowResponse`
- [x] `backend/app/services/evaluator.py`: `mock_evaluate()` + `llm_evaluate()` (real LLM, uses existing provider)
- [x] Route calls evaluator after complete trace when `settings.evaluate=True`
- [x] Skip evaluation when trace is paused or errored
- [x] pytest: mock shape, LLM path calls provider, evaluate=True includes result, evaluate=False returns null, paused/error skips

### Task 31 — Evaluation UI `[x]`

- [x] "Evaluate results" toggle in SimulateModal (default off)
- [x] `EvaluationPanel` component: score badge, summary, strengths/issues/recommendations
- [x] Score colour-coding (≥7 green, 4–6 amber, ≤3 red)
- [x] Panel shown alongside TracePanel when evaluation present
- [x] HITL approve/reject controls in trace panel

---

## Iteration 3 — Testing + Docs

### Task 27 — Simulation Unit Tests `[x]`

- [x] SimulateModal renders + submits (14 tests: rendering, JSON validation, submission paths)
- [x] TracePanel renders + expand/collapse + HITL bar + clear (18 tests)
- [x] Node status CSS classes + opacity (9 tests in WorkflowNodeComponent.test.tsx)
- [x] Manual step-through cursor (5 tests — Next Step visibility + onAdvanceStep callback)

### Task 28 — Simulation E2E Tests `[x]`

- [x] Simulate button → modal opens (+ Cancel/✕ close, settings controls visible)
- [x] Submit → trace panel with steps (instant mode: step names, status badge, expand detail, Clear)
- [x] Animated mode smoke tests (steps animate in, complete status reached)
- [x] Manual step-through (Next Step visible, advances cursor, hides when done)
- [x] HITL auto-approve no pause (complete status, no pause bar, HITL step shows success)
- [x] State reset — New workflow clears trace panel
- [x] Fixed 4 pre-existing app.spec.ts failures (START/END ambiguity, HITL label, Complex badge, Untitled Workflow name)

### Task 29 — README Update `[x]`

- [x] Simulator section in README
- [x] Mock handler behavior documented
- [x] Future real-LLM path noted

---

## Iteration 4 — Example Library

### Task 32 — Categorised Example Workflows `[x]`

- [x] `examples/easy/email-auto-reply.json` — 3 nodes, Customer Service
- [x] `examples/easy/sentiment-classifier.json` — 5 nodes, Marketing
- [x] `examples/easy/data-enrichment.json` — 4 nodes, Sales/CRM
- [x] `examples/medium/customer-support.json` — 8 nodes, Customer Service (enhanced from root)
- [x] `examples/medium/content-moderation.json` — 7 nodes, Platform/Social
- [x] `examples/medium/invoice-processing.json` — 7 nodes, Finance
- [x] `examples/medium/hr-onboarding.json` — 7 nodes, HR
- [x] `examples/complex/ai-research-agent.json` — 12 nodes, Research & Analytics
- [x] `examples/complex/supply-chain-monitor.json` — 11 nodes, Supply Chain
- [x] `examples/complex/multi-agent-customer-journey.json` — 12 nodes, E-commerce/CRM

### Task 33 — Example Picker UI `[x]`

- [x] `ExamplePickerModal` component — replaces direct "Example" toolbar button
- [x] Group by difficulty (Easy / Medium / Complex) with industry label
- [x] Card shows: name, industry, description, node count, tags
- [x] Search filters by name, industry, description, tag
- [x] On select: loads workflow and clears simulation state

---

## MVP1 Archive

See `docs/AiFlow - MVP1.md` for full MVP1 spec.
All MVP1 tasks completed — 2026-09-19.
