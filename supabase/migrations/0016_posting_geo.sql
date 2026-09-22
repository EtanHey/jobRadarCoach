-- Approximate place centroids. HQ is always explicitly distinguished from a job location.
create table public.posting_geo (
  posting_id uuid primary key references public.postings(id) on delete cascade,
  lat double precision not null check (lat between -90 and 90),
  lng double precision not null check (lng between -180 and 180),
  precision text not null check (precision in ('city','region','country','hq')),
  source text not null check (btrim(source) <> ''),
  resolved_at timestamptz not null default now()
);
create table public.company_hq (
  company text primary key check (btrim(company) <> ''),
  lat double precision not null check (lat between -90 and 90),
  lng double precision not null check (lng between -180 and 180),
  city text not null,
  country text not null,
  source text not null check (btrim(source) <> ''),
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
  where p.id = any($1) and (g.posting_id is not null or h.company is not null)
$$;
revoke all on function public.get_job_geo(uuid[]) from public, anon, authenticated;
grant execute on function public.get_job_geo(uuid[]) to service_role;
comment on table public.posting_geo is 'Geocoded posting place centroids, never inferred office addresses.';
comment on table public.company_hq is 'Evidence-backed HQ locations; not job locations. Source includes evidence URL.';
notify pgrst, 'reload schema';
