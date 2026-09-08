create type public.job_listing as (
  posting_id uuid, source text, external_id text, url text, title text, company text,
  location text, remote boolean, seniority text, stack text[], salary text, apply_url text,
  posted_at timestamptz, raw_jd text, status text, status_reason text,
  status_updated_at timestamptz, score smallint, reasons jsonb, labels jsonb,
  brain text, scored_at timestamptz
);

create function public.list_jobs(
  seen boolean default false,
  "max" integer default 5,
  min_score integer default null,
  location text default null,
  seniority text default null,
  query text default null
)
returns setof public.job_listing
language plpgsql
stable
security invoker
set search_path = ''
as $$
begin
  if $2 is null or $2 not between 1 and 1000 then
    raise exception using errcode = '22023', message = 'max must be between 1 and 1000';
  end if;
  if $3 is not null and $3 not between 0 and 100 then
    raise exception using errcode = '22023', message = 'min_score must be between 0 and 100';
  end if;

  return query
  select
    p.id, p.source, p.external_id, p.url, p.title, p.company, p.location, p.remote,
    p.seniority, p.stack, p.salary, p.apply_url, p.posted_at, p.raw_jd,
    coalesce(s.status, 'new'), s.reason, s.updated_at,
    ps.score, ps.reasons, ps.labels, ps.brain, ps.scored_at
  from public.postings p
  left join public.posting_status s on s.posting_id = p.id
  left join public.posting_scores ps on ps.posting_id = p.id
  where ($1 is null or (coalesce(s.status, 'new') <> 'new') = $1)
    and ($3 is null or ps.score >= $3)
    and ($4 is null or pg_catalog.strpos(
      pg_catalog.lower(coalesce(p.location, '')), pg_catalog.lower($4)
    ) > 0)
    and ($5 is null or pg_catalog.lower(p.seniority) = pg_catalog.lower($5))
    and ($6 is null
      or pg_catalog.strpos(pg_catalog.lower(p.title), pg_catalog.lower($6)) > 0
      or pg_catalog.strpos(pg_catalog.lower(p.company), pg_catalog.lower($6)) > 0
      or exists (
        select 1 from pg_catalog.unnest(p.stack) technology
        where pg_catalog.strpos(
          pg_catalog.lower(technology), pg_catalog.lower($6)
        ) > 0
      )
    )
  order by ps.score desc nulls last,
    coalesce(p.posted_at, p.first_seen_at) desc, p.id
  limit $2;
end
$$;

revoke all on function public.list_jobs(boolean, integer, integer, text, text, text)
  from public;
grant execute on function public.list_jobs(boolean, integer, integer, text, text, text)
  to anon, authenticated, service_role;

comment on function public.list_jobs(boolean, integer, integer, text, text, text) is
  'Bounded ranked job listing: unseen by default; seen null includes either workflow state.';

notify pgrst, 'reload schema';
