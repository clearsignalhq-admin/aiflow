-- Task 42 — Persisted simulation runs
-- Stores each user's simulation traces so they can be listed, replayed and deleted.
-- The backend writes via the service role; users can only read their own rows through RLS.

create table if not exists public.workflow_runs (
  id            uuid        primary key,            -- equals the trace_id
  user_id       uuid        references auth.users(id) on delete cascade not null,
  workflow_id   text        not null,
  workflow_name text        not null,
  status        text        not null
                check (status in ('running', 'paused', 'complete', 'error')),
  step_count    integer     not null default 0,
  settings      jsonb       not null default '{}'::jsonb,
  input         jsonb       not null default '{}'::jsonb,
  workflow      jsonb       not null,               -- snapshot of the workflow as simulated
  trace         jsonb       not null,
  evaluation    jsonb,
  truncated     boolean     not null default false, -- step inputs/outputs dropped to fit the size cap
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

alter table public.workflow_runs enable row level security;

create policy "Users can view own runs"
  on public.workflow_runs for select
  using (auth.uid() = user_id);

drop trigger if exists workflow_runs_updated_at on public.workflow_runs;
create trigger workflow_runs_updated_at
  before update on public.workflow_runs
  for each row execute procedure public.set_updated_at();

create index if not exists workflow_runs_user_created_idx
  on public.workflow_runs (user_id, created_at desc);
