-- Task 55 — Real-LLM test suites
-- A suite run can use the real AI model. The mode is fixed when the run is created.

alter table public.suite_runs
  add column if not exists llm_mode text not null default 'mock';

alter table public.suite_runs
  drop constraint if exists suite_runs_llm_mode_check;

alter table public.suite_runs
  add constraint suite_runs_llm_mode_check check (llm_mode in ('mock', 'real'));
