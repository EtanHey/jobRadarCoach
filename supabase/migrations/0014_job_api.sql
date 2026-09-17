create function public.score_band(score smallint)
returns text language sql immutable strict security invoker set search_path = ''
as $$ select case when $1 >= 70 then 'strong' when $1 >= 40 then 'more' else 'below' end $$;

create function public.job_link_url(apply_url text, url text)
returns text language sql immutable security invoker set search_path = ''
as $$
  select pg_catalog.regexp_replace(coalesce(nullif($1, ''), $2),
    '^(https?://apply[.]workable[.]com(?::[0-9]+)?)/([^/?#]+)/jobs/view/([a-z0-9]+)[.]md([?#].*)?$',
    '\1/\2/j/\3/\4', 'i')
$$;

create function public.job_link_status(value text)
returns text language plpgsql immutable security invoker set search_path = ''
as $$
declare authority text; host_text text; port_text text; suffix text;
  host_ip inet; closing_bracket integer;
begin
  if value is null or value = '' then return 'no_link'; end if;
  if value ~ '[[:space:]]' or value !~* '^https?://' then return 'invalid_url'; end if;
  authority := substring(value from '^https?://([^/?#]*)');
  if authority is null or authority = '' or authority ~ '@' then return 'invalid_url'; end if;
  if pg_catalog.left(authority, 1) = '[' then
    closing_bracket := pg_catalog.strpos(authority, ']');
    if closing_bracket <= 2 then return 'invalid_url'; end if;
    host_text := substring(authority from 2 for closing_bracket - 2);
    if host_text !~ ':' then return 'invalid_url'; end if;
    host_ip := host_text::inet;
    suffix := substring(authority from closing_bracket + 1);
    if suffix <> '' and suffix !~ '^:[0-9]*$' then return 'invalid_url'; end if;
    port_text := substring(suffix from 2);
  else
    if pg_catalog.length(authority) - pg_catalog.length(pg_catalog.replace(authority, ':', '')) > 1 then
      return 'invalid_url';
    end if;
    if pg_catalog.strpos(authority, ':') > 0 then
      if pg_catalog.split_part(authority, ':', 1) = '' then return 'invalid_url'; end if;
      port_text := pg_catalog.split_part(authority, ':', 2);
      if port_text !~ '^[0-9]*$' then return 'invalid_url'; end if;
    end if;
  end if;
  if port_text is not null and port_text <> ''
     and (pg_catalog.length(port_text) > 5 or port_text::integer > 65535) then
    return 'invalid_url';
  end if;
  return 'available';
exception when invalid_text_representation or numeric_value_out_of_range then
  return 'invalid_url';
end
$$;

create type public.job_card as (
  id uuid, title text, company text, location text, score smallint, reasons jsonb,
  apply_url text, stack text[], remote boolean, seniority text, source text,
  last_seen_at timestamptz, experience text, description_available boolean,
  seniority_origin text, extraction_state text, salary text, url text,
  posted_at timestamptz, first_seen_at timestamptz, status text, status_reason text,
  fit_line text, recommendation text, alive boolean, link_url text, link_status text,
  score_band text, fit_tier text, seen boolean, seen_at timestamptz, pipeline_status text
);
create type public.job_counts as (strong integer, more integer, below integer, unscored integer);
create type public.job_detail as (
  id uuid, title text, company text, location text, score smallint, reasons jsonb,
  apply_url text, stack text[], remote boolean, seniority text, source text,
  last_seen_at timestamptz, experience text, description_available boolean,
  seniority_origin text, extraction_state text, salary text, url text,
  posted_at timestamptz, first_seen_at timestamptz, status text, status_reason text,
  fit_line text, recommendation text, alive boolean, link_url text, link_status text,
  score_band text, fit_tier text, seen boolean, seen_at timestamptz, pipeline_status text,
  raw_jd text, labels jsonb, score_payload jsonb, brain text, scored_at timestamptz
);

-- Derived text facts belong in posting_facts in J2a/J3 and must have one
-- Python implementation. J1 returns stored posting columns and does not
-- reimplement UI text heuristics from raw_jd or title.
create function public._job_card(posting_id uuid)
returns public.job_card language sql stable security invoker set search_path = ''
as $$
  with source as (select p.* from public.postings p where p.id = $1),
  links as (select source.*, public.job_link_url(source.apply_url, source.url) link_url from source)
  select p.id, p.title, p.company, p.location, ps.score, ps.reasons,
    public.job_link_url(p.apply_url, p.url), p.stack, p.remote, p.seniority, p.source,
    p.last_seen_at, null::text, p.raw_jd is not null and pg_catalog.btrim(p.raw_jd) <> '',
    case when p.seniority is not null then 'extracted' else 'unknown' end,
    case when exists (select 1 from public.posting_extractions e where e.posting_id = p.id)
      then 'extracted' else 'not-extracted' end,
    p.salary, public.job_link_url(p.url, p.url), p.posted_at, p.first_seen_at,
    coalesce(s.status, 'new'), s.reason, ps.score_payload->>'fit_line',
    ps.score_payload->>'recommendation',
    case when pg_catalog.jsonb_typeof(p.liveness->'alive') = 'boolean'
      then (p.liveness->>'alive')::boolean end,
    p.link_url, public.job_link_status(p.link_url), public.score_band(ps.score),
    ps.score_payload->>'fit_tier', coalesce(s.seen, false), s.seen_at,
    case when s.status in ('new', 'seen') then null else s.status end
  from links p left join public.posting_status s on s.posting_id = p.id
    left join public.posting_scores ps on ps.posting_id = p.id
$$;

create function public.search_jobs(
  seen boolean default false, min_score integer default null, location text default null,
  seniority text default null, query text default null, remote boolean default null,
  exclude_ids uuid[] default '{}'::uuid[], scored_only boolean default false, "max" integer default 20
) returns setof public.job_card
language plpgsql stable security invoker set search_path = ''
as $$
begin
  if $9 is null or $9 not between 1 and 1000 then
    raise exception using errcode = '22023', message = 'max must be between 1 and 1000';
  end if;
  if $2 is not null and $2 not between 0 and 100 then
    raise exception using errcode = '22023', message = 'min_score must be between 0 and 100';
  end if;
  return query select card.* from public.postings p
    left join public.posting_status s on s.posting_id = p.id
    left join public.posting_scores ps on ps.posting_id = p.id
    cross join lateral public._job_card(p.id) card
  where ($1 is null or coalesce(s.seen, false) = $1)
    and ($2 is null or ps.score >= $2)
    and ($3 is null or pg_catalog.strpos(pg_catalog.lower(coalesce(p.location, '')), pg_catalog.lower($3)) > 0)
    and ($4 is null or pg_catalog.lower(p.seniority) = pg_catalog.lower($4))
    and ($5 is null or pg_catalog.strpos(pg_catalog.lower(p.title), pg_catalog.lower($5)) > 0
      or pg_catalog.strpos(pg_catalog.lower(p.company), pg_catalog.lower($5)) > 0
      or exists (select 1 from pg_catalog.unnest(p.stack) technology
        where pg_catalog.strpos(pg_catalog.lower(technology), pg_catalog.lower($5)) > 0))
    and ($6 is null or p.remote = $6) and not (p.id = any(coalesce($7, '{}'::uuid[])))
    and (not coalesce($8, false) or ps.score is not null)
  order by ps.score desc nulls last, coalesce(p.posted_at, p.first_seen_at) desc, p.id limit $9;
end
$$;

create function public.count_jobs(
  seen boolean default false, min_score integer default null, location text default null,
  seniority text default null, query text default null, remote boolean default null,
  exclude_ids uuid[] default '{}'::uuid[], scored_only boolean default false
) returns public.job_counts
language plpgsql stable security invoker set search_path = ''
as $$
declare result public.job_counts;
begin
  if $2 is not null and $2 not between 0 and 100 then
    raise exception using errcode = '22023', message = 'min_score must be between 0 and 100';
  end if;
  select count(*) filter (where public.score_band(ps.score) = 'strong')::integer,
    count(*) filter (where public.score_band(ps.score) = 'more')::integer,
    count(*) filter (where public.score_band(ps.score) = 'below')::integer,
    count(*) filter (where ps.score is null)::integer into result
  from public.postings p left join public.posting_status s on s.posting_id = p.id
    left join public.posting_scores ps on ps.posting_id = p.id
  where ($1 is null or coalesce(s.seen, false) = $1) and ($2 is null or ps.score >= $2)
    and ($3 is null or pg_catalog.strpos(pg_catalog.lower(coalesce(p.location, '')), pg_catalog.lower($3)) > 0)
    and ($4 is null or pg_catalog.lower(p.seniority) = pg_catalog.lower($4))
    and ($5 is null or pg_catalog.strpos(pg_catalog.lower(p.title), pg_catalog.lower($5)) > 0
      or pg_catalog.strpos(pg_catalog.lower(p.company), pg_catalog.lower($5)) > 0
      or exists (select 1 from pg_catalog.unnest(p.stack) technology
        where pg_catalog.strpos(pg_catalog.lower(technology), pg_catalog.lower($5)) > 0))
    and ($6 is null or p.remote = $6) and not (p.id = any(coalesce($7, '{}'::uuid[])))
    and (not coalesce($8, false) or ps.score is not null);
  return result;
end
$$;

create function public.get_job(posting_id uuid)
returns setof public.job_detail language sql stable security invoker set search_path = ''
as $$
  select card.*, p.raw_jd, ps.labels, ps.score_payload, ps.brain, ps.scored_at
  from public.postings p left join public.posting_scores ps on ps.posting_id = p.id
    cross join lateral public._job_card(p.id) card where p.id = $1
$$;

revoke all on function public.score_band(smallint), public.job_link_url(text, text),
  public.job_link_status(text), public._job_card(uuid),
  public.search_jobs(boolean, integer, text, text, text, boolean, uuid[], boolean, integer),
  public.count_jobs(boolean, integer, text, text, text, boolean, uuid[], boolean),
  public.get_job(uuid) from public, anon, authenticated;
grant execute on function public.score_band(smallint), public.job_link_url(text, text),
  public.job_link_status(text), public._job_card(uuid),
  public.search_jobs(boolean, integer, text, text, text, boolean, uuid[], boolean, integer),
  public.count_jobs(boolean, integer, text, text, text, boolean, uuid[], boolean),
  public.get_job(uuid) to service_role;

comment on type public.job_card is 'Shared job card projection. Additive columns are appended at the end only.';
comment on type public.job_detail is 'Shared job card plus stored detail fields; new columns append at the end only.';
comment on function public.search_jobs(boolean, integer, text, text, text, boolean, uuid[], boolean, integer)
  is 'Bounded ranked job search over the shared card projection.';
comment on function public.count_jobs(boolean, integer, text, text, text, boolean, uuid[], boolean)
  is 'Score-band counts over the shared job search filters.';
comment on function public.get_job(uuid)
  is 'Read-only job detail lookup; missing ids return zero rows and never mark seen.';
notify pgrst, 'reload schema';
