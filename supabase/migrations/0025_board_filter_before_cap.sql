begin;
-- Abort a contended hosted apply instead of waiting indefinitely for table locks.
set local lock_timeout = '5s';
alter table public.posting_scores add column recommendation text
  generated always as (score_payload->>'recommendation') stored;
alter table public.postings add column sort_posted_at timestamptz
  generated always as (coalesce(posted_at,first_seen_at)) stored;

-- Match titleSeniority followed by levelGroup; filtering seniority stays client-side.
create function public.board_level_rank(seniority text, title text)
returns integer language sql immutable security invoker set search_path = '' as $$
  with level as (select coalesce($1,case
    when ($2 collate "C") ~* '(?<![A-Za-z0-9_])(intern|internship)(?![A-Za-z0-9_])' then 'Intern'
    when ($2 collate "C") ~* '(?<![A-Za-z0-9_])(junior|jr\.?|graduate|entry[- ]level)(?![A-Za-z0-9_])' then 'Junior'
    when ($2 collate "C") ~* '(?<![A-Za-z0-9_])(principal|staff)(?![A-Za-z0-9_])' then 'Staff'
    when ($2 collate "C") ~* '(?<![A-Za-z0-9_])(lead|manager|head|director)(?![A-Za-z0-9_])' then 'Lead'
    when ($2 collate "C") ~* '(?<![A-Za-z0-9_])(senior|sr\.?)(?![A-Za-z0-9_])' then 'Senior'
    when ($2 collate "C") ~* '(?<![A-Za-z0-9_])(mid[- ]level|intermediate)(?![A-Za-z0-9_])' then 'Mid'
  end) value)
  select case
    when (value collate "C") ~* 'intern' then 0
    when (value collate "C") ~* 'junior|entry|graduate' then 1
    when (value collate "C") ~* 'staff|principal' then 5
    when (value collate "C") ~* 'lead|manager|director|head' then 4
    when (value collate "C") ~* 'senior' then 3
    when (value collate "C") ~* 'mid|intermediate' then 2
    else 6 end from level
$$;
-- localeCompare treats canonically equivalent Unicode titles as equal. Keep
-- ICU ties for first_seen_at/id rather than adding a bytewise title tie-break.
create collation public.board_title (provider = icu, locale = 'en-US', deterministic = false);
-- Date.parse compares milliseconds; preserve that tie semantics before the cap.
create index postings_sort_posted_idx on public.postings
  (date_trunc('milliseconds',sort_posted_at,'UTC') desc, first_seen_at desc, id);
create index postings_board_level_idx on public.postings
  (public.board_level_rank(seniority,title), title collate public.board_title, first_seen_at desc, id);
create index posting_scores_recommendation_idx on public.posting_scores(recommendation,score desc,posting_id);

-- A postings row type preserves PostgREST's existing to-one embeds. The limit is
-- inside SQL after every board facet/order; poll and ID reads use their old paths.
create function public.board_postings(
  filter text default 'all', availability text default 'active', fit text default '',
  statuses text[] default '{}', sort text default 'fit', "max" integer default 1000
) returns setof public.postings
language plpgsql stable security invoker set search_path = '' as $$
declare ordering text;
begin
  if $6 is null or $6 not between 1 and 1000
    or $2 is null or $2 not in ('all','active','inactive')
    or $3 is null or $3 not in ('','recommended','skip','good','scored','unscored') then
    raise exception using errcode='22023', message='Invalid board filters';
  end if;
  ordering := case $5
    when 'fit' then 'ps.score desc nulls last,date_trunc(''milliseconds'',p.sort_posted_at,''UTC'') desc,p.id'
    when 'posted' then 'date_trunc(''milliseconds'',p.sort_posted_at,''UTC'') desc,p.first_seen_at desc,p.id'
    when 'found' then 'p.first_seen_at desc,p.id'
    when 'seniority' then 'public.board_level_rank(p.seniority,p.title),p.title collate public.board_title,p.first_seen_at desc,p.id'
  end;
  if ordering is null then
    raise exception using errcode='22023', message='Invalid board sort';
  end if;
  -- Only the whitelist above is interpolated; all user values stay parameters.
  return query execute 'select p.* from public.postings p
    left join public.posting_status s on s.posting_id=p.id
    left join public.posting_scores ps on ps.posting_id=p.id
    where ($1=''all'' or coalesce(s.status,''new'')=case when $1=''new-for-me'' then ''new'' else $1 end)
      and ($2=''all'' or ($2=''active'' and p.liveness->''alive'' is distinct from ''false''::jsonb)
        or ($2=''inactive'' and p.liveness->''alive''=''false''::jsonb))
      and (coalesce(cardinality($4),0)=0 or coalesce(s.status,''new'')=any($4))
      and ($3='''' or ($3=''recommended'' and ps.score is not null and ps.recommendation in (''apply'',''referral'',''review''))
        or ($3=''skip'' and ps.score is not null and ps.recommendation=''skip'')
        or ($3=''good'' and ps.score>=60) or ($3=''scored'' and ps.score is not null)
        or ($3=''unscored'' and ps.score is null))
    order by ' || ordering || ' limit $6'
    using $1,$2,$3,$4,$5,$6;
end
$$;
revoke all on function public.board_level_rank(text,text),
  public.board_postings(text,text,text,text[],text,integer) from public,anon,authenticated;
grant execute on function public.board_level_rank(text,text),
  public.board_postings(text,text,text,text[],text,integer) to service_role;
notify pgrst, 'reload schema';
commit;
