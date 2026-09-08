create table public.active_mic (
  singleton boolean primary key default true,
  client_id uuid,
  revision bigint not null default 0,
  updated_at timestamptz not null default pg_catalog.clock_timestamp(),
  constraint active_mic_singleton check (singleton),
  constraint active_mic_revision_nonnegative check (revision >= 0)
);

insert into public.active_mic (singleton, client_id, revision)
values (true, null, 0);

create function public.claim_active_mic(client_id uuid)
returns setof public.active_mic
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  if $1 is null then
    raise exception using errcode = '22023', message = 'client_id must not be null';
  end if;
  return query
  update public.active_mic as mic
  set client_id = $1,
      revision = mic.revision + 1,
      updated_at = pg_catalog.clock_timestamp()
  where mic.singleton
  returning mic.*;
end
$$;

create function public.release_active_mic(client_id uuid)
returns setof public.active_mic
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  current_client uuid;
begin
  if $1 is null then
    raise exception using errcode = '22023', message = 'client_id must not be null';
  end if;
  select mic.client_id into current_client
  from public.active_mic as mic
  where mic.singleton
  for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'active_mic singleton is missing';
  end if;
  if current_client = $1 then
    return query
    update public.active_mic as mic
    set client_id = null,
        revision = mic.revision + 1,
        updated_at = pg_catalog.clock_timestamp()
    where mic.singleton
    returning mic.*;
  else
    return query select mic.* from public.active_mic as mic where mic.singleton;
  end if;
end
$$;

create function public.get_active_mic()
returns setof public.active_mic
language sql
stable
security definer
set search_path = ''
as $$
  select mic.* from public.active_mic as mic where mic.singleton
$$;

revoke all on table public.active_mic from public, anon, authenticated, service_role;
grant select on table public.active_mic to service_role;

revoke all on function public.claim_active_mic(uuid) from public, anon, authenticated, service_role;
revoke all on function public.release_active_mic(uuid) from public, anon, authenticated, service_role;
revoke all on function public.get_active_mic() from public, anon, authenticated, service_role;
grant execute on function public.claim_active_mic(uuid) to service_role;
grant execute on function public.release_active_mic(uuid) to service_role;
grant execute on function public.get_active_mic() to service_role;

do $realtime$
begin
  if not exists (
    select 1 from pg_catalog.pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'active_mic'
  ) then
    alter publication supabase_realtime add table public.active_mic;
  end if;
end
$realtime$;

comment on table public.active_mic is
  'Singleton ownership lease for cross-client microphone arbitration.';
notify pgrst, 'reload schema';
