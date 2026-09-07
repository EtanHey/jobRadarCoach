begin;

create schema if not exists extensions;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;

select plan(43);

create function pg_temp.throws_sqlstate(command text, expected_state text)
returns boolean
language plpgsql
as $$
begin
  execute command;
  return false;
exception when others then
  return sqlstate = expected_state;
end;
$$;

select has_table('public', 'postings', 'postings exists');
select has_table('public', 'posting_scores', 'posting_scores exists');
select has_table('public', 'posting_status', 'posting_status exists');
select has_table('public', 'profile', 'profile exists');
select has_table('public', 'visits', 'visits exists');

select is(
  (select count(*) from information_schema.columns
   where table_schema = 'public' and table_name = 'postings'
     and column_name in ('location', 'remote', 'seniority', 'salary', 'apply_url', 'posted_at', 'raw_jd')
     and is_nullable = 'YES'),
  7::bigint,
  'all extracted posting fields are nullable'
);

insert into postings (id, source, external_id, url, title, company)
values ('00000000-0000-0000-0000-000000000001', 'test', 'one', 'https://example.test/one', 'One', 'Example');

select is(
  (select count(*) from posting_scores
   where posting_id = '00000000-0000-0000-0000-000000000001'),
  0::bigint,
  'the inserted posting remains unscored'
);
select ok(pg_temp.throws_sqlstate(
  $$insert into postings (source, external_id, url, title, company)
    values ('test', 'one', 'https://example.test/duplicate', 'Duplicate', 'Example')$$,
  '23505'), 'posting identity is unique by source and external_id');
select ok(pg_temp.throws_sqlstate(
  $$insert into postings (source, external_id, url, title, company)
    values (E'\t\n', 'bad-source', 'https://example.test/source', 'Source', 'Example')$$,
  '23514'), 'posting source rejects tab/newline-only text');
select ok(pg_temp.throws_sqlstate(
  $$insert into postings (source, external_id, url, title, company)
    values ('test', E'\t\n', 'https://example.test/id', 'ID', 'Example')$$,
  '23514'), 'posting external_id rejects tab/newline-only text');
select ok(pg_temp.throws_sqlstate(
  $$insert into postings (source, external_id, url, title, company)
    values ('test', 'bad-url', E'\t\n', 'URL', 'Example')$$,
  '23514'), 'posting URL rejects tab/newline-only text');
select ok(pg_temp.throws_sqlstate(
  $$insert into postings (source, external_id, url, title, company)
    values ('test', 'bad-title', 'https://example.test/title', E'\t\n', 'Example')$$,
  '23514'), 'posting title rejects tab/newline-only text');
select ok(pg_temp.throws_sqlstate(
  $$insert into postings (source, external_id, url, title, company)
    values ('test', 'bad-company', 'https://example.test/company', 'Company', E'\t\n')$$,
  '23514'), 'posting company rejects tab/newline-only text');
select ok(pg_temp.throws_sqlstate(
  $$insert into postings (source, external_id, url, title, company, first_seen_at, last_seen_at)
    values ('test', 'bad-time', 'https://example.test/time', 'Time', 'Example', now(), now() - interval '1 second')$$,
  '23514'), 'last_seen_at cannot precede first_seen_at');

select lives_ok(
  $$insert into posting_scores (
      posting_id, score, reasons, labels, brain, model, scorer_version,
      posting_sha256, profile_sha256, history_sha256, score_payload
    ) values (
      '00000000-0000-0000-0000-000000000001', 0, '[]',
      '{"role_type":null,"seniority_match":"unknown","remote_ok":"unknown","red_flag_count":0}',
      'test', 'test-model', 'test-1', repeat('a',64), repeat('b',64), repeat('c',64),
      '{"employer_type":"unknown","seniority_real":null,"fit_score":0,"fit_tier":"weak","recommendation":"review","reasons":[],"fit_line":"fixture","fit_line_evidence_ids":[],"luna_status":"ok"}'
    )$$,
  'score lower boundary is accepted');
select ok(pg_temp.throws_sqlstate(
  $$update posting_scores set brain = E'\t\n'
    where posting_id = '00000000-0000-0000-0000-000000000001'$$,
  '23514'), 'score brain rejects tab/newline-only text');
update posting_scores set score = 100,
  score_payload = jsonb_set(score_payload, '{fit_score}', '100')
  where posting_id = '00000000-0000-0000-0000-000000000001';
select is((select score from posting_scores where posting_id = '00000000-0000-0000-0000-000000000001'), 100::smallint, 'score upper boundary is accepted');
select ok(pg_temp.throws_sqlstate(
  $$update posting_scores set score = -1 where posting_id = '00000000-0000-0000-0000-000000000001'$$,
  '23514'), 'negative scores are rejected');
select ok(pg_temp.throws_sqlstate(
  $$update posting_scores set score = 101 where posting_id = '00000000-0000-0000-0000-000000000001'$$,
  '23514'), 'scores above 100 are rejected');

select ok(pg_temp.throws_sqlstate(
  $$insert into posting_status (posting_id, status)
    values ('00000000-0000-0000-0000-000000000001', 'rejected')$$,
  '23514'), 'rejected status requires a reason');
select ok(pg_temp.throws_sqlstate(
  $$insert into posting_status (posting_id, status, reason)
    values ('00000000-0000-0000-0000-000000000001', 'rejected', '   ')$$,
  '23514'), 'rejected status requires a nonblank reason');
select ok(pg_temp.throws_sqlstate(
  $$insert into posting_status (posting_id, status, reason)
    values ('00000000-0000-0000-0000-000000000001', 'rejected', E'\t\n')$$,
  '23514'), 'rejected reason rejects tab/newline-only text');
select lives_ok(
  $$insert into posting_status (posting_id, status, reason)
    values ('00000000-0000-0000-0000-000000000001', 'rejected', 'not a fit')$$,
  'rejected status accepts a reason');

select ok(pg_temp.throws_sqlstate(
  $$insert into profile (field, value) values (E'\t\n', 'null')$$,
  '23514'), 'profile field rejects tab/newline-only text');

select is(
  (select count(*) from pg_publication_tables
   where pubname = 'supabase_realtime' and schemaname = 'public'
     and tablename in ('postings', 'posting_scores', 'posting_status', 'profile', 'visits')),
  5::bigint,
  'all five tables are in the Realtime publication'
);
select is(
  (select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
   where n.nspname = 'public'
     and c.relname in ('postings', 'posting_scores', 'posting_status', 'profile', 'visits')
     and not c.relrowsecurity),
  5::bigint,
  'RLS is deliberately disabled on all five tables'
);

select ok(has_table_privilege('anon', 'public.postings', 'select'), 'anon can select postings');
select ok(has_table_privilege('anon', 'public.posting_scores', 'select'), 'anon can select scores');
select ok(has_table_privilege('anon', 'public.posting_status', 'select'), 'anon can select statuses');
select ok(has_table_privilege('anon', 'public.profile', 'select'), 'anon can select profile');
select ok(has_table_privilege('anon', 'public.visits', 'select'), 'anon can select visits');
select ok(not has_table_privilege('anon', 'public.postings', 'insert'), 'anon cannot insert postings');
select ok(not has_table_privilege('anon', 'public.posting_scores', 'update'), 'anon cannot update scores');
select ok(not has_table_privilege('anon', 'public.posting_status', 'delete'), 'anon cannot delete statuses');
select ok(not has_table_privilege('authenticated', 'public.profile', 'update'), 'authenticated cannot update profile');
select ok(not has_table_privilege('authenticated', 'public.visits', 'insert'), 'authenticated cannot insert visits');
select ok(
  has_schema_privilege('anon', 'public', 'usage')
    and has_schema_privilege('authenticated', 'public', 'usage')
    and has_schema_privilege('service_role', 'public', 'usage'),
  'API roles can resolve public tables'
);

select ok(has_table_privilege('service_role', 'public.postings', 'insert'), 'service role can insert postings');
select ok(has_table_privilege('service_role', 'public.posting_scores', 'update'), 'service role can update scores');
select ok(has_table_privilege('service_role', 'public.posting_status', 'delete'), 'service role can delete statuses');
select ok(has_table_privilege('service_role', 'public.profile', 'insert'), 'service role can insert profile');
select ok(has_table_privilege('service_role', 'public.visits', 'update'), 'service role can update visits');

select is(
  (select count(*) from pg_indexes
   where schemaname = 'public'
     and indexname in ('postings_posted_at_idx', 'postings_last_seen_at_idx', 'posting_status_status_idx', 'posting_scores_score_idx')),
  4::bigint,
  'all four query indexes exist'
);

select * from finish();
rollback;
