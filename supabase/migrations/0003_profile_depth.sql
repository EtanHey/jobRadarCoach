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
          or (item #>> '{}') not in ('remote', 'hybrid', 'onsite', 'on-site')
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
    when $1 = 'candidate.professional_depth' then
      case when pg_catalog.jsonb_typeof($2) = 'object' then not exists (
        select 1 from pg_catalog.jsonb_each($2) depth
        where depth.key !~ '[^[:space:]]'
          or pg_catalog.jsonb_typeof(depth.value) <> 'array'
          or pg_catalog.jsonb_array_length(depth.value) = 0
          or exists (
            select 1 from pg_catalog.jsonb_array_elements(depth.value) label
            where pg_catalog.jsonb_typeof(label) <> 'string'
              or (label #>> '{}') not in ('hands-on', 'directed-AI', 'studied-with-AI')
          )
          or pg_catalog.jsonb_array_length(depth.value) <> (
            select count(distinct label) from pg_catalog.jsonb_array_elements_text(depth.value) label
          )
      ) else false end
    when $1 = 'runtime.brain' then
      pg_catalog.jsonb_typeof($2) = 'string'
        and ($2 #>> '{}') in ('ollama', 'codex', 'claude', 'cursor-agent')
    else false
  end
$$;

comment on function public.profile_value_is_valid(text, jsonb) is
  'Shared typed profile contract. Empty professional_depth means unratified/unset, not no knowledge.';
