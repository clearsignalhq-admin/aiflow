-- AiFlow — Supabase Schema
-- Run this in the Supabase SQL Editor (Dashboard → SQL Editor → New query)

-- ── User Profiles ──────────────────────────────────────────────────────────
-- Extends auth.users with access control state.
-- id mirrors auth.users.id (UUID).

create table if not exists public.user_profiles (
  id                   uuid        references auth.users(id) on delete cascade primary key,
  email                text        not null,
  access_status        text        not null default 'pending'
                                   check (access_status in ('pending', 'approved', 'demo', 'disabled')),
  role                 text        not null default 'user'
                                   check (role in ('user', 'demo', 'admin')),
  must_change_password boolean     not null default false,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  last_login           timestamptz
);

-- If the table already exists (re-running on an existing project), add the column:
alter table public.user_profiles
  add column if not exists must_change_password boolean not null default false;

-- Auto-create a profile row whenever a new user signs up.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.user_profiles (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- Auto-update updated_at on every change.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists user_profiles_updated_at on public.user_profiles;
create trigger user_profiles_updated_at
  before update on public.user_profiles
  for each row execute procedure public.set_updated_at();


-- ── Access Requests ─────────────────────────────────────────────────────────
-- Public visitors submit these; admin approves or rejects.

create table if not exists public.access_requests (
  id           uuid        default gen_random_uuid() primary key,
  name         text        not null,
  email        text        not null,
  linkedin_url text,
  company      text,
  message      text,
  status       text        not null default 'pending'
               check (status in ('pending', 'approved', 'rejected')),
  created_at   timestamptz not null default now()
);


-- ── Usage Tracking ──────────────────────────────────────────────────────────
-- Per-user daily counters for executions and LLM requests.
-- Used to enforce demo limits and provide usage feedback to users.

create table if not exists public.usage_tracking (
  id           uuid    default gen_random_uuid() primary key,
  user_id      uuid    references auth.users(id) on delete cascade not null,
  date         date    not null default current_date,
  executions   integer not null default 0,
  llm_requests integer not null default 0,
  unique (user_id, date)
);


-- ── Atomic usage counter (Task 47) ───────────────────────────────────────────
-- Called by the backend through RPC; service role only.

-- Only the service role may call it; users must not be able to edit their own usage via RPC.

create or replace function public.increment_usage(
  p_user_id uuid,
  p_field   text,
  p_by      integer default 1,
  p_date    date    default current_date
)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_by is null or p_by < 1 then
    raise exception 'p_by must be a positive integer';
  end if;

  if p_field = 'executions' then
    insert into public.usage_tracking (user_id, date, executions)
    values (p_user_id, p_date, p_by)
    on conflict (user_id, date)
    do update set executions = public.usage_tracking.executions + excluded.executions;
  elsif p_field = 'llm_requests' then
    insert into public.usage_tracking (user_id, date, llm_requests)
    values (p_user_id, p_date, p_by)
    on conflict (user_id, date)
    do update set llm_requests = public.usage_tracking.llm_requests + excluded.llm_requests;
  else
    raise exception 'unknown usage field: %', p_field;
  end if;
end;
$$;

revoke all on function public.increment_usage(uuid, text, integer, date) from public, anon, authenticated;
grant execute on function public.increment_usage(uuid, text, integer, date) to service_role;


-- ── Row Level Security ──────────────────────────────────────────────────────

alter table public.user_profiles    enable row level security;
alter table public.access_requests  enable row level security;
alter table public.usage_tracking   enable row level security;

-- user_profiles: each user can read and update their own row only.
create policy "Users can view own profile"
  on public.user_profiles for select
  using (auth.uid() = id);

create policy "Users can update own last_login"
  on public.user_profiles for update
  using (auth.uid() = id)
  with check (auth.uid() = id);

-- access_requests: anyone (unauthenticated too) can insert; nobody can read.
-- Reads happen only via service role (backend admin endpoints).
create policy "Anyone can submit access request"
  on public.access_requests for insert
  with check (true);

-- usage_tracking: users can read their own row; backend increments via service role.
create policy "Users can view own usage"
  on public.usage_tracking for select
  using (auth.uid() = user_id);


-- ── Analytics Events ────────────────────────────────────────────────────────
-- Lightweight event log (page views, logins, workflow usage).
-- Inserts are public; all reads go via backend service role.

create table if not exists public.analytics_events (
  id         uuid        default gen_random_uuid() primary key,
  event      text        not null,
  page       text,
  user_id    uuid        references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

alter table public.analytics_events enable row level security;

create policy "Anyone can insert analytics"
  on public.analytics_events for insert
  with check (true);


-- ── Workflow Runs ───────────────────────────────────────────────────────────
-- Persisted simulation traces (Task 42). Backend writes via service role.
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
  continuation  jsonb,                          -- state needed to resume a paused run (null otherwise)
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


-- ── Test Suites (Task 50) ───────────────────────────────────────────────────
-- Suites, suite runs (jobs) and per-case results. Backend writes via service role.

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
  llm_mode    text        not null default 'mock' check (llm_mode in ('mock', 'real')),
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


-- ── Indexes ──────────────────────────────────────────────────────────────────

create index if not exists user_profiles_access_status_idx
  on public.user_profiles (access_status);

create index if not exists access_requests_status_idx
  on public.access_requests (status);

create index if not exists usage_tracking_user_date_idx
  on public.usage_tracking (user_id, date);

create index if not exists analytics_events_event_idx
  on public.analytics_events (event);

create index if not exists analytics_events_created_at_idx
  on public.analytics_events (created_at desc);

create index if not exists workflow_runs_user_created_idx
  on public.workflow_runs (user_id, created_at desc);

create index if not exists suites_user_workflow_idx
  on public.suites (user_id, workflow_id);

create index if not exists suite_runs_suite_created_idx
  on public.suite_runs (suite_id, created_at desc);

create index if not exists suite_runs_user_idx
  on public.suite_runs (user_id);

create index if not exists suite_case_results_user_idx
  on public.suite_case_results (user_id);

-- ── Cloud workflows, versions and share links (Task 61) ─────────────────────
-- A cloud workflow is the current copy of a workflow plus its saved versions. A share link is a long random token;
-- anyone holding it can read (never change) the current copy through the backend. The backend writes via the service
-- role; users can only read their own rows through RLS, and the share token is never readable by other users.

create table if not exists public.cloud_workflows (
  id            uuid        primary key default gen_random_uuid(),
  user_id       uuid        references auth.users(id) on delete cascade not null,
  name          text        not null,
  workflow      jsonb       not null,                     -- the current copy
  version_count integer     not null default 1,           -- number of the latest version
  share_token   text        unique,                       -- null = not shared
  shared_at     timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create table if not exists public.workflow_versions (
  id          uuid        primary key default gen_random_uuid(),
  workflow_id uuid        references public.cloud_workflows(id) on delete cascade not null,
  user_id     uuid        references auth.users(id) on delete cascade not null,
  version     integer     not null,
  label       text,
  workflow    jsonb       not null,
  created_at  timestamptz not null default now(),
  unique (workflow_id, version)                           -- two saves racing cannot both claim a version number
);

alter table public.cloud_workflows  enable row level security;
alter table public.workflow_versions enable row level security;

create policy "Users can view own cloud workflows"
  on public.cloud_workflows for select
  using (auth.uid() = user_id);

create policy "Users can view own workflow versions"
  on public.workflow_versions for select
  using (auth.uid() = user_id);

drop trigger if exists cloud_workflows_updated_at on public.cloud_workflows;
create trigger cloud_workflows_updated_at
  before update on public.cloud_workflows
  for each row execute procedure public.set_updated_at();

create index if not exists cloud_workflows_user_updated_idx
  on public.cloud_workflows (user_id, updated_at desc);

create index if not exists workflow_versions_workflow_idx
  on public.workflow_versions (workflow_id, version desc);

create index if not exists workflow_versions_user_idx
  on public.workflow_versions (user_id);
