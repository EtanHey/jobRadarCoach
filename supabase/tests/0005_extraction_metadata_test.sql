begin;

create schema if not exists extensions;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;
select plan(25);

create function pg_temp.throws_sqlstate(command text, expected_state text)
returns boolean language plpgsql as $$
begin
  execute command;
  return false;
exception when others then
  return sqlstate = expected_state;
end
$$;

select has_table('public', 'posting_extractions', 'extraction metadata exists');
select is(
  (select array_agg(attname::text order by attnum) from pg_attribute
   where attrelid = 'public.posting_extractions'::regclass and attnum > 0 and not attisdropped),
  array['posting_id', 'brain', 'model', 'extractor_version', 'schema_sha256',
        'jd_sha256', 'fingerprint', 'facts', 'extracted_at'],
  'metadata has only posting identity, observed processor identity, facts, and receipt time'
);
select col_is_pk('public', 'posting_extractions', 'posting_id', 'one last-good extraction exists per posting');
select col_not_null('public', 'posting_extractions', 'facts', 'complete facts are required');
select col_not_null('public', 'posting_extractions', 'extracted_at', 'success receipt time is required');

insert into postings (id, source, external_id, url, title, company, raw_jd) values (
  '00000000-0000-0000-0000-000000005001', 'lane3d', 'metadata',
  'https://example.test/metadata', 'Synthetic role', 'Synthetic company', 'Public JD'
);
insert into posting_extractions (
  posting_id, brain, model, extractor_version, schema_sha256, jd_sha256,
  fingerprint, facts
) values (
  '00000000-0000-0000-0000-000000005001', 'ollama', 'model', '1.1',
  repeat('a', 64), repeat('b', 64), repeat('c', 64),
  '{"location":{"value":null,"evidence_quote":null},"remote":{"value":null,"evidence_quote":null},"seniority":{"value":null,"evidence_quote":null},"stack":[],"salary":{"value":null,"evidence_quote":null}}'
);
select is(
  (select facts->'location'->'value' from posting_extractions
   where posting_id = '00000000-0000-0000-0000-000000005001'),
  'null'::jsonb,
  'truthful unknown facts remain JSON null'
);
select ok(
  (select extracted_at is not null from posting_extractions
   where posting_id = '00000000-0000-0000-0000-000000005001'),
  'database records successful extraction time'
);

select ok(pg_temp.throws_sqlstate(
  $$update posting_extractions set brain = E'\t\n'$$, '23514'),
  'brain rejects whitespace-only text');
select ok(pg_temp.throws_sqlstate(
  $$update posting_extractions set model = E'\t\n'$$, '23514'),
  'model rejects whitespace-only text');
select ok(pg_temp.throws_sqlstate(
  $$update posting_extractions set extractor_version = E'\t\n'$$, '23514'),
  'extractor version rejects whitespace-only text');
select ok(pg_temp.throws_sqlstate(
  $$update posting_extractions set schema_sha256 = 'bad'$$, '23514'),
  'schema hash must be lowercase SHA-256');
select ok(pg_temp.throws_sqlstate(
  $$update posting_extractions set jd_sha256 = repeat('A', 64)$$, '23514'),
  'JD hash rejects uppercase hex');
select ok(pg_temp.throws_sqlstate(
  $$update posting_extractions set fingerprint = repeat('0', 63)$$, '23514'),
  'fingerprint must be exactly 64 lowercase hex characters');
select ok(pg_temp.throws_sqlstate(
  $$update posting_extractions set facts = '[]'$$, '23514'),
  'facts must be an object');
select ok(pg_temp.throws_sqlstate(
  $$update posting_extractions set facts = '{"location":{}}'$$, '23514'),
  'facts must contain every extraction field');
select ok(pg_temp.throws_sqlstate(
  $$update posting_extractions set facts = '{"location":{},"remote":{},"seniority":{},"stack":{},"salary":{}}'$$,
  '23514'), 'each extraction field retains its container type');

select ok(pg_temp.throws_sqlstate(
  $$update posting_extractions set facts = '{"location":{},"remote":{},"seniority":{},"stack":[],"salary":{}}'$$,
  '23514'), 'scalar facts require value and evidence_quote keys');

select ok(has_table_privilege('anon', 'public.posting_extractions', 'select'), 'anon can read extraction metadata');
select ok(not has_table_privilege('anon', 'public.posting_extractions', 'insert'), 'anon cannot insert extraction metadata');
select ok(has_table_privilege('authenticated', 'public.posting_extractions', 'select'), 'authenticated can read extraction metadata');
select ok(not has_table_privilege('authenticated', 'public.posting_extractions', 'update'), 'authenticated cannot update extraction metadata');
select ok(has_table_privilege('service_role', 'public.posting_extractions', 'insert'), 'service role can insert extraction metadata');
select is(
  (select relrowsecurity from pg_class where oid = 'public.posting_extractions'::regclass),
  false,
  'RLS follows the no-login tables'
);
select ok(exists(
  select 1 from pg_publication_tables
  where pubname = 'supabase_realtime' and schemaname = 'public'
    and tablename = 'posting_extractions'
), 'extraction metadata is in the Realtime publication');

delete from postings where id = '00000000-0000-0000-0000-000000005001';
select is(
  (select count(*) from posting_extractions
   where posting_id = '00000000-0000-0000-0000-000000005001'),
  0::bigint,
  'posting deletion cascades to extraction metadata'
);

select * from finish();
rollback;
