begin;

create schema if not exists extensions;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;

select plan(42);

create function pg_temp.throws_sqlstate(command text, expected_state text)
returns boolean language plpgsql as $$
begin
  execute command;
  return false;
exception when others then
  return sqlstate = expected_state;
end
$$;

select has_function('public', 'list_new_for_me', array[]::text[], 'list_new_for_me exists');
select has_function('public', 'set_status', array['uuid', 'text', 'text'], 'set_status exists');
select has_function('public', 'update_profile', array['text', 'jsonb'], 'update_profile exists');
select has_function('public', 'profile_value_is_valid', array['text', 'jsonb'], 'profile validator exists');
select is(
  (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
   where n.nspname = 'public'
     and p.proname in ('list_new_for_me', 'set_status', 'update_profile', 'profile_value_is_valid')
     and not p.prosecdef and p.proconfig = array['search_path=""']),
  4::bigint,
  'all functions are invoker-scoped with an empty search path'
);

select ok(public.profile_value_is_valid('runtime.brain', '"ollama"'), 'ollama is a valid DB brain');
select ok(exists(
  select 1 from profile where field = 'runtime.brain'
    and public.profile_value_is_valid(field, value)
), 'a valid runtime brain preference exists in the database');
select is(
  (select count(*) from (values
    ('contract_version', '1'::jsonb),
    ('candidate.positioning', '"Engineer"'), ('candidate.tenure_years', '5'),
    ('candidate.location', '"Example City"'), ('candidate.fit_terms', '[]'),
    ('candidate.roles_wanted', '[]'), ('candidate.stacks', '[]'),
    ('candidate.seniority', '[]'), ('candidate.remote', 'null'),
    ('candidate.open_to.geographies', '[]'), ('candidate.open_to.work_modes', '["remote"]'),
    ('candidate.open_to.relocation', 'false'),
    ('candidate.preferences.product_company', '"preferred"'),
    ('candidate.preferences.experience_gap', '{}'), ('candidate.salary_floor', 'null'),
    ('candidate.red_flag_words', '[]'), ('candidate.preferences.free_text', 'null'),
    ('fit_signals', '[]'), ('constraints.global_never_claims', '[]'),
    ('constraints.evidence_scoped_prohibitions', '{}'), ('search.terms', '[]'),
    ('search.recency', '"r10800"'), ('search.location_terms', '{}'),
    ('runtime.brain', '"cursor-agent"')
  ) supported(field, value) where public.profile_value_is_valid(field, value)),
  24::bigint,
  'all 24 profile fields accept a typed representative value'
);
select ok(not public.profile_value_is_valid('unknown', 'null'), 'unknown profile fields are rejected');
select ok(not public.profile_value_is_valid('search.terms', '{}'), 'profile type mismatches are rejected');
select ok(not public.profile_value_is_valid('candidate.open_to.work_modes', '["teleport"]'), 'unknown work modes are rejected');
select ok(not public.profile_value_is_valid('runtime.brain', '"other"'), 'unknown brains are rejected');
select ok(not public.profile_value_is_valid('candidate.positioning', '"\t\n"'), 'whitespace-only strings are rejected');
select ok(pg_temp.throws_sqlstate(
  $$insert into profile (field, value) values ('lane2b.invalid', 'null')$$,
  '23514'), 'direct profile writes share the typed contract');
select is((public.update_profile('candidate.positioning', '"Lane 2B"')).value, '"Lane 2B"'::jsonb, 'valid profile updates return their value');
select ok(pg_temp.throws_sqlstate(
  $$select public.update_profile('search.terms', '{}')$$,
  '22023'), 'update_profile rejects invalid values');
select is((public.update_profile('runtime.brain', '"codex"')).value, '"codex"'::jsonb, 'runtime brain can be changed');

delete from visits;
delete from postings where id between '00000000-0000-0000-0000-000000002001' and '00000000-0000-0000-0000-000000002099';
insert into postings (id, source, external_id, url, title, company, posted_at) values
  ('00000000-0000-0000-0000-000000002001', 'lane2b', 'high', 'https://example.test/high', 'High', 'Example', '2026-01-01 13:00Z'),
  ('00000000-0000-0000-0000-000000002002', 'lane2b', 'low', 'https://example.test/low', 'Low', 'Example', '2026-01-01 15:00Z'),
  ('00000000-0000-0000-0000-000000002003', 'lane2b', 'unscored', 'https://example.test/unscored', 'Unscored', 'Example', '2026-01-01 16:00Z'),
  ('00000000-0000-0000-0000-000000002004', 'lane2b', 'old', 'https://example.test/old', 'Old', 'Example', '2026-01-01 11:00Z'),
  ('00000000-0000-0000-0000-000000002005', 'lane2b', 'undated', 'https://example.test/undated', 'Undated', 'Example', null),
  ('00000000-0000-0000-0000-000000002006', 'lane2b', 'seen', 'https://example.test/seen', 'Seen', 'Example', '2026-01-01 17:00Z');
insert into posting_scores (
  posting_id, score, reasons, labels, brain, model, scorer_version,
  posting_sha256, profile_sha256, history_sha256, score_payload
) values
  ('00000000-0000-0000-0000-000000002001', 90, '[]',
   '{"role_type":null,"seniority_match":"unknown","remote_ok":"unknown","red_flag_count":0}',
   'test', 'test-model', 'test-1', repeat('a',64), repeat('b',64), repeat('c',64),
   '{"employer_type":"unknown","seniority_real":null,"fit_score":90,"fit_tier":"strong","recommendation":"review","reasons":[],"fit_line":"fixture","fit_line_evidence_ids":[],"luna_status":"ok"}'),
  ('00000000-0000-0000-0000-000000002002', 20, '[]',
   '{"role_type":null,"seniority_match":"unknown","remote_ok":"unknown","red_flag_count":0}',
   'test', 'test-model', 'test-1', repeat('d',64), repeat('e',64), repeat('f',64),
   '{"employer_type":"unknown","seniority_real":null,"fit_score":20,"fit_tier":"weak","recommendation":"review","reasons":[],"fit_line":"fixture","fit_line_evidence_ids":[],"luna_status":"ok"}');
insert into posting_status (posting_id, status) values
  ('00000000-0000-0000-0000-000000002002', 'new'),
  ('00000000-0000-0000-0000-000000002006', 'seen');

select ok(exists(
  select 1 from public.list_new_for_me() where posting_id = '00000000-0000-0000-0000-000000002004'
), 'no visits row behaves as a first visit');
insert into visits (singleton, last_visit_at) values (true, '2026-01-01 12:00Z');
select is(
  (select count(*) from public.list_new_for_me()
   where posting_id between '00000000-0000-0000-0000-000000002001' and '00000000-0000-0000-0000-000000002006'),
  3::bigint,
  'only synthetic dated new postings after the visit are listed'
);
select is(
  (select array_agg(posting_id order by ordinality)
   from public.list_new_for_me() with ordinality
   where posting_id in (
     '00000000-0000-0000-0000-000000002001',
     '00000000-0000-0000-0000-000000002002',
     '00000000-0000-0000-0000-000000002003')),
  array[
    '00000000-0000-0000-0000-000000002001',
    '00000000-0000-0000-0000-000000002002',
    '00000000-0000-0000-0000-000000002003']::uuid[],
  'scores rank descending and missing scores sort last'
);
select is((select status from public.list_new_for_me() where posting_id = '00000000-0000-0000-0000-000000002001'), 'new', 'missing status is treated as new');
select is((select score from public.list_new_for_me() where posting_id = '00000000-0000-0000-0000-000000002003'), null::smallint, 'missing score remains null');
select ok(not exists(select 1 from public.list_new_for_me() where posting_id = '00000000-0000-0000-0000-000000002005'), 'null posted_at is excluded');
select ok(not exists(select 1 from public.list_new_for_me() where posting_id = '00000000-0000-0000-0000-000000002004'), 'pre-visit postings are excluded');
select ok(not exists(select 1 from public.list_new_for_me() where posting_id = '00000000-0000-0000-0000-000000002006'), 'non-new status is excluded');

select ok(pg_temp.throws_sqlstate(
  $$select public.set_status('00000000-0000-0000-0000-000000002001', 'unknown')$$,
  '22023'), 'set_status rejects unknown states');
select ok(pg_temp.throws_sqlstate(
  $$select public.set_status('00000000-0000-0000-0000-000000002001', 'rejected', E'\t\n')$$,
  '22023'), 'set_status rejects whitespace-only rejection reasons');
select ok(pg_temp.throws_sqlstate(
  $$select public.set_status('00000000-0000-0000-0000-000000002099', 'seen')$$,
  'P0002'), 'set_status rejects missing postings');
select is((public.set_status('00000000-0000-0000-0000-000000002001', 'worth_checking')).status, 'worth_checking', 'new postings can be marked worth checking directly');
select is((public.set_status('00000000-0000-0000-0000-000000002001', 'rejected', 'not a fit')).reason, 'not a fit', 'rejections retain their reason');
select is((public.set_status('00000000-0000-0000-0000-000000002001', 'seen')).reason, null::text, 'corrections clear stale rejection reasons');
create temp table before_same_state as
select updated_at from posting_status
where posting_id = '00000000-0000-0000-0000-000000002001';
select is(
  (public.set_status('00000000-0000-0000-0000-000000002001', 'seen')).updated_at,
  (select updated_at from before_same_state),
  'same-state calls preserve updated_at'
);
select is((public.set_status('00000000-0000-0000-0000-000000002001', 'applied')).status, 'applied', 'status corrections can move to any known state');
select is((public.set_status('00000000-0000-0000-0000-000000002001', 'new')).status, 'new', 'applied can be corrected back to new');

select ok(has_function_privilege('anon', 'public.list_new_for_me()', 'execute'), 'anon can execute the read RPC');
select ok(has_function_privilege('authenticated', 'public.list_new_for_me()', 'execute'), 'authenticated can execute the read RPC');
select ok(not has_function_privilege('anon', 'public.set_status(uuid,text,text)', 'execute'), 'anon cannot execute set_status');
select ok(not has_function_privilege('authenticated', 'public.update_profile(text,jsonb)', 'execute'), 'authenticated cannot execute update_profile');
select ok(has_function_privilege('service_role', 'public.set_status(uuid,text,text)', 'execute'), 'service role can execute set_status');
select ok(has_function_privilege('service_role', 'public.update_profile(text,jsonb)', 'execute'), 'service role can execute update_profile');
select ok(not has_function_privilege('anon', 'public.profile_value_is_valid(text,jsonb)', 'execute'), 'anon cannot execute the profile validator');
select ok(has_function_privilege('service_role', 'public.profile_value_is_valid(text,jsonb)', 'execute'), 'service role can execute the profile validator');

select * from finish();
rollback;
