begin;
-- SET clauses prevent SQL table-function inlining and force each poll to scan
-- every marker. A parsed SQL body binds tables, functions, casts and operators
-- at CREATE time, so caller search_path cannot redirect them after removing SET.
-- Explicitly pin the creation path; the function itself has no SET clause.
set local search_path = pg_catalog;
create or replace function public.board_marker_rows()
returns table(id uuid, first_seen_at timestamptz, relevance_filtered boolean, alive boolean, status text, marker jsonb)
language sql stable security invoker
begin atomic
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
;
end;
revoke all on function public.board_marker_rows() from public,anon,authenticated;
grant execute on function public.board_marker_rows() to service_role;
notify pgrst,'reload schema';
commit;
