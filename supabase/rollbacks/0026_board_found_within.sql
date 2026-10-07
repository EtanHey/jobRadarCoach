-- Roll back 0026 before 0025 and before running a UI that sends found_within.
-- Restore the exact six-argument 0025 RPC and its service-role-only ACL.
begin;
set local lock_timeout = '5s';
drop function public.board_postings(text,text,text,text[],text,integer,text);
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
revoke all on function public.board_postings(text,text,text,text[],text,integer) from public,anon,authenticated;
grant execute on function public.board_postings(text,text,text,text[],text,integer) to service_role;
notify pgrst, 'reload schema';
commit;
