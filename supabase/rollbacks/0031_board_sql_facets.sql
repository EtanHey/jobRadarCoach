-- Revert the frontend facet consumers before applying this rollback.
begin;
drop function public.board_postings(text,text,text,text[],text,integer,text,text,text,text,text,boolean);
drop function public.board_location_group(text);
-- Extend the board query with the Not scored archive.
create or replace function public.board_postings(
  filter text default 'all', availability text default 'active', fit text default '',
  statuses text[] default '{}', sort text default 'fit', "max" integer default 1000, found_within text default ''
) returns setof public.postings
language plpgsql stable security invoker set search_path = '' as $$
declare ordering text;
begin
  if $6 is null or $6 not between 1 and 1000
    or $2 is null or $2 not in ('all','active','inactive')
    or $7 is null or $7 not in ('','24h','3d','7d','30d')
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
    where p.relevance_filtered=($1=''not-scored'')
      and ($1 in (''all'',''not-scored'') or coalesce(s.status,''new'')=case when $1=''new-for-me'' then ''new'' else $1 end)
      and ($7='''' or p.first_seen_at >= now() - case $7
        when ''24h'' then interval ''24 hours'' when ''3d'' then interval ''72 hours''
        when ''7d'' then interval ''168 hours'' when ''30d'' then interval ''720 hours'' end)
      and ($2=''all'' or ($2=''active'' and p.liveness->''alive'' is distinct from ''false''::jsonb)
        or ($2=''inactive'' and p.liveness->''alive''=''false''::jsonb))
      and (coalesce(cardinality($4),0)=0 or coalesce(s.status,''new'')=any($4))
      and ($3='''' or ($3=''recommended'' and ps.score is not null and ps.recommendation in (''apply'',''referral'',''review''))
        or ($3=''skip'' and ps.score is not null and ps.recommendation=''skip'')
        or ($3=''good'' and ps.score>=60) or ($3=''scored'' and ps.score is not null)
        or ($3=''unscored'' and ps.score is null))
    order by ' || ordering || ' limit $6'
    using $1,$2,$3,$4,$5,$6,$7;
end
$$;
revoke all on function public.board_postings(text,text,text,text[],text,integer,text) from public,anon,authenticated;
grant execute on function public.board_postings(text,text,text,text[],text,integer,text) to service_role;

notify pgrst, 'reload schema';
commit;
