-- Task 50 — Test suites
-- A suite is a named list of test cases (input + deterministic assertions) for one workflow.
-- A suite run is a job that executes those cases; each case result is one row.
-- The backend writes via the service role; users can only read their own rows through RLS.

create table if not exists public.suites (
  id          uuid        primary key default gen_random_uuid(),
  user_id     uuid        references auth.users(id) on delete cascade not null,
  workflow_id text        not null,
  name        text        not null,
  cases       jsonb       not null default '[]'::jsonb,   -- [{id, name, input, assertions, tags, seed}]
  case_count  integer     not null default 0,             -- kept in step with cases so lists need not load them
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists public.suite_runs (
  id          uuid        primary key default gen_random_uuid(),
  user_id     uuid        references auth.users(id) on delete cascade not null,
  suite_id    uuid        references public.suites(id) on delete cascade not null,
  status      text        not null default 'running'
              check (status in ('running', 'complete', 'cancelled', 'failed')),
  case_count  integer     not null,
  seed        integer     not null default 0,
  workflow    jsonb       not null,                       -- snapshot: editing the workflow mid-run changes nothing
  cases       jsonb       not null,                       -- snapshot of the suite's cases
  note        text,                                       -- why a job was marked failed
  created_at  timestamptz not null default now(),
  finished_at timestamptz
);

create table if not exists public.suite_case_results (
  run_id     uuid        references public.suite_runs(id) on delete cascade not null,
  case_id    text        not null,
  user_id    uuid        references auth.users(id) on delete cascade not null,
  status     text        not null check (status in ('passed', 'failed', 'error')),
  result     jsonb       not null,
  created_at timestamptz not null default now(),
  primary key (run_id, case_id)                           -- makes running a case idempotent
);

alter table public.suites             enable row level security;
alter table public.suite_runs         enable row level security;
alter table public.suite_case_results enable row level security;

create policy "Users can view own suites"
  on public.suites for select
  using (auth.uid() = user_id);

create policy "Users can view own suite runs"
  on public.suite_runs for select
  using (auth.uid() = user_id);

create policy "Users can view own suite case results"
  on public.suite_case_results for select
  using (auth.uid() = user_id);

drop trigger if exists suites_updated_at on public.suites;
create trigger suites_updated_at
  before update on public.suites
  for each row execute procedure public.set_updated_at();

create index if not exists suites_user_workflow_idx
  on public.suites (user_id, workflow_id);

create index if not exists suite_runs_suite_created_idx
  on public.suite_runs (suite_id, created_at desc);

create index if not exists suite_runs_user_idx
  on public.suite_runs (user_id);

create index if not exists suite_case_results_user_idx
  on public.suite_case_results (user_id);
