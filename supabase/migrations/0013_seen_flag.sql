alter table public.posting_status
  add column seen boolean not null default false,
  add column seen_at timestamptz;

-- Historical seen_at is approximate: updated_at is the only legacy transition time.
update public.posting_status
set seen = status <> 'new',
    seen_at = case when status <> 'new' then updated_at end;

alter table public.posting_status
  drop constraint posting_status_value,
  add constraint posting_status_value check (status in (
    'new', 'seen', 'worth_checking', 'skipped', 'applied', 'screen',
    'interview_technical', 'interview_final', 'offer', 'contract',
    'rejected', 'archived', 'not_relevant'
  ));
alter table public.posting_status_history
  drop constraint posting_status_history_status_from,
  drop constraint posting_status_history_status_to,
  add constraint posting_status_history_status_from check (
    status_from is null or status_from in (
      'new', 'seen', 'worth_checking', 'skipped', 'applied', 'screen',
      'interview_technical', 'interview_final', 'offer', 'contract',
      'rejected', 'archived', 'not_relevant'
    )
  ),
  add constraint posting_status_history_status_to check (status_to in (
    'new', 'seen', 'worth_checking', 'skipped', 'applied', 'screen',
    'interview_technical', 'interview_final', 'offer', 'contract',
    'rejected', 'archived', 'not_relevant'
  ));

create function public.derive_posting_seen()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  if tg_op = 'INSERT' then
    new.seen := new.status <> 'new';
    new.seen_at := case when new.seen
      then coalesce(new.seen_at, pg_catalog.clock_timestamp()) else null end;
  elsif new.status is distinct from old.status then
    new.seen := new.status <> 'new';
    new.seen_at := case when new.seen
      then coalesce(old.seen_at, new.seen_at, pg_catalog.clock_timestamp())
      else null end;
  elsif new.seen is distinct from old.seen then
    if new.seen and old.status = 'new' then
      new.status := 'seen';
      new.seen_at := coalesce(old.seen_at, new.seen_at, pg_catalog.clock_timestamp());
    elsif not new.seen and old.status = 'seen' then
      new.status := 'new';
      new.seen_at := null;
    elsif not new.seen then
      raise exception using errcode = '22023',
        message = 'cannot mark a pipeline status unseen';
    else
      new.seen_at := coalesce(old.seen_at, new.seen_at, pg_catalog.clock_timestamp());
    end if;
  else
    new.seen := new.status <> 'new';
    new.seen_at := case when new.seen then old.seen_at else null end;
  end if;
  return new;
end
$$;
create trigger posting_status_derive_seen
before insert or update on public.posting_status
for each row execute function public.derive_posting_seen();
revoke all on function public.derive_posting_seen() from public, anon, authenticated;

create or replace function public.set_status(
  posting_id uuid, status text, reason text default null
) returns public.posting_status
language plpgsql security invoker set search_path = '' as $$
declare result public.posting_status; stored_reason text;
begin
  if $2 is null or $2 not in (
    'new', 'seen', 'worth_checking', 'skipped', 'applied', 'screen',
    'interview_technical', 'interview_final', 'offer', 'contract',
    'rejected', 'archived', 'not_relevant'
  ) then
    raise exception using errcode = '22023', message = 'unsupported posting status';
  end if;
  if $2 = 'rejected' and ($3 is null or not ($3 ~ '[^[:space:]]')) then
    raise exception using errcode = '22023', message = 'rejected status requires a nonblank reason';
  end if;
  if $2 = 'not_relevant' and $3 is not null and not ($3 ~ '[^[:space:]]') then
    raise exception using errcode = '22023', message = 'not_relevant reason must be null or nonblank';
  end if;
  if $2 not in ('rejected', 'not_relevant') and $3 is not null then
    raise exception using errcode = '22023', message = 'reason is unsupported for this posting status';
  end if;
  stored_reason := case when $2 in ('rejected', 'not_relevant') then $3 end;
  perform 1 from public.postings p where p.id = $1 for update;
  if not found then raise exception using errcode = 'P0002', message = 'posting does not exist'; end if;
  perform 1 from public.posting_status s where s.posting_id = $1 for update;
  insert into public.posting_status as current_status (posting_id, status, reason)
  values ($1, $2, stored_reason)
  on conflict on constraint posting_status_pkey do update set
    status = excluded.status, reason = excluded.reason
  returning * into result;
  return result;
end
$$;

create function public.mark_seen(posting_id uuid)
returns public.posting_status language plpgsql security invoker set search_path = '' as $$
declare result public.posting_status;
begin
  perform 1 from public.postings p where p.id = $1 for update;
  if not found then raise exception using errcode = 'P0002', message = 'posting does not exist'; end if;
  insert into public.posting_status as current_status (posting_id, status)
  values ($1, 'seen')
  on conflict on constraint posting_status_pkey do update set seen = true
  returning * into result;
  return result;
end
$$;

create function public.set_seen(posting_id uuid, seen boolean)
returns public.posting_status language plpgsql security invoker set search_path = '' as $$
declare result public.posting_status;
begin
  if $2 is null then raise exception using errcode = '22023', message = 'seen must not be null'; end if;
  perform 1 from public.postings p where p.id = $1 for update;
  if not found then raise exception using errcode = 'P0002', message = 'posting does not exist'; end if;
  insert into public.posting_status as current_status (posting_id, status)
  values ($1, case when $2 then 'seen' else 'new' end)
  on conflict on constraint posting_status_pkey do update set seen = excluded.seen
  returning * into result;
  return result;
end
$$;

drop function public.list_jobs(boolean, integer, integer, text, text, text);
drop type public.job_listing;
create type public.job_listing as (
  posting_id uuid, source text, external_id text, url text, title text, company text,
  location text, remote boolean, seniority text, stack text[], salary text, apply_url text,
  posted_at timestamptz, raw_jd text, status text, status_reason text,
  status_updated_at timestamptz, seen boolean, seen_at timestamptz, pipeline_status text,
  score smallint, reasons jsonb, labels jsonb, brain text, scored_at timestamptz
);
create function public.list_jobs(
  seen boolean default false, "max" integer default 5, min_score integer default null,
  location text default null, seniority text default null, query text default null
) returns setof public.job_listing language plpgsql stable security invoker set search_path = '' as $$
begin
  if $2 is null or $2 not between 1 and 1000 then
    raise exception using errcode = '22023', message = 'max must be between 1 and 1000';
  end if;
  if $3 is not null and $3 not between 0 and 100 then
    raise exception using errcode = '22023', message = 'min_score must be between 0 and 100';
  end if;
  return query select
    p.id, p.source, p.external_id, p.url, p.title, p.company, p.location, p.remote,
    p.seniority, p.stack, p.salary, p.apply_url, p.posted_at, p.raw_jd,
    coalesce(s.status, 'new'), s.reason, s.updated_at, coalesce(s.seen, false), s.seen_at,
    case when s.status in ('new', 'seen') then null else s.status end,
    ps.score, ps.reasons, ps.labels, ps.brain, ps.scored_at
  from public.postings p
  left join public.posting_status s on s.posting_id = p.id
  left join public.posting_scores ps on ps.posting_id = p.id
  where ($1 is null or coalesce(s.seen, false) = $1)
    and ($3 is null or ps.score >= $3)
    and ($4 is null or pg_catalog.strpos(pg_catalog.lower(coalesce(p.location, '')), pg_catalog.lower($4)) > 0)
    and ($5 is null or pg_catalog.lower(p.seniority) = pg_catalog.lower($5))
    and ($6 is null or pg_catalog.strpos(pg_catalog.lower(p.title), pg_catalog.lower($6)) > 0
      or pg_catalog.strpos(pg_catalog.lower(p.company), pg_catalog.lower($6)) > 0
      or exists (select 1 from pg_catalog.unnest(p.stack) technology
        where pg_catalog.strpos(pg_catalog.lower(technology), pg_catalog.lower($6)) > 0))
  order by ps.score desc nulls last, coalesce(p.posted_at, p.first_seen_at) desc, p.id
  limit $2;
end
$$;

revoke all on function public.mark_seen(uuid), public.set_seen(uuid, boolean),
  public.list_jobs(boolean, integer, integer, text, text, text) from public, anon, authenticated;
grant execute on function public.mark_seen(uuid), public.set_seen(uuid, boolean),
  public.list_jobs(boolean, integer, integer, text, text, text) to service_role;
comment on function public.list_jobs(boolean, integer, integer, text, text, text) is
  'Bounded ranked job listing filtered by the independent seen flag.';
notify pgrst, 'reload schema';
