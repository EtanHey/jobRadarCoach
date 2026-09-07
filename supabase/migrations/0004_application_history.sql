create table if not exists public.application_history (
  id uuid primary key default gen_random_uuid(),
  posting_id uuid references public.postings(id) on delete set null,
  company text not null,
  role text,
  application_date date,
  outcome text,
  recorded_at timestamptz not null default now(),
  constraint application_history_company_nonblank check (company ~ '[^[:space:]]'),
  constraint application_history_role_nonblank check (role is null or role ~ '[^[:space:]]'),
  constraint application_history_outcome_nonblank check (outcome is null or outcome ~ '[^[:space:]]')
);

create index if not exists application_history_company_date_idx
  on public.application_history (lower(btrim(company)), application_date desc);

alter table public.application_history disable row level security;
revoke insert, update, delete, truncate, references, trigger
  on table public.application_history from anon, authenticated;
grant select on table public.application_history to anon, authenticated;
grant all on table public.application_history to service_role;

do $realtime$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'application_history'
  ) then
    alter publication supabase_realtime add table public.application_history;
  end if;
end
$realtime$;

create or replace function public.record_application_history(
  company text,
  role text,
  application_date date,
  outcome text,
  posting_id uuid default null
)
returns public.application_history
language plpgsql
security invoker
set search_path = ''
as $$
declare
  result public.application_history;
begin
  if $1 is null or not ($1 ~ '[^[:space:]]') then
    raise exception using errcode = '22023', message = 'application company is required';
  end if;
  if $2 is not null and not ($2 ~ '[^[:space:]]') then
    raise exception using errcode = '22023', message = 'application role must be null or nonblank';
  end if;
  if $4 is not null and not ($4 ~ '[^[:space:]]') then
    raise exception using errcode = '22023', message = 'application outcome must be null or nonblank';
  end if;

  insert into public.application_history (
    company, role, application_date, outcome, posting_id
  ) values ($1, $2, $3, $4, $5)
  returning * into result;
  return result;
end
$$;

create or replace function public.list_application_history(company_filter text default null)
returns table (
  history_id uuid,
  posting_id uuid,
  company text,
  role text,
  application_date date,
  outcome text,
  recorded_at timestamptz
)
language plpgsql
stable
security invoker
set search_path = ''
as $$
begin
  if $1 is not null and not ($1 ~ '[^[:space:]]') then
    raise exception using errcode = '22023', message = 'company filter must be null or nonblank';
  end if;
  return query
    select h.id, h.posting_id, h.company, h.role, h.application_date, h.outcome, h.recorded_at
    from public.application_history h
    where $1 is null or pg_catalog.lower(pg_catalog.btrim(h.company)) =
      pg_catalog.lower(pg_catalog.btrim($1))
    order by h.application_date desc nulls last, h.recorded_at desc, h.id;
end
$$;

revoke all on function public.record_application_history(text, text, date, text, uuid)
  from public, anon, authenticated;
revoke all on function public.list_application_history(text) from public;
grant execute on function public.record_application_history(text, text, date, text, uuid)
  to service_role;
grant execute on function public.list_application_history(text)
  to anon, authenticated, service_role;

comment on table public.application_history is
  'Explicit application events. History informs later fit policy but never imposes a company block or cooldown.';
comment on column public.application_history.application_date is
  'Caller-supplied application date; null means unknown and is never replaced with today.';
