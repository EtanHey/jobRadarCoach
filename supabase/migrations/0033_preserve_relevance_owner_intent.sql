begin;
-- Text changes invalidate computed decisions, never the owner's score request.
create or replace function public.reset_relevance_gate() returns trigger
language plpgsql set search_path='' as $$
begin
  if new.raw_jd is distinct from old.raw_jd or new.title is distinct from old.title then
    select coalesce(jsonb_object_agg(key,value),'{}'::jsonb)
      into new.relevance_gate
      from jsonb_each(old.relevance_gate)
      where key in ('override','score_requested');
  end if;
  return new;
end $$;
notify pgrst, 'reload schema';
commit;
