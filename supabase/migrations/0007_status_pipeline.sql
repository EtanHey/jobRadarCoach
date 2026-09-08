alter table public.posting_status
  drop constraint posting_status_value,
  drop constraint posting_status_rejected_reason;
-- Legacy "rejected" was the owner's ruled-out action, not employer rejection.
-- Install transition triggers only after this remap so migration is not history.
update public.posting_status set status = 'worth_checking' where status = 'saved';
update public.posting_status set status = 'not_relevant' where status = 'rejected';
alter table public.posting_status
  add constraint posting_status_value check (status in (
    'new', 'seen', 'worth_checking', 'applied', 'screen', 'interview_technical',
    'interview_final', 'offer', 'contract', 'rejected', 'archived', 'not_relevant'
  )),
  add constraint posting_status_rejected_reason check (
    status <> 'rejected' or (reason is not null and reason ~ '[^[:space:]]')
  );
create table public.posting_status_history (
  id uuid primary key default gen_random_uuid(),
  posting_id uuid not null references public.postings(id) on delete cascade,
  company text not null,
  role text not null,
  recorded_at timestamptz not null,
  status_from text,
  status_to text not null,
  reason text,
  constraint posting_status_history_company_nonblank check (company ~ '[^[:space:]]'),
  constraint posting_status_history_role_nonblank check (role ~ '[^[:space:]]'),
  constraint posting_status_history_status_from check (
    status_from is null or status_from in (
      'new', 'seen', 'worth_checking', 'applied', 'screen', 'interview_technical',
      'interview_final', 'offer', 'contract', 'rejected', 'archived', 'not_relevant'
    )
  ),
  constraint posting_status_history_status_to check (
    status_to in (
      'new', 'seen', 'worth_checking', 'applied', 'screen', 'interview_technical',
      'interview_final', 'offer', 'contract', 'rejected', 'archived', 'not_relevant'
    )
  ),
  constraint posting_status_history_reason_nonblank check (reason is null or reason ~ '[^[:space:]]')
);
create index posting_status_history_posting_recorded_idx on public.posting_status_history (posting_id, recorded_at desc);
alter table public.posting_status_history enable row level security;
revoke all on table public.posting_status_history from public, anon, authenticated;
grant all on table public.posting_status_history to service_role;
create function public.prepare_posting_status_change()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  if tg_op = 'UPDATE'
     and (new.status, new.reason) is not distinct from (old.status, old.reason) then
    new.updated_at := old.updated_at;
  else
    new.updated_at := pg_catalog.clock_timestamp();
  end if;
  return new;
end
$$;
create function public.record_posting_status_change()
returns trigger language plpgsql security invoker set search_path = '' as $$
declare previous_status text;
begin
  if tg_op = 'UPDATE' then
    if (new.status, new.reason) is not distinct from (old.status, old.reason) then
      return new;
    end if;
    previous_status := old.status;
  end if;
  insert into public.posting_status_history
    (posting_id, company, role, recorded_at, status_from, status_to, reason)
  select new.posting_id, p.company, p.title, new.updated_at, previous_status,
         new.status, new.reason
  from public.postings p
  where p.id = new.posting_id;
  return new;
end
$$;
create trigger posting_status_prepare_change
before insert or update on public.posting_status
for each row execute function public.prepare_posting_status_change();
create trigger posting_status_record_change
after insert or update on public.posting_status
for each row execute function public.record_posting_status_change();
revoke all on function public.prepare_posting_status_change() from public, anon, authenticated;
revoke all on function public.record_posting_status_change() from public, anon, authenticated;
create or replace function public.set_status(
  posting_id uuid, status text, reason text default null
) returns public.posting_status
language plpgsql security invoker set search_path = '' as $$
declare result public.posting_status; stored_reason text;
begin
  if $2 is null or $2 not in (
    'new', 'seen', 'worth_checking', 'applied', 'screen', 'interview_technical',
    'interview_final', 'offer', 'contract', 'rejected', 'archived', 'not_relevant'
  ) then
    raise exception using errcode = '22023', message = 'unsupported posting status';
  end if;
  if $2 = 'rejected' and ($3 is null or not ($3 ~ '[^[:space:]]')) then
    raise exception using errcode = '22023',
      message = 'rejected status requires a nonblank reason';
  end if;
  if $2 = 'not_relevant' and $3 is not null
     and not ($3 ~ '[^[:space:]]') then
    raise exception using errcode = '22023',
      message = 'not_relevant reason must be null or nonblank';
  end if;
  if $2 not in ('rejected', 'not_relevant') and $3 is not null then
    raise exception using errcode = '22023',
      message = 'reason is unsupported for this posting status';
  end if;
  stored_reason := case when $2 in ('rejected', 'not_relevant') then $3 end;
  perform 1 from public.postings p where p.id = $1 for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'posting does not exist';
  end if;
  perform 1 from public.posting_status s where s.posting_id = $1 for update;
  insert into public.posting_status as current_status (posting_id, status, reason)
  values ($1, $2, stored_reason)
  on conflict on constraint posting_status_pkey do update set
    status = excluded.status,
    reason = excluded.reason
  returning * into result;
  return result;
end
$$;
comment on table public.posting_status_history is 'Private workflow audit facts, isolated from explicit application evidence.';
