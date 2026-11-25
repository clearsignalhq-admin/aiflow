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
- **Browse examples** — 12 categorised workflows across Easy / Medium / Complex difficulties

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
      └── LangGraph Adapter  →  runnable Python project (zip)
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
# Backend (1019 tests)
cd backend
.venv/Scripts/pytest -v       # Windows
pytest -v                     # macOS / Linux

# Frontend unit tests (550 tests)
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
Click **Examples** → an example picker opens with 12 pre-built, simulation-ready workflows:

| Difficulty | Workflows |
|------------|-----------|
| Easy | Email auto-reply, Sentiment classifier, Data enrichment, Meeting notes to action items |
| Medium | Customer support, Content moderation, Invoice processing, HR onboarding, Refund request handler |
| Complex | AI research agent, Supply chain monitor, Multi-tier customer journey |

Most examples model good practice: outside steps are checked, failures are handled, and a person reviews what a model wrote before anything changes. **Supply chain monitor** is the exception on purpose, left with design findings so you can try Validate, Suggest changes and Safety checks on it. Each example is described in [examples/README.md](examples/README.md), and `backend/tests/test_examples.py` keeps them valid, clean and exportable.

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
- **Limits:** up to 50 cases per suite (10 for demo accounts) and 20 suites per user. Each case counts as one simulation toward your daily allowance, and a run that would exceed it is refused up front.
- **Real-model runs:** choose *Real model* to run the cases against the actual AI model instead of simulated answers. Before you run, the dialog shows the most model calls and rough cost the run could use, and how many AI requests you have left today; it asks you to confirm. Each model call a case makes counts against your daily AI request allowance (a timed-out case is charged the most it could have used), at most 20 cases per real run, and answers can differ between runs, so checks on model output are less exact than with the simulator. A pinned *Mock output* on an AI step is ignored in real mode A run is tied to the workflow it was created for (matched by workflow id) and uses a snapshot of both the workflow and the cases, so editing them mid-run changes nothing
- **Compare runs:** open any previous run, pick another run of the same suite under *Compare with* (the run just before it is preselected) and press **Compare**. You get a verdict (regression, improvement or no change) with the pass-rate movement, then each test case classified as **regressed**, **fixed**, **still failing**, **unchanged**, new, removed or not run in both. For cases that ran in both: which checks flipped (with the reason), which steps now run or no longer run, and whether the output, cost or model calls changed. A **workflow diff** shows what was added, removed or edited between the two runs (including changed settings such as a prompt or an expression), so a regression can be traced to an edit, plus coverage movement. Warnings flag runs that are not directly comparable: one real and one simulated, different seeds, edited test cases, unfinished runs, or ordinary variation between two real-model runs. Comparing in the other direction turns a regression into an improvement
- Requires the suite tables: apply `supabase/update_202611241600.sql`, then `update_202611241700.sql` for real-model runs (both already in `supabase/schema.sql` for new projects)

#### The video guide

`docs/video-guide/` holds four **storyboards** (quick start; test suites and comparing runs; safety checks; saving, sharing and exporting). Each scene has a screenshot from the user guide, what to emphasise on screen, and the narration, with chapter markers for the video description. They are written to be turned into videos with a tool such as Google NotebookLM; `00-production-notes.md` has the wording rules and the instructions to paste into it. A test fails if a storyboard points at a missing screenshot or its timeline has gaps.

#### The app introduction video

A video introduction to AiFlow (on YouTube) is on the landing page as a click-to-play section (nothing loads from YouTube until it is played), under **Help → App introduction video**, and at the top of the user guide. Its address lives in `frontend/src/links.ts`.

#### The user guide

A step-by-step guide with screenshots lives in `docs/user-guide/README.md`. The app shows it at `/guide` (public, no sign-in) and from **Help → User guide**; it also reads fine on GitHub. A PDF version is made by `node make-pdf.mjs` (same folder). The screenshots are taken from the real interface by a script, so they can be redone whenever the interface changes: `cd docs/user-guide/capture && node run.mjs` (see the README in that folder). It runs a local copy of the backend with a fake user and in-memory storage, never your real services.

#### Versions and the About dialog

The product version lives in one file, `VERSION`. To cut a release: run `python scripts/bump_version.py patch|minor|major` (it bumps `VERSION`, adds a changelog entry to fill in, and copies the number into `backend/app/version.py` and `frontend/package.json`), write the entry, run the tests, commit, and deploy with `python scripts/deploy.py` (it builds, adds `GitCommit=<sha>` to the parameters already in `samconfig.toml`, deploys, refuses to run with uncommitted changes, and then offers to create and push the annotated tag `vX.Y.Z` on the deployed commit; `--dry-run` previews, `--tag` tags without asking, `--no-tag` skips it). `python scripts/sync_version.py` alone re-copies the number; `--check` is what the tests run. A test fails if any copy disagrees or the changelog does not lead with the current version. Numbering is `MAJOR.MINOR.PATCH`; while in private beta the major stays 0, a feature raises MINOR and a fix raises PATCH.

**Help → About AiFlow** shows the version, the commit and build date of the page, the version and commit of the server (from `GET /api/health`), the changelog, and a **Copy version info** button for bug reports. If the page and the server differ in MAJOR or MINOR (typically a stale cached page after a deploy), a banner offers a reload; a different PATCH is treated as compatible. The server's commit is stamped by `scripts/deploy.py`; a plain `sam deploy` leaves it as `unknown`. The full routine, with the manual fallback, is in [docs/deploy.md](docs/deploy.md). The page's commit comes from Amplify (or git, locally) at build time.

#### The top bar

Everyday actions sit on the bar: undo/redo, **Validate**, **▶ Simulate**, **Tests**, **Refine** and **Generate**. The rest is grouped into four menus: **Help** (search actions, About), and **File** (new, open, save to a file, cloud workflows, examples), **Export** (edit JSON, code, Mermaid, report) and **Analyze** (explain, suggest changes, safety checks, run history). Press **Ctrl+K** (⌘K on a Mac) or use *Search actions* to find any action by typing part of its name or what it does; arrow keys and Enter work in the menus and in the palette.

#### Cloud workflows, versions and sharing

**Cloud** (toolbar) keeps workflows in your account instead of a file.

- **Save** the workflow on screen as a new cloud workflow, or **Save changes** to the one open in the editor. Every save that changes something adds a **version** (with an optional note); a save that changes nothing adds none. The newest 30 versions are kept, and you can keep up to 30 workflows.
- **Versions** lists the history. **Changes since** shows what was added, removed or edited between a version and the current copy (including changed settings), and **Restore** brings an old version back as a new version, so nothing is lost.
- **Share** turns on a read-only link (`/shared/<token>`) that anyone can open without signing in. The page shows the current copy on a canvas, with a JSON download; it never shows who owns it and cannot change anything. **Stop sharing** ends the link for good; sharing again makes a new address. Deleting a workflow also ends its link. Anyone who has the link can see the workflow, so do not share workflows that contain anything private.

Needs the `cloud_workflows` and `workflow_versions` tables (`supabase/update_202611241800.sql`). Endpoints: `/api/cloud/workflows` (list, create, get, save, delete), `/versions`, `/diff`, `/versions/{n}/restore`, `/share`, and the public `GET /api/shared/{token}`.

#### Safety checks

**Safety** (toolbar) runs two checks that need no AI:

- **Prompt-injection exposure** reads the design and lists every AI step that both receives untrusted text (user input, retrieved documents, API responses, database rows, tool output) and can lead to an action that changes something (a write API, a write query, a tool call). Severity is *high* when it can reach a write, *medium* for a tool call, and *low* when a human review sits on every path in between. Each entry says what to do about it. Free; endpoint `POST /api/workflows/injection-exposure`.
- **Failure drill** makes each outside step (API, database, tool, retrieval, AI) fail in turn with a server error, a timeout, an empty result and a malformed result, in a simulated run using the sample input, and reports for each: **handled** (the workflow noticed and took a different route), **stops** (the run failed, including a decision that could not read the failed result), or **not noticed** (it finished exactly as if nothing had happened, which is the dangerous one). Steps that did not run with that input are listed so you can try another. Counts as one run against the daily limit; endpoint `POST /api/workflows/resilience`. The same failure can be injected on a single step through the `inject` simulation setting.

These are design checks, not proof of safety: they do not test real model behaviour, PII leakage or jailbreaks.

#### Suggested changes

**Suggest** (toolbar) offers edits you can accept one at a time:

- **Fixes for design findings** are worked out from the workflow itself, so they are free and always the same: delete an unreachable step, connect a dead end to END, label or complete a decision's branches, declare the fields a decision reads in the upstream output schema, and add a failure branch (a check plus a human review) after an API, database or tool step.
- **Describe a change** sends your instruction and the workflow to the AI, which proposes edits (for example "add a human approval before the refund is issued"). This uses one AI request from your daily allowance.

Every suggestion is a short list of typed operations (add or remove a step, change settings, connect, relabel). Nothing changes until you press **Apply**. The server checks each change against your actual workflow and applies it all together or not at all; anything the AI proposes that does not fit (a missing step, a second START, an unknown operation) is dropped and listed. Applying is a single undoable edit (Ctrl+Z). Endpoints: `POST /api/workflows/fixes`, `/suggest`, `/apply-changes`.

#### Explain this workflow

**Explain** writes a plain-language description for reviewers and stakeholders: what happens step by step (in flow order, with each decision's branches), where people review things, which outside systems it reads from or writes to, rough time and cost per run, and anything the automatic checks flagged. It is built directly from the workflow without the AI model, so it is free (no allowance used), always current, and identical for an identical workflow. Copy it or download it as Markdown.

#### Mermaid diagrams

**Mermaid** exports the workflow as a Mermaid `flowchart` you can paste into a README, a pull request or mermaid.live, and imports one back.

- Each node type has its own shape and is tagged with a class (`id["Name"]:::LLM`), so an AiFlow diagram imports back exactly (ids are made Mermaid-safe, for example `end` becomes `end_n`)
- A diagram carries the *shape* of the workflow only. Prompts, URLs, expressions and schemas are not part of it, so imported nodes have empty settings
- Hand-written flowcharts import too: types come from the shape (`{}` decision, `[( )]` database, `[[ ]]` tool, `[/ /]` API, `{{ }}` knowledge search, `(( ))` human review) or label (`Start`, `End`); anything guessed is listed as a warning, and a START or END is added if the diagram has none. Subgraphs are flattened

#### Export as code

**Code** downloads the workflow as a runnable project. Pick a format:

| Format | What you get |
|---|---|
| **LangGraph (Python)** | The whole workflow as a LangGraph project: graph, one function per step, routing for decisions, human-review pauses (`interrupt`), command-line runner, tests |
| **Plain Python** | The same steps, routing and tests with **no framework**: a ~40-line `engine.py` runs the graph. Easiest to read, change and embed |
| **MCP tools** | The workflow's TOOL, API, DATABASE and knowledge-search steps as an **MCP server** (`server.py`, tool definitions in `tools.json`) that Claude Desktop, IDEs and agents can call. Needs the official `mcp` package, 1.x |

All formats ship the workflow as `workflow.json` and every step reads its settings from there, so the code contains no copied prompts or URLs, and workflow text can never become code.

- `python main.py --mock` runs offline. Mock data is generated by the same code and seed as the simulator, so branches match
- **API steps** send the real request: method, URL (`{{field}}` values are percent-encoded), headers, and a JSON body. A header value written `env:NAME` is read from that environment variable. A non-2xx response is returned as `{status, body}` so a decision can branch on it
- **DATABASE steps** run the query with SQLAlchemy; `{{field}}` values become **bound parameters** (never pasted into the SQL). Set the connection to `env:NAME`; connection strings are never stored in the workflow
- **Knowledge-search steps** search `knowledge/<knowledge base>/*.md|*.txt` (OpenAI embeddings if `OPENAI_API_KEY` is set, otherwise an offline keyword scorer); replace `connectors.search_knowledge` with your vector store when you have one
- **TOOL and TRANSFORM steps** have no settings that say how to run them, so they raise `NotImplementedError` until you write them in `integrations.py` (the README lists which)
- Pick a **test suite** to also get one generated pytest test per case, replayed with the same seeds and checks (LangGraph and plain Python formats)
- Differences from the simulator are listed in the dialog and in each generated README (results accumulate; a decision matching no branch raises; in plain Python each step runs once per run)

#### Import from LangGraph

The **Import** tab of the Code dialog turns a LangGraph project into a workflow. Upload the Python files that build the graph (or paste the code). The code is only **read, never run**.

- An AiFlow export that includes `workflow.json` is restored **exactly**
- Otherwise the graph is read from `StateGraph` builder calls (`add_node`, `add_edge`, `add_conditional_edges`, `set_entry_point`, `set_finish_point`, `add_sequence`, chained builders). Step types are **guessed** from what each function does (calls an LLM, an HTTP client, a database, a retriever, `interrupt`...), and settings that are plain literals (prompt, model, URL, SQL) are carried over
- A router function that is a simple chain of `if`/`return` on `state[...]` becomes a decision expression; anything more complex is left blank with a warning so you can write the rule
- Everything guessed is listed as a warning; review the steps and run Validate

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
| **Future** | Team collaboration, cloud deployment, versioning, real-LLM test suites | Backlog |
