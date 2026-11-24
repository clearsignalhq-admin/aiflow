# AiFlow — Async Suite Runs: Design Note (Task 44 spike)

**Date:** 2026-11-24 · **Status:** design; prerequisites (Tasks 46–49) implemented the same day · **Feeds:** the dataset / suite work in `docs/future/2026-11-24 AiFlow - Future Directions.md` (Tier B: B1–B3) · **Related:** Task 42 (persisted runs)

A *suite run* executes one workflow against N test cases and aggregates the results. This note decides how that fits the current deployment (AWS Lambda behind an API Gateway HTTP API), before any B-tier code is written.

---

## 1. Constraints, checked against the repo

| # | Fact | Where | Consequence |
|---|---|---|---|
| 1 | The API is an API Gateway **HTTP API** (`AWS::Serverless::HttpApi`). Its integration timeout is **30 s, a hard limit** | `template.yaml` | No synchronous request can exceed 30 s, whatever the Lambda timeout says. (An earlier brainstorm said ~29 s; for an HTTP API it is 30 s. Re-verify against current AWS quotas.) |
| 2 | Lambda timeout is **60 s**, 512 MB, Python 3.12 | `template.yaml` Globals | The Lambda could run longer than the gateway will wait. A client would see a 503 while the function keeps running and spending LLM money |
| 3 | `POST /workflows/simulate` wraps the run in `asyncio.wait_for(..., 120.0)` | `routes.py` | The 120 s guard can never fire before the gateway cuts the request at 30 s. It should be at most ~25 s. **Fixed (Task 48):** simulate/resume guard 25 s, whole-request budget 28 s, generate/chat 25 s, Lambda `Timeout` 30 s; timeouts return a clear 504 |
| 4 | Lambda synchronous request/response payload limit is **6 MB** | AWS quota | A suite response must be paged; never return all traces in one body |
| 5 | HITL / user-pick pause state lives in the **in-memory** `_paused_store` | `services/simulator.py` | On Lambda, the resume request usually lands on a different container (or after a cold start) and gets "No paused simulation found". **Pause/resume works locally but is unreliable in production.** See §7. **Fixed (Task 46):** the continuation is stored with the run and rebuilt on resume |
| 6 | slowapi's `Limiter` uses in-memory storage | `core/limiter.py` | Rate limits are per container, so `5/hour` on `/access-requests` is not a global limit |
| 7 | `increment_usage` reads then writes the counter | `core/supabase_client.py` | Not atomic. Concurrent requests undercount. Fine for one-at-a-time use, wrong for suites. **Fixed (Task 47):** single-statement SQL function called over RPC |
| 8 | Usage limits are per day: demo 10 executions / 20 LLM requests, approved unlimited | `config.py`, `template.yaml` | A 20-case suite would consume a demo user's whole day if each case counts as an execution |
| 9 | The mock simulator is pure Python with no I/O; a real-LLM node costs one provider call (typically seconds) | `node_handlers.py` | Mock suites are cheap and fast; real-LLM suites and LLM judges are what break the 30 s wall |

**Measured (Task 49, 2026-11-24).** `backend/benchmarks/bench_simulation.py` runs every example workflow for 300 cases in mock mode (case *i* uses seed *i*, so branches vary) on a Windows 11 developer machine, Python 3.13:

| Workflow | Nodes | Avg steps | Engine p95 | Run-record build p95 | Whole case p95 | Record size p95 |
|---|---|---|---|---|---|---|
| complex / ai-research-agent (worst) | 12 | 9.3 | 0.20 ms | 0.13 ms | **0.33 ms** | 9.9 KB |
| complex / multi-agent-customer-journey | 12 | 8.0 | 0.17 ms | 0.12 ms | 0.29 ms | 9.7 KB |
| medium / customer-support | 8 | 7.5 | 0.19 ms | 0.11 ms | 0.30 ms | 7.7 KB |
| easy / email-auto-reply | 3 | 3.0 | 0.05 ms | 0.05 ms | 0.09 ms | 3.3 KB |

Reading it:

- **The mock engine is not a constraint.** The worst case is ~0.3 ms, about 3,000+ cases per second per core.
- **Lambda estimate (not measured here).** CPU scales with memory, and 512 MB is roughly 0.3 of a vCPU, so allow ~3–4× slower: ~1–1.5 ms per case. Verify with one real deploy before relying on it.
- **Wall time is dominated by I/O that this benchmark does not cover:** one Supabase insert per saved run (typically tens to a few hundred ms, **unmeasured**), real LLM calls (seconds each), and cold starts. Sequentially saving 50 runs at ~100 ms each would take ~5 s, which is why suite case runs should be written with **one bulk insert** (PostgREST accepts an array) rather than one request per case.
- Per-case records are 3–10 KB, so a 50-case suite stores well under 1 MB.
- `tests/test_simulation_performance.py` guards the engine loosely (100 cases of the largest example in under 2 s) so accidental slowdowns or I/O in the engine are caught.

---

## 2. Options considered

| Option | How | Pros | Cons |
|---|---|---|---|
| **A. Client-driven** | The browser creates a job, then calls the existing per-run endpoint once per case (a few in parallel) and reports each result | No new infrastructure. Each call is far below 30 s. Natural progress and cancel. Reuses auth, limits, persisted runs | The tab must stay open. Not usable from CI |
| **B. SQS fan-out** | `POST` creates the job and enqueues one message per case. A worker Lambda (per case, up to 15 min) writes results; the client polls | Survives closing the browser. Parallel with a concurrency cap. Works for CI (D4) | New infra: queue, DLQ, worker, IAM, `template.yaml` changes. More failure modes (duplicates, poison messages) |
| **C. Lambda self-invoke (async)** | `POST` invokes the same function with `InvocationType=Event`, which loops over cases | Smallest infra delta | A single 15-min ceiling; weak retry story; one slow case blocks the rest; hard to cap concurrency |
| **D. Step Functions Map** | State machine maps over cases | Built-in retries, concurrency limit, visibility | Heaviest. More cost and concepts than this project needs |
| **E. Always-on container** | Move the API off Lambda | Removes every limit above | Gives up the serverless setup already deployed; unjustified now |

### Recommendation

Build the **job model once, with a pluggable executor**:

1. **Phase 1 (with B1–B3): Option A.** The server owns the job and the budget; the browser is the executor. This is the lowest-risk way to ship datasets and pass-rate reports and it is enough for the demo/portfolio goal.
2. **Phase 2 (with D4, CI for workflows): Option B.** Swap the executor for SQS + a worker Lambda. The API, data model and UI do not change, only *who calls "run case"*.

Skip C, D and E.

---

## 3. Job model (identical for both executors)

```
POST   /api/suites/{suite_id}/runs        → 202 { job_id, status: "queued", case_count, reserved_units }
GET    /api/suite-runs/{job_id}           → { status, counts, started_at, … }          (cheap; poll every 2–3 s)
GET    /api/suite-runs/{job_id}/results   → paged case results (?after=<case_id>&limit=50)
POST   /api/suite-runs/{job_id}/cancel    → 202
POST   /api/suite-runs/{job_id}/cases/{case_id}/run   → 200 case result      (Option A executor only)
```

State machine: `queued → running → complete | failed | cancelled`. A case result is `passed | failed | error | skipped`.

- **Synchronous fast path:** mock-mode suites run inside one request, up to the per-tier case cap (suggested 50). By the §1 measurements the engine needs well under a second for 50 cases even on a small Lambda; the case results must be stored with a single bulk insert to stay inside the 25 s guard. Real-LLM suites and anything with an LLM judge are always asynchronous (one LLM call alone can take several seconds).
- **Per-case timeout:** 25 s, so one slow case never reaches the 30 s wall. A timed-out case is `error` and the job continues.
- **Stale jobs:** a job `running` with no progress for 15 min is marked `failed` on the next read.
- **No pauses inside suites:** suite runs force `hitl_mode = auto-approve` and `condition_mode` ∈ {expression, random}. A paused case would hold a job open indefinitely.
- **Determinism:** each case runs with an explicit `seed` (the case's own, else its index), so reruns are comparable (Tasks 40–41).

## 4. Storage (Supabase, same pattern as Task 42)

| Table | Purpose |
|---|---|
| `suites` | `id, user_id, workflow_id, name, created_at` |
| `suite_cases` | `id, suite_id, input jsonb, expected jsonb, assertions jsonb, tags text[]` |
| `suite_runs` | the job: `id, user_id, suite_id, status, case_count, passed, failed, errors, reserved_units, settings jsonb, workflow_snapshot jsonb, created_at, finished_at` |
| `suite_case_results` | `run_id, case_id, status, run_id_trace` (a `workflow_runs.id`), `assertion_results jsonb, duration_ms, cost_estimate` |

- RLS: users read only their own rows; the backend writes with the service role, and every query is `user_id`-scoped (as in the runs API).
- The per-case trace is stored in `workflow_runs` (Task 42), so replay on the canvas already works. Suite rows hold only the verdict and a link.
- Snapshot the workflow into the job so editing the workflow mid-run cannot change results.
- Caps: cases per suite (demo 10, approved 50, to be tuned), bytes per case, and the same retention window as runs. Any new schema change needs `schema.sql` **and** a matching `supabase/update_YYYYMMDDhhmm.sql`.

## 5. Usage accounting and cost control

- **Unit = case execution.** One mock case = 1 execution unit; each real-LLM node executed adds LLM-request units. A suite is one *job* but N units.
- **Reserve up front:** at `POST …/runs`, compute `cases × expected units` (the lint engine's per-path estimate gives expected LLM nodes per path) and reject with 429 if the user's remaining daily allowance is lower. Show the estimate in the UI *before* the run starts.
- **Atomic counter:** replace read-then-write `increment_usage` with a SQL function `increment_usage(user, field, by int)` (single `insert … on conflict do update set x = x + by`), called through Supabase RPC. This is required before suites, otherwise parallel cases undercount.
- **Refund on cancel/failure:** release the unspent part of the reservation.
- **Global budget kill-switch** (Future Directions §8.4) belongs here too: a suite run is the first feature that can spend real money in bulk.

## 6. Security and robustness

- Treat case inputs, expected values and LLM-judge text as untrusted (prompt injection into the judge). Validate size with the same limits as workflows (Task 38) and cap total job bytes.
- Authorisation on every job endpoint is `user_id`-scoped; job and case ids are UUIDs validated before they reach a PostgREST filter (done for runs in Task 42).
- Idempotency: `POST …/cases/{case_id}/run` is safe to repeat (it upserts the result for `(run_id, case_id)`), which also covers duplicate SQS deliveries in Phase 2.
- Concurrency: Option A caps parallel in-flight cases at 3 per tab; Option B uses reserved concurrency on the worker so a suite cannot exhaust the account.

## 7. Related problem found while writing this: pause/resume on Lambda

Fact 5 matters beyond suites. HITL pause (and the user-pick pause added in Task 43) keep their continuation in process memory, so in the deployed Lambda a resume request will often hit a different container and fail with "No paused simulation found". The persisted run (Task 42) already holds the trace and the workflow snapshot; what is missing is the continuation (queue + visited set). **Resolved in Task 46:** the continuation (queue, visited set, pause kind, branch choices, branch data) is stored in `workflow_runs.continuation` and `_PausedState` is rebuilt from it on resume, scoped to the requesting user. It is cleared when the run is no longer paused. If the run cannot be stored or restored, resume still works within the same process as before.

## 8. Decisions (2026-11-24)

Resolved by the owner choosing the recommended defaults:

1. **Executor:** client-driven (Option A) for the first release; the SQS worker (Option B) stays the plan for CI. The job API is unchanged between them.
2. **Case caps:** 10 for demo accounts, 50 for approved accounts (settings `DEMO_MAX_CASES_PER_SUITE` / `APPROVED_MAX_CASES_PER_SUITE`), plus 20 suites per user.
3. **Allowance:** suites share the daily *executions* allowance; each executed case costs one unit, and a run is refused up front if it cannot fit.
4. **Assertions:** deterministic only. No LLM judge, so no calibration problem (B9) yet.

Consequences: suites run in **mock mode only** for now (a real-LLM case would need LLM-request accounting and a longer per-case budget).

## 9. Follow-up tasks

| Task | Scope | Status |
|---|---|---|
| 46 | Durable pause/resume: persist the continuation with the run; rebuild on resume (§7) | Done |
| 47 | Atomic usage counter via SQL function + RPC (§5) | Done. Suites can add N units in one call (`by=N`) |
| 48 | Align timeouts with the 30 s gateway limit; clear 504s (§1 #3) | Done |
| 49 | Benchmark mock simulation; fix the synchronous cutoff (§1, §3) | Done (results in §1) |
| 50 | Suites data model + job API + Option A executor (B1–B3) | Done (see below) |

### What Task 50 built

- **Tables:** `suites` (cases stored as a JSON document, so a save is atomic), `suite_runs` (the job, with snapshots of the workflow and cases), `suite_case_results` (primary key `(run_id, case_id)`, which makes running a case idempotent). RLS lets users read only their own rows; the backend writes through the service role.
- **API:** `GET/POST /api/suites`, `GET/PUT/DELETE /api/suites/{id}`, `POST /api/suites/{id}/runs`, `GET /api/suites/{id}/runs`, `GET /api/suite-runs/{id}`, `POST /api/suite-runs/{id}/cancel`, `POST /api/suite-runs/{id}/cases/{case_id}/run`.
- **Job rules:** created in `running`; becomes `complete` when every case has a result, `cancelled` on request, and `failed` if it is still unfinished 15 minutes after creation (settled lazily on the next read). Repeating a case returns the stored result and is not charged again. A run is refused for a different workflow, an empty suite, an unsimulatable workflow (cycle, no START/END), or an exceeded allowance.
- **Coverage is exact:** steps now record the edges actually followed (`next_ids`), so "branches never taken" is not guessed from visited nodes.

### Real-model runs (Task 55)

Decision 1 (§8) kept suites mock-only; real runs were added once the accounting existed.

- A run records `llm_mode` (`mock` or `real`) when created. `POST /suites/{id}/runs/estimate` returns, without reserving anything, the most model calls one case can make (the worst route through the workflow, from the linter's path estimates), the rough cost, the remaining executions and AI requests today, and whether the run is allowed and why not.
- Creating a real run is refused (422/429/503) if it has more than 20 cases, no model is configured, or the run could not fit the day's execution or AI-request allowance.
- Before **each** case the AI-request allowance is checked again (other activity can have used it). After each case the model calls it made are added with the atomic counter (`increment_usage(..., "llm_requests", n)`); a case that times out is charged the most it could have used, since its trace is lost.
- Cases still run one per request, bounded by the 25 s simulation guard, so workflows with many sequential model calls can time out; the estimate warns when a case can make more than five.

