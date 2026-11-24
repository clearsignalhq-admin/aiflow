# AiFlow — Async Suite Runs: Design Note (Task 44 spike)

**Date:** 2026-11-24 · **Status:** design only, no production code · **Feeds:** the dataset / suite work in `docs/future/2026-11-24 AiFlow - Future Directions.md` (Tier B: B1–B3) · **Related:** Task 42 (persisted runs)

A *suite run* executes one workflow against N test cases and aggregates the results. This note decides how that fits the current deployment (AWS Lambda behind an API Gateway HTTP API), before any B-tier code is written.

---

## 1. Constraints, checked against the repo

| # | Fact | Where | Consequence |
|---|---|---|---|
| 1 | The API is an API Gateway **HTTP API** (`AWS::Serverless::HttpApi`). Its integration timeout is **30 s, a hard limit** | `template.yaml` | No synchronous request can exceed 30 s, whatever the Lambda timeout says. (An earlier brainstorm said ~29 s; for an HTTP API it is 30 s. Re-verify against current AWS quotas.) |
| 2 | Lambda timeout is **60 s**, 512 MB, Python 3.12 | `template.yaml` Globals | The Lambda could run longer than the gateway will wait. A client would see a 503 while the function keeps running and spending LLM money |
| 3 | `POST /workflows/simulate` wraps the run in `asyncio.wait_for(..., 120.0)` | `routes.py` | The 120 s guard can never fire before the gateway cuts the request at 30 s. It should be at most ~25 s |
| 4 | Lambda synchronous request/response payload limit is **6 MB** | AWS quota | A suite response must be paged; never return all traces in one body |
| 5 | HITL / user-pick pause state lives in the **in-memory** `_paused_store` | `services/simulator.py` | On Lambda, the resume request usually lands on a different container (or after a cold start) and gets "No paused simulation found". **Pause/resume works locally but is unreliable in production.** See §7 |
| 6 | slowapi's `Limiter` uses in-memory storage | `core/limiter.py` | Rate limits are per container, so `5/hour` on `/access-requests` is not a global limit |
| 7 | `increment_usage` reads then writes the counter | `core/supabase_client.py` | Not atomic. Concurrent requests undercount. Fine for one-at-a-time use, wrong for suites |
| 8 | Usage limits are per day: demo 10 executions / 20 LLM requests, approved unlimited | `config.py`, `template.yaml` | A 20-case suite would consume a demo user's whole day if each case counts as an execution |
| 9 | The mock simulator is pure Python with no I/O; a real-LLM node costs one provider call (typically seconds) | `node_handlers.py` | Mock suites are cheap and fast; real-LLM suites and LLM judges are what break the 30 s wall |

**Measure before deciding thresholds.** "Cheap and fast" for mock mode is expected, not measured. Time a 12-node example (`examples/complex/*`) over 100 cases on a Lambda-sized container and record p50/p95 before fixing the synchronous cutoff in §3.

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

- **Synchronous fast path:** mock-mode suites of up to N cases *may* run inside a single request when the measured p95 fits under ~20 s. Pick N from the measurement in §1. Real-LLM suites are always asynchronous.
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

Fact 5 matters beyond suites. HITL pause (and the user-pick pause added in Task 43) keep their continuation in process memory, so in the deployed Lambda a resume request will often hit a different container and fail with "No paused simulation found". The persisted run (Task 42) already holds the trace and the workflow snapshot; what is missing is the continuation (queue + visited set). **Recommended follow-up (Task 46): store the continuation with the run row and rebuild `_PausedState` from it on resume**, so pause/resume works across invocations. This is independent of suites and worth doing first, because it fixes shipped behaviour.

## 8. Decisions needed from the owner

1. Is "browser must stay open" acceptable for Phase 1 (Option A), or is CI-style unattended running needed from day one (go straight to Option B)?
2. Case caps per tier (suggested: demo 10, approved 50).
3. Should a suite consume the same daily allowance as one-off simulations, or get its own?
4. Assertion/judge scope for the first release: deterministic assertions only, or an LLM judge too (adds cost and the calibration problem, B9)?

## 9. Proposed follow-up tasks (not scheduled)

| Task | Scope |
|---|---|
| 46 | Durable pause/resume: persist the continuation with the run; rebuild on resume (§7) |
| 47 | Atomic usage counter via SQL function + RPC; use it everywhere (§5) |
| 48 | Lower the simulate guard from 120 s to ≤ 25 s and return a clear 504 body (§1 #3) |
| 49 | Benchmark mock-simulation throughput on a Lambda-sized container; fix the synchronous cutoff (§1, §3) |
| 50 | Suites data model + job API + Option A executor (B1–B3) |
