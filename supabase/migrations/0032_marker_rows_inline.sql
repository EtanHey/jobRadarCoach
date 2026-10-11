begin;
-- SET clauses prevent SQL table-function inlining and force each poll to scan
-- every marker. Qualify all relations, functions, casts and operators so caller
-- search_path cannot redirect them after removing SET. Use a quoted SQL body:
-- Supabase CLI 2.116.0 mis-splits BEGIN ATOMIC bodies containing CASE/END:
-- https://github.com/supabase/cli/issues/3474
set local search_path = pg_catalog;
create or replace function public.board_marker_rows()
returns table(id uuid, first_seen_at timestamptz, relevance_filtered boolean, alive boolean, status text, marker jsonb)
language sql stable security invoker as $$
  select p.id,p.first_seen_at,p.relevance_filtered,
    case when pg_catalog.jsonb_typeof(p.liveness operator(pg_catalog.->) 'alive') operator(pg_catalog.=) 'boolean'
      then (p.liveness operator(pg_catalog.->>) 'alive')::pg_catalog.bool end,
    coalesce(s.status,'new'),
    pg_catalog.jsonb_build_object(
      'id',p.id,'title',p.title,'company',p.company,'source',p.source,'location',p.location,
      'remote',p.remote,'work_mode',p.work_mode,'seniority',p.seniority,
      'stack',case when pg_catalog.cardinality(p.stack) operator(pg_catalog.>) 0 then pg_catalog.to_jsonb(p.stack)
        else p.list_metadata operator(pg_catalog.->) 'stack' end,
      'url',p.url,'apply_url',p.apply_url,'posted_at',p.posted_at,'last_published_at',p.last_published_at,
      'first_seen_at',p.first_seen_at,'status',coalesce(s.status,'new'),'status_reason',s.reason,
      'score',case when not p.relevance_filtered then ps.score end,
      'recommendation',case when not p.relevance_filtered then ps.recommendation end,
      'relevance_filtered',p.relevance_filtered,
      'alive',case when pg_catalog.jsonb_typeof(p.liveness operator(pg_catalog.->) 'alive') operator(pg_catalog.=) 'boolean'
        then (p.liveness operator(pg_catalog.->>) 'alive')::pg_catalog.bool end)
  from public.postings p left join public.posting_status s on s.posting_id operator(pg_catalog.=) p.id
  left join public.posting_scores ps on ps.posting_id operator(pg_catalog.=) p.id
$$;
revoke all on function public.board_marker_rows() from public,anon,authenticated;
grant execute on function public.board_marker_rows() to service_role;
notify pgrst,'reload schema';
commit;
