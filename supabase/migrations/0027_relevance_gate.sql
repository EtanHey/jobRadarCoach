begin;
alter table public.postings add column relevance_gate jsonb not null default '{}'::jsonb
  check (jsonb_typeof(relevance_gate)='object'
    and (not relevance_gate ? 'version' or jsonb_typeof(relevance_gate->'version')='string')
    and (not relevance_gate ? 'rule' or jsonb_typeof(relevance_gate->'rule') in ('string','null'))
    and (not relevance_gate ? 'override' or jsonb_typeof(relevance_gate->'override')='boolean'));
alter table public.postings add column relevance_filtered boolean generated always as
  (relevance_gate->>'rule' is not null and not coalesce((relevance_gate->>'override')::boolean,false)) stored;
create function public.reset_relevance_gate() returns trigger
language plpgsql set search_path='' as $$
begin
  if new.raw_jd is distinct from old.raw_jd or new.title is distinct from old.title then
    new.relevance_gate := '{}'::jsonb;
  end if;
  return new;
end $$;
create trigger reset_relevance_gate before update of raw_jd,title on public.postings
  for each row execute function public.reset_relevance_gate();
notify pgrst, 'reload schema';
commit;
