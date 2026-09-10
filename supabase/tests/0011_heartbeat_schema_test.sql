begin;

create schema if not exists extensions;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;

select plan(13);

select has_table('public', 'heartbeat', 'heartbeat exists after the migration');
select columns_are('public', 'heartbeat', array['at'], 'heartbeat has the source column');
select col_type_is('public', 'heartbeat', 'at', 'timestamp with time zone', 'heartbeat timestamp matches source');
select is(
  (select pg_get_expr(d.adbin, d.adrelid)
   from pg_catalog.pg_attrdef d
   join pg_catalog.pg_class c on c.oid = d.adrelid
   join pg_catalog.pg_namespace n on n.oid = c.relnamespace
   join pg_catalog.pg_attribute a on a.attrelid = c.oid and a.attnum = d.adnum
   where n.nspname = 'public' and c.relname = 'heartbeat' and a.attname = 'at'),
  'now()',
  'heartbeat keeps the now default'
);
select ok((select relrowsecurity from pg_catalog.pg_class where oid = 'public.heartbeat'::regclass),
  'heartbeat enables row-level security');
select ok(not has_table_privilege('anon', 'public.heartbeat', 'select')
  and not has_table_privilege('authenticated', 'public.heartbeat', 'select'),
  'browser roles cannot read heartbeat');
select ok(not has_table_privilege('anon', 'public.heartbeat', 'insert,update,delete')
  and not has_table_privilege('authenticated', 'public.heartbeat', 'insert,update,delete'),
  'browser roles cannot write heartbeat');
select ok(has_table_privilege('service_role', 'public.heartbeat', 'select,insert,update,delete'),
  'service role retains heartbeat access');
select ok(not exists(
  select 1 from pg_catalog.pg_class c
  cross join lateral pg_catalog.aclexplode(coalesce(c.relacl, pg_catalog.acldefault('r', c.relowner))) a
  where c.oid = 'public.heartbeat'::regclass and a.grantee = 0
), 'PUBLIC has no direct heartbeat privilege');
select ok(not exists(
  select 1 from pg_catalog.pg_publication_tables
  where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'heartbeat'
), 'heartbeat is not added to Realtime');

insert into public.heartbeat default values;
select is((select count(*) from public.heartbeat), 1::bigint, 'fresh heartbeat accepts a defaulted fixture row');

create table if not exists public.heartbeat (at timestamptz default now());
alter table public.heartbeat enable row level security;
revoke all on table public.heartbeat from public, anon, authenticated, service_role;
grant all on table public.heartbeat to service_role;
select is((select count(*) from public.heartbeat), 1::bigint, 'reapplying the migration preserves existing heartbeat data');
select is(
  (select pg_get_expr(d.adbin, d.adrelid)
   from pg_catalog.pg_attrdef d
   join pg_catalog.pg_class c on c.oid = d.adrelid
   join pg_catalog.pg_namespace n on n.oid = c.relnamespace
   join pg_catalog.pg_attribute a on a.attrelid = c.oid and a.attnum = d.adnum
   where n.nspname = 'public' and c.relname = 'heartbeat' and a.attname = 'at'),
  'now()',
  'reapplying the migration preserves the heartbeat default'
);

select * from finish();
rollback;
