-- Synthetic data only. Executed exclusively by db.mjs after --local reset.
insert into public.postings (id, source, external_id, url, title, company, location, remote, work_mode, work_mode_source, seniority, stack, raw_jd, liveness)
select ('12000000-0000-4000-8000-' || lpad(n::text,12,'0'))::uuid,
  (array['fixture','fixture-b','fixture-c'])[n], 'p12-' || n, 'https://example.test/jobs/' || n,
  (array['Frontend Engineer','Platform Engineer','UI Engineer'])[n],
  'Synthetic P12 Studio ' || n, 'Tel Aviv, Israel', false, 'on-site', 'structured', 'Junior',
  array['TypeScript','React'], 'Synthetic local-only job description for testing the real drawer and database routes.', '{"alive":true}'::jsonb
from generate_series(1,3) n;

insert into public.posting_scores (posting_id, score, reasons, labels, brain, model, scorer_version, posting_sha256, profile_sha256, history_sha256, score_payload)
select id, 90, '[]'::jsonb,
  '{"role_type":"frontend","seniority_match":"positive","remote_ok":"positive","red_flag_count":0}'::jsonb,
  'fixture', 'synthetic', 'p12', repeat('0',64), repeat('0',64), repeat('0',64),
  '{"employer_type":"direct","seniority_real":true,"fit_score":90,"fit_tier":"strong","recommendation":"apply","reasons":[],"fit_line":"Synthetic local test role","fit_line_evidence_ids":[],"luna_status":"ok"}'::jsonb
from public.postings;

insert into public.posting_status (posting_id, status)
select id, (array['new','seen','applied'])[row_number() over (order by id)] from public.postings;

insert into public.posting_geo (posting_id, lat, lng, precision, source)
select id, 32.0853, 34.7818, 'city', 'Synthetic local centroid' from public.postings;

do $$ begin
  if (select count(*) from public.postings) <> 3 or
     (select count(*) from public.posting_scores) <> 3 or
     (select count(*) from public.posting_status) <> 3 or
     (select count(*) from public.posting_geo) <> 3 then
    raise exception 'Synthetic seed population mismatch';
  end if;
end $$;
