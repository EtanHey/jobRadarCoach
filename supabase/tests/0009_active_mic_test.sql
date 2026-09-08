begin;

create schema if not exists extensions;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;

select plan(29);

create function pg_temp.throws_sqlstate(command text, expected_state text)
returns boolean language plpgsql as $$
begin
  execute command;
  return false;
exception when others then
  return sqlstate = expected_state;
end
$$;

select has_table('public','active_mic','active_mic exists');
select columns_are('public','active_mic',array['singleton','client_id','revision','updated_at']);
select col_type_is('public','active_mic','revision','bigint','revision is bigint');
select is((select count(*) from active_mic),1::bigint,'exactly one row is seeded');
select is((select client_id from active_mic where singleton),null::uuid,'seed is inactive');
select is((select revision from active_mic where singleton),0::bigint,'seed revision is zero');
select ok((select updated_at is not null from active_mic where singleton),'seed timestamp is generated');
select is(
  (select count(*) from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
   where n.nspname='public' and p.proname in ('claim_active_mic','release_active_mic','get_active_mic')
     and p.prosecdef and p.proconfig=array['search_path=""']),
  3::bigint,'all RPCs are security-definer functions with empty search paths');
select ok(pg_temp.throws_sqlstate($$select public.claim_active_mic(null)$$,'22023'),
  'claim rejects null client');
select ok(pg_temp.throws_sqlstate($$select public.release_active_mic(null)$$,'22023'),
  'release rejects null client');
create temp table initial_mic as select * from active_mic;
select is((select revision from public.claim_active_mic('00000000-0000-0000-0000-000000009001')),
  1::bigint,'first claim increments revision');
select is((select client_id from active_mic),
  '00000000-0000-0000-0000-000000009001'::uuid,'first claim owns the mic');
select ok((select a.updated_at > i.updated_at from active_mic a cross join initial_mic i),
  'claim advances the server timestamp');
select is((select revision from public.claim_active_mic('00000000-0000-0000-0000-000000009002')),
  2::bigint,'successive claim increments revision');
select is((select client_id from active_mic),
  '00000000-0000-0000-0000-000000009002'::uuid,'successive claim replaces ownership');
create temp table before_stale_release as select * from active_mic;
select is((select revision from public.release_active_mic('00000000-0000-0000-0000-000000009001')),
  2::bigint,'stale release returns unchanged revision');
select is((select client_id from active_mic),
  '00000000-0000-0000-0000-000000009002'::uuid,'stale release cannot clear newer ownership');
select is((select to_jsonb(a) from active_mic a),
  (select to_jsonb(b) from before_stale_release b),'stale release preserves the entire row');
select is((select revision from public.release_active_mic('00000000-0000-0000-0000-000000009002')),
  3::bigint,'active owner release increments revision');
select is((select client_id from active_mic),null::uuid,'active owner release clears ownership');
select is((select revision from public.release_active_mic('00000000-0000-0000-0000-000000009001')),
  3::bigint,'release against inactive row is unchanged');
select ok(pg_temp.throws_sqlstate($$update public.active_mic set revision=-1$$,'23514'),
  'negative revision is rejected');
select ok(has_table_privilege('service_role','public.active_mic','select'),
  'service role can read active mic');
select ok(not has_table_privilege('service_role','public.active_mic','insert,update,delete'),
  'service role has no direct writes');
select ok(not has_table_privilege('anon','public.active_mic','select')
  and not has_table_privilege('authenticated','public.active_mic','select'),
  'browser roles cannot read the relation directly');
select ok(not has_table_privilege('anon','public.active_mic','insert,update,delete')
  and not has_table_privilege('authenticated','public.active_mic','insert,update,delete'),
  'browser roles cannot write the relation directly');
select ok(
  has_function_privilege('service_role','public.claim_active_mic(uuid)','execute')
  and has_function_privilege('service_role','public.release_active_mic(uuid)','execute')
  and has_function_privilege('service_role','public.get_active_mic()','execute'),
  'service role can execute all active-mic RPCs');
select ok(
  not has_function_privilege('anon','public.claim_active_mic(uuid)','execute')
  and not has_function_privilege('authenticated','public.claim_active_mic(uuid)','execute')
  and not has_function_privilege('anon','public.release_active_mic(uuid)','execute')
  and not has_function_privilege('authenticated','public.release_active_mic(uuid)','execute')
  and not has_function_privilege('anon','public.get_active_mic()','execute')
  and not has_function_privilege('authenticated','public.get_active_mic()','execute'),
  'browser roles cannot execute active-mic RPCs');
select ok(not exists(
  select 1 from pg_catalog.pg_proc p
  join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  cross join lateral pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
  where n.nspname='public' and p.proname in ('claim_active_mic','release_active_mic','get_active_mic')
    and a.grantee=0 and a.privilege_type='EXECUTE'),
  'PUBLIC cannot execute active-mic RPCs');
select ok(exists(select 1 from pg_catalog.pg_publication_tables
  where pubname='supabase_realtime' and schemaname='public' and tablename='active_mic'),
  'active_mic is in the Realtime publication');

select * from finish();
rollback;
