# AiFlow — Current Iteration

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

#### Task 42 — Persist Traces and Runs `[ ]`

- [ ] Supabase tables + RLS; `schema.sql` change **and** matching `update_YYYYMMDDhhmm.sql`
- [ ] API: list / fetch / delete runs; retention + size caps
- [ ] UI: run history + replay

#### Task 43 — Fix `user-pick` Condition Mode `[ ]`

- [ ] Pause at CONDITION and let user pick an edge (reuse HITL pause/resume)
- [ ] Tests incl. an end-to-end HITL pause test

#### Task 44 — Spike: Async Suite Runs on Lambda `[ ]`

- [ ] Design note in `docs/` (timeouts, job model, storage, usage accounting)

#### Task 45 — Cleanup and Doc Consistency `[ ]`

- [ ] Fix redundant branch in `mock_evaluate`
- [ ] Audit broad `except Exception` handlers
- [x] BACKLOG.md / TASKS.md synced (Tasks 21–33 marked done in backlog)

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
