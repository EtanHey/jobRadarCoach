begin;
-- Why: owner dismissals must not bypass the cheap gate or enqueue model work.
-- Pursuit protects only the forward pipeline; a score earned during pursuit
-- permits returning to discovery unless the saved rule requires US residency.
-- Keep the persisted pursued_rule key for compatibility with applied 0034.
create or replace function public.protect_pursued_relevance_gate() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if new.status in ('worth_checking','applied','screen','interview_technical','interview_final','offer','contract','rejected') then
    update public.postings p
      set relevance_gate=p.relevance_gate || pg_catalog.jsonb_build_object(
        'pursued_rule',p.relevance_gate->'rule','rule',null)
      where p.id=new.posting_id and p.relevance_filtered;
  else
    update public.postings p
      set relevance_gate=(p.relevance_gate - 'pursued_rule') ||
        pg_catalog.jsonb_build_object('rule',case
          when p.relevance_gate->>'pursued_rule'='already-us-resident'
            or not exists(select 1 from public.posting_scores s where s.posting_id=p.id)
          then p.relevance_gate->'pursued_rule' else 'null'::jsonb end)
      where p.id=new.posting_id and p.relevance_gate ? 'pursued_rule';
  end if;
  return new;
end $$;

-- Repair protection missing from existing pursued rows.
update public.postings p
  set relevance_gate=p.relevance_gate || pg_catalog.jsonb_build_object(
    'pursued_rule',p.relevance_gate->'rule','rule',null)
  where p.relevance_filtered and exists (
    select 1 from public.posting_status s where s.posting_id=p.id
      and s.status in ('worth_checking','applied','screen','interview_technical','interview_final','offer','contract','rejected'));
-- Undo 0034's protection of dismissed roles, honoring scores and owner overrides.
update public.postings p
  set relevance_gate=(p.relevance_gate - 'pursued_rule') ||
    pg_catalog.jsonb_build_object('rule',case
      when p.relevance_gate->>'pursued_rule'='already-us-resident'
        or not exists(select 1 from public.posting_scores sc where sc.posting_id=p.id)
      then p.relevance_gate->'pursued_rule' else 'null'::jsonb end)
  where p.relevance_gate ? 'pursued_rule' and exists (
    select 1 from public.posting_status s where s.posting_id=p.id
      and s.status not in ('worth_checking','applied','screen','interview_technical','interview_final','offer','contract','rejected'));
notify pgrst,'reload schema';
commit;
