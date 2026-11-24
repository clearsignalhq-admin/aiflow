-- Task 61 — Cloud workflows, version history and share links
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
