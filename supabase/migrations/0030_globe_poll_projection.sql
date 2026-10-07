begin;
create function public.board_marker_rows()
returns table(id uuid, first_seen_at timestamptz, relevance_filtered boolean, alive boolean, status text, marker jsonb)
language sql stable security invoker set search_path='' as $$
  select p.id,p.first_seen_at,p.relevance_filtered,
    case when pg_catalog.jsonb_typeof(p.liveness->'alive')='boolean' then (p.liveness->>'alive')::boolean end,
    coalesce(s.status,'new'),
    pg_catalog.jsonb_build_object(
      'id',p.id,'title',p.title,'company',p.company,'source',p.source,'location',p.location,
      'remote',p.remote,'work_mode',p.work_mode,'seniority',p.seniority,
      'stack',case when pg_catalog.cardinality(p.stack)>0 then pg_catalog.to_jsonb(p.stack) else p.list_metadata->'stack' end,
      'url',p.url,'apply_url',p.apply_url,'posted_at',p.posted_at,'last_published_at',p.last_published_at,
      'first_seen_at',p.first_seen_at,'status',coalesce(s.status,'new'),'status_reason',s.reason,
      'score',case when not p.relevance_filtered then ps.score end,
      'recommendation',case when not p.relevance_filtered then ps.recommendation end,
      'relevance_filtered',p.relevance_filtered,
      'alive',case when pg_catalog.jsonb_typeof(p.liveness->'alive')='boolean' then (p.liveness->>'alive')::boolean end)
  from public.postings p left join public.posting_status s on s.posting_id=p.id
  left join public.posting_scores ps on ps.posting_id=p.id
$$;
create function public.marker_window(found_within text) returns interval
language plpgsql immutable set search_path='' as $$
begin
  if $1 is null or $1 not in ('','24h','3d','7d','30d') then
    raise exception using errcode='22023',message='Invalid found window';
  end if;
  return case $1 when '24h' then interval '24 hours' when '3d' then interval '72 hours'
    when '7d' then interval '168 hours' when '30d' then interval '720 hours' end;
end $$;
create function public.get_globe_markers(filter text default 'all', availability text default 'active', found_within text default '')
returns jsonb language sql stable security invoker set search_path='' as $$
  with selected as materialized (
    select m.* from public.board_marker_rows() m
    where m.relevance_filtered=($1='not-scored')
      and ($1 in ('all','not-scored') or m.status=case when $1='new-for-me' then 'new' else $1 end)
      and ($2='all' or ($2='active' and m.alive is distinct from false) or ($2='inactive' and m.alive=false))
      and ($3='' or m.first_seen_at>=now()-public.marker_window($3))
  )
  select pg_catalog.jsonb_build_object(
    'jobs',coalesce((select pg_catalog.jsonb_agg(marker order by first_seen_at desc,id) from selected),'[]'::jsonb),
    'geo',coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(g)) from public.get_job_geo(
      coalesce((select pg_catalog.array_agg(id) from selected),'{}'::uuid[])) g),'[]'::jsonb))
$$;
create function public.get_new_roles_snapshot(filter text,availability text,since timestamptz,found_within text default '',ids uuid[] default '{}')
returns jsonb language sql stable security invoker set search_path='' as $$
  with incoming as (
    select m.* from public.board_marker_rows() m
    where m.first_seen_at>$3 and m.relevance_filtered=($1='not-scored')
      and ($1 in ('all','not-scored') or m.status=case when $1='new-for-me' then 'new' else $1 end)
      and ($2='all' or ($2='active' and m.alive is distinct from false) or ($2='inactive' and m.alive=false))
      and ($4='' or m.first_seen_at>=now()-public.marker_window($4))
    order by m.first_seen_at desc,m.id limit 101
  ), relevant_current as (
    select m.marker from public.board_marker_rows() m
    where m.id=any($5) and not m.relevance_filtered
  )
  select pg_catalog.jsonb_build_object(
    'incoming',coalesce((select pg_catalog.jsonb_agg(marker order by first_seen_at desc,id) from incoming),'[]'::jsonb),
    'current',coalesce((select pg_catalog.jsonb_agg(marker) from relevant_current),'[]'::jsonb))
$$;
revoke all on function public.board_marker_rows(),public.marker_window(text),public.get_globe_markers(text,text,text),public.get_new_roles_snapshot(text,text,timestamptz,text,uuid[]) from public,anon,authenticated;
grant execute on function public.board_marker_rows(),public.marker_window(text),public.get_globe_markers(text,text,text),public.get_new_roles_snapshot(text,text,timestamptz,text,uuid[]) to service_role;
notify pgrst,'reload schema';
commit;
