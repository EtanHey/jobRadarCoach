-- Operator-only durable target/apply identity. Never inferred from a connection string.
create table public.globe_geo_target (
  singleton boolean primary key default true check (singleton),
  target_id uuid not null unique default pg_catalog.gen_random_uuid(),
  database_oid oid not null
);
insert into public.globe_geo_target(database_oid)
  select oid from pg_catalog.pg_database where datname = current_database();
create table public.globe_geo_applies (
  apply_id uuid primary key,
  target_id uuid not null references public.globe_geo_target(target_id),
  receipt jsonb not null default '{}'::jsonb
);
alter table public.posting_geo add column geo_apply_id uuid references public.globe_geo_applies(apply_id);
alter table public.company_hq add column geo_apply_id uuid references public.globe_geo_applies(apply_id);
-- Any later update relinquishes ownership, even if values are subsequently restored.
create function public.clear_geo_apply_owner() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin new.geo_apply_id := null; return new; end
$$;
create trigger posting_geo_clear_owner before update on public.posting_geo
  for each row execute function public.clear_geo_apply_owner();
create trigger company_hq_clear_owner before update on public.company_hq
  for each row execute function public.clear_geo_apply_owner();
alter table public.globe_geo_target enable row level security;
alter table public.globe_geo_applies enable row level security;
revoke all on public.globe_geo_target, public.globe_geo_applies from public, anon, authenticated;
grant select on public.globe_geo_target to service_role;
grant select, insert, update on public.globe_geo_applies to service_role;
revoke all on function public.clear_geo_apply_owner() from public, anon, authenticated;
grant execute on function public.clear_geo_apply_owner() to service_role;
notify pgrst, 'reload schema';
