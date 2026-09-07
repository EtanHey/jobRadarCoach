begin;

create schema if not exists extensions;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;

select plan(41);

create function pg_temp.throws_sqlstate(command text, expected_state text)
returns boolean language plpgsql as $$
begin
  execute command;
  return false;
exception when others then
  return sqlstate = expected_state;
end
$$;

select has_table('public', 'application_history', 'application_history exists');
select is(
  (select array_agg(attname::text order by attnum) from pg_attribute
   where attrelid = 'public.application_history'::regclass and attnum > 0 and not attisdropped),
  array['id', 'posting_id', 'company', 'role', 'application_date', 'outcome', 'recorded_at'],
  'history exposes only durable identity, optional posting link, evidence, and receipt time'
);
select col_type_is('public', 'application_history', 'application_date', 'date', 'application date is an exact date');
select col_not_null('public', 'application_history', 'company', 'known company is required');
select col_is_null('public', 'application_history', 'role', 'unknown role remains null');
select col_is_null('public', 'application_history', 'application_date', 'unknown application date remains null');
select col_is_null('public', 'application_history', 'outcome', 'unknown outcome remains null');
select has_function('public', 'record_application_history', array['text', 'text', 'date', 'text', 'uuid'], 'record helper exists');
select has_function('public', 'list_application_history', array['text'], 'read helper exists');
select is(
  (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
   where n.nspname = 'public'
     and p.proname in ('record_application_history', 'list_application_history')
     and not p.prosecdef and p.proconfig = array['search_path=""']),
  2::bigint,
  'history helpers are invoker-scoped with an empty search path'
);
select is(
  (select count(*) from pg_constraint
   where conrelid = 'public.application_history'::regclass and contype = 'u'),
  0::bigint,
  'history has no uniqueness rule that collapses repeat applications'
);

select ok(pg_temp.throws_sqlstate(
  $$insert into application_history (company) values (E'\t\n')$$,
  '23514'), 'direct writes reject whitespace-only company names');
select ok(pg_temp.throws_sqlstate(
  $$select record_application_history(E'\t\n', null, null, null)$$,
  '22023'), 'record helper requires a known company');
select ok(pg_temp.throws_sqlstate(
  $$select record_application_history('Lane2H Co', E'\t\n', null, null)$$,
  '22023'), 'record helper rejects blank roles');
select ok(pg_temp.throws_sqlstate(
  $$select record_application_history('Lane2H Co', null, null, E'\t\n')$$,
  '22023'), 'record helper rejects blank outcomes');
select ok(pg_temp.throws_sqlstate(
  $$select * from list_application_history(E'\t\n')$$,
  '22023'), 'read helper rejects a blank company filter');

delete from postings
where id = '00000000-0000-0000-0000-000000004001';
delete from application_history where company like 'Lane2H %';
insert into postings (id, source, external_id, url, title, company) values (
  '00000000-0000-0000-0000-000000004001', 'lane2h', 'history',
  'https://example.test/history', 'Synthetic role', 'Lane2H Linked Co'
);

create temporary table recorded_application as
select * from record_application_history(
  'Lane2H Linked Co', 'Engineer', '2025-03-04', 'interviewed',
  '00000000-0000-0000-0000-000000004001'
);
select is((select company from recorded_application), 'Lane2H Linked Co', 'record helper returns exact company');
select is((select role from recorded_application), 'Engineer', 'record helper returns exact role');
select is((select application_date from recorded_application), '2025-03-04'::date, 'record helper returns caller date');
select is((select outcome from recorded_application), 'interviewed', 'record helper returns exact outcome');
select is((select posting_id from recorded_application), '00000000-0000-0000-0000-000000004001'::uuid, 'optional posting link is retained');
select ok(not exists(
  select 1 from posting_status where posting_id = '00000000-0000-0000-0000-000000004001'
), 'recording history does not manufacture posting status');

select record_application_history('Lane2H Repeat Co', 'Engineer', '2024-01-02', 'declined');
select record_application_history('Lane2H Repeat Co', 'Engineer', '2025-06-07', 'applied');
select record_application_history('Lane2H Repeat Co', 'Engineer', '2025-06-07', 'applied');
create temporary table repeat_history as
select * from list_application_history('  lane2h repeat co  ');
select is((select count(*) from repeat_history), 3::bigint, 'repeat applications are preserved as distinct events');
select is(
  (select array_agg(application_date order by ordinality)
   from list_application_history('Lane2H Repeat Co') with ordinality),
  array['2025-06-07'::date, '2025-06-07'::date, '2024-01-02'::date],
  'read helper returns exact dates without a cooldown decision'
);
select is((select count(distinct history_id) from repeat_history), 3::bigint, 'each repeated event has durable identity');

create temporary table unknown_history as
select * from record_application_history('Lane2H Unknown Co', null, null, null);
select is((select role from unknown_history), null::text, 'unknown role remains visibly null');
select is((select application_date from unknown_history), null::date, 'unknown date is not replaced with today');
select is((select outcome from unknown_history), null::text, 'unknown outcome remains visibly null');

delete from postings where id = '00000000-0000-0000-0000-000000004001';
select ok(exists(
  select 1 from application_history
  where company = 'Lane2H Linked Co' and posting_id is null
), 'posting deletion preserves history and clears only the optional link');

select ok(has_table_privilege('anon', 'public.application_history', 'select'), 'anon can read history');
select ok(not has_table_privilege('anon', 'public.application_history', 'insert'), 'anon cannot insert history');
select ok(has_table_privilege('authenticated', 'public.application_history', 'select'), 'authenticated can read history');
select ok(not has_table_privilege('authenticated', 'public.application_history', 'insert'), 'authenticated cannot insert history');
select ok(has_table_privilege('service_role', 'public.application_history', 'insert'), 'service role can insert history');
select ok(not has_function_privilege('anon', 'public.record_application_history(text,text,date,text,uuid)', 'execute'), 'anon cannot record history');
select ok(not has_function_privilege('authenticated', 'public.record_application_history(text,text,date,text,uuid)', 'execute'), 'authenticated cannot record history');
select ok(has_function_privilege('service_role', 'public.record_application_history(text,text,date,text,uuid)', 'execute'), 'service role can record history');
select ok(has_function_privilege('anon', 'public.list_application_history(text)', 'execute'), 'anon can use the read helper');
select ok(has_function_privilege('authenticated', 'public.list_application_history(text)', 'execute'), 'authenticated can use the read helper');
select is((select relrowsecurity from pg_class where oid = 'public.application_history'::regclass), false, 'RLS follows the no-login tables');
select ok(exists(
  select 1 from pg_publication_tables
  where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'application_history'
), 'history is in the Realtime publication');

select * from finish();
rollback;
