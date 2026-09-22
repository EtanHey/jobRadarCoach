create function public.hq_source_is_valid(source text)
returns boolean language sql immutable security invoker set search_path = '' as $$
  select $1 ~ '^https://[A-Za-z0-9.-]+(:[0-9]+)?(/[^[:space:]|]*)? [|] nominatim:osm:(node|way|relation):[1-9][0-9]*$'
$$;
create function public.posting_hq_eligible(location text, remote boolean)
returns boolean language sql immutable security invoker set search_path = '' as $$
  select $2 is true or pg_catalog.lower(pg_catalog.btrim(coalesce($1,'')))
    in ('','remote','hybrid','on-site','onsite','worldwide','anywhere')
$$;
revoke all on function public.hq_source_is_valid(text), public.posting_hq_eligible(text,boolean) from public, anon, authenticated;
grant execute on function public.hq_source_is_valid(text), public.posting_hq_eligible(text,boolean) to service_role;

-- Approximate place centroids. HQ is always explicitly distinguished from a job location.
create table public.posting_geo (
  posting_id uuid primary key references public.postings(id) on delete cascade,
  lat double precision not null check (lat between -90 and 90),
  lng double precision not null check (lng between -180 and 180),
  precision text not null check (precision in ('city','region','country','hq')),
  check (precision <> 'hq' or public.hq_source_is_valid(source)),
  source text not null check (btrim(source) <> ''),
  resolved_at timestamptz not null default now()
);
create table public.company_hq (
  company text primary key check (btrim(company) <> ''),
  lat double precision not null check (lat between -90 and 90),
  lng double precision not null check (lng between -180 and 180),
  city text not null,
  country text not null,
  source text not null check (public.hq_source_is_valid(source)),
  resolved_at timestamptz not null default now()
);
alter table public.posting_geo enable row level security;
alter table public.company_hq enable row level security;
revoke all on public.posting_geo, public.company_hq from public, anon, authenticated;
grant select, insert, update, delete on public.posting_geo, public.company_hq to service_role;

-- Called in batches for the full filtered set, never limited to the visible rail.
-- Exact company names prevent accidental joins between similarly named employers.
create function public.get_job_geo(posting_ids uuid[])
returns table (posting_id uuid, lat double precision, lng double precision,
  "precision" text, source text, resolved_at timestamptz)
language sql stable security invoker set search_path = '' as $$
  select p.id, coalesce(g.lat,h.lat), coalesce(g.lng,h.lng),
    case when g.posting_id is not null then g.precision else 'hq' end,
    coalesce(g.source,h.source), coalesce(g.resolved_at,h.resolved_at)
  from public.postings p
  left join public.posting_geo g on g.posting_id = p.id
  left join public.company_hq h on h.company = p.company and g.posting_id is null
    and public.posting_hq_eligible(p.location,p.remote)
  where p.id = any($1) and (g.posting_id is not null or h.company is not null)
$$;
revoke all on function public.get_job_geo(uuid[]) from public, anon, authenticated;
grant execute on function public.get_job_geo(uuid[]) to service_role;
comment on table public.posting_geo is 'Geocoded posting place centroids, never inferred office addresses.';
comment on table public.company_hq is 'Evidence-backed HQ locations; not job locations. Source includes evidence URL.';
notify pgrst, 'reload schema';

-- One stable statement pins jobs, visit cutoff, scores and geo to the same MVCC snapshot.
-- Return one JSON object so PostgREST row caps cannot truncate the posting population.
create function public.get_globe_snapshot(filter text default 'all', availability text default 'active')
returns jsonb language sql stable security invoker set search_path = '' as $$
  with selected as materialized (
    select p.id, p.first_seen_at,
      pg_catalog.to_jsonb(p) || pg_catalog.jsonb_build_object(
        'posting_status', case when s.posting_id is not null then
          pg_catalog.jsonb_build_object('status',s.status,'reason',s.reason) end,
        'posting_scores', case when ps.posting_id is not null then
          pg_catalog.jsonb_build_object('score',ps.score,'score_payload',ps.score_payload) end,
        'posting_extractions', case when e.posting_id is not null then
          pg_catalog.jsonb_build_object('posting_id',e.posting_id) end) as summary
    from public.postings p
    left join public.posting_status s on s.posting_id=p.id
    left join public.posting_scores ps on ps.posting_id=p.id
    left join public.posting_extractions e on e.posting_id=p.id
    where ($1='all' or s.status=$1 or ($1='new-for-me' and s.status='new' and
      ((select last_visit_at from public.visits where singleton) is null or
       coalesce(p.posted_at,p.first_seen_at) > (select last_visit_at from public.visits where singleton))))
      and ($2='all' or ($2='active' and p.liveness->'alive' is distinct from 'false'::jsonb)
        or ($2='inactive' and p.liveness->'alive'='false'::jsonb))
  )
  select pg_catalog.jsonb_build_object(
    'jobs', coalesce((select pg_catalog.jsonb_agg(summary order by first_seen_at desc,id) from selected),'[]'::jsonb),
    'geo', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(g)) from public.get_job_geo(
      coalesce((select pg_catalog.array_agg(id) from selected),'{}'::uuid[])) g),'[]'::jsonb))
$$;
revoke all on function public.get_globe_snapshot(text,text) from public, anon, authenticated;
grant execute on function public.get_globe_snapshot(text,text) to service_role;
notify pgrst, 'reload schema';
