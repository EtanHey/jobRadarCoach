-- One-shot migration after 0019_publication_dates; not idempotent after success.
-- Record successful apply; do not rerun it. Any failure rolls back the whole DDL,
-- so retry only after fixing the cause. No inferred default from a city alone.
-- Rollback only after reverting/stopping column consumers, in one transaction:
-- drop work_mode attributes from job_detail, then job_card; restore _job_card/get_job
-- from 0019; drop postings_work_mode_provenance and both work-mode columns;
-- notify pgrst to reload, then commit. This discards stored work-mode values.
begin;
alter table public.postings
  add column work_mode text check (work_mode in ('hybrid', 'remote', 'on-site')),
  add column work_mode_source text check (work_mode_source in ('structured', 'location', 'extracted')),
  add constraint postings_work_mode_provenance check ((work_mode is null) = (work_mode_source is null));
alter type public.job_card add attribute work_mode text;
alter type public.job_detail add attribute work_mode text;

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
    p.last_published_at, p.work_mode
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
commit;
