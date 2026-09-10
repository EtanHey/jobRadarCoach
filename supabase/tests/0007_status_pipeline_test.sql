begin;

create schema if not exists extensions;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;

select plan(1);

do $status_pipeline_test$
declare
  posting constant uuid := '00000000-0000-0000-0000-000000007001';
  automatic_seen constant uuid := '00000000-0000-0000-0000-000000007002';
  states constant text[] := array[
    'new', 'seen', 'worth_checking', 'applied', 'screen',
    'interview_technical', 'interview_final', 'offer', 'contract',
    'rejected', 'archived', 'not_relevant'
  ];
  target text;
  supplied_reason text;
  previous_status text;
  changed public.posting_status;
  before_invalid bigint;
  application_before jsonb;
begin
  insert into public.postings (id, source, external_id, url, title, company)
  values (posting, 'lane2-status', 'pipeline', 'https://example.test/pipeline',
          'Pipeline Engineer', 'Status Pipeline Co');
  application_before := (
    select jsonb_agg(to_jsonb(h) order by h.id) from public.application_history h
  );

  foreach target in array states loop
    supplied_reason := case target
      when 'rejected' then '  Employer declined verbatim  '
      when 'not_relevant' then '  Owner ruled this out verbatim  '
      else null
    end;
    changed := public.set_status(posting, target, supplied_reason);
    if changed.status <> target or changed.reason is distinct from supplied_reason then
      raise exception 'status or reason did not round-trip for %', target;
    end if;
    if not exists (
      select 1 from public.posting_status_history h
      where h.posting_id = posting
        and h.status_from is not distinct from previous_status
        and h.status_to = target and h.reason is not distinct from supplied_reason
        and h.recorded_at = changed.updated_at
    ) then
      raise exception 'exact history fact missing for %', target;
    end if;
    previous_status := target;
  end loop;
  if (select count(*) from public.posting_status_history h
      where h.posting_id = posting) <> cardinality(states) then
    raise exception 'one history fact was not recorded per state change';
  end if;
  if exists (
    select 1 from public.posting_status_history h where h.posting_id = posting
      and (h.status_to is null or h.recorded_at is null
           or h.company <> 'Status Pipeline Co'
           or h.role <> 'Pipeline Engineer')
  ) then
    raise exception 'transition history lost posting identity';
  end if;
  changed := public.set_status(posting, 'seen');
  if changed.status <> 'seen' or changed.reason is not null then
    raise exception 'backward edit failed to clear a stale reason';
  end if;
  changed := public.set_status(posting, 'rejected', 'first rejection');
  changed := public.set_status(posting, 'rejected', 'corrected verbatim');
  if not exists (
    select 1 from public.posting_status_history h where h.posting_id = posting
      and h.status_from = 'rejected' and h.status_to = 'rejected'
      and h.reason = 'corrected verbatim' and h.recorded_at = changed.updated_at
  ) then
    raise exception 'reason correction was not recorded atomically';
  end if;
  before_invalid := (select count(*) from public.posting_status_history h
                     where h.posting_id = posting);
  changed := public.set_status(posting, 'rejected', 'corrected verbatim');
  if (select count(*) from public.posting_status_history h
      where h.posting_id = posting) <> before_invalid then
    raise exception 'identical repeat created duplicate history';
  end if;
  changed := public.set_status(posting, 'applied');
  if changed.reason is not null then
    raise exception 'ordinary transition retained a stale reason';
  end if;
  before_invalid := (select count(*) from public.posting_status_history h
                     where h.posting_id = posting);
  begin
    perform public.set_status(posting, 'unknown');
    raise exception 'unknown status was accepted';
  exception when sqlstate '22023' then null;
  end;
  begin
    perform public.set_status(posting, 'rejected', E'\t\n');
    raise exception 'blank rejected reason was accepted';
  exception when sqlstate '22023' then null;
  end;
  begin
    perform public.set_status(posting, 'not_relevant', E'\t\n');
    raise exception 'blank not-relevant reason was accepted';
  exception when sqlstate '22023' then null;
  end;
  begin
    perform public.set_status(posting, 'seen', 'unexpected reason');
    raise exception 'reason on an ordinary status was accepted';
  exception when sqlstate '22023' then null;
  end;
  begin
    perform public.set_status(
      '00000000-0000-0000-0000-000000007099', 'seen'
    );
    raise exception 'missing posting was accepted';
  exception when sqlstate 'P0002' then null;
  end;
  if (select status from public.posting_status where posting_id = posting) <> 'applied'
     or (select count(*) from public.posting_status_history h
         where h.posting_id = posting) <> before_invalid then
    raise exception 'invalid input changed current state or history';
  end if;
  insert into public.postings (id, source, external_id, url, title, company)
  values (automatic_seen, 'lane2-status', 'automatic-seen',
          'https://example.test/automatic-seen', 'Seen role', 'Status Pipeline Co');
  perform public.set_status(automatic_seen, 'new');
  update public.posting_status set status = 'seen', reason = null
  where posting_id = automatic_seen and status = 'new';
  update public.posting_status set status = 'seen', reason = null
  where posting_id = automatic_seen and status = 'new';
  if (select status from public.posting_status
      where posting_id = automatic_seen) <> 'seen'
     or (select count(*) from public.posting_status_history h
         where h.posting_id = automatic_seen) <> 2 then
    raise exception 'automatic seen was not monotonic and recorded exactly once';
  end if;
  if (select jsonb_agg(to_jsonb(h) order by h.id)
      from public.application_history h) is distinct from application_before then
    raise exception 'status changes altered explicit application history';
  end if;
  delete from public.postings where id = automatic_seen;
  if exists (select 1 from public.posting_status_history h
             where h.posting_id = automatic_seen) then
    raise exception 'posting deletion did not cascade status history';
  end if;
end
$status_pipeline_test$;

select ok(true, 'status pipeline assertions completed');

select * from finish();
rollback;
