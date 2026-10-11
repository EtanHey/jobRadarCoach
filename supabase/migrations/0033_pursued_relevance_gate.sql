begin;
-- Clear the active rejection for every owner-managed pipeline status. Retain
-- the rule so returning an unchanged role to discovery restores the archive.
-- The existing title/JD reset trigger invalidates this saved rule too.
create function public.protect_pursued_relevance_gate() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if new.status not in ('new','seen') then
    update public.postings p
      set relevance_gate=p.relevance_gate || pg_catalog.jsonb_build_object(
        'pursued_rule',p.relevance_gate->'rule','rule',null)
      where p.id=new.posting_id and p.relevance_filtered;
  else
    update public.postings p
      set relevance_gate=(p.relevance_gate - 'pursued_rule') ||
        pg_catalog.jsonb_build_object('rule',p.relevance_gate->'pursued_rule')
      where p.id=new.posting_id and p.relevance_gate ? 'pursued_rule';
  end if;
  return new;
end $$;
create trigger posting_status_protect_relevance_gate
  after insert or update of status on public.posting_status
  for each row execute function public.protect_pursued_relevance_gate();
revoke all on function public.protect_pursued_relevance_gate() from public,anon,authenticated;
grant execute on function public.protect_pursued_relevance_gate() to service_role;

-- Repair roles that were already hidden before this protection was installed.
update public.postings p
  set relevance_gate=p.relevance_gate || pg_catalog.jsonb_build_object(
    'pursued_rule',p.relevance_gate->'rule','rule',null)
  where p.relevance_filtered and exists (
    select 1 from public.posting_status s
    where s.posting_id=p.id and s.status not in ('new','seen'));
notify pgrst,'reload schema';
commit;
