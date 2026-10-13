begin;
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

create or replace function public.get_globe_snapshot(filter text default 'all', availability text default 'active')
returns jsonb language sql stable security invoker set search_path = '' as $$
  with selected as materialized (
    select p.id, p.first_seen_at,
      pg_catalog.jsonb_build_object(
        'source',p.source,'last_seen_at',p.last_seen_at,'list_metadata',p.list_metadata,
        'relevance_gate',p.relevance_gate,'relevance_filtered',p.relevance_filtered,'liveness',p.liveness,'id',p.id,'title',p.title,
        'company',p.company,'location',p.location,'remote',p.remote,
        'work_mode',p.work_mode,'seniority',p.seniority,'stack',p.stack,
        'salary',p.salary,'url',p.url,'apply_url',p.apply_url,
        'posted_at',p.posted_at,'last_published_at',p.last_published_at,'first_seen_at',p.first_seen_at) || pg_catalog.jsonb_build_object(
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
    where p.relevance_filtered=($1='not-scored')
      and ($1 in ('all','not-scored') or s.status=$1 or ($1='new-for-me' and s.status='new'))
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

-- Queue only the first override transition. Replays after acknowledgement still
-- succeed for an existing row without requesting another model call.
create function public.score_anyway(posting_id uuid) returns boolean
language sql security invoker set search_path='' as $$
  with changed as (update public.postings p
    set relevance_gate=p.relevance_gate || '{"override":true,"score_requested":true}'::jsonb
    where p.id=$1 and not coalesce((p.relevance_gate->>'override')::boolean,false)
    returning p.id)
  select exists(select 1 from changed) or exists(select 1 from public.postings p where p.id=$1)
$$;
revoke all on function public.score_anyway(uuid) from public,anon,authenticated;
grant execute on function public.score_anyway(uuid) to service_role;
notify pgrst, 'reload schema';
commit;
