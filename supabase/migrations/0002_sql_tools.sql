create or replace function public.profile_value_is_valid(field text, value jsonb)
returns boolean
language sql
immutable
strict
security invoker
set search_path = ''
as $$
  select case
    when $1 = 'contract_version' then $2 = '1'::jsonb
    when $1 in ('candidate.positioning', 'candidate.location', 'search.recency') then
      pg_catalog.jsonb_typeof($2) = 'string' and ($2 #>> '{}') ~ '[^[:space:]]'
    when $1 = 'candidate.tenure_years' then
      case when pg_catalog.jsonb_typeof($2) = 'number' then ($2 #>> '{}')::numeric >= 0 else false end
    when $1 in (
      'candidate.fit_terms', 'candidate.roles_wanted', 'candidate.stacks', 'candidate.seniority',
      'candidate.open_to.geographies', 'candidate.red_flag_words',
      'constraints.global_never_claims', 'search.terms'
    ) then
      case when pg_catalog.jsonb_typeof($2) = 'array' then not exists (
        select 1 from pg_catalog.jsonb_array_elements($2) item
        where pg_catalog.jsonb_typeof(item) <> 'string' or not ((item #>> '{}') ~ '[^[:space:]]')
      ) else false end
    when $1 = 'candidate.open_to.work_modes' then
      case when pg_catalog.jsonb_typeof($2) = 'array' then not exists (
        select 1 from pg_catalog.jsonb_array_elements($2) item
        where pg_catalog.jsonb_typeof(item) <> 'string'
          or (item #>> '{}') not in ('remote', 'hybrid', 'onsite')
      ) else false end
    when $1 in ('candidate.remote', 'candidate.open_to.relocation') then
      pg_catalog.jsonb_typeof($2) in ('boolean', 'null')
    when $1 = 'candidate.salary_floor' then
      case
        when pg_catalog.jsonb_typeof($2) = 'null' then true
        when pg_catalog.jsonb_typeof($2) = 'number' then ($2 #>> '{}')::numeric >= 0
        else false
      end
    when $1 in ('candidate.preferences.product_company', 'candidate.preferences.free_text') then
      pg_catalog.jsonb_typeof($2) = 'null'
        or (pg_catalog.jsonb_typeof($2) = 'string' and ($2 #>> '{}') ~ '[^[:space:]]')
    when $1 in (
      'candidate.preferences.experience_gap', 'constraints.evidence_scoped_prohibitions',
      'search.location_terms'
    ) then pg_catalog.jsonb_typeof($2) = 'object'
    when $1 = 'fit_signals' then
      case when pg_catalog.jsonb_typeof($2) = 'array' then not exists (
        select 1 from pg_catalog.jsonb_array_elements($2) item
        where pg_catalog.jsonb_typeof(item) <> 'object'
      ) else false end
    when $1 = 'runtime.brain' then
      pg_catalog.jsonb_typeof($2) = 'string'
        and ($2 #>> '{}') in ('ollama', 'codex', 'claude', 'cursor-agent')
    else false
  end
$$;

do $profile_contract$
begin
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.profile'::regclass and conname = 'profile_supported_value'
  ) then
    alter table public.profile add constraint profile_supported_value
      check (public.profile_value_is_valid(field, value));
  end if;
end
$profile_contract$;

insert into public.profile (field, value)
values ('runtime.brain', '"ollama"'::jsonb)
on conflict (field) do nothing;

create or replace function public.list_new_for_me()
returns table (
  posting_id uuid, source text, external_id text, url text, title text, company text,
  location text, remote boolean, seniority text, stack text[], salary text, apply_url text,
  posted_at timestamptz, raw_jd text, status text, status_reason text,
  status_updated_at timestamptz, score smallint, reasons jsonb, labels jsonb,
  brain text, scored_at timestamptz
)
language sql
stable
security invoker
set search_path = ''
as $$
  select
    p.id, p.source, p.external_id, p.url, p.title, p.company, p.location, p.remote,
    p.seniority, p.stack, p.salary, p.apply_url, p.posted_at, p.raw_jd,
    coalesce(s.status, 'new'), s.reason, s.updated_at,
    ps.score, ps.reasons, ps.labels, ps.brain, ps.scored_at
  from public.postings p
  left join public.posting_status s on s.posting_id = p.id
  left join public.posting_scores ps on ps.posting_id = p.id
  where p.posted_at is not null
    and p.posted_at > coalesce(
      (select v.last_visit_at from public.visits v where v.singleton),
      '-infinity'::timestamptz
    )
    and coalesce(s.status, 'new') = 'new'
  order by ps.score desc nulls last, p.posted_at desc, p.id
$$;

create or replace function public.set_status(posting_id uuid, status text, reason text default null)
returns public.posting_status
language plpgsql
security invoker
set search_path = ''
as $$
declare
  result public.posting_status;
begin
  if $2 is null or $2 not in ('new', 'seen', 'saved', 'applied', 'rejected') then
    raise exception using errcode = '22023', message = 'unsupported posting status';
  end if;
  if $2 = 'rejected' and ($3 is null or not ($3 ~ '[^[:space:]]')) then
    raise exception using errcode = '22023', message = 'rejected status requires a nonblank reason';
  end if;
  if not exists (select 1 from public.postings p where p.id = $1) then
    raise exception using errcode = 'P0002', message = 'posting does not exist';
  end if;

  insert into public.posting_status as current_status (posting_id, status, reason)
  values ($1, $2, case when $2 = 'rejected' then $3 else null end)
  on conflict on constraint posting_status_pkey do update set
    status = excluded.status,
    reason = excluded.reason,
    updated_at = case
      when (current_status.status, current_status.reason)
        is distinct from (excluded.status, excluded.reason)
      then pg_catalog.clock_timestamp()
      else current_status.updated_at
    end
  returning * into result;
  return result;
end
$$;

create or replace function public.update_profile(field text, value jsonb)
returns public.profile
language plpgsql
security invoker
set search_path = ''
as $$
declare
  result public.profile;
begin
  if not coalesce(public.profile_value_is_valid($1, $2), false) then
    raise exception using errcode = '22023', message = 'unsupported profile field or invalid value';
  end if;

  insert into public.profile as current_profile (field, value)
  values ($1, $2)
  on conflict on constraint profile_pkey do update set
    value = excluded.value,
    updated_at = case
      when current_profile.value is distinct from excluded.value then pg_catalog.clock_timestamp()
      else current_profile.updated_at
    end
  returning * into result;
  return result;
end
$$;

revoke all on function public.profile_value_is_valid(text, jsonb) from public, anon, authenticated;
revoke all on function public.list_new_for_me() from public;
revoke all on function public.set_status(uuid, text, text) from public, anon, authenticated;
revoke all on function public.update_profile(text, jsonb) from public, anon, authenticated;

grant execute on function public.profile_value_is_valid(text, jsonb) to service_role;
grant execute on function public.list_new_for_me() to anon, authenticated, service_role;
grant execute on function public.set_status(uuid, text, text) to service_role;
grant execute on function public.update_profile(text, jsonb) to service_role;

comment on function public.profile_value_is_valid(text, jsonb) is
  'Shared typed profile contract for application updates and first-run seeding.';
