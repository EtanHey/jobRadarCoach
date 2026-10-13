-- posted_at remains the earliest known publication, never an edit/update time.
-- Older originals already overwritten by historical scrapes cannot be reconstructed.
alter table public.postings add column last_published_at timestamptz;
update public.postings set last_published_at = posted_at;
comment on column public.postings.posted_at is
  'Earliest known source publication date for this source/external_id; may be a repost if the original was never observed.';
comment on column public.postings.last_published_at is
  'Latest observed source publication date; not the last edit or JRC observation time.';

-- Protect all writers, including older scraper installations during rollout.
create function public.preserve_publication_dates() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  if TG_OP = 'UPDATE' then
    new.last_published_at := greatest(old.last_published_at, old.posted_at,
                                      new.last_published_at, new.posted_at);
    new.posted_at := least(old.posted_at, new.posted_at);
  else
    new.last_published_at := greatest(new.last_published_at, new.posted_at);
  end if;
  return new;
end
$$;
create trigger postings_preserve_publication_dates
before insert or update of posted_at, last_published_at on public.postings
for each row execute function public.preserve_publication_dates();
revoke all on function public.preserve_publication_dates() from public, anon, authenticated;
grant execute on function public.preserve_publication_dates() to service_role;

alter type public.job_card add attribute last_published_at timestamptz;
alter type public.job_detail add attribute last_published_at timestamptz;
create or replace function public._job_card(posting_id uuid)
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
    p.link_url, public.score_band(ps.score),
    ps.score_payload->>'fit_tier', coalesce(s.seen, false), s.seen_at,
    case when s.status in ('new', 'seen') then null else s.status end,
    p.last_published_at
  from links p left join public.posting_status s on s.posting_id = p.id
    left join public.posting_scores ps on ps.posting_id = p.id
$$;

-- Populate by name: new card attributes must not shift the existing detail fields.
create or replace function public.get_job(posting_id uuid)
returns setof public.job_detail language sql stable security invoker set search_path = '' as $$
  select detail.*
  from public.postings p left join public.posting_scores ps on ps.posting_id = p.id
    cross join lateral public._job_card(p.id) card
    cross join lateral pg_catalog.jsonb_populate_record(null::public.job_detail,
      pg_catalog.to_jsonb(card) || pg_catalog.jsonb_build_object(
        'raw_jd',p.raw_jd,'labels',ps.labels,'score_payload',ps.score_payload,
        'brain',ps.brain,'scored_at',ps.scored_at)) detail
  where p.id = $1
$$;
notify pgrst, 'reload schema';
