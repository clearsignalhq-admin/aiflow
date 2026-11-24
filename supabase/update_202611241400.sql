-- Task 46 — Durable pause/resume
-- Stores the continuation of a paused simulation with its run row, so any server process
-- (e.g. a different Lambda container) can resume it. Cleared when the run is no longer paused.

alter table public.workflow_runs
  add column if not exists continuation jsonb;
