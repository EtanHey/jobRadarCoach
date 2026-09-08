begin;

create schema if not exists extensions;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;

select plan(24);

create function pg_temp.throws_sqlstate(command text, expected_state text)
returns boolean language plpgsql as $$
begin
  execute command;
  return false;
exception when others then
  return sqlstate = expected_state;
end
$$;

select has_function('public', 'list_jobs',
  array['boolean','integer','integer','text','text','text'], 'list_jobs exists');
select ok(
  (select not p.prosecdef and p.provolatile = 's'
     and p.proconfig = array['search_path=""'] and p.pronargdefaults = 6
   from pg_catalog.pg_proc p
   join pg_catalog.pg_namespace n on n.oid = p.pronamespace
   where n.nspname = 'public' and p.proname = 'list_jobs'),
  'list_jobs is stable, invoker-scoped, empty-search-path, with six defaults');

delete from visits;
insert into visits (singleton, last_visit_at) values (true, '2026-01-01 12:00Z');
insert into postings (
  id, source, external_id, url, title, company, location, seniority, stack, posted_at
) values
  ('00000000-0000-0000-0000-000000008001','list-jobs','platform','https://example.test/platform','Senior Platform Engineer','Acme Systems','Tel Aviv, Israel','Senior',array['Go','Kubernetes'],'2026-01-01 19:00Z'),
  ('00000000-0000-0000-0000-000000008002','list-jobs','backend','https://example.test/backend','Backend Developer','RemoteCo','Remote - Israel','Mid',array['Python','Django'],'2026-01-01 18:00Z'),
  ('00000000-0000-0000-0000-000000008003','list-jobs','ml','https://example.test/ml','ML Engineer','AI Labs','Haifa','Senior',array['Python','PyTorch'],'2026-01-01 17:00Z'),
  ('00000000-0000-0000-0000-000000008004','list-jobs','percent','https://example.test/percent','Infrastructure Engineer','Percent Works','100% Remote','Staff',array['Rust'],'2026-01-01 16:00Z'),
  ('00000000-0000-0000-0000-000000008005','list-jobs','low','https://example.test/low','Junior Engineer','Low Co','Jerusalem','Junior',array['Ruby'],'2026-01-01 15:00Z'),
  ('00000000-0000-0000-0000-000000008006','list-jobs','unscored','https://example.test/unscored','Unscored Engineer','No Score Ltd','Tel Aviv','Mid',array['Elixir'],'2026-01-01 14:00Z'),
  ('00000000-0000-0000-0000-000000008007','list-jobs','seen','https://example.test/seen','Seen Engineer','Seen Co','Tel Aviv','Senior',array['Go'],'2026-01-01 20:00Z'),
  ('00000000-0000-0000-0000-000000008008','list-jobs','saved','https://example.test/saved','Saved Engineer','Saved Co','Tel Aviv','Senior',array['Go'],'2026-01-01 13:00Z'),
  ('00000000-0000-0000-0000-000000008009','list-jobs','old','https://example.test/old','Old Engineer','Old Co','Tel Aviv','Senior',array['Go'],'2026-01-01 11:00Z'),
  ('00000000-0000-0000-0000-000000008010','list-jobs','old-tie','https://example.test/old-tie','Old Tie Engineer','Old Tie Co','Tel Aviv','Senior',array['Go'],'2026-01-01 11:00Z');
update postings set posted_at = null, first_seen_at = '2026-01-01 14:00Z'
where id = '00000000-0000-0000-0000-000000008006';

insert into posting_scores (
  posting_id, score, reasons, labels, brain, model, scorer_version,
  posting_sha256, profile_sha256, history_sha256, score_payload
)
select id, score, jsonb_build_array('score ' || score),
  '{"role_type":null,"seniority_match":"unknown","remote_ok":"unknown","red_flag_count":0}',
  'test','test-model','test-1',repeat('a',64),repeat('b',64),repeat('c',64),
  jsonb_build_object(
    'employer_type','unknown','seniority_real',null,'fit_score',score,
    'fit_tier',case when score >= 80 then 'strong' when score >= 60 then 'stretch' else 'weak' end,
    'recommendation','review','reasons',jsonb_build_array('score ' || score),
    'fit_line','fixture','fit_line_evidence_ids','[]'::jsonb,'luna_status','ok')
from (values
  ('00000000-0000-0000-0000-000000008001'::uuid,95::smallint),
  ('00000000-0000-0000-0000-000000008002'::uuid,80::smallint),
  ('00000000-0000-0000-0000-000000008003'::uuid,65::smallint),
  ('00000000-0000-0000-0000-000000008004'::uuid,75::smallint),
  ('00000000-0000-0000-0000-000000008005'::uuid,10::smallint),
  ('00000000-0000-0000-0000-000000008007'::uuid,100::smallint),
  ('00000000-0000-0000-0000-000000008008'::uuid,90::smallint),
  ('00000000-0000-0000-0000-000000008009'::uuid,90::smallint),
  ('00000000-0000-0000-0000-000000008010'::uuid,90::smallint)
) scored(id, score);
insert into posting_status (posting_id, status) values
  ('00000000-0000-0000-0000-000000008007','seen'),
  ('00000000-0000-0000-0000-000000008008','worth_checking'),
  ('00000000-0000-0000-0000-000000008009','seen'),
  ('00000000-0000-0000-0000-000000008010','seen');

select is(
  (select array_agg(posting_id order by ordinality) from public.list_jobs() with ordinality),
  array['00000000-0000-0000-0000-000000008001','00000000-0000-0000-0000-000000008002','00000000-0000-0000-0000-000000008004','00000000-0000-0000-0000-000000008003','00000000-0000-0000-0000-000000008005']::uuid[],
  'defaults return five best-fit unseen jobs with no score floor');
select is((select count(*) from public.list_jobs(false,10)), 6::bigint,
  'a larger max includes low and unscored unseen jobs');
select is(
  (select array_agg(posting_id order by ordinality) from public.list_jobs(true,10) with ordinality),
  array['00000000-0000-0000-0000-000000008007','00000000-0000-0000-0000-000000008008','00000000-0000-0000-0000-000000008009','00000000-0000-0000-0000-000000008010']::uuid[],
  'seen history orders by score, coalesced date, and id across the visit boundary');
select is((select count(*) from public.list_jobs(null,10)), 10::bigint,
  'seen null returns unseen and handled eligible jobs');
select ok(exists(select 1 from public.list_jobs(false,10)
  where posting_id = '00000000-0000-0000-0000-000000008006' and posted_at is null),
  'unknown posted_at jobs remain retrievable');
select is((select array_agg(posting_id order by posting_id) from public.list_jobs(false,10,null,'TEL AVIV')),
  array['00000000-0000-0000-0000-000000008001','00000000-0000-0000-0000-000000008006']::uuid[],
  'location is a case-insensitive literal substring');
select is((select posting_id from public.list_jobs(false,10,null,'%')),
  '00000000-0000-0000-0000-000000008004'::uuid,
  'location treats SQL wildcard characters literally');
select is((select array_agg(posting_id order by posting_id) from public.list_jobs(false,10,null,null,'SENIOR')),
  array['00000000-0000-0000-0000-000000008001','00000000-0000-0000-0000-000000008003']::uuid[],
  'seniority matches the extracted projection case-insensitively');
select is((select posting_id from public.list_jobs(false,10,null,null,null,'platform')),
  '00000000-0000-0000-0000-000000008001'::uuid, 'query matches title');
select is((select posting_id from public.list_jobs(false,10,null,null,null,'REMOTECO')),
  '00000000-0000-0000-0000-000000008002'::uuid, 'query matches company');
select is((select posting_id from public.list_jobs(false,10,null,null,null,'torch')),
  '00000000-0000-0000-0000-000000008003'::uuid, 'query matches a stack item');
select is((select posting_id from public.list_jobs(false,10,75,'remote','staff','rust')),
  '00000000-0000-0000-0000-000000008004'::uuid, 'filters combine with AND semantics');
select is((select count(*) from public.list_jobs(null,1)), 1::bigint, 'max bounds results');
select is((select count(*) from public.list_jobs(false,10,80)), 2::bigint,
  'minimum score is inclusive and excludes null scores');
select ok(exists(select 1 from public.list_jobs(true,10)
  where posting_id = '00000000-0000-0000-0000-000000008009'),
  'seen history remains retrievable after a later visit');
select ok(pg_temp.throws_sqlstate($$select public.list_jobs(false,0)$$,'22023'),
  'max below one is rejected');
select ok(pg_temp.throws_sqlstate($$select public.list_jobs(false,1001)$$,'22023'),
  'max above 1000 is rejected');
select ok(pg_temp.throws_sqlstate($$select public.list_jobs(false,5,-1)$$,'22023'),
  'negative minimum score is rejected');
select ok(pg_temp.throws_sqlstate($$select public.list_jobs(false,5,101)$$,'22023'),
  'minimum score above 100 is rejected');
select ok(has_function_privilege('anon','public.list_jobs(boolean,integer,integer,text,text,text)','execute')
  and has_function_privilege('authenticated','public.list_jobs(boolean,integer,integer,text,text,text)','execute')
  and has_function_privilege('service_role','public.list_jobs(boolean,integer,integer,text,text,text)','execute'),
  'named API roles can execute list_jobs');
select ok(not exists(
  select 1 from pg_catalog.pg_proc p
  join pg_catalog.pg_namespace n on n.oid = p.pronamespace
  cross join lateral pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
  where n.nspname='public' and p.proname='list_jobs' and a.grantee=0 and a.privilege_type='EXECUTE'),
  'PUBLIC has no execute privilege');
select is(
  (select array_agg(key order by key) from
     (select * from public.list_jobs() limit 1) row_value
   cross join lateral jsonb_object_keys(to_jsonb(row_value)) key),
  array['apply_url','brain','company','external_id','labels','location','posted_at','posting_id','raw_jd','reasons','remote','salary','score','scored_at','seniority','source','stack','status','status_reason','status_updated_at','title','url']::text[],
  'return shape matches the legacy professional projection');

select * from finish();
rollback;
