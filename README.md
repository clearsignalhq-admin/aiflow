# AiFlow — AI Workflow Designer

**GitHub:** https://github.com/fuvito/aiflow

A developer tool for visually designing, generating, and exporting AI/agentic workflows.

Describe a workflow in natural language → an LLM generates the structured graph → you edit, validate, simulate, and export it as JSON.

---

## What Is This?

AiFlow is a visual node-based editor for designing AI agent workflows. Developers can:

- **Describe** a workflow in plain English and generate it instantly with an LLM
- **Design** workflows visually — drag nodes onto a canvas and connect them
- **Configure** each node (LLM prompts, API endpoints, RAG settings, conditions, etc.)
- **Validate** the workflow for structural correctness
- **Simulate** — run a mock execution and inspect each step's input/output in a trace panel
- **Save/Export** as clean, versioned JSON — or **Import** previously saved workflows
- **Browse examples** — 10 categorised workflows across Easy / Medium / Complex difficulties

### Node Types

| Type | Purpose |
|------|---------|
| `START` | Entry point |
| `END` | Exit point |
| `LLM` | Language model call |
| `TOOL` | Tool / function call |
| `API` | External HTTP API |
| `DATABASE` | Database query |
| `RAG` | Retrieval-augmented generation |
| `CONDITION` | Conditional branching |
| `HITL` | Human-in-the-loop review |
| `TRANSFORM` | Data transformation |

---

## Architecture

The internal **Workflow Model** is the source of truth. React Flow is a rendering layer only.

```
Workflow Model (TypeScript + Pydantic)
      │
      ├── React Flow Adapter  →  Visual Canvas
      ├── JSON serializer     →  workflow.json
      ├── Simulator           →  BFS mock execution, HITL pause/resume, evaluation
      └── Future: LangGraph Adapter
```

```
frontend/     React + TypeScript + Vite + React Flow
backend/      Python + FastAPI + Pydantic + OpenAI SDK
examples/     Example workflow JSON files
docs/         Product spec
```

---

## Prerequisites

| Tool | Version |
|------|---------|
| Node.js | 18+ |
| Python | 3.11+ |
| npm | 9+ |
| OpenAI API key | Required for Generate feature |

---

## Quick Start

### 1. Clone

```bash
git clone <repo-url>
cd aiflow
```

### 2. Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Edit `backend/.env` and set your API key:

```
LLM_API_KEY=sk-...
```

Start the backend:

```bash
# Windows — double-click run.bat, or:
.venv\Scripts\uvicorn app.main:app --reload

# macOS / Linux
uvicorn app.main:app --reload
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**.

---

## Running Tests

```bash
# Backend (443 tests)
cd backend
.venv/Scripts/pytest -v       # Windows
pytest -v                     # macOS / Linux

# Frontend unit tests (265 tests)
cd frontend
npm test

# Frontend E2E tests (34 tests — requires dev server)
cd frontend
npx playwright test
```

---

## Using the App

### New Workflow
Click **New** → canvas resets to `START → END`.

### Browse Examples
Click **Examples** → an example picker opens with 10 pre-built, simulation-ready workflows:

| Difficulty | Nodes | Workflows |
|------------|-------|-----------|
| Easy | 2–5 | Email auto-reply, Sentiment classifier, Data enrichment |
| Medium | 6–10 | Customer support, Content moderation, Invoice processing, HR onboarding |
| Complex | 11+ | AI research agent, Supply chain monitor, Multi-tier customer journey |

Search by name, industry, or tag. Click any card to load the workflow onto the canvas. Every example ships with a pre-populated **sample input**, so you can click **Simulate → Run Simulation** immediately without typing anything.

### Add Nodes
Drag a node type from the left panel onto the canvas.

### Connect Nodes
Drag from the bottom handle of one node to the top handle of another.

### Configure Nodes
Click a node → edit its name and config in the right panel. Press **Delete** to remove a selected node.

### Validate
Click **Validate** → errors and warnings appear in a panel below the canvas. The button badge shows the count.

Validate also runs a deterministic **design lint** (no LLM involved). Findings appear under *Design findings*; click one to select the node, and a badge on the node shows its finding count. Rules: unreachable nodes, dead ends (no path to END), decisions with fewer than two or unlabelled branches, API/database/tool calls with no failure branch, human review placed after an irreversible write (POST/PUT/PATCH/DELETE, INSERT/UPDATE/DELETE…), conditions reading fields their upstream node does not declare, `{{placeholders}}` nothing upstream produces, and cycles. The panel also shows a rough latency/cost estimate across all paths (fixed per-node-type heuristics, not measurements).

#### Data contracts

Nodes can declare an optional **input schema** and **output schema** (Properties panel → *Data contract*), written as JSON Schema (supported keywords: `type`, `properties`, `required`, `items`, `enum`, `const`, `default`, `example`, `minimum`, `maximum`, `minItems`, `maxItems`).

- Validate warns when a schema is malformed, or when connected nodes disagree (a required input field that is not produced upstream, or a field with different types)
- The AI generator fills in output schemas for LLM, API, TOOL, RAG, DATABASE and TRANSFORM nodes
- During simulation, a node with an output schema produces **mock data that matches it** instead of a canned string. Values are seeded by the simulation `seed` (default 0) and the node id, so a run is reproducible and CONDITION expressions take real branches
- **Mock output (pinned)** on a node pins an exact output instead. Precedence: pinned mock output > output schema > default mock. Real-LLM mode is never overridden
- Schemas are optional: workflows without them behave as before

### Simulate

Click **Simulate** → configure settings → click **Run Simulation**. The backend executes a mock BFS traversal of your workflow graph from `START` to `END`. Results appear in the right sidebar panel (which replaces the Properties panel for the duration of the simulation), keeping the canvas fully visible.

#### Sample Input

The **Sample input** field accepts a JSON object that is passed to the `START` node as the initial data. It flows through the workflow and is transformed by each node.

- **Persists automatically** — the last-used input is saved as part of the workflow and restored every time you open the modal (survives page refresh via localStorage).
- **Suggest fields ✦** button — scans all node configs in the workflow (LLM prompt templates, condition expressions, API URL parameters, input schemas) and generates a JSON object with realistic placeholder values. Use this as a starting point rather than typing from scratch.

#### Simulation Settings

| Setting | Options | Default | Notes |
|---------|---------|---------|-------|
| HITL nodes | Auto-approve / Pause and wait | Auto-approve | Pause suspends execution; Approve or Reject to resume |
| CONDITION branching | Expression eval / Random / User picks | Expression eval | Evaluates the node's expression with a safe evaluator (see *CONDITION expressions*). **User picks** pauses at each decision with 2+ branches and shows one button per branch |
| Execution display | Animated / Instant / Manual | Animated | Manual adds a **Next Step** button to step through one node at a time |
| Step delay | 200–2000 ms | 600 ms | Visible in Animated mode only |
| Evaluate results | On / Off | Off | Calls LLM after a complete run to generate a quality report |

#### Mock Handlers

Every node type returns a deterministic mock output so you can explore workflows without real API keys:

| Node | Mock output |
|------|-------------|
| `START` | Passes input data through unchanged |
| `END` | Wraps preceding output as `{ result: ... }` |
| `LLM` | `{ response: "Mock LLM response for <node>", tokens_used: 42 }` |
| `TOOL` | `{ output: "Mock tool result for <node>", success: true }` |
| `API` | `{ status: 200, data: { message: "Mock API response" } }` |
| `DATABASE` | `{ rows: [{ id: 1, data: "Mock row" }], count: 1 }` |
| `RAG` | `{ documents: [{ content: "Mock document", score: 0.95 }] }` |
| `CONDITION` | Evaluates the node's `expression` and routes by edge label; if it cannot, follows all edges and records a warning on the step |
| `HITL` | `{ approved: true, reviewer: "auto" }` (auto-approve) or suspends (pause mode) |
| `TRANSFORM` | Returns input data unchanged |

Any node of type LLM, TOOL, API, DATABASE, RAG or TRANSFORM that declares an output schema or a pinned mock output uses that instead (see *Data contracts*).

#### CONDITION expressions

Expressions use a small, safe Python-style language. They are parsed and checked against a whitelist (never run as Python), so function calls, attribute tricks (`__class__`), comprehensions, f-strings and `**` are rejected.

- **Data:** the fields of the node's input are available as names, plus `input` / `output` for the whole object: `input.amount > 5000`, `input["status"] == "open"`, `items[0] == 1`
- **Operators:** `== != < <= > >= in not in`, `and or not`, `+ - * / // %`, `x if cond else y`, string/number/`True`/`False`/`None` literals (`true`/`false`/`null` also work). JavaScript operators such as `&&`, `||`, `!` are not supported
- **Routing:** the result is matched, case-insensitively, against the outgoing edges' condition labels. `True` matches `true`/`yes`, `False` matches `false`/`no`; any other value matches its text, so `"complex" if input.score > 5 else "simple"` routes to the edge labelled `complex` or `simple`. An edge labelled `else` (or `default` / `otherwise`) is the fallback
- **When it cannot route** (missing field, invalid expression, no matching label) the simulator follows all edges and shows a warning on the CONDITION step in the trace. Validate also warns about unlabelled edges, invalid expressions, and labels the expression can never produce

#### Simulation Sidebar

The sidebar has two tabs:

- **Trace** — each execution step with status (●success / ●error / ●waiting), node type, name, and duration. Click any row to expand it and see the exact input and output JSON. In Manual mode a **Next Step** button advances the trace one node at a time.
- **Evaluation** — appears when **Evaluate results** is enabled (see below). Shows a quality score and report once the run completes. The sidebar switches to this tab automatically.

#### HITL Pause / Resume

When **HITL mode → Pause and wait** is selected, execution halts at the first HITL node. An amber banner appears at the top of the sidebar showing the node name and **Approve** / **Reject** buttons. Clicking either resumes the BFS from that point with the decision recorded in the node's output. If evaluation was requested, the Evaluation tab populates once the resumed trace completes.

#### Branch choice (User picks)

With **Condition branching → User picks**, the simulation pauses at every CONDITION that has two or more branches. The sidebar shows a button per branch (`label → target`); clicking one resumes the run down that branch only. A decision with a single branch does not pause. The chosen branch is recorded on the step in the trace.

#### Run history

Every simulation is saved to your account, including its settings, input, the workflow as it was, the trace and any evaluation. Open **History** in the toolbar to see your recent runs, **Replay** one, or **Delete** it. Replay shows the stored trace on the canvas; if the nodes in the run no longer exist in your current workflow, the workflow from the run is restored (you are asked before your current work is replaced).

- Only your own runs are visible (enforced server-side and by row-level security)
- Retention: the newest 50 runs per user, for at most 30 days (`MAX_RUNS_PER_USER`, `RUN_RETENTION_DAYS`)
- A run larger than 500 KB (`MAX_RUN_BYTES`) is saved without per-step inputs/outputs and marked *trimmed*; if it still does not fit it is not saved
- Saving is best-effort: if storage is unavailable the simulation still succeeds, it just does not appear in History
- Requires the `workflow_runs` table (`supabase/update_202611241200.sql`). Resuming a paused run from another server process also needs `supabase/update_202611241400.sql` (adds `continuation`). Daily usage counting uses `supabase/update_202611241500.sql` (atomic `increment_usage` function). All three are already part of `supabase/schema.sql` for new projects; apply them in order on an existing project

#### Test suites

Click **Tests** in the toolbar to define test cases for the current workflow and run them all at once.

- **Cases:** each case has a name, an input (JSON) and any number of **checks** on the workflow's final output (the `result` of the END node reached). Use *Add case from sample input* to start from the workflow's sample input
- **Checks** (deterministic, there is no AI judge, so the same suite always gives the same answer): output equals / contains / is one of, a field exists, a number comparison, output matches a JSON schema, a safe expression is true (names: `input`, `output`, `visited`, `steps`, `status`), the case visits or skips a node, or finishes in at most N steps. Field paths are dotted, with list indexes: `order.items.0.sku`
- **Running:** every case is one **mock-mode** simulation, auto-approving human review, with a reproducible seed (a case's own seed, or run seed + its position), so branches vary across cases but results repeat exactly. The browser drives the run, a few cases at a time, and the server stores every result; **Stop** ends it early. Real-LLM suites are not supported yet
- **Report:** pass rate, per-case results with the reason each check failed, which nodes no case executed, which branches were never taken, and which nodes failures involve. Previous runs (the newest 20 per suite) can be reopened
- **Limits:** up to 50 cases per suite (10 for demo accounts) and 20 suites per user. Each case counts as one simulation toward your daily allowance, and a run that would exceed it is refused up front. A run is tied to the workflow it was created for (matched by workflow id) and uses a snapshot of both the workflow and the cases, so editing them mid-run changes nothing
- Requires the suite tables: apply `supabase/update_202611241600.sql` (already in `supabase/schema.sql` for new projects)

#### LLM Evaluation

Enable **Evaluate results** before running. After simulation completes the **Evaluation** tab shows a quality score (1–10), a 2–3 sentence summary, and collapsible **Strengths / Issues / Recommendations** sections. The sidebar switches to this tab automatically.

In mock mode (the default) the evaluation is generated deterministically from the workflow's structure — no API key needed. In real mode it calls your configured LLM provider.

#### Future: Real LLM Execution

The simulation engine supports a `llm_mode: real` path (not yet exposed in the UI). Setting this will route LLM, API, RAG, and TOOL nodes through actual providers instead of mock handlers. Requires valid credentials in `backend/.env`.

### Generate with AI
Click **Generate** → a chat panel opens. Describe your workflow in plain English and send the message. The AI responds in one of two ways:

- **If the description is detailed enough**, it generates the workflow immediately and shows a **Load to Canvas** card.
- **If it needs clarification**, it asks one focused question. Answer it and the workflow is generated on the next turn (maximum 2 questions before it makes reasonable assumptions and generates anyway).

Once a **Load to Canvas** card appears, click it to load the result. You can keep chatting to regenerate with adjustments — each reply that produces a workflow replaces the previous card.

Requires `LLM_API_KEY` in `backend/.env`.

**Example opening message:**
> Create a customer support agent that classifies requests, searches the knowledge base, retrieves customer info, and routes complex cases to a human reviewer.

### Refine with AI
Click **Refine** (enabled once your canvas has more than two nodes) → the same chat panel opens, but with the current workflow already loaded as context. Describe the change you want:

> Add error handling — if the API call fails, route to a fallback LLM node that generates a response from cached data.

> Replace the single CONDITION node with two separate routing steps — first by tier, then by issue type.

The AI returns a complete updated workflow preserving all unchanged node IDs and positions. Click **Load to Canvas** to apply it. The previous state is on the undo stack (`Ctrl+Z`) if you want to revert.

### Save / Open
- **Save** downloads `<workflow-name>.json`
- **Open** loads a previously saved `.json` file

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_PROVIDER` | Provider (`openai`) | `openai` |
| `LLM_API_KEY` | API key — never commit | _(required for Generate)_ |
| `LLM_MODEL` | Model ID | `gpt-4o-mini` |
| `CORS_ORIGINS` | Frontend origin | `http://localhost:5173` |

### Frontend (`frontend/.env`)

| Variable | Description | Default |
|----------|-------------|---------|
| `VITE_API_BASE_URL` | Backend URL | `http://localhost:8000` |

> **Deploying beyond localhost?** The backend's CORS config uses `allow_credentials=True` with
> wildcard methods and headers. This is fine for local development but should be tightened before
> exposing the backend on a public URL: set `CORS_ORIGINS` to your exact frontend origin and
> restrict `allow_methods` / `allow_headers` to only what the frontend actually sends.

---

## Workflow JSON Format

```json
{
  "version": "1.0",
  "id": "uuid",
  "name": "Customer Support Agent",
  "description": "Handles support requests",
  "nodes": [
    {
      "id": "classify-request",
      "type": "LLM",
      "name": "Classify Request",
      "position": { "x": 350, "y": 240 },
      "config": {
        "model": "gpt-4o-mini",
        "prompt": "Classify the request...",
        "temperature": 0
      }
    }
  ],
  "edges": [
    { "source": "start", "target": "classify-request" },
    { "source": "decision", "target": "human-review", "condition": "complex" }
  ],
  "metadata": {}
}
```

---

## Troubleshooting

**Backend won't start — `ModuleNotFoundError: No module named 'pydantic_settings'`**
→ You're running the system Python's uvicorn instead of the venv's. Use `run.bat` (Windows) or activate the venv first.

**Port 8000 already in use**
→ `run.bat` automatically frees port 8000 before starting. Or kill manually:
```powershell
# Windows PowerShell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess -Force
```

**Generate returns 503**
→ `LLM_API_KEY` is missing or empty in `backend/.env`.

**Workflow loads but nodes aren't visible**
→ Click **Validate** or zoom out — nodes may be off-screen. The canvas auto-fits when a workflow is opened.

**`LF will be replaced by CRLF` git warnings**
→ Cosmetic git line-ending warning on Windows — safe to ignore.

---

## Current Limitations

- **Simulator uses mock handlers only** — no real LLM, API, DB, or RAG calls during simulation
- **Size limits** — a workflow may have at most 100 nodes and 300 edges, 20 KB of config per node, and request bodies are capped at 1 MB (`MAX_REQUEST_BYTES`). Larger imports are rejected with a clear message
- **Pause/resume needs saved runs on Lambda** — a paused simulation's continuation is stored with its run, so any container (or a restarted server) can resume it. If run saving is unavailable (no Supabase, or the migrations below are not applied), a pause is held only in the server process and a resume can fail on Lambda with "No paused simulation found"
- **Request time limit** — simulate/resume stop after 25 s and a whole request after 28 s, because API Gateway cuts requests at 30 s. Use mock mode or a smaller workflow for long runs; slow AI evaluations fall back to the built-in review with a note
- **Workflow persists in this browser only** — localStorage keeps your work across refreshes, but it is tied to the current browser/device; multi-device or team access requires the cloud features listed in the roadmap
- Single LLM provider (OpenAI / LangChain wrapper)
- No authentication or multi-user support

---

## Roadmap

| Milestone | Focus | Status |
|-----------|-------|--------|
| **MVP1** | Visual designer + AI generation | ✓ Done |
| **MVP2** | Workflow simulator — mock BFS, HITL pause/resume, LLM evaluation | ✓ Done |
| **MVP3** | Real execution — live LLM, API, RAG, and HITL calls | Planned |
| **MVP4** | Optimizer — cost, latency, token analysis | Planned |
| **Future** | LangGraph export, team collaboration, cloud deployment, versioning | Backlog |
