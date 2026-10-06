-- New-for-me is status-based; the unused visits timestamp no longer filters it.
create or replace function public.get_globe_snapshot(filter text default 'all', availability text default 'active')
returns jsonb language sql stable security invoker set search_path = '' as $$
  with selected as materialized (
    select p.id, p.first_seen_at,
      pg_catalog.to_jsonb(p) || pg_catalog.jsonb_build_object(
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
    where ($1='all' or s.status=$1 or ($1='new-for-me' and s.status='new'))
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
notify pgrst, 'reload schema';
