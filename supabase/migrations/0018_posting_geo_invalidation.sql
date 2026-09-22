-- Apply locks posting inputs until commit; later input edits retire that posting's point.
-- Keep shared HQ evidence and immutable apply receipts for other postings/rollback.
create function public.invalidate_posting_geo() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  delete from public.posting_geo where posting_id = new.id;
  return new;
end
$$;
create trigger postings_invalidate_geo
  after update of location, company, remote on public.postings
  for each row when (
    old.location is distinct from new.location or
    old.company is distinct from new.company or
    old.remote is distinct from new.remote
  ) execute function public.invalidate_posting_geo();
revoke all on function public.invalidate_posting_geo() from public, anon, authenticated;
grant execute on function public.invalidate_posting_geo() to service_role;
