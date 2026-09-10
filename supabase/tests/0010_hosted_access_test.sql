begin;
create schema if not exists extensions;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;
select plan(15);

select is((select array_agg(c.relname::text order by c.relname) from pg_catalog.pg_class c
  join pg_catalog.pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind='r'
  and c.relrowsecurity and c.relname=any(array['active_mic','application_history','posting_extractions','posting_scores','posting_status','posting_status_history','postings','profile','visits'])),
  array['active_mic','application_history','posting_extractions','posting_scores','posting_status','posting_status_history','postings','profile','visits']::text[], 'every tracked application table has RLS enabled');
select is((select count(*) from pg_catalog.pg_policy p join pg_catalog.pg_class c on c.oid=p.polrelid
  join pg_catalog.pg_namespace n on n.oid=c.relnamespace where n.nspname='public'),0::bigint,'no browser policy opens application rows');
select ok(not has_schema_privilege('anon','public','usage') and not has_schema_privilege('authenticated','public','usage')
  and has_schema_privilege('service_role','public','usage') and has_schema_privilege('supabase_realtime_admin','public','usage')
  and not has_schema_privilege('service_role','public','create') and not has_schema_privilege('supabase_realtime_admin','public','create'),'only server and Realtime roles can resolve public');
select ok(not exists(select 1 from pg_catalog.pg_namespace n cross join lateral
  pg_catalog.aclexplode(coalesce(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) a where n.nspname='public' and a.grantee=0),
  'PUBLIC has no public-schema privilege');
select ok(not exists(select 1 from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid=c.relnamespace
  where n.nspname='public' and c.relkind in ('r','p') and (has_table_privilege('anon',c.oid,'select,insert,update,delete,truncate,references,trigger')
    or has_table_privilege('authenticated',c.oid,'select,insert,update,delete,truncate,references,trigger')
    or exists(select 1 from pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a where a.grantee=0))),
  'browser roles and PUBLIC have no application-table privilege');
select ok((select bool_and(has_table_privilege('service_role',c.oid,'select,insert,update,delete,truncate,references,trigger'))
  from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid=c.relnamespace where n.nspname='public'
  and c.relkind in ('r','p') and c.relname=any(array['application_history','posting_extractions','posting_scores','posting_status','posting_status_history','postings','profile','visits'])),
  'service_role retains full access to ordinary application tables');
select ok(has_table_privilege('service_role','public.active_mic','select')
  and not has_table_privilege('service_role','public.active_mic','insert,update,delete'),'active_mic preserves RPC-only service writes');
select ok(not exists(select 1 from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  where n.nspname='public' and p.oid=any(array['public.profile_value_is_valid(text,jsonb)'::regprocedure,'public.list_new_for_me()'::regprocedure,'public.set_status(uuid,text,text)'::regprocedure,
    'public.update_profile(text,jsonb)'::regprocedure,'public.record_application_history(text,text,date,text,uuid)'::regprocedure,'public.list_application_history(text)'::regprocedure,'public.prepare_posting_status_change()'::regprocedure,
    'public.record_posting_status_change()'::regprocedure,'public.list_jobs(boolean,integer,integer,text,text,text)'::regprocedure,'public.claim_active_mic(uuid)'::regprocedure,'public.release_active_mic(uuid)'::regprocedure,'public.get_active_mic()'::regprocedure])
    and (has_function_privilege('anon',p.oid,'execute') or has_function_privilege('authenticated',p.oid,'execute')
      or exists(select 1 from pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a where a.privilege_type='EXECUTE' and a.grantee=0))),
  'browser roles and PUBLIC cannot execute any public routine');
select ok((select bool_and(has_function_privilege('service_role',routine,'execute')) from (values
  ('public.profile_value_is_valid(text,jsonb)'::regprocedure),('public.list_new_for_me()'::regprocedure),('public.set_status(uuid,text,text)'::regprocedure),
  ('public.update_profile(text,jsonb)'::regprocedure),('public.record_application_history(text,text,date,text,uuid)'::regprocedure),('public.list_application_history(text)'::regprocedure),
  ('public.list_jobs(boolean,integer,integer,text,text,text)'::regprocedure),('public.claim_active_mic(uuid)'::regprocedure),('public.release_active_mic(uuid)'::regprocedure),('public.get_active_mic()'::regprocedure)) required(routine)),
  'service_role retains every explicitly required routine');
select ok((select convalidated from pg_catalog.pg_constraint where conrelid='public.posting_scores'::regclass
  and conname='posting_scores_complete_metadata'),'the complete scoring metadata predicate is validated');
select is((select count(*) from pg_catalog.pg_publication_tables where pubname='supabase_realtime' and schemaname='public'
  and tablename=any(array['active_mic','application_history','posting_extractions','posting_scores','posting_status','postings','profile','visits'])),
  8::bigint,'all server-side Realtime tables remain published');
select ok(to_regclass('public.heartbeat') is null or (select c.relrowsecurity and not has_table_privilege('anon',c.oid,'select')
  and not has_table_privilege('authenticated',c.oid,'select') from pg_catalog.pg_class c where c.oid=to_regclass('public.heartbeat')),
  'heartbeat is absent or hardened');

create table public.hosted_access_future_table(id bigint generated always as identity primary key);
create function public.hosted_access_future_function() returns bigint language sql set search_path='' as 'select 1::bigint';
select ok(not has_table_privilege('anon','public.hosted_access_future_table','select') and not has_table_privilege('authenticated','public.hosted_access_future_table','insert')
  and not has_table_privilege('service_role','public.hosted_access_future_table','select'),'future tables require explicit grants');
select ok(not has_sequence_privilege('anon','public.hosted_access_future_table_id_seq','usage') and not has_sequence_privilege('authenticated','public.hosted_access_future_table_id_seq','select')
  and not has_sequence_privilege('service_role','public.hosted_access_future_table_id_seq','usage'),'future sequences require explicit grants');
select ok(not has_function_privilege('anon','public.hosted_access_future_function()','execute') and not has_function_privilege('authenticated','public.hosted_access_future_function()','execute')
  and not has_function_privilege('service_role','public.hosted_access_future_function()','execute') and not exists(select 1 from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
    cross join lateral pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a where n.nspname='public' and p.proname='hosted_access_future_function' and a.grantee=0),
  'future functions override inherited grants and PostgreSQL PUBLIC EXECUTE');
select * from finish();
rollback;
