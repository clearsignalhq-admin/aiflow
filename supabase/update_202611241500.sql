-- Task 47 — Atomic usage counter
-- Replaces the backend's read-then-write counter, which undercounted under concurrency.
-- One statement inserts today's row or adds `p_by` to it, so parallel requests all count.
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
