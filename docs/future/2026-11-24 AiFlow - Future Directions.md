# AiFlow — Future Directions

Written after reviewing the repo (MVP1 design, MVP2 simulator + evaluator, MVP2.5 gated deployment), the backlog, and the backend services.

## About this document (read first)

- **Snapshot dated 2026-11-24.** The file name carries the date on purpose: it records what the repo looked like and what was suggested at that time. Do not edit it to track progress. Write a new dated file for new brainstorms.
- **Brainstorm, not a plan.** Nothing here is committed until it is moved into `BACKLOG.md` / `TASKS.md`.
- **Where to start:** §1 (current state and honest gaps), §4 (recommended sequencing), §7 (quick wins). The `eval()` security item in §1 is the one that should not wait.
- **Code references may be stale.** Re-verify file/function names before acting on them.
- **Specific, dated questions** (e.g. the desktop/Tauri question) are logged separately in `AiFlow - Questions and Answers.md` in this folder.

---

## 1. Where AiFlow is today

| Capability | State |
|---|---|
| Describe → Generate → Design | Done. NL generation, multi-turn chat (`/workflows/chat`), canvas, palette, properties, undo/redo, JSON import/export, report export |
| Validate | Done. Structural rules only (START/END, IDs, edges, required config) |
| Simulate | Done, but **mock-first**. All handlers except LLM return canned output. LLM has `mock`/`real` modes. HITL pause/resume exists. Condition branching: expression / random / user-pick (user-pick currently just takes the first edge) |
| Evaluate | Done, thin. `mock_evaluate` is derived from node-type presence only (a heuristic score). `llm_evaluate` has the LLM read a trace and write 1 score + prose |
| Example library | 10 examples (easy/medium/complex) |
| Access / ops | Supabase auth, access requests, admin page, per-user usage limits, rate limiting, analytics |
| LangGraph export | **Stub only** (`langgraph_exporter.py` raises `NotImplementedError`) |
| Persistence | Frontend localStorage + JSON download. Traces are not stored |

### Honest observations

1. **Simulation proves the wiring, not the quality.** With mock outputs, a trace says "the graph is connected", which the validator already says. The interesting question — *does this workflow produce good results?* — is not answered anywhere.
2. **The evaluator judges a design from its trace, but the trace carries almost no signal.** An LLM reading mocked outputs can only comment on structure. A single 1–10 score is also non-reproducible and not comparable between runs.
3. **There is no way out of the tool.** No working export means AiFlow is a diagram tool with a good UX, not something that ends in running software.
4. **No feedback loop.** Generate → edit → simulate → evaluate produces recommendations, but nothing applies them.
5. **Technical debt worth fixing early**
   - `node_handlers.select_condition_edges` uses Python `eval()` on a user-supplied expression with `__builtins__` emptied. That is a known-escapable sandbox (e.g. via `().__class__.__mro__...`). Since workflows are user-authored/LLM-generated and the server is publicly reachable, replace with a safe expression evaluator (`simpleeval`, `asteval`, or a tiny AST whitelist walker). This is the single most important item in this document.
   - `condition_mode=user-pick` silently falls back to the first edge; docs say it pauses.
   - Docs/specs say "JS expression" for conditions; the implementation is Python. Pick one and document it.
   - `BACKLOG.md` still shows MVP2 tasks as `[ ]` while `TASKS.md` shows them `[x]`.
   - Mock evaluator score formula has a redundant branch (`+1` for condition, then `-1` if not condition).

---

## 2. The big idea: from simulator to *workflow quality platform*

The strongest direction is not "a better simulator". It is:

> **AiFlow is where you design an agentic workflow, prove it works against a dataset, and ship it as code.**

That is design → **test/evaluate** → **export/deploy** → **observe**, i.e. the missing half of the lifecycle. Simulation becomes one of several execution backends rather than the end goal.

```
Describe → Generate → Design → Test (datasets + evals) → Improve (AI-assisted) → Export / Deploy → Observe
```

---

## 3. Idea tiers

### Tier A — Make what exists trustworthy and useful (small, high payoff)

**A1. Replace `eval()` with a safe expression engine.** See above. Also add a "test this expression" box in the CONDITION properties panel against sample data.

**A2. Rule-based "static analysis" before any LLM.** A deterministic linter far richer than the validator, so the LLM evaluator is not doing work code can do:
- Unreachable nodes / dead-end paths (no path to END)
- CONDITION with a single outgoing edge, or branches without conditions
- API/DATABASE/TOOL with no failure branch
- HITL placed *after* an irreversible node (DATABASE write, API POST)
- LLM node without output schema feeding a CONDITION that reads fields from it
- Data-flow check: a node reads `{{field}}` that no upstream node produces
- Cost/latency estimate per path (sum of node-type heuristics)
- Cycle detection with a suggestion for a bounded-loop pattern

Output: structured findings with `severity`, `node_id`, `rule_id`, `fix_hint` — clickable on the canvas. This replaces the hardcoded text in `mock_evaluate`.

**A3. Typed data contracts between nodes.** Optional `input_schema` / `output_schema` (JSON Schema) on nodes. The generator fills them in; the validator checks edges for compatibility; the mock simulator generates outputs that *conform to the schema* instead of `"mock tool output"`. This one change makes simulation meaningfully better and unlocks a lot below.

**A4. Schema-conformant mock data.** Use A3 (or an LLM once, cached) to produce realistic fixtures per node ("API node `GET /orders/{id}` → plausible order JSON"). Allow the user to pin fixtures per node (`mock_output` in config). Now the CONDITION expressions actually take real branches.

**A5. Fix `user-pick` condition mode and add true step-through pause** (reuse the HITL pause/resume mechanism).

**A6. Persist traces and runs** (Supabase, per user, RLS). Prerequisite for nearly everything in Tier B.

### Tier B — Evaluator done properly (the differentiator)

Evaluation of agentic workflows is the unsolved, valuable part. Instead of "an LLM gives a score", build:

**B1. Test datasets / test cases per workflow.**
A workflow gets a set of cases: `{input, expected_output | assertions, tags}`. Cases can be hand-written, imported (CSV/JSONL), or LLM-generated ("give me 20 diverse inputs including 5 adversarial ones and 3 edge cases").

**B2. Assertions and graders, mixed deterministic + LLM.**
- Deterministic: JSON-schema match, regex, contains, numeric range, "path taken includes node X / excludes node Y", max steps, max cost
- LLM-as-judge with rubric (per case or global), with pairwise comparison instead of absolute scores where possible
- Per-node assertions ("the classify node returns one of [billing, tech, other]")

**B3. Run suites, get a report, not a vibe.**
Pass-rate, per-node failure heat map on the canvas, path coverage (which branches were never exercised), latency/cost per case, flaky-case detection (run N times). Replace the single score with a scorecard: *correctness, robustness, coverage, cost, latency, safety*.

**B4. Branch & path coverage.** Like code coverage for a workflow: "your CONDITION `refund > 500` never went to the HITL branch in any of your 20 cases." Cheap to compute from traces; very persuasive visually.

**B5. Run comparison / regression.** Diff two runs (or two workflow versions) on the same dataset: which cases flipped pass→fail, which paths changed, cost delta. Already flagged in MVP2 §8 as "trace diff"; this is the full form.

**B6. Prompt A/B and model comparison.** Same workflow, same dataset, swap one LLM node's prompt or model, compare scorecards. "Is the cheaper model good enough for the classify node?" is a real question teams pay to answer.

**B7. Failure injection / chaos mode.** Simulation setting that makes API/DB/TOOL nodes return 500s, timeouts, empty results, malformed JSON, or hostile content, and checks whether the workflow degrades gracefully. This is the *right* use of a simulator and directly checks the "no failure branch" smell from A2.

**B8. Adversarial / safety evaluation.** Prompt-injection payloads in inputs (especially into RAG documents and API responses), PII leakage checks, jailbreak cases, tool-misuse cases. Output a per-node "injection exposure" report: which nodes pass untrusted text to an LLM that can then trigger a TOOL/API/DATABASE write.

**B9. Calibrated judge.** Let users label 10–20 outputs good/bad; measure judge agreement; surface the judge's reliability. Without this, LLM-as-judge numbers are untrustworthy.

### Tier C — Close the loop with AI-assisted improvement

**C1. Evaluate → Propose patch → Apply.** Findings and recommendations become *structured edits* to the Workflow Model (`add_node`, `add_edge`, `set_config`, …) shown as a visual diff on canvas with accept/reject per change. The model is already immutable with undo/redo, so an "apply patch" is cheap and safe.

**C2. Conversational editing of an existing workflow** ("add a human approval before the refund step", "split classify into two stages"). `chat_workflow` already accepts `current_workflow`; extend it to return patches rather than a full regenerated workflow so layout and user edits are preserved.

**C3. Auto-optimise a node's prompt against the dataset** (DSPy/TextGrad-style): propose prompt variants, run the suite, keep the best, show the delta. Needs B1–B3.

**C4. Explain mode.** "Explain this workflow to a non-technical stakeholder" / "what could go wrong here?" / "generate runbook and docs" — generated from the model, exportable as Markdown/PDF. Cheap, and useful to the audience that approves workflows.

**C5. Pattern library & refactoring suggestions.** Recognise common agent patterns (router, plan-and-execute, reflection/critic loop, human gate, map-reduce, guardrail wrapper) and offer to insert or convert to them. Gives the generator a vocabulary beyond 10 node types.

### Tier D — Get workflows out of the tool (turn a diagram into software)

**D1. Real LangGraph exporter** (stub exists). Generate a runnable Python project: `graph.py`, `state.py` (TypedDict from the data contracts in A3), `nodes/*.py`, `requirements.txt`, `.env.example`, a CLI entry point, and the test dataset as `pytest` cases. HITL → `interrupt`, CONDITION → conditional edges, RAG/TOOL/API/DB → typed stubs with TODOs. The workflow model remains source of truth.

**D2. Additional targets via the same adapter pattern**: plain Python (no framework), OpenAI Agents SDK, CrewAI, n8n / Temporal / Step Functions / Airflow-style JSON, and **MCP**: export each TOOL/API node as an MCP tool definition.

**D3. Import (round-trip).** Parse an existing LangGraph / n8n / Mermaid definition into the model so AiFlow can be used on workflows people already have — important for adoption. Even a *Mermaid import/export* is a cheap crowd-pleaser (docs, READMEs, PRs).

**D4. Round-trip with code review**: export to Git (a `workflow.aiflow.json` + generated code), with GitHub Action that runs the evaluation suite on PRs and posts the scorecard/diff as a comment. "CI for agent workflows."

**D5. Lightweight real execution** (opt-in, sandboxed): "live mode" where API/TOOL nodes call real endpoints with user-supplied secrets stored server-side, with allowlists, dry-run for writes, per-run budgets. This is where cost and security controls from MVP2.5 become essential. Do it after B and D1; do not make it the next milestone.

### Tier E — Observability and the production feedback loop

**E1. Trace ingestion.** Accept traces from the *exported* code (OpenTelemetry / OpenInference spans, or a tiny SDK) and render them on the same canvas with the same trace panel. The visual model becomes the way you *debug production*. This is a natural extension of the existing trace format.

**E2. Production → test case.** "Add this real failing run to the dataset" with one click (with PII scrubbing). Dataset grows from reality; regressions become permanent tests.

**E3. Drift & cost dashboards** per node: latency p50/p95, token cost, error rate, branch distribution shift (e.g. escalation rate doubled this week).

**E4. Guardrail suggestions from real traffic** ("90% of HITL approvals are auto-approvable — consider a confidence threshold").

### Tier F — Product surface, collaboration, and ecosystem

- **Cloud workflows + versioning + diff** (already in the backlog): named versions, visual diff, fork, restore. Prerequisite for B5 and D4.
- **Share by link** (read-only) — good for the portfolio use case: a visitor opens a pre-built workflow plus its evaluation report without needing to log in.
- **Comments / review mode**: reviewers annotate nodes; approval gates for production workflows.
- **Sub-workflows / composition**: a node that embeds another workflow; reusable components with typed inputs/outputs. Needed to scale beyond ~15 nodes (the complex examples are already 12).
- **Parallel / map nodes and bounded loops** (explicitly deferred in MVP2): fan-out/fan-in, `for_each`, retry-with-limit, reflection loops with max iterations. Real agents loop; today simulation rejects cycles. A *bounded loop* construct keeps determinism and analysability.
- **Memory / state node and multi-agent primitives**: shared state schema, agent roles, supervisor patterns.
- **Governance view**: for each workflow list data sources touched, PII classes, external calls, write operations, human gates. Exportable as a risk assessment (EU AI Act / SOC2-flavoured checklist). This is where an "evaluator" becomes sellable to larger organisations.
- **Cost modeller**: before running, estimate $ per run and per 1k runs given model prices and expected token sizes; show on the canvas as a per-path cost.
- **Template marketplace / import from gallery**; community-contributed example workflows with their datasets and scorecards.
- **Plugin node types** (data-driven definitions already exist in `nodeDefinitions.ts`): allow loading custom node definitions from JSON so users can add `SLACK`, `EMAIL`, `WEB_SEARCH`, etc. with schema + mock behaviour + export template.

---

## 4. Recommended sequencing

**Phase 1 — Foundations (hardening + signal)**
1. Replace `eval()` with a safe expression evaluator (+ tests for escape attempts)
2. Static analysis / lint engine (A2) with clickable findings
3. Data contracts + schema-conformant mock outputs (A3, A4)
4. Persist traces/runs (A6); fix `user-pick`; reconcile BACKLOG/TASKS and docs

**Phase 2 — Evaluator becomes the product**
5. Datasets + assertions + suite runner (B1–B3)
6. Coverage + failure injection (B4, B7)
7. Run comparison (B5), then model/prompt A/B (B6)

**Phase 3 — Out of the tool**
8. LangGraph exporter generating code + pytest suite from the dataset (D1)
9. Patch-based AI improvements (C1, C2)
10. Mermaid import/export (D3) and Git/CI integration (D4)

**Phase 4 — Production loop**
11. Trace ingestion + production-to-test-case (E1, E2)
12. Cloud storage, versioning, share links (F)

Why this order: Phase 1 makes simulation give real signal; Phase 2 turns that signal into a measurable quality story; Phase 3 gives the user something to take away; Phase 4 closes the loop and creates retention.

---

## 5. Positioning options

| Positioning | What it emphasises | Competes with |
|---|---|---|
| **"Postman/Playwright for agent workflows"** — design, test, regression-check | Tiers A+B+D4 | LangSmith evals, Promptfoo, Braintrust (but those are code-first, none start from a visual model) |
| **"Design-to-code for agents"** | Tiers A+D | n8n/Flowise/Langflow (those run the flow; AiFlow would export clean, reviewable code instead of locking you into a runtime) |
| **"Agent design review & governance"** | Static analysis, safety eval, governance view, explain mode | Mostly nobody; appeals to enterprises and consultants |
| **"Observability with a map"** | Tier E | LangSmith, Langfuse, Arize Phoenix (they show trace lists; a canvas-first view is a differentiator) |

The most defensible and most aligned with the existing codebase: **"Test and review agent workflows before you build them, then export the code"** — i.e. positions 1+2+3 combined. It builds directly on what is already built (model, trace, evaluator, LLM provider, auth/limits) and avoids competing head-on as yet another runtime.

For the portfolio/job-search purpose from MVP2.5, the strongest demonstrable slice is small: **safe expression engine + lint findings on canvas + a 10-case dataset run with a pass/fail heat map + a LangGraph export**. It tells a complete story in a 2-minute demo video.

---

## 6. Risks and things to avoid

- **Scope creep into a runtime.** Building real execution (D5) early drags in secrets, sandboxing, queues, and billing. Keep simulation + export first.
- **LLM-judged numbers without calibration** (B9) will be dismissed by technical audiences; always show the evidence (trace, rubric) beside the score and prefer deterministic assertions.
- **Non-determinism.** Evaluation needs seeded mocks, cached fixtures, and repeat-runs to be comparable. Design for it from A3/A4.
- **Prompt injection of AiFlow itself.** Workflow descriptions, example imports, and traces are fed to LLMs in the generator/evaluator. Treat imported workflows and trace contents as untrusted input; keep the evaluator's output strictly schema-validated (partly done in `llm_evaluate`).
- **Cost exposure.** Dataset runs multiply LLM calls by N cases. Extend the existing per-user usage limits to count *suite runs*, cap cases per suite for DEMO users, and show a cost estimate before running.
- **Model growth.** Data contracts, datasets, and versions all extend the workflow JSON. Keep `version` migrations explicit and keep new fields optional.

---

## 7. Quick wins (each ≤ ~1–2 days)

1. Safe expression evaluator
2. Mermaid export of a workflow
3. Findings from static rules shown as badges on nodes
4. Per-node `mock_output` override in the properties panel
5. Branch-coverage highlight (edges never taken) from a single trace
6. "Explain this workflow" button (Markdown output)
7. Export trace + evaluation as a single shareable HTML report
8. Rough cost/latency estimate shown per path
9. Sync BACKLOG.md with TASKS.md; fix doc/implementation mismatch on condition expression language

---

## 8. Addendum (2026-11-24, same day) — verification, corrections, and gaps not covered above

Added at the owner's request after re-checking §1–§7 against the code. Sections 1–7 are left as originally written; this section adds to them.

### 8.1 Verified claims

- `node_handlers.py:167` does `eval(expression, {"__builtins__": {}}, output_data)`. Confirmed. Note the broad `except Exception: pass` around it: a failed or hostile expression silently falls through to "follow all edges", so errors are invisible to the user. The safe replacement should *report* evaluation errors in the trace instead.
- `node_handlers.py:157-159`: `USER_PICK` returns `outgoing_edges[:1]`. Confirmed.
- `langgraph_exporter.py:35` raises `NotImplementedError`. Confirmed.
- BACKLOG.md has 14 open and 20 done items; TASKS.md has 77 done and none open. Confirmed that the two are out of sync.

### 8.2 Corrections / precision

- **HITL:** the handler (`_handle_hitl`) always auto-approves. Pause/resume lives in `simulator.py` and the resume route, so "pause/resume exists" in §1 is accurate only when that path is triggered; the node handler itself never pauses. Worth one test that proves the pause path end to end.
- **Mock evaluator:** the redundant `+1` / `-1` branch noted in §1 is a symptom of a bigger point: the score is a function of node-type presence only, so it cannot differ between two workflows of the same shape. Treat it as a placeholder, not something to tune.
- **Condition language:** besides the doc/implementation mismatch, edge labels are matched against a hardcoded vocabulary (`true/yes/complex/1`, `false/no/simple/0`). A workflow with edges labelled `approved` / `rejected` can never be routed by an expression and silently falls back to "follow all edges". This needs a defined contract (see 8.3 #2).

### 8.3 Additional gaps found in the code

1. **No size limits on the Workflow body.** `schemas/requests.py` caps `description` (2000 chars) and chat history (50 messages), but `Workflow.nodes`, `Workflow.edges`, and node `config` have no limits. `/validate` and `/simulate` accept arbitrarily large graphs, and the evaluator puts workflow content into an LLM prompt. Add limits (e.g. nodes ≤ 100, edges ≤ 300, config size cap) plus a request-body size limit at the app/proxy level. Cheap, and belongs in Phase 1 next to the `eval()` fix.
2. **Edge-condition contract.** Define what `edge.condition` means (label vs. boolean vs. expression result). Make the generator, validator, simulator, and properties panel agree, and have the validator flag a CONDITION whose outgoing edges cannot be matched by its expression.
3. **Swallowed errors.** The broad `except Exception` pattern in routing (8.1) should be audited elsewhere in `simulator.py` and the providers, so failures show up in traces instead of producing a plausible-looking run.
4. **Lambda deployment constraints.** The backend runs on AWS Lambda (MVP2.5). Long simulations, dataset suite runs (B3), and LLM calls are bound by Lambda and API Gateway timeouts (API Gateway's integration limit is ~29 s by default; re-verify). Suite runs need an async job model (start → job id → poll status), not a single request. Design this before building B1–B3, because it shapes the API, storage (A6), and usage accounting.
5. **Structured LLM output.** Generator and evaluator parse model output. Provider-native structured output / JSON-schema mode would remove a class of parse failures and tighten the prompt-injection boundary noted in §6.
6. **Provider capability visibility.** `providers/base.py` has optional capabilities that raise `NotImplementedError` (evaluation then falls back to mock). Report which capabilities the configured provider supports, so "mock fallback" is never a silent downgrade for users.

### 8.4 New ideas not mentioned above

**Product / UX**
- **Run history and replay:** step a stored trace forward/backward on the canvas (scrubber), not just view a final list. Pairs with A6.
- **Assumptions panel:** the generator lists the assumptions it made (data sources, auth, thresholds) so the user can confirm or correct them before designing. Reduces silent invented structure.
- **Deterministic "ask the workflow" Q&A:** "which nodes can write to the database?" answered by a graph query, with the LLM only phrasing the answer.
- **Accessibility pass:** keyboard-only canvas editing, screen-reader labels for nodes/edges, contrast check on node-type colours.
- **Internationalisation:** descriptions in other languages already work through the LLM; UI strings do not. Low priority; cheap to prepare if strings live in one place.

**Quality / engineering**
- **Property-based and fuzz tests** for the validator, expression engine, and JSON import (random graphs, hostile configs, huge inputs). Complements the escape-attempt tests proposed in A1.
- **Golden tests for generation:** a small set of prompts whose generated workflows are checked by the lint engine (A2) rather than by string match, run on a schedule to catch model/prompt regressions.
- **Published Workflow JSON Schema** (generated from the Pydantic model) with explicit `version` migrations. Enables editor validation, external tooling, and the import/export items in Tier D.
- **Frontend/backend type contract:** generate TS types from the OpenAPI schema so `models/` and `backend/app/models/` cannot drift.
- **Dependency and secret scanning in CI** (`pip-audit`, `npm audit`, a secret scanner); proportionate for a project handling auth and LLM keys.

**Operations / business**
- **LLM spend guardrails:** a global monthly budget kill-switch and admin alert, in addition to per-user limits, so one abusive account or a loop bug cannot cause a surprise bill.
- **Audit log** for admin actions (approve/deny access, limit changes). Small table, supports the governance story in Tier F.
- **Account lifecycle:** user data export and deletion (GDPR-style), since email and usage data live in Supabase.
- **In-app feedback channel:** "report a problem / suggest a node type", with opt-in attachment of the current workflow, feeding the backlog.
- **Analytics transparency:** document exactly what `useAnalytics` collects and keep workflow content out of events.

### 8.5 Suggested adjustment to §4 (Phase 1)

1. Safe expression evaluator **and** surfaced evaluation errors (A1, 8.1)
2. Define the edge-condition contract (8.3 #2), together with item 1, since it changes what the evaluator must support
3. Request size limits on workflow/config payloads (8.3 #1)
4. Lint engine (A2); data contracts + schema-conformant mocks (A3, A4)
5. Persist traces/runs (A6); fix `user-pick`; sync BACKLOG/TASKS

Before Phase 2, add a short **design spike for async suite runs on Lambda** (8.3 #4). Without it, B1–B3 will hit timeouts and force a rework.

### 8.6 Interaction with the desktop (Tauri) question

See `AiFlow - Questions and Answers.md` (Q1). Two cross-effects:
- Request-size limits and the async job model matter more with desktop clients, because old installed clients cannot be forced to upgrade. Keep new endpoints additive and versioned.
- Dataset/suite runs are the best candidate for a desktop-only local-LLM mode (removes LLM cost), so design the suite runner with a provider-selectable backend from the start.
